from fastapi import APIRouter, Depends, HTTPException, Request

from app.deps import get_spotify
from app.favorites import Favorite, FavoriteInput, FavoriteView, favorite_status
from app.routers.library import load_library
from app.spotify.client import SpotifyClient

router = APIRouter(prefix="/favorites", tags=["favorites"])


def _user(spotify: SpotifyClient) -> str:
    return spotify.tokens.spotify_user_id or spotify.session_id


@router.get("", response_model=list[FavoriteView])
async def list_favorites(request: Request, spotify: SpotifyClient = Depends(get_spotify)):
    """Favoris, du plus récent au plus ancien, avec leur état d'après la dernière recherche (sans coût)."""
    favorites = await request.app.state.favorites_store.list(_user(spotify))
    return [favorite_status(f, request.app.state.offers_store) for f in favorites]


@router.post("", response_model=FavoriteView, status_code=201)
async def add_favorite(body: FavoriteInput, request: Request, spotify: SpotifyClient = Depends(get_spotify)):
    albums = await load_library(request, spotify, refresh=False)
    album = next((a for a in albums if body.spotify_id in (a.spotify_id, *a.duplicates)), None)
    if album is None:
        raise HTTPException(status_code=404, detail="Album absent de ta bibliothèque Spotify")
    fav = Favorite(
        spotify_id=album.spotify_id,
        match_key=album.match_key,
        artist=album.primary_artist,
        album_title=album.title_clean,
        cover_url=album.cover_url,
        listing=body.listing,
    )
    await request.app.state.favorites_store.add(_user(spotify), fav)
    return favorite_status(fav, request.app.state.offers_store)


@router.delete("/{platform}/{external_id}")
async def remove_favorite(
    platform: str, external_id: str, request: Request, spotify: SpotifyClient = Depends(get_spotify)
):
    await request.app.state.favorites_store.remove(_user(spotify), platform, external_id)
    return {"ok": True}
