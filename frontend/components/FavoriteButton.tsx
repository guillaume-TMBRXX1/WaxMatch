"use client";

export function FavoriteButton({
  active,
  onToggle,
  style,
}: {
  active: boolean;
  onToggle: () => void;
  style?: React.CSSProperties;
}) {
  const label = active ? "Retirer des favoris" : "Ajouter aux favoris";
  return (
    <button
      type="button"
      className="btn-secondary icon-btn fav-btn"
      aria-pressed={active}
      aria-label={label}
      title={label}
      style={style}
      onClick={(e) => {
        e.preventDefault();
        e.stopPropagation();
        onToggle();
      }}
    >
      <svg width="18" height="18" viewBox="0 0 24 24" aria-hidden="true" fill={active ? "currentColor" : "none"} stroke="currentColor" strokeWidth="2" strokeLinejoin="round">
        <path d="M12 3.5l2.6 5.3 5.9.9-4.3 4.1 1 5.8L12 16.9l-5.2 2.7 1-5.8L3.5 9.7l5.9-.9z" />
      </svg>
    </button>
  );
}
