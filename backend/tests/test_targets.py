"""Prix cible par album."""

from fastapi.testclient import TestClient

from tests.test_offers import FakeApify, _app, _fast_geocoder, _login


def test_target_price_flags_listings_and_best():
    with TestClient(_app(FakeApify()), base_url="https://testserver") as client:
        _fast_geocoder(client)
        _login(client)
        assert client.put("/targets/al1", json={"target_price": 0}).status_code == 422
        assert client.put("/targets/inconnu", json={"target_price": 20}).status_code == 404
        assert client.put("/targets/al1", json={"target_price": 23}).json() == {"spotify_id": "al1", "target_price": 23}
        assert client.get("/targets").json() == [{"spotify_id": "al1", "target_price": 23}]

        data = client.get("/offers/albums/al1").json()
        assert data["target_price"] == 23
        under = [l for l in data["listings"] if l["under_target"]]
        # Ostende 22,50 € livré : sous la cible ; Jambes 25 € et Vinted 37,20 € : au-dessus.
        assert [l["delivered_total"] for l in under] == [22.5]
        assert under[0]["notes"][0] == "Sous ton prix cible (23,00 €)"

        best = client.get("/offers/best", params={"sort": "target"}).json()
        assert best["sort"] == "target" and best["albums"][0]["target_price"] == 23

        client.delete("/targets/al1")
        assert client.get("/targets").json() == []
        assert not any(l["under_target"] for l in client.get("/offers/albums/al1").json()["listings"])
