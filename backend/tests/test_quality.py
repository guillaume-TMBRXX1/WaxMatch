"""Robustesse : goodies, pochettes seules, disques sans pochette, défauts, état réel."""

import pytest

from app.offers.models import Listing
from app.offers.quality import assess_quality, grade_at_least
from app.resale.models import ResaleSettings
from app.resale.service import quality_rejection


def L(title, condition=None, platform="vinted", url="https://x"):
    return Listing(platform=platform, external_id="1", title=title, url=url, condition=condition)


@pytest.mark.parametrize(
    "title",
    [
        "T-shirt James Brown The Payback taille M",
        "Poster Fela Kuti Zombie 60x90",
        "Tote bag Daft Punk Discovery",
        "Mug Curtis Mayfield Superfly",
        "Badge Stevie Wonder Songs In The Key Of Life",
        "Livre Motown : l'histoire",
        "CD Marvin Gaye What's Going On",
        "Cassette K7 Barry White",
        "Porte-clés Prince Purple Rain",
        "Slipmat feutrine Stax records",
    ],
)
def test_merch_and_other_media_are_not_records(title):
    q = assess_quality(L(title))
    assert q.blocking and q.blocking.startswith("pas un vinyle")


@pytest.mark.parametrize("title", ["Pochette seule Marvin Gaye LP", "Ohio Players vinyle - pochette vide", "Isaac Hayes sans disque"])
def test_sleeve_only_is_blocked(title):
    assert assess_quality(L(title)).blocking == "pochette seule, sans disque"


def test_record_with_poster_is_kept_but_flagged():
    q = assess_quality(L("Vinyle Prince Purple Rain avec poster"))
    assert q.blocking is None and q.mixed_media and q.confirmed


def test_vinyl_evidence():
    assert assess_quality(L('Prince - Purple Rain 12" 1984')).confirmed
    assert assess_quality(L("Prince Purple Rain 33 tours")).confirmed
    assert assess_quality(L("Kool & The Gang Wild And Peaceful LP")).confirmed
    assert not assess_quality(L("Thunder chicken - The mighty imperials")).confirmed
    # Catégorie 2ememain « vinyles-… » : preuve par la catégorie.
    cat = L("Thunder chicken", platform="2ememain", url="https://www.2ememain.be/v/cd-dvd/vinyles-soul/m1-x")
    assert assess_quality(cat).confirmed
    # Recherche Vinted limitée à la catégorie vinyles.
    assert assess_quality(L("Thunder chicken").model_copy(update={"vinyl_source": True})).confirmed


def test_defects_lower_the_real_grade():
    assert assess_quality(L("Vinyle Al Green Let's Stay Together", "Très bon état")).grade == "VG+"
    mild = assess_quality(L("Vinyle Al Green Let's Stay Together, légères rayures", "Très bon état"))
    assert mild.grade == "VG" and mild.mild == ["rayures"]
    sleeve = assess_quality(L("LP Al Green - pochette abîmée", "Bon état"))
    assert sleeve.grade == "G+" and "pochette abîmée" in sleeve.mild
    for title in ("Vinyle Al Green voilé", "LP Al Green saute sur face B", "Al Green 33t fêlé", "LP très rayé"):
        q = assess_quality(L(title))
        assert q.severe and q.grade == "G", title
    no_sleeve = assess_quality(L("Disque seul Al Green LP sans pochette", "Bon état"))
    assert no_sleeve.no_sleeve and no_sleeve.grade == "G+"
    assert grade_at_least("VG+", "VG") and not grade_at_least("G+", "VG")


def test_resale_rejection_reasons():
    rs = ResaleSettings()
    ok = L("Vinyle Curtis Mayfield Superfly", "Très bon état")
    assert quality_rejection(ok, rs) is None
    assert quality_rejection(L("Curtis Mayfield Superfly", "Très bon état"), rs) == "vinyle non confirmé"
    assert quality_rejection(L("Vinyle Curtis Mayfield Superfly voilé"), rs) == "défaut grave"
    assert quality_rejection(L("Vinyle Curtis Mayfield Superfly sans pochette", "Très bon état"), rs) == "sans pochette"
    assert quality_rejection(L("Vinyle Curtis Mayfield Superfly", "Satisfaisant"), rs) == "état insuffisant"
    assert quality_rejection(L("Vinyle Curtis Mayfield Superfly + CD", "Très bon état"), rs) == "annonce mixte"
    relaxed = rs.model_copy(update={"min_grade": "G+", "allow_no_sleeve": True, "exclude_mixed": False})
    assert quality_rejection(L("Vinyle Curtis Mayfield Superfly", "Satisfaisant"), relaxed) is None
    assert quality_rejection(L("Lot de 10 vinyles soul Curtis Mayfield", "Bon état"),
                             rs.model_copy(update={"exclude_lots": True})) == "lot"
