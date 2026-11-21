"""Recherche d'annonces vinyles via Apify : filtrage, cache (mémoire + base) et analyse en lot."""

import asyncio
import logging
import re
import time
from dataclasses import asdict, dataclass

from rapidfuzz import fuzz

from app.offers.apify import ApifyClient, ApifyError
from app.offers.models import AlbumListings, Listing, PlatformSearch, RejectedListing
from app.offers.platforms import PLATFORMS
from app.spotify.normalize import LibraryAlbum, artist_key, fold, strip_nickname

log = logging.getLogger("waxmatch.offers")

# Coût moyen observé par recherche (20 résultats max), en dollars : sert à l'estimation affichée.
COST_PER_SEARCH = {"vinted": 0.02, "leboncoin": 0.04}

_EXCLUDED = re.compile(
    r"\b(cd|cds|compact disc|cassette|cassettes|k7|dvd|blu ray|poster|affiche|t shirt|tshirt|tee shirt|"
    r"sweat|livre|magazine|pochette vide|pochette seule|sans disque|sans vinyle|partition|badge|mug|cadre)\b"
)


# --------------------------------------------------------------------------- filtrage


def judge(album: LibraryAlbum, listing: Listing, threshold: float = 85) -> tuple[bool, str, float]:
    """L'annonce correspond-elle à l'album, et est-ce bien un disque ? -> (gardée, raison, score)."""
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
    return True, "ok", round((artist_score + title_score) / 2, 1)


def build_query(album: LibraryAlbum) -> str:
    return f"{strip_nickname(album.primary_artist)} {album.title_clean} vinyle"


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


async def search_platform(apify: ApifyClient, platform: str, album: LibraryAlbum, max_items: int) -> PlatformSearch:
    config = PLATFORMS[platform]
    query = build_query(album)
    search = PlatformSearch(platform=platform, query=query)
    try:
        items = await apify.run_actor(config.actor_id, config.build_input(query, max_items))
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
    return search


async def album_listings(
    apify: ApifyClient,
    store: OffersStore,
    album: LibraryAlbum,
    platforms: list[str],
    max_items: int,
    cache_hours: float,
    refresh: bool = False,
) -> AlbumListings:
    async def one(platform: str) -> PlatformSearch:
        cached = None if refresh else store.get(platform, album.match_key, cache_hours * 3600)
        if cached:
            return cached.model_copy(update={"from_cache": True})
        result = await search_platform(apify, platform, album, max_items)
        if result.error is None:  # on ne met pas les échecs en cache
            await store.put(album.match_key, result)
        return result

    searches = await asyncio.gather(*(one(p) for p in platforms))
    listings: list[Listing] = [lst for s in searches for lst in s.listings]
    listings.sort(key=lambda lst: (lst.total_known is None, lst.total_known or 0))
    return AlbumListings(
        spotify_id=album.spotify_id,
        artist=album.primary_artist,
        title=album.title_clean,
        listings=listings,
        searches=list(searches),
    )


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
    platforms: list[str],
    max_items: int,
    cache_hours: float,
) -> None:
    job.running, job.phase, job.started_at, job.total = True, "recherche des annonces", time.time(), len(albums)
    job.estimated_cost_usd = round(len(albums) * sum(COST_PER_SEARCH[p] for p in platforms), 2)
    sem = asyncio.Semaphore(3)  # 3 albums à la fois (chaque recherche Apify prend 20 à 60 s)

    async def one(album: LibraryAlbum) -> None:
        async with sem:
            try:
                result = await album_listings(apify, store, album, platforms, max_items, cache_hours)
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
