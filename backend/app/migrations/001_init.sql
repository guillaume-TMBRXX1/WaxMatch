-- WaxMatch : schéma initial.
-- Le back-end se connecte avec le rôle "postgres" (il contourne la RLS). On active la RLS sans
-- aucune politique sur chaque table : l'API REST publique de Supabase (clé "anon") n'y a donc
-- aucun accès, ce qui protège les jetons même si cette clé fuitait.

create table users (
    spotify_user_id text primary key,
    display_name    text,
    created_at      timestamptz not null default now(),
    updated_at      timestamptz not null default now()
);

create table oauth_tokens (
    spotify_user_id   text primary key references users on delete cascade,
    access_token_enc  text not null,   -- chiffré (Fernet)
    refresh_token_enc text not null,   -- chiffré (Fernet)
    expires_at        timestamptz not null,
    scope             text not null default '',
    updated_at        timestamptz not null default now()
);

create table sessions (
    session_hash    text primary key,  -- SHA-256 de l'identifiant du cookie, jamais l'identifiant lui-même
    spotify_user_id text not null references users on delete cascade,
    created_at      timestamptz not null default now(),
    last_seen_at    timestamptz not null default now()
);
create index sessions_user_idx on sessions (spotify_user_id);

create table user_albums (
    spotify_user_id  text not null references users on delete cascade,
    spotify_album_id text not null,
    match_key        text not null,
    added_at         timestamptz,
    data             jsonb not null,
    primary key (spotify_user_id, spotify_album_id)
);
create index user_albums_match_key_idx on user_albums (match_key);

create table library_syncs (
    spotify_user_id text primary key references users on delete cascade,
    synced_at       timestamptz not null,
    album_count     integer not null
);

-- Partagées entre utilisateurs : un même album n'est cherché qu'une fois sur Discogs.
create table discogs_matches (
    match_key  text primary key,
    found      boolean not null,
    data       jsonb not null,
    matched_at timestamptz not null default now()
);

create table discogs_offers (
    match_key  text primary key,
    data       jsonb not null,
    checked_at timestamptz not null default now()
);

alter table users           enable row level security;
alter table oauth_tokens    enable row level security;
alter table sessions        enable row level security;
alter table user_albums     enable row level security;
alter table library_syncs   enable row level security;
alter table discogs_matches enable row level security;
alter table discogs_offers  enable row level security;
