import time
from typing import Literal

from pydantic import BaseModel, Field

from app.offers.models import ScoredListing

FUNK_SOUL_STYLES = ["Funk", "Soul", "Disco", "Rhythm & Blues", "Afrobeat", "Jazz-Funk", "Boogie", "Northern Soul"]


class ResaleSettings(BaseModel):
    """Réglages de l'onglet Revente (revente visée : Vinted)."""

    genre: str = "Funk / Soul"
    styles: list[str] = Field(default_factory=lambda: list(FUNK_SOUL_STYLES))
    extra_genres: list[str] = Field(default_factory=lambda: ["Jazz", "Rock"], description="Genres secondaires")
    watchlist_size: int = Field(300, ge=20, le=2000)
    min_margin: float = Field(8.0, ge=0, description="Marge nette minimum, en euros")
    min_roi: float = Field(0.3, ge=0, description="Rendement minimum : 0,3 = +30 % sur le prix d'achat")
    max_buy: float = Field(80.0, gt=0, description="Prix d'achat livré maximum")
    packaging: float = Field(1.5, ge=0, description="Coût d'emballage par disque revendu")
    vinted_discount: float = Field(0.9, gt=0, le=1, description="Prix de vente Vinted réaliste / prix affichés")
    discogs_to_vinted: float = Field(0.8, gt=0, le=1.5, description="Prix Vinted / cote Discogs, sans comparables")
    platforms: list[Literal["vinted", "2ememain", "ebay", "leboncoin"]] = Field(
        default_factory=lambda: ["ebay", "vinted", "2ememain"]
    )
    daily_apify_runs: int = Field(30, ge=0, le=1000, description="Plafond journalier de recherches Apify")
    min_grade: Literal["G+", "VG", "VG+", "NM"] = Field("VG", description="État minimum, défauts compris")
    require_confirmed_vinyl: bool = Field(True, description="Exiger une preuve que c'est un vinyle")
    allow_no_sleeve: bool = Field(False, description="Accepter les disques sans pochette")
    exclude_lots: bool = Field(False, description="Écarter les lots (valeur par disque difficile à estimer)")
    exclude_reissues: bool = Field(False, description="Écarter les rééditions")
    exclude_mixed: bool = Field(True, description="Écarter les annonces mixtes (vinyle + CD, goodies…)")


class WatchItem(BaseModel):
    key: str
    artist: str
    title: str
    discogs_id: int
    year: int | None = None
    genres: list[str] = []
    styles: list[str] = []
    cover_url: str | None = None
    want: int = 0
    have: int = 0
    demand: float = 0  # score de demande (want, rareté)
    last_scanned: float | None = None


class Opportunity(BaseModel):
    key: str
    watch_key: str
    artist: str
    title: str
    cover_url: str | None = None
    listing: ScoredListing
    grade: str
    buy_total: float
    resale_estimate: float
    resale_basis: str
    margin: float
    roi: float
    demand: float = 0
    risks: list[str] = []
    status: Literal["active", "disparue"] = "active"
    first_seen: float = Field(default_factory=time.time)
    last_seen: float = Field(default_factory=time.time)
