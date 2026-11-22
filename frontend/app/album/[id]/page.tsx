"use client";

import Link from "next/link";
import { use, useState } from "react";
import { FavoriteButton } from "@/components/FavoriteButton";
import { ErrorState } from "@/components/States";
import { useFavorites } from "@/lib/favorites";
import { api, ApiError, useApi } from "@/lib/api";
import { formatDelta, formatPrice, PLATFORM_LABEL } from "@/lib/format";
import type { Album, AlbumListings, Listing } from "@/lib/types";

const COMPONENT_LABEL: Record<string, string> = {
  price: "Prix",
  deal: "Affaire",
  proximity: "Proximité",
  trust: "Confiance",
  freshness: "Fraîcheur",
};

function ListingRow({
  listing,
  reference,
  first,
  favorite,
  onToggleFavorite,
}: {
  listing: Listing;
  reference: number | null;
  first: boolean;
  favorite: boolean;
  onToggleFavorite: () => void;
}) {
  const ref = listing.reference ?? reference; // cote Discogs de l'état de l'annonce si connue
  const delta = ref && listing.delivered_total ? formatDelta(listing.delivered_total / ref) : null;
  const hot = ref != null && listing.delivered_total != null && listing.delivered_total <= ref * 0.7;
  return (
    <article className={`card${first ? " featured" : ""}${hot ? " hot" : ""}`} style={{ position: "relative" }}>
      <FavoriteButton active={favorite} onToggle={onToggleFavorite} style={{ position: "absolute", top: 10, left: 10, zIndex: 1 }} />
      <div className="deal-row">
        {listing.photo_url ? (
          // eslint-disable-next-line @next/next/no-img-element
          <img className="cover" src={listing.photo_url} alt="" loading="lazy" />
        ) : (
          <div className="cover" aria-hidden="true" />
        )}
        <div style={{ minWidth: 0 }}>
          <div className="cluster" style={{ marginBottom: 6 }}>
            {listing.under_target && <span className="badge-live">Sous ta cible</span>}
            {hot && <span className="badge-live">Bonne affaire</span>}
            <span className="pill">{PLATFORM_LABEL[listing.platform]}</span>
            {listing.format_hint && <span className="pill">{listing.format_hint}</span>}
            {listing.condition && <span className="pill">{listing.condition}</span>}
            {listing.grade && <span className="pill">≈ {listing.grade}</span>}
          </div>
          <a href={listing.url} target="_blank" rel="noopener noreferrer" style={{ textDecoration: "none" }}>
            <span className="album-title" style={{ fontSize: 20 }}>
              {listing.title}
            </span>
          </a>
          <ul className="notes">
            {listing.city && <li>{listing.city}</li>}
            {listing.notes.map((n) => (
              <li key={n}>{n}</li>
            ))}
          </ul>
        </div>
        <div className="deal-price">
          <div className="figure" style={{ fontSize: 36 }}>
            {formatPrice(listing.delivered_total)}
          </div>
          <div className="label" style={{ marginTop: 6 }}>
            {listing.delivery_mode ?? ""}
            {delta ? <span className={hot ? " negative" : ""}> · {delta}</span> : null}
          </div>
          <div className="label" style={{ marginTop: 10 }}>
            Score <span className="figure" style={{ fontSize: 22, color: "var(--ink)" }}>{Math.round(listing.score)}</span>
          </div>
        </div>
      </div>
      <details style={{ marginTop: 12 }}>
        <summary className="label" style={{ cursor: "pointer" }}>
          Détail du score
        </summary>
        <div className="stack" style={{ gap: 8, marginTop: 10 }}>
          {Object.entries(listing.components).map(([key, value]) => (
            <div key={key} style={{ display: "grid", gridTemplateColumns: "90px 1fr 36px", gap: 10, alignItems: "center" }}>
              <span className="label">{COMPONENT_LABEL[key] ?? key}</span>
              <div className="meter">
                <span style={{ width: `${value}%` }} />
              </div>
              <span style={{ textAlign: "right", fontVariantNumeric: "tabular-nums" }}>{Math.round(value)}</span>
            </div>
          ))}
          <a href={listing.url} target="_blank" rel="noopener noreferrer" className="btn-secondary" style={{ alignSelf: "flex-start" }}>
            Ouvrir l&apos;annonce
          </a>
        </div>
      </details>
    </article>
  );
}

function TargetPrice({
  spotifyId,
  current,
  onSaved,
}: {
  spotifyId: string;
  current: number | null;
  onSaved: () => void;
}) {
  const [value, setValue] = useState("");
  const [message, setMessage] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function save(e: React.FormEvent) {
    e.preventDefault();
    const price = Number(value.replace(",", "."));
    if (!price || price <= 0) {
      setMessage("Indique un prix supérieur à 0 €.");
      return;
    }
    setBusy(true);
    setMessage(null);
    try {
      await api(`/targets/${spotifyId}`, { method: "PUT", body: JSON.stringify({ target_price: price }) });
      setValue("");
      onSaved();
    } catch (err) {
      setMessage(err instanceof ApiError ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  }

  async function remove() {
    setBusy(true);
    try {
      await api(`/targets/${spotifyId}`, { method: "DELETE" });
      onSaved();
    } finally {
      setBusy(false);
    }
  }

  return (
    <form className="panel cluster" onSubmit={save} style={{ marginBottom: 24, justifyContent: "space-between", gap: 12 }}>
      <div style={{ flex: "1 1 240px" }}>
        <span className="label">Prix cible</span>
        <p style={{ margin: "4px 0 0", color: "var(--ink-2)" }}>
          {current
            ? `Les annonces livrées sous ${formatPrice(current)} sont signalées.`
            : "Fixe le prix livré maximum que tu es prêt à payer : les annonces en dessous seront signalées."}
        </p>
      </div>
      <div className="cluster">
        <label className="field" style={{ width: 130 }}>
          <span className="sr-only">Prix cible en euros</span>
          <input
            className="input"
            inputMode="decimal"
            placeholder={current ? String(current) : "ex. 40"}
            value={value}
            onChange={(e) => setValue(e.target.value)}
          />
        </label>
        <button type="submit" className="btn-secondary" disabled={busy || !value}>
          {current ? "Modifier" : "Définir"}
        </button>
        {current && (
          <button type="button" className="btn-secondary" onClick={remove} disabled={busy}>
            Retirer
          </button>
        )}
      </div>
      {message && (
        <p className="negative" role="alert" style={{ margin: 0, flexBasis: "100%" }}>
          {message}
        </p>
      )}
    </form>
  );
}

export default function AlbumPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = use(params);
  const library = useApi<{ albums: Album[] }>("/library/albums?limit=2000&include_singles=true");
  const [refresh, setRefresh] = useState(0);
  const fav = useFavorites();
  const offers = useApi<AlbumListings>(`/offers/albums/${id}${refresh ? `?refresh=true&r=${refresh}` : ""}`);
  const grades = Object.entries(offers.data?.discogs_by_condition ?? {});
  const album = library.data?.albums.find((a) => a.spotify_id === id);

  if (offers.error?.status === 401) return <ErrorState error={offers.error} />;

  return (
    <>
      <section className="page-head">
        <Link href="/bibliotheque" className="label" style={{ textDecoration: "none" }}>
          ← Bibliothèque
        </Link>
        <div className="deal-row" style={{ marginTop: 18, gridTemplateColumns: "minmax(96px, 180px) 1fr" }}>
          {album?.cover_url ? (
            // eslint-disable-next-line @next/next/no-img-element
            <img className="cover" src={album.cover_url} alt="" />
          ) : (
            <div className="cover skeleton" aria-hidden="true" />
          )}
          <div style={{ minWidth: 0 }}>
            <span className="label">{album?.primary_artist ?? offers.data?.artist ?? " "}</span>
            <h1 className="page-title" style={{ marginTop: 8 }}>
              {album?.title_clean ?? offers.data?.title ?? "…"}
            </h1>
            <div className="cluster" style={{ marginTop: 14 }}>
              {album?.release_year && <span className="pill">{album.release_year}</span>}
              {[...(album?.genres ?? []), ...(album?.styles ?? [])].slice(0, 4).map((g) => (
                <span key={g} className="pill">
                  {g}
                </span>
              ))}
              {album?.discogs?.url && (
                <a className="btn-secondary" href={album.discogs.url} target="_blank" rel="noopener noreferrer">
                  Fiche Discogs
                </a>
              )}
              {album && (
                <a
                  className="btn-secondary"
                  href={`https://www.popsike.com/php/quicksearch.php?searchtext=${encodeURIComponent(
                    `${album.primary_artist} ${album.title_clean}`,
                  )}`}
                  target="_blank"
                  rel="noopener noreferrer"
                  title="Historique des ventes aux enchères eBay (pressages de collection)"
                >
                  Voir sur Popsike
                </a>
              )}
              {album?.spotify_url && (
                <a className="btn-secondary" href={album.spotify_url} target="_blank" rel="noopener noreferrer">
                  Écouter
                </a>
              )}
            </div>
          </div>
        </div>
      </section>

      <div className="kpis" style={{ marginBottom: 24 }}>
        <div className="panel kpi">
          <span className="label">Offres</span>
          <div className="figure">{offers.data ? offers.data.listings.length : "—"}</div>
        </div>
        <div className="panel kpi">
          <span className="label">Meilleur prix livré</span>
          <div className="figure">{formatPrice(offers.data?.listings[0]?.delivered_total)}</div>
        </div>
        <div className="panel kpi">
          <span className="label">Discogs typique</span>
          <div className="figure">{formatPrice(offers.data?.discogs_reference)}</div>
        </div>
        <div className="panel kpi">
          <span className="label">Inaccessibles</span>
          <div className="figure">{offers.data ? offers.data.unreachable.length : "—"}</div>
        </div>
      </div>

      <TargetPrice spotifyId={id} current={offers.data?.target_price ?? null} onSaved={offers.reload} />

      {grades.length > 0 && (
        <div className="panel" style={{ marginBottom: 24 }}>
          <span className="label">Cote Discogs par état (hors port, édition la plus répandue)</span>
          <div className="cluster" style={{ marginTop: 10, gap: 18 }}>
            {grades.map(([grade, value]) => (
              <div key={grade}>
                <span className="label">{grade}</span>
                <div className="figure" style={{ fontSize: 28 }}>
                  {formatPrice(value)}
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      <div className="cluster" style={{ justifyContent: "space-between", marginBottom: 16 }}>
        <h2>Offres</h2>
        <button
          type="button"
          className="btn-secondary"
          disabled={offers.loading}
          onClick={() => setRefresh(Date.now())}
          title="Interroge à nouveau Vinted et 2ememain (≈ 0,005 $)"
        >
          {offers.loading ? "Recherche…" : "Relancer la recherche"}
        </button>
      </div>

      {offers.error ? (
        <ErrorState error={offers.error} onRetry={offers.reload} />
      ) : offers.loading ? (
        <div className="state glass" aria-busy="true">
          <span className="label">Recherche en cours</span>
          <p style={{ margin: 0 }}>Vinted et 2ememain sont interrogés en direct (jusqu&apos;à une minute)…</p>
          <div className="meter" style={{ width: 220 }}>
            <span className="skeleton" style={{ width: "100%" }} />
          </div>
        </div>
      ) : offers.data && offers.data.listings.length === 0 ? (
        <div className="state glass">
          <h2>Aucune offre pour l&apos;instant</h2>
          <p className="subtitle" style={{ margin: 0 }}>
            Ce disque n&apos;est pas en vente près de chez toi en ce moment. Les résultats sont gardés 24 h.
          </p>
        </div>
      ) : (
        <div className="stack">
          {offers.data?.listings.map((l, i) => (
            <ListingRow
              key={`${l.platform}-${l.external_id}`}
              listing={l}
              reference={offers.data!.discogs_reference}
              first={i === 0}
              favorite={fav.isFavorite(l)}
              onToggleFavorite={() => fav.toggle(id, l)}
            />
          ))}
        </div>
      )}

      {(offers.data?.discogs_market?.length ?? 0) > 0 && (
        <section style={{ marginTop: 32 }}>
          <h2>Sur Discogs</h2>
          <p className="subtitle" style={{ marginBottom: 14 }}>
            Prix le plus bas de chaque édition, <strong>hors port</strong>. Le port dépend du vendeur (souvent élevé
            hors Europe) et certains ne livrent pas en Belgique : vérifie sur Discogs avant d&apos;acheter. Ces offres
            ne sont donc pas classées.
          </p>
          <div className="stack" style={{ gap: 10 }}>
            {offers.data!.discogs_market!.map((m) => (
              <div key={m.external_id} className="panel cluster" style={{ justifyContent: "space-between", gap: 12 }}>
                <div style={{ minWidth: 0, flex: "1 1 260px" }}>
                  <div style={{ fontWeight: 700 }}>{m.title}</div>
                  <div style={{ color: "var(--ink-2)", fontSize: 13 }}>
                    {m.stock} exemplaire{(m.stock ?? 0) > 1 ? "s" : ""} en vente
                  </div>
                </div>
                <div className="cluster">
                  <span className="figure" style={{ fontSize: 26 }}>
                    dès {formatPrice(m.price)}
                  </span>
                  <span className="label">+ port</span>
                  <a className="btn-secondary" href={m.url} target="_blank" rel="noopener noreferrer">
                    Voir sur Discogs
                  </a>
                </div>
              </div>
            ))}
          </div>
        </section>
      )}

      {offers.data?.searches.some((s) => s.error) && (
        <p className="negative" role="alert" style={{ marginTop: 16 }}>
          {offers.data.searches
            .filter((s) => s.error)
            .map((s) => `${PLATFORM_LABEL[s.platform]} : ${s.error}`)
            .join(" · ")}
        </p>
      )}
    </>
  );
}
