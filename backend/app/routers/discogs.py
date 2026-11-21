import asyncio
import time

from fastapi import APIRouter, Depends, HTTPException, Request

from app.deps import get_discogs, get_spotify
from app.discogs.client import DiscogsClient, DiscogsError
from app.discogs.models import AlbumOffers
from app.discogs.service import OFFERS_TTL_SECONDS, album_offers, find_match, run_enrichment
from app.routers.library import load_library
from app.spotify.client import SpotifyClient

router = APIRouter(prefix="/discogs", tags=["discogs"])


@router.post("/enrich")
async def start_enrichment(
    request: Request,
    spotify: SpotifyClient = Depends(get_spotify),
    discogs: DiscogsClient = Depends(get_discogs),
):
    """Lance (en arrière-plan) la recherche Discogs de tous les albums pas encore traités."""
    state = request.app.state
    if not state.discogs_job.running:
        albums = await load_library(request, spotify, refresh=False)
        state.discogs_task = asyncio.create_task(
            run_enrichment(
                discogs, state.discogs_store, state.discogs_job, albums, state.settings.discogs_match_threshold
            )
        )
        await asyncio.sleep(0)  # laisse la tâche initialiser ses compteurs
    return state.discogs_job.status()


@router.get("/enrich/status")
async def enrichment_status(request: Request):
    return request.app.state.discogs_job.status()


@router.get("/albums/{spotify_id}", response_model=AlbumOffers)
async def album_vinyl_offers(
    spotify_id: str,
    request: Request,
    refresh: bool = False,
    spotify: SpotifyClient = Depends(get_spotify),
    discogs: DiscogsClient = Depends(get_discogs),
):
    """Fiche Discogs d'un album et prix des éditions vinyles en vente."""
    albums = await load_library(request, spotify, refresh=False)
    album = next((a for a in albums if spotify_id in (a.spotify_id, *a.duplicates)), None)
    if album is None:
        raise HTTPException(status_code=404, detail="Album absent de ta bibliothèque Spotify")

    store = request.app.state.discogs_store
    cached = store.offers.get(album.match_key)
    if cached and not refresh and time.time() - cached.checked_at < OFFERS_TTL_SECONDS:
        return cached

    try:
        match = store.get(album.match_key)
        if match is None or refresh:
            match = await find_match(discogs, album, request.app.state.settings.discogs_match_threshold)
            store.put(album.match_key, match)
            store.save()
        offers = await album_offers(discogs, match)
    except DiscogsError as exc:
        raise HTTPException(status_code=502, detail=f"Discogs indisponible : {exc}") from exc
    store.offers[album.match_key] = offers
    return offers
