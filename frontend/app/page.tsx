"use client";

import Link from "next/link";
import { DealCard } from "@/components/DealCard";
import { ConnectSpotify, ErrorState } from "@/components/States";
import { useApi } from "@/lib/api";
import { formatPrice } from "@/lib/format";
import type { BestRow, Me } from "@/lib/types";

export default function Home() {
  const me = useApi<Me>("/auth/me");
  const best = useApi<{ total: number; albums: BestRow[] }>(me.data ? "/offers/best?sort=deal&limit=3" : null);
  const library = useApi<{ total: number }>(me.data ? "/library/albums?limit=1&include_singles=true" : null);

  if (me.error && me.error.status !== 401) return <ErrorState error={me.error} onRetry={me.reload} />;

  const loggedOut = me.error?.status === 401;
  const deals = best.data?.albums ?? [];
  const hotCount = deals.filter((d) => d.vs_discogs != null && d.vs_discogs <= 0.7).length;

  return (
    <>
      <section className="page-head">
        <span className="label">Spotify-to-Vinyl Smart Matcher</span>
        <h1 className="page-title" style={{ marginTop: 10 }}>
          Tes albums.
          <br />
          En vinyle. Au juste prix.
        </h1>
        <p className="subtitle">
          WaxMatch croise ta bibliothèque Spotify avec Vinted, 2ememain et Discogs, puis classe les offres
          d&apos;occasion par prix livré, bonne affaire et proximité.
        </p>
        {loggedOut && (
          <div style={{ marginTop: 28 }}>
            <ConnectSpotify compact />
          </div>
        )}
      </section>

      {me.data && (
        <div className="stack">
          <div className="kpis">
            <div className="panel kpi">
              <span className="label">Albums</span>
              <div className="figure">{library.data?.total ?? "—"}</div>
            </div>
            <div className="panel kpi">
              <span className="label">Avec offres</span>
              <div className="figure">{best.data?.total ?? "—"}</div>
            </div>
            <div className="panel kpi">
              <span className="label">Bonnes affaires</span>
              <div className={`figure${hotCount ? " negative" : ""}`}>{best.data ? hotCount : "—"}</div>
            </div>
            <div className="panel kpi">
              <span className="label">Meilleur prix</span>
              <div className="figure">
                {deals.length ? formatPrice(Math.min(...deals.map((d) => d.best.delivered_total ?? Infinity))) : "—"}
              </div>
            </div>
          </div>

          <div className="page-head" style={{ paddingBottom: 8 }}>
            <div className="row">
              <h2>À saisir maintenant</h2>
              <Link href="/affaires" className="btn-secondary">
                Voir toutes les affaires
              </Link>
            </div>
          </div>
          {deals.map((row, i) => (
            <DealCard key={row.spotify_id} row={row} featured={i === 0} />
          ))}
          {best.data && deals.length === 0 && (
            <p className="subtitle">
              Aucune offre en cache pour l&apos;instant : lance une analyse depuis la page{" "}
              <Link href="/affaires">Affaires</Link>.
            </p>
          )}
        </div>
      )}
    </>
  );
}
