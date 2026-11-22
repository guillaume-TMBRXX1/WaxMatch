import Link from "next/link";
import { formatPrice } from "@/lib/format";
import type { Album } from "@/lib/types";

export function AlbumCard({ album, bestPrice }: { album: Album; bestPrice?: number | null }) {
  const tag = album.styles[0] ?? album.genres[0];
  return (
    <Link href={`/album/${album.spotify_id}`} className="card card-link">
      {album.cover_url ? (
        // eslint-disable-next-line @next/next/no-img-element
        <img className="cover" src={album.cover_url} alt="" loading="lazy" />
      ) : (
        <div className="cover" aria-hidden="true" />
      )}
      <div className="album-meta">
        <span className="album-title">{album.title_clean}</span>
        <span className="album-artist">
          {album.primary_artist}
          {album.release_year ? ` · ${album.release_year}` : ""}
        </span>
        {(tag || bestPrice != null) && (
          <span className="cluster" style={{ marginTop: 8 }}>
            {bestPrice != null && <span className="pill premium">dès {formatPrice(bestPrice)}</span>}
            {tag && <span className="pill">{tag}</span>}
          </span>
        )}
      </div>
    </Link>
  );
}
