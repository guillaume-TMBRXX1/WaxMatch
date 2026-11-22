import Link from "next/link";
import { FavoriteButton } from "./FavoriteButton";
import { formatDelta, formatPrice, PLATFORM_LABEL } from "@/lib/format";
import type { BestRow } from "@/lib/types";

export function DealCard({
  row,
  featured = false,
  favorite,
  onToggleFavorite,
}: {
  row: BestRow;
  featured?: boolean;
  favorite?: boolean;
  onToggleFavorite?: () => void;
}) {
  const delta = formatDelta(row.vs_discogs);
  const hot = row.vs_discogs != null && row.vs_discogs <= 0.7;
  const best = row.best;
  return (
    <div style={{ position: "relative" }}>
    <Link
      href={`/album/${row.spotify_id}`}
      className={`card card-link${featured ? " featured" : ""}${hot ? " hot" : ""}`}
    >
      <div className="deal-row">
        {row.cover_url ? (
          // eslint-disable-next-line @next/next/no-img-element
          <img className="cover" src={row.cover_url} alt="" loading="lazy" />
        ) : (
          <div className="cover" aria-hidden="true" />
        )}
        <div style={{ minWidth: 0 }}>
          <div className="cluster" style={{ marginBottom: 6 }}>
            {row.under_target && <span className="badge-live">Sous ta cible</span>}
            {hot && <span className="badge-live">Bonne affaire</span>}
            <span className="pill">{PLATFORM_LABEL[best.platform]}</span>
            <span className="pill">{best.delivery_mode === "main propre" ? `Main propre · ${best.distance_km} km` : "Envoi"}</span>
          </div>
          <div className="album-title" style={{ fontSize: 24 }}>
            {row.title}
          </div>
          <div className="album-artist">{row.artist}</div>
          <div className="album-artist" style={{ marginTop: 4 }}>
            {row.target_price ? `Cible ${formatPrice(row.target_price)} · ` : ""}
            {row.offers_count} offre{row.offers_count > 1 ? "s" : ""}
            {best.condition ? ` · ${best.condition}` : ""}
          </div>
        </div>
        <div className="deal-price" style={{ gridColumn: "span 1" }}>
          <div className="figure" style={{ fontSize: 40 }}>
            {formatPrice(best.delivered_total)}
          </div>
          <div className="label" style={{ marginTop: 6 }}>
            {delta ? (
              <span className={hot ? "negative" : undefined}>{delta} vs Discogs</span>
            ) : (
              "livré, estimation"
            )}
          </div>
        </div>
      </div>
    </Link>
    {onToggleFavorite && (
      <FavoriteButton active={Boolean(favorite)} onToggle={onToggleFavorite} style={{ position: "absolute", top: 10, left: 10 }} />
    )}
    </div>
  );
}
