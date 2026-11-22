-- Prix cible par album : « préviens-moi sous X € ».
create table album_targets (
    spotify_user_id  text not null references users on delete cascade,
    spotify_album_id text not null,
    match_key        text not null,
    target_price     numeric(10, 2) not null,
    updated_at       timestamptz not null default now(),
    primary key (spotify_user_id, spotify_album_id)
);
alter table album_targets enable row level security;
