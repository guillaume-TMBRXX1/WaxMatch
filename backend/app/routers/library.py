import asyncio
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
    """Bibliothèque normalisée : mémoire, puis base de données, puis Spotify (`refresh=true` force Spotify)."""
    state = request.app.state
    settings = spotify.settings
    user_key = spotify.tokens.spotify_user_id or spotify.session_id
    cached = state.library_cache.get(user_key)
    if cached and not refresh and time.time() - cached[0] < settings.library_cache_ttl_seconds:
        return cached[1]

    repo = state.library_repo
    if repo is not None and not refresh and spotify.tokens.spotify_user_id:
        stored = await repo.load(spotify.tokens.spotify_user_id)
        if stored and time.time() - stored[0].timestamp() < settings.library_max_age_hours * 3600:
            state.library_cache[user_key] = (time.time(), stored[1])
            return stored[1]

    items = [item async for item in spotify.iter_saved_albums(settings.max_albums)]
    artists_by_id: dict[str, dict] = {}
    if settings.spotify_artist_genres:
        artist_ids = [a["id"] for it in items for a in it["album"].get("artists", []) if a.get("id")]
        artists_by_id = await spotify.get_artists(artist_ids)

    albums = dedupe([normalize_saved_item(it, artists_by_id) for it in items])
    if repo is not None and spotify.tokens.spotify_user_id:
        await repo.save(spotify.tokens.spotify_user_id, albums)
    start_discogs_for_new_albums(request, albums)
    state.library_cache[user_key] = (time.time(), albums)
    return albums


def start_discogs_for_new_albums(request: Request, albums: list[LibraryAlbum]) -> None:
    """Nouveaux albums ajoutés sur Spotify : genres et styles Discogs cherchés en arrière-plan."""
    state = request.app.state
    settings = state.settings
    store = state.discogs_store
    job = state.discogs_job
    if not settings.discogs_token or job.running or not any(store.needs_lookup(a.match_key) for a in albums):
        return
    from app.deps import get_discogs
    from app.discogs.service import run_enrichment

    client = get_discogs(request, settings, state.http)
    state.discogs_task = asyncio.create_task(
        run_enrichment(client, store, job, albums, settings.discogs_match_threshold)
    )


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
