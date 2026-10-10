# Assistant développeur RAG

L’assistant répond aux questions des développeurs à partir de la table Supabase
`documents`. Chaque requête relit les documents actuels : les nouvelles
connaissances sont donc prises en compte sans entraîner ni réentraîner le modèle.
Il retourne les références des sources trouvées et enregistre la question, les
documents consultés et la réponse dans `events`, avec leurs liens parent-enfant.
Après l’écriture réussie dans Supabase, il transmet le lot d’événements à la
pipeline d’Alex (`POST /events`). Une panne ou un délai dépassé chez Alex ne
supprime pas la réponse RAG : `pipeline_delivery.status` indique `unknown`, sans
réessai automatique, car le serveur a peut-être déjà traité la demande.

## Parcours

```text
Question → recherche textuelle Supabase → réponse GPT-6 Luna avec sources
                                      ↘ traces dans Supabase.events
                                       → lot d’événements → pipeline d’Alex
```

La recherche porte sur les champs `title` et `content` de `documents`, en
excluant les documents marqués `is_decoy`. Elle utilise la recherche plein texte
Postgres. La table a aussi un champ `embedding`, mais cette version n’en dépend
pas. Elle ne fait pas d’entraînement automatique.

## Configuration et démarrage

Le fichier racine `.env` fournit `DATABASE_URL`, `service_role_key` et
`OPENAI_API_KEY_RAG`. Garder ces secrets côté serveur et hors du dépôt. Le modèle
par défaut est `gpt-6-luna`; on peut le remplacer avec `RAG_MODEL`.

```bash
python -m pip install -r victim_agent/requirements.lock.txt
python -m victim_agent.cli init
python -m uvicorn victim_agent.app:app --host 127.0.0.1 --port 8001 --workers 1
```

Les jetons privés créés par `init` sont conservés dans `.env.victim`, ignoré
par Git. Ouvrir ensuite [http://127.0.0.1:8001/docs](http://127.0.0.1:8001/docs).
L’API exige `Authorization: Bearer <VICTIM_GATEWAY_TOKEN>`.

Dans un autre terminal, lancer la pipeline de défense depuis la racine du dépôt :

```bash
python -m victim_agent.launch_alex --port 8000
```

Elle utilise `ALEX_API_URL` et `PASSERELLE_TOKEN` du `.env`, ainsi que
`ANALYSTE_TOKEN` de `.env.victim`. Le tableau de bord local tourne avec
`npm run dev` sur le port 3100.

## Utilisation

```bash
python -m victim_agent.cli health
python -m victim_agent.cli chat Quelle est notre procédure de revue de code ?
```

Le chat de l’interface utilise cette API (`/api/rag/chat`). La pipeline doit
être lancée sur `ALEX_API_URL` et accepter le même `PASSERELLE_TOKEN`. Le
tableau de bord vérifie séparément la base, l’agent RAG et l’API de défense.

`POST /chat` accepte `{"question":"..." }` et renvoie `answer`, `sources`,
`documents_found`, `conversation_id` et `model`.

## Accès nécessaires dans Supabase

Le service utilise une clé serveur privée. Elle a besoin de `SELECT` sur
`documents` et de `SELECT, INSERT` sur `events`. Aucun schéma ni document n’est
créé ou modifié par l’agent.

L’assistant est volontairement en lecture seule : il ne publie pas de packages,
n’appelle pas d’outils externes et ne modifie aucune connaissance. Le
confinement automatique d’un outil n’est donc pas exposé par cette version. Les
approbations de la pipeline ne doivent pas être présentées comme une suspension
effective tant qu’un outil réel et son point de contrôle ne sont pas raccordés.
