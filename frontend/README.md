# WaxMatch — site (Next.js)

Interface « Glass éditorial » de WaxMatch : accueil, bibliothèque, bonnes affaires, fiche album, réglages.

- Le navigateur ne parle qu'au site : `app/api/[...path]/route.ts` relaie les appels vers l'API FastAPI
  (`BACKEND_URL`, variable serveur). Le cookie de session reste donc sur le domaine du site.
- Système de design : `app/globals.css` (tokens sur `:root`, mode sombre via `html[data-theme]`).

## Déploiement Vercel
- *Root Directory* : `frontend`
- Variable d'environnement : `BACKEND_URL` = adresse de l'API (ngrok pendant la phase Colab, puis Railway)
