"""Score des annonces (sur 100) : prix total livré, bonne affaire vs Discogs, proximité, confiance, fraîcheur."""

import re
from datetime import datetime, timedelta

from app.geo import haversine_km
from app.offers.models import Listing, ScoredListing
from app.spotify.normalize import fold
from app.user_settings import UserSettings

# Frais de port indicatifs pour un vinyle 33T (colis ~0,5-1 kg), en euros.
# Vinted : point relais (Mondial Relay, bpost…). 2ememain : envoi à convenir, souvent bpost.
SHIPPING_ESTIMATE = {"vinted": 5.0, "2ememain": 7.5, "leboncoin": 5.5}
# Pays de livraison possibles par plateforme (Leboncoin ne livre qu'en France).
SHIPS_TO = {"vinted": None, "2ememain": {"BE"}, "leboncoin": {"FR"}}  # None = pas de restriction connue

_CONDITION = [
    (re.compile(r"neuf|blister|scell"), 100),
    (re.compile(r"tres bon"), 85),
    (re.compile(r"bon"), 70),
    (re.compile(r"satisfaisant|correct|use"), 45),
]
_FR_MONTHS = {
    "janv": 1, "fevr": 2, "mars": 3, "avr": 4, "mai": 5, "juin": 6,
    "juil": 7, "aout": 8, "sept": 9, "oct": 10, "nov": 11, "dec": 12,
}


def condition_score(condition: str | None, title: str) -> float:
    text = fold(f"{condition or ''} {title}")
    for pattern, value in _CONDITION:
        if pattern.search(text):
            return value
    return 60.0


def parse_date(value: str | None, now: datetime) -> datetime | None:
    """Dates Leboncoin ("2026-11-21 22:21:00") et 2ememain ("22 août 26", "Aujourd'hui", "Hier")."""
    if not value:
        return None
    text = fold(value)
    if text.startswith("aujourd"):
        return now
    if text.startswith("hier"):
        return now - timedelta(days=1)
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).replace(tzinfo=None)
    except ValueError:
        pass
    m = re.match(r"(\d{1,2}) ([a-z]+) (\d{2,4})", text)  # fold() a déjà retiré accents et points
    if m:
        month = _FR_MONTHS.get(m.group(2)[:4]) or _FR_MONTHS.get(m.group(2)[:3])
        year = int(m.group(3))
        year = year + 2000 if year < 100 else year
        if month:
            try:
                return datetime(year, month, int(m.group(1)))
            except ValueError:
                return None
    return None


def freshness_score(published: datetime | None, now: datetime) -> float:
    if published is None:
        return 50.0
    days = (now - published).days
    return 100.0 if days <= 7 else 75.0 if days <= 30 else 50.0 if days <= 90 else 30.0


def deal_score(delivered: float, reference: float | None) -> float:
    """Rapport au prix Discogs : -50 % ou mieux = 100 ; même prix = 50 ; +50 % ou plus = 0."""
    if not reference:
        return 50.0
    ratio = delivered / reference
    return max(0.0, min(100.0, 100 * (1.5 - ratio)))


def score_listings(
    listings: list[Listing],
    settings: UserSettings,
    discogs_reference: float | None = None,
    now: datetime | None = None,
) -> tuple[list[ScoredListing], list[ScoredListing]]:
    """Renvoie (annonces classées du meilleur au moins bon, annonces inaccessibles)."""
    now = now or datetime.now()
    candidates: list[ScoredListing] = []
    unreachable: list[ScoredListing] = []

    for listing in listings:
        s = ScoredListing(**listing.model_dump())
        if s.price is None:
            s.notes.append("Prix non indiqué (voir l'annonce)")
            unreachable.append(s)
            continue
        if s.price_type == "MIN_BID":
            s.notes.append("Prix « à partir de » : offre à négocier")

        # Main propre : vendeur localisé dans le rayon (Vinted ne donne pas la localisation).
        if None not in (s.latitude, s.longitude, settings.latitude, settings.longitude):
            s.distance_km = round(haversine_km(settings.latitude, settings.longitude, s.latitude, s.longitude), 1)
            s.pickup_possible = s.distance_km <= settings.pickup_radius_km

        ships_to = SHIPS_TO.get(s.platform)
        can_ship = s.shippable is not False and (ships_to is None or settings.country in ships_to)
        options: list[tuple[float, str, float | None]] = []
        if s.pickup_possible:
            options.append((s.price, "main propre", None))  # pas de frais acheteur en main propre
        if can_ship:
            shipping = SHIPPING_ESTIMATE[s.platform]
            options.append((round((s.total_known or s.price) + shipping, 2), "envoi", shipping))
        if not options:
            where = f" ({s.distance_km} km)" if s.distance_km is not None else ""
            s.notes.append(f"Non livrable en {settings.country} et hors de ton rayon de main propre{where}")
            unreachable.append(s)
            continue
        s.delivered_total, s.delivery_mode, s.shipping_estimate = min(options, key=lambda o: o[0])
        if s.delivery_mode == "main propre":
            s.notes.append(f"Main propre possible ({s.distance_km} km)")
        else:
            s.notes.append(f"Port estimé {s.shipping_estimate:.2f} €".replace(".", ","))
        candidates.append(s)

    _merge_cross_posts(candidates)
    if not candidates:
        return [], unreachable

    best_price = min(c.delivered_total for c in candidates)
    weights = settings.weights
    radius = max(settings.pickup_radius_km, 1)
    for c in candidates:
        if c.pickup_possible:
            proximity = 100 - 30 * (c.distance_km or 0) / radius
        elif c.distance_km is not None and c.distance_km <= radius * 3:
            proximity = 50.0  # pas loin : main propre envisageable en se déplaçant un peu
        else:
            proximity = 35.0
        seller = (
            c.seller_rating * 100 if c.seller_rating is not None and (c.seller_rating_count or 0) >= 3 else 60.0
        )
        components = {
            "price": round(100 * best_price / c.delivered_total, 1) if c.delivered_total else 0.0,
            "deal": round(deal_score(c.delivered_total, discogs_reference), 1),
            "proximity": round(proximity, 1),
            "trust": round((condition_score(c.condition, c.title) + seller) / 2, 1),
            # Vinted : les anciens résultats en cache portaient la date de collecte, pas de publication.
            "freshness": freshness_score(None if c.platform == "vinted" else parse_date(c.published_at, now), now),
        }
        c.components = components
        c.score = round(sum(components[k] * weights[k] for k in weights) / 100, 1)
        if discogs_reference and c.delivered_total <= discogs_reference * 0.7:
            c.notes.append(f"Bonne affaire : {round(100 * (1 - c.delivered_total / discogs_reference))} % sous Discogs")
        elif discogs_reference and c.delivered_total >= discogs_reference * 1.2:
            ref = f"{discogs_reference:.2f}".replace(".", ",")
            c.notes.append(
                f"Plus cher que sur Discogs (+{round(100 * (c.delivered_total / discogs_reference - 1))} % ; "
                f"{ref} € hors port)"
            )

    candidates.sort(key=lambda c: c.score, reverse=True)
    return candidates, unreachable


def _merge_cross_posts(candidates: list[ScoredListing]) -> None:
    """Même annonce sur deux plateformes (même titre, même prix) : on garde la moins chère pour toi."""
    groups: dict[tuple[str, float], list[ScoredListing]] = {}
    for c in candidates:
        groups.setdefault((fold(c.title), c.price), []).append(c)
    for group in groups.values():
        platforms = {c.platform for c in group}
        if len(group) < 2 or len(platforms) < 2:
            continue
        group.sort(key=lambda c: c.delivered_total)
        keep, *others = group
        for other in others:
            keep.also_on.append(other.url)
            candidates.remove(other)
        keep.notes.append("Aussi en vente sur " + ", ".join(sorted({o.platform for o in others})))
