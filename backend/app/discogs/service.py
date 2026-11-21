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
from app.spotify.normalize import LibraryAlbum, artist_key, clean_title, fold

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


def score_result(album: LibraryAlbum, result: dict) -> tuple[float, float, float]:
    """(score global, score artiste, score titre), chacun sur 100."""
    r_artist, r_title = split_discogs_title(result.get("title", ""))
    r_artist = _ANV.sub("", _DISAMBIGUATION.sub("", r_artist))
    a_key, r_key = artist_key(album.primary_artist), artist_key(r_artist)
    artist_score = max(fuzz.token_sort_ratio(a_key, r_key), fuzz.partial_ratio(a_key, r_key))
    title_score = fuzz.token_sort_ratio(fold(album.title_clean), fold(clean_title(r_title)))
    return (artist_score + title_score) / 2, artist_score, title_score


def best_result(album: LibraryAlbum, results: list[dict], threshold: float) -> tuple[dict, float] | None:
    best: tuple[dict, float] | None = None
    for res in results:
        total, a, t = score_result(album, res)
        if total >= threshold and min(a, t) >= threshold - 15 and (best is None or total > best[1]):
            best = (res, total)
    return best


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
    """1) fiche "master" (regroupe toutes les éditions) ; 2) à défaut, une édition vinyle."""
    base = {"artist": album.primary_artist, "release_title": album.title_clean}
    for params in ({"type": "master"}, {"type": "release", "format": "Vinyl"}):
        results = await client.search(**base, **params)
        hit = best_result(album, results, threshold)
        if hit:
            return match_from_result(*hit)
    return DiscogsMatch(found=False)


# --------------------------------------------------------------------------- cache persistant


class DiscogsStore:
    """Correspondances par `match_key`, partagées entre utilisateurs, sauvegardées en JSON si un chemin est donné."""

    def __init__(self, path: str | None = None):
        self.path = path
        self.matches: dict[str, DiscogsMatch] = {}
        self.offers: dict[str, AlbumOffers] = {}
        if path and os.path.exists(path):
            try:
                with open(path, encoding="utf-8") as f:
                    raw = json.load(f)
                self.matches = {k: DiscogsMatch.model_validate(v) for k, v in raw.items()}
            except (OSError, ValueError) as exc:
                log.warning("Cache Discogs illisible (%s), on repart de zéro", exc)

    def get(self, key: str) -> DiscogsMatch | None:
        return self.matches.get(key)

    def needs_lookup(self, key: str) -> bool:
        m = self.matches.get(key)
        return m is None or (not m.found and time.time() - m.matched_at > NOT_FOUND_RETRY_SECONDS)

    def put(self, key: str, match: DiscogsMatch) -> None:
        self.matches[key] = match

    def save(self) -> None:
        if not self.path:
            return
        tmp = f"{self.path}.tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump({k: v.model_dump() for k, v in self.matches.items()}, f, ensure_ascii=False)
        os.replace(tmp, self.path)  # écriture atomique


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
    client: DiscogsClient, store: DiscogsStore, job: EnrichJob, albums: list[LibraryAlbum], threshold: float
) -> None:
    todo = [a for a in albums if store.needs_lookup(a.match_key)]
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
                store.save()
    finally:
        store.save()
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
