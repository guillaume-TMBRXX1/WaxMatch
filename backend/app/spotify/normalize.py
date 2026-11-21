"""Nettoyage et normalisation des albums Spotify, pour la recherche sur les sites de revente.

Objectif : passer de "Rumours (Super Deluxe Edition) [2004 Remaster]" de "Fleetwood Mac"
à une clé stable "fleetwood mac|rumours" et une requête "Fleetwood Mac Rumours vinyle".
"""

import re
import unicodedata
from datetime import datetime

from pydantic import BaseModel
from rapidfuzz import fuzz

from app.discogs.models import DiscogsMatch

# Mots qui signalent une mention éditoriale sans intérêt pour trouver le vinyle.
_EDITION_WORDS = (
    r"remaster(?:ed)?|deluxe|expanded|anniversary|edition|[ée]dition|version|bonus|"
    r"special|collector'?s?|reissue|mono|stereo|super|legacy|definitive|complete|"
    r"original motion picture soundtrack"
)
_BRACKETED_EDITION = re.compile(
    rf"\s*[\(\[][^\)\]]*\b(?:{_EDITION_WORDS})\b[^\)\]]*[\)\]]", re.IGNORECASE
)
_DASH_EDITION = re.compile(rf"\s+[-–—]\s+[^-–—]*\b(?:{_EDITION_WORDS})\b.*$", re.IGNORECASE)
_FEAT = re.compile(r"\s*[\(\[]?\b(?:feat\.?|ft\.?|featuring)\b.*$", re.IGNORECASE)
_WITH = re.compile(r"\s*[\(\[]\s*(?:with|avec)\s[^\)\]]*[\)\]]", re.IGNORECASE)  # "(with Ry Cooder)"
_NICKNAME = re.compile(r"\s*[\"“”][^\"“”]+[\"“”]")  # Bobby "Blue" Bland -> Bobby Bland
_NON_ALNUM = re.compile(r"[^a-z0-9]+")


def clean_title(title: str) -> str:
    """Retire les mentions d'édition/remaster et les "feat." en gardant la casse d'origine."""
    out = _BRACKETED_EDITION.sub("", title)
    out = _DASH_EDITION.sub("", out)
    out = _WITH.sub("", out)
    out = _FEAT.sub("", out)
    return re.sub(r"\s{2,}", " ", out).strip() or title.strip()


def strip_nickname(name: str) -> str:
    """Retire un surnom entre guillemets : 'Bobby "Blue" Bland' -> 'Bobby Bland'."""
    return re.sub(r"\s{2,}", " ", _NICKNAME.sub("", name)).strip() or name


def fold(text: str) -> str:
    """Minuscules, sans accents ni ponctuation : "Beyoncé & Jay-Z" -> "beyonce and jay z"."""
    text = unicodedata.normalize("NFKD", text)
    text = "".join(c for c in text if not unicodedata.combining(c))
    text = text.lower().replace("&", " and ")
    return _NON_ALNUM.sub(" ", text).strip()


def artist_key(name: str) -> str:
    key = fold(name)
    return key[4:] if key.startswith("the ") else key


def match_key(artist: str, title: str) -> str:
    return f"{artist_key(artist)}|{fold(clean_title(title))}"


def similarity(a: str, b: str) -> float:
    """Score 0-100 entre deux libellés (servira à valider les annonces Vinted/Discogs)."""
    return fuzz.token_set_ratio(fold(a), fold(b))


def listing_matches(artist: str, title: str, listing_title: str, threshold: float = 80) -> bool:
    """Une annonce correspond-elle à l'album ? Il faut que l'artiste ET le titre y figurent."""
    lt = fold(listing_title)
    return (
        fuzz.partial_ratio(artist_key(artist), lt) >= threshold
        and fuzz.partial_ratio(fold(clean_title(title)), lt) >= threshold
    )


class LibraryAlbum(BaseModel):
    spotify_id: str
    title: str
    title_clean: str
    artists: list[str]
    primary_artist: str
    artist_ids: list[str]
    album_type: str
    total_tracks: int | None = None
    release_year: int | None = None
    label: str | None = None
    upc: str | None = None  # code-barres : correspondance exacte sur Discogs
    popularity: int | None = None
    cover_url: str | None = None
    spotify_url: str | None = None
    added_at: datetime | None = None
    genres: list[str] = []
    styles: list[str] = []  # styles Discogs, plus fins que les genres (ex. "House", "Shoegaze")
    # Indisponible via Spotify pour les nouvelles apps (audio-features fermé en nov. 2024) ;
    # sera renseigné par une source externe en phase 2.
    energy: float | None = None
    match_key: str
    search_query: str
    duplicates: list[str] = []  # autres ID Spotify fusionnés (deluxe, remaster…)
    discogs: DiscogsMatch | None = None


def _release_year(album: dict) -> int | None:
    date = album.get("release_date") or ""
    return int(date[:4]) if date[:4].isdigit() else None


def normalize_saved_item(item: dict, artists_by_id: dict[str, dict]) -> LibraryAlbum:
    album = item["album"]
    artists = [a["name"] for a in album.get("artists", [])]
    artist_ids = [a["id"] for a in album.get("artists", []) if a.get("id")]
    primary = artists[0] if artists else "Unknown"
    title_clean = clean_title(album["name"])

    genres: list[str] = list(album.get("genres") or [])
    for aid in artist_ids:
        for g in (artists_by_id.get(aid) or {}).get("genres") or []:
            if g not in genres:
                genres.append(g)

    images = album.get("images") or []
    added_at = item.get("added_at")
    return LibraryAlbum(
        spotify_id=album["id"],
        title=album["name"],
        title_clean=title_clean,
        artists=artists,
        primary_artist=primary,
        artist_ids=artist_ids,
        album_type=album.get("album_type", "album"),
        total_tracks=album.get("total_tracks"),
        release_year=_release_year(album),
        label=album.get("label"),
        upc=(album.get("external_ids") or {}).get("upc"),
        popularity=album.get("popularity"),
        cover_url=images[0]["url"] if images else None,
        spotify_url=(album.get("external_urls") or {}).get("spotify"),
        added_at=datetime.fromisoformat(added_at.replace("Z", "+00:00")) if added_at else None,
        genres=genres,
        match_key=match_key(primary, album["name"]),
        search_query=f"{primary} {title_clean} vinyle",
    )


def _added_ts(album: LibraryAlbum) -> float:
    return album.added_at.timestamp() if album.added_at else 0.0


def dedupe(albums: list[LibraryAlbum]) -> list[LibraryAlbum]:
    """Fusionne les doublons (édition standard + deluxe d'un même album).

    On garde l'entrée ajoutée le plus récemment et on mémorise les autres ID.
    """
    by_key: dict[str, LibraryAlbum] = {}
    for alb in albums:
        kept = by_key.get(alb.match_key)
        if kept is None:
            by_key[alb.match_key] = alb
            continue
        newer, older = (alb, kept) if _added_ts(alb) > _added_ts(kept) else (kept, alb)
        newer.duplicates = [*newer.duplicates, older.spotify_id, *older.duplicates]
        newer.genres = list(dict.fromkeys([*newer.genres, *older.genres]))
        by_key[alb.match_key] = newer
    return list(by_key.values())
