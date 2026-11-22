"""Recherche d'annonces vinyles via Apify : filtrage, cache (mémoire + base) et analyse en lot."""

import asyncio
import logging
import re
import time
from dataclasses import asdict, dataclass

from rapidfuzz import fuzz

from app.offers.apify import ApifyClient, ApifyError
from app.geo import Geocoder
from app.offers.models import AlbumListings, Listing, PlatformSearch, RejectedListing
from app.offers.scoring import score_listings
from app.user_settings import UserSettings
from app.discogs.models import AlbumOffers
from app.offers.platforms import PLATFORMS, format_hint
from app.spotify.normalize import LibraryAlbum, artist_key, fold, strip_nickname

log = logging.getLogger("waxmatch.offers")

# Coût réel observé : ~0,001-0,002 $ par recherche (20 annonces max) ; on garde une marge.
COST_PER_SEARCH = {"vinted": 0.003, "leboncoin": 0.003, "2ememain": 0.003, "discogs": 0.0}

_EXCLUDED = re.compile(
    r"\b(cd|cds|compact disc|cassette|cassettes|k7|dvd|blu ray|poster|affiche|t shirt|tshirt|tee shirt|"
    r"sweat|livre|magazine|pochette vide|pochette seule|sans disque|sans vinyle|partition|badge|mug|cadre)\b"
)


# --------------------------------------------------------------------------- filtrage


# 2ememain : la catégorie est dans l'URL (/v/cd-dvd/cd-jazz-blues/…) et les publicités ont un
# identifiant en "a…" (/a169078540-…) au lieu de "m…".
_2EMEMAIN_CD = re.compile(r"2ememain\.be/v/[^/]+/(?:cd|dvd)[-/]")
_2EMEMAIN_AD = re.compile(r"2ememain\.be/.*/a\d+-")
# Mots génériques d'une annonce, ignorés pour vérifier un album éponyme ("Bo Diddley" de Bo Diddley).
_GENERIC = set(
    "vinyle vinyles vinyl vinyls lp lps 33t 45t 33 45 tours tour rpm album disque disques plaat record records "
    "original originale pressage press persing edition reissue re neuf new mint tres bon etat used gebraucht "
    "occasion vintage collector rare stereo mono de du des la le les et the a and of by st s t self titled eponyme "
    "same lot uk us usa france fr be".split()
)


def judge(album: LibraryAlbum, listing: Listing, threshold: float = 85) -> tuple[bool, str, float]:
    """L'annonce correspond-elle à l'album, et est-ce bien un disque ? -> (gardée, raison, score)."""
    if _2EMEMAIN_AD.search(listing.url):
        return False, "publicité (annonce sponsorisée)", 0.0
    if _2EMEMAIN_CD.search(listing.url):
        return False, "objet exclu : catégorie CD/DVD", 0.0
    text = fold(listing.title)
    excluded = _EXCLUDED.search(text)
    if excluded:
        return False, f"objet exclu : « {excluded.group(1)} »", 0.0

    artist_score = 0.0
    for name in dict.fromkeys([*album.artists, album.primary_artist]):
        for variant in {name, strip_nickname(name)}:
            key = artist_key(variant)
            if key:
                artist_score = max(artist_score, fuzz.partial_ratio(key, text))
    if artist_score < threshold:
        return False, "artiste absent du titre", artist_score

    title = fold(album.title_clean)
    if len(title) < 4 or len(title.split()) == 1 and len(title) < 6:
        # Titre très court ("II", "21", "Mud") : on exige le mot exact, pas une ressemblance.
        title_score = 100.0 if re.search(rf"\b{re.escape(title)}\b", text) else 0.0
    else:
        title_score = fuzz.partial_ratio(title, text)
    if title_score < threshold:
        return False, "titre de l'album absent", title_score

    # Album éponyme : le titre est déjà couvert par le nom de l'artiste. On vérifie qu'il ne reste
    # pas un autre titre dans l'annonce ("Bo Diddley 'the London sessions'").
    if title == artist_key(album.primary_artist) or title == fold(album.primary_artist):
        leftover = [w for w in text.split() if w not in set(fold(album.primary_artist).split()) | _GENERIC
                    and not w.isdigit()]
        if len(leftover) > 1:
            return False, f"autre album de l'artiste (« {' '.join(leftover[:4])} »)", 0.0
    return True, "ok", round((artist_score + title_score) / 2, 1)


# Mot ajouté à la recherche. Sur 2ememain (annonces en français ET en néerlandais : « vinyl », « LP »,
# « plaat »), « vinyle » éliminait des annonces pertinentes : on cherche artiste + titre seuls,
# le filtre écarte ensuite CD, K7, etc.
QUERY_SUFFIX = {"vinted": " vinyle", "leboncoin": " vinyle", "2ememain": ""}


def build_query(album: LibraryAlbum, platform: str = "vinted") -> str:
    return f"{strip_nickname(album.primary_artist)} {album.title_clean}{QUERY_SUFFIX.get(platform, '')}"


# --------------------------------------------------------------------------- cache


class OffersStore:
    """Résultats de recherche par (plateforme, album). En base si un pool est fourni."""

    def __init__(self, pool=None):
        self.pool = pool
        self.searches: dict[tuple[str, str], PlatformSearch] = {}

    async def load(self) -> None:
        if self.pool is None:
            return
        rows = await self.pool.fetch("select platform, match_key, data from listing_searches")
        self.searches = {(r["platform"], r["match_key"]): PlatformSearch.model_validate(r["data"]) for r in rows}

    def get(self, platform: str, match_key: str, max_age_s: float) -> PlatformSearch | None:
        found = self.searches.get((platform, match_key))
        if found and time.time() - found.searched_at < max_age_s:
            return found
        return None

    def last_searched(self, match_key: str, platforms: list[str]) -> float | None:
        """Date de la plus ancienne des dernières recherches de cet album (None = jamais analysé)."""
        dates = [s.searched_at for p in platforms if (s := self.searches.get((p, match_key)))]
        return min(dates) if len(dates) == len(platforms) and dates else None

    async def put(self, match_key: str, search: PlatformSearch) -> None:
        self.searches[(search.platform, match_key)] = search
        if self.pool is not None:
            await self.pool.execute(
                """
                insert into listing_searches (platform, match_key, query, searched_at, raw_count, kept_count, data)
                values ($1, $2, $3, to_timestamp($4), $5, $6, $7)
                on conflict (platform, match_key) do update
                set query = excluded.query, searched_at = excluded.searched_at, raw_count = excluded.raw_count,
                    kept_count = excluded.kept_count, data = excluded.data
                """,
                search.platform,
                match_key,
                search.query,
                search.searched_at,
                search.raw_count,
                len(search.listings),
                search.model_dump(mode="json"),
            )


# --------------------------------------------------------------------------- recherche


async def search_platform(
    apify: ApifyClient,
    platform: str,
    album: LibraryAlbum,
    max_items: int,
    country: str = "BE",
    geocoder: Geocoder | None = None,
) -> PlatformSearch:
    config = PLATFORMS[platform]
    query = build_query(album, platform)
    search = PlatformSearch(platform=platform, query=query)
    try:
        items = await apify.run_actor(config.actor_id, config.build_input(query, max_items, country))
    except ApifyError as exc:
        search.error = str(exc)
        return search
    search.raw_count = len(items)
    seen: set[str] = set()
    for item in items:
        listing = config.parse(item)
        if listing is None or listing.external_id in seen:
            continue
        seen.add(listing.external_id)
        ok, reason, score = judge(album, listing)
        if ok:
            listing.match_score = score
            search.listings.append(listing)
        else:
            search.rejected.append(
                RejectedListing(platform=platform, title=listing.title, url=listing.url, reason=reason)
            )
    # Villes sans coordonnées (2ememain) : géocodage, pour calculer la distance de main propre.
    if geocoder is not None:
        for listing in search.listings:
            if listing.city and listing.latitude is None:
                found = await geocoder.geocode(listing.city, listing.country)
                if found:
                    listing.latitude, listing.longitude = found[0], found[1]
    return search


def discogs_listings(offers: AlbumOffers | None) -> list[Listing]:
    """Éditions vinyles en vente sur Discogs (API officielle : prix le plus bas par édition)."""
    if offers is None:
        return []
    result = []
    for o in offers.offers:
        if not o.lowest_price or o.num_for_sale <= 0:
            continue
        details = ", ".join(x for x in (o.format, o.country, o.released, o.label) if x)
        result.append(
            Listing(
                platform="discogs",
                external_id=str(o.release_id),
                title=f"{offers.match.title or 'Discogs'} — {details}" if details else (offers.match.title or "Discogs"),
                url=o.sell_url,  # page des annonces de cette édition
                price=o.lowest_price,
                currency=o.currency or "EUR",
                total_known=o.lowest_price,  # pas de frais acheteur sur Discogs
                photo_url=offers.match.cover_url,
                format_hint=format_hint(o.format or ""),
                shippable=True,
                stock=o.num_for_sale,
                match_score=100,
            )
        )
    return result


def build_album_listings(
    album: LibraryAlbum,
    searches: list[PlatformSearch],
    settings: UserSettings,
    discogs_reference: float | None,
    discogs_offers: AlbumOffers | None = None,
) -> AlbumListings:
    # Le filtre est réappliqué aux résultats en cache : toute amélioration du filtre vaut aussi
    # pour les recherches déjà faites (et payées), sans relancer Apify.
    cleaned: list[PlatformSearch] = []
    for search in searches:
        kept, rejected = [], list(search.rejected)
        for lst in search.listings:
            ok, reason, _ = judge(album, lst)
            if ok:
                kept.append(lst)
            else:
                rejected.append(RejectedListing(platform=lst.platform, title=lst.title, url=lst.url, reason=reason))
        cleaned.append(search.model_copy(update={"listings": kept, "rejected": rejected}))
    searches = cleaned
    raw = [lst for s in searches for lst in s.listings]
    if "discogs" in settings.platforms:
        raw += discogs_listings(discogs_offers)
    suggestions = discogs_offers.price_suggestions if discogs_offers else None
    ranked, unreachable = score_listings(raw, settings, discogs_reference, price_suggestions=suggestions)
    return AlbumListings(
        spotify_id=album.spotify_id,
        artist=album.primary_artist,
        title=album.title_clean,
        discogs_reference=discogs_reference,
        discogs_by_condition=suggestions or {},
        listings=ranked,
        unreachable=unreachable,
        searches=searches,
    )


async def album_listings(
    apify: ApifyClient,
    store: OffersStore,
    album: LibraryAlbum,
    settings: UserSettings,
    max_items: int,
    cache_hours: float,
    refresh: bool = False,
    geocoder: Geocoder | None = None,
    discogs_reference: float | None = None,
    discogs_offers: AlbumOffers | None = None,
) -> AlbumListings:
    async def one(platform: str) -> PlatformSearch:
        cached = None if refresh else store.get(platform, album.match_key, cache_hours * 3600)
        if cached:
            return cached.model_copy(update={"from_cache": True})
        result = await search_platform(apify, platform, album, max_items, settings.country, geocoder)
        if result.error is None:  # on ne met pas les échecs en cache
            await store.put(album.match_key, result)
        return result

    searches = await asyncio.gather(*(one(p) for p in settings.apify_platforms))
    return build_album_listings(album, list(searches), settings, discogs_reference, discogs_offers)


# --------------------------------------------------------------------------- analyse en lot


@dataclass
class ScanJob:
    running: bool = False
    phase: str = "en attente"
    total: int = 0
    done: int = 0
    albums_with_offers: int = 0
    listings_found: int = 0
    errors: int = 0
    last_error: str | None = None
    estimated_cost_usd: float = 0.0
    started_at: float | None = None
    finished_at: float | None = None

    def status(self) -> dict:
        data = asdict(self)
        data["remaining"] = max(self.total - self.done, 0)
        return data


async def run_scan(
    apify: ApifyClient,
    store: OffersStore,
    job: ScanJob,
    albums: list[LibraryAlbum],
    settings: UserSettings,
    max_items: int,
    cache_hours: float,
    concurrency: int = 1,
    geocoder: Geocoder | None = None,
) -> None:
    job.running, job.phase, job.started_at, job.total = True, "recherche des annonces", time.time(), len(albums)
    job.estimated_cost_usd = round(len(albums) * sum(COST_PER_SEARCH[p] for p in settings.platforms), 2)
    # 1 album à la fois par défaut (= 2 runs Apify, un par plateforme) : un compte gratuit limite
    # la mémoire totale des runs simultanés.
    sem = asyncio.Semaphore(concurrency)

    async def one(album: LibraryAlbum) -> None:
        async with sem:
            try:
                result = await album_listings(
                    apify, store, album, settings, max_items, cache_hours, geocoder=geocoder
                )
                job.listings_found += len(result.listings)
                job.albums_with_offers += bool(result.listings)
                failed = [s.error for s in result.searches if s.error]
                if failed:
                    job.errors += 1
                    job.last_error = failed[0]
            except Exception as exc:  # noqa: BLE001 - un album en échec n'arrête pas le lot
                job.errors += 1
                job.last_error = str(exc)[:200]
            job.done += 1

    try:
        await asyncio.gather(*(one(a) for a in albums))
    finally:
        job.running, job.phase, job.finished_at = False, "terminé", time.time()
