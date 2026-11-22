"use client";

import { useEffect, useState } from "react";
import { ErrorState } from "@/components/States";
import { api, ApiError, useApi } from "@/lib/api";
import type { Platform, UserSettings } from "@/lib/types";

const PRIORITIES: { value: UserSettings["priority"]; label: string; hint: string }[] = [
  { value: "price", label: "Prix", hint: "Le moins cher, quitte à payer le port" },
  { value: "balanced_price", label: "Équilibre · prix", hint: "Équilibre, avec une tendance prix bas" },
  { value: "balanced", label: "Équilibre", hint: "Prix et proximité à parts égales" },
  { value: "pickup", label: "Main propre", hint: "Proximité avant tout" },
];
const PLATFORMS: { value: Platform; label: string; hint: string }[] = [
  { value: "vinted", label: "Vinted", hint: "Envoi en point relais, catalogue européen" },
  { value: "2ememain", label: "2ememain", hint: "Petites annonces belges, main propre" },
  { value: "discogs", label: "Discogs", hint: "Marché mondial des disquaires et collectionneurs (sans coût Apify)" },
  { value: "leboncoin", label: "Leboncoin", hint: "France : main propre près de la frontière" },
];

export default function SettingsPage() {
  const remote = useApi<UserSettings>("/settings");
  const [form, setForm] = useState<UserSettings | null>(null);
  const [saving, setSaving] = useState(false);
  const [message, setMessage] = useState<{ ok: boolean; text: string } | null>(null);

  useEffect(() => {
    if (remote.data) setForm(remote.data);
  }, [remote.data]);

  if (remote.error) return <ErrorState error={remote.error} onRetry={remote.reload} />;
  if (!form) return <div className="card skeleton" style={{ height: 320, marginTop: 40 }} aria-busy="true" />;

  function togglePlatform(p: Platform) {
    setForm((f) => {
      if (!f) return f;
      const has = f.platforms.includes(p);
      const platforms = has ? f.platforms.filter((x) => x !== p) : [...f.platforms, p];
      return { ...f, platforms: platforms.length ? platforms : f.platforms };
    });
  }

  async function save(e: React.FormEvent) {
    e.preventDefault();
    if (!form) return;
    setSaving(true);
    setMessage(null);
    try {
      const saved = await api<UserSettings>("/settings", {
        method: "PUT",
        body: JSON.stringify({
          city: form.city || null,
          country: form.country,
          pickup_radius_km: form.pickup_radius_km,
          priority: form.priority,
          platforms: form.platforms,
        }),
      });
      setForm(saved);
      setMessage({ ok: true, text: saved.location_label ? `Enregistré · ${saved.location_label}` : "Enregistré" });
    } catch (err) {
      setMessage({ ok: false, text: err instanceof ApiError ? err.message : String(err) });
    } finally {
      setSaving(false);
    }
  }

  return (
    <>
      <section className="page-head">
        <span className="label">Réglages</span>
        <h1 className="page-title" style={{ marginTop: 10 }}>
          Mes préférences
        </h1>
        <p className="subtitle">Ta localisation sert à calculer les distances pour la remise en main propre.</p>
      </section>

      <form className="stack" onSubmit={save} style={{ maxWidth: 760 }}>
        <div className="card stack">
          <h2>Localisation</h2>
          <div className="cluster" style={{ alignItems: "flex-end", gap: 12 }}>
            <label className="field" style={{ flex: "2 1 220px" }}>
              <span className="label">Ville</span>
              <input
                className="input"
                value={form.city ?? ""}
                onChange={(e) => setForm({ ...form, city: e.target.value })}
                autoComplete="address-level2"
              />
            </label>
            <label className="field" style={{ flex: "1 1 120px" }}>
              <span className="label">Pays</span>
              <select className="select" value={form.country} onChange={(e) => setForm({ ...form, country: e.target.value })}>
                <option value="BE">Belgique</option>
                <option value="FR">France</option>
                <option value="LU">Luxembourg</option>
                <option value="NL">Pays-Bas</option>
              </select>
            </label>
          </div>
          <label className="field">
            <span className="label">Rayon de main propre : {form.pickup_radius_km} km</span>
            <input
              type="range"
              min={0}
              max={100}
              step={5}
              value={form.pickup_radius_km}
              onChange={(e) => setForm({ ...form, pickup_radius_km: Number(e.target.value) })}
              style={{ accentColor: "var(--accent)" }}
            />
          </label>
        </div>

        <div className="card stack">
          <h2>Priorité du score</h2>
          <div className="segmented" role="group" aria-label="Priorité">
            {PRIORITIES.map((p) => (
              <button
                key={p.value}
                type="button"
                aria-pressed={form.priority === p.value}
                onClick={() => setForm({ ...form, priority: p.value })}
              >
                {p.label}
              </button>
            ))}
          </div>
          <p className="subtitle" style={{ margin: 0 }}>
            {PRIORITIES.find((p) => p.value === form.priority)?.hint}
          </p>
        </div>

        <div className="card stack">
          <h2>Plateformes</h2>
          {PLATFORMS.map((p) => {
            const on = form.platforms.includes(p.value);
            return (
              <div key={p.value} className="cluster" style={{ justifyContent: "space-between", gap: 16 }}>
                <div>
                  <div style={{ fontWeight: 700 }}>{p.label}</div>
                  <div style={{ color: "var(--ink-2)", fontSize: 13 }}>{p.hint}</div>
                </div>
                <button
                  type="button"
                  className="switch"
                  role="switch"
                  aria-checked={on}
                  aria-label={p.label}
                  onClick={() => togglePlatform(p.value)}
                />
              </div>
            );
          })}
        </div>

        <div className="cluster">
          <button type="submit" className="btn" disabled={saving}>
            {saving ? "Enregistrement…" : "Enregistrer"}
          </button>
          {message && (
            <span role="status" className={message.ok ? undefined : "negative"} style={{ fontWeight: 600 }}>
              {message.text}
            </span>
          )}
        </div>
      </form>
    </>
  );
}
