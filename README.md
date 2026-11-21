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
| GET | `/library/albums` | Albums normalisés. `sort=added_at\|artist\|title\|release_year\|popularity\|genre`, `genre=`, `include_singles=`, `refresh=` |
| GET | `/library/genres` | Genres de la bibliothèque et nombre d'albums par genre |
| GET | `/health` | Contrôle de santé (Railway) |

Lancement (Colab ou Railway) : `uvicorn app.main:create_app --factory --host 0.0.0.0 --port 8000`, depuis `backend/`.
