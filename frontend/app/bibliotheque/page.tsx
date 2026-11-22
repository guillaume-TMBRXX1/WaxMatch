"use client";

import { useMemo, useState } from "react";
import { AlbumCard } from "@/components/AlbumCard";
import { EmptyState, ErrorState, GridSkeleton } from "@/components/States";
import { useApi } from "@/lib/api";
import type { Album, BestRow } from "@/lib/types";

const SORTS = [
  { value: "added_at", label: "Récents" },
  { value: "genre", label: "Genre" },
  { value: "artist", label: "Artiste" },
  { value: "release_year", label: "Année" },
] as const;

type Sort = (typeof SORTS)[number]["value"];

export default function LibraryPage() {
  const [sort, setSort] = useState<Sort>("added_at");
  const [genre, setGenre] = useState<string | null>(null);
  const [query, setQuery] = useState("");

  const params = new URLSearchParams({ sort, limit: "2000" });
  if (genre) params.set("genre", genre);
  const [refreshed, setRefreshed] = useState(0);
  if (refreshed) params.set("refresh", "true");
  if (refreshed) params.set("r", String(refreshed));
  const albums = useApi<{ total: number; albums: Album[] }>(`/library/albums?${params}`);
  const best = useApi<{ albums: BestRow[] }>("/offers/best?sort=price&limit=500");
  const bestPrice = useMemo(
    () => new Map((best.data?.albums ?? []).map((r) => [r.spotify_id, r.best.delivered_total])),
    [best.data],
  );
  const genres = useApi<{ genres: { name: string; albums: number }[]; styles: { name: string; albums: number }[] }>(
    "/library/genres",
  );

  const visible = useMemo(() => {
    const q = query.trim().toLowerCase();
    const list = albums.data?.albums ?? [];
    if (!q) return list;
    return list.filter((a) => `${a.title_clean} ${a.artists.join(" ")}`.toLowerCase().includes(q));
  }, [albums.data, query]);

  const topTags = [...(genres.data?.genres ?? []).slice(0, 6), ...(genres.data?.styles ?? []).slice(0, 8)];

  return (
    <>
      <section className="page-head">
        <span className="label">{albums.data ? `${albums.data.total} albums` : "Bibliothèque"}</span>
        <div className="row">
          <h1 className="page-title" style={{ marginTop: 10 }}>
            Ma bibliothèque
          </h1>
          <button
            type="button"
            className="btn-secondary"
            onClick={() => setRefreshed(Date.now())}
            disabled={albums.loading}
            title="Recharge tes albums depuis Spotify (sinon : automatiquement toutes les 6 h)"
          >
            {albums.loading && refreshed ? "Actualisation…" : "Actualiser depuis Spotify"}
          </button>
        </div>
        <p className="subtitle">
          Tes albums Spotify, enrichis des genres et styles Discogs. Clique sur un album pour chercher ses offres
          vinyles.
        </p>
      </section>

      <div className="stack" style={{ marginBottom: 24 }}>
        <div className="cluster" style={{ justifyContent: "space-between" }}>
          <div className="segmented" role="group" aria-label="Trier par">
            {SORTS.map((s) => (
              <button key={s.value} type="button" aria-pressed={sort === s.value} onClick={() => setSort(s.value)}>
                {s.label}
              </button>
            ))}
          </div>
          <label className="field" style={{ flex: "1 1 220px", maxWidth: 360 }}>
            <span className="sr-only">Rechercher un album ou un artiste</span>
            <input
              className="input"
              type="search"
              placeholder="Rechercher…"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
            />
          </label>
        </div>
        {topTags.length > 0 && (
          <div className="cluster" role="group" aria-label="Filtrer par genre">
            <button type="button" className="pill" aria-pressed={genre === null} onClick={() => setGenre(null)}>
              Tous
            </button>
            {topTags.map((t) => (
              <button
                key={t.name}
                type="button"
                className="pill"
                aria-pressed={genre === t.name}
                onClick={() => setGenre(genre === t.name ? null : t.name)}
              >
                {t.name} · {t.albums}
              </button>
            ))}
          </div>
        )}
      </div>

      {albums.error ? (
        <ErrorState error={albums.error} onRetry={albums.reload} />
      ) : albums.loading && !albums.data ? (
        <GridSkeleton />
      ) : visible.length === 0 ? (
        <EmptyState title="Aucun album">Aucun album ne correspond à ces filtres.</EmptyState>
      ) : (
        <div className="grid-albums">
          {visible.map((album) => (
            <AlbumCard key={album.spotify_id} album={album} bestPrice={bestPrice.get(album.spotify_id)} />
          ))}
        </div>
      )}
    </>
  );
}
