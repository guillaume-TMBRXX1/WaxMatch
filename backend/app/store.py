"""Stockage des jetons OAuth.

Phase Colab : en mémoire (perdu au redémarrage du runtime, suffisant pour tester).
Phase 2 : implémentation PostgreSQL/Supabase avec chiffrement du refresh_token,
en respectant le même Protocol -> aucun autre fichier à modifier.
"""

import time
from dataclasses import dataclass
from typing import Protocol


@dataclass
class SpotifyTokens:
    access_token: str
    refresh_token: str
    expires_at: float  # timestamp UNIX
    scope: str = ""
    spotify_user_id: str | None = None
    display_name: str | None = None

    def is_expired(self, leeway: int = 60) -> bool:
        return time.time() >= self.expires_at - leeway


class TokenStore(Protocol):
    async def get(self, session_id: str) -> SpotifyTokens | None: ...
    async def save(self, session_id: str, tokens: SpotifyTokens) -> None: ...
    async def delete(self, session_id: str) -> None: ...


class InMemoryTokenStore:
    def __init__(self) -> None:
        self._data: dict[str, SpotifyTokens] = {}

    async def get(self, session_id: str) -> SpotifyTokens | None:
        return self._data.get(session_id)

    async def save(self, session_id: str, tokens: SpotifyTokens) -> None:
        self._data[session_id] = tokens

    async def delete(self, session_id: str) -> None:
        self._data.pop(session_id, None)
