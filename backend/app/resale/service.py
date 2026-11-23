"""Analyse de la liste de surveillance : recherche d'annonces, estimation de marge, journal d'opportunités."""

import time
from statistics import median
from dataclasses import asdict, dataclass, field

from app.discogs.client import DiscogsClient
from app.discogs.models import AlbumOffers, DiscogsMatch
from app.discogs.service import album_offers
from app.discogs.service import DiscogsStore
from app.geo import Geocoder
from app.offers.apify import ApifyClient
from app.offers.ebay import EbayClient
from app.offers.apify import ApifyError
from app.offers.platforms import PLATFORMS
from app.offers.scoring import discogs_reference_price, score_listings
from app.offers.service import OffersStore, album_listings, judge
from app.spotify.normalize import artist_key, fold
from app.offers.quality import assess_quality, grade_at_least
from app.resale.evaluate import resale_estimate, risks_for
from app.resale.models import Comparable, Opportunity, WatchItem
from app.resale.store import ResaleStore
from app.resale.watchlist import item_from_result
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
    discovered: int = 0  # albums ajoutés à la liste lors du balayage
    last_error: str | None = None
    started_at: float | None = None
    finished_at: float | None = None
    new_keys: list[str] = field(default_factory=list)
    filtered: dict[str, int] = field(default_factory=dict)  # annonces écartées, par raison

    def status(self) -> dict:
        data = asdict(self)
        data.pop("new_keys")
        data["filtered_total"] = sum(self.filtered.values())
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


def _comparables(listings, exclude_id: str | None = None) -> list[Comparable]:
    comps = [
        Comparable(platform=l.platform, title=l.title, url=l.url, price=l.price, condition=l.condition)
        for l in listings
        if l.platform == "vinted" and l.price and l.external_id != exclude_id
    ]
    return sorted(comps, key=lambda c: c.price)


async def evaluate_candidates(
    ctx: ResaleContext,
    item: WatchItem,
    listings,
    comparables: list[Comparable],
    offers: AlbumOffers | None,
    job: ResaleJob,
    source: str,
) -> list[tuple[Opportunity, bool]]:
    """Évalue des annonces déjà classées (prix livré connu) ; enregistre les opportunités retenues."""
    rs = ctx.resale.settings
    suggestions = offers.price_suggestions if offers else None
    results: list[tuple[Opportunity, bool]] = []
    for listing in listings:
        if listing.delivered_total is None:
            continue
        reason = quality_rejection(listing, rs)
        if reason:
            job.filtered[reason] = job.filtered.get(reason, 0) + 1
            continue
        comps = [c for c in comparables if c.url != listing.url]
        if rs.require_vinted_comparables and len(comps) < rs.min_comparables:
            job.filtered["comparables Vinted insuffisants"] = job.filtered.get("comparables Vinted insuffisants", 0) + 1
            continue
        value, basis, grade = resale_estimate(listing, suggestions, [c.price for c in comps], rs)
        if value is None:
            job.filtered["pas de référence de prix"] = job.filtered.get("pas de référence de prix", 0) + 1
            continue
        buy = listing.delivered_total
        margin = round(value - buy - rs.packaging, 2)
        roi = round(margin / buy, 2) if buy else 0.0
        if margin < rs.min_margin or roi < rs.min_roi or buy > rs.max_buy:
            job.filtered["marge insuffisante"] = job.filtered.get("marge insuffisante", 0) + 1
            continue
        risks = risks_for(listing)
        if roi >= 3:
            risks.append("Prix anormalement bas : arnaque, erreur ou mauvaise identification ? Vérifier")
        if len(comps) < 3:
            risks.append("Peu d'annonces Vinted comparables : estimation fondée sur la cote Discogs")
        envoi = listing.delivery_mode == "envoi"
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
            risks=risks,
            source=source,
            buy_price=listing.price,
            buy_fee=listing.buyer_fee if envoi else 0.0,
            buy_shipping=listing.shipping_estimate if envoi else 0.0,
            delivery_mode=listing.delivery_mode,
            packaging=rs.packaging,
            comparables=comps[:12],
            vinted_median=round(median([c.price for c in comps]), 2) if comps else None,
            discogs_by_condition=suggestions or {},
            discogs_lowest=offers.best_price if offers else None,
            discogs_for_sale=offers.total_for_sale if offers else None,
            discogs_url=f"https://www.discogs.com/sell/list?master_id={item.discogs_id}&format=Vinyl",
        )
        is_new = await ctx.resale.upsert_opportunity(opp)
        job.opportunities += 1
        if is_new:
            job.new_opportunities += 1
            job.new_keys.append(opp.key)
        results.append((opp, is_new))
    return results


async def scan_item(ctx: ResaleContext, item: WatchItem, job: ResaleJob) -> None:
    """Analyse « disque par disque » : une recherche par plateforme pour ce disque."""
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

    comparables = _comparables([l for s in result.searches for l in s.listings])
    found = await evaluate_candidates(ctx, item, result.listings, comparables, offers, job, "disque")
    job.gone += await ctx.resale.mark_gone(item.key, {opp.key for opp, _ in found})


async def run_sweep(ctx: ResaleContext, job: ResaleJob) -> None:
    """Balayage large : quelques recherches par style (dernières annonces), rapprochées de la liste de
    surveillance (et d'albums découverts), puis vérification par les prix Vinted AVANT de proposer quoi que ce soit."""
    rs = ctx.resale.settings
    job.running, job.phase, job.started_at = True, "balayage des annonces", time.time()
    try:
        listings = await _sweep_listings(ctx, job, rs)
        job.phase = "rapprochement avec la liste de surveillance"
        matches = _match_watchlist(ctx, listings)
        if rs.discover_new_albums and ctx.discogs is not None:
            job.phase = "découverte d'albums (Discogs)"
            matched_ids = {id(l) for found in matches.values() for l in found}
            await _discover(ctx, job, rs, [l for l in listings if id(l) not in matched_ids], matches)
        job.total = len(matches)

        # 1) Préparation : prix livré, comparables déjà connus, potentiel (cote Discogs) pour prioriser.
        job.phase = "préparation"
        prepared = []
        for key, found in matches.items():
            item = ctx.resale.watchlist[key]
            try:
                offers = await discogs_value(ctx, item)
                ranked, _ = score_listings(
                    found, ctx.user_settings, discogs_reference_price(offers),
                    price_suggestions=offers.price_suggestions if offers else None,
                )
                cached = ctx.offers.get("vinted", key, 7 * 24 * 3600)
                comps = _comparables(found + (cached.listings if cached else []))
                prepared.append([item, offers, ranked, comps, _potential(ranked, offers, rs)])
            except Exception as exc:  # noqa: BLE001
                job.errors += 1
                job.last_error = str(exc)[:200]

        # 2) Vérification : pour les disques prometteurs sans assez de comparables, recherche Vinted dédiée.
        to_verify = sorted(
            (p for p in prepared if len(p[3]) < rs.min_comparables and p[4] >= rs.min_margin),
            key=lambda p: p[4], reverse=True,
        )[: rs.verify_top]
        for entry in to_verify:
            if ctx.apify is None or ctx.resale.apify_runs_today() >= rs.daily_apify_runs:
                job.last_error = "Plafond Apify atteint : vérification partielle"
                break
            job.phase = "vérification par les prix Vinted"
            settings = ctx.user_settings.model_copy(update={"platforms": ["vinted"]})
            result = await album_listings(ctx.apify, ctx.offers, to_album(entry[0]), settings, ctx.max_items, ctx.cache_hours)
            if any(not s.from_cache for s in result.searches):
                await ctx.resale.add_apify_runs(1)
                job.apify_runs += 1
            seen = {c.url for c in entry[3]}
            entry[3] = entry[3] + [c for c in _comparables([l for s in result.searches for l in s.listings]) if c.url not in seen]

        # 3) Évaluation, avec les comparables Vinted exigés.
        job.phase = "évaluation"
        for item, offers, ranked, comps, _ in prepared:
            await evaluate_candidates(ctx, item, ranked, comps, offers, job, "balayage")
            job.done += 1
    finally:
        job.running, job.phase, job.finished_at = False, "terminé", time.time()


def _potential(ranked, offers: AlbumOffers | None, rs) -> float:
    """Meilleure marge possible d'après la cote Discogs : sert seulement à choisir quoi vérifier."""
    from app.resale.evaluate import graded_price

    suggestions = offers.price_suggestions if offers else None
    best = -1e9
    for listing in ranked:
        cote = graded_price(listing.grade or "VG", suggestions)
        if cote and listing.delivered_total is not None:
            best = max(best, cote * rs.discogs_to_vinted - listing.delivered_total - rs.packaging)
    return best


_GENERIC_WORDS = set(
    "vinyle vinyles vinyl vinyls lp lps 2lp 3lp ep maxi 33t 45t 33 45 tours tour rpm disque disques album original originale "
    "pressage press edition reissue neuf tres bon etat used de du des la le les et the a".split()
)


async def _discover(ctx: ResaleContext, job: ResaleJob, rs, listings: list, matches: dict[str, list]) -> None:
    """Annonce d'un artiste suivi pour un album absent de la liste : recherche Discogs, ajout si demandé."""
    artists = {artist_key(i.artist) for i in ctx.resale.watchlist.values() if artist_key(i.artist)}
    queries: dict[str, list[dict]] = {}
    lookups = 0
    for listing in listings:
        quality = assess_quality(listing)
        if quality.blocking or not quality.confirmed:
            continue
        text = fold(listing.title)
        if not any(f" {a} " in f" {text} " for a in artists):
            continue
        query = " ".join(w for w in text.split() if w not in _GENERIC_WORDS and not w.isdigit())
        if query not in queries:
            if lookups >= rs.discovery_max_lookups:
                continue
            lookups += 1
            try:
                queries[query] = await ctx.discogs.search(q=query, type="master", format="Vinyl", per_page=5)
            except Exception as exc:  # noqa: BLE001
                job.errors += 1
                job.last_error = str(exc)[:200]
                queries[query] = []
        for result in queries[query]:
            item = item_from_result(result)
            if item is None or item.want < rs.discovery_min_want:
                continue
            if item.key not in ctx.resale.watchlist:
                if not judge(to_album(item), listing)[0]:
                    continue
                item.discovered = True
                await ctx.resale.save_item(item)
                job.discovered += 1
            if judge(to_album(ctx.resale.watchlist[item.key]), listing)[0]:
                matches.setdefault(item.key, []).append(listing)
                break


async def _sweep_listings(ctx: ResaleContext, job: ResaleJob, rs) -> list:
    from app.offers import platforms as platform_config

    listings: dict[tuple[str, str], object] = {}
    for platform in [p for p in ("vinted", "2ememain") if p in rs.platforms]:
        config = PLATFORMS[platform]
        for query in rs.sweep_queries:
            if ctx.apify is None or ctx.resale.apify_runs_today() >= rs.daily_apify_runs:
                job.last_error = (
                    f"Plafond Apify du jour atteint ({ctx.resale.apify_runs_today()}/{rs.daily_apify_runs} recherches) : "
                    "balayage partiel. Remise à zéro à minuit (heure de Bruxelles) ; le plafond se règle dans "
                    "« Réglages de la revente »."
                )
                return list(listings.values())
            try:
                items = await ctx.apify.run_actor(
                    config.actor_id, config.build_input(query, rs.sweep_max_items, ctx.user_settings.country)
                )
            except ApifyError as exc:
                job.errors += 1
                job.last_error = f"{platform} : {exc}"[:200]
                items = []
            await ctx.resale.add_apify_runs(1)
            job.apify_runs += 1
            for raw in items:
                listing = config.parse(raw)
                if listing is None:
                    continue
                if platform == "vinted" and platform_config.VINTED_CATALOG_IDS:
                    listing.vinyl_source = True
                listings.setdefault((platform, listing.external_id), listing)
    if ctx.geocoder is not None:
        for listing in listings.values():
            if listing.city and listing.latitude is None:
                found = await ctx.geocoder.geocode(listing.city, listing.country)
                if found:
                    listing.latitude, listing.longitude = found[0], found[1]
    return list(listings.values())


def _match_watchlist(ctx: ResaleContext, listings: list) -> dict[str, list]:
    """Associe chaque annonce aux disques surveillés (artiste présent, puis titre vérifié)."""
    items = [(i, artist_key(i.artist), to_album(i)) for i in ctx.resale.watchlist.values()]
    matches: dict[str, list] = {}
    for listing in listings:
        if assess_quality(listing).blocking:
            continue
        text = f" {fold(listing.title)} "
        for item, akey, album in items:
            if not akey or f" {akey} " not in text and f" {fold(item.artist)} " not in text:
                continue
            if judge(album, listing)[0]:
                matches.setdefault(item.key, []).append(listing)
                break
    return matches


def quality_rejection(listing, rs) -> str | None:
    """Raison d'écarter l'annonce selon les réglages de revente (None = on garde)."""
    q = assess_quality(listing)
    if q.blocking:
        return "pas un vinyle"
    if rs.require_confirmed_vinyl and not q.confirmed:
        return "vinyle non confirmé"
    if q.severe:
        return "défaut grave"
    if q.no_sleeve and not rs.allow_no_sleeve:
        return "sans pochette"
    if not grade_at_least(q.grade, rs.min_grade):
        return "état insuffisant"
    if q.is_lot and rs.exclude_lots:
        return "lot"
    if q.mixed_media and rs.exclude_mixed:
        return "annonce mixte"
    if rs.exclude_reissues and any("Réédition" in r for r in risks_for(listing)):
        return "réédition"
    return None


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
