import time
from typing import Literal

from pydantic import BaseModel, Field

Platform = Literal["vinted", "leboncoin", "2ememain", "discogs", "ebay"]


class Listing(BaseModel):
    """Annonce normalisée, quelle que soit la plateforme."""

    platform: Platform
    external_id: str
    title: str
    url: str
    price: float | None = None
    currency: str = "EUR"
    price_type: str | None = None  # 2ememain : FIXED, MIN_BID (offre à partir de)…
    buyer_fee: float | None = None  # protection acheteur (Vinted, Leboncoin)
    shipping_cost: float | None = None  # port réel quand la plateforme le donne (eBay)
    vinyl_source: bool = False  # recherche limitée à la catégorie vinyles de la plateforme
    total_known: float | None = None  # prix + protection acheteur, HORS frais de port
    condition: str | None = None
    photo_url: str | None = None
    format_hint: str | None = None  # "33T", "45T", "2LP"… déduit du titre
    # Localisation (Leboncoin) : sert à la remise en main propre
    city: str | None = None
    zipcode: str | None = None
    department: str | None = None
    country: str | None = None  # code pays du vendeur quand il est connu (FR, BE…)
    latitude: float | None = None
    longitude: float | None = None
    shippable: bool | None = None
    seller_name: str | None = None
    seller_is_pro: bool | None = None
    seller_rating: float | None = None  # 0 à 1
    seller_rating_count: int | None = None
    stock: int | None = None  # Discogs : nombre d'exemplaires en vente pour cette édition
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


class ScoredListing(Listing):
    score: float = 0  # sur 100
    delivered_total: float | None = None  # prix total pour toi : port estimé inclus, ou main propre
    delivery_mode: Literal["main propre", "envoi"] | None = None
    shipping_estimate: float | None = None
    distance_km: float | None = None
    pickup_possible: bool = False
    components: dict[str, float] = {}  # détail du score par critère
    grade: str | None = None  # état estimé, sur l'échelle Discogs (NM, VG+, VG…), défauts compris
    vinyl_confirmed: bool = True  # preuve qu'il s'agit d'un vinyle (titre, catégorie)
    defects: list[str] = []  # défauts détectés dans l'annonce
    no_sleeve: bool = False
    reference: float | None = None  # prix Discogs de comparaison pour CET état, port compris
    notes: list[str] = []
    also_on: list[str] = []  # même annonce repérée sur une autre plateforme (liens)
    under_target: bool = False  # prix livré sous le prix cible de l'utilisateur


class AlbumListings(BaseModel):
    spotify_id: str
    artist: str
    title: str
    discogs_reference: float | None = None  # prix Discogs typique livré (médiane des éditions + port)
    discogs_by_condition: dict[str, float] = {}  # prix conseillés Discogs par état, hors port
    target_price: float | None = None  # prix cible de l'utilisateur pour cet album
    listings: list[ScoredListing]  # du meilleur score au moins bon
    unreachable: list[ScoredListing] = []  # ni livrable chez toi, ni dans ton rayon de main propre
    # Éditions en vente sur Discogs : prix le plus bas HORS PORT. L'API ne donne ni le pays du vendeur,
    # ni le port, ni la livraison possible en Belgique : affichées à part, sans score ni « bonne affaire ».
    discogs_market: list[Listing] = []
    searches: list[PlatformSearch]
    note: str = "Frais de port estimés (barème indicatif) ; à confirmer sur l'annonce."
