import time
from typing import Literal

from pydantic import BaseModel, Field

Platform = Literal["vinted", "leboncoin"]


class Listing(BaseModel):
    """Annonce normalisée, quelle que soit la plateforme."""

    platform: Platform
    external_id: str
    title: str
    url: str
    price: float | None = None
    currency: str = "EUR"
    buyer_fee: float | None = None  # protection acheteur (Vinted, Leboncoin)
    total_known: float | None = None  # prix + protection acheteur, HORS frais de port
    condition: str | None = None
    photo_url: str | None = None
    format_hint: str | None = None  # "33T", "45T", "2LP"… déduit du titre
    # Localisation (Leboncoin) : sert à la remise en main propre
    city: str | None = None
    zipcode: str | None = None
    department: str | None = None
    latitude: float | None = None
    longitude: float | None = None
    shippable: bool | None = None
    seller_name: str | None = None
    seller_is_pro: bool | None = None
    seller_rating: float | None = None  # 0 à 1
    seller_rating_count: int | None = None
    published_at: str | None = None
    match_score: float | None = None


class RejectedListing(BaseModel):
    platform: Platform
    title: str
    url: str
    reason: str


class PlatformSearch(BaseModel):
    platform: Platform
    query: str
    searched_at: float = Field(default_factory=time.time)
    raw_count: int = 0
    listings: list[Listing] = []
    rejected: list[RejectedListing] = []
    error: str | None = None
    from_cache: bool = False


class AlbumListings(BaseModel):
    spotify_id: str
    artist: str
    title: str
    listings: list[Listing]  # toutes plateformes, triées par prix connu croissant
    searches: list[PlatformSearch]
    note: str = "Prix hors frais de port (estimation du port et score : étape suivante)."
