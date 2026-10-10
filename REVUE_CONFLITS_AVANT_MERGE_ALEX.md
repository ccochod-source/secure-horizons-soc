# Revue des conflits potentiels avant intégration avec Alex

Document préparatoire à transmettre au LLM d’Alex. Il décrit l’état local observé et les zones à comparer avant tout merge. Il ne constitue pas une autorisation de commit, push, pull ou merge.

## Consigne à donner au LLM d’Alex

Analyse ce document avec le contenu réel de la branche d’Alex et celui de `main`. Repère les conflits Git probables et les incompatibilités fonctionnelles, en particulier sur les variables d’environnement, les formats d’événements, les tables Supabase, les ports et le démarrage des deux services. Pour chaque risque, indique les fichiers/lignes concernés et propose la résolution minimale qui conserve les deux fonctionnalités. Ne modifie aucun fichier et ne lance aucune opération Git distante.

## État local observé

- Branche courante : `clement/agent-supabase`.
- La branche courante et le `main` local pointent actuellement sur le même commit (`1ff2cad`, `nouveau_front_simple`). Les travaux de cette branche sont donc encore dans les changements locaux non commités, y compris plusieurs nouveaux fichiers non suivis par Git.
- Aucun pull, push, commit ou merge n’a été effectué pour préparer ce document.
- Références distantes déjà présentes localement : `origin/pr-1` (ajoute le backend de pipeline sous `backend/`) et `origin/controle_package` (ajoute une autre implémentation sous `backend/` et une migration Supabase). Ces références peuvent être anciennes ; vérifier avec Alex laquelle correspond à sa branche actuelle. Aucune référence distante n’a été actualisée pour cette analyse.

## Travaux RAG à intégrer

Les changements locaux de l’agent RAG et de son raccordement au front comprennent notamment :

- `src/components/soc-console.tsx` : ajout du chat et affichage des réponses/sources.
- `src/app/globals.css` : styles de ce bloc de chat.
- `src/app/api/rag/chat/route.ts` : relais serveur local vers l’agent RAG, avec jeton conservé côté serveur.
- `victim_agent/` : agent RAG Python, recherche dans `documents`, écriture des traces dans `events`, relais des conversations et passerelle locale.
- `.env.example`, `.gitignore` et `README.md` : configuration/documentation Python et RAG.

Les fichiers de l’agent et de la route incluent des fichiers non suivis par Git : ils n’apparaîtront pas dans une comparaison de diff classique tant qu’ils ne seront pas ajoutés à une branche. Ne pas confondre « non suivi » avec « absent du travail local ».

## Zones de conflit à vérifier en priorité

### 1. `.gitignore` — conflit de texte probable

Les modifications RAG ajoutent les exclusions Python, environnements virtuels, caches et bases SQLite locales. `origin/pr-1` et `origin/controle_package` modifient également `.gitignore`. Garder toutes les règles utiles, en particulier les exclusions des fichiers d’environnement/secrets, `.venv/`, caches Python et bases de données locales. Vérifier qu’aucune règle n’exclut par erreur les migrations ou le code à partager.

### 2. `.env.example` — conflit de texte probable et risque de configuration

Le travail RAG modifie le `.env.example` racine pour ajouter sa clé de modèle et les paramètres de son service. `origin/controle_package` modifie aussi ce fichier ; `origin/pr-1` ajoute plutôt `backend/.env.example`. Fusionner les variables sans recopier aucune valeur de `.env` ou `.env.victim`. Garder une séparation explicite entre configuration racine/RAG et configuration du backend d’Alex, et vérifier notamment les noms qui se recoupent (`OPENAI_API_KEY`, `OPENAI_MODEL`, `CONFINEMENT_TOKEN`, `FRONTEND_ORIGIN`).

### 3. `README.md` racine — risque de cohérence fonctionnelle

La documentation locale décrit maintenant le chat RAG et précise que la pipeline d’Alex reste distincte. Conserver les instructions de démarrage des deux services et retirer toute affirmation devenue fausse après intégration. Les références `origin/pr-1` et `origin/controle_package` ajoutent un `backend/README.md` séparé ; vérifier que ses ports et commandes sont cohérents avec le service RAG.

### 4. `backend/` et `victim_agent/` — pas de conflit de chemin direct, intégration à examiner

Les deux composants sont dans des dossiers distincts, mais chacun est une application Python avec son propre point de démarrage et ses dépendances. Vérifier que les commandes d’installation et d’exécution indiquent correctement le dossier concerné, que les deux serveurs peuvent tourner ensemble, et qu’aucun import Python ne suppose un répertoire de lancement incompatible.

### 5. Contrat d’événements RAG → pipeline d’Alex — risque fonctionnel élevé

La pipeline de `origin/pr-1` attend `POST /events` avec `{ "agent_id": "…", "events": [...] }` et les champs d’événement documentés dans `backend/formats.py`. Le relais RAG doit conserver ces noms et types, notamment `id`, `parent_event_id`, `timestamp`, `actor`, `type`, `title`, `description`, `tool`, `resource` et `result` (`allowed`, `blocked` ou `flagged`). Vérifier les liens parent-enfant, le masquage des faux secrets et le comportement en cas d’envoi incertain afin d’éviter une double transmission ou plusieurs incidents.

Le RAG écrit également les traces dans Supabase. Cela ne remplace pas l’envoi du lot à Alex : confirmer si ce double stockage est voulu et que la transformation entre le schéma SQL de `events` et le format API d’Alex ne perd pas les identifiants ou la causalité.

### 6. Schéma Supabase et migrations — risque fonctionnel élevé

Le RAG suppose que `documents` est lisible et que les traces peuvent être insérées dans `events`. `origin/controle_package` ajoute une migration Supabase ; `origin/pr-1` garde le stockage de la pipeline sous `backend/`. Avant intégration, comparer la migration au schéma réellement en place : noms/types des colonnes, contraintes `parent_event_id`, droits de lecture/écriture et politique de masquage. Ne pas appliquer ou modifier une migration pendant la simple résolution de conflits sans validation de l’équipe.

### 7. Variables, jetons et ports — risque opérationnel

Le front appelle le RAG à `127.0.0.1:8001`, le backend de pipeline d’Alex documente `8000`, et la passerelle/confinement du RAG utilise également le port `8001`. Vérifier le plan de lancement complet et confirmer que les routes prévues (`/chat`, `/confinement`, `/events` ou récepteur de démonstration) appartiennent bien aux bons services. Les jetons doivent rester dans des fichiers locaux ignorés par Git ou dans l’environnement serveur, jamais dans le navigateur ni dans un fichier versionné.

## Contrôles à demander avant de conclure

1. Confirmer quelle référence locale correspond à la branche actuelle d’Alex (`origin/pr-1`, `origin/controle_package`, ou une autre).
2. Comparer les fichiers communs et vérifier les conflits Git réels avant tout merge.
3. Vérifier le contrat complet d’un événement RAG sur `/events`, avec une conversation normale et une conversation de test, puis la réponse à incident.
4. Confirmer le schéma Supabase et les permissions sans exposer ni recopier de secrets.
5. Démarrer le front, le RAG et la pipeline simultanément et valider les ports, les sources affichées et les traces.
6. Présenter les conflits et propositions de résolution à l’équipe ; ne pas intégrer sur `main` avant autorisation explicite.
