import httpx
from fastapi import Depends, HTTPException, Request

from app.config import Settings
from app.spotify.client import SpotifyClient
from app.store import TokenStore


def get_settings_dep(request: Request) -> Settings:
    return request.app.state.settings


def get_http(request: Request) -> httpx.AsyncClient:
    return request.app.state.http


def get_store(request: Request) -> TokenStore:
    return request.app.state.store


async def get_spotify(
    request: Request,
    settings: Settings = Depends(get_settings_dep),
    http: httpx.AsyncClient = Depends(get_http),
    store: TokenStore = Depends(get_store),
) -> SpotifyClient:
    session_id = request.session.get("sid")
    tokens = await store.get(session_id) if session_id else None
    if not session_id or tokens is None:
        raise HTTPException(status_code=401, detail="Non connecté à Spotify : passe par /auth/login")
    return SpotifyClient(http, settings, store, session_id, tokens)
