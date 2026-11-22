-- Annonces mises en favori par chaque utilisateur (copie de l'annonce au moment de l'ajout).
create table favorites (
    spotify_user_id  text not null references users on delete cascade,
    platform         text not null,
    external_id      text not null,
    spotify_album_id text not null,
    match_key        text not null,
    data             jsonb not null,
    created_at       timestamptz not null default now(),
    primary key (spotify_user_id, platform, external_id)
);
alter table favorites enable row level security;
