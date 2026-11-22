"""Qualité d'une annonce : est-ce bien un vinyle ? dans quel état réel ?

On ne dispose que du titre, de l'état déclaré et de la catégorie (selon la plateforme) : les règles
sont volontairement prudentes, et chaque décision est expliquée en clair.
"""

import re
import unicodedata
from dataclasses import dataclass, field

from app.offers.models import Listing
from app.offers.scoring_grades import GRADE_ORDER, condition_grade, downgrade


def simplify(text: str) -> str:
    """Minuscules, sans accents, ponctuation conservée (utile pour 12" / 7")."""
    text = unicodedata.normalize("NFKD", text or "")
    text = "".join(c for c in text if not unicodedata.combining(c)).lower()
    return re.sub(r"[‘’´`]", "'", text).replace("“", '"').replace("”", '"').replace("''", '"')


def _words(*terms: str) -> re.Pattern:
    return re.compile(r"(?<![a-z0-9])(?:" + "|".join(terms) + r")(?![a-z0-9])")


# Preuve que l'annonce porte sur un disque vinyle.
VINYL_EVIDENCE = _words(
    r"vinyles?", r"vinyls?", r"lps?", r"2 ?lp", r"3 ?lp", r"33 ?t", r"33 ?tours?", r"45 ?t", r"45 ?tours?",
    r"33 ?rpm", r"45 ?rpm", r'12 ?(?:"|inch|pouces?)', r'7 ?(?:"|inch|pouces?)', r"maxi(?: 45)?", r"ep",
    r"disques?", r"microsillons?", r"picture ?disc", r"plaat", r"platen", r"elpee", r"schallplatten?",
)
# Autres supports : exclus s'il n'y a aucune preuve de vinyle, signalés sinon (annonce mixte).
OTHER_MEDIA = _words(
    r"cd", r"cds", r"compact ?disc", r"cassettes?", r"k7", r"dvd", r"blu ?ray", r"vhs", r"mini ?disc",
)
# Produits dérivés et accessoires : exclus s'il n'y a aucune preuve de vinyle.
MERCH = _words(
    r"t ?-?shirts?", r"tee ?-?shirts?", r"tees?", r"sweats?", r"sweat ?-?shirts?", r"hoodies?", r"pulls?",
    r"casquettes?", r"bonnets?", r"tote ?bags?", r"totebags?", r"mugs?", r"tasses?", r"badges?", r"pins?",
    r"patchs?", r"patches", r"ecussons?", r"stickers?", r"autocollants?", r"porte ?-?cles?", r"keychains?",
    r"posters?", r"affiches?", r"lithographies?", r"serigraphies?", r"toiles?", r"tableaux?", r"cadres?",
    r"cartes? postales?", r"figurines?", r"funko", r"peluches?", r"livres?", r"books?", r"magazines?",
    r"programmes?", r"billets?", r"tickets?", r"places? de concert", r"slipmats?", r"feutrines?", r"coques?",
    r"puzzles?", r"calendriers?", r"partitions?", r"songbooks?", r"platines?", r"tourne ?-?disques?",
    r"enceintes?", r"amplis?", r"amplificateurs?", r"cellules?", r"diamants?", r"aiguilles?", r"bacs?",
    r"caisses?", r"meubles?", r"etageres?", r"rangements?", r"sous ?-?pochettes?", r"pochettes de protection",
    r"nettoyants?", r"brosses?", r"lampes?", r"horloges?",
)
# Pochette sans disque : jamais un vinyle à acheter.
SLEEVE_ONLY = _words(
    r"pochette (?:seule|vide|uniquement)", r"sans (?:disque|vinyle|le disque|le vinyle)", r"empty sleeve",
    r"sleeve only", r"cover only", r"(?:juste|seulement) la pochette",
)
# Disque sans pochette.
NO_SLEEVE = _words(
    r"sans pochette", r"pochette manquante", r"(?:vinyle|disque) seul", r"no (?:sleeve|cover)", r"sleeve missing",
    r"without (?:sleeve|cover)", r"sans jaquette", r"pochette generique", r"generic sleeve",
)
# Défauts graves : le disque ne se revend pas (ou très mal).
SEVERE = {
    "voilé": _words(r"voiles?", r"voilees?", r"gondoles?", r"warped", r"warp"),
    "saute": _words(r"sautes?", r"saute", r"skips?", r"skipping", r"accroches?"),
    "fêlé ou cassé": _words(r"feles?", r"fissures?", r"casses?", r"cassees?", r"cracked", r"broken"),
    "très rayé": _words(r"tres rayes?", r"fortement rayes?", r"tres rayures", r"heavily scratched", r"deep scratch(?:es)?"),
    "pour pièces": _words(r"pour pieces", r"hors service", r"for parts", r"not working", r"defectueux"),
    "mauvais état": _words(r"mauvais etat", r"tres abime", r"tres usee?", r"poor", r"etat moyen"),
    "dégât des eaux": _words(r"moisis?", r"moisissures?", r"degats? des eaux", r"humidite", r"water damage", r"mold"),
}
# Défauts légers : l'état réel est d'un cran inférieur à l'état déclaré.
MILD = {
    "rayures": _words(r"rayes?", r"rayures?", r"scratch(?:es|ed)?", r"micro ?-?rayures?"),
    "craquements": _words(r"craquements?", r"crepitements?", r"crackles?", r"surface noise", r"souffle"),
    "pochette abîmée": _words(
        r"pochette (?:abimee|dechiree|usee|tachee|ecrite|annotee)", r"ring ?wear", r"seam split", r"split seam",
        r"sleeve (?:damage|wear)", r"dechirures?", r"traces? d'usure",
    ),
    "usé": _words(r"uses?", r"usees?", r"usure", r"traces d'usage", r"worn"),
}
LOT = _words(r"lots?", r"collection de \d+", r"\d+ (?:vinyles|disques|lp|33 ?t)")


@dataclass
class Quality:
    confirmed: bool  # preuve d'un vinyle (titre, catégorie ou filtre de recherche)
    blocking: str | None = None  # raison d'exclusion systématique (ce n'est pas un disque à acheter)
    no_sleeve: bool = False
    severe: list[str] = field(default_factory=list)
    mild: list[str] = field(default_factory=list)
    mixed_media: bool = False
    is_lot: bool = False
    grade: str = "VG"  # état estimé après prise en compte des défauts
    notes: list[str] = field(default_factory=list)


def assess_quality(listing: Listing) -> Quality:
    text = simplify(f"{listing.title} {listing.condition or ''}")
    category_confirmed = bool(listing.vinyl_source) or (
        listing.platform == "2ememain" and re.search(r"2ememain\.be/v/[^/]+/vinyl", listing.url or "")
    )
    title_evidence = bool(VINYL_EVIDENCE.search(text))
    evidence = title_evidence or bool(category_confirmed)
    q = Quality(confirmed=evidence)

    if SLEEVE_ONLY.search(text):
        q.blocking = "pochette seule, sans disque"
        return q
    other = OTHER_MEDIA.search(text)
    merch = MERCH.search(text)
    # Sans mention de vinyle dans le titre, un CD ou un goodie reste exclu, même rangé dans une catégorie
    # « vinyles » (erreur de classement fréquente chez les vendeurs).
    if not title_evidence and (other or merch):
        q.blocking = f"pas un vinyle (« {(other or merch).group(0)} »)"
        return q
    if evidence and (other or merch):
        q.mixed_media = True
        q.notes.append(f"Annonce mixte (« {(other or merch).group(0)} ») : vérifier ce qui est vendu")
    if not evidence:
        q.notes.append("Type non confirmé : aucune mention de vinyle, vérifier les photos")

    q.no_sleeve = bool(NO_SLEEVE.search(text))
    if q.no_sleeve:
        q.notes.append("Sans pochette : forte décote")
    q.severe = [label for label, pattern in SEVERE.items() if pattern.search(text)]
    # Un défaut léger déjà couvert par un défaut grave n'est pas compté deux fois (« très rayé »).
    q.mild = [label for label, pattern in MILD.items() if pattern.search(text)
              and not (label == "rayures" and "très rayé" in q.severe)]
    q.is_lot = bool(LOT.search(text))

    grade = condition_grade(listing.condition, listing.title)
    if q.severe:
        grade = "G"
        q.notes.append("Défaut grave : " + ", ".join(q.severe))
    elif q.mild:
        grade = downgrade(grade, 1)
        q.notes.append("Défaut signalé : " + ", ".join(q.mild) + f" (état estimé {grade})")
    if q.no_sleeve:
        grade = downgrade(grade, 1)
    q.grade = grade
    return q


def grade_at_least(grade: str, minimum: str) -> bool:
    return GRADE_ORDER.index(grade) >= GRADE_ORDER.index(minimum)
