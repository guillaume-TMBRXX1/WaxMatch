-- Réglages de chaque utilisateur (localisation, rayon de main propre, priorité, plateformes).
create table user_settings (
    spotify_user_id  text primary key references users on delete cascade,
    data             jsonb not null,
    updated_at       timestamptz not null default now()
);

-- Cache du géocodage des villes (Nominatim) : chaque ville n'est cherchée qu'une fois.
create table geocodes (
    query        text primary key,  -- "ville|pays"
    latitude     double precision,  -- null = introuvable
    longitude    double precision,
    display_name text,
    created_at   timestamptz not null default now()
);

alter table user_settings enable row level security;
alter table geocodes      enable row level security;
