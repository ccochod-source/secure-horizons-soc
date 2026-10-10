# Guide pas à pas : le backend du pipeline de défense

Pour Alex, sans prérequis en code. Une étape à la fois : fais-la, regarde le résultat, passe à la suivante.

## Ce que contient le dossier `backend/`

| Fichier | À quoi il sert |
|---|---|
| `formats.py` | Les formats échangés avec l'équipe. Ils recopient ceux de l'interface (`frontend/src/lib/demo-data.ts`) : événement (`TraceEvent`), incident (`Incident`), décision de l'analyste. C'est la base de la réunion avec Léon. |
| `pipeline.py` | Le pipeline LangGraph : règle → enquêteur (OpenAI) → vérificateur → dossier → pause jusqu'au clic de l'analyste → application de la décision. |
| `main.py` | Le serveur (FastAPI) que l'interface et l'agent d'Elyott appellent, sur le port 8000. |
| `stockage.py` | Range les incidents dans un fichier SQLite. |
| `exemple_attaque.json`, `exemple_normal.json` | Deux jeux d'événements pour tester : une attaque et une conversation normale. |
| `.env.example` | Modèle du fichier de configuration (clé OpenAI, modèle). |
| `requirements.txt` | La liste des bibliothèques Python à installer. |

## Étape 1 : mettre le code dans le dépôt

Le dossier `backend/` doit arriver dans le dépôt `secure-horizons-soc`, à côté de `frontend/`.

## Étape 2 : ranger la clé OpenAI dans GitHub (jamais dans le code)

Sur la page du dépôt : **Settings → Secrets and variables → Codespaces → New repository secret**.
Nom : `OPENAI_API_KEY`. Valeur : la clé OpenAI de l'équipe.

## Étape 3 : ouvrir un Codespace

Sur la page du dépôt : bouton vert **Code → onglet Codespaces → Create codespace on main**.
Un éditeur s'ouvre dans le navigateur, avec un terminal en bas.

## Étape 4 : installer

Dans le terminal, taper une ligne à la fois puis Entrée :

```
cd backend
pip install -r requirements.txt
cp .env.example .env
```

## Étape 5 : premier test sans IA

```
MOCK_LLM=1 python pipeline.py
```

Résultat attendu : un incident `INC-0001`, deux preuves (`evt-002`, `evt-004`), une confiance de 1.0, l'action « Suspendre le connecteur github.publish », puis « Statut final : Confiné ».

## Étape 6 : test avec la vraie IA

```
python pipeline.py
```

Même chose, mais l'explication est écrite par OpenAI. Si une erreur parle du modèle, changer `OPENAI_MODEL` dans `.env` (par exemple `gpt-4.1-mini`).

## Étape 7 : lancer le serveur

```
uvicorn main:app --reload --port 8000
```

Codespaces propose d'ouvrir le port 8000 : ouvrir le lien et ajouter `/docs` à l'adresse. Cette page permet d'essayer chaque route :
1. `POST /events` : coller le contenu de `exemple_attaque.json` → un incident revient, statut « À examiner ».
2. `GET /incidents` : la liste des incidents.
3. `POST /incidents/INC-000X/decision` avec `{"decision": "approved", "reason": "clé exposée", "analyst": "alex"}` → statut « Confiné ».

## Étape 8 : brancher l'interface

L'interface lit `NEXT_PUBLIC_API_BASE_URL` (déjà prévu à `http://localhost:8000`). La personne qui fait l'interface remplace les données de démonstration par `GET /incidents` et le bouton Approuver par `POST /incidents/{id}/decision`.

## Ce qui reste simple pour l'instant (à améliorer ensuite)

- Une seule règle : lecture d'une ressource sensible suivie d'une sortie vers l'extérieur.
- L'action approuvée est simulée (un message dans le terminal). Le vrai blocage viendra du proxy MCP.
- Les routes ne demandent pas encore d'authentification.
