from app.spotify.normalize import (
    clean_title,
    dedupe,
    fold,
    listing_matches,
    match_key,
    normalize_saved_item,
)


def test_clean_title_strips_editions():
    assert clean_title("Rumours (Super Deluxe Edition) [2004 Remaster]") == "Rumours"
    assert clean_title("Abbey Road - Remastered 2009") == "Abbey Road"
    assert clean_title("OK Computer OKNOTOK 1997 2017") == "OK Computer OKNOTOK 1997 2017"
    assert clean_title("Song (feat. Someone)") == "Song"


def test_clean_title_keeps_meaningful_brackets():
    assert clean_title("Live at Leeds (Live)") == "Live at Leeds (Live)"
    assert clean_title("(What's The Story) Morning Glory?") == "(What's The Story) Morning Glory?"


def test_fold_and_keys():
    assert fold("Beyoncé & Jay-Z") == "beyonce and jay z"
    assert match_key("The Beatles", "Abbey Road (Remastered)") == "beatles|abbey road"
    assert match_key("Beatles", "Abbey Road") == "beatles|abbey road"


def test_listing_matches():
    assert listing_matches("Daft Punk", "Discovery", "Vinyle DAFT PUNK - Discovery 2LP 2001")
    assert not listing_matches("Daft Punk", "Discovery", "Vinyle Justice - Cross")


def _item(album_id, name, added_at, genres=None):
    return {
        "added_at": added_at,
        "album": {
            "id": album_id,
            "name": name,
            "album_type": "album",
            "artists": [{"id": "a1", "name": "Fleetwood Mac"}],
            "release_date": "1977-02-04",
            "images": [{"url": "https://img/1"}],
            "external_ids": {"upc": "081227970949"},
            "genres": genres or [],
        },
    }


def test_normalize_and_dedupe():
    artists = {"a1": {"id": "a1", "genres": ["soft rock", "classic rock"]}}
    a = normalize_saved_item(_item("x1", "Rumours", "2023-01-01T00:00:00Z"), artists)
    b = normalize_saved_item(_item("x2", "Rumours (Super Deluxe)", "2025-06-01T00:00:00Z"), artists)

    assert a.release_year == 1977
    assert a.upc == "081227970949"
    assert a.genres == ["soft rock", "classic rock"]
    assert a.search_query == "Fleetwood Mac Rumours vinyle"

    merged = dedupe([a, b])
    assert len(merged) == 1
    assert merged[0].spotify_id == "x2"  # le plus récemment ajouté
    assert merged[0].duplicates == ["x1"]
