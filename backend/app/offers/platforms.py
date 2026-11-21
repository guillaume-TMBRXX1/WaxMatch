"""Configuration des Actors Apify et conversion de leurs résultats en `Listing`.

Formats calibrés sur de vrais runs (novembre 2026) :
- Vinted   : piotrv1001/vinted-listings-scraper
- Leboncoin : piotrv1001/leboncoin-listings-scraper
"""

import re
from collections.abc import Callable
from dataclasses import dataclass

from app.offers.models import Listing

PROXY = {"useApifyProxy": True, "apifyProxyGroups": ["RESIDENTIAL"]}

_FORMATS = [
    (re.compile(r"\b(?:3|triple)\s*(?:x\s*)?lp\b|\b3lp\b", re.I), "3LP"),
    (re.compile(r"\b(?:2|double)\s*(?:x\s*)?lp\b|\b2lp\b|\bdouble (?:album|vinyle)\b", re.I), "2LP"),
    (re.compile(r"\b33\s*(?:t\b|tours?\b|rpm\b)", re.I), "33T"),
    (re.compile(r"\b45\s*(?:t\b|tours?\b|rpm\b)", re.I), "45T"),
    (re.compile(r"\bmaxi\b", re.I), "Maxi 45T"),
    (re.compile(r"\blp\b", re.I), "LP"),
]


def format_hint(title: str) -> str | None:
    for pattern, label in _FORMATS:
        if pattern.search(title):
            return label
    return None


def _num(value) -> float | None:
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def parse_vinted(item: dict) -> Listing | None:
    if not item.get("id") or not item.get("url"):
        return None
    photos = item.get("photos") or []
    main = next((p for p in photos if p.get("isMain")), photos[0] if photos else {})
    seller = item.get("seller") or {}
    price, total = _num(item.get("price")), _num(item.get("totalPrice"))
    return Listing(
        platform="vinted",
        external_id=str(item["id"]),
        title=item.get("title") or "",
        url=item["url"],
        price=price,
        currency=item.get("currency") or "EUR",
        buyer_fee=round(total - price, 2) if price is not None and total is not None else None,
        total_known=total if total is not None else price,
        condition=item.get("condition"),
        photo_url=main.get("url"),
        format_hint=format_hint(item.get("title") or ""),
        shippable=True,  # Vinted : envoi uniquement
        seller_name=seller.get("username"),
        seller_is_pro=seller.get("isBusiness"),
        published_at=item.get("scrapedAt"),
    )


def parse_leboncoin(item: dict) -> Listing | None:
    if not item.get("listId") or not item.get("url"):
        return None
    loc = item.get("location") or {}
    seller = item.get("seller") or {}
    price = _num(item.get("price"))
    fee_cents = _num(item.get("buyerFee"))
    fee = round(fee_cents / 100, 2) if fee_cents is not None else None
    shippable = item.get("shippable")
    return Listing(
        platform="leboncoin",
        external_id=str(item["listId"]),
        title=item.get("title") or "",
        url=item["url"],
        price=price,
        buyer_fee=fee if shippable else None,
        # Protection acheteur seulement en cas d'envoi ; en main propre on paie le prix affiché.
        total_known=(price + fee) if price is not None and fee is not None and shippable else price,
        condition=item.get("condition"),
        format_hint=format_hint(item.get("title") or ""),
        city=loc.get("city"),
        zipcode=loc.get("zipcode"),
        department=loc.get("department"),
        latitude=_num(loc.get("latitude")),
        longitude=_num(loc.get("longitude")),
        shippable=shippable,
        seller_name=seller.get("name"),
        seller_is_pro=(seller.get("type") == "pro") if seller.get("type") else None,
        seller_rating=_num(seller.get("ratingScore")),
        seller_rating_count=seller.get("ratingCount"),
        published_at=item.get("firstPublicationDate"),
    )


@dataclass(frozen=True)
class PlatformConfig:
    actor_id: str
    build_input: Callable[[str, int], dict]
    parse: Callable[[dict], Listing | None]


PLATFORMS: dict[str, PlatformConfig] = {
    "vinted": PlatformConfig(
        actor_id="piotrv1001/vinted-listings-scraper",
        build_input=lambda query, n: {
            "domain": "vinted.fr",
            "searchQueries": [query],
            "maxItems": n,
            "includeSellerDetails": False,
            "order": "newest_first",
            "proxyConfiguration": PROXY,
        },
        parse=parse_vinted,
    ),
    "leboncoin": PlatformConfig(
        actor_id="piotrv1001/leboncoin-listings-scraper",
        build_input=lambda query, n: {
            "searchQueries": [query],
            "maxItems": n,
            "maxPages": 2,
            "includeDetails": False,
            "shippableOnly": False,  # on garde la remise en main propre
            "sort": "time",
            "proxyConfiguration": PROXY,
        },
        parse=parse_leboncoin,
    ),
}
