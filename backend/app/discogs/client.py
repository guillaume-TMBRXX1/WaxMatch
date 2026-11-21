"""Client de l'API officielle Discogs (https://www.discogs.com/developers).

Authentification par jeton personnel, limite de 60 requêtes/minute : toutes les requêtes
passent par un limiteur partagé, et un 429 déclenche une pause.
"""

import asyncio
import time
from typing import Any

import httpx

API_BASE = "https://api.discogs.com"


class DiscogsError(Exception):
    def __init__(self, status: int, message: str):
        super().__init__(f"Discogs {status}: {message}")
        self.status = status


class RateLimiter:
    """Espace les requêtes d'au moins `min_interval` secondes (partagé par toute l'application)."""

    def __init__(self, min_interval: float):
        self.min_interval = min_interval
        self._lock = asyncio.Lock()
        self._last = 0.0

    async def wait(self) -> None:
        async with self._lock:
            delay = self._last + self.min_interval - time.monotonic()
            if delay > 0:
                await asyncio.sleep(delay)
            self._last = time.monotonic()

    def penalize(self, seconds: float) -> None:
        """Repousse la prochaine requête (après un 429)."""
        self._last = max(self._last, time.monotonic() + seconds - self.min_interval)


class DiscogsClient:
    def __init__(
        self,
        http: httpx.AsyncClient,
        token: str,
        user_agent: str,
        limiter: RateLimiter,
        currency: str = "EUR",
    ):
        self.http = http
        self.limiter = limiter
        self.currency = currency
        self.headers = {
            "Authorization": f"Discogs token={token}",
            "User-Agent": user_agent,  # exigé par Discogs
            "Accept": "application/vnd.discogs.v2.discogs+json",
        }

    async def get(self, path: str, params: dict | None = None) -> Any:
        for _ in range(4):
            await self.limiter.wait()
            resp = await self.http.get(f"{API_BASE}{path}", params=params, headers=self.headers)
            if resp.status_code == 429:
                self.limiter.penalize(float(resp.headers.get("Retry-After", 60)))
                continue
            if resp.status_code == 404:
                return None
            if resp.status_code >= 400:
                raise DiscogsError(resp.status_code, resp.text[:300])
            return resp.json()
        raise DiscogsError(429, "Limite de débit Discogs atteinte trop souvent")

    async def search(self, **params: Any) -> list[dict]:
        params.setdefault("per_page", 10)
        data = await self.get("/database/search", params=params)
        return (data or {}).get("results", [])

    async def master_vinyl_versions(self, master_id: int, limit: int = 25) -> list[dict]:
        data = await self.get(
            f"/masters/{master_id}/versions",
            params={"format": "Vinyl", "per_page": limit, "sort": "released", "sort_order": "asc"},
        )
        return (data or {}).get("versions", [])

    async def marketplace_stats(self, release_id: int) -> dict | None:
        return await self.get(f"/marketplace/stats/{release_id}", params={"curr_abbr": self.currency})
