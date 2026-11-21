import secrets

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import RedirectResponse

from app.config import Settings
from app.deps import get_http, get_settings_dep, get_spotify, get_store
from app.spotify.client import SpotifyClient
from app.spotify.oauth import SpotifyAuthError, build_authorize_url, exchange_code
from app.store import TokenStore

router = APIRouter(prefix="/auth", tags=["auth"])


@router.get("/login")
async def login(request: Request, settings: Settings = Depends(get_settings_dep)):
    """Redirige vers l'écran de consentement Spotify."""
    state = secrets.token_urlsafe(24)
    request.session["oauth_state"] = state  # protège contre les attaques CSRF
    return RedirectResponse(build_authorize_url(settings, state), status_code=307)


@router.get("/callback")
async def callback(
    request: Request,
    code: str | None = None,
    state: str | None = None,
    error: str | None = None,
    settings: Settings = Depends(get_settings_dep),
    http: httpx.AsyncClient = Depends(get_http),
    store: TokenStore = Depends(get_store),
):
    expected = request.session.pop("oauth_state", None)
    if error:
        raise HTTPException(status_code=400, detail=f"Connexion Spotify refusée : {error}")
    if not code or not state or not expected or not secrets.compare_digest(state, expected):
        raise HTTPException(status_code=400, detail="Paramètre state invalide : relance /auth/login")

    try:
        tokens = await exchange_code(http, settings, code)
    except SpotifyAuthError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    resp = await http.get(
        "https://api.spotify.com/v1/me",
        headers={"Authorization": f"Bearer {tokens.access_token}"},
    )
    profile = resp.json() if resp.status_code == 200 else {}
    if not profile.get("id"):
        # En Development Mode, un compte non ajouté dans "User Management" est refusé ici (403).
        raise HTTPException(
            status_code=403,
            detail="Profil Spotify inaccessible : ce compte est-il autorisé dans le dashboard Spotify (User Management) ?",
        )
    tokens.spotify_user_id = profile["id"]
    tokens.display_name = profile.get("display_name")

    session_id = secrets.token_urlsafe(32)
    await store.save(session_id, tokens)
    request.session["sid"] = session_id  # cookie signé : ne contient QUE l'identifiant, jamais les jetons
    return RedirectResponse(settings.frontend_url, status_code=303)


@router.get("/me")
async def me(spotify: SpotifyClient = Depends(get_spotify)):
    return {
        "spotify_user_id": spotify.tokens.spotify_user_id,
        "display_name": spotify.tokens.display_name,
        "scopes": spotify.tokens.scope.split(),
    }


@router.post("/logout")
async def logout(request: Request, store: TokenStore = Depends(get_store)):
    session_id = request.session.pop("sid", None)
    if session_id:
        tokens = await store.get(session_id)
        await store.delete(session_id)
        request.app.state.library_cache.pop(tokens.spotify_user_id if tokens else session_id, None)
    return {"ok": True}
