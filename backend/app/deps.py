import httpx
from fastapi import Depends, HTTPException, Request

from app.config import Settings
from app.discogs.client import DiscogsClient
from app.offers.apify import ApifyClient
from app.spotify.client import SpotifyClient
from app.store import TokenStore


def get_settings_dep(request: Request) -> Settings:
    return request.app.state.settings


def get_http(request: Request) -> httpx.AsyncClient:
    return request.app.state.http


def get_store(request: Request) -> TokenStore:
    return request.app.state.store


def get_discogs(
    request: Request,
    settings: Settings = Depends(get_settings_dep),
    http: httpx.AsyncClient = Depends(get_http),
) -> DiscogsClient:
    if not settings.discogs_token:
        raise HTTPException(status_code=503, detail="Discogs non configuré : ajoute le secret DISCOGS_TOKEN")
    return DiscogsClient(
        http,
        settings.discogs_token,
        settings.discogs_user_agent,
        request.app.state.discogs_limiter,
        settings.discogs_currency,
    )


def get_apify(
    settings: Settings = Depends(get_settings_dep),
    http: httpx.AsyncClient = Depends(get_http),
) -> ApifyClient:
    if not settings.apify_token:
        raise HTTPException(status_code=503, detail="Apify non configuré : ajoute le secret APIFY_TOKEN")
    return ApifyClient(http, settings.apify_token)


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
