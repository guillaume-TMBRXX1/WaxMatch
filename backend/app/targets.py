"""Prix cible par album : les annonces livrées sous ce prix sont signalées."""


class TargetsStore:
    def __init__(self, pool=None):
        self.pool = pool
        self.memory: dict[str, dict[str, float]] = {}

    async def all(self, user_id: str) -> dict[str, float]:
        """{spotify_album_id: prix cible}"""
        if self.pool is not None:
            rows = await self.pool.fetch(
                "select spotify_album_id, target_price from album_targets where spotify_user_id = $1", user_id
            )
            return {r["spotify_album_id"]: float(r["target_price"]) for r in rows}
        return dict(self.memory.get(user_id, {}))

    async def get(self, user_id: str, spotify_id: str) -> float | None:
        return (await self.all(user_id)).get(spotify_id)

    async def set(self, user_id: str, spotify_id: str, match_key: str, price: float) -> None:
        if self.pool is not None:
            await self.pool.execute(
                """
                insert into album_targets (spotify_user_id, spotify_album_id, match_key, target_price)
                values ($1, $2, $3, $4)
                on conflict (spotify_user_id, spotify_album_id)
                do update set target_price = excluded.target_price, updated_at = now()
                """,
                user_id, spotify_id, match_key, price,
            )
            return
        self.memory.setdefault(user_id, {})[spotify_id] = price

    async def delete(self, user_id: str, spotify_id: str) -> None:
        if self.pool is not None:
            await self.pool.execute(
                "delete from album_targets where spotify_user_id = $1 and spotify_album_id = $2", user_id, spotify_id
            )
            return
        self.memory.get(user_id, {}).pop(spotify_id, None)
