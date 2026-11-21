"""Configuration des Actors Apify et conversion de leurs résultats en `Listing`.

Formats calibrés sur de vrais runs (novembre 2026) :
- Vinted   : piotrv1001/vinted-listings-scraper
- Leboncoin : piotrv1001/leboncoin-listings-scraper
- 2ememain : piotrv1001/2ememain-listings-scraper (Belgique)
"""

import re
from collections.abc import Callable
from dataclasses import dataclass

from app.offers.models import Listing

PROXY = {"useApifyProxy": True, "apifyProxyGroups": ["RESIDENTIAL"]}

_FORMATS = [
    (re.compile(r"\b12\s*(?:\"|''|pouces|inch)", re.I), "LP"),
    (re.compile(r"\b7\s*(?:\"|''|pouces|inch)", re.I), "45T (7\")"),
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
        published_at=None,  # l'Actor ne donne que la date de collecte, pas celle de publication
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
        country=loc.get("country") or "FR",
        latitude=_num(loc.get("latitude")),
        longitude=_num(loc.get("longitude")),
        shippable=shippable,
        seller_name=seller.get("name"),
        seller_is_pro=(seller.get("type") == "pro") if seller.get("type") else None,
        seller_rating=_num(seller.get("ratingScore")),
        seller_rating_count=seller.get("ratingCount"),
        published_at=item.get("firstPublicationDate"),
    )


_2EMEMAIN_ID = re.compile(r"/(m\d+)-")
_NO_PRICE = {"SEE_DESCRIPTION", "NOTK", "RESERVED", "EXCHANGE", "FREE"}


def parse_2ememain(item: dict) -> Listing | None:
    url = item.get("url")
    if not url:
        return None
    found = _2EMEMAIN_ID.search(url)
    price_type = item.get("priceType")
    price = _num(item.get("price"))
    if price_type in _NO_PRICE and not price:
        price = None
    return Listing(
        platform="2ememain",
        external_id=found.group(1) if found else url,
        title=item.get("title") or "",
        url=url,
        price=price,
        price_type=price_type,
        total_known=price,  # pas de frais acheteur sur 2ememain
        photo_url=item.get("imageUrl"),
        format_hint=format_hint(item.get("title") or ""),
        city=item.get("city"),
        country="BE",
        seller_name=item.get("sellerName"),
        seller_is_pro=item.get("isCommercialAd"),
        published_at=item.get("date"),
    )


VINTED_DOMAINS = {"BE": "vinted.be", "FR": "vinted.fr", "LU": "vinted.lu", "NL": "vinted.nl", "ES": "vinted.es"}


@dataclass(frozen=True)
class PlatformConfig:
    actor_id: str
    build_input: Callable[[str, int, str], dict]  # (recherche, nb max, pays de l'acheteur)
    parse: Callable[[dict], Listing | None]


PLATFORMS: dict[str, PlatformConfig] = {
    "vinted": PlatformConfig(
        actor_id="piotrv1001/vinted-listings-scraper",
        build_input=lambda query, n, country: {
            "domain": VINTED_DOMAINS.get(country, "vinted.fr"),
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
        build_input=lambda query, n, country: {
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
    "2ememain": PlatformConfig(
        actor_id="piotrv1001/2ememain-listings-scraper",
        build_input=lambda query, n, country: {
            "searchQuery": query,
            "maxItems": n,
            "sort": "relevance",
            "includeDetails": False,
            "proxyConfiguration": {"useApifyProxy": True},
        },
        parse=parse_2ememain,
    ),
}
