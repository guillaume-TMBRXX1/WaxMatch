"""Appel d'Actors Apify en mode synchrone (le run démarre, on reçoit directement les résultats)."""

import httpx

API_BASE = "https://api.apify.com/v2"


class ApifyError(Exception):
    pass


class ApifyClient:
    def __init__(self, http: httpx.AsyncClient, token: str):
        self.http = http
        self.headers = {"Authorization": f"Bearer {token}"}

    async def run_actor(self, actor_id: str, run_input: dict, timeout_s: int = 120) -> list[dict]:
        url = f"{API_BASE}/acts/{actor_id.replace('/', '~')}/run-sync-get-dataset-items"
        try:
            resp = await self.http.post(
                url,
                params={"timeout": timeout_s, "clean": "true"},
                json=run_input,
                headers=self.headers,
                timeout=timeout_s + 30,
            )
        except httpx.HTTPError as exc:
            raise ApifyError(f"Apify injoignable : {exc}") from exc
        if resp.status_code in (200, 201):
            data = resp.json()
            return data if isinstance(data, list) else []
        if resp.status_code == 401:
            raise ApifyError("Jeton Apify refusé : vérifie le secret APIFY_TOKEN")
        if resp.status_code == 402:
            raise ApifyError("Crédit Apify épuisé pour ce mois")
        if resp.status_code == 408:
            raise ApifyError("L'Actor Apify a dépassé le délai")
        raise ApifyError(f"Apify {resp.status_code} : {resp.text[:300]}")
