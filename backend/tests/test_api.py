"""Test de bout en bout du flux OAuth + bibliothèque, avec Spotify simulé (aucun appel réseau)."""

from urllib.parse import parse_qs, urlparse

import httpx
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app

SETTINGS = Settings(
    spotify_client_id="cid",
    spotify_client_secret="secret",
    spotify_redirect_uri="https://testserver/auth/callback",
    frontend_url="https://testserver/done",
    session_secret="test-secret",
    cookie_secure=False,
    spotify_artist_genres=True,
)


def fake_spotify(request: httpx.Request) -> httpx.Response:
    url = str(request.url)
    if url == "https://accounts.spotify.com/api/token":
        assert request.headers["Authorization"].startswith("Basic ")
        return httpx.Response(
            200,
            json={"access_token": "AT", "refresh_token": "RT", "expires_in": 3600, "scope": "user-library-read"},
        )
    assert request.headers["Authorization"] == "Bearer AT"
    if url == "https://api.spotify.com/v1/me":
        return httpx.Response(200, json={"id": "u1", "display_name": "Test"})
    if url.startswith("https://api.spotify.com/v1/me/albums"):
        return httpx.Response(
            200,
            json={
                "next": None,
                "items": [
                    {
                        "added_at": "2025-01-01T00:00:00Z",
                        "album": {
                            "id": "al1",
                            "name": "Discovery",
                            "album_type": "album",
                            "release_date": "2001-03-12",
                            "artists": [{"id": "ar1", "name": "Daft Punk"}],
                            "images": [],
                        },
                    },
                    {
                        "added_at": "2025-05-01T00:00:00Z",
                        "album": {
                            "id": "al2",
                            "name": "Kind of Blue",
                            "album_type": "album",
                            "release_date": "1959",
                            "artists": [{"id": "ar2", "name": "Miles Davis"}],
                            "images": [],
                        },
                    },
                ],
            },
        )
    if url.startswith("https://api.spotify.com/v1/artists?"):
        # Simule une app "Development Mode" privée de l'endpoint groupé -> repli unitaire.
        return httpx.Response(403, json={"error": {"status": 403}})
    if url == "https://api.spotify.com/v1/artists/ar1":
        return httpx.Response(200, json={"id": "ar1", "genres": ["french house"]})
    if url == "https://api.spotify.com/v1/artists/ar2":
        return httpx.Response(200, json={"id": "ar2", "genres": ["jazz", "cool jazz"]})
    return httpx.Response(404)


def test_full_flow():
    app = create_app(SETTINGS, transport=httpx.MockTransport(fake_spotify))
    with TestClient(app, base_url="https://testserver") as client:
        assert client.get("/library/albums").status_code == 401

        r = client.get("/auth/login", follow_redirects=False)
        assert r.status_code == 307
        qs = parse_qs(urlparse(r.headers["location"]).query)
        assert qs["client_id"] == ["cid"]
        state = qs["state"][0]

        bad = client.get("/auth/callback", params={"code": "c", "state": "wrong"}, follow_redirects=False)
        assert bad.status_code == 400

        # L'ancien state a été consommé par la tentative ratée : on relance la connexion.
        r = client.get("/auth/login", follow_redirects=False)
        state = parse_qs(urlparse(r.headers["location"]).query)["state"][0]
        r = client.get("/auth/callback", params={"code": "c", "state": state}, follow_redirects=False)
        assert r.status_code == 303
        assert r.headers["location"] == "https://testserver/done"

        assert client.get("/auth/me").json()["spotify_user_id"] == "u1"

        data = client.get("/library/albums").json()
        assert [a["title"] for a in data["albums"]] == ["Kind of Blue", "Discovery"]  # ajout récent d'abord

        jazz = client.get("/library/albums", params={"genre": "jazz"}).json()
        assert jazz["total"] == 1 and jazz["albums"][0]["primary_artist"] == "Miles Davis"

        genres = client.get("/library/genres").json()
        assert {g["name"] for g in genres["genres"]} == {"french house", "jazz", "cool jazz"}

        assert client.post("/auth/logout").json() == {"ok": True}
        assert client.get("/library/albums").status_code == 401


def test_artist_genres_disabled_by_default():
    calls = []

    def spy(request: httpx.Request) -> httpx.Response:
        calls.append(request.url.path)
        return fake_spotify(request)

    settings = SETTINGS.model_copy(update={"spotify_artist_genres": False})
    app = create_app(settings, transport=httpx.MockTransport(spy))
    with TestClient(app, base_url="https://testserver") as client:
        r = client.get("/auth/login", follow_redirects=False)
        state = parse_qs(urlparse(r.headers["location"]).query)["state"][0]
        client.get("/auth/callback", params={"code": "c", "state": state}, follow_redirects=False)
        albums = client.get("/library/albums").json()["albums"]
    assert len(albums) == 2 and all(a["genres"] == [] for a in albums)
    assert not any(p.startswith("/v1/artists") for p in calls)  # aucune requête artiste
