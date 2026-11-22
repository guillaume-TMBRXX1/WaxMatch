from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from app.deps import get_spotify
from app.routers.library import load_library
from app.spotify.client import SpotifyClient

router = APIRouter(prefix="/targets", tags=["targets"])


class TargetInput(BaseModel):
    target_price: float = Field(gt=0, le=100000, description="Prix livré maximum, en euros")


def _user(spotify: SpotifyClient) -> str:
    return spotify.tokens.spotify_user_id or spotify.session_id


@router.get("")
async def list_targets(request: Request, spotify: SpotifyClient = Depends(get_spotify)):
    targets = await request.app.state.targets_store.all(_user(spotify))
    return [{"spotify_id": k, "target_price": v} for k, v in targets.items()]


@router.put("/{spotify_id}")
async def set_target(spotify_id: str, body: TargetInput, request: Request, spotify: SpotifyClient = Depends(get_spotify)):
    albums = await load_library(request, spotify, refresh=False)
    album = next((a for a in albums if spotify_id in (a.spotify_id, *a.duplicates)), None)
    if album is None:
        raise HTTPException(status_code=404, detail="Album absent de ta bibliothèque Spotify")
    price = round(body.target_price, 2)
    await request.app.state.targets_store.set(_user(spotify), album.spotify_id, album.match_key, price)
    return {"spotify_id": album.spotify_id, "target_price": price}


@router.delete("/{spotify_id}")
async def delete_target(spotify_id: str, request: Request, spotify: SpotifyClient = Depends(get_spotify)):
    await request.app.state.targets_store.delete(_user(spotify), spotify_id)
    return {"ok": True}
