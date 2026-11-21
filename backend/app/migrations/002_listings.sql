-- Résultats des recherches d'annonces (Vinted, Leboncoin…) par album, mis en cache.
create table listing_searches (
    platform    text not null,
    match_key   text not null,
    query       text not null,
    searched_at timestamptz not null default now(),
    raw_count   integer not null default 0,
    kept_count  integer not null default 0,
    data        jsonb not null,
    primary key (platform, match_key)
);
create index listing_searches_match_key_idx on listing_searches (match_key);
alter table listing_searches enable row level security;
