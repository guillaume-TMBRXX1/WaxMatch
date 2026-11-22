"""Estimation de la valeur de revente sur Vinted et de la marge nette."""

from statistics import median

from app.offers.models import ScoredListing
from app.offers.scoring import GRADE_FALLBACK, condition_grade
from app.resale.models import ResaleSettings


def graded_price(grade: str, suggestions: dict[str, float] | None) -> float | None:
    """Cote Discogs de cet état (ou de l'état voisin), hors port."""
    for g in GRADE_FALLBACK.get(grade, [grade]):
        if suggestions and suggestions.get(g):
            return suggestions[g]
    return None


def resale_estimate(
    listing: ScoredListing,
    suggestions: dict[str, float] | None,
    vinted_prices: list[float],
    settings: ResaleSettings,
) -> tuple[float | None, str, str]:
    """(prix de revente réaliste sur Vinted, base de calcul, état estimé).

    Prudent : on retient le plus bas entre les prix affichés sur Vinted pour ce disque (au moins
    3 annonces comparables, décotés) et la cote Discogs de l'état, convertie en prix Vinted.
    """
    grade = listing.grade or condition_grade(listing.condition, listing.title)  # état réel (défauts compris)
    candidates: list[tuple[float, str]] = []
    if len(vinted_prices) >= 3:
        value = median(vinted_prices) * settings.vinted_discount
        factor = f"{settings.vinted_discount:g}".replace(".", ",")
        candidates.append((value, f"médiane de {len(vinted_prices)} annonces Vinted × {factor}"))
    cote = graded_price(grade, suggestions)
    if cote:
        factor = f"{settings.discogs_to_vinted:g}".replace(".", ",")
        candidates.append((cote * settings.discogs_to_vinted, f"cote Discogs {grade} × {factor}"))
    if not candidates:
        return None, "pas de référence", grade
    value, basis = min(candidates, key=lambda c: c[0])
    return round(value, 2), basis, grade


def risks_for(listing: ScoredListing) -> list[str]:
    title = listing.title.lower()
    risks = []
    if not listing.condition:
        risks.append("État non précisé : vérifier les photos")
    if "lot" in title.split() or "lots" in title.split():
        risks.append("Lot : identifier chaque disque")
    if getattr(listing, "defects", None):
        risks.append("Défaut signalé : " + ", ".join(listing.defects))
    if listing.price_type == "MIN_BID":
        risks.append("Prix « à partir de » : à négocier")
    if any(w in title for w in ("reissue", "réédition", "reedition", "repress", " re ")):
        risks.append("Réédition : cote inférieure à l'original")
    if listing.seller_rating is not None and listing.seller_rating < 0.95:
        risks.append(f"Vendeur noté {round(listing.seller_rating * 100)} %")
    return risks
