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
    album = _album('Bobby "Blue" Bland', "Two Steps From The Blues (Remastered)")
    assert build_query(album) == "Bobby Bland Two Steps From The Blues vinyle"
    assert build_query(album, "2ememain") == "Bobby Bland Two Steps From The Blues"  # FR + NL : pas de « vinyle »


# --------------------------------------------------------------------------- API de bout en bout

VINTED_RESULTS = [
    {**VINTED_ITEM, "id": 1, "title": "Vinyle Daft Punk Discovery 2LP", "url": "https://v/1", "price": 30, "totalPrice": 32.2},
    {**VINTED_ITEM, "id": 2, "title": "CD Daft Punk Discovery", "url": "https://v/2", "price": 3, "totalPrice": 3.85},
    {**VINTED_ITEM, "id": 3, "title": "Daft Punk Homework vinyle", "url": "https://v/3"},
    {**VINTED_ITEM, "id": 1, "title": "Vinyle Daft Punk Discovery 2LP", "url": "https://v/1", "price": 30, "totalPrice": 32.2},
]
DEUXIEME_RESULTS = [
    # Format réel de piotrv1001/2ememain-listings-scraper
    {"imageUrl": "https://img/2m.jpg", "title": "Vinyle Daft Punk Discovery", "price": 25, "priceType": "FIXED",
     "city": "Jambes", "date": "Hier", "sellerName": "Bob", "isCommercialAd": False,
     "url": "https://www.2ememain.be/v/cd-dvd/vinyles/m111-vinyle-daft-punk-discovery"},
    {"imageUrl": None, "title": "Daft Punk Discovery 33T", "price": 15, "priceType": "MIN_BID",
     "city": "Ostende", "date": "22 août 26", "sellerName": "Zoé", "isCommercialAd": False,
     "url": "https://www.2ememain.be/v/cd-dvd/vinyles/m222-daft-punk-discovery-33t"},
]
LBC_RESULTS = [
    {**LBC_ITEM, "listId": 9, "title": "Daft Punk - Discovery - 33T", "url": "https://l/9", "price": 20, "shippable": False},
]
CITIES = {"namur": (50.4669, 4.8675), "jambes": (50.4560, 4.8730), "ostende": (51.2154, 2.9286)}


class FakeApify:
    def __init__(self):
        self.calls: list[tuple[str, dict]] = []
        self.geocode_calls = 0
        self.fail_vinted = False
        self.busy_vinted = 0

    def __call__(self, request: httpx.Request) -> httpx.Response:
        if request.url.host == "nominatim.openstreetmap.org":
            self.geocode_calls += 1
            city = request.url.params["q"].lower()
            if city in CITIES:
                lat, lon = CITIES[city]
                return httpx.Response(200, json=[{"lat": str(lat), "lon": str(lon), "display_name": f"{city.title()}, Belgique"}])
            return httpx.Response(200, json=[])
        if request.url.host == "api.discogs.com":
            from tests.test_discogs import fake_world

            return fake_world(request)
        if request.url.host != "api.apify.com":
            return fake_spotify(request)
        assert request.headers["Authorization"] == "Bearer AP"
        body = json.loads(request.content)
        actor = request.url.path.split("/")[3]
        self.calls.append((actor, body))
        query = (body.get("searchQueries") or [body.get("searchQuery")])[0]
        daft = "Daft Punk" in query
        if "vinted" in actor:
            if self.fail_vinted:
                return httpx.Response(
                    402, json={"error": {"type": "not-enough-usage-to-run-paid-actor", "message": "Monthly usage exceeded"}}
                )
            if self.busy_vinted > 0:
                self.busy_vinted -= 1
                return httpx.Response(402, json={"error": {"type": "actor-memory-limit-exceeded", "message": "8192MB"}})
            return httpx.Response(201, json=VINTED_RESULTS if daft else [])
        if "2ememain" in actor:
            return httpx.Response(201, json=DEUXIEME_RESULTS if daft else [])
        return httpx.Response(201, json=LBC_RESULTS if daft else [])


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
    app = create_app(settings, transport=httpx.MockTransport(apify))
    return app


def _login(client, namur=True):
    from urllib.parse import parse_qs, urlparse

    r = client.get("/auth/login", follow_redirects=False)
    state = parse_qs(urlparse(r.headers["location"]).query)["state"][0]
    client.get("/auth/callback", params={"code": "c", "state": state}, follow_redirects=False)
    if namur:
        r = client.put("/settings", json={"city": "Namur", "country": "BE", "pickup_radius_km": 30})
        assert r.status_code == 200, r.text


def _fast_geocoder(client):
    client.app.state.geocoder.min_interval = 0


def test_settings_geocoding():
    apify = FakeApify()
    with TestClient(_app(apify), base_url="https://testserver") as client:
        _fast_geocoder(client)
        _login(client, namur=False)
        assert client.get("/settings").json()["platforms"] == ["vinted", "2ememain"]
        saved = client.put("/settings", json={"city": "Namur", "country": "BE", "priority": "pickup"}).json()
        assert saved["latitude"] == 50.4669 and saved["location_label"] == "Namur, Belgique"
        assert client.get("/settings").json()["priority"] == "pickup"
        bad = client.put("/settings", json={"city": "Atlantide", "country": "BE"})
        assert bad.status_code == 422
        assert client.get("/settings/presets").json()["balanced_price"]["price"] == 50


def test_namur_scoring_end_to_end():
    apify = FakeApify()
    with TestClient(_app(apify), base_url="https://testserver") as client:
        _fast_geocoder(client)
        _login(client)
        data = client.get("/offers/albums/al1").json()

        actors = sorted(a for a, _ in apify.calls)
        assert actors == ["piotrv1001~2ememain-listings-scraper", "piotrv1001~vinted-listings-scraper"]
        vinted_input = next(b for a, b in apify.calls if "vinted" in a)
        assert vinted_input["domain"] == "vinted.be" and vinted_input["searchQueries"] == ["Daft Punk Discovery vinyle"]
        assert next(b for a, b in apify.calls if "2ememain" in a)["searchQuery"] == "Daft Punk Discovery"

        listings = data["listings"]
        first = listings[0]
        # Jambes (à ~1 km de Namur) : main propre, 25 € tout compris -> meilleur score.
        assert first["platform"] == "2ememain" and first["delivery_mode"] == "main propre"
        assert first["delivered_total"] == 25 and first["distance_km"] < 3 and first["pickup_possible"]
        # Ostende (~150 km) : envoi, port estimé ajouté ; prix "à partir de" signalé.
        ostende = next(l for l in listings if "m222" in l["url"])
        assert ostende["delivery_mode"] == "envoi" and ostende["delivered_total"] == 22.5
        assert any("à partir de" in n for n in ostende["notes"])
        # Vinted : 32,20 € + 5 € de port estimé.
        vinted = next(l for l in listings if l["platform"] == "vinted")
        assert vinted["delivered_total"] == 37.2
        assert all(0 <= l["score"] <= 100 for l in listings)
        assert set(first["components"]) == {"price", "deal", "proximity", "trust", "freshness"}

        rejected = next(s for s in data["searches"] if s["platform"] == "vinted")["rejected"]
        assert sorted(r["reason"] for r in rejected) == ["objet exclu : « cd »", "titre de l'album absent"]

        # Cache : aucun nouveau run Apify ni géocodage.
        calls, geo = len(apify.calls), apify.geocode_calls
        again = client.get("/offers/albums/al1").json()
        assert len(apify.calls) == calls and apify.geocode_calls == geo
        assert all(s["from_cache"] for s in again["searches"])
        assert client.get("/offers/albums/inconnu").status_code == 404


def test_leboncoin_unreachable_from_namur():
    apify = FakeApify()
    with TestClient(_app(apify), base_url="https://testserver") as client:
        _fast_geocoder(client)
        _login(client)
        data = client.get("/offers/albums/al1", params={"platforms": "leboncoin"}).json()
        # Annonce à Lieuvillers (Oise), main propre seulement, ~230 km : ni livrable en Belgique, ni à portée.
        assert data["listings"] == [] and len(data["unreachable"]) == 1
        assert "Non livrable en BE" in data["unreachable"][0]["notes"][0]


def test_errors_are_reported_not_cached():
    apify = FakeApify()
    apify.fail_vinted = True
    with TestClient(_app(apify), base_url="https://testserver") as client:
        _fast_geocoder(client)
        _login(client)
        data = client.get("/offers/albums/al1").json()
        vinted = next(s for s in data["searches"] if s["platform"] == "vinted")
        assert vinted["error"].startswith("Apify refuse le lancement (402, not-enough-usage-to-run-paid-actor)")
        assert len(data["listings"]) == 2  # 2ememain a fonctionné
        apify.fail_vinted = False
        client.get("/offers/albums/al1")
        assert sum("vinted" in a for a, _ in apify.calls) == 2  # l'échec n'était pas en cache


def test_memory_limit_is_retried_not_reported(monkeypatch):
    import app.offers.apify as apify_module

    async def no_sleep(_):
        return None

    monkeypatch.setattr(apify_module.asyncio, "sleep", no_sleep)
    apify = FakeApify()
    apify.busy_vinted = 2
    with TestClient(_app(apify), base_url="https://testserver") as client:
        _fast_geocoder(client)
        _login(client)
        data = client.get("/offers/albums/al1").json()
        vinted = next(s for s in data["searches"] if s["platform"] == "vinted")
        assert vinted["error"] is None and len(vinted["listings"]) == 1
    assert sum("vinted" in a for a, _ in apify.calls) == 3


def test_scan_and_best():
    apify = FakeApify()
    with TestClient(_app(apify), base_url="https://testserver") as client:
        _fast_geocoder(client)
        _login(client)
        started = client.post("/offers/scan", params={"limit": 5}).json()
        assert started["running"] and started["estimated_cost_usd"] == 0.03
        for _ in range(200):
            status = client.get("/offers/scan/status").json()
            if not status["running"]:
                break
            time.sleep(0.02)
        assert status["total"] == 2 and status["done"] == 2 and status["errors"] == 0
        assert status["albums_with_offers"] == 1

        best = client.get("/offers/best").json()
        assert best["total"] == 1 and best["albums"][0]["title"] == "Discovery"
        assert best["albums"][0]["best"]["delivery_mode"] == "main propre"
        assert client.get("/offers/best", params={"sort": "price"}).json()["sort"] == "price"


def test_apify_not_configured():
    with TestClient(_no_token_app(), base_url="https://testserver") as client:
        _login(client, namur=False)
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


# --------------------------------------------------------------------------- scoring (unitaire)


def test_scoring_helpers():
    from datetime import datetime

    from app.offers.scoring import condition_score, deal_score, parse_date

    now = datetime(2026, 11, 22)
    assert parse_date("22 août 26", now) == datetime(2026, 8, 22)
    assert parse_date("3 déc. 25", now) == datetime(2025, 12, 3)
    assert parse_date("Hier", now).day == 21
    assert parse_date("2026-11-21 22:21:00", now) == datetime(2026, 11, 21, 22, 21)
    assert parse_date("n'importe quoi", now) is None

    assert deal_score(10, 20) == 100 and deal_score(20, 20) == 50 and deal_score(40, 20) == 0
    assert deal_score(20, None) == 50
    assert condition_score("État neuf", "") == 100 and condition_score("Très bon état", "") == 85
    assert format_hint('Vinyle 12" Leon Bridges') == "LP" and format_hint('Single 7" 45rpm') == '45T (7")'


def test_cross_posted_listing_shown_once():
    from app.offers.scoring import score_listings
    from app.user_settings import UserSettings

    title = "Vinyle Leon Bridges - Happiness Anytime (LP, vinyle blanc opaque) neuf"
    lbc = Listing(platform="leboncoin", external_id="1", title=title, url="https://l/1", price=30, total_known=31.99,
                  shippable=True, country="FR", latitude=48.08, longitude=7.364)
    vinted = Listing(platform="vinted", external_id="2", title=title, url="https://v/2", price=30, total_known=32.2,
                     shippable=True)
    settings = UserSettings(city="Paris", country="FR", latitude=48.857, longitude=2.341)
    ranked, unreachable = score_listings([lbc, vinted], settings, discogs_reference=60)
    assert len(ranked) == 1 and not unreachable
    kept = ranked[0]
    assert kept.also_on and any("Aussi en vente" in n for n in kept.notes)
    assert any("Bonne affaire" in n for n in kept.notes)  # ~37 € contre 60 € sur Discogs


def test_more_expensive_than_discogs_is_flagged():
    from app.offers.scoring import score_listings
    from app.user_settings import UserSettings

    vinted = Listing(platform="vinted", external_id="1", title="Vinyle Leon Bridges Happiness Anytime",
                     url="https://v/1", price=30, total_known=32.2, shippable=True)
    ranked, _ = score_listings([vinted], UserSettings(country="BE"), discogs_reference=25.46)
    assert ranked[0].delivered_total == 37.2
    assert any(n.startswith("Plus cher que sur Discogs (+46 %") for n in ranked[0].notes)


def test_real_false_positives_from_namur_scan():
    """Faux positifs observés lors du scan réel de 30 albums (22/11/2026)."""
    bo = _album("Bo Diddley", "Bo Diddley")
    cd = Listing(platform="2ememain", external_id="m2453649222", title="Bo Diddley 'the London sessions'",
                 url="https://www.2ememain.be/v/cd-dvd/cd-jazz-blues/m2453649222-bo-diddley-the-london-sessions")
    assert judge(bo, cd)[1] == "objet exclu : catégorie CD/DVD"
    other = cd.model_copy(update={"url": "https://www.2ememain.be/v/cd-dvd/vinyles-jazz/m1-bo-diddley"})
    assert judge(bo, other)[1].startswith("autre album de l'artiste")
    assert judge(bo, _listing("Bo Diddley LP 1958 vinyle original"))[0]  # l'éponyme reste accepté

    duke = _album("Duke Ellington", "Duke Ellington & John Coltrane")
    ad = Listing(platform="2ememain", external_id="x", title="Duke Ellington & John Coltrane - Duke Ellington & John",
                 url="https://www.2ememain.be/v/cd-dvd/vinyles-singles/a169078540-duke-ellington-john-coltrane")
    assert judge(duke, ad)[1] == "publicité (annonce sponsorisée)"

    jj = _album("J.J. Cale", "Troubadour")
    assert judge(jj, _listing("J.J. Cale Troubadour (Vinyl LP) gebraucht"))[0]


def test_scan_fetches_discogs_reference_and_best_sorts_by_deal():
    from app.discogs.models import DiscogsMatch

    apify = FakeApify()
    with TestClient(_app(apify, discogs_token="DT", discogs_min_interval=0), base_url="https://testserver") as client:
        _fast_geocoder(client)
        _login(client)
        client.app.state.discogs_store.put("daft punk|discovery", DiscogsMatch(found=True, kind="master", id=100))
        client.post("/offers/scan", params={"limit": 5})
        for _ in range(300):
            status = client.get("/offers/scan/status").json()
            if not status["running"]:
                break
            time.sleep(0.02)
        assert status["phase"] == "terminé"
        best = client.get("/offers/best").json()
        row = best["albums"][0]
        assert best["sort"] == "deal" and row["discogs_reference"] == 29.9
        assert row["vs_discogs"] == round(row["best"]["delivered_total"] / 29.9, 2)


def test_backfill_discogs_references():
    from app.discogs.models import DiscogsMatch

    apify = FakeApify()
    with TestClient(_app(apify, discogs_token="DT", discogs_min_interval=0), base_url="https://testserver") as client:
        _fast_geocoder(client)
        _login(client)
        client.get("/offers/albums/al1")  # offres en cache, sans correspondance Discogs à ce moment-là
        assert client.app.state.discogs_store.get_offers("daft punk|discovery") is None
        client.app.state.discogs_store.put("daft punk|discovery", DiscogsMatch(found=True, kind="master", id=100))
        assert client.post("/offers/references").json()["total"] == 1
        for _ in range(300):
            status = client.get("/offers/scan/status").json()
            if not status["running"]:
                break
            time.sleep(0.02)
        assert status["done"] == 1 and status["albums_with_offers"] == 1
        assert client.get("/offers/best").json()["albums"][0]["discogs_reference"] == 29.9
