import asyncio
import time
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request

from app.deps import get_spotify
from app.resale.models import Opportunity, ResaleSettings, WatchItem
from app.resale.service import ResaleContext, ResaleJob, run_resale_scan
from app.resale.watchlist import build_watchlist
from app.spotify.client import SpotifyClient

router = APIRouter(prefix="/resale", tags=["resale"])


def _discogs(request: Request):
    from app.deps import get_discogs

    state = request.app.state
    return get_discogs(request, state.settings, state.http) if state.settings.discogs_token else None


def _apify(request: Request):
    from app.offers.apify import ApifyClient

    token = request.app.state.settings.apify_token
    return ApifyClient(request.app.state.http, token) if token else None


async def _context(request: Request, spotify: SpotifyClient) -> ResaleContext:
    state = request.app.state
    user = await state.settings_store.get(spotify.tokens.spotify_user_id or spotify.session_id)
    return ResaleContext(
        resale=state.resale_store,
        offers=state.offers_store,
        discogs_store=state.discogs_store,
        user_settings=user,
        discogs=_discogs(request),
        apify=_apify(request),
        ebay=state.ebay,
        geocoder=state.geocoder,
        max_items=state.settings.apify_max_items,
        cache_hours=state.settings.offers_cache_hours,
    )


@router.get("/settings", response_model=ResaleSettings)
async def read_settings(request: Request, spotify: SpotifyClient = Depends(get_spotify)):
    return request.app.state.resale_store.settings


@router.put("/settings", response_model=ResaleSettings)
async def update_settings(body: ResaleSettings, request: Request, spotify: SpotifyClient = Depends(get_spotify)):
    await request.app.state.resale_store.save_settings(body)
    return body


@router.get("/watchlist", response_model=list[WatchItem])
async def read_watchlist(request: Request, limit: int = Query(100, ge=1, le=2000), spotify=Depends(get_spotify)):
    items = sorted(request.app.state.resale_store.watchlist.values(), key=lambda i: i.demand, reverse=True)
    return items[:limit]


@router.post("/watchlist/build")
async def start_build(request: Request, spotify: SpotifyClient = Depends(get_spotify)):
    """(Re)construit la liste de surveillance depuis Discogs (gratuit). Suivi : GET /resale/status."""
    state = request.app.state
    job: ResaleJob = state.resale_job
    if job.running:
        return job.status()
    discogs = _discogs(request)
    if discogs is None:
        raise HTTPException(status_code=503, detail="Discogs non configuré : ajoute le secret DISCOGS_TOKEN")
    job.__init__()
    job.running, job.phase, job.started_at = True, "liste de surveillance (Discogs)", time.time()

    async def run() -> None:
        try:
            items = await build_watchlist(discogs, state.resale_store.settings)
            await state.resale_store.replace_watchlist(items)
            job.total = job.done = len(items)
        except Exception as exc:  # noqa: BLE001
            job.errors, job.last_error = 1, str(exc)[:200]
        finally:
            job.running, job.phase, job.finished_at = False, "terminé", time.time()

    state.resale_task = asyncio.create_task(run())
    return job.status()


@router.post("/scan")
async def start_scan(
    request: Request,
    limit: int = Query(10, ge=1, le=500, description="Disques de la liste à analyser"),
    spotify: SpotifyClient = Depends(get_spotify),
):
    """Cherche des annonces pour les disques surveillés (eBay gratuit ; Apify dans la limite du plafond du jour)."""
    state = request.app.state
    job: ResaleJob = state.resale_job
    if job.running:
        return job.status()
    if not state.resale_store.watchlist:
        raise HTTPException(status_code=409, detail="Liste de surveillance vide : construis-la d'abord")
    ctx = await _context(request, spotify)
    job.__init__()
    job.running, job.phase = True, "préparation"
    state.resale_task = asyncio.create_task(run_resale_scan(ctx, job, limit))
    return job.status()


@router.get("/status")
async def scan_status(request: Request):
    return request.app.state.resale_job.status()


@router.get("/opportunities", response_model=list[Opportunity])
async def list_opportunities(
    request: Request,
    status: Literal["active", "disparue", "toutes"] = "active",
    sort: Literal["margin", "roi", "recent", "demand"] = "margin",
    min_margin: float = 0,
    spotify: SpotifyClient = Depends(get_spotify),
):
    opps = [
        o for o in request.app.state.resale_store.opportunities.values()
        if (status == "toutes" or o.status == status) and o.margin >= min_margin
    ]
    key = {"margin": lambda o: o.margin, "roi": lambda o: o.roi, "recent": lambda o: o.first_seen,
           "demand": lambda o: o.demand}[sort]
    return sorted(opps, key=key, reverse=True)


@router.get("/stats")
async def stats(request: Request, spotify: SpotifyClient = Depends(get_spotify)):
    """Journal d'observation : mesurer la rentabilité potentielle avant d'acheter."""
    store = request.app.state.resale_store
    opps = list(store.opportunities.values())
    active = [o for o in opps if o.status == "active"]
    gone = [o for o in opps if o.status == "disparue"]
    week_ago = time.time() - 7 * 24 * 3600
    return {
        "watched": len(store.watchlist),
        "scanned": sum(1 for i in store.watchlist.values() if i.last_scanned),
        "active": len(active),
        "active_margin_total": round(sum(o.margin for o in active), 2),
        "best_margin": max((o.margin for o in active), default=0),
        "seen_total": len(opps),
        "seen_last_7_days": sum(1 for o in opps if o.first_seen >= week_ago),
        "margin_seen_last_7_days": round(sum(o.margin for o in opps if o.first_seen >= week_ago), 2),
        # Disparues rapidement = vendues vite : signe que ces affaires existent et partent vite.
        "gone": len(gone),
        "observing_since": min((o.first_seen for o in opps), default=None),
        "apify_runs_today": store.apify_runs_today(),
        "apify_daily_cap": store.settings.daily_apify_runs,
        "ebay_configured": request.app.state.ebay is not None,
    }
