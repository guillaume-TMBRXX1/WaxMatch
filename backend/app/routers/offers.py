import asyncio
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request

from app.deps import get_apify, get_spotify
from app.offers.apify import ApifyClient
from app.offers.models import AlbumListings
from app.offers.service import COST_PER_SEARCH, ScanJob, album_listings, build_album_listings, run_scan
from app.routers.library import load_library
from app.spotify.client import SpotifyClient
from app.spotify.normalize import LibraryAlbum
from app.user_settings import PlatformName, UserSettings

router = APIRouter(prefix="/offers", tags=["offers"])


async def user_settings(request: Request, spotify: SpotifyClient, platforms: list[str] | None) -> UserSettings:
    settings = await request.app.state.settings_store.get(spotify.tokens.spotify_user_id or spotify.session_id)
    if platforms:
        settings = settings.model_copy(update={"platforms": list(dict.fromkeys(platforms))})
    return settings


async def discogs_reference(request: Request, album: LibraryAlbum, fetch: bool) -> float | None:
    """Prix vinyle le plus bas sur Discogs : cache, ou interrogation si `fetch` et Discogs configuré."""
    store = request.app.state.discogs_store
    cached = store.get_offers(album.match_key)
    if cached is not None or not fetch:
        return cached.best_price if cached else None
    match = store.get(album.match_key)
    if not (match and match.found and request.app.state.settings.discogs_token):
        return None
    from app.deps import get_discogs
    from app.discogs.service import album_offers

    try:
        offers = await album_offers(get_discogs(request, request.app.state.settings, request.app.state.http), match)
    except Exception:  # noqa: BLE001 - la référence Discogs est un bonus, pas un prérequis
        return None
    await store.put_offers(album.match_key, offers)
    return offers.best_price


@router.get("/albums/{spotify_id}", response_model=AlbumListings)
async def offers_for_album(
    spotify_id: str,
    request: Request,
    platforms: list[PlatformName] | None = Query(None, description="Par défaut : celles de tes réglages"),
    refresh: bool = Query(False, description="Ignorer le cache et relancer la recherche"),
    spotify: SpotifyClient = Depends(get_spotify),
    apify: ApifyClient = Depends(get_apify),
):
    """Annonces classées par score pour un album (cache 24 h ; ~0,002 $ par recherche et par plateforme)."""
    albums = await load_library(request, spotify, refresh=False)
    album = next((a for a in albums if spotify_id in (a.spotify_id, *a.duplicates)), None)
    if album is None:
        raise HTTPException(status_code=404, detail="Album absent de ta bibliothèque Spotify")
    state = request.app.state
    settings = await user_settings(request, spotify, platforms)
    reference = await discogs_reference(request, album, fetch=True)
    return await album_listings(
        apify,
        state.offers_store,
        album,
        settings,
        state.settings.apify_max_items,
        state.settings.offers_cache_hours,
        refresh,
        geocoder=state.geocoder,
        discogs_reference=reference,
    )


@router.post("/scan")
async def start_scan(
    request: Request,
    limit: int = Query(10, ge=1, le=800, description="Nombre d'albums à analyser (les plus récemment ajoutés)"),
    platforms: list[PlatformName] | None = Query(None, description="Par défaut : celles de tes réglages"),
    spotify: SpotifyClient = Depends(get_spotify),
    apify: ApifyClient = Depends(get_apify),
):
    """Analyse en arrière-plan les albums récents sans résultat en cache. Suivi : GET /offers/scan/status."""
    state = request.app.state
    job: ScanJob = state.offers_job
    if job.running:
        return job.status()
    config = state.settings
    settings = await user_settings(request, spotify, platforms)
    job.__init__()
    job.running, job.phase = True, "préparation"

    async def prepare_then_scan() -> None:
        try:
            albums = await load_library(request, spotify, refresh=False)
        except Exception as exc:  # noqa: BLE001
            job.running, job.phase, job.last_error = False, "erreur", str(exc)[:200]
            return
        store = state.offers_store
        max_age = config.offers_cache_hours * 3600
        todo = [
            a
            for a in sorted(albums, key=lambda a: a.added_at.timestamp() if a.added_at else 0, reverse=True)
            if a.album_type != "single" and any(store.get(p, a.match_key, max_age) is None for p in settings.platforms)
        ][:limit]
        await run_scan(
            apify, store, job, todo, settings, config.apify_max_items, config.offers_cache_hours,
            config.apify_concurrency, state.geocoder,
        )

    state.offers_task = asyncio.create_task(prepare_then_scan())
    status = job.status()
    status["estimated_cost_usd"] = round(limit * sum(COST_PER_SEARCH[p] for p in settings.platforms), 2)
    return status


@router.get("/scan/status")
async def scan_status(request: Request):
    return request.app.state.offers_job.status()


@router.get("/best")
async def best_offers(
    request: Request,
    sort: Literal["score", "price"] = "score",
    limit: int = Query(50, ge=1, le=500),
    spotify: SpotifyClient = Depends(get_spotify),
):
    """Meilleure annonce connue (en cache, aucun coût) pour chaque album de ta bibliothèque."""
    albums = await load_library(request, spotify, refresh=False)
    settings = await user_settings(request, spotify, None)
    store = request.app.state.offers_store
    by_key: dict[str, list] = {}
    for (platform, key), search in store.searches.items():
        if platform in settings.platforms:
            by_key.setdefault(key, []).append(search)
    rows = []
    for album in albums:
        searches = by_key.get(album.match_key)
        if not searches:
            continue
        result = build_album_listings(album, searches, settings, await discogs_reference(request, album, fetch=False))
        if not result.listings:
            continue
        best = result.listings[0]
        rows.append(
            {
                "spotify_id": album.spotify_id,
                "artist": album.primary_artist,
                "title": album.title_clean,
                "cover_url": album.cover_url,
                "offers_count": len(result.listings),
                "discogs_reference": result.discogs_reference,
                "best": best.model_dump(),
            }
        )
    if sort == "price":
        rows.sort(key=lambda r: r["best"]["delivered_total"])
    else:
        rows.sort(key=lambda r: r["best"]["score"], reverse=True)
    return {"total": len(rows), "sort": sort, "albums": rows[:limit]}
