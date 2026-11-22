"""Tests sur une vraie base PostgreSQL (ignorés si TEST_DATABASE_URL n'est pas défini).

Exemple : TEST_DATABASE_URL=postgresql://postgres:test@127.0.0.1/waxmatch_test pytest
"""

import asyncio
import json
import os
from urllib.parse import parse_qs, urlparse

import asyncpg
import httpx
import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app
from tests.test_discogs import fake_world

DB_URL = os.environ.get("TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(not DB_URL, reason="TEST_DATABASE_URL non défini")


def _run(coro):
    return asyncio.run(coro)


async def _reset():
    con = await asyncpg.connect(DB_URL)
    await con.execute("drop schema public cascade; create schema public;")
    await con.close()


async def _query(sql, *args):
    con = await asyncpg.connect(DB_URL)
    try:
        return await con.fetch(sql, *args)
    finally:
        await con.close()


@pytest.fixture(autouse=True)
def clean_db():
    _run(_reset())


def _settings(tmp_path, **extra):
    base = dict(
        spotify_client_id="cid",
        spotify_client_secret="secret",
        spotify_redirect_uri="https://testserver/auth/callback",
        frontend_url="https://testserver/done",
        session_secret="secret-stable",
        cookie_secure=False,
        discogs_token="DT",
        discogs_min_interval=0,
        database_url=DB_URL,
    )
    base.update(extra)
    return Settings(**base)


class SpotifyCounter:
    def __init__(self):
        self.library_calls = 0

    def __call__(self, request: httpx.Request) -> httpx.Response:
        if request.url.path == "/v1/me/albums":
            self.library_calls += 1
        return fake_world(request)


def _login(client):
    r = client.get("/auth/login", follow_redirects=False)
    state = parse_qs(urlparse(r.headers["location"]).query)["state"][0]
    r = client.get("/auth/callback", params={"code": "c", "state": state}, follow_redirects=False)
    assert r.status_code == 303


def test_session_and_library_survive_restart(tmp_path):
    settings = _settings(tmp_path)
    spy = SpotifyCounter()

    with TestClient(create_app(settings, transport=httpx.MockTransport(spy)), base_url="https://testserver") as c1:
        assert c1.get("/health").json()["database"] == "connectée"
        _login(c1)
        assert len(c1.get("/library/albums").json()["albums"]) == 2
        cookies = dict(c1.cookies)
    assert spy.library_calls == 1

    # Les jetons sont chiffrés en base, et l'identifiant de session n'y est stocké que haché.
    row = _run(_query("select access_token_enc, refresh_token_enc from oauth_tokens"))[0]
    assert "AT" != row["access_token_enc"] and "RT" not in row["refresh_token_enc"]
    sid = json.loads(__import__("base64").b64decode(cookies["waxmatch_session"].split(".")[0] + "=="))["sid"]
    assert not _run(_query("select 1 from sessions where session_hash = $1", sid))

    # Nouveau démarrage de l'API (comme un redémarrage de Colab) : même cookie, pas de reconnexion,
    # et la bibliothèque vient de la base, sans appel à Spotify.
    app2 = create_app(settings, transport=httpx.MockTransport(spy))
    with TestClient(app2, base_url="https://testserver", cookies=cookies) as c2:
        assert c2.get("/auth/me").json()["spotify_user_id"] == "u1"
        albums = c2.get("/library/albums").json()["albums"]
        assert {a["title"] for a in albums} == {"Discovery", "Kind of Blue"}
        assert c2.get("/library/albums", params={"refresh": True}).status_code == 200
    assert spy.library_calls == 2  # uniquement le refresh explicite

    # Secret de l'application changé : les jetons sont illisibles, il faut se reconnecter (pas de plantage).
    app3 = create_app(_settings(tmp_path, session_secret="autre-secret"), transport=httpx.MockTransport(spy))
    with TestClient(app3, base_url="https://testserver", cookies=cookies) as c3:
        assert c3.get("/auth/me").status_code == 401


def test_discogs_in_database_and_json_import(tmp_path):
    from app.discogs.models import DiscogsMatch

    legacy = tmp_path / "discogs_cache.json"
    legacy.write_text(
        json.dumps({"miles davis|kind of blue": DiscogsMatch(found=True, kind="master", id=5, genres=["Jazz"]).model_dump()})
    )
    settings = _settings(tmp_path, discogs_cache_path=str(legacy))

    with TestClient(create_app(settings, transport=httpx.MockTransport(fake_world)), base_url="https://testserver") as c:
        # Le fichier JSON (Google Drive) est importé dans la base au démarrage.
        assert c.get("/health").json()["discogs_matches"] == 1
        _login(c)
        status = c.post("/discogs/enrich").json()
        for _ in range(200):
            status = c.get("/discogs/enrich/status").json()
            if not status["running"]:
                break
            asyncio.run(asyncio.sleep(0.02))
        assert status["already_known"] == 1 and status["matched"] == 1  # seul Discovery était à chercher
        assert c.get("/discogs/albums/al1").json()["best_price"] == 29.9

    rows = _run(_query("select match_key, found from discogs_matches order by match_key"))
    assert [(r["match_key"], r["found"]) for r in rows] == [("daft punk|discovery", True), ("miles davis|kind of blue", True)]
    assert _run(_query("select count(*) as n from discogs_offers"))[0]["n"] == 1

    # Sans le fichier, tout est relu depuis la base.
    settings2 = _settings(tmp_path, discogs_cache_path=None)
    with TestClient(create_app(settings2, transport=httpx.MockTransport(fake_world)), base_url="https://testserver") as c:
        _login(c)
        jazz = c.get("/library/albums", params={"genre": "jazz"}).json()
        assert jazz["total"] == 1


def test_rls_enabled_on_all_tables(tmp_path):
    with TestClient(create_app(_settings(tmp_path), transport=httpx.MockTransport(fake_world)), base_url="https://testserver"):
        pass
    rows = _run(_query("select relname, relrowsecurity from pg_class where relnamespace = 'public'::regnamespace and relkind = 'r'"))
    assert rows and all(r["relrowsecurity"] for r in rows), rows


def test_listings_settings_and_geocodes_in_database(tmp_path):
    from tests.test_offers import FakeApify

    apify = FakeApify()
    settings = _settings(tmp_path, apify_token="AP")
    with TestClient(create_app(settings, transport=httpx.MockTransport(apify)), base_url="https://testserver") as c:
        c.app.state.geocoder.min_interval = 0
        _login(c)
        assert c.put("/settings", json={"city": "Namur", "country": "BE"}).status_code == 200
        data = c.get("/offers/albums/al1").json()
        assert len(data["listings"]) == 3 and data["listings"][0]["delivery_mode"] == "main propre"
    rows = _run(_query("select platform, kept_count from listing_searches order by platform"))
    assert [(r["platform"], r["kept_count"]) for r in rows] == [("2ememain", 2), ("vinted", 1)]
    geocoded = apify.geocode_calls
    assert geocoded == 3  # Namur, Jambes, Ostende

    # Après redémarrage : réglages, annonces et villes relus depuis la base ; aucun appel externe.
    with TestClient(create_app(settings, transport=httpx.MockTransport(apify)), base_url="https://testserver") as c:
        _login(c)
        assert c.get("/settings").json()["city"] == "Namur"
        data = c.get("/offers/albums/al1").json()
        assert all(s["from_cache"] for s in data["searches"]) and data["listings"][0]["delivery_mode"] == "main propre"
    assert len(apify.calls) == 2 and apify.geocode_calls == geocoded


def test_favorites_persist_in_database(tmp_path):
    from tests.test_offers import FakeApify

    apify = FakeApify()
    settings = _settings(tmp_path, apify_token="AP")
    with TestClient(create_app(settings, transport=httpx.MockTransport(apify)), base_url="https://testserver") as c:
        c.app.state.geocoder.min_interval = 0
        _login(c)
        listing = c.get("/offers/albums/al1").json()["listings"][0]
        assert c.post("/favorites", json={"spotify_id": "al1", "listing": listing}).status_code == 201
    with TestClient(create_app(settings, transport=httpx.MockTransport(apify)), base_url="https://testserver") as c:
        _login(c)
        favs = c.get("/favorites").json()
        assert len(favs) == 1 and favs[0]["listing"]["external_id"] == listing["external_id"]
        assert favs[0]["status"] == "en ligne"  # annonces relues depuis la base


def test_targets_persist_in_database(tmp_path):
    from tests.test_offers import FakeApify

    settings = _settings(tmp_path, apify_token="AP")
    with TestClient(create_app(settings, transport=httpx.MockTransport(FakeApify())), base_url="https://testserver") as c:
        _login(c)
        assert c.put("/targets/al1", json={"target_price": 23.456}).json()["target_price"] == 23.46
    with TestClient(create_app(settings, transport=httpx.MockTransport(FakeApify())), base_url="https://testserver") as c:
        _login(c)
        assert c.get("/targets").json() == [{"spotify_id": "al1", "target_price": 23.46}]


def test_resale_journal_persists(tmp_path):
    from tests.test_resale import FakeWorld, _wait

    world = FakeWorld()
    settings = _settings(tmp_path, apify_token="AP", ebay_client_id="EID", ebay_client_secret="ES")
    with TestClient(create_app(settings, transport=httpx.MockTransport(world)), base_url="https://testserver") as c:
        _login(c)
        c.post("/resale/watchlist/build")
        _wait(c)
        c.post("/resale/scan")
        assert _wait(c)["new_opportunities"] == 1
    with TestClient(create_app(settings, transport=httpx.MockTransport(world)), base_url="https://testserver") as c:
        _login(c)
        stats = c.get("/resale/stats").json()
        assert stats["watched"] == 1 and stats["scanned"] == 1 and stats["active"] == 1 and stats["apify_runs_today"] == 2
        assert c.get("/resale/opportunities").json()[0]["margin"] == 16.0
