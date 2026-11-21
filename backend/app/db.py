"""Connexion PostgreSQL (Supabase) et migrations appliquées automatiquement au démarrage."""

import json
import logging
from pathlib import Path

import asyncpg

log = logging.getLogger("waxmatch.db")
MIGRATIONS_DIR = Path(__file__).parent / "migrations"
_LOCK_ID = 7_315_002  # verrou consultatif : deux instances ne migrent pas en même temps


async def _init_connection(con: asyncpg.Connection) -> None:
    await con.set_type_codec("jsonb", encoder=json.dumps, decoder=json.loads, schema="pg_catalog")


async def create_pool(database_url: str) -> asyncpg.Pool:
    # Avec Supabase, utiliser l'URL du "Session pooler" (compatible IPv4, donc Colab et Railway).
    pool = await asyncpg.create_pool(
        database_url, min_size=1, max_size=5, command_timeout=30, init=_init_connection
    )
    await migrate(pool)
    return pool


async def migrate(pool: asyncpg.Pool) -> list[str]:
    applied: list[str] = []
    async with pool.acquire() as con:
        await con.execute("select pg_advisory_lock($1)", _LOCK_ID)
        try:
            await con.execute(
                "create table if not exists schema_migrations ("
                " name text primary key, applied_at timestamptz not null default now())"
            )
            await con.execute("alter table schema_migrations enable row level security")
            done = {r["name"] for r in await con.fetch("select name from schema_migrations")}
            for path in sorted(MIGRATIONS_DIR.glob("*.sql")):
                if path.name in done:
                    continue
                async with con.transaction():
                    await con.execute(path.read_text(encoding="utf-8"))
                    await con.execute("insert into schema_migrations (name) values ($1)", path.name)
                applied.append(path.name)
                log.info("Migration appliquée : %s", path.name)
        finally:
            await con.execute("select pg_advisory_unlock($1)", _LOCK_ID)
    return applied
