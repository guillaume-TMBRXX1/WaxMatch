"use client";

import { useEffect, useRef, useState } from "react";
import { DealCard } from "@/components/DealCard";
import { EmptyState, ErrorState } from "@/components/States";
import { api, ApiError, useApi } from "@/lib/api";
import type { BestRow, ScanStatus } from "@/lib/types";

const SORTS = [
  { value: "deal", label: "Bonne affaire" },
  { value: "score", label: "Score" },
  { value: "price", label: "Prix" },
] as const;

export default function DealsPage() {
  const [sort, setSort] = useState<(typeof SORTS)[number]["value"]>("deal");
  const [limit, setLimit] = useState(30);
  const [status, setStatus] = useState<ScanStatus | null>(null);
  const [scanError, setScanError] = useState<string | null>(null);
  const best = useApi<{ total: number; albums: BestRow[] }>(`/offers/best?sort=${sort}&limit=200`);
  const timer = useRef<ReturnType<typeof setInterval> | null>(null);

  function poll() {
    if (timer.current) clearInterval(timer.current);
    timer.current = setInterval(async () => {
      try {
        const s = await api<ScanStatus>("/offers/scan/status");
        setStatus(s);
        if (!s.running) {
          if (timer.current) clearInterval(timer.current);
          best.reload();
        }
      } catch {
        /* on réessaie au prochain tick */
      }
    }, 3000);
  }

  useEffect(() => {
    api<ScanStatus>("/offers/scan/status")
      .then((s) => {
        setStatus(s);
        if (s.running) poll();
      })
      .catch(() => undefined);
    return () => {
      if (timer.current) clearInterval(timer.current);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  async function startScan() {
    setScanError(null);
    try {
      setStatus(await api<ScanStatus>(`/offers/scan?limit=${limit}`, { method: "POST" }));
      poll();
    } catch (e) {
      setScanError(e instanceof ApiError ? e.message : String(e));
    }
  }

  async function refreshReferences() {
    setScanError(null);
    try {
      setStatus(await api<ScanStatus>("/offers/references", { method: "POST" }));
      poll();
    } catch (e) {
      setScanError(e instanceof ApiError ? e.message : String(e));
    }
  }

  const running = status?.running ?? false;
  const rows = best.data?.albums ?? [];

  return (
    <>
      <section className="page-head">
        <div className="row">
          <div>
            <span className="label">{best.data ? `${best.data.total} albums avec offres` : "Affaires"}</span>
            <h1 className="page-title" style={{ marginTop: 10 }}>
              Bonnes affaires
            </h1>
            <p className="subtitle">
              La meilleure offre pour chaque album, comparée au prix Discogs typique livré.
            </p>
          </div>
          <div className="segmented" role="group" aria-label="Trier par">
            {SORTS.map((s) => (
              <button key={s.value} type="button" aria-pressed={sort === s.value} onClick={() => setSort(s.value)}>
                {s.label}
              </button>
            ))}
          </div>
        </div>
      </section>

      <div className="panel" style={{ marginBottom: 24 }}>
        <div className="cluster" style={{ justifyContent: "space-between", gap: 16 }}>
          <div style={{ minWidth: 0, flex: "1 1 260px" }}>
            <span className="label">Analyse des annonces</span>
            {running ? (
              <>
                <p style={{ margin: "6px 0 10px" }}>
                  {status!.phase} · {status!.done}/{status!.total} albums · {status!.listings_found} annonces
                </p>
                <div className="meter" aria-hidden="true">
                  <span style={{ width: `${status!.total ? (100 * status!.done) / status!.total : 5}%` }} />
                </div>
              </>
            ) : (
              <p style={{ margin: "6px 0 0", color: "var(--ink-2)" }}>
                Analyse d&apos;abord les albums jamais analysés, puis les plus anciennement analysés : en
                relançant, tu couvres toute ta bibliothèque (≈ 0,005 $ par album). Pour un album précis, ouvre sa
                fiche depuis la bibliothèque.
              </p>
            )}
          </div>
          <div className="cluster">
            <label className="field" style={{ width: 210 }}>
              <span className="sr-only">Nombre d&apos;albums à analyser</span>
              <select
                className="select"
                value={limit}
                onChange={(e) => setLimit(Number(e.target.value))}
                disabled={running}
              >
                {[10, 30, 100, 300].map((n) => (
                  <option key={n} value={n}>
                    {n} albums
                  </option>
                ))}
                <option value={5000}>Toute la bibliothèque</option>
              </select>
            </label>
            <button type="button" className="btn" onClick={startScan} disabled={running}>
              {running ? "Analyse…" : "Analyser"}
            </button>
            <button
              type="button"
              className="btn-secondary"
              onClick={refreshReferences}
              disabled={running}
              title="Récupère la cote Discogs par état des albums qui ont des offres (gratuit)"
            >
              Mettre à jour les cotes Discogs
            </button>
          </div>
        </div>
        {(scanError || status?.last_error) && (
          <p className="negative" role="alert" style={{ margin: "10px 0 0" }}>
            {scanError ?? status?.last_error}
          </p>
        )}
      </div>

      {best.error ? (
        <ErrorState error={best.error} onRetry={best.reload} />
      ) : best.loading && !best.data ? (
        <div className="stack" aria-busy="true">
          {[0, 1, 2].map((i) => (
            <div key={i} className="card skeleton" style={{ height: 120 }} />
          ))}
        </div>
      ) : rows.length === 0 ? (
        <EmptyState title="Pas encore d'offres">
          Lance une analyse ci-dessus : WaxMatch cherchera tes albums sur Vinted et 2ememain.
        </EmptyState>
      ) : (
        <div className="stack">
          {rows.map((row, i) => (
            <DealCard key={row.spotify_id} row={row} featured={i === 0 && sort === "deal"} />
          ))}
        </div>
      )}
    </>
  );
}
