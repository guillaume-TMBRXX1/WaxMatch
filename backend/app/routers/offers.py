import asyncio
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request

from app.deps import get_apify, get_spotify
from app.offers.apify import ApifyClient
from app.offers.models import AlbumListings
from app.offers.platforms import PLATFORMS
from app.offers.service import COST_PER_SEARCH, ScanJob, album_listings, run_scan
from app.routers.library import load_library
from app.spotify.client import SpotifyClient

router = APIRouter(prefix="/offers", tags=["offers"])

PlatformName = Literal["vinted", "leboncoin"]


def _platforms(values: list[PlatformName] | None) -> list[str]:
    return list(dict.fromkeys(values or PLATFORMS.keys()))


@router.get("/albums/{spotify_id}", response_model=AlbumListings)
async def offers_for_album(
    spotify_id: str,
    request: Request,
    platforms: list[PlatformName] | None = Query(None, description="Par défaut : toutes"),
    refresh: bool = Query(False, description="Ignorer le cache et relancer la recherche (payant)"),
    spotify: SpotifyClient = Depends(get_spotify),
    apify: ApifyClient = Depends(get_apify),
):
    """Annonces Vinted / Leboncoin pour un album (cache 24 h ; une recherche coûte ~0,02-0,04 $)."""
    albums = await load_library(request, spotify, refresh=False)
    album = next((a for a in albums if spotify_id in (a.spotify_id, *a.duplicates)), None)
    if album is None:
        raise HTTPException(status_code=404, detail="Album absent de ta bibliothèque Spotify")
    settings = request.app.state.settings
    return await album_listings(
        apify,
        request.app.state.offers_store,
        album,
        _platforms(platforms),
        settings.apify_max_items,
        settings.offers_cache_hours,
        refresh,
    )


@router.post("/scan")
async def start_scan(
    request: Request,
    limit: int = Query(10, ge=1, le=100, description="Nombre d'albums à analyser (les plus récemment ajoutés)"),
    platforms: list[PlatformName] | None = Query(None),
    spotify: SpotifyClient = Depends(get_spotify),
    apify: ApifyClient = Depends(get_apify),
):
    """Analyse en arrière-plan les albums récents sans résultat en cache. Suivi : GET /offers/scan/status."""
    state = request.app.state
    job: ScanJob = state.offers_job
    if job.running:
        return job.status()
    settings = state.settings
    chosen = _platforms(platforms)
    job.__init__()
    job.running, job.phase = True, "préparation"

    async def prepare_then_scan() -> None:
        try:
            albums = await load_library(request, spotify, refresh=False)
        except Exception as exc:  # noqa: BLE001
            job.running, job.phase, job.last_error = False, "erreur", str(exc)[:200]
            return
        store = state.offers_store
        max_age = settings.offers_cache_hours * 3600
        todo = [
            a
            for a in sorted(albums, key=lambda a: a.added_at.timestamp() if a.added_at else 0, reverse=True)
            if a.album_type != "single" and any(store.get(p, a.match_key, max_age) is None for p in chosen)
        ][:limit]
        await run_scan(apify, store, job, todo, chosen, settings.apify_max_items, settings.offers_cache_hours)

    state.offers_task = asyncio.create_task(prepare_then_scan())
    status = job.status()
    status["estimated_cost_usd"] = round(limit * sum(COST_PER_SEARCH[p] for p in chosen), 2)
    return status


@router.get("/scan/status")
async def scan_status(request: Request):
    return request.app.state.offers_job.status()


@router.get("/best")
async def best_offers(
    request: Request,
    limit: int = Query(50, ge=1, le=500),
    spotify: SpotifyClient = Depends(get_spotify),
):
    """Meilleure annonce connue (en cache) pour chaque album de ta bibliothèque, la moins chère d'abord."""
    albums = await load_library(request, spotify, refresh=False)
    store = request.app.state.offers_store
    rows = []
    for album in albums:
        listings = [
            lst
            for (platform, key), search in store.searches.items()
            if key == album.match_key
            for lst in search.listings
        ]
        priced = [lst for lst in listings if lst.total_known is not None]
        if not priced:
            continue
        best = min(priced, key=lambda lst: lst.total_known)
        rows.append(
            {
                "spotify_id": album.spotify_id,
                "artist": album.primary_artist,
                "title": album.title_clean,
                "cover_url": album.cover_url,
                "offers_count": len(listings),
                "best": best.model_dump(),
            }
        )
    rows.sort(key=lambda r: r["best"]["total_known"])
    return {"total": len(rows), "albums": rows[:limit]}
