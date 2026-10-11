# Guide pas à pas : le backend du pipeline de défense

Pour Alex, sans prérequis en code. Une étape à la fois : fais-la, regarde le résultat, passe à la suivante.

## Ce que contient le dossier `backend/`

| Fichier | À quoi il sert |
|---|---|
| `formats.py` | Les formats échangés avec l'équipe. Ils recopient ceux de l'interface (`frontend/src/lib/demo-data.ts`) : événement (`TraceEvent`), incident (`Incident`), décision de l'analyste. C'est la base de la réunion avec Léon. |
| `pipeline.py` | Le pipeline LangGraph : règle → enquêteur (OpenAI) → vérificateur → dossier → pause jusqu'au clic de l'analyste → application de la décision. |
| `main.py` | Le serveur (FastAPI) que l'interface et l'agent d'Elyott appellent, sur le port 8000. |
| `stockage.py` | Range les incidents dans la base Supabase de l'équipe (ou dans un fichier SQLite si `DATABASE_URL` est vide). Réserve un numéro unique dès la réception et n'accepte qu'une seule décision par incident. |
| `masquage.py` | Remplace chaque secret (clés, jetons, mots de passe dans une URL...) par un jeton stable `SECRET_001`, dans tous les champs, avant l'IA et avant la base. |
| `execution.py` | Envoie l'action approuvée à la passerelle (`CONFINEMENT_URL`). Sans confirmation de la passerelle, l'incident n'est jamais « Confiné ». |
| `tests/` | Les tests automatiques (`python -m pytest -q`), sans clé OpenAI. |
| `exemple_attaque.json`, `exemple_normal.json` | Deux jeux d'événements pour tester : une attaque et une conversation normale. |
| `.env.example` | Modèle du fichier de configuration (clé OpenAI, modèle, passerelle, jetons d'accès). |
| `requirements.txt` | La liste des bibliothèques Python à installer, avec leurs versions exactes (rien ne change sans qu'on le décide). |

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

Résultat attendu : un incident `INC-0001`, deux conclusions marquées `[OK]` avec la raison donnée par le vérificateur, deux preuves (`evt-002`, `evt-004`), une confiance de 1.0, l'action « Suspendre le connecteur github.publish », puis « Statut final : Approuvé, en attente d'exécution » : aucune passerelle n'est branchée, donc rien n'a réellement été bloqué et le backend ne prétend pas le contraire.

Les tests automatiques vérifient les points de la relecture (masquage, numéros uniques, boucles, vérification des preuves, exécution réelle, jetons d'accès) :

```
python -m pytest -q
```

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
3. `POST /incidents/INC-000X/decision` avec `{"decision": "approved", "reason": "clé exposée", "analyst": "alex"}` → statut « Approuvé, en attente d'exécution ».
4. `POST /incidents/INC-000X/execution` avec `{"etat": "execute", "detail": "outil retiré"}` (c'est la passerelle qui l'enverra) → statut « Confiné ».

## Étape 8 : brancher l'interface

L'interface lit `NEXT_PUBLIC_API_BASE_URL` (déjà prévu à `http://localhost:8000`). La personne qui fait l'interface remplace les données de démonstration par `GET /incidents` et le bouton Approuver par `POST /incidents/{id}/decision`. Deux ajouts côté interface :
- le statut « Approuvé, en attente d'exécution » est déjà ajouté à `IncidentStatus` et aux badges ;
- si `ANALYSTE_TOKEN` est défini, chaque appel envoie l'en-tête `Authorization: Bearer <jeton>`.

## Étape 8 bis : brancher la base Supabase

1. Demander à Léon la chaîne de connexion : dans Supabase, bouton « Connect », onglet « Session pooler » (celle-ci marche depuis Codespaces). Elle ressemble à `postgresql://postgres.xxxx:[YOUR-PASSWORD]@aws-0-eu-west-3.pooler.supabase.com:5432/postgres`, avec le mot de passe de la base à la place de `[YOUR-PASSWORD]`.
2. La ranger comme la clé OpenAI : GitHub > Settings > Codespaces > New secret, nom `DATABASE_URL`, accès au dépôt `secure-horizons-soc`. Puis redémarrer le Codespace. Jamais dans le code ni dans un message.
3. Relancer `MOCK_LLM=1 python pipeline.py`. Dans Supabase, Table Editor, choisir le schéma `trace` : la table `incidents` contient le nouvel incident, et les tables `checkpoints*` contiennent les pauses du pipeline.

Le backend crée lui-même ses tables, dans le schéma `trace`. Ce schéma n'est pas exposé par l'API publique de Supabase : le navigateur ne peut pas lire les incidents directement, seul le backend le peut. La table `incidents` garde le dossier complet (`contenu`, en JSON) et quelques colonnes pour les requêtes de Léon : `id`, `agent_id`, `statut`, `cree_le`, `maj_le`.

Pour lancer les tests sur une base PostgreSQL (dans un schéma jetable, jamais `trace`) : `TEST_DATABASE_URL=... python -m pytest -q`.

## Étape 9 : brancher la passerelle d'Elyott

- Elyott envoie ses événements sur `POST /events` (en-tête `Authorization: Bearer <PASSERELLE_TOKEN>` si défini).
- Pour l'exécution, deux possibilités : soit on met dans `.env` `CONFINEMENT_URL` (l'adresse où sa passerelle reçoit `{incident_id, action, cible, agent_id, approuve_par}`), et le backend passe à « Confiné » si elle répond 2xx ; soit sa passerelle confirme elle-même via `POST /incidents/{id}/execution`.

## Ce qui reste simple pour l'instant (à améliorer ensuite)

- Deux règles :
  1. lecture d'une ressource sensible suivie d'une sortie vers l'extérieur ;
  2. installation de package bloquée par la passerelle (réponse `install_package` en attente d'un analyste ou refusée). L'enquêteur cite alors la demande ET le refus (conclusion `package_suspect`) ; une installation retenue par la passerelle compte comme un `blocage`. Un package sain installé automatiquement ne déclenche rien. Tests : `tests/test_pipeline.py` (section 7), sur des sessions réelles exportées de Supabase (`exemple_package_suspect.json`, `exemple_package_sain.json`).
  3. accès à un leurre (`decoy_access`, la passerelle a dérouté la session vers le bac à sable). L'enquêteur cite l'appel d'outil ET l'accès (conclusion `acces_leurre`). Test : `exemple_leurre.json`, session réelle.
- Contre-vérification des packages approuvés (`contre_verification.py`) : chaque fois qu'un analyste autorise un package bloqué, la passerelle demande une deuxième vérification (`POST /packages/contre-verification`). Les agents collectent eux-mêmes des faits (registre PyPI / npm, vulnérabilités OSV, signaux du contrôle), l'enquêteur rend un verdict (sûr / douteux / dangereux) en citant ces faits, le vérificateur refuse « sûr » si un fait critique le contredit. Verdict non positif, ou enquête initiale sûre à ≥ 85 % que le package est suspect (`SEUIL_CONFIRMATION_D_OFFICE`) : seul l'analyste qui a approuvé peut répondre (`POST /contre-verifications/{id}/confirmation`) ; s'il refuse, la passerelle retire le package (désinstallation, inventaire, revue passée à « refusé »). Tests : `tests/test_contre_verification.py`.
- L'action réelle dépend de la passerelle d'Elyott : tant qu'elle n'est pas branchée, les incidents approuvés restent « en attente d'exécution ».
- Les jetons d'accès sont partagés (un pour la passerelle, un pour les analystes). En entreprise : connexion par l'annuaire (SSO), et le nom de l'analyste viendra de cette connexion au lieu du champ `analyst`.
- Les événements sont gardés dans le dossier de l'incident ; une table d'événements séparée pourra venir avec Léon.
- Le vérificateur contrôle le type de chaque conclusion et ses preuves, pas chaque mot de la phrase écrite par l'IA.
