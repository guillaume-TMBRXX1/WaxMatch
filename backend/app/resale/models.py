import time
from typing import Literal

from pydantic import BaseModel, Field

from app.offers.models import ScoredListing

FUNK_SOUL_STYLES = ["Funk", "Soul", "Disco", "Rhythm & Blues", "Afrobeat", "Jazz-Funk", "Boogie", "Northern Soul"]


class ResaleSettings(BaseModel):
    """Réglages de l'onglet Revente (revente visée : Vinted)."""

    settings_version: int = 2  # 2 : réglages économes (facturation Apify au résultat)

    genre: str = "Funk / Soul"
    styles: list[str] = Field(default_factory=lambda: list(FUNK_SOUL_STYLES))
    extra_genres: list[str] = Field(default_factory=lambda: ["Jazz", "Rock"], description="Genres secondaires")
    watchlist_size: int = Field(600, ge=20, le=3000)
    min_margin: float = Field(8.0, ge=0, description="Marge nette minimum, en euros")
    min_roi: float = Field(0.3, ge=0, description="Rendement minimum : 0,3 = +30 % sur le prix d'achat")
    max_buy: float = Field(80.0, gt=0, description="Prix d'achat livré maximum")
    packaging: float = Field(1.5, ge=0, description="Coût d'emballage par disque revendu")
    vinted_discount: float = Field(0.9, gt=0, le=1, description="Prix de vente Vinted réaliste / prix affichés")
    discogs_to_vinted: float = Field(0.8, gt=0, le=1.5, description="Prix Vinted / cote Discogs, sans comparables")
    platforms: list[Literal["vinted", "2ememain", "ebay", "leboncoin"]] = Field(
        default_factory=lambda: ["ebay", "vinted", "2ememain"]
    )
    daily_apify_runs: int = Field(50, ge=0, le=1000, description="Plafond journalier de recherches Apify")
    # Apify facture au résultat (~1 $ / 1 000 annonces) : le vrai garde-fou est un budget en dollars.
    daily_budget_usd: float = Field(0.15, ge=0, le=50, description="Budget Apify par jour, en dollars")
    min_grade: Literal["G+", "VG", "VG+", "NM"] = Field("VG", description="État minimum, défauts compris")
    require_confirmed_vinyl: bool = Field(True, description="Exiger une preuve que c'est un vinyle")
    allow_no_sleeve: bool = Field(False, description="Accepter les disques sans pochette")
    exclude_lots: bool = Field(False, description="Écarter les lots (valeur par disque difficile à estimer)")
    exclude_reissues: bool = Field(False, description="Écarter les rééditions")
    exclude_mixed: bool = Field(True, description="Écarter les annonces mixtes (vinyle + CD, goodies…)")
    # Balayage large : quelques recherches par style, dont les annonces sont comparées à toute la liste.
    sweep_queries: list[str] = Field(
        default_factory=lambda: ["vinyle soul", "vinyle funk", "vinyle disco", "vinyle afro"]
    )
    sweep_max_items: int = Field(30, ge=5, le=500, description="Annonces récupérées par recherche de balayage")
    verify_top: int = Field(5, ge=0, le=50, description="Disques prometteurs vérifiés automatiquement sur Vinted")
    # Sources du balayage : eBay (API officielle, gratuite) par défaut ; Vinted et 2ememain coûtent (Apify).
    sweep_platforms: list[Literal["ebay", "vinted", "2ememain"]] = Field(default_factory=lambda: ["ebay"])
    ebay_sweep_queries: list[str] = Field(
        default_factory=lambda: ["soul vinyl", "funk vinyl", "disco vinyl", "afrobeat vinyl", "jazz funk lp",
                                 "northern soul", "rare groove lp", "soul lp original"]
    )
    ebay_marketplaces: list[str] = Field(
        default_factory=lambda: ["EBAY_DE", "EBAY_FR", "EBAY_BE", "EBAY_NL"],
        description="Sites eBay balayés (le port est toujours calculé vers ton pays)",
    )
    ebay_sweep_max_items: int = Field(100, ge=10, le=200, description="Annonces eBay par recherche (gratuit)")
    allow_pistes: bool = Field(False, description="Garder les pistes estimées sur la seule cote Discogs")
    comparables_max_items: int = Field(12, ge=3, le=50, description="Annonces Vinted récupérées pour comparer")
    comparables_cache_days: int = Field(7, ge=1, le=60, description="Durée de réutilisation des comparables")
    # Revente sur Vinted : seule la preuve par les prix Vinted compte.
    require_vinted_comparables: bool = Field(True, description="Exiger des annonces Vinted comparables")
    min_comparables: int = Field(3, ge=1, le=20)
    # Découverte : annonce d'un artiste suivi pour un album absent de la liste -> recherche Discogs.
    discover_new_albums: bool = True
    discovery_min_want: int = Field(150, ge=0, description="Demande minimum (want Discogs) d'un album découvert")
    discovery_max_lookups: int = Field(40, ge=0, le=300, description="Recherches Discogs de découverte par balayage")


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
    discovered: bool = False  # ajouté automatiquement lors d'un balayage


class Comparable(BaseModel):
    """Annonce comparable du même disque, qui sert à estimer le prix de revente."""

    platform: str
    title: str
    url: str
    price: float
    condition: str | None = None


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
    # Tri par l'utilisateur : gardée (intéressante) ou écartée (masquée, jamais reproposée).
    decision: Literal["gardee", "ecartee"] | None = None
    decision_reason: str | None = None
    decided_at: float | None = None
    source: Literal["disque", "balayage"] = "disque"
    # Piste : marge possible d'après la cote Discogs, mais pas encore confirmée par des prix Vinted.
    needs_check: bool = False
    # Détail du calcul, pour vérifier soi-même.
    buy_price: float | None = None
    buy_fee: float | None = None
    buy_shipping: float | None = None
    delivery_mode: str | None = None
    packaging: float = 0
    comparables: list[Comparable] = []
    vinted_median: float | None = None
    discogs_by_condition: dict[str, float] = {}
    discogs_lowest: float | None = None
    discogs_for_sale: int | None = None
    discogs_url: str | None = None
    first_seen: float = Field(default_factory=time.time)
    last_seen: float = Field(default_factory=time.time)
