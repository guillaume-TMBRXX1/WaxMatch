"""Échelle des états d'un vinyle (Goldmine / Discogs) et lecture de l'état déclaré dans une annonce."""

import re

from app.spotify.normalize import fold

GRADE_ORDER = ["P", "G", "G+", "VG", "VG+", "NM", "M"]


def downgrade(grade: str, steps: int = 1) -> str:
    i = GRADE_ORDER.index(grade) if grade in GRADE_ORDER else GRADE_ORDER.index("VG")
    return GRADE_ORDER[max(i - steps, 0)]


# État de l'annonce -> échelle Discogs (Goldmine). Inconnu : VG, hypothèse prudente pour de l'occasion.
_GRADES = [
    (re.compile(r"blister|scell|sealed|sous cello"), "M"),
    (re.compile(r"neuf|new|mint"), "NM"),
    (re.compile(r"tres bon|excellent|comme neuf|nickel|very good|like new|vg\b ?\+|\bvg\+"), "VG+"),
    (re.compile(r"bon etat|\bbon\b|good"), "VG"),
    (re.compile(r"satisfaisant|correct|usage|use|abime"), "G+"),
]
GRADE_FALLBACK = {"M": ["M", "NM"], "NM": ["NM", "M", "VG+"], "VG+": ["VG+", "VG"], "VG": ["VG", "VG+"],
                  "G+": ["G+", "G", "VG"]}


def condition_grade(condition: str | None, title: str) -> str:
    text = fold(f"{condition or ''} {title}")
    for pattern, grade in _GRADES:
        if pattern.search(text):
            return grade
    return "VG"


