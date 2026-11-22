"""Favoris : ajout, état (en ligne, prix changé, disparue), suppression."""

import time

from fastapi.testclient import TestClient

from tests.test_offers import FakeApify, _app, _fast_geocoder, _login


def _setup(client):
    _fast_geocoder(client)
    _login(client)
    data = client.get("/offers/albums/al1").json()
    return data["listings"][0]


def test_add_list_and_remove_favorite():
    with TestClient(_app(FakeApify()), base_url="https://testserver") as client:
        listing = _setup(client)
        r = client.post("/favorites", json={"spotify_id": "al1", "listing": listing})
        assert r.status_code == 201 and r.json()["status"] == "en ligne"

        favs = client.get("/favorites").json()
        assert len(favs) == 1
        fav = favs[0]
        assert fav["album_title"] == "Discovery" and fav["artist"] == "Daft Punk"
        assert fav["listing"]["external_id"] == listing["external_id"] and fav["price_change"] == 0

        # Ajouter deux fois la même annonce ne crée pas de doublon.
        client.post("/favorites", json={"spotify_id": "al1", "listing": listing})
        assert len(client.get("/favorites").json()) == 1

        client.delete(f"/favorites/{listing['platform']}/{listing['external_id']}")
        assert client.get("/favorites").json() == []
        assert client.post("/favorites", json={"spotify_id": "inconnu", "listing": listing}).status_code == 404


def test_favorite_status_follows_new_searches():
    with TestClient(_app(FakeApify()), base_url="https://testserver") as client:
        listing = _setup(client)
        client.post("/favorites", json={"spotify_id": "al1", "listing": listing})
        store = client.app.state.offers_store
        key = (listing["platform"], "daft punk|discovery")

        # Baisse de prix vue lors d'une nouvelle recherche.
        search = store.searches[key]
        cheaper = [l.model_copy(update={"price": (l.price or 0) - 5}) if l.external_id == listing["external_id"] else l
                   for l in search.listings]
        store.searches[key] = search.model_copy(update={"listings": cheaper, "searched_at": time.time() + 1})
        fav = client.get("/favorites").json()[0]
        assert fav["status"] == "en ligne" and fav["price_change"] == -5

        # Nouvelle recherche où l'annonce n'apparaît plus : vendue ou retirée.
        gone = [l for l in cheaper if l.external_id != listing["external_id"]]
        store.searches[key] = search.model_copy(update={"listings": gone, "searched_at": time.time() + 2})
        assert client.get("/favorites").json()[0]["status"] == "disparue"
