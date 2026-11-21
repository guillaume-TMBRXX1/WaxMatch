import time
from collections import Counter
from typing import Literal

from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel

from app.deps import get_spotify
from app.discogs.service import apply_match
from app.spotify.client import SpotifyClient
from app.spotify.normalize import LibraryAlbum, dedupe, fold, normalize_saved_item

router = APIRouter(prefix="/library", tags=["library"])

SortKey = Literal["added_at", "artist", "title", "release_year", "popularity", "genre"]


class AlbumsResponse(BaseModel):
    total: int
    sort: SortKey
    albums: list[LibraryAlbum]


async def load_library(request: Request, spotify: SpotifyClient, refresh: bool) -> list[LibraryAlbum]:
    """Récupère, enrichit (genres), normalise et dédoublonne la bibliothèque. Mise en cache par session."""
    cache: dict = request.app.state.library_cache
    ttl = spotify.settings.library_cache_ttl_seconds
    cached = cache.get(spotify.session_id)
    if cached and not refresh and time.time() - cached[0] < ttl:
        return cached[1]

    items = [item async for item in spotify.iter_saved_albums(spotify.settings.max_albums)]
    artist_ids = [a["id"] for it in items for a in it["album"].get("artists", []) if a.get("id")]
    artists_by_id = await spotify.get_artists(artist_ids)

    albums = dedupe([normalize_saved_item(it, artists_by_id) for it in items])
    cache[spotify.session_id] = (time.time(), albums)
    return albums


def with_discogs(request: Request, albums: list[LibraryAlbum]) -> list[LibraryAlbum]:
    """Ajoute genres, styles et fiche Discogs déjà connus (sans appel réseau)."""
    store = request.app.state.discogs_store
    return [apply_match(a, store.get(a.match_key)) for a in albums]


def sort_albums(albums: list[LibraryAlbum], sort: SortKey) -> list[LibraryAlbum]:
    if sort == "added_at":
        return sorted(albums, key=lambda a: a.added_at.timestamp() if a.added_at else 0, reverse=True)
    if sort == "artist":
        return sorted(albums, key=lambda a: (fold(a.primary_artist), a.release_year or 0))
    if sort == "title":
        return sorted(albums, key=lambda a: fold(a.title_clean))
    if sort == "release_year":
        return sorted(albums, key=lambda a: a.release_year or 0, reverse=True)
    if sort == "popularity":
        return sorted(albums, key=lambda a: a.popularity or -1, reverse=True)
    # "genre" : regroupe par genre dominant de la bibliothèque, puis par artiste.
    counts = Counter(g for a in albums for g in a.genres)

    def main_genre(a: LibraryAlbum) -> str:
        return max(a.genres, key=lambda g: counts[g]) if a.genres else "~"  # sans genre en dernier

    return sorted(albums, key=lambda a: (-counts.get(main_genre(a), 0), main_genre(a), fold(a.primary_artist)))


@router.get("/albums", response_model=AlbumsResponse)
async def list_albums(
    request: Request,
    sort: SortKey = "added_at",
    genre: str | None = Query(None, description="Filtre sur genres et styles (sous-chaîne), ex. 'jazz'"),
    on_discogs: bool | None = Query(None, description="true : seulement les albums trouvés sur Discogs"),
    include_singles: bool = False,
    limit: int = Query(200, ge=1, le=2000),
    refresh: bool = False,
    spotify: SpotifyClient = Depends(get_spotify),
):
    albums = with_discogs(request, await load_library(request, spotify, refresh))
    if not include_singles:
        albums = [a for a in albums if a.album_type != "single"]
    if genre:
        g = fold(genre)
        albums = [a for a in albums if any(g in fold(x) for x in [*a.genres, *a.styles])]
    if on_discogs is not None:
        albums = [a for a in albums if bool(a.discogs and a.discogs.found) == on_discogs]
    albums = sort_albums(albums, sort)
    return AlbumsResponse(total=len(albums), sort=sort, albums=albums[:limit])


@router.get("/genres")
async def list_genres(request: Request, spotify: SpotifyClient = Depends(get_spotify)):
    albums = with_discogs(request, await load_library(request, spotify, refresh=False))
    counts = Counter(g for a in albums for g in a.genres)
    styles = Counter(s for a in albums for s in a.styles)
    return {
        "genres": [{"name": g, "albums": n} for g, n in counts.most_common()],
        "styles": [{"name": s, "albums": n} for s, n in styles.most_common()],
        "albums_without_genre": sum(1 for a in albums if not a.genres),
    }
