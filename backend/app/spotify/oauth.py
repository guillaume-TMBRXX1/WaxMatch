"""Flux OAuth 2.0 "Authorization Code" de Spotify (client confidentiel côté serveur)."""

import base64
import time
from urllib.parse import urlencode

import httpx

from app.config import Settings
from app.store import SpotifyTokens

AUTHORIZE_URL = "https://accounts.spotify.com/authorize"
TOKEN_URL = "https://accounts.spotify.com/api/token"


class SpotifyAuthError(Exception):
    pass


def build_authorize_url(settings: Settings, state: str) -> str:
    params = {
        "client_id": settings.spotify_client_id,
        "response_type": "code",
        "redirect_uri": settings.spotify_redirect_uri,
        "scope": settings.spotify_scopes,
        "state": state,
        "show_dialog": "false",
    }
    return f"{AUTHORIZE_URL}?{urlencode(params)}"


def _basic_auth(settings: Settings) -> str:
    raw = f"{settings.spotify_client_id}:{settings.spotify_client_secret}".encode()
    return "Basic " + base64.b64encode(raw).decode()


async def _token_request(http: httpx.AsyncClient, settings: Settings, data: dict) -> dict:
    resp = await http.post(
        TOKEN_URL,
        data=data,
        headers={"Authorization": _basic_auth(settings)},
    )
    if resp.status_code != 200:
        raise SpotifyAuthError(f"Échec de l'échange de jeton ({resp.status_code}) : {resp.text}")
    return resp.json()


async def exchange_code(http: httpx.AsyncClient, settings: Settings, code: str) -> SpotifyTokens:
    payload = await _token_request(
        http,
        settings,
        {
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": settings.spotify_redirect_uri,
        },
    )
    return SpotifyTokens(
        access_token=payload["access_token"],
        refresh_token=payload["refresh_token"],
        expires_at=time.time() + int(payload.get("expires_in", 3600)),
        scope=payload.get("scope", ""),
    )


async def refresh_tokens(
    http: httpx.AsyncClient, settings: Settings, tokens: SpotifyTokens
) -> SpotifyTokens:
    payload = await _token_request(
        http,
        settings,
        {"grant_type": "refresh_token", "refresh_token": tokens.refresh_token},
    )
    tokens.access_token = payload["access_token"]
    tokens.expires_at = time.time() + int(payload.get("expires_in", 3600))
    # Spotify ne renvoie pas toujours un nouveau refresh_token : on garde l'ancien sinon.
    tokens.refresh_token = payload.get("refresh_token") or tokens.refresh_token
    tokens.scope = payload.get("scope", tokens.scope)
    return tokens
