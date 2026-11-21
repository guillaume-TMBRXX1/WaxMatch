"use client";

import Link from "next/link";
import { useApi } from "@/lib/api";
import { formatDelta, formatPrice } from "@/lib/format";
import type { BestRow } from "@/lib/types";

/** Bandeau défilant des meilleures affaires (en cache côté API : aucun coût). */
export function Ticker() {
  const { data } = useApi<{ albums: BestRow[] }>("/offers/best?sort=deal&limit=12");
  const rows = data?.albums ?? [];
  if (rows.length === 0) return null;
  const items = [...rows, ...rows]; // doublé pour une boucle continue
  return (
    <div className="ticker" role="region" aria-label="Meilleures affaires du moment">
      <span className="ticker-head">En direct</span>
      <div className="ticker-track">
        {items.map((row, i) => (
          <Link key={`${row.spotify_id}-${i}`} href={`/album/${row.spotify_id}`} tabIndex={i >= rows.length ? -1 : 0}>
            <strong>{row.title}</strong> · {row.artist} · {formatPrice(row.best.delivered_total)}
            {row.vs_discogs != null && row.vs_discogs <= 0.7 ? (
              <span className="negative"> {formatDelta(row.vs_discogs)}</span>
            ) : null}
          </Link>
        ))}
      </div>
    </div>
  );
}
