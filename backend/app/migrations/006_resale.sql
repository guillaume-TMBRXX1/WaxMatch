-- Onglet Revente (usage personnel) : liste de surveillance, opportunités repérées, réglages et compteurs.
create table resale_watchlist (
    key         text primary key,   -- match_key "artiste|titre"
    data        jsonb not null,
    updated_at  timestamptz not null default now()
);

create table resale_opportunities (
    key         text primary key,   -- "plateforme:identifiant"
    watch_key   text not null,
    status      text not null,      -- active | disparue
    margin      numeric(10, 2),
    data        jsonb not null,
    first_seen  timestamptz not null default now(),
    last_seen   timestamptz not null default now()
);
create index resale_opportunities_status_idx on resale_opportunities (status);

create table resale_meta (
    key   text primary key,         -- "settings", "usage:2026-11-22"…
    data  jsonb not null
);

alter table resale_watchlist     enable row level security;
alter table resale_opportunities enable row level security;
alter table resale_meta          enable row level security;
