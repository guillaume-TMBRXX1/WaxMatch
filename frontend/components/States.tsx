import type { ApiError } from "@/lib/api";

export function ConnectSpotify({ compact = false }: { compact?: boolean }) {
  return (
    <div className={compact ? "cluster" : "state glass"}>
      {!compact && (
        <>
          <span className="label">Première étape</span>
          <h2>Connecte ta bibliothèque</h2>
          <p className="subtitle" style={{ margin: 0 }}>
            WaxMatch lit tes albums Spotify (lecture seule) pour leur trouver des vinyles d&apos;occasion.
          </p>
        </>
      )}
      <a className="btn" href="/api/auth/login">
        Connecter Spotify
      </a>
    </div>
  );
}

export function ErrorState({ error, onRetry }: { error: ApiError; onRetry?: () => void }) {
  if (error.status === 401) return <ConnectSpotify />;
  return (
    <div className="state glass" role="alert">
      <span className="label negative">Impossible de charger</span>
      <p style={{ margin: 0, maxWidth: "52ch" }}>{error.message}</p>
      {onRetry && (
        <button type="button" className="btn-secondary" onClick={onRetry}>
          Réessayer
        </button>
      )}
    </div>
  );
}

export function GridSkeleton({ count = 12 }: { count?: number }) {
  return (
    <div className="grid-albums" aria-busy="true" aria-label="Chargement">
      {Array.from({ length: count }, (_, i) => (
        <div key={i} className="card">
          <div className="skeleton" style={{ aspectRatio: "1" }} />
          <div className="skeleton" style={{ height: 16, marginTop: 12, width: "80%" }} />
          <div className="skeleton" style={{ height: 12, marginTop: 8, width: "55%" }} />
        </div>
      ))}
    </div>
  );
}

export function EmptyState({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div className="state glass">
      <h2>{title}</h2>
      <div className="subtitle" style={{ margin: 0 }}>
        {children}
      </div>
    </div>
  );
}
