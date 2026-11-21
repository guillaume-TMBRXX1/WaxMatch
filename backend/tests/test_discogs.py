"""Discogs : correspondance, enrichissement en tâche de fond et offres (API Discogs simulée)."""

import time

import httpx
from fastapi.testclient import TestClient

from app.config import Settings
from app.discogs.service import best_result, split_discogs_title
from app.main import create_app
from app.spotify.normalize import normalize_saved_item
from tests.test_api import fake_spotify


def _album(artist, title):
    return normalize_saved_item(
        {"added_at": None, "album": {"id": "x", "name": title, "artists": [{"id": "a", "name": artist}]}}, {}
    )


def test_split_title():
    assert split_discogs_title("Daft Punk - Discovery") == ("Daft Punk", "Discovery")
    assert split_discogs_title("Sans tiret") == ("", "Sans tiret")


def test_best_result_picks_right_album():
    album = _album("Prince", "Purple Rain (Deluxe Expanded Edition)")
    results = [
        {"title": "Prince And The Revolution - Around The World In A Day", "type": "master", "id": 1},
        {"title": "Prince (2) - Purple Rain", "type": "master", "id": 2},
    ]
    hit = best_result(album, results, threshold=80)
    assert hit and hit[0]["id"] == 2


def test_best_result_rejects_wrong_artist():
    album = _album("Daft Punk", "Discovery")
    assert best_result(album, [{"title": "Justice - Discovery", "id": 3}], threshold=80) is None


SEARCH_MASTER = {
    "results": [
        {
            "type": "master",
            "id": 100,
            "title": "Daft Punk - Discovery",
            "year": "2001",
            "genre": ["Electronic"],
            "style": ["House", "Disco"],
            "uri": "/master/100-Daft-Punk-Discovery",
            "cover_image": "https://img/disc.jpg",
            "community": {"want": 5000, "have": 9000},
        }
    ]
}


def fake_world(request: httpx.Request) -> httpx.Response:
    if request.url.host != "api.discogs.com":
        return fake_spotify(request)
    assert request.headers["Authorization"] == "Discogs token=DT"
    assert request.headers["User-Agent"]
    path, params = request.url.path, request.url.params
    if path == "/database/search":
        if params["type"] == "master" and params["artist"] == "Daft Punk":
            return httpx.Response(200, json=SEARCH_MASTER)
        return httpx.Response(200, json={"results": []})  # Miles Davis introuvable
    if path == "/masters/100/versions":
        assert params["format"] == "Vinyl"
        return httpx.Response(
            200,
            json={
                "versions": [
                    {"id": 11, "title": "Discovery", "format": "2xLP", "country": "Europe", "released": "2001",
                     "stats": {"community": {"in_collection": 900}}},
                    {"id": 12, "title": "Discovery", "format": "2xLP, RE", "country": "Europe", "released": "2021",
                     "stats": {"community": {"in_collection": 3000}}},
                ]
            },
        )
    if path == "/marketplace/stats/11":
        return httpx.Response(200, json={"lowest_price": {"value": 85.0, "currency": "EUR"}, "num_for_sale": 4})
    if path == "/marketplace/stats/12":
        return httpx.Response(200, json={"lowest_price": {"value": 29.9, "currency": "EUR"}, "num_for_sale": 40})
    return httpx.Response(404)


def _settings(tmp_path):
    return Settings(
        spotify_client_id="cid",
        spotify_client_secret="secret",
        spotify_redirect_uri="https://testserver/auth/callback",
        frontend_url="https://testserver/done",
        session_secret="s",
        cookie_secure=False,
        spotify_artist_genres=True,
        discogs_token="DT",
        discogs_min_interval=0,
        discogs_cache_path=str(tmp_path / "discogs.json"),
    )


def _login(client):
    from urllib.parse import parse_qs, urlparse

    r = client.get("/auth/login", follow_redirects=False)
    state = parse_qs(urlparse(r.headers["location"]).query)["state"][0]
    client.get("/auth/callback", params={"code": "c", "state": state}, follow_redirects=False)


def test_enrichment_and_offers(tmp_path):
    settings = _settings(tmp_path)
    app = create_app(settings, transport=httpx.MockTransport(fake_world))
    with TestClient(app, base_url="https://testserver") as client:
        _login(client)

        started = client.post("/discogs/enrich").json()
        assert started["running"] is True  # réponse immédiate, le travail continue en arrière-plan
        for _ in range(100):
            status = client.get("/discogs/enrich/status").json()
            if not status["running"]:
                break
            time.sleep(0.02)
        assert status["total"] == 2 and status["phase"] == "terminé"
        assert status["matched"] == 1 and status["not_found"] == 1 and status["errors"] == 0

        albums = {a["title"]: a for a in client.get("/library/albums").json()["albums"]}
        disc = albums["Discovery"]
        assert disc["discogs"]["id"] == 100
        assert disc["styles"] == ["House", "Disco"]
        assert disc["genres"] == ["french house"]  # les genres Spotify restent prioritaires s'ils existent
        assert albums["Kind of Blue"]["discogs"]["found"] is False

        house = client.get("/library/albums", params={"genre": "house"}).json()
        assert house["total"] == 1
        assert client.get("/library/albums", params={"on_discogs": True}).json()["total"] == 1

        offers = client.get("/discogs/albums/al1").json()
        assert offers["best_price"] == 29.9 and offers["currency"] == "EUR"
        assert offers["total_for_sale"] == 44
        assert [o["release_id"] for o in offers["offers"]] == [12, 11]  # le moins cher d'abord
        assert offers["match"]["marketplace_url"].endswith("master_id=100&format=Vinyl")

        assert client.get("/discogs/albums/inconnu").status_code == 404

    # Le cache est relu au redémarrage : plus rien à chercher.
    app2 = create_app(settings, transport=httpx.MockTransport(fake_world))
    with TestClient(app2, base_url="https://testserver") as client:
        _login(client)
        client.post("/discogs/enrich")
        for _ in range(100):
            status = client.get("/discogs/enrich/status").json()
            if not status["running"]:
                break
            time.sleep(0.02)
        assert status["already_known"] == 2 and status["total"] == 0


def test_discogs_not_configured(tmp_path):
    settings = _settings(tmp_path).model_copy(update={"discogs_token": None})
    app = create_app(settings, transport=httpx.MockTransport(fake_world))
    with TestClient(app, base_url="https://testserver") as client:
        _login(client)
        r = client.post("/discogs/enrich")
        assert r.status_code == 503 and "DISCOGS_TOKEN" in r.json()["detail"]
