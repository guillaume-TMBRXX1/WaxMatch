"""Appel d'Actors Apify en mode synchrone (le run démarre, on reçoit directement les résultats)."""

import asyncio

import httpx

API_BASE = "https://api.apify.com/v2"


class ApifyError(Exception):
    pass


def _error_info(resp: httpx.Response) -> tuple[str, str]:
    try:
        err = resp.json().get("error") or {}
        return str(err.get("type") or ""), str(err.get("message") or "")
    except ValueError:
        return "", resp.text[:300]


class ApifyClient:
    """`busy_retries` : un compte gratuit limite la mémoire totale des runs simultanés ; Apify répond
    alors 402 (« memory limit exceeded »). Ce n'est pas un manque de crédit : on patiente et on réessaie."""

    def __init__(self, http: httpx.AsyncClient, token: str, busy_retries: int = 6, busy_wait_s: float = 15):
        self.http = http
        self.headers = {"Authorization": f"Bearer {token}"}
        self.busy_retries = busy_retries
        self.busy_wait_s = busy_wait_s

    async def run_actor(self, actor_id: str, run_input: dict, timeout_s: int = 120) -> list[dict]:
        url = f"{API_BASE}/acts/{actor_id.replace('/', '~')}/run-sync-get-dataset-items"
        for attempt in range(self.busy_retries + 1):
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
            err_type, err_msg = _error_info(resp)
            if resp.status_code == 401:
                raise ApifyError("Jeton Apify refusé : vérifie le secret APIFY_TOKEN")
            if resp.status_code == 402:
                if ("memory" in err_type or "concurrent" in err_type) and attempt < self.busy_retries:
                    await asyncio.sleep(self.busy_wait_s)
                    continue
                if "memory" in err_type or "concurrent" in err_type:
                    raise ApifyError("Trop de recherches Apify en même temps (limite du compte gratuit)")
                raise ApifyError(f"Apify refuse le lancement (402, {err_type or 'paiement'}) : {err_msg[:200]}")
            if resp.status_code == 408:
                raise ApifyError("L'Actor Apify a dépassé le délai")
            raise ApifyError(f"Apify {resp.status_code} ({err_type}) : {err_msg[:200]}")
        raise ApifyError("Apify indisponible")
