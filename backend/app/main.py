from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.sessions import SessionMiddleware

from app.config import Settings, get_settings
from app.routers import auth, library
from app.store import InMemoryTokenStore, TokenStore


def create_app(
    settings: Settings | None = None,
    store: TokenStore | None = None,
    transport: httpx.AsyncBaseTransport | None = None,  # injecté par les tests
) -> FastAPI:
    settings = settings or get_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        app.state.http = httpx.AsyncClient(timeout=20, transport=transport)
        yield
        await app.state.http.aclose()

    app = FastAPI(title="WaxMatch API", version="0.1.0", lifespan=lifespan)
    app.state.settings = settings
    app.state.store = store or InMemoryTokenStore()
    app.state.library_cache = {}

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

    @app.get("/health", tags=["meta"])
    async def health():
        return {"status": "ok"}

    return app


# Lancement : uvicorn app.main:create_app --factory --host 0.0.0.0 --port 8000
