"use client";

import Link from "next/link";
import { FavoriteButton } from "@/components/FavoriteButton";
import { EmptyState } from "@/components/States";
import { useFavorites } from "@/lib/favorites";
import { formatPrice, PLATFORM_LABEL } from "@/lib/format";
import type { Favorite } from "@/lib/types";

function since(ts: number | null): string {
  if (!ts) return "";
  const hours = Math.round((Date.now() / 1000 - ts) / 3600);
  return hours < 1 ? "il y a moins d'une heure" : hours < 48 ? `il y a ${hours} h` : `il y a ${Math.round(hours / 24)} j`;
}

function StatusBadge({ fav }: { fav: Favorite }) {
  if (fav.status === "disparue") return <span className="badge-live">Disparue · vendue ?</span>;
  if (fav.status === "en ligne") return <span className="pill">En ligne</span>;
  return <span className="pill">À vérifier</span>;
}

export default function FavoritesPage() {
  const { favorites, loaded, toggle } = useFavorites();
  const online = favorites.filter((f) => f.status === "en ligne");
  const drops = favorites.filter((f) => (f.price_change ?? 0) < 0);

  return (
    <>
      <section className="page-head">
        <span className="label">{loaded ? `${favorites.length} favori${favorites.length > 1 ? "s" : ""}` : "Favoris"}</span>
        <h1 className="page-title" style={{ marginTop: 10 }}>
          Mes favoris
        </h1>
        <p className="subtitle">
          Les annonces que tu gardes à l&apos;œil. Leur état est mis à jour à chaque nouvelle recherche de l&apos;album :
          baisse de prix, ou annonce disparue (sans doute vendue).
        </p>
      </section>

      {favorites.length > 0 && (
        <div className="kpis" style={{ marginBottom: 24 }}>
          <div className="panel kpi">
            <span className="label">Favoris</span>
            <div className="figure">{favorites.length}</div>
          </div>
          <div className="panel kpi">
            <span className="label">Toujours en ligne</span>
            <div className="figure">{online.length}</div>
          </div>
          <div className="panel kpi">
            <span className="label">Baisses de prix</span>
            <div className={`figure${drops.length ? " negative" : ""}`}>{drops.length}</div>
          </div>
          <div className="panel kpi">
            <span className="label">Total en ligne</span>
            <div className="figure">{formatPrice(online.reduce((sum, f) => sum + (f.listing.delivered_total ?? 0), 0))}</div>
          </div>
        </div>
      )}

      {!loaded ? (
        <div className="card skeleton" style={{ height: 140 }} aria-busy="true" />
      ) : favorites.length === 0 ? (
        <EmptyState title="Aucun favori pour l'instant">
          Clique sur l&apos;étoile d&apos;une annonce, dans <Link href="/affaires">Affaires</Link> ou sur la fiche d&apos;un
          album, pour la retrouver ici.
        </EmptyState>
      ) : (
        <div className="stack">
          {favorites.map((fav) => {
            const l = fav.listing;
            return (
              <article
                key={`${l.platform}-${l.external_id}`}
                className={`card${fav.status === "disparue" ? "" : (fav.price_change ?? 0) < 0 ? " hot" : ""}`}
                style={{ position: "relative", opacity: fav.status === "disparue" ? 0.72 : 1 }}
              >
                <FavoriteButton active onToggle={() => toggle(fav.spotify_id, l)} style={{ position: "absolute", top: 10, left: 10, zIndex: 1 }} />
                <div className="deal-row">
                  {fav.cover_url || l.photo_url ? (
                    // eslint-disable-next-line @next/next/no-img-element
                    <img className="cover" src={fav.cover_url ?? l.photo_url ?? ""} alt="" loading="lazy" />
                  ) : (
                    <div className="cover" aria-hidden="true" />
                  )}
                  <div style={{ minWidth: 0 }}>
                    <div className="cluster" style={{ marginBottom: 6 }}>
                      <StatusBadge fav={fav} />
                      <span className="pill">{PLATFORM_LABEL[l.platform]}</span>
                      {l.condition && <span className="pill">{l.condition}</span>}
                    </div>
                    <Link href={`/album/${fav.spotify_id}`} style={{ textDecoration: "none" }}>
                      <span className="album-title" style={{ fontSize: 22 }}>
                        {fav.album_title}
                      </span>
                    </Link>
                    <div className="album-artist">{fav.artist}</div>
                    <div className="album-artist" style={{ marginTop: 4 }}>
                      {l.title}
                    </div>
                    <ul className="notes">
                      <li>Ajouté {since(fav.saved_at)}</li>
                      {fav.last_checked && <li>Dernière vérification {since(fav.last_checked)}</li>}
                    </ul>
                  </div>
                  <div className="deal-price">
                    <div className="figure" style={{ fontSize: 36 }}>
                      {formatPrice(l.delivered_total)}
                    </div>
                    <div className="label" style={{ marginTop: 6 }}>
                      {fav.price_change != null && fav.price_change !== 0 ? (
                        <span className={fav.price_change < 0 ? "negative" : undefined}>
                          {fav.price_change < 0 ? "−" : "+"}
                          {formatPrice(Math.abs(fav.price_change))} depuis l&apos;ajout
                        </span>
                      ) : (
                        l.delivery_mode ?? ""
                      )}
                    </div>
                    <a className="btn-secondary" href={l.url} target="_blank" rel="noopener noreferrer" style={{ marginTop: 12 }}>
                      Ouvrir l&apos;annonce
                    </a>
                  </div>
                </div>
              </article>
            );
          })}
        </div>
      )}
    </>
  );
}
