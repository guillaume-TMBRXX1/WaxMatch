import time
from typing import Literal

from pydantic import BaseModel, Field


class DiscogsMatch(BaseModel):
    """Correspondance entre un album Spotify et une fiche Discogs (master = toutes éditions)."""

    found: bool
    kind: Literal["master", "release"] | None = None
    id: int | None = None
    title: str | None = None
    year: int | None = None
    genres: list[str] = []
    styles: list[str] = []
    cover_url: str | None = None
    url: str | None = None
    marketplace_url: str | None = None  # annonces vinyles sur Discogs
    want: int | None = None  # nb d'utilisateurs qui le recherchent (indicateur de demande)
    have: int | None = None
    score: float | None = None
    matched_at: float = Field(default_factory=time.time)


class VinylOffer(BaseModel):
    """Une édition vinyle et son état sur le marché Discogs (prix hors frais de port)."""

    release_id: int
    title: str | None = None
    format: str | None = None
    label: str | None = None
    catno: str | None = None
    country: str | None = None
    released: str | None = None
    num_for_sale: int = 0
    lowest_price: float | None = None
    currency: str | None = None
    url: str
    sell_url: str


class AlbumOffers(BaseModel):
    match: DiscogsMatch
    best_price: float | None = None
    currency: str | None = None
    total_for_sale: int = 0
    versions_checked: int = 0
    offers: list[VinylOffer] = []
    note: str = "Prix Discogs les plus bas, hors frais de port."
    main_release_id: int | None = None  # édition la plus répandue (sert aux prix conseillés par état)
    # Prix conseillés par état pour cette édition, hors port : {"M": 40, "NM": 32, "VG+": 24…}.
    # None = pas encore demandé ; {} = indisponible (paramètres vendeur Discogs non remplis ?).
    price_suggestions: dict[str, float] | None = None
    checked_at: float = Field(default_factory=time.time)
