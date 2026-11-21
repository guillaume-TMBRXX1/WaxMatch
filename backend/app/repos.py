"""Persistance de la bibliothèque normalisée de chaque utilisateur."""

from datetime import datetime, timezone

from app.spotify.normalize import LibraryAlbum


class PostgresLibraryRepo:
    def __init__(self, pool):
        self.pool = pool

    async def load(self, spotify_user_id: str) -> tuple[datetime, list[LibraryAlbum]] | None:
        sync = await self.pool.fetchrow(
            "select synced_at from library_syncs where spotify_user_id = $1", spotify_user_id
        )
        if sync is None:
            return None
        rows = await self.pool.fetch("select data from user_albums where spotify_user_id = $1", spotify_user_id)
        return sync["synced_at"], [LibraryAlbum.model_validate(r["data"]) for r in rows]

    async def save(self, spotify_user_id: str, albums: list[LibraryAlbum]) -> None:
        records = [
            (
                spotify_user_id,
                a.spotify_id,
                a.match_key,
                a.added_at,
                a.model_dump(mode="json", exclude={"discogs"}),  # Discogs vit dans sa propre table
            )
            for a in albums
        ]
        async with self.pool.acquire() as con, con.transaction():
            await con.execute("delete from user_albums where spotify_user_id = $1", spotify_user_id)
            await con.executemany(
                "insert into user_albums (spotify_user_id, spotify_album_id, match_key, added_at, data)"
                " values ($1, $2, $3, $4, $5)",
                records,
            )
            await con.execute(
                """
                insert into library_syncs (spotify_user_id, synced_at, album_count) values ($1, $2, $3)
                on conflict (spotify_user_id) do update
                set synced_at = excluded.synced_at, album_count = excluded.album_count
                """,
                spotify_user_id,
                datetime.now(timezone.utc),
                len(albums),
            )
