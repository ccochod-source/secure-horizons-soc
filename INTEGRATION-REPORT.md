# État de l’intégration — 11 octobre 2026

## Branches réunies dans main local

- clement/agent-supabase et clement/interface-soc.
- controle_package (nom GitHub avec underscore) et passerelle_coffre : passerelle, coffre, leurres, contrôle packages, environnement victime de démonstration.
- Dernière branche backend-pipeline d’Alex, récupérée depuis son fork amc-boop via la PR #1, jusqu’au commit d0136d1 : stockage PostgreSQL et checkpoints.

Toutes les références distantes récupérées sont incluses dans main local. Aucun push effectué ; origin/main et la PR GitHub restent inchangés.

## Résolutions effectuées

Fusion des dépendances Python dans une seule .venv ; conservation des deux applications backend sur des ports différents ; documentation séparée défense/passerelle ; fusion des variables d’exemple et fichiers ignorés. Conservation du frontend actuel à la racine, sans réintroduire l’ancien dossier frontend. Les tests d’Alex utilisent une base isolée et ne chargent pas DATABASE_URL depuis .env.

Commandes groupées : npm run dev:all (interface 3100, défense 8000, RAG 8001), npm run dev:full (ajoute passerelle 8002). Les ports occupés provoquent un arrêt explicite sans tuer les services existants. Une vérification PostgreSQL précède le lancement si DATABASE_URL est configuré.

## Vérifications réussies

- 124 tests Python ; dépendances Python cohérentes.
- Compilation Next.js et vérification TypeScript.
- 6 tests frontend.
- Test réel du RAG de main : /health HTTP 200 contre Supabase ; /chat HTTP 200 avec réponse OpenAI et une source. Ce test a enregistré des traces réelles d’une question normale.

## Blocages et limites

La connexion PostgreSQL configurée dans .env refuse la connexion avant authentification. L’accès HTTPS Supabase fonctionne. La passerelle et le stockage PostgreSQL d’Alex ne sont donc pas validés contre la base réelle ; confirmer le host et le port dans Supabase → Connect → Session pooler.

Les serveurs déjà ouverts pendant la vérification n’ont pas été remplacés : le serveur défense sur 8000 vient encore de l’ancien checkout temporaire, et le RAG sur 8001 n’a pas encore été redémarré. Le test réel ci-dessus utilise le code actuel de main dans un processus séparé, pas ces anciens serveurs. Le redémarrage complet doit suivre la correction PostgreSQL.

Le RAG simple lit documents et enregistre ses traces, puis les transmet à Alex. Il ne modifie pas les connaissances et n’installe pas de packages. La passerelle packages/leurres dispose de ses propres traces et alertes Supabase ; leur relais automatique vers les incidents d’Alex reste à intégrer. L’interface de validation packages reste à raccorder. Aucun confinement effectif d’outil n’est configuré pour le RAG en lecture seule.

Le pipeline d’Alex détecte actuellement les lectures sensibles suivies d’une sortie causale ; il ne garantit pas à lui seul la salubrité de tous les documents de la base. Les installations packages sans PACKAGE_AGENT_ENV sont simulées. Le semis automatique de leurres est désactivé pour préserver une base initialement saine.

Avec DATABASE_URL, Alex utilise le schéma trace de PostgreSQL. Les anciens incidents SQLite dans .runtime sont conservés, sans copie automatique vers PostgreSQL. Aucune attaque injectée dans la base et aucune décision humaine d’incident exécutée pendant cette intégration.
