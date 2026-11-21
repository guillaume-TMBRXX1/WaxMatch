"""Correspondance albums Spotify ↔ Discogs, cache persistant et enrichissement en tâche de fond."""

import asyncio
import json
import logging
import os
import re
import time
from dataclasses import asdict, dataclass, field

import httpx
from rapidfuzz import fuzz

from app.discogs.client import DiscogsClient, DiscogsError
from app.discogs.models import AlbumOffers, DiscogsMatch, VinylOffer
from app.spotify.normalize import LibraryAlbum, artist_key, clean_title, fold, strip_nickname

log = logging.getLogger("waxmatch.discogs")

SITE = "https://www.discogs.com"
NOT_FOUND_RETRY_SECONDS = 7 * 24 * 3600
OFFERS_TTL_SECONDS = 6 * 3600

_DISAMBIGUATION = re.compile(r"\s*\(\d+\)")  # "Prince (2)" -> "Prince"
_ANV = re.compile(r"\*")  # "Artiste*" : variante de nom chez Discogs


# --------------------------------------------------------------------------- correspondance


def split_discogs_title(title: str) -> tuple[str, str]:
    """Les résultats Discogs sont intitulés "Artiste - Titre"."""
    artist, sep, album = title.partition(" - ")
    return (artist, album) if sep else ("", title)


VARIOUS = {"various", "various artists", "divers"}


def _artist_score(album: LibraryAlbum, discogs_artist: str) -> float:
    """Meilleur score parmi les artistes de l'album (gère duos, collaborations et surnoms)."""
    r_key = artist_key(_ANV.sub("", _DISAMBIGUATION.sub("", discogs_artist)))
    best = 0.0
    for name in dict.fromkeys([*album.artists, album.primary_artist]):
        for variant in {name, strip_nickname(name)}:
            a_key = artist_key(variant)
            if a_key and r_key:
                best = max(best, fuzz.token_sort_ratio(a_key, r_key), fuzz.partial_ratio(a_key, r_key))
    return best


def score_result(album: LibraryAlbum, result: dict) -> tuple[float, float, float]:
    """(score global, score artiste, score titre), chacun sur 100."""
    r_artist, r_title = split_discogs_title(result.get("title", ""))
    title_score = fuzz.token_sort_ratio(fold(album.title_clean), fold(clean_title(r_title)))
    if fold(r_artist) in VARIOUS:
        # Compilation ou revue collective (ex. "Daptone Super Soul Revue") : on se fie au titre,
        # à condition qu'il soit long et quasi identique, pour éviter les "Greatest Hits".
        long_title = len(fold(album.title_clean).split()) >= 3
        artist_score = 100.0 if long_title and title_score >= 95 else 0.0
    else:
        artist_score = _artist_score(album, r_artist)
    return (artist_score + title_score) / 2, artist_score, title_score


def best_result(album: LibraryAlbum, results: list[dict], threshold: float) -> tuple[dict, float] | None:
    best: tuple[dict, float] | None = None
    for res in results:
        total, a, t = score_result(album, res)
        if total >= threshold and min(a, t) >= threshold - 15 and (best is None or total > best[1]):
            best = (res, total)
    return best


def search_plans(album: LibraryAlbum) -> list[dict]:
    """Recherches successives, de la plus précise à la plus large ; on s'arrête au premier résultat fiable."""
    artist = strip_nickname(album.primary_artist)
    title = album.title_clean
    plans: list[dict] = [
        {"type": "master", "artist": artist, "release_title": title},
        {"type": "release", "format": "Vinyl", "artist": artist, "release_title": title},
        # Recherche libre sans accents ni ponctuation ("DeBÍ TiRAR MáS FOToS" -> "debi tirar mas fotos")
        {"type": "master", "q": f"{fold(artist)} {fold(title)}"},
    ]
    if len(fold(title).split()) >= 3:  # titre seul : compilations, collaborations mal attribuées
        plans.append({"type": "master", "q": fold(title)})
    return plans


def match_from_result(result: dict, score: float) -> DiscogsMatch:
    kind = "master" if result.get("type") == "master" else "release"
    rid = int(result["id"])
    year = str(result.get("year") or "")
    community = result.get("community") or {}
    return DiscogsMatch(
        found=True,
        kind=kind,
        id=rid,
        title=result.get("title"),
        year=int(year) if year.isdigit() else None,
        genres=result.get("genre") or [],
        styles=result.get("style") or [],
        cover_url=result.get("cover_image") or result.get("thumb") or None,
        url=f"{SITE}{result['uri']}" if result.get("uri") else None,
        marketplace_url=(
            f"{SITE}/sell/list?master_id={rid}&format=Vinyl" if kind == "master" else f"{SITE}/sell/release/{rid}"
        ),
        want=community.get("want"),
        have=community.get("have"),
        score=round(score, 1),
    )


async def find_match(client: DiscogsClient, album: LibraryAlbum, threshold: float) -> DiscogsMatch:
    for params in search_plans(album):
        results = await client.search(**params)
        hit = best_result(album, results, threshold)
        if hit:
            return match_from_result(*hit)
    return DiscogsMatch(found=False)


# --------------------------------------------------------------------------- cache persistant


class DiscogsStore:
    """Correspondances par `match_key`, partagées entre utilisateurs.

    Toujours gardées en mémoire pour des lectures instantanées, et persistées :
    - en base PostgreSQL si un pool est fourni (le fichier JSON éventuel est alors importé une fois) ;
    - sinon dans un fichier JSON si un chemin est donné.
    """

    def __init__(self, path: str | None = None, pool=None):
        self.path = path or None
        self.pool = pool
        self.matches: dict[str, DiscogsMatch] = {}
        self.offers: dict[str, AlbumOffers] = {}
        self._dirty: set[str] = set()

    async def load(self) -> None:
        if self.pool is not None:
            rows = await self.pool.fetch("select match_key, data from discogs_matches")
            self.matches = {r["match_key"]: DiscogsMatch.model_validate(r["data"]) for r in rows}
            rows = await self.pool.fetch("select match_key, data from discogs_offers")
            self.offers = {r["match_key"]: AlbumOffers.model_validate(r["data"]) for r in rows}
        if self.path and os.path.exists(self.path):
            try:
                with open(self.path, encoding="utf-8") as f:
                    raw = json.load(f)
            except (OSError, ValueError) as exc:
                log.warning("Cache Discogs illisible (%s), ignoré", exc)
                raw = {}
            for key, value in raw.items():
                if key not in self.matches:
                    self.matches[key] = DiscogsMatch.model_validate(value)
                    if self.pool is not None:
                        self._dirty.add(key)  # import du fichier vers la base
            if self._dirty:
                log.info("Import de %d correspondances Discogs du fichier vers la base", len(self._dirty))
                await self.save()

    def get(self, key: str) -> DiscogsMatch | None:
        return self.matches.get(key)

    def needs_lookup(self, key: str, retry_not_found: bool = False) -> bool:
        m = self.matches.get(key)
        if m is None:
            return True
        return not m.found and (retry_not_found or time.time() - m.matched_at > NOT_FOUND_RETRY_SECONDS)

    def put(self, key: str, match: DiscogsMatch) -> None:
        self.matches[key] = match
        self._dirty.add(key)

    async def save(self) -> None:
        if self.pool is not None:
            keys, self._dirty = list(self._dirty), set()
            if keys:
                await self.pool.executemany(
                    """
                    insert into discogs_matches (match_key, found, data, matched_at)
                    values ($1, $2, $3, to_timestamp($4))
                    on conflict (match_key) do update
                    set found = excluded.found, data = excluded.data, matched_at = excluded.matched_at
                    """,
                    [(k, self.matches[k].found, self.matches[k].model_dump(mode="json"), self.matches[k].matched_at)
                     for k in keys],
                )
            return
        self._dirty.clear()
        if self.path:
            tmp = f"{self.path}.tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump({k: v.model_dump() for k, v in self.matches.items()}, f, ensure_ascii=False)
            os.replace(tmp, self.path)  # écriture atomique

    def get_offers(self, key: str) -> AlbumOffers | None:
        return self.offers.get(key)

    async def put_offers(self, key: str, offers: AlbumOffers) -> None:
        self.offers[key] = offers
        if self.pool is not None:
            await self.pool.execute(
                """
                insert into discogs_offers (match_key, data, checked_at) values ($1, $2, to_timestamp($3))
                on conflict (match_key) do update set data = excluded.data, checked_at = excluded.checked_at
                """,
                key,
                offers.model_dump(mode="json"),
                offers.checked_at,
            )


def apply_match(album: LibraryAlbum, match: DiscogsMatch | None) -> LibraryAlbum:
    if not match:
        return album
    update: dict = {"discogs": match}
    if match.found:
        update["genres"] = album.genres or match.genres
        update["styles"] = match.styles
    return album.model_copy(update=update)


# --------------------------------------------------------------------------- enrichissement en tâche de fond


@dataclass
class EnrichJob:
    running: bool = False
    phase: str = "en attente"
    total: int = 0
    done: int = 0
    matched: int = 0
    not_found: int = 0
    errors: int = 0
    already_known: int = 0
    started_at: float | None = None
    finished_at: float | None = None
    last_error: str | None = None
    seconds_per_album: float = field(default=2.2, repr=False)

    def status(self) -> dict:
        data = asdict(self)
        data.pop("seconds_per_album")
        remaining = max(self.total - self.done, 0)
        data["remaining"] = remaining
        data["eta_minutes"] = round(remaining * self.seconds_per_album / 60, 1) if self.running else 0
        return data


async def run_enrichment(
    client: DiscogsClient,
    store: DiscogsStore,
    job: EnrichJob,
    albums: list[LibraryAlbum],
    threshold: float,
    retry_not_found: bool = False,
) -> None:
    todo = [a for a in albums if store.needs_lookup(a.match_key, retry_not_found)]
    job.__init__()  # remise à zéro
    job.running, job.started_at, job.phase = True, time.time(), "recherche Discogs"

    job.total, job.already_known = len(todo), len(albums) - len(todo)
    try:
        for i, album in enumerate(todo, 1):
            try:
                match = await find_match(client, album, threshold)
                store.put(album.match_key, match)
                job.matched += match.found
                job.not_found += not match.found
            except (DiscogsError, httpx.HTTPError, OSError) as exc:  # une erreur sur un album n'arrête pas les autres
                job.errors += 1
                job.last_error = str(exc)[:200]
            job.done = i
            job.seconds_per_album = (time.time() - job.started_at) / i
            if i % 10 == 0:
                await store.save()
    finally:
        await store.save()
        job.running, job.finished_at, job.phase = False, time.time(), "terminé"


# --------------------------------------------------------------------------- offres vinyles


def _offer(version: dict, stats: dict | None) -> VinylOffer:
    rid = int(version["id"])
    price = (stats or {}).get("lowest_price") or {}
    return VinylOffer(
        release_id=rid,
        title=version.get("title"),
        format=version.get("format"),
        label=version.get("label"),
        catno=version.get("catno"),
        country=version.get("country"),
        released=str(version.get("released") or "") or None,
        num_for_sale=int((stats or {}).get("num_for_sale") or 0),
        lowest_price=price.get("value"),
        currency=price.get("currency"),
        url=f"{SITE}/release/{rid}",
        sell_url=f"{SITE}/sell/release/{rid}",
    )


async def album_offers(client: DiscogsClient, match: DiscogsMatch, max_versions: int = 6) -> AlbumOffers:
    """Prix des éditions vinyles. Pour un master, on interroge les éditions les plus répandues."""
    if not match.found or match.id is None:
        return AlbumOffers(match=match)

    if match.kind == "master":
        versions = await client.master_vinyl_versions(match.id, limit=50)
        # Les éditions les plus présentes dans les collections sont aussi les plus souvent en vente.
        versions.sort(
            key=lambda v: ((v.get("stats") or {}).get("community") or {}).get("in_collection") or 0, reverse=True
        )
        versions = versions[:max_versions]
    else:
        versions = [{"id": match.id, "title": match.title}]

    stats = await asyncio.gather(*(client.marketplace_stats(int(v["id"])) for v in versions))
    offers = [_offer(v, s) for v, s in zip(versions, stats)]
    offers.sort(key=lambda o: (o.lowest_price is None, o.lowest_price or 0))
    priced = [o for o in offers if o.lowest_price is not None]
    return AlbumOffers(
        match=match,
        best_price=priced[0].lowest_price if priced else None,
        currency=priced[0].currency if priced else None,
        total_for_sale=sum(o.num_for_sale for o in offers),
        versions_checked=len(offers),
        offers=offers,
    )
