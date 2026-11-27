"""API officielle eBay « Browse » : recherche d'annonces (gratuite, jeton applicatif OAuth).

Port réel vers le pays de l'acheteur (en-tête X-EBAY-C-ENDUSERCTX), vendeurs hors UE signalés
(douane et TVA à l'import).
"""

import base64
import re
import time

import httpx

from app.offers.models import Listing
from app.offers.platforms import format_hint

TOKEN_URL = "https://api.ebay.com/identity/v1/oauth2/token"
SEARCH_URL = "https://api.ebay.com/buy/browse/v1/item_summary/search"
SCOPE = "https://api.ebay.com/oauth/api_scope"

EU = {
    "AT", "BE", "BG", "HR", "CY", "CZ", "DK", "EE", "FI", "FR", "DE", "GR", "HU", "IE", "IT", "LV", "LT",
    "LU", "MT", "NL", "PL", "PT", "RO", "SK", "SI", "ES", "SE",
}
# Site eBay interrogé selon le pays de l'acheteur.
MARKETPLACES = {"BE": "EBAY_BE", "FR": "EBAY_FR", "NL": "EBAY_NL", "DE": "EBAY_DE", "LU": "EBAY_FR"}


class EbayError(Exception):
    pass


class EbayClient:
    def __init__(self, http: httpx.AsyncClient, client_id: str, client_secret: str):
        self.http = http
        self.client_id = client_id
        self.client_secret = client_secret
        self._token: str | None = None
        self._expires = 0.0

    async def _access_token(self) -> str:
        if self._token and time.time() < self._expires - 60:
            return self._token
        basic = base64.b64encode(f"{self.client_id}:{self.client_secret}".encode()).decode()
        resp = await self.http.post(
            TOKEN_URL,
            data={"grant_type": "client_credentials", "scope": SCOPE},
            headers={"Authorization": f"Basic {basic}", "Content-Type": "application/x-www-form-urlencoded"},
        )
        if resp.status_code != 200:
            raise EbayError(f"Jeton eBay refusé ({resp.status_code}) : vérifie EBAY_CLIENT_ID / EBAY_CLIENT_SECRET")
        data = resp.json()
        self._token = data["access_token"]
        self._expires = time.time() + int(data.get("expires_in", 7200))
        return self._token

    async def search(
        self,
        query: str,
        limit: int = 20,
        country: str = "BE",
        zip_code: str | None = None,
        marketplace: str | None = None,
        newest_first: bool = False,
    ) -> list[dict]:
        """`marketplace` : site eBay interrogé (EBAY_DE…) ; le port reste calculé vers `country`."""
        ctx = f"contextualLocation=country={country}" + (f",zip={zip_code}" if zip_code else "")
        params = {"q": query, "limit": min(limit, 200), "filter": "buyingOptions:{FIXED_PRICE|BEST_OFFER}"}
        if newest_first:
            params["sort"] = "newlyListed"
        try:
            resp = await self.http.get(
                SEARCH_URL,
                params=params,
                headers={
                    "Authorization": f"Bearer {await self._access_token()}",
                    "X-EBAY-C-MARKETPLACE-ID": marketplace or MARKETPLACES.get(country, "EBAY_DE"),
                    "X-EBAY-C-ENDUSERCTX": ctx,
                },
                timeout=30,
            )
        except httpx.HTTPError as exc:
            raise EbayError(f"eBay injoignable : {exc}") from exc
        if resp.status_code != 200:
            raise EbayError(f"eBay {resp.status_code} : {resp.text[:200]}")
        return resp.json().get("itemSummaries", [])


def _money(data: dict | None) -> float | None:
    try:
        return float(data["value"]) if data and data.get("value") is not None else None
    except (TypeError, ValueError):
        return None


_ITEM_ID = re.compile(r"v1\|(\d+)\|")


def parse_ebay(item: dict) -> Listing | None:
    if not item.get("itemWebUrl") or not item.get("title"):
        return None
    price = _money(item.get("price"))
    shipping_options = item.get("shippingOptions") or []
    costs = [_money(o.get("shippingCost")) for o in shipping_options if o.get("shippingCost")]
    shipping = min((c for c in costs if c is not None), default=None)
    location = item.get("itemLocation") or {}
    country = location.get("country")
    seller = item.get("seller") or {}
    raw_id = item.get("itemId", "")
    found = _ITEM_ID.search(raw_id)
    rating = seller.get("feedbackPercentage")
    return Listing(
        platform="ebay",
        external_id=found.group(1) if found else raw_id or item["itemWebUrl"],
        title=item["title"],
        url=item["itemWebUrl"],
        price=price,
        currency=(item.get("price") or {}).get("currency", "EUR"),
        total_known=price,
        shipping_cost=shipping,  # None : port non communiqué pour ce pays
        condition=item.get("condition"),
        photo_url=(item.get("image") or {}).get("imageUrl"),
        format_hint=format_hint(item["title"]),
        city=location.get("city"),
        zipcode=location.get("postalCode"),
        country=country,
        # Hors UE : douane et TVA à l'import, on ne le considère pas comme livrable « simplement ».
        shippable=bool(shipping_options) and (country is None or country in EU),
        seller_name=seller.get("username"),
        seller_rating=float(rating) / 100 if rating else None,
        seller_rating_count=seller.get("feedbackScore"),
    )
