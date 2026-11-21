from functools import lru_cache
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Configuration lue depuis les variables d'environnement (ou un fichier .env)."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    spotify_client_id: str
    spotify_client_secret: str
    spotify_redirect_uri: str
    # user-library-read : albums sauvegardés ; user-top-read : affinité (tri "ce que j'écoute le plus").
    spotify_scopes: str = "user-library-read user-top-read"

    frontend_url: str = "http://127.0.0.1:3000"
    cors_origins: list[str] = []

    session_secret: str
    cookie_samesite: Literal["lax", "strict", "none"] = "lax"
    cookie_secure: bool = True

    # Garde-fous
    max_albums: int = 2000
    library_cache_ttl_seconds: int = 600


@lru_cache
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]
