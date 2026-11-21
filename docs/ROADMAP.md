# WaxMatch — Feuille de route

> Spotify-to-Vinyl Smart Matcher : relier la bibliothèque Spotify d'un utilisateur aux meilleures offres de vinyles d'occasion (Vinted, Leboncoin, Discogs…), en privilégiant le prix total livré et la remise en main propre.

**Règle de travail :** rien n'est installé en local. Le back-end se développe et se teste dans Google Colab (`notebook.ipynb`), le code vit sur GitHub, le front se prévisualise sur Vercel (un déploiement de prévisualisation par pull request).

## Architecture cible

```
Navigateur ──► Next.js (Vercel) ──► FastAPI (Railway) ──► Spotify Web API
                                         │  ├──► Apify Actors (Vinted, Leboncoin…)
                                         │  └──► API officielle Discogs
                                         └──► PostgreSQL (Supabase)
```

---

## Étape 0 — Fondations ✅ (ce bloc)
- Dépôt GitHub privé, monorepo `backend/` (FastAPI) + `frontend/` (Next.js, étape 5).
- Notebook Colab : clone du dépôt, tests, lancement de l'API derrière un tunnel HTTPS ngrok (domaine fixe gratuit, nécessaire car Spotify n'accepte que des Redirect URI en HTTPS).
- Secrets uniquement dans les Secrets Colab, puis dans les variables Railway/Vercel. Jamais dans le code.

## Étape 1 — Connexion Spotify et bibliothèque ✅ (ce bloc)
- OAuth « Authorization Code » côté serveur, paramètre `state` anti-CSRF, cookie de session signé qui ne contient qu'un identifiant opaque.
- Rafraîchissement automatique du jeton, gestion du 429 (`Retry-After`) et des erreurs 5xx.
- Récupération paginée de `/me/albums`, enrichissement des genres via les artistes (avec repli si l'endpoint groupé est fermé en Development Mode).
- Normalisation : suppression des mentions « Remaster », « Deluxe », « feat. »…, clé de correspondance `artiste|titre`, fusion des doublons, requête de recherche prête (`"Fleetwood Mac Rumours vinyle"`), conservation de l'UPC (code-barres).
- Tris disponibles : ajout récent, artiste, titre, année, popularité, genre ; filtre par genre.

**Contraintes Spotify à connaître :**
- Depuis novembre 2024, les nouvelles apps n'ont plus accès à `audio-features` (énergie, tempo…). Le tri par « énergie » passera par une source externe (étape 3b).
- Depuis février 2026, le *Development Mode* exige un compte Premium pour le propriétaire de l'app et plafonne à 5 utilisateurs. Pour ouvrir au public, il faudra demander l'*Extended Quota Mode* à Spotify. Il faut donc prévoir dès maintenant une page de confidentialité et un usage conforme aux règles développeur Spotify.
- Les genres d'albums reviennent souvent vides et ceux des artistes peuvent manquer : le code le tolère (`albums_without_genre`).

## Étape 2 — Base de données (Supabase PostgreSQL)
- Tables : `users` (id Spotify, nom, ville et code postal pour la géolocalisation, préférences), `oauth_tokens` (refresh_token **chiffré**), `albums` (catalogue normalisé partagé, clé `match_key` + UPC), `user_albums` (added_at, tags), `wishlist`, `listings` (annonces mises en cache avec `fetched_at`), `searches` (journal des runs Apify, coûts).
- Implémenter `PostgresTokenStore` derrière le `Protocol` existant (`app/store.py`) pour qu'aucun autre fichier ne change.
- Migrations SQL versionnées dans `backend/migrations/` et appliquées depuis l'éditeur SQL de Supabase.
- Synchronisation incrémentale de la bibliothèque : on s'arrête dès qu'on retrouve un `added_at` déjà connu.

## Étape 3 — Recherche des offres
**3a. Sources**
- **Discogs** : API officielle (jeton personnel gratuit). Recherche par **UPC/code-barres**, puis par artiste + titre en format Vinyl. `marketplace/stats` donne le prix le plus bas et le nombre d'exemplaires en vente. C'est la source la plus fiable, à brancher en premier.
- **Vinted, Leboncoin** : Actors Apify existants du Store (à évaluer : coût par résultat, champs disponibles comme les frais de port et la localisation, fiabilité), sinon un Actor maison. Appel via `apify-client` (Python), en asynchrone (lancement du run, puis récupération du dataset ou webhook).
- ⚖️ Les CGU de Vinted et Leboncoin encadrent strictement l'extraction automatisée. On ne lance que des requêtes ciblées à faible volume, on ne stocke que le minimum (titre, prix, lien, localisation), on renvoie systématiquement vers l'annonce d'origine et on ne republie aucune photo. À valider avant toute ouverture publique.

**3b. Enrichissement « énergie / ambiance »** : sources externes possibles (tags Last.fm, MusicBrainz/AcousticBrainz, API d'audio-features tierces). À choisir selon la couverture et la licence.

**3c. Orchestration**
- File de tâches : un job par album, avec priorité à la wishlist puis aux ajouts récents. Exécution par une tâche de fond Railway (cron), pas pendant la requête HTTP.
- Cache des résultats 12 à 24 h par `match_key`, mutualisé entre utilisateurs. Plafond de budget Apify par jour.
- Validation des annonces avec `listing_matches()` (correspondance floue sur l'artiste et le titre), exclusion des mots-clés CD, cassette, poster, tee-shirt…

## Étape 4 — Scoring
Score sur 100 par annonce, pondérations réglables par utilisateur :

| Critère | Poids indicatif | Calcul |
|---|---|---|
| Prix total livré | 45 | prix + port estimé (barème Mondial Relay / Relais Colis, ou port réel s'il est fourni), comparé à la médiane Discogs de la même édition |
| Proximité | 20 | distance entre la ville de l'annonce et celle de l'utilisateur ; bonus « main propre » sous un rayon configurable (géocodage via l'API Adresse data.gouv.fr) |
| Confiance | 15 | note et nombre d'avis du vendeur, état du disque (grille Goldmine : M, NM, VG+…) |
| Pertinence | 15 | score de correspondance floue, édition originale ou réédition, présence de l'UPC |
| Fraîcheur | 5 | ancienneté de l'annonce |

Alertes en rouge brique (`--live`) quand une offre passe sous le prix cible de la wishlist.

## Étape 5 — Front-end Next.js (style « Glass éditorial »)
- App Router, TypeScript, CSS Modules et tokens CSS sur `:root` (clair et sombre via `html[data-theme]`), Google Fonts via `next/font` (Big Shoulders Display, Manrope, Unbounded).
- Écrans :
  1. **Accueil / connexion** : grand titre condensé, bouton principal « Connecter Spotify ».
  2. **Ma bibliothèque** : grille de pochettes en cartes de verre, contrôle segmenté de tri (Récents · Genre · Artiste · Année), filtres de genre en pastilles, recherche.
  3. **Album** (panneau latéral) : offres classées, score en grand chiffre, prix total livré, distance, badge « Main propre », lien vers l'annonce.
  4. **Wishlist et alertes** : ticker défilant collé en haut avec les dernières baisses de prix, toasts.
  5. **Réglages** : ville, rayon, budget, pondérations du score, thème soleil/lune.
- Appels API avec `credentials: "include"`. En production, idéalement l'API sur un sous-domaine du front (ex. `api.waxmatch.fr`) pour que le cookie reste « first-party » ; sinon `COOKIE_SAMESITE=none`.
- Accessibilité : contraste vérifié sur le verre, focus visibles, `prefers-reduced-motion` respecté (fond animé coupé).

## Étape 6 — Déploiement
- **Railway** (API) : déploiement automatique depuis GitHub, commande de démarrage `uvicorn app.main:create_app --factory --host 0.0.0.0 --port $PORT`, variables d'environnement, cron pour les recherches.
- **Vercel** (front) : déploiement de prévisualisation sur chaque PR, variable `NEXT_PUBLIC_API_URL`.
- **Supabase** : base managée, sauvegardes, Row Level Security si le front lit directement certaines tables.
- Redirect URI Spotify de production ajoutée dans le dashboard.
- GitHub Actions : tests `pytest`, lint (ruff) et build Next.js sur chaque PR, sans rien exécuter en local.

## Étape 7 — Qualité et lancement
- Observabilité : logs structurés, suivi des coûts Apify, Sentry.
- RGPD : page de confidentialité, suppression de compte (jetons et données), durée de conservation des annonces.
- Demande d'*Extended Quota Mode* à Spotify avant d'ouvrir au-delà de 5 utilisateurs.
