# WaxMatch — Onglet « Revente » : plan

> Objectif : repérer des vinyles **achetables sous leur valeur de revente**, au-delà de la bibliothèque Spotify, sur plusieurs plateformes, avec des alertes en temps réel. Usage personnel.

## Principes
- **Même site, onglet interne** (`/revente`), même API, même base Supabase, même système de design.
- **La valeur de revente est le cœur du système** : sans estimation fiable par état, pas de marge fiable.
- **Budget maîtrisé** : chaque recherche Apify coûte, et la surveillance continue les multiplie. Plafonds journaliers obligatoires.
- **Cadre légal** : une activité régulière d'achat-revente est une activité commerciale en Belgique (statut d'indépendant au moins complémentaire, numéro BCE, TVA selon le cas). Les plateformes déclarent au fisc les vendeurs qui dépassent 30 ventes ou ~2 000 € par an (DAC7). Sur Vinted, les vendeurs professionnels relèvent de Vinted Pro. **À valider avec un comptable avant de revendre régulièrement.**

---

## Phase R0 — Prérequis techniques
- **Railway** (projet séparé de Snapline.live) : API toujours allumée, plus un **worker** qui exécute les surveillances planifiées.
- **Web push** : site installable (PWA : manifeste + service worker), clés VAPID, abonnements enregistrés en base, envoi via `pywebpush`.
  - Android et ordinateur : fonctionne dans le navigateur.
  - iPhone (iOS 16.4 ou plus) : seulement si le site est **ajouté à l'écran d'accueil**.
- **Garde-fous** : alerte de dépense Railway, plafond journalier de recherches Apify dans l'API.

## Phase R1 — Quoi chercher (l'univers de recherche)
On ne part plus de ta bibliothèque, mais d'une **liste de surveillance** de vinyles qui se revendent bien.

| Source de l'univers | Signal | Accès |
|---|---|---|
| Discogs : `community.want` / `community.have` | **Demande** : beaucoup de « want » pour peu de « have », c'est un disque recherché | API officielle (résultats de recherche) |
| Discogs : exemplaires en vente (`num_for_sale`) | **Rareté** : peu d'offres face à une forte demande | API officielle (`marketplace/stats`) |
| Discogs : prix conseillés par état | **Valeur de revente** par état (NM, VG+…) | API officielle (déjà intégrée) |
| Tes genres de prédilection (funk/soul, afro, jazz…) | Ta connaissance du marché = ton avantage | Réglages |
| Recherches libres (« lot vinyles », « 33 tours soul original »…) | Lots et vendeurs qui ignorent la valeur | Phase R4 |

**Score de liquidité** (le disque se revend-il vite ?) : demande (want), rareté (want/have, exemplaires en vente), prix.

## Phase R2 — Où chercher (sourcing)

| Plateforme | Accès | Intérêt depuis Namur | Priorité |
|---|---|---|---|
| **Vinted** (.be, catalogue européen) | Apify (en place) | Envoi en point relais | ✅ En place |
| **2ememain** | Apify (en place) | Main propre et envoi en Belgique | ✅ En place |
| **eBay** | **API officielle « Browse »** (gratuite, compte développeur) | Annonces européennes, **port affiché**, filtres prix et état | ⭐ Haute |
| **Marktplaats** (Pays-Bas, même groupe que 2ememain) | Plusieurs Actors Apify (environ 0,3 à 1,6 $ les 1 000 annonces) | Gros marché du vinyle ; main propre jusqu'à environ 100 km | Moyenne |
| **Kleinanzeigen** (Allemagne) | Actors Apify (environ 1,5 à 2 $ les 1 000 annonces) | Région d'Aix-la-Chapelle et Cologne en main propre | Moyenne |
| **Leboncoin** | Apify (en place) | Main propre près de la frontière seulement | Basse |
| **Facebook Marketplace** | **Pas d'API officielle** pour les annonces ; Actors Apify (environ 1,5 à 2,7 $ les 1 000 annonces, souvent avec proxies résidentiels payants) | Très fort pour les lots locaux | Basse : conditions de Meta et fiabilité à tester |
| **Discogs (achat)** | API sans port ni pays vendeur ; Actor Apify nécessaire pour le port réel | Large offre, mais port souvent élevé | Basse |
| CDandLP, Catawiki | Pas d'Actor trouvé (CDandLP) ; enchères (Catawiki) | — | Plus tard |

## Phase R3 — Évaluer la marge

**Marge nette estimée** = prix de revente estimé (cote Discogs de l'état estimé)
− frais de la plateforme de revente (Discogs : commission vendeur et frais de paiement ; Vinted : vérifier les frais vendeur en vigueur)
− frais d'envoi non couverts et emballage
− prix d'achat − port d'achat − protection acheteur

**Indicateurs affichés** : marge en euros, rendement (marge / coût d'achat), liquidité, niveau de confiance.

**Drapeaux de risque** : état inconnu ou peu de photos, ambiguïté entre original et réédition, « lot », vendeur sans avis, prix anormalement bas (arnaque possible).

**Filtres** : marge minimum (€), rendement minimum (%), prix d'achat maximum, distance maximum (main propre), plateformes, genres, liquidité minimum, exclure les rééditions, état minimum.

## Phase R4 — Lots et vendeurs qui ignorent la valeur
- Détection des annonces « lot de X vinyles » : prix par disque, artistes cités dans le titre ou la description (nécessite le détail des annonces, plus coûteux).
- Repérage des disques à forte cote dans les lots (comparaison avec la liste de surveillance).

## Phase R5 — Alertes en temps réel (Railway)
- **Recherches enregistrées** (« Soul originale sous 30 €, marge ≥ 15 € ») exécutées périodiquement par le worker.
- Mémoire des annonces déjà vues : une alerte par **nouvelle** opportunité seulement.
- **Notification web push** : titre, prix, marge estimée, lien direct. Heures calmes et résumé quotidien en option.

## Phase R6 — Suivi des achats et ventes
- Stock : prix d'achat, frais, prix de mise en vente, prix vendu.
- **Rentabilité réelle** (et non estimée), export pour la comptabilité.

---

## Coûts estimés (à affiner avec les vrais chiffres)
| Poste | Hypothèse | Coût mensuel |
|---|---|---|
| Railway (API + worker) | ~0,3 Go de mémoire, peu de processeur | ≈ 3 à 4 $ |
| Apify, surveillance modérée | 10 recherches × 2 plateformes toutes les 2 h = 240 runs/jour × ~0,002 $ | ≈ 15 $ |
| Apify, surveillance intensive | 15 recherches × 3 plateformes toutes les 30 min = 2 160 runs/jour | **≈ 130 $** (à éviter) |
| eBay Browse API | Gratuite (dans les quotas) | 0 $ |
| Discogs API | Gratuite | 0 $ |
| Supabase | Offre gratuite | 0 $ |

**La fréquence des surveillances est le principal levier de coût.** On privilégiera eBay (gratuit) et des recherches ciblées.

## Ordre de réalisation proposé
1. **R1 + R3 en lecture seule** : liste de surveillance Discogs, estimation de marge sur les annonces déjà trouvées. Ça ne coûte presque rien.
2. **R2 : eBay** (API officielle gratuite), puis Marktplaats et Kleinanzeigen si besoin.
3. **R0 + R5** : Railway, worker, web push et recherches enregistrées.
4. **R4** (lots), puis **R6** (suivi achats et ventes).
