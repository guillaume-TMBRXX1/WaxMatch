"""Géocodage (ville -> coordonnées) via Nominatim / OpenStreetMap, avec cache, et calcul de distance."""

import asyncio
import math
import time

import httpx

NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    r = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = math.radians(lat2 - lat1), math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


class Geocoder:
    """Respecte la politique d'usage de Nominatim : 1 requête/s au plus, User-Agent explicite, cache."""

    def __init__(self, http: httpx.AsyncClient, user_agent: str, pool=None, min_interval: float = 1.1):
        self.http = http
        self.headers = {"User-Agent": user_agent, "Accept-Language": "fr"}
        self.pool = pool
        self.min_interval = min_interval
        self.cache: dict[str, tuple[float, float, str] | None] = {}
        self._lock = asyncio.Lock()
        self._last = 0.0

    async def load(self) -> None:
        if self.pool is not None:
            rows = await self.pool.fetch("select query, latitude, longitude, display_name from geocodes")
            self.cache = {
                r["query"]: (r["latitude"], r["longitude"], r["display_name"]) if r["latitude"] is not None else None
                for r in rows
            }

    async def geocode(self, place: str, country: str | None = None) -> tuple[float, float, str] | None:
        key = f"{place.strip().lower()}|{(country or '').lower()}"
        if key in self.cache:
            return self.cache[key]
        params = {"q": place, "format": "json", "limit": 1}
        if country:
            params["countrycodes"] = country.lower()
        async with self._lock:
            delay = self._last + self.min_interval - time.monotonic()
            if delay > 0:
                await asyncio.sleep(delay)
            try:
                resp = await self.http.get(NOMINATIM_URL, params=params, headers=self.headers, timeout=15)
            except httpx.HTTPError:
                return None  # non mis en cache : on réessaiera
            finally:
                self._last = time.monotonic()
        if resp.status_code != 200:
            return None
        data = resp.json()
        result = (float(data[0]["lat"]), float(data[0]["lon"]), data[0].get("display_name", place)) if data else None
        self.cache[key] = result
        if self.pool is not None:
            await self.pool.execute(
                "insert into geocodes (query, latitude, longitude, display_name) values ($1, $2, $3, $4)"
                " on conflict (query) do nothing",
                key,
                result[0] if result else None,
                result[1] if result else None,
                result[2] if result else None,
            )
        return result
