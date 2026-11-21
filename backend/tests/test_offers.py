"""Annonces Vinted / Leboncoin via Apify (Actors simulés avec le format réel de leurs résultats)."""

import json
import time

import httpx
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app
from app.offers.models import Listing
from app.offers.platforms import format_hint, parse_leboncoin, parse_vinted
from app.offers.service import build_query, judge
from app.spotify.normalize import normalize_saved_item
from tests.test_api import fake_spotify

# Exemples réels (runs du 21/11/2026), raccourcis.
VINTED_ITEM = {
    "id": 10882993906,
    "title": "Maxi 45 Tours Syl johnson",
    "url": "https://www.vinted.fr/items/10882993906-maxi-45-tours-syl-johnson",
    "price": 5,
    "currency": "EUR",
    "totalPrice": 5.95,
    "condition": "Très bon état",
    "photos": [{"url": "https://images1.vinted.net/a.webp", "isMain": True}],
    "seller": {"id": 1, "username": "milanac1977", "isBusiness": False},
    "domain": "vinted.fr",
    "scrapedAt": "2026-11-21T21:18:46.376Z",
}
LBC_ITEM = {
    "listId": 3314830040,
    "title": "Miles Davis - The Man With The Horn - 33T - Vinyle Transparent",
    "url": "https://www.leboncoin.fr/ad/cd_musique/3314830040",
    "price": 12,
    "condition": "Très bon état",
    "location": {"city": "Lieuvillers", "zipcode": "60130", "department": "Oise", "latitude": 49.47, "longitude": 2.495},
    "seller": {"name": "Guts", "type": "private", "ratingScore": 0.99, "ratingCount": 122},
    "shippable": True,
    "firstPublicationDate": "2026-11-21 22:21:00",
    "buyerFee": 130,
}


def _album(artist, title):
    return normalize_saved_item(
        {"added_at": None, "album": {"id": "x", "name": title, "artists": [{"id": "a", "name": artist}]}}, {}
    )


def test_parse_real_items():
    v = parse_vinted(VINTED_ITEM)
    assert (v.price, v.total_known, v.buyer_fee) == (5, 5.95, 0.95)
    assert v.format_hint == "45T" and v.shippable is True and v.photo_url.endswith("a.webp")

    lbc = parse_leboncoin(LBC_ITEM)
    assert (lbc.price, lbc.buyer_fee, lbc.total_known) == (12, 1.3, 13.3)
    assert (lbc.city, lbc.zipcode, lbc.latitude) == ("Lieuvillers", "60130", 49.47)
    assert lbc.seller_rating == 0.99 and lbc.seller_is_pro is False and lbc.format_hint == "33T"

    pickup_only = parse_leboncoin({**LBC_ITEM, "shippable": False})
    assert pickup_only.total_known == 12 and pickup_only.buyer_fee is None  # main propre : pas de frais


def test_format_hint():
    assert format_hint("Daft Punk Discovery double LP") == "2LP"
    assert format_hint("vinyle 33 tours") == "33T"
    assert format_hint("Vinyle") is None


def _listing(title):
    return Listing(platform="vinted", external_id="1", title=title, url="u")


def test_judge():
    album = _album("Miles Davis", "The Man With The Horn")
    assert judge(album, parse_leboncoin(LBC_ITEM))[0]
    assert judge(album, _listing("CD Miles Davis The Man With The Horn"))[1].startswith("objet exclu")
    assert judge(album, _listing("Vinyle Miles Davis Kind of Blue"))[1] == "titre de l'album absent"
    assert judge(album, _listing("John Coltrane The Man With The Horn"))[1] == "artiste absent du titre"

    led = _album("Led Zeppelin", "II")
    assert judge(led, _listing("Led Zeppelin II vinyle 1969"))[0]
    assert not judge(led, _listing("Led Zeppelin IV vinyle"))[0]  # "II" ne doit pas matcher "IV"/"III"


def test_build_query():
    assert build_query(_album('Bobby "Blue" Bland', "Two Steps From The Blues (Remastered)")) == (
        "Bobby Bland Two Steps From The Blues vinyle"
    )


# --------------------------------------------------------------------------- API de bout en bout

VINTED_RESULTS = [
    {**VINTED_ITEM, "id": 1, "title": "Vinyle Daft Punk Discovery 2LP", "url": "https://v/1", "price": 30, "totalPrice": 32.2},
    {**VINTED_ITEM, "id": 2, "title": "CD Daft Punk Discovery", "url": "https://v/2", "price": 3, "totalPrice": 3.85},
    {**VINTED_ITEM, "id": 3, "title": "Daft Punk Homework vinyle", "url": "https://v/3"},
    {**VINTED_ITEM, "id": 1, "title": "Vinyle Daft Punk Discovery 2LP", "url": "https://v/1", "price": 30, "totalPrice": 32.2},
]
LBC_RESULTS = [
    {**LBC_ITEM, "listId": 9, "title": "Daft Punk - Discovery - 33T", "url": "https://l/9", "price": 20, "shippable": False},
]


class FakeApify:
    def __init__(self):
        self.calls: list[tuple[str, dict]] = []
        self.fail_vinted = False

    def __call__(self, request: httpx.Request) -> httpx.Response:
        if request.url.host != "api.apify.com":
            return fake_spotify(request)
        assert request.headers["Authorization"] == "Bearer AP"
        body = json.loads(request.content)
        actor = request.url.path.split("/")[3]
        self.calls.append((actor, body))
        if "vinted" in actor:
            if self.fail_vinted:
                return httpx.Response(402, json={"error": "payment required"})
            items = VINTED_RESULTS if "Daft Punk" in body["searchQueries"][0] else []
            return httpx.Response(201, json=items)
        items = LBC_RESULTS if "Daft Punk" in body["searchQueries"][0] else []
        return httpx.Response(201, json=items)


def _app(apify, **extra):
    settings = Settings(
        spotify_client_id="cid",
        spotify_client_secret="secret",
        spotify_redirect_uri="https://testserver/auth/callback",
        frontend_url="https://testserver/done",
        session_secret="s",
        cookie_secure=False,
        apify_token="AP",
        **extra,
    )
    return create_app(settings, transport=httpx.MockTransport(apify))


def _login(client):
    from urllib.parse import parse_qs, urlparse

    r = client.get("/auth/login", follow_redirects=False)
    state = parse_qs(urlparse(r.headers["location"]).query)["state"][0]
    client.get("/auth/callback", params={"code": "c", "state": state}, follow_redirects=False)


def test_album_offers_filter_sort_and_cache():
    apify = FakeApify()
    with TestClient(_app(apify), base_url="https://testserver") as client:
        _login(client)
        data = client.get("/offers/albums/al1").json()

        assert sorted(c[0] for c in apify.calls) == [
            "piotrv1001~leboncoin-listings-scraper",
            "piotrv1001~vinted-listings-scraper",
        ]
        vinted_input = next(body for actor, body in apify.calls if "vinted" in actor)
        assert vinted_input["searchQueries"] == ["Daft Punk Discovery vinyle"] and vinted_input["domain"] == "vinted.fr"

        # Leboncoin en main propre (20 €) avant Vinted (32,20 € protection incluse), doublon supprimé.
        assert [(l["platform"], l["total_known"]) for l in data["listings"]] == [("leboncoin", 20), ("vinted", 32.2)]
        vinted = next(s for s in data["searches"] if s["platform"] == "vinted")
        assert vinted["raw_count"] == 4
        assert sorted(r["reason"] for r in vinted["rejected"]) == ["objet exclu : « cd »", "titre de l'album absent"]

        # Deuxième appel : servi par le cache, aucun nouveau run Apify (donc aucun coût).
        again = client.get("/offers/albums/al1").json()
        assert len(apify.calls) == 2 and all(s["from_cache"] for s in again["searches"])
        client.get("/offers/albums/al1", params={"refresh": True, "platforms": "vinted"})
        assert len(apify.calls) == 3

        assert client.get("/offers/albums/inconnu").status_code == 404


def test_errors_are_reported_not_cached():
    apify = FakeApify()
    apify.fail_vinted = True
    with TestClient(_app(apify), base_url="https://testserver") as client:
        _login(client)
        data = client.get("/offers/albums/al1").json()
        vinted = next(s for s in data["searches"] if s["platform"] == "vinted")
        assert vinted["error"] == "Crédit Apify épuisé pour ce mois"
        assert len(data["listings"]) == 1  # Leboncoin a fonctionné
        apify.fail_vinted = False
        client.get("/offers/albums/al1")
        assert sum("vinted" in a for a, _ in apify.calls) == 2  # l'échec n'était pas en cache


def test_scan_and_best():
    apify = FakeApify()
    with TestClient(_app(apify), base_url="https://testserver") as client:
        _login(client)
        started = client.post("/offers/scan", params={"limit": 5}).json()
        assert started["running"] and started["estimated_cost_usd"] == 0.3
        for _ in range(200):
            status = client.get("/offers/scan/status").json()
            if not status["running"]:
                break
            time.sleep(0.02)
        assert status["total"] == 2 and status["done"] == 2 and status["errors"] == 0
        assert status["albums_with_offers"] == 1 and status["listings_found"] == 2

        best = client.get("/offers/best").json()
        assert best["total"] == 1
        assert best["albums"][0]["title"] == "Discovery" and best["albums"][0]["best"]["total_known"] == 20

        # Rien de nouveau à analyser : tout est en cache.
        client.post("/offers/scan")
        for _ in range(200):
            status = client.get("/offers/scan/status").json()
            if not status["running"]:
                break
            time.sleep(0.02)
        assert status["total"] == 0 and len(apify.calls) == 4


def test_apify_not_configured():
    with TestClient(_no_token_app(), base_url="https://testserver") as client:
        _login(client)
        r = client.get("/offers/albums/al1")
        assert r.status_code == 503 and "APIFY_TOKEN" in r.json()["detail"]


def _no_token_app():
    settings = Settings(
        spotify_client_id="cid",
        spotify_client_secret="secret",
        spotify_redirect_uri="https://testserver/auth/callback",
        frontend_url="https://testserver/done",
        session_secret="s",
        cookie_secure=False,
    )
    return create_app(settings, transport=httpx.MockTransport(FakeApify()))
