"""Persistance de l'onglet Revente (mémoire + PostgreSQL si disponible)."""

import time
from datetime import date

from app.resale.models import Opportunity, ResaleSettings, WatchItem


class ResaleStore:
    def __init__(self, pool=None):
        self.pool = pool
        self.watchlist: dict[str, WatchItem] = {}
        self.opportunities: dict[str, Opportunity] = {}
        self.meta: dict[str, dict] = {}

    async def load(self) -> None:
        if self.pool is None:
            return
        self.watchlist = {
            r["key"]: WatchItem.model_validate(r["data"]) for r in await self.pool.fetch("select key, data from resale_watchlist")
        }
        self.opportunities = {
            r["key"]: Opportunity.model_validate(r["data"])
            for r in await self.pool.fetch("select key, data from resale_opportunities")
        }
        self.meta = {r["key"]: r["data"] for r in await self.pool.fetch("select key, data from resale_meta")}

    # ------------------------------------------------------------------ réglages et compteurs
    @property
    def settings(self) -> ResaleSettings:
        return ResaleSettings.model_validate(self.meta.get("settings") or {})

    async def _put_meta(self, key: str, data: dict) -> None:
        self.meta[key] = data
        if self.pool is not None:
            await self.pool.execute(
                "insert into resale_meta (key, data) values ($1, $2) on conflict (key) do update set data = excluded.data",
                key, data,
            )

    async def save_settings(self, settings: ResaleSettings) -> None:
        await self._put_meta("settings", settings.model_dump(mode="json"))

    def apify_runs_today(self) -> int:
        return int((self.meta.get(f"usage:{date.today().isoformat()}") or {}).get("apify_runs", 0))

    async def add_apify_runs(self, n: int) -> None:
        if n:
            await self._put_meta(f"usage:{date.today().isoformat()}", {"apify_runs": self.apify_runs_today() + n})

    # ------------------------------------------------------------------ liste de surveillance
    async def replace_watchlist(self, items: list[WatchItem]) -> None:
        for item in items:  # garde la date de dernière analyse des disques déjà suivis
            if item.key in self.watchlist:
                item.last_scanned = self.watchlist[item.key].last_scanned
        self.watchlist = {i.key: i for i in items}
        if self.pool is not None:
            async with self.pool.acquire() as con, con.transaction():
                await con.execute("delete from resale_watchlist")
                await con.executemany(
                    "insert into resale_watchlist (key, data) values ($1, $2)",
                    [(i.key, i.model_dump(mode="json")) for i in items],
                )

    async def save_item(self, item: WatchItem) -> None:
        self.watchlist[item.key] = item
        if self.pool is not None:
            await self.pool.execute(
                "insert into resale_watchlist (key, data) values ($1, $2)"
                " on conflict (key) do update set data = excluded.data, updated_at = now()",
                item.key, item.model_dump(mode="json"),
            )

    # ------------------------------------------------------------------ opportunités (journal)
    async def upsert_opportunity(self, opp: Opportunity) -> bool:
        """Enregistre ou met à jour ; renvoie True si l'opportunité est nouvelle."""
        previous = self.opportunities.get(opp.key)
        if previous is not None:
            # La décision de l'utilisateur est conservée : une offre écartée n'est jamais reproposée.
            opp.decision, opp.decision_reason, opp.decided_at = previous.decision, previous.decision_reason, previous.decided_at
        is_new = (previous is None or previous.status == "disparue") and opp.decision != "ecartee"
        if previous is not None and previous.status == "active":
            opp.first_seen = previous.first_seen
        opp.last_seen, opp.status = time.time(), "active"
        self.opportunities[opp.key] = opp
        await self._save_opportunity(opp)
        return is_new

    async def decide(self, key: str, decision: str | None, reason: str | None = None) -> Opportunity | None:
        opp = self.opportunities.get(key)
        if opp is None:
            return None
        opp.decision, opp.decision_reason = decision, reason if decision == "ecartee" else None
        opp.decided_at = time.time() if decision else None
        await self._save_opportunity(opp)
        return opp

    async def remove(self, key: str) -> None:
        self.opportunities.pop(key, None)
        if self.pool is not None:
            await self.pool.execute("delete from resale_opportunities where key = $1", key)

    async def mark_gone(self, watch_key: str, seen: set[str]) -> int:
        gone = 0
        for opp in self.opportunities.values():
            if opp.watch_key == watch_key and opp.status == "active" and opp.key not in seen:
                opp.status = "disparue"  # absente de la nouvelle recherche : vendue, retirée ou plus rentable
                await self._save_opportunity(opp)
                gone += 1
        return gone

    async def _save_opportunity(self, opp: Opportunity) -> None:
        if self.pool is not None:
            await self.pool.execute(
                """
                insert into resale_opportunities (key, watch_key, status, margin, data, first_seen, last_seen)
                values ($1, $2, $3, $4, $5, to_timestamp($6), to_timestamp($7))
                on conflict (key) do update set status = excluded.status, margin = excluded.margin,
                    data = excluded.data, last_seen = excluded.last_seen
                """,
                opp.key, opp.watch_key, opp.status, opp.margin, opp.model_dump(mode="json"), opp.first_seen, opp.last_seen,
            )
