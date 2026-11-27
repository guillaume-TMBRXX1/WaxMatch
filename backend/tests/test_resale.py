"""Onglet Revente : eBay, liste de surveillance Discogs, estimation de marge, journal d'opportunités."""

import json
import time
from urllib.parse import parse_qs, urlparse

import httpx
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app
from app.offers.ebay import parse_ebay
from app.offers.models import ScoredListing
from app.resale.evaluate import resale_estimate
from app.resale.models import ResaleSettings
from app.resale.watchlist import demand_score, item_from_result
from tests.test_api import fake_spotify

EBAY_ITEM_DE = {
    "itemId": "v1|1234567890|0",
    "title": "James Brown - The Payback - 2LP Vinyl Polydor",
    "price": {"value": "12.00", "currency": "EUR"},
    "shippingOptions": [{"shippingCostType": "FIXED", "shippingCost": {"value": "6.50", "currency": "EUR"}}],
    "condition": "Very Good",
    "itemWebUrl": "https://www.ebay.de/itm/1234567890",
    "image": {"imageUrl": "https://i.ebayimg.com/a.jpg"},
    "itemLocation": {"country": "DE", "postalCode": "50667"},
    "seller": {"username": "soulshop", "feedbackPercentage": "99.6", "feedbackScore": 1200},
    "buyingOptions": ["FIXED_PRICE"],
}
EBAY_ITEM_US = {**EBAY_ITEM_DE, "itemId": "v1|999|0", "itemWebUrl": "https://www.ebay.com/itm/999",
                "itemLocation": {"country": "US"}, "price": {"value": "5.00", "currency": "EUR"}}

DISCOGS_PAYBACK = {
    "type": "master", "id": 500, "title": "James Brown - The Payback", "year": "1973",
    "genre": ["Funk / Soul"], "style": ["Funk"], "cover_image": "https://img/payback.jpg",
    "community": {"want": 5000, "have": 3000},
}


def test_parse_ebay_item():
    lst = parse_ebay(EBAY_ITEM_DE)
    assert (lst.platform, lst.external_id, lst.price, lst.shipping_cost) == ("ebay", "1234567890", 12.0, 6.5)
    assert lst.country == "DE" and lst.shippable and lst.seller_rating == 0.996 and lst.format_hint == "2LP"
    assert parse_ebay(EBAY_ITEM_US).shippable is False  # hors UE : douane et TVA


def test_watchlist_helpers():
    assert demand_score(0, 10) == 0
    assert demand_score(5000, 1000) > demand_score(5000, 10000)  # plus rare = plus intéressant
    item = item_from_result(DISCOGS_PAYBACK)
    assert (item.artist, item.title, item.key, item.discogs_id) == ("James Brown", "The Payback", "james brown|the payback", 500)
    assert item_from_result({**DISCOGS_PAYBACK, "title": "Various - Soul Hits"}) is None


def test_resale_estimate_is_conservative():
    listing = ScoredListing(platform="ebay", external_id="1", title="x", url="u", condition="Very Good")
    rs = ResaleSettings()
    value, basis, grade = resale_estimate(listing, {"VG+": 45.0}, [40, 38, 42], rs)
    assert grade == "VG+" and value == 36.0  # min(médiane Vinted 40 × 0,9 ; cote 45 × 0,8)
    value, basis, _ = resale_estimate(listing, {"VG+": 45.0}, [40, 38], rs)  # moins de 3 comparables
    assert value == 36.0 and basis.startswith("cote Discogs VG+")
    assert resale_estimate(listing, None, [], rs)[0] is None


class FakeWorld:
    def __init__(self):
        self.apify_calls = 0
        self.ebay_calls: list[tuple] = []
        self.ebay_items = [EBAY_ITEM_DE, EBAY_ITEM_US]

    def __call__(self, request: httpx.Request) -> httpx.Response:
        host, path, params = request.url.host, request.url.path, request.url.params
        if host == "api.ebay.com" and path == "/identity/v1/oauth2/token":
            return httpx.Response(200, json={"access_token": "EBAYTOKEN", "expires_in": 7200})
        if host == "api.ebay.com":
            assert request.headers["Authorization"] == "Bearer EBAYTOKEN"
            assert request.headers["X-EBAY-C-MARKETPLACE-ID"] in {"EBAY_BE", "EBAY_DE", "EBAY_FR", "EBAY_NL"}
            self.ebay_calls.append((request.headers["X-EBAY-C-MARKETPLACE-ID"], request.url.params["q"],
                                    request.url.params.get("sort")))
            assert "country=BE" in request.headers["X-EBAY-C-ENDUSERCTX"]
            return httpx.Response(200, json={"itemSummaries": self.ebay_items})
        if host == "api.discogs.com":
            if path == "/database/search":
                assert params["type"] == "master" and params["format"] == "Vinyl" and params["sort"] == "want"
                return httpx.Response(200, json={"results": [DISCOGS_PAYBACK] if params.get("style") == "Funk" else []})
            if path == "/masters/500/versions":
                return httpx.Response(200, json={"versions": [{"id": 501, "title": "The Payback", "format": "2xLP",
                                                               "stats": {"community": {"in_collection": 900}}}]})
            if path == "/marketplace/stats/501":
                return httpx.Response(200, json={"lowest_price": {"value": 20.0, "currency": "EUR"}, "num_for_sale": 30})
            if path == "/marketplace/price_suggestions/501":
                return httpx.Response(200, json={"Near Mint (NM or M-)": {"value": 60.0},
                                                 "Very Good Plus (VG+)": {"value": 45.0},
                                                 "Very Good (VG)": {"value": 30.0}})
            return httpx.Response(404)
        if host == "api.apify.com":
            self.apify_calls += 1
            body = json.loads(request.content)
            if "vinted" in path:
                items = [
                    {"id": 70 + i, "title": "James Brown The Payback vinyle", "url": f"https://v/{70 + i}",
                     "price": p, "totalPrice": p + 2, "currency": "EUR", "condition": "Bon état", "photos": []}
                    for i, p in enumerate([40, 38, 42])
                ] if "James Brown" in body["searchQueries"][0] else []
                return httpx.Response(201, json=items)
            return httpx.Response(201, json=[])
        return fake_spotify(request)


def _app(world, **extra):
    settings = Settings(
        spotify_client_id="cid", spotify_client_secret="secret", spotify_redirect_uri="https://testserver/auth/callback",
        frontend_url="https://testserver/done", session_secret="s", cookie_secure=False,
        discogs_token="DT", discogs_min_interval=0, apify_token="AP",
        ebay_client_id="EID", ebay_client_secret="ESECRET", **extra,
    )
    return create_app(settings, transport=httpx.MockTransport(world))


def _login(client):
    r = client.get("/auth/login", follow_redirects=False)
    state = parse_qs(urlparse(r.headers["location"]).query)["state"][0]
    client.get("/auth/callback", params={"code": "c", "state": state}, follow_redirects=False)


def _wait(client):
    for _ in range(400):
        status = client.get("/resale/status").json()
        if not status["running"]:
            return status
        time.sleep(0.02)
    raise AssertionError("job toujours en cours")


def test_resale_end_to_end():
    world = FakeWorld()
    with TestClient(_app(world), base_url="https://testserver") as client:
        _login(client)
        assert client.post("/resale/scan").status_code == 409  # liste vide

        client.post("/resale/watchlist/build")
        assert _wait(client)["total"] == 1
        watch = client.get("/resale/watchlist").json()
        assert watch[0]["key"] == "james brown|the payback" and watch[0]["want"] == 5000

        client.post("/resale/scan", params={"limit": 5})
        status = _wait(client)
        assert status["done"] == 1 and status["new_opportunities"] == 1 and status["apify_runs"] == 2

        opps = client.get("/resale/opportunities").json()
        assert len(opps) == 1
        opp = opps[0]
        # eBay DE : 12 € + 6,50 € de port réel = 18,50 € ; revente estimée 36 € ; emballage 1,50 €.
        assert opp["listing"]["platform"] == "ebay" and opp["buy_total"] == 18.5
        assert opp["resale_estimate"] == 36.0 and opp["margin"] == 16.0 and opp["roi"] == 0.86
        assert opp["grade"] == "VG+"
        assert not any(o["listing"]["external_id"] == "999" for o in opps)  # vendeur US exclu

        stats = client.get("/resale/stats").json()
        assert stats["active"] == 1 and stats["active_margin_total"] == 16.0 and stats["apify_runs_today"] == 2

        # Nouvelle recherche (cache vidé) sans l'annonce : elle passe en « disparue ».
        world.ebay_items = []
        client.app.state.offers_store.searches.clear()
        client.post("/resale/scan", params={"limit": 5})
        assert _wait(client)["gone"] == 1
        assert client.get("/resale/opportunities", params={"status": "disparue"}).json()[0]["key"] == "ebay:1234567890"


def test_daily_apify_cap_keeps_ebay_only():
    world = FakeWorld()
    with TestClient(_app(world), base_url="https://testserver") as client:
        _login(client)
        settings = client.get("/resale/settings").json()
        assert settings["platforms"] == ["ebay", "vinted", "2ememain"]
        client.put("/resale/settings", json={**settings, "daily_apify_runs": 0})
        client.post("/resale/watchlist/build")
        _wait(client)
        client.post("/resale/scan")
        status = _wait(client)
        assert world.apify_calls == 0 and status["apify_runs"] == 0
        # Revente sur Vinted : sans annonces Vinted comparables, pas d'opportunité (la cote Discogs ne suffit pas).
        assert status["new_opportunities"] == 0
        assert client.get("/resale/status").json()["filtered"] == {"comparables Vinted insuffisants": 1}
        # Si l'utilisateur l'autorise, la cote Discogs seule sert de référence.
        client.put("/resale/settings", json={**settings, "daily_apify_runs": 0, "require_vinted_comparables": False})
        client.app.state.offers_store.searches.clear()
        client.post("/resale/scan")
        assert _wait(client)["new_opportunities"] == 1


def test_opportunity_details_and_triage():
    world = FakeWorld()
    with TestClient(_app(world), base_url="https://testserver") as client:
        _login(client)
        client.post("/resale/watchlist/build")
        _wait(client)
        client.post("/resale/scan")
        _wait(client)
        opp = client.get("/resale/opportunities").json()[0]
        # Détail du calcul : achat, comparables Vinted et médiane, cote Discogs, lien Discogs.
        assert (opp["buy_price"], opp["buy_shipping"], opp["packaging"]) == (12.0, 6.5, 1.5)
        assert [c["price"] for c in opp["comparables"]] == [38, 40, 42] and opp["vinted_median"] == 40
        assert opp["discogs_by_condition"]["VG+"] == 45.0 and opp["discogs_lowest"] == 20.0
        assert opp["discogs_url"].endswith("master_id=500&format=Vinyl")

        key = opp["key"]
        client.post(f"/resale/opportunities/{key}/decision", json={"decision": "gardee"})
        assert client.get("/resale/opportunities").json() == []  # plus « à trier »
        assert client.get("/resale/opportunities", params={"view": "gardees"}).json()[0]["key"] == key

        client.post(f"/resale/opportunities/{key}/decision", json={"decision": "ecartee", "reason": "revente surestimée"})
        assert client.get("/resale/opportunities", params={"view": "ecartees"}).json()[0]["decision_reason"] == "revente surestimée"
        # Retrouvée lors d'une nouvelle analyse : reste écartée, pas reproposée ni comptée comme nouvelle.
        client.app.state.offers_store.searches.clear()
        client.post("/resale/scan")
        assert _wait(client)["new_opportunities"] == 0
        assert client.get("/resale/opportunities").json() == []
        stats = client.get("/resale/stats").json()
        assert stats["dismissed"] == 1 and stats["dismissed_reasons"] == {"revente surestimée": 1}
        assert client.post("/resale/opportunities/inconnue/decision", json={"decision": "gardee"}).status_code == 404


def test_sweep_matches_many_listings_with_few_searches():
    world = FakeWorld()
    world.ebay_items = []

    def sweep_vinted(request):
        body = json.loads(request.content)
        query = body.get("searchQueries", [body.get("searchQuery")])[0]
        if "vinyle soul" in query and "vinted" in request.url.path:
            return httpx.Response(201, json=[
                # Bonne affaire : The Payback à 9 €, état « Très bon état ».
                {"id": 900, "title": "James Brown The Payback vinyle 1973", "url": "https://v/900", "price": 9,
                 "totalPrice": 10.1, "currency": "EUR", "condition": "Très bon état", "photos": []},
                # Sans rapport avec la liste : ignorée.
                {"id": 901, "title": "Vinyle Johnny Hallyday", "url": "https://v/901", "price": 5, "totalPrice": 6,
                 "currency": "EUR", "condition": "Bon état", "photos": []},
                # Goodie : exclu.
                {"id": 902, "title": "T-shirt James Brown The Payback", "url": "https://v/902", "price": 3,
                 "totalPrice": 4, "currency": "EUR", "condition": "Neuf", "photos": []},
            ])
        return None

    original = world.__call__

    def handler(request):
        if request.url.host == "api.apify.com":
            world.apify_calls += 1
            body = json.loads(request.content)
            # Recherche « disque par disque » de vérification : comparables Vinted.
            if body.get("searchQueries") == ["James Brown The Payback vinyle"]:
                return httpx.Response(201, json=[
                    {"id": 70 + i, "title": "James Brown The Payback vinyle", "url": f"https://v/{70 + i}",
                     "price": p, "totalPrice": p + 2, "currency": "EUR", "condition": "Bon état", "photos": []}
                    for i, p in enumerate([40, 38, 42])
                ])
            return sweep_vinted(request) or httpx.Response(201, json=[])
        return original(request)

    with TestClient(_app(handler), base_url="https://testserver") as client:
        _login(client)
        client.post("/resale/watchlist/build")
        _wait(client)
        settings = client.get("/resale/settings").json()
        client.put("/resale/settings", json={**settings, "sweep_queries": ["vinyle soul", "vinyle funk"],
                                             "sweep_platforms": ["vinted", "2ememain"]})
        client.post("/resale/sweep")
        status = _wait(client)
        # 2 requêtes × 2 plateformes pour le balayage + 1 vérification.
        assert status["apify_runs"] == 5 and status["new_opportunities"] == 1
        opp = client.get("/resale/opportunities").json()[0]
        assert opp["source"] == "balayage" and opp["listing"]["external_id"] == "900"
        assert opp["vinted_median"] == 40 and len(opp["comparables"]) == 3  # vérifiée avec des comparables
        assert opp["buy_total"] == 15.1  # 10,10 € (protection incluse) + 5 € de port estimé


def test_daily_counter_follows_brussels_time(monkeypatch):
    """À 00h45 à Bruxelles (23h45 UTC), c'est déjà un nouveau jour pour le compteur Apify."""
    from datetime import datetime, timezone

    import app.resale.store as store_module
    from app.resale.store import ResaleStore

    utc_evening = datetime(2026, 11, 22, 23, 45, tzinfo=timezone.utc)  # 00h45 le 23 à Bruxelles

    class FrozenDatetime(datetime):
        @classmethod
        def now(cls, tz=None):
            return utc_evening.astimezone(tz) if tz else utc_evening.replace(tzinfo=None)

    monkeypatch.setattr(store_module, "datetime", FrozenDatetime)
    store = ResaleStore()
    store.meta["usage:2026-11-22"] = {"apify_runs": 30}  # quota consommé la veille
    assert store.today().isoformat() == "2026-11-23"
    assert store.apify_runs_today() == 0


def test_listing_at_vinted_market_price_is_not_an_opportunity():
    """Cas réel : l'annonce est au prix des autres annonces Vinted du même disque -> pas d'affaire."""
    world = FakeWorld()
    world.ebay_items = []

    def handler(request):
        if request.url.host == "api.apify.com":
            world.apify_calls += 1
            body = json.loads(request.content)
            if body.get("searchQueries") == ["James Brown The Payback vinyle"]:  # vérification : marché à ~40 €
                return httpx.Response(201, json=[
                    {"id": 70 + i, "title": "James Brown The Payback vinyle", "url": f"https://v/{70 + i}",
                     "price": p, "totalPrice": p + 2, "currency": "EUR", "condition": "Très bon état", "photos": []}
                    for i, p in enumerate([39, 40, 41])
                ])
            if "vinted" in request.url.path and body.get("searchQueries") == ["vinyle soul"]:
                return httpx.Response(201, json=[
                    {"id": 900, "title": "James Brown The Payback vinyle", "url": "https://v/900", "price": 39,
                     "totalPrice": 41.2, "currency": "EUR", "condition": "Très bon état", "photos": []}])
            return httpx.Response(201, json=[])
        return world(request)

    with TestClient(_app(handler), base_url="https://testserver") as client:
        _login(client)
        client.post("/resale/watchlist/build")
        _wait(client)
        settings = client.get("/resale/settings").json()
        # Conversion Discogs -> Vinted généreuse (VG+ 45 € × 1,2 = 54 €) : sur la cote seule, on aurait cru à une
        # affaire ; la vérification par les prix Vinted (marché à ~40 €) montre que non.
        client.put("/resale/settings", json={**settings, "sweep_queries": ["vinyle soul"], "min_margin": 2, "min_roi": 0.0,
                                             "discogs_to_vinted": 1.2, "sweep_platforms": ["vinted", "2ememain"]})
        client.post("/resale/sweep")
        status = _wait(client)
        assert status["new_opportunities"] == 0
        assert status["filtered"].get("marge insuffisante") == 1


def test_sweep_discovers_albums_of_watched_artists():
    world = FakeWorld()
    world.ebay_items = []
    SEX_MACHINE = {"type": "master", "id": 600, "title": "James Brown - Sex Machine", "year": "1970",
                   "genre": ["Funk / Soul"], "style": ["Funk"], "community": {"want": 2000, "have": 4000}}

    def handler(request):
        if request.url.host == "api.discogs.com" and request.url.path == "/database/search" and request.url.params.get("q"):
            assert request.url.params["q"] == "james brown sex machine"
            return httpx.Response(200, json={"results": [SEX_MACHINE]})
        if request.url.host == "api.apify.com":
            world.apify_calls += 1
            body = json.loads(request.content)
            if "vinted" in request.url.path and body.get("searchQueries") == ["vinyle soul"]:
                return httpx.Response(201, json=[
                    {"id": 910, "title": "James Brown Sex Machine 2LP vinyle", "url": "https://v/910", "price": 12,
                     "totalPrice": 13.3, "currency": "EUR", "condition": "Très bon état", "photos": []}])
            return httpx.Response(201, json=[])
        return world(request)

    with TestClient(_app(handler), base_url="https://testserver") as client:
        _login(client)
        client.post("/resale/watchlist/build")
        _wait(client)
        settings = client.get("/resale/settings").json()
        client.put("/resale/settings", json={**settings, "sweep_queries": ["vinyle soul"],
                                             "sweep_platforms": ["vinted", "2ememain"]})
        client.post("/resale/sweep")
        status = _wait(client)
        assert status["discovered"] == 1
        keys = {w["key"]: w for w in client.get("/resale/watchlist").json()}
        assert keys["james brown|sex machine"]["discovered"] is True


def test_budget_in_dollars_and_pistes():
    """Facturation au résultat : budget en dollars ; disques sans comparables -> pistes vérifiables à la demande."""
    world = FakeWorld()
    world.ebay_items = []

    def handler(request):
        if request.url.host == "api.apify.com":
            world.apify_calls += 1
            body = json.loads(request.content)
            if body.get("searchQueries") == ["James Brown The Payback vinyle"]:  # vérification : marché à ~40 €
                return httpx.Response(201, json=[
                    {"id": 70 + i, "title": "James Brown The Payback vinyle", "url": f"https://v/{70 + i}",
                     "price": p, "totalPrice": p + 2, "currency": "EUR", "condition": "Bon état", "photos": []}
                    for i, p in enumerate([40, 38, 42])
                ])
            if "vinted" in request.url.path and body.get("searchQueries") == ["vinyle soul"]:
                assert body["maxItems"] == 30  # balayage économe
                return httpx.Response(201, json=[
                    {"id": 900, "title": "James Brown The Payback vinyle 1973", "url": "https://v/900", "price": 9,
                     "totalPrice": 10.1, "currency": "EUR", "condition": "Très bon état", "photos": []}])
            return httpx.Response(201, json=[])
        return world(request)

    with TestClient(_app(handler), base_url="https://testserver") as client:
        _login(client)
        client.post("/resale/watchlist/build")
        _wait(client)
        settings = client.get("/resale/settings").json()
        assert settings["daily_budget_usd"] == 0.15 and settings["sweep_max_items"] == 30
        client.put("/resale/settings", json={**settings, "sweep_queries": ["vinyle soul"], "verify_top": 0,
                                             "sweep_platforms": ["vinted", "2ememain"], "allow_pistes": True})
        stats = client.get("/resale/stats").json()
        assert stats["sweep_cost_usd"] == 0.06  # 1 requête × 2 plateformes × 30 annonces × 1 $ / 1 000

        client.post("/resale/sweep")
        status = _wait(client)
        assert status["new_opportunities"] == 0 and status["filtered"]["pistes à vérifier"] == 1
        assert status["cost"] == 0.001  # une seule annonce renvoyée
        piste = client.get("/resale/opportunities", params={"view": "pistes"}).json()[0]
        assert piste["needs_check"] and "provisoire" in piste["resale_basis"]
        assert client.get("/resale/opportunities").json() == []  # pas dans « À trier » tant que non vérifiée

        verified = client.post(f"/resale/opportunities/{piste['key']}/verify").json()
        assert verified["needs_check"] is False and verified["vinted_median"] == 40
        assert client.get("/resale/opportunities").json()[0]["key"] == piste["key"]
        stats = client.get("/resale/stats").json()
        assert stats["spent_today"] == 0.004 and stats["spent_month"] == 0.004  # 1 + 3 annonces

        # Budget épuisé : la vérification est refusée avec un message clair.
        client.put("/resale/settings", json={**client.get("/resale/settings").json(), "daily_budget_usd": 0.0})
        r = client.post(f"/resale/opportunities/{piste['key']}/verify")
        assert r.status_code == 429 and "Budget Apify du jour atteint" in r.json()["detail"]


def test_old_costly_settings_are_upgraded():
    from app.resale.store import ResaleStore

    store = ResaleStore()
    store.meta["settings"] = {
        "daily_apify_runs": 50, "sweep_max_items": 100, "verify_top": 8, "min_margin": 10,
        "sweep_queries": ["vinyle soul", "vinyle funk", "vinyle disco", "vinyle afro", "vinyle jazz funk", "vinyle rnb"],
    }
    s = store.settings
    assert (s.sweep_max_items, s.verify_top, len(s.sweep_queries)) == (30, 5, 4)
    assert s.daily_apify_runs == 50 and s.min_margin == 10  # choix personnels conservés
    store.meta["settings"]["sweep_queries"] = ["vinyle stax"]
    store.meta["settings"]["sweep_max_items"] = 50
    s = store.settings
    assert s.sweep_queries == ["vinyle stax"] and s.sweep_max_items == 50


def test_ebay_first_sweep_is_free_and_verified_on_vinted():
    """Balayage par défaut : eBay (gratuit) sur plusieurs sites, puis vérification payante des seules
    annonces prometteuses avec les prix Vinted."""
    world = FakeWorld()  # eBay renvoie l'annonce allemande (12 € + 6,50 €) et une annonce US (exclue)
    with TestClient(_app(world), base_url="https://testserver") as client:
        _login(client)
        client.post("/resale/watchlist/build")
        _wait(client)
        settings = client.get("/resale/settings").json()
        assert settings["sweep_platforms"] == ["ebay"] and settings["allow_pistes"] is False
        client.put("/resale/settings", json={**settings, "ebay_sweep_queries": ["soul vinyl"],
                                             "ebay_marketplaces": ["EBAY_DE", "EBAY_FR"]})
        assert client.get("/resale/stats").json()["sweep_cost_usd"] == 0  # balayage eBay : gratuit

        client.post("/resale/sweep")
        status = _wait(client)
        assert {(m, q, sort) for m, q, sort in world.ebay_calls if q == "soul vinyl"} == {
            ("EBAY_DE", "soul vinyl", "newlyListed"), ("EBAY_FR", "soul vinyl", "newlyListed")}
        assert status["ebay_calls"] == 2 and status["listings_seen"] == 2  # même annonce dédoublonnée
        # Vérification Vinted : 1 seule recherche Apify (comparables à 38-42 €), puis opportunité confirmée.
        assert status["apify_runs"] == 1 and status["new_opportunities"] == 1
        opp = client.get("/resale/opportunities").json()[0]
        assert opp["listing"]["platform"] == "ebay" and opp["vinted_median"] == 40 and opp["margin"] == 16.0


def test_broad_identification_and_miss_memory():
    """Annonce d'un artiste NON suivi : identifiée sur Discogs (gratuit) et ajoutée si demandée ;
    une annonce introuvable n'est plus recherchée aux balayages suivants."""
    world = FakeWorld()
    SUPERFLY = {"type": "master", "id": 700, "title": "Curtis Mayfield - Superfly", "year": "1972",
                "genre": ["Funk / Soul"], "style": ["Soul"], "community": {"want": 900, "have": 5000}}
    discogs_queries: list[str] = []
    world.ebay_items = [
        {**EBAY_ITEM_DE, "itemId": "v1|11|0", "title": "Curtis Mayfield - Superfly LP vinyl 1972",
         "itemWebUrl": "https://www.ebay.de/itm/11", "price": {"value": "15.00", "currency": "EUR"}},
        {**EBAY_ITEM_DE, "itemId": "v1|12|0", "title": "Obscure Band - Unknown Record LP vinyl",
         "itemWebUrl": "https://www.ebay.de/itm/12", "price": {"value": "5.00", "currency": "EUR"}},
    ]

    def handler(request):
        if request.url.host == "api.discogs.com" and request.url.path == "/database/search" and request.url.params.get("q"):
            discogs_queries.append(request.url.params["q"])
            hit = "curtis mayfield" in request.url.params["q"]
            return httpx.Response(200, json={"results": [SUPERFLY] if hit else []})
        return world(request)

    with TestClient(_app(handler), base_url="https://testserver") as client:
        _login(client)
        client.post("/resale/watchlist/build")
        _wait(client)
        settings = client.get("/resale/settings").json()
        assert settings["identify_unmatched"] and settings["discovery_max_lookups"] == 150
        client.put("/resale/settings", json={**settings, "ebay_sweep_queries": ["soul vinyl"], "ebay_marketplaces": ["EBAY_DE"]})

        client.post("/resale/sweep")
        status = _wait(client)
        assert status["discovered"] == 1 and status["identify_lookups"] == 2
        # Le moins cher d'abord : l'annonce à 5 € est identifiée avant celle à 15 €.
        assert discogs_queries == ["obscure band unknown record", "curtis mayfield superfly"]
        assert "curtis mayfield|superfly" in {w["key"] for w in client.get("/resale/watchlist", params={"limit": 2000}).json()}

        # Nouveau balayage : l'annonce introuvable n'est pas re-demandée ; Superfly est désormais suivi.
        client.post("/resale/sweep")
        assert _wait(client)["identify_lookups"] == 0
        assert discogs_queries == ["obscure band unknown record", "curtis mayfield superfly"]


def test_settings_v2_upgraded_to_broad_identification():
    from app.resale.store import ResaleStore

    store = ResaleStore()
    store.meta["settings"] = {"settings_version": 2, "discovery_max_lookups": 40, "discovery_min_want": 150,
                              "watchlist_size": 600, "daily_budget_usd": 0.06}
    s = store.settings
    assert (s.discovery_max_lookups, s.discovery_min_want, s.watchlist_size) == (150, 60, 1500)
    assert s.daily_budget_usd == 0.06 and s.settings_version == 3
