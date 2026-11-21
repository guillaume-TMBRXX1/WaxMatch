# WaxMatch

[![Open In Colab](https://colab.research.google.com/assets/colab-badge.svg)](https://colab.research.google.com/github/guillaume-TMBRXX1/WaxMatch/blob/main/notebook.ipynb)

Spotify-to-Vinyl Smart Matcher : ta bibliothèque Spotify associée aux meilleures offres de vinyles d'occasion.

- `backend/` : API FastAPI (connexion Spotify, bibliothèque normalisée, puis recherche et scoring des offres)
- `notebook.ipynb` : lance l'API dans Google Colab derrière un tunnel HTTPS (mode d'emploi dans le notebook)
- `docs/ROADMAP.md` : feuille de route complète

## Endpoints disponibles

| Méthode | Route | Rôle |
|---|---|---|
| GET | `/auth/login` | Redirige vers l'écran de consentement Spotify |
| GET | `/auth/callback` | Retour OAuth : échange le code, ouvre la session |
| GET | `/auth/me` | Profil Spotify connecté |
| POST | `/auth/logout` | Ferme la session |
| GET | `/library/albums` | Albums normalisés. `sort=added_at\|artist\|title\|release_year\|popularity\|genre`, `genre=` (genres et styles), `on_discogs=`, `include_singles=`, `refresh=` |
| GET | `/library/genres` | Genres et styles de la bibliothèque, avec le nombre d'albums |
| POST | `/discogs/enrich` | Lance en arrière-plan la recherche Discogs (genres, styles, fiche) des albums non traités |
| GET | `/discogs/enrich/status` | Avancée de la recherche Discogs |
| GET | `/discogs/albums/{spotify_id}` | Éditions vinyles d'un album et prix Discogs les plus bas (hors port) |
| GET | `/health` | Contrôle de santé : état de la base, nombre d'utilisateurs et de correspondances Discogs |

Base de données : PostgreSQL/Supabase via `DATABASE_URL` (migrations appliquées automatiquement au démarrage, depuis `backend/app/migrations/`). Tests sur une vraie base : `TEST_DATABASE_URL=postgresql://… pytest`.

Lancement (Colab ou Railway) : `uvicorn app.main:create_app --factory --host 0.0.0.0 --port 8000`, depuis `backend/`.
