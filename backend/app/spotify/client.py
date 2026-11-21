"""Client Web API Spotify : rafraîchissement auto du jeton, pagination, gestion du 429."""

import asyncio
from collections.abc import AsyncIterator
from typing import Any

import httpx

from app.config import Settings
from app.spotify.oauth import refresh_tokens
from app.store import SpotifyTokens, TokenStore

API_BASE = "https://api.spotify.com/v1"
MAX_RETRIES = 4


class SpotifyAPIError(Exception):
    def __init__(self, status: int, message: str):
        super().__init__(f"Spotify API {status}: {message}")
        self.status = status


class SpotifyClient:
    def __init__(
        self,
        http: httpx.AsyncClient,
        settings: Settings,
        store: TokenStore,
        session_id: str,
        tokens: SpotifyTokens,
    ):
        self.http = http
        self.settings = settings
        self.store = store
        self.session_id = session_id
        self.tokens = tokens

    async def _refresh(self) -> None:
        self.tokens = await refresh_tokens(self.http, self.settings, self.tokens)
        await self.store.save(self.session_id, self.tokens)

    async def request(self, method: str, path: str, params: dict | None = None) -> Any:
        if self.tokens.is_expired():
            await self._refresh()

        url = path if path.startswith("http") else f"{API_BASE}{path}"
        refreshed = False
        for attempt in range(MAX_RETRIES):
            resp = await self.http.request(
                method,
                url,
                params=params,
                headers={"Authorization": f"Bearer {self.tokens.access_token}"},
            )
            if resp.status_code == 401 and not refreshed:
                await self._refresh()
                refreshed = True
                continue
            if resp.status_code == 429:
                # Limite de débit : Spotify indique combien de secondes attendre.
                wait = int(resp.headers.get("Retry-After", "1"))
                await asyncio.sleep(min(wait, 30))
                continue
            if resp.status_code >= 500 and attempt < MAX_RETRIES - 1:
                await asyncio.sleep(2**attempt)
                continue
            if resp.status_code >= 400:
                raise SpotifyAPIError(resp.status_code, resp.text)
            return resp.json() if resp.content else None
        raise SpotifyAPIError(429, "Trop de tentatives (limite de débit)")

    async def me(self) -> dict:
        return await self.request("GET", "/me")

    async def iter_saved_albums(self, max_items: int) -> AsyncIterator[dict]:
        """Itère sur les albums sauvegardés ({added_at, album}), 50 par page."""
        url: str | None = f"{API_BASE}/me/albums"
        params: dict | None = {"limit": 50, "offset": 0}
        count = 0
        while url and count < max_items:
            page = await self.request("GET", url, params=params)
            for item in page.get("items", []):
                yield item
                count += 1
                if count >= max_items:
                    return
            url = page.get("next")  # l'URL "next" contient déjà offset/limit
            params = None

    async def get_artists(self, artist_ids: list[str]) -> dict[str, dict]:
        """Récupère les artistes (pour leurs genres).

        Les apps en "Development Mode" créées après février 2026 peuvent ne plus avoir
        accès à l'endpoint groupé /artists?ids= : on tente le groupé puis on retombe
        sur des appels unitaires limités en concurrence. Les genres peuvent aussi
        revenir vides : le reste du pipeline doit le tolérer.
        """
        unique = list(dict.fromkeys(i for i in artist_ids if i))
        result: dict[str, dict] = {}

        try:
            for i in range(0, len(unique), 50):
                chunk = unique[i : i + 50]
                data = await self.request("GET", "/artists", params={"ids": ",".join(chunk)})
                for artist in data.get("artists") or []:
                    if artist:
                        result[artist["id"]] = artist
            return result
        except SpotifyAPIError as exc:
            if exc.status not in (403, 404):
                raise

        sem = asyncio.Semaphore(5)

        async def fetch_one(artist_id: str) -> None:
            async with sem:
                try:
                    result[artist_id] = await self.request("GET", f"/artists/{artist_id}")
                except SpotifyAPIError:
                    pass  # un artiste manquant ne doit pas faire échouer toute la bibliothèque

        await asyncio.gather(*(fetch_one(a) for a in unique if a not in result))
        return result
