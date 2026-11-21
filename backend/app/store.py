"""Stockage des jetons OAuth.

- InMemoryTokenStore : sans base de données (tests, essais rapides).
- PostgresTokenStore : Supabase, jetons chiffrés, sessions stockées hachées.
"""

import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Protocol

from app.crypto import InvalidToken, TokenCipher, hash_session_id


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


class PostgresTokenStore:
    """Jetons chiffrés en base ; le cookie ne porte qu'un identifiant de session, stocké haché."""

    def __init__(self, pool, cipher: TokenCipher):
        self.pool = pool
        self.cipher = cipher

    async def get(self, session_id: str) -> SpotifyTokens | None:
        row = await self.pool.fetchrow(
            """
            update sessions s set last_seen_at = now()
            from oauth_tokens t, users u
            where s.session_hash = $1
              and t.spotify_user_id = s.spotify_user_id
              and u.spotify_user_id = s.spotify_user_id
            returning t.access_token_enc, t.refresh_token_enc, t.expires_at, t.scope,
                      u.spotify_user_id, u.display_name
            """,
            hash_session_id(session_id),
        )
        if row is None:
            return None
        try:
            access, refresh = self.cipher.decrypt(row["access_token_enc"]), self.cipher.decrypt(row["refresh_token_enc"])
        except InvalidToken:
            return None  # secret de l'application changé : l'utilisateur doit se reconnecter
        return SpotifyTokens(
            access_token=access,
            refresh_token=refresh,
            expires_at=row["expires_at"].timestamp(),
            scope=row["scope"],
            spotify_user_id=row["spotify_user_id"],
            display_name=row["display_name"],
        )

    async def save(self, session_id: str, tokens: SpotifyTokens) -> None:
        if not tokens.spotify_user_id:
            raise ValueError("spotify_user_id requis pour enregistrer les jetons")
        async with self.pool.acquire() as con, con.transaction():
            await con.execute(
                """
                insert into users (spotify_user_id, display_name) values ($1, $2)
                on conflict (spotify_user_id) do update
                set display_name = coalesce(excluded.display_name, users.display_name), updated_at = now()
                """,
                tokens.spotify_user_id,
                tokens.display_name,
            )
            await con.execute(
                """
                insert into oauth_tokens (spotify_user_id, access_token_enc, refresh_token_enc, expires_at, scope)
                values ($1, $2, $3, $4, $5)
                on conflict (spotify_user_id) do update
                set access_token_enc = excluded.access_token_enc, refresh_token_enc = excluded.refresh_token_enc,
                    expires_at = excluded.expires_at, scope = excluded.scope, updated_at = now()
                """,
                tokens.spotify_user_id,
                self.cipher.encrypt(tokens.access_token),
                self.cipher.encrypt(tokens.refresh_token),
                datetime.fromtimestamp(tokens.expires_at, tz=timezone.utc),
                tokens.scope,
            )
            await con.execute(
                "insert into sessions (session_hash, spotify_user_id) values ($1, $2) on conflict do nothing",
                hash_session_id(session_id),
                tokens.spotify_user_id,
            )

    async def delete(self, session_id: str) -> None:
        await self.pool.execute("delete from sessions where session_hash = $1", hash_session_id(session_id))
