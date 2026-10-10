# TRACE — Copilote SOC

Interface provisoire, assistant RAG Supabase et pipeline de défense d’Alex, avec une passerelle de traçage, un coffre, des leurres et le contrôle des packages.

## Démarrer depuis la racine

Node.js 20.9+ et Python 3.11+. Installer les dépendances dans un environnement local :

```sh
npm ci
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
npm run dev:all
```

Interface : http://127.0.0.1:3100. Défense : port 8000. RAG simple : port 8001.
La commande refuse de démarrer si un port est déjà occupé ; elle n’arrête aucun autre serveur. Ctrl+C arrête uniquement les processus qu’elle a lancés.

## Configuration privée

`.env.example` décrit les variables, `.env` contient les accès et `.env.victim` les jetons locaux. Ces fichiers privés sont ignorés par Git.

- `SUPABASE_URL` : URL HTTPS du projet pour l’interface et le RAG.
- `SUPABASE_SERVICE_ROLE_KEY` : clé serveur, jamais envoyée au navigateur.
- `DATABASE_URL` : connexion PostgreSQL pour la nouvelle passerelle. Elle ne remplace pas `SUPABASE_URL`.
- `OPENAI_API_KEY_RAG` et `RAG_MODEL` : assistant en lecture seule.
- `OPENAI_API_KEY_ENQUETEUR` : utilisée par le lancement groupé de la défense, à défaut `OPENAI_API_KEY`.
- `PASSERELLE_TOKEN`, `ANALYSTE_TOKEN`, `VICTIM_GATEWAY_TOKEN` : authentification des services locaux.

Les modèles se configurent avec leur identifiant d’API exact, pas leur nom d’affichage. Le backend de défense utilise `OPENAI_MODEL` ou `AGENT_MODEL`, le RAG utilise `RAG_MODEL`.

## Parcours actuellement raccordé

L’utilisateur pose une question → le RAG lit `documents` dans Supabase → OpenAI prépare une réponse sourcée → les traces sont ajoutées à `events` → elles sont envoyées au serveur d’Alex. L’interface distingue une livraison confirmée d’une livraison incertaine.

Les incidents et décisions humaines d’Alex sont conservés dans `.runtime/` (SQLite). Sans connecteur de confinement effectif, l’approbation reste en attente d’exécution : elle ne signifie pas qu’un outil est bloqué.

## Passerelle, coffre, leurres et packages

```sh
npm run dev:full
```

Ajoute `app.main:app` sur le port 8002. Une connexion PostgreSQL fonctionnelle, le schéma de Léon et les rôles de la migration dans `supabase/migrations/` sont requis. Cette application fournit aussi un agent victime de démonstration utilisant des outils : il est distinct du RAG simple du front.

Le semis de leurres est désactivé par défaut ; l’activer explicitement pour une démonstration. Sans `PACKAGE_AGENT_ENV`, les installations de packages sont simulées et marquées comme telles. Les agents de défense d’Alex ne reçoivent pas encore automatiquement les traces de cette nouvelle passerelle ; ses alertes en Supabase et les incidents d’Alex restent deux circuits distincts.

Guides : [backend](backend/README.md), [RAG](victim_agent/README.md).

## Vérifier

```sh
.venv/bin/python -m pytest -q
npm run build
npm run typecheck
node --test tests/*.test.ts
```

Les tests Python utilisent des modèles et bases isolés : ils ne prouvent pas à eux seuls que la passerelle démarre contre Supabase. L’interface affiche les connexions et résultats réels, sans fabriquer de succès.
