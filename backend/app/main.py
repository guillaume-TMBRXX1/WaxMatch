from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.sessions import SessionMiddleware

from app.config import Settings, get_settings
from app.crypto import TokenCipher
from app.db import create_pool
from app.discogs.client import RateLimiter
from app.discogs.service import DiscogsStore, EnrichJob
from app.offers.service import OffersStore, ScanJob
from app.geo import Geocoder
from app.favorites import FavoritesStore
from app.targets import TargetsStore
from app.routers import auth, discogs, favorites, library, offers, settings as settings_router, targets
from app.user_settings import SettingsStore
from app.repos import PostgresLibraryRepo
from app.store import InMemoryTokenStore, PostgresTokenStore, TokenStore


def create_app(
    settings: Settings | None = None,
    store: TokenStore | None = None,
    transport: httpx.AsyncBaseTransport | None = None,  # injecté par les tests
) -> FastAPI:
    settings = settings or get_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        app.state.http = httpx.AsyncClient(timeout=20, transport=transport)
        pool = None
        if settings.database_url:
            pool = await create_pool(settings.database_url)
            if store is None:
                app.state.store = PostgresTokenStore(pool, TokenCipher(settings.session_secret))
            app.state.library_repo = PostgresLibraryRepo(pool)
        app.state.db_pool = pool
        app.state.discogs_store = DiscogsStore(settings.discogs_cache_path, pool)
        await app.state.discogs_store.load()
        app.state.offers_store = OffersStore(pool)
        await app.state.offers_store.load()
        app.state.settings_store = SettingsStore(pool)
        app.state.favorites_store = FavoritesStore(pool)
        app.state.targets_store = TargetsStore(pool)
        app.state.geocoder = Geocoder(app.state.http, settings.geocoder_user_agent, pool)
        await app.state.geocoder.load()
        yield
        for task in (app.state.discogs_task, app.state.offers_task):
            if task and not task.done():
                task.cancel()
        await app.state.http.aclose()
        if pool is not None:
            await pool.close()

    app = FastAPI(title="WaxMatch API", version="0.1.0", lifespan=lifespan)
    app.state.settings = settings
    app.state.store = store or InMemoryTokenStore()
    app.state.library_cache = {}
    app.state.library_repo = None
    app.state.db_pool = None
    app.state.discogs_limiter = RateLimiter(settings.discogs_min_interval)
    app.state.discogs_job = EnrichJob()
    app.state.discogs_task = None
    app.state.offers_job = ScanJob()
    app.state.offers_task = None

    app.add_middleware(
        SessionMiddleware,
        secret_key=settings.session_secret,
        session_cookie="waxmatch_session",
        max_age=60 * 60 * 24 * 30,
        same_site=settings.cookie_samesite,
        https_only=settings.cookie_secure,
    )
    if settings.cors_origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=settings.cors_origins,
            allow_credentials=True,  # nécessaire pour envoyer le cookie de session depuis Next.js
            allow_methods=["*"],
            allow_headers=["*"],
        )

    app.include_router(auth.router)
    app.include_router(library.router)
    app.include_router(discogs.router)
    app.include_router(offers.router)
    app.include_router(settings_router.router)
    app.include_router(favorites.router)
    app.include_router(targets.router)

    @app.get("/health", tags=["meta"])
    async def health():
        pool = app.state.db_pool
        if pool is None:
            return {"status": "ok", "database": "absente (tout est en mémoire)"}
        try:
            await pool.fetchval("select 1")
            discogs = await pool.fetchval("select count(*) from discogs_matches")
            users = await pool.fetchval("select count(*) from users")
            return {"status": "ok", "database": "connectée", "users": users, "discogs_matches": discogs}
        except Exception as exc:  # noqa: BLE001
            return {"status": "dégradé", "database": f"erreur : {exc}"}

    return app


# Lancement : uvicorn app.main:create_app --factory --host 0.0.0.0 --port 8000
