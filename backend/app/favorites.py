"""Favoris : annonces que l'utilisateur veut garder à l'œil, avec leur état actuel."""

import time
from typing import Literal

from pydantic import BaseModel, Field

from app.offers.models import ScoredListing
from app.offers.service import OffersStore


class FavoriteInput(BaseModel):
    spotify_id: str
    listing: ScoredListing


class Favorite(BaseModel):
    spotify_id: str
    match_key: str
    artist: str = ""
    album_title: str = ""
    cover_url: str | None = None
    listing: ScoredListing  # copie au moment de l'ajout
    saved_at: float = Field(default_factory=time.time)


class FavoriteView(Favorite):
    status: Literal["en ligne", "disparue", "à vérifier"] = "à vérifier"
    current_price: float | None = None  # prix lors de la dernière recherche, si l'annonce y figure encore
    price_change: float | None = None  # current_price - prix au moment de l'ajout
    last_checked: float | None = None


def favorite_status(fav: Favorite, offers: OffersStore) -> FavoriteView:
    """Compare le favori à la dernière recherche faite pour son album sur sa plateforme."""
    view = FavoriteView(**fav.model_dump())
    if fav.listing.platform == "discogs":
        return view
    search = offers.searches.get((fav.listing.platform, fav.match_key))
    if search is None:
        return view
    view.last_checked = search.searched_at
    current = next((lst for lst in search.listings if lst.external_id == fav.listing.external_id), None)
    if current is not None:
        view.status = "en ligne"
        view.current_price = current.price
        if current.price is not None and fav.listing.price is not None:
            view.price_change = round(current.price - fav.listing.price, 2)
    elif search.searched_at > fav.saved_at and search.error is None:
        view.status = "disparue"  # absente d'une recherche postérieure à l'ajout : vendue ou retirée
    return view


class FavoritesStore:
    def __init__(self, pool=None):
        self.pool = pool
        self.memory: dict[str, dict[tuple[str, str], Favorite]] = {}

    async def list(self, user_id: str) -> list[Favorite]:
        if self.pool is not None:
            rows = await self.pool.fetch(
                "select data from favorites where spotify_user_id = $1 order by created_at desc", user_id
            )
            return [Favorite.model_validate(r["data"]) for r in rows]
        return sorted(self.memory.get(user_id, {}).values(), key=lambda f: f.saved_at, reverse=True)

    async def add(self, user_id: str, fav: Favorite) -> None:
        key = (fav.listing.platform, fav.listing.external_id)
        if self.pool is not None:
            await self.pool.execute(
                """
                insert into favorites (spotify_user_id, platform, external_id, spotify_album_id, match_key, data)
                values ($1, $2, $3, $4, $5, $6)
                on conflict (spotify_user_id, platform, external_id) do nothing
                """,
                user_id, key[0], key[1], fav.spotify_id, fav.match_key, fav.model_dump(mode="json"),
            )
            return
        self.memory.setdefault(user_id, {}).setdefault(key, fav)

    async def remove(self, user_id: str, platform: str, external_id: str) -> None:
        if self.pool is not None:
            await self.pool.execute(
                "delete from favorites where spotify_user_id = $1 and platform = $2 and external_id = $3",
                user_id, platform, external_id,
            )
            return
        self.memory.get(user_id, {}).pop((platform, external_id), None)
