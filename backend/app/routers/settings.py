from fastapi import APIRouter, Depends, HTTPException, Request

from app.deps import get_spotify
from app.spotify.client import SpotifyClient
from app.user_settings import PRESETS, SettingsInput, UserSettings

router = APIRouter(prefix="/settings", tags=["settings"])


@router.get("", response_model=UserSettings)
async def read_settings(request: Request, spotify: SpotifyClient = Depends(get_spotify)):
    return await request.app.state.settings_store.get(spotify.tokens.spotify_user_id or spotify.session_id)


@router.put("", response_model=UserSettings)
async def update_settings(body: SettingsInput, request: Request, spotify: SpotifyClient = Depends(get_spotify)):
    """Ville (géocodée pour calculer les distances), rayon de main propre, priorité du score, plateformes."""
    settings = UserSettings(**body.model_dump())
    if body.city:
        found = await request.app.state.geocoder.geocode(body.city, body.country)
        if found is None:
            raise HTTPException(status_code=422, detail=f"Ville introuvable : « {body.city} » ({body.country})")
        settings.latitude, settings.longitude, settings.location_label = found
    await request.app.state.settings_store.put(spotify.tokens.spotify_user_id or spotify.session_id, settings)
    return settings


@router.get("/presets")
async def presets():
    """Pondérations du score pour chaque priorité (total 100)."""
    return PRESETS
