export function Logo() {
  return (
    <span className="logo" aria-hidden="true">
      {/* Disque vinyle stylisé */}
      <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="#fff" strokeWidth="1.6" style={{ position: "relative" }}>
        <circle cx="12" cy="12" r="9.5" />
        <circle cx="12" cy="12" r="6" opacity="0.55" />
        <circle cx="12" cy="12" r="2.2" fill="#fff" stroke="none" />
      </svg>
    </span>
  );
}

export function Wordmark() {
  return (
    <span>
      <span className="wordmark-kicker">Spotify → Vinyle</span>
      <span className="wordmark">
        Wax<em>Match</em>
      </span>
    </span>
  );
}
