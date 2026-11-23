"use client";

import { useEffect, useRef, useState } from "react";
import { EmptyState, ErrorState } from "@/components/States";
import { api, ApiError, useApi } from "@/lib/api";
import { formatPrice, PLATFORM_LABEL } from "@/lib/format";
import type { Opportunity, ResaleSettings, ResaleStats, ResaleStatus, WatchItem } from "@/lib/types";

const VIEWS = [
  { value: "a_trier", label: "À trier" },
  { value: "pistes", label: "Pistes" },
  { value: "gardees", label: "Gardées" },
  { value: "disparues", label: "Disparues" },
  { value: "ecartees", label: "Écartées" },
] as const;
const SORTS = [
  { value: "margin", label: "Marge" },
  { value: "roi", label: "Rendement" },
  { value: "recent", label: "Récentes" },
  { value: "demand", label: "Demande" },
] as const;

function days(ts: number | null) {
  if (!ts) return null;
  return Math.max(1, Math.round((Date.now() / 1000 - ts) / 86400));
}

const REASONS = ["Pas un vinyle", "Mauvais état", "Revente surestimée", "Trop loin / port trop cher", "Autre"];

function Row({ label, value, strong }: { label: string; value: string; strong?: boolean }) {
  return (
    <div style={{ display: "flex", justifyContent: "space-between", gap: 12, fontWeight: strong ? 800 : 500 }}>
      <span style={{ color: strong ? "var(--ink)" : "var(--ink-2)" }}>{label}</span>
      <span style={{ fontVariantNumeric: "tabular-nums" }}>{value}</span>
    </div>
  );
}

function OpportunityDetails({ opp }: { opp: Opportunity }) {
  const l = opp.listing;
  const search = encodeURIComponent(`${opp.artist} ${opp.title}`);
  return (
    <div className="stack" style={{ gap: 14, marginTop: 12 }}>
      <div className="kpis" style={{ gridTemplateColumns: "repeat(auto-fit, minmax(240px, 1fr))" }}>
        <div className="panel stack" style={{ gap: 6 }}>
          <span className="label">Achat</span>
          <Row label="Prix affiché" value={formatPrice(opp.buy_price)} />
          {(opp.buy_fee ?? 0) > 0 && <Row label="Protection acheteur" value={formatPrice(opp.buy_fee)} />}
          <Row
            label={opp.delivery_mode === "main propre" ? "Main propre" : `Port ${l.shipping_cost != null ? "(vendeur)" : "(estimé)"}`}
            value={formatPrice(opp.buy_shipping ?? 0)}
          />
          <Row label="Total achat" value={formatPrice(opp.buy_total)} strong />
        </div>
        <div className="panel stack" style={{ gap: 6 }}>
          <span className="label">Revente estimée sur Vinted</span>
          <Row label="Prix de revente retenu" value={formatPrice(opp.resale_estimate)} strong />
          <span style={{ color: "var(--ink-2)", fontSize: 12.5 }}>Base : {opp.resale_basis}</span>
          {opp.vinted_median != null && <Row label={`Médiane Vinted (${opp.comparables.length} annonces)`} value={formatPrice(opp.vinted_median)} />}
          <Row label="− Total achat" value={formatPrice(opp.buy_total)} />
          <Row label="− Emballage" value={formatPrice(opp.packaging)} />
          <Row label="Marge nette" value={`+${formatPrice(opp.margin)}`} strong />
        </div>
        <div className="panel stack" style={{ gap: 6 }}>
          <span className="label">Discogs</span>
          {Object.entries(opp.discogs_by_condition).map(([g, v]) => (
            <Row key={g} label={`Cote ${g}${g === opp.grade ? " (cet état)" : ""}`} value={formatPrice(v)} strong={g === opp.grade} />
          ))}
          {opp.discogs_lowest != null && (
            <Row label={`Le moins cher (${opp.discogs_for_sale ?? "?"} en vente)`} value={`${formatPrice(opp.discogs_lowest)} + port`} />
          )}
        </div>
      </div>

      {opp.comparables.length > 0 && (
        <div className="panel">
          <span className="label">Annonces Vinted comparables (même disque)</span>
          <div className="stack" style={{ gap: 6, marginTop: 8 }}>
            {opp.comparables.map((c) => (
              <a key={c.url} href={c.url} target="_blank" rel="noopener noreferrer"
                 style={{ display: "flex", justifyContent: "space-between", gap: 12, textDecoration: "none" }}>
                <span style={{ minWidth: 0, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                  {c.title}
                  {c.condition ? <span style={{ color: "var(--ink-3)" }}> · {c.condition}</span> : null}
                </span>
                <strong style={{ fontVariantNumeric: "tabular-nums" }}>{formatPrice(c.price)}</strong>
              </a>
            ))}
          </div>
        </div>
      )}

      <div className="cluster">
        <span className="label">Comparer ailleurs :</span>
        {opp.discogs_url && <a className="btn-secondary" href={opp.discogs_url} target="_blank" rel="noopener noreferrer">Discogs (vinyles en vente)</a>}
        <a className="btn-secondary" href={`https://www.vinted.be/catalog?search_text=${search}&catalog[]=3041`} target="_blank" rel="noopener noreferrer">Vinted</a>
        <a className="btn-secondary" href={`https://www.popsike.com/php/quicksearch.php?searchtext=${search}`} target="_blank" rel="noopener noreferrer">Popsike</a>
        <a className="btn-secondary" href={`https://www.ebay.fr/sch/i.html?_nkw=${search}+vinyl&LH_Sold=1&LH_Complete=1`} target="_blank" rel="noopener noreferrer">eBay (vendus)</a>
      </div>
    </div>
  );
}

function OpportunityCard({
  opp,
  onDecide,
  onVerify,
}: {
  opp: Opportunity;
  onDecide: (decision: "gardee" | "ecartee" | null, reason?: string) => void;
  onVerify: () => Promise<string | null>;
}) {
  const [verifying, setVerifying] = useState(false);
  const [verifyMsg, setVerifyMsg] = useState<string | null>(null);
  const l = opp.listing;
  const gone = opp.status === "disparue";
  const [open, setOpen] = useState(false);
  const [askReason, setAskReason] = useState(false);
  return (
    <article className={`card${!gone && opp.roi >= 1 ? " hot" : ""}`} style={{ opacity: gone || opp.decision === "ecartee" ? 0.7 : 1 }}>
      <div className="deal-row">
        {opp.cover_url || l.photo_url ? (
          // eslint-disable-next-line @next/next/no-img-element
          <img className="cover" src={opp.cover_url ?? l.photo_url ?? ""} alt="" loading="lazy" />
        ) : (
          <div className="cover" aria-hidden="true" />
        )}
        <div style={{ minWidth: 0 }}>
          <div className="cluster" style={{ marginBottom: 6 }}>
            {gone ? <span className="badge-live">Disparue · vendue ?</span> : opp.roi >= 1 && <span className="badge-live">×2</span>}
            {opp.decision === "gardee" && <span className="pill premium">Gardée</span>}
            {opp.needs_check && <span className="pill">Piste · non vérifiée</span>}
            <span className="pill">{PLATFORM_LABEL[l.platform]}</span>
            <span className="pill">≈ {opp.grade}</span>
            {l.delivery_mode && (
              <span className="pill">{l.delivery_mode === "main propre" ? `Main propre · ${l.distance_km} km` : "Envoi"}</span>
            )}
          </div>
          <div className="album-title" style={{ fontSize: 22 }}>{opp.title}</div>
          <div className="album-artist">{opp.artist}</div>
          <div className="album-artist" style={{ marginTop: 4 }}>{l.title}</div>
          <ul className="notes">
            <li>Achat {formatPrice(opp.buy_total)} → revente ~{formatPrice(opp.resale_estimate)}</li>
            {opp.vinted_median != null && <li>Médiane Vinted {formatPrice(opp.vinted_median)}</li>}
            {opp.vinted_median != null && l.total_known != null && (
              <li style={{ fontWeight: 700, color: "var(--ink)" }}>
                Prix {Math.round((1 - l.total_known / opp.vinted_median) * 100)} % sous la médiane Vinted
              </li>
            )}
            {opp.risks.map((r) => (
              <li key={r} style={{ color: "var(--ochre)" }}>⚠ {r}</li>
            ))}
          </ul>
        </div>
        <div className="deal-price">
          <div className="label">Marge nette</div>
          <div className="figure" style={{ fontSize: 44 }}>+{formatPrice(opp.margin)}</div>
          <div className="label" style={{ marginTop: 6 }}>Rendement +{Math.round(opp.roi * 100)} %</div>
          <a className="btn-secondary" href={l.url} target="_blank" rel="noopener noreferrer" style={{ marginTop: 12 }}>
            Ouvrir l&apos;annonce
          </a>
        </div>
      </div>

      <div className="cluster" style={{ justifyContent: "space-between", marginTop: 12 }}>
        <button type="button" className="btn-secondary" aria-expanded={open} onClick={() => setOpen(!open)}>
          {open ? "Masquer le détail" : "Détail du calcul et comparaisons"}
        </button>
        <div className="cluster">
          {opp.needs_check && !opp.decision && (
            <button
              type="button"
              className="btn-secondary"
              disabled={verifying}
              onClick={async () => {
                setVerifying(true);
                setVerifyMsg(await onVerify());
                setVerifying(false);
              }}
              title="Récupère des annonces Vinted du même disque pour confirmer le prix de revente"
            >
              {verifying ? "Vérification…" : "Vérifier sur Vinted (~0,01 $)"}
            </button>
          )}
          {opp.decision ? (
            <button type="button" className="btn-secondary" onClick={() => onDecide(null)}>Annuler mon choix</button>
          ) : askReason ? (
            <>
              <span className="label">Pourquoi ?</span>
              {REASONS.map((r) => (
                <button key={r} type="button" className="pill" onClick={() => onDecide("ecartee", r)}>{r}</button>
              ))}
              <button type="button" className="btn-secondary" onClick={() => setAskReason(false)}>Annuler</button>
            </>
          ) : (
            <>
              <button type="button" className="btn-secondary" onClick={() => onDecide("gardee")} title="Intéressante : la garder">
                👍 Garder
              </button>
              <button type="button" className="btn-secondary" onClick={() => setAskReason(true)} title="Pas bonne : l'écarter">
                👎 Écarter
              </button>
            </>
          )}
        </div>
      </div>
      {verifyMsg && (
        <p role="status" style={{ margin: "10px 0 0", color: "var(--ink-2)" }}>
          {verifyMsg}
        </p>
      )}
      {open && <OpportunityDetails opp={opp} />}
    </article>
  );
}

function SettingsPanel({ onSaved }: { onSaved: () => void }) {
  const remote = useApi<ResaleSettings>("/resale/settings");
  const [form, setForm] = useState<ResaleSettings | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  useEffect(() => {
    if (remote.data) setForm(remote.data);
  }, [remote.data]);
  if (!form) return null;

  const num = (k: keyof ResaleSettings, label: string, suffix: string, step = 1, factor = 1) => (
    <label className="field" style={{ flex: "1 1 160px" }}>
      <span className="label">
        {label} ({suffix})
      </span>
      <input
        className="input"
        type="number"
        step={step}
        value={Math.round((form[k] as number) * factor * 100) / 100}
        onChange={(e) => setForm({ ...form, [k]: Number(e.target.value) / factor })}
      />
    </label>
  );

  async function save(e: React.FormEvent) {
    e.preventDefault();
    try {
      await api("/resale/settings", { method: "PUT", body: JSON.stringify(form) });
      setMessage("Enregistré");
      onSaved();
    } catch (err) {
      setMessage(err instanceof ApiError ? err.message : String(err));
    }
  }

  return (
    <form className="stack" onSubmit={save} style={{ marginTop: 14 }}>
      <div className="cluster" style={{ gap: 12, alignItems: "flex-end" }}>
        {num("min_margin", "Marge minimum", "€")}
        {num("min_roi", "Rendement minimum", "%", 5, 100)}
        {num("max_buy", "Achat maximum", "€")}
        {num("daily_budget_usd", "Budget Apify par jour", "$", 0.05)}
        {num("daily_apify_runs", "Recherches Apify par jour", "max")}
        {num("sweep_max_items", "Annonces par recherche de balayage", "nb")}
        {num("verify_top", "Vérifications automatiques", "nb")}
      </div>
      <div className="cluster" style={{ gap: 12, alignItems: "flex-end" }}>
        <label className="field" style={{ flex: "0 1 200px" }}>
          <span className="label">État minimum (défauts compris)</span>
          <select
            className="select"
            value={form.min_grade}
            onChange={(e) => setForm({ ...form, min_grade: e.target.value as ResaleSettings["min_grade"] })}
          >
            <option value="G+">G+ (usé, joue bien)</option>
            <option value="VG">VG (bon état)</option>
            <option value="VG+">VG+ (très bon état)</option>
            <option value="NM">NM (quasi neuf)</option>
          </select>
        </label>
      </div>
      <div className="stack" style={{ gap: 10 }}>
        {(
          [
            ["require_vinted_comparables", "Exiger des annonces Vinted comparables", "revente sur Vinted : seule la preuve par les prix Vinted compte"],
            ["discover_new_albums", "Découvrir des albums", "annonce d'un artiste suivi, album absent de la liste : recherche Discogs"],
            ["require_confirmed_vinyl", "Exiger une preuve que c'est un vinyle", "mention vinyle/LP/33t ou catégorie vinyles"],
            ["exclude_mixed", "Écarter les annonces mixtes", "vinyle + CD, goodies, poster…"],
            ["allow_no_sleeve", "Accepter les disques sans pochette", "forte décote à la revente"],
            ["exclude_lots", "Écarter les lots", "valeur par disque difficile à estimer"],
            ["exclude_reissues", "Écarter les rééditions", "cote inférieure aux originaux"],
          ] as const
        ).map(([key, label, hint]) => (
          <div key={key} className="cluster" style={{ justifyContent: "space-between", gap: 16 }}>
            <div>
              <div style={{ fontWeight: 700 }}>{label}</div>
              <div style={{ color: "var(--ink-2)", fontSize: 13 }}>{hint}</div>
            </div>
            <button
              type="button"
              className="switch"
              role="switch"
              aria-checked={form[key]}
              aria-label={label}
              onClick={() => setForm({ ...form, [key]: !form[key] })}
            />
          </div>
        ))}
      </div>
      <div className="cluster">
        {(["ebay", "vinted", "2ememain", "leboncoin"] as const).map((p) => (
          <button
            key={p}
            type="button"
            className="pill"
            aria-pressed={form.platforms.includes(p)}
            onClick={() =>
              setForm({
                ...form,
                platforms: form.platforms.includes(p) ? form.platforms.filter((x) => x !== p) : [...form.platforms, p],
              })
            }
          >
            {PLATFORM_LABEL[p]}
          </button>
        ))}
      </div>
      <label className="field">
        <span className="label">Recherches du balayage large (séparées par des virgules)</span>
        <textarea
          className="input"
          rows={3}
          style={{ borderRadius: 16, padding: "10px 16px", minHeight: 80 }}
          value={form.sweep_queries.join(", ")}
          onChange={(e) =>
            setForm({ ...form, sweep_queries: e.target.value.split(",").map((q) => q.trim()).filter(Boolean) })
          }
        />
        <span style={{ color: "var(--ink-2)", fontSize: 12.5 }}>
          Chaque recherche coûte 1 recherche Apify par plateforme. Idées : labels (« vinyle stax », « vinyle motown »,
          « vinyle philadelphia »), mots de vendeurs (« 33 tours soul », « disque funk original »).
        </span>
      </label>
      <p className="subtitle" style={{ margin: 0 }}>
        Styles surveillés : {form.styles.join(", ")} · genres secondaires : {form.extra_genres.join(", ")}
      </p>
      <div className="cluster">
        <button type="submit" className="btn-secondary">
          Enregistrer les réglages
        </button>
        {message && <span role="status">{message}</span>}
      </div>
    </form>
  );
}

export default function ResalePage() {
  const [view, setView] = useState<(typeof VIEWS)[number]["value"]>("a_trier");
  const [sort, setSort] = useState<(typeof SORTS)[number]["value"]>("margin");
  const [limit, setLimit] = useState(10);
  const [job, setJob] = useState<ResaleStatus | null>(null);
  const [error, setError] = useState<string | null>(null);
  const stats = useApi<ResaleStats>("/resale/stats");
  const opps = useApi<Opportunity[]>(`/resale/opportunities?view=${view}&sort=${sort}`);
  const watch = useApi<WatchItem[]>("/resale/watchlist?limit=24");
  const timer = useRef<ReturnType<typeof setInterval> | null>(null);

  function refreshAll() {
    stats.reload();
    opps.reload();
    watch.reload();
  }

  function poll() {
    if (timer.current) clearInterval(timer.current);
    timer.current = setInterval(async () => {
      try {
        const s = await api<ResaleStatus>("/resale/status");
        setJob(s);
        if (!s.running) {
          if (timer.current) clearInterval(timer.current);
          refreshAll();
        }
      } catch {
        /* prochain tick */
      }
    }, 3000);
  }

  useEffect(() => {
    api<ResaleStatus>("/resale/status")
      .then((s) => {
        setJob(s);
        if (s.running) poll();
      })
      .catch(() => undefined);
    return () => {
      if (timer.current) clearInterval(timer.current);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  async function decide(key: string, decision: "gardee" | "ecartee" | null, reason?: string) {
    try {
      await api(`/resale/opportunities/${encodeURIComponent(key)}/decision`, {
        method: "POST",
        body: JSON.stringify({ decision, reason: reason ?? null }),
      });
    } finally {
      opps.reload();
      stats.reload();
    }
  }

  async function verify(key: string): Promise<string | null> {
    try {
      const result = await api<Opportunity | null>(`/resale/opportunities/${encodeURIComponent(key)}/verify`, {
        method: "POST",
      });
      const msg = result ? null : "Prix Vinted vérifiés : ce n'est pas une affaire, piste retirée.";
      opps.reload();
      stats.reload();
      return msg;
    } catch (e) {
      return e instanceof ApiError ? e.message : String(e);
    }
  }

  async function launch(path: string) {
    setError(null);
    try {
      setJob(await api<ResaleStatus>(path, { method: "POST" }));
      poll();
    } catch (e) {
      setError(e instanceof ApiError ? e.message : String(e));
    }
  }

  if (stats.error) return <ErrorState error={stats.error} onRetry={stats.reload} />;
  const s = stats.data;
  const running = job?.running ?? false;
  const since = days(s?.observing_since ?? null);

  return (
    <>
      <section className="page-head">
        <span className="label">Revente · usage personnel · revente sur Vinted</span>
        <h1 className="page-title" style={{ marginTop: 10 }}>
          Revente
        </h1>
        <p className="subtitle">
          Vinyles funk/soul (et plus) achetables sous leur valeur de revente. Mode observation : note les opportunités
          quelques semaines avant d&apos;acheter, pour mesurer la rentabilité réelle.
        </p>
      </section>

      <div className="kpis" style={{ marginBottom: 16 }}>
        <div className="panel kpi">
          <span className="label">Disques surveillés</span>
          <div className="figure">{s ? s.watched : "—"}</div>
          <span className="label">{s ? `${s.scanned} analysés` : ""}</span>
        </div>
        <div className="panel kpi">
          <span className="label">À trier</span>
          <div className="figure">{s ? s.to_review : "—"}</div>
          <span className="label">{s ? `${s.kept} gardées · ${s.dismissed} écartées` : ""}</span>
        </div>
        <div className="panel kpi">
          <span className="label">Marge potentielle</span>
          <div className="figure">{s ? formatPrice(s.active_margin_total) : "—"}</div>
        </div>
        <div className="panel kpi">
          <span className="label">Meilleure marge</span>
          <div className="figure">{s ? formatPrice(s.best_margin) : "—"}</div>
        </div>
      </div>

      {s && s.seen_total > 0 && (
        <p className="subtitle" style={{ marginTop: 0, marginBottom: 16 }}>
          Journal : observé depuis {since} j · {s.seen_last_7_days} opportunités vues sur 7 jours (
          {formatPrice(s.margin_seen_last_7_days)} de marge cumulée) · {s.gone} disparues (vendues ?)
        </p>
      )}

      <div className="panel" style={{ marginBottom: 24 }}>
        <div className="cluster" style={{ justifyContent: "space-between", gap: 16 }}>
          <div style={{ minWidth: 0, flex: "1 1 260px" }}>
            <span className="label">Analyse</span>
            {running ? (
              <>
                <p style={{ margin: "6px 0 10px" }}>
                  {job!.phase} · {job!.done}/{job!.total} · {job!.new_opportunities} nouvelles opportunités
                  {job!.discovered ? ` · ${job!.discovered} albums découverts` : ""}
                  {job!.cost ? ` · ${job!.cost.toFixed(3)} $` : ""}
                </p>
                <div className="meter" aria-hidden="true">
                  <span style={{ width: `${job!.total ? (100 * job!.done) / job!.total : 5}%` }} />
                </div>
              </>
            ) : (
              <p style={{ margin: "6px 0 0", color: "var(--ink-2)" }}>
                {s?.watched
                  ? `Apify : ${(s.spent_today ?? 0).toFixed(2)} $ aujourd'hui sur ${(s.daily_budget ?? 0).toFixed(2)} $ ` +
                    `(${(s.spent_month ?? 0).toFixed(2)} $ ce mois-ci, estimation). Un balayage large coûte jusqu'à ` +
                    `${(s.sweep_cost_usd ?? 0).toFixed(2)} $` +
                    ((s.sweep_cost_usd ?? 0) > (s.daily_budget ?? 0) - (s.spent_today ?? 0)
                      ? " : budget du jour insuffisant, il sera partiel."
                      : ".") +
                    ` eBay : ${s.ebay_configured ? "actif, gratuit" : "non configuré"}.`
                  : "Commence par construire la liste de surveillance : les disques les plus demandés sur Discogs (gratuit)."}
              </p>
            )}
          </div>
          <div className="cluster">
            {s?.watched ? (
              <>
                <label className="field" style={{ width: 140 }}>
                  <span className="sr-only">Nombre de disques à analyser</span>
                  <select className="select" value={limit} onChange={(e) => setLimit(Number(e.target.value))} disabled={running}>
                    {[5, 10, 30, 100].map((n) => (
                      <option key={n} value={n}>
                        {n} disques
                      </option>
                    ))}
                  </select>
                </label>
                <button type="button" className="btn" disabled={running} onClick={() => launch("/resale/sweep")}
                        title="Dernières annonces funk/soul de Vinted et 2ememain, comparées à toute la liste">
                  {running ? "Analyse…" : "Balayage large"}
                </button>
                <button type="button" className="btn-secondary" disabled={running} onClick={() => launch(`/resale/scan?limit=${limit}`)}>
                  Disque par disque
                </button>
                <button type="button" className="btn-secondary" disabled={running} onClick={() => launch("/resale/watchlist/build")}>
                  Reconstruire la liste
                </button>
              </>
            ) : (
              <button type="button" className="btn" disabled={running} onClick={() => launch("/resale/watchlist/build")}>
                {running ? "Construction…" : "Construire la liste"}
              </button>
            )}
          </div>
        </div>
        {!running && job && (job.filtered_total ?? 0) > 0 && (
          <p style={{ margin: "10px 0 0", color: "var(--ink-2)" }}>
            Dernière analyse : {job.filtered_total} annonces écartées —{" "}
            {Object.entries(job.filtered ?? {})
              .sort((a, b) => b[1] - a[1])
              .map(([reason, n]) => `${reason} (${n})`)
              .join(", ")}
          </p>
        )}
        {(error || job?.last_error) && (
          <p className="negative" role="alert" style={{ margin: "10px 0 0" }}>
            {error ?? job?.last_error}
          </p>
        )}
        <details style={{ marginTop: 12 }}>
          <summary className="label" style={{ cursor: "pointer" }}>
            Réglages de la revente
          </summary>
          <SettingsPanel onSaved={refreshAll} />
        </details>
      </div>

      <div className="cluster" style={{ justifyContent: "space-between", marginBottom: 16 }}>
        <div className="segmented" role="group" aria-label="Liste">
          {VIEWS.map((x) => (
            <button key={x.value} type="button" aria-pressed={view === x.value} onClick={() => setView(x.value)}>
              {x.label}
              {x.value === "a_trier" && s ? ` · ${s.to_review}` : ""}
              {x.value === "pistes" && s ? ` · ${s.pistes ?? 0}` : ""}
              {x.value === "gardees" && s ? ` · ${s.kept}` : ""}
            </button>
          ))}
        </div>
        <div className="segmented" role="group" aria-label="Trier par">
          {SORTS.map((x) => (
            <button key={x.value} type="button" aria-pressed={sort === x.value} onClick={() => setSort(x.value)}>
              {x.label}
            </button>
          ))}
        </div>
      </div>

      {opps.error ? (
        <ErrorState error={opps.error} onRetry={opps.reload} />
      ) : (opps.data ?? []).length === 0 ? (
        <EmptyState title="Aucune opportunité pour l'instant">
          {s?.watched
            ? "Lance une analyse : chaque disque surveillé est cherché sur eBay, Vinted et 2ememain, puis comparé à sa valeur de revente."
            : "Construis d'abord la liste de surveillance."}
        </EmptyState>
      ) : (
        <div className="stack">
          {opps.data!.map((o) => (
            <OpportunityCard
              key={o.key}
              opp={o}
              onDecide={(decision, reason) => decide(o.key, decision, reason)}
              onVerify={() => verify(o.key)}
            />
          ))}
        </div>
      )}

      {(watch.data ?? []).length > 0 && (
        <details style={{ marginTop: 32 }}>
          <summary className="label" style={{ cursor: "pointer" }}>
            Liste de surveillance (les plus demandés)
          </summary>
          <div className="stack" style={{ gap: 8, marginTop: 12 }}>
            {watch.data!.map((w) => (
              <div key={w.key} className="panel cluster" style={{ justifyContent: "space-between" }}>
                <span style={{ fontWeight: 700 }}>
                  {w.artist} — {w.title}
                  {w.year ? ` (${w.year})` : ""}
                  {w.discovered ? " · découvert" : ""}
                </span>
                <span className="label">
                  {w.want} want · {w.have} have{w.last_scanned ? " · analysé" : ""}
                </span>
              </div>
            ))}
          </div>
        </details>
      )}
    </>
  );
}
