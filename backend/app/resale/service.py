"""Analyse de la liste de surveillance : recherche d'annonces, estimation de marge, journal d'opportunités."""

import time
from dataclasses import asdict, dataclass, field

from app.discogs.client import DiscogsClient
from app.discogs.models import AlbumOffers, DiscogsMatch
from app.discogs.service import album_offers
from app.discogs.service import DiscogsStore
from app.geo import Geocoder
from app.offers.apify import ApifyClient
from app.offers.ebay import EbayClient
from app.offers.service import OffersStore, album_listings
from app.resale.evaluate import resale_estimate, risks_for
from app.resale.models import Opportunity, WatchItem
from app.resale.store import ResaleStore
from app.spotify.normalize import LibraryAlbum
from app.user_settings import APIFY_PLATFORMS, UserSettings

DISCOGS_VALUE_TTL = 7 * 24 * 3600  # la cote bouge lentement : une fois par semaine suffit


@dataclass
class ResaleContext:
    resale: ResaleStore
    offers: OffersStore
    discogs_store: DiscogsStore
    user_settings: UserSettings
    discogs: DiscogsClient | None = None
    apify: ApifyClient | None = None
    ebay: EbayClient | None = None
    geocoder: Geocoder | None = None
    max_items: int = 20
    cache_hours: float = 24


@dataclass
class ResaleJob:
    running: bool = False
    phase: str = "en attente"
    total: int = 0
    done: int = 0
    opportunities: int = 0
    new_opportunities: int = 0
    gone: int = 0
    apify_runs: int = 0
    errors: int = 0
    last_error: str | None = None
    started_at: float | None = None
    finished_at: float | None = None
    new_keys: list[str] = field(default_factory=list)

    def status(self) -> dict:
        data = asdict(self)
        data.pop("new_keys")
        return data


def to_album(item: WatchItem) -> LibraryAlbum:
    return LibraryAlbum(
        spotify_id=f"discogs-{item.discogs_id}",
        title=item.title,
        title_clean=item.title,
        artists=[item.artist],
        primary_artist=item.artist,
        artist_ids=[],
        album_type="album",
        release_year=item.year,
        cover_url=item.cover_url,
        genres=item.genres,
        styles=item.styles,
        match_key=item.key,
        search_query=f"{item.artist} {item.title}",
    )


async def discogs_value(ctx: ResaleContext, item: WatchItem) -> AlbumOffers | None:
    cached = ctx.discogs_store.get_offers(item.key)
    if cached and cached.price_suggestions is not None and time.time() - cached.checked_at < DISCOGS_VALUE_TTL:
        return cached
    if ctx.discogs is None:
        return cached
    match = DiscogsMatch(found=True, kind="master", id=item.discogs_id, title=f"{item.artist} - {item.title}",
                         genres=item.genres, styles=item.styles, cover_url=item.cover_url)
    ctx.discogs_store.put(item.key, match)
    offers = await album_offers(ctx.discogs, match)
    await ctx.discogs_store.put_offers(item.key, offers)
    return offers


async def scan_item(ctx: ResaleContext, item: WatchItem, job: ResaleJob) -> None:
    rs = ctx.resale.settings
    offers = await discogs_value(ctx, item)
    album = to_album(item)

    # Budget : les plateformes Apify déjà en cache sont gratuites ; les autres consomment le quota du jour.
    max_age = ctx.cache_hours * 3600
    platforms = [p for p in rs.platforms if p != "ebay" or ctx.ebay is not None]
    paid = [p for p in platforms if p in APIFY_PLATFORMS and ctx.offers.get(p, item.key, max_age) is None]
    remaining = max(rs.daily_apify_runs - ctx.resale.apify_runs_today(), 0)
    if ctx.apify is None or len(paid) > remaining:
        platforms = [p for p in platforms if p not in paid]  # quota atteint : on se contente du cache et d'eBay
        paid = []
    if not platforms:
        return
    settings = ctx.user_settings.model_copy(update={"platforms": platforms})
    result = await album_listings(
        ctx.apify, ctx.offers, album, settings, ctx.max_items, ctx.cache_hours,
        geocoder=ctx.geocoder, discogs_offers=offers, ebay=ctx.ebay if "ebay" in platforms else None,
    )
    executed = sum(1 for s in result.searches if s.platform in paid and not s.from_cache)
    await ctx.resale.add_apify_runs(executed)
    job.apify_runs += executed
    for s in result.searches:
        if s.error:
            job.errors += 1
            job.last_error = f"{s.platform} : {s.error}"[:200]

    vinted = [(l.external_id, l.price) for s in result.searches if s.platform == "vinted" for l in s.listings if l.price]
    suggestions = offers.price_suggestions if offers else None
    seen: set[str] = set()
    for listing in result.listings:
        if listing.delivered_total is None:
            continue
        comparables = [p for ext, p in vinted if ext != listing.external_id]
        value, basis, grade = resale_estimate(listing, suggestions, comparables, rs)
        if value is None:
            continue
        buy = listing.delivered_total
        margin = round(value - buy - rs.packaging, 2)
        roi = round(margin / buy, 2) if buy else 0.0
        if margin < rs.min_margin or roi < rs.min_roi or buy > rs.max_buy:
            continue
        opp = Opportunity(
            key=f"{listing.platform}:{listing.external_id}",
            watch_key=item.key,
            artist=item.artist,
            title=item.title,
            cover_url=item.cover_url,
            listing=listing,
            grade=grade,
            buy_total=buy,
            resale_estimate=value,
            resale_basis=basis,
            margin=margin,
            roi=roi,
            demand=item.demand,
            risks=risks_for(listing),
        )
        seen.add(opp.key)
        job.opportunities += 1
        if await ctx.resale.upsert_opportunity(opp):
            job.new_opportunities += 1
            job.new_keys.append(opp.key)
    job.gone += await ctx.resale.mark_gone(item.key, seen)


async def run_resale_scan(ctx: ResaleContext, job: ResaleJob, limit: int) -> None:
    """Analyse les disques surveillés jamais analysés d'abord, puis les plus anciennement analysés."""
    items = sorted(ctx.resale.watchlist.values(), key=lambda i: (i.last_scanned is not None, i.last_scanned or 0))
    items = items[:limit]
    job.running, job.phase, job.total, job.started_at = True, "analyse des annonces", len(items), time.time()
    try:
        for item in items:
            try:
                await scan_item(ctx, item, job)
            except Exception as exc:  # noqa: BLE001 - un disque en échec n'arrête pas l'analyse
                job.errors += 1
                job.last_error = str(exc)[:200]
            item.last_scanned = time.time()
            await ctx.resale.save_item(item)
            job.done += 1
    finally:
        job.running, job.phase, job.finished_at = False, "terminé", time.time()
