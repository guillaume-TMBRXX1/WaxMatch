"""Liste de surveillance : vinyles à forte demande sur Discogs (want), plus rares que demandés."""

import math

from app.discogs.client import DiscogsClient
from app.discogs.service import split_discogs_title
from app.resale.models import ResaleSettings, WatchItem
from app.spotify.normalize import clean_title, match_key
import re

_DISAMBIGUATION = re.compile(r"\s*\(\d+\)")
_ANV = re.compile(r"\*")


def demand_score(want: int, have: int) -> float:
    """Demande (want, échelle logarithmique) pondérée par la rareté (want / have)."""
    if want <= 0:
        return 0.0
    scarcity = min(want / max(have, 1), 2.0)
    return round(math.log10(want + 1) * 100 * (0.5 + scarcity), 1)


def item_from_result(result: dict) -> WatchItem | None:
    artist, title = split_discogs_title(result.get("title", ""))
    artist = _ANV.sub("", _DISAMBIGUATION.sub("", artist)).strip()
    if not artist or not title or artist.lower() in {"various", "various artists"}:
        return None  # compilations : trop ambiguës pour la revente
    community = result.get("community") or {}
    want, have = int(community.get("want") or 0), int(community.get("have") or 0)
    year = str(result.get("year") or "")
    return WatchItem(
        key=match_key(artist, title),
        artist=artist,
        title=clean_title(title),
        discogs_id=int(result["id"]),
        year=int(year) if year.isdigit() else None,
        genres=result.get("genre") or [],
        styles=result.get("style") or [],
        cover_url=result.get("cover_image") or None,
        want=want,
        have=have,
        demand=demand_score(want, have),
    )


async def build_watchlist(client: DiscogsClient, settings: ResaleSettings, pages_per_style: int = 6) -> list[WatchItem]:
    """Interroge Discogs par style (fiches « master », vinyle, triées par demande) et garde les plus demandés."""
    queries = [{"genre": settings.genre, "style": style} for style in settings.styles]
    queries += [{"genre": genre} for genre in settings.extra_genres]
    found: dict[str, WatchItem] = {}
    for query in queries:
        pages = pages_per_style if "style" in query else 1
        for page in range(1, pages + 1):
            results = await client.search(
                type="master", format="Vinyl", per_page=100, page=page, sort="want", sort_order="desc", **query
            )
            for result in results:
                item = item_from_result(result)
                if item and (item.key not in found or found[item.key].demand < item.demand):
                    found[item.key] = item
            if len(results) < 100:
                break
    ranked = sorted(found.values(), key=lambda i: i.demand, reverse=True)
    return ranked[: settings.watchlist_size]
