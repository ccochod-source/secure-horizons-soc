# Backend — passerelle, coffre, leurres, contrôle des packages et environnement attaqué

Cinq briques de l'architecture, en Python + FastAPI. Elles écrivent dans le
schéma `public` du projet Supabase et lisent l'annuaire `public.employees`.

## Démarrer

Python 3.11 ou supérieur, depuis `backend/` :

```sh
python -m venv .venv && .venv/bin/pip install -r requirements.txt
.venv/bin/python -m pytest tests        # hors ligne, aucune base requise
.venv/bin/uvicorn app.main:app --reload # exige DATABASE_URL dans ../.env
```

Prérequis en base : la migration `supabase/migrations/…_20_passerelle_coffre_roles.sql`
doit être appliquée (rôles `soc_gateway` et `soc_confineur`).

## Passerelle (`gateway/`)

Point de passage obligatoire entre l'agent victime et ses outils. Chaque
élément devient une ligne de `public.events`, reliée à sa cause par
`parent_event_id`, avec un contenu toujours pseudonymisé.

```python
session = gateway.open_session("DevBot", user_id="…")
await gateway.record_query(session, question)                 # user_request
await gateway.record_document(session, source="email", resource_id=…, content=…)
result = await gateway.dispatch(session, "send_message", {…}) # tool_call + tool_response
await gateway.record_response(session, answer)                # agent_response
```

- `gateway.register(upstream)` trace le serveur MCP et le texte de chaque
  description d'outil ; chaque appel y renvoie par `metadata.tool_description_event_id`.
- L'agent reçoit la vraie réponse de l'outil ; seule la trace est pseudonymisée.
  `metadata.tokens` liste les jetons présents dans l'événement.
- Si la trace ne peut pas être écrite, l'appel est refusé (`TraceUnavailable`).
- Les mêmes opérations existent en HTTP : `POST /gateway/sessions`,
  `…/documents`, `…/tools/{outil}`, `…/response`, `GET /gateway/tools`,
  `GET /incidents/{trace_id}/graph` (nœuds et arêtes pour React Flow).

### Brancher les deux blocs de protection

`Gateway(events, pseudonymizer, decoys=…, packages=…)` attend les interfaces de
`gateway/hooks.py` (méthodes synchrones ou asynchrones) :

- **Leurres** — `trips(session, tool, payload, direction)` est appelé sur les
  paramètres (`"call"`) puis sur le résultat (`"result"`). S'il rend vrai, la
  session est déroutée pour de bon et reçoit `tarpit_response(…)`.
- **Packages** — `review(session, event_id, ecosystem, name, version)` reçoit
  tout appel à `install_package`, jamais relayé à l'outil. Le `status` rendu
  vaut `installed`, `blocked_pending_review` ou `blocked`.

Les deux blocs sont branchés au démarrage (voir plus bas). La passerelle
soumet aussi au détecteur les documents reçus par `record_document` et la
réponse finale de l'agent ; les routes HTTP correspondantes rendent `diverted`.

## Coffre (`vault/`)

- `Pseudonymizer.pseudonymize(obj)` remplace secrets et données personnelles
  par des jetons typés et stables (`SECRET_AWS_101`, `EMAIL_102`, `PERSONNE_103`).
  Règles locales toujours actives (formats connus, affectations, entropie,
  e-mails, téléphones, IBAN, noms de l'annuaire) ; GitGuardian en complément si
  `GITGUARDIAN_API_KEY` est défini.
- La valeur réelle part dans Supabase Vault via `public.pseudonymize_values` ; le
  backend n'en garde aucune copie.
- `vault.reveal.reveal(db, token)` est réservé au Confineur (rôle
  `soc_confineur`) ; chaque appel est journalisé dans `public.token_vault_log`.
- `vault.audit.PromptAudit.check(prompt, agent=…)` est à appeler sur chaque
  prompt envoyé à un LLM défenseur : il alimente la métrique « secrets en clair
  vus par les LLM » (objectif 0).

## Environnement attaqué (`env_attacked/`)

L'agent victime `DevBot` et ses serveurs MCP, lancés dans le même processus que
la passerelle. L'agent n'appelle jamais un serveur directement : tout passe par
`gateway.dispatch`, `record_query`, `record_document` et `record_response`.

- Serveurs enregistrés au démarrage : `mcp_docs` (`search_docs`), `mcp_fichiers`
  (`list_files`, `read_file`), `mcp_messagerie` (`send_message`), `mcp_packages`
  (`install_package`) et `mcp_deploy_helper`, le serveur tiers dont la
  description d'outil est piégée.
- `POST /chat` : `{"question": "…", "poisoned": false}`. Avec `poisoned: true`,
  le modèle voit aussi l'outil du serveur piégé (scénario 1).
- Modèle OpenAI en température 0, graine fixe, prompt figé (`SYSTEM_PROMPT`).
  Sans `OPENAI_API_KEY`, `/chat` répond 503 et la recherche se fait par mots.
- Au démarrage, les documents sans embedding sont calculés, documents pièges
  compris (`text-embedding-3-small`, 1536 dimensions).

## Scripts (`scripts/`)

```sh
.venv/bin/python -m scripts.smoke_db             # vraies écritures en base, vérifiées puis nettoyées
.venv/bin/python -m scripts.demo plant           # document piégé du scénario package
.venv/bin/python -m scripts.demo scenario1       # lance le scénario 1 et vérifie sa trace
.venv/bin/python -m scripts.demo package         # idem pour le scénario package
.venv/bin/python -m scripts.demo export <trace_id>   # vers demo/trace_scenario1.json
.venv/bin/python -m scripts.demo replay          # plan B : réinjecte la trace enregistrée
```

## Couche de leurres (`decoys/`)

Premier bloc de protection. Un leurre n'a aucune raison d'être lu par un usage
légitime : dès qu'il apparaît, la session est déroutée et ne touche plus rien
de réel.

- **Semeur** (`seed.py`) — au démarrage, plante ce qui manque parmi six leurres
  (`LURES`) et les inscrit dans `public.decoys` :

  | Leurre | Type | Emplacement |
  |---|---|---|
  | HONEYTOKEN_001 | honeytoken_key | document « Accès d'urgence » (clé AWS) |
  | HONEYTOKEN_002 | honeytoken_key | fichier `infra-tools/backup.key` |
  | HONEYTOKEN_003 | fake_credential | document « Comptes de service » |
  | HONEYTOKEN_004 | honeytoken_key | fichier `monorepo-app/config/.env.backup` |
  | HONEYTOKEN_005 | poisoned_document | document « Mots de passe infra » |
  | HONEYTOKEN_006 | poisoned_mcp_config | fichier `monorepo-app/config/mcp.servers.backup.json` |

  Les valeurs sont fabriquées à l'exécution, au format des vrais secrets ; avec
  `GITGUARDIAN_API_KEY`, la clé AWS du premier est un honeytoken GitGuardian.
  Un leurre déjà planté n'est jamais régénéré, un vrai fichier jamais écrasé.
  `DECOYS_SEED_ON_START=false` désactive le semis.
- **Détecteur** (`detector.py`) — relit les contenus `is_decoy` et en extrait
  les valeurs à surveiller ; rien d'autre n'est stocké. Il déclenche sur :
  la valeur d'un honeytoken (brute, en base64 ou encodée pour une URL) ou le nom
  d'un leurre, dans un appel comme dans un résultat ; la demande directe d'un
  fichier ou d'un document leurre (chemin ou identifiant en paramètre). Un
  chemin de leurre dans une simple liste de fichiers ne déclenche rien.
  Au déclenchement : alerte `critical` (`source = 'detecteur_piege'`,
  `signal = 'decoy_access'`), compteur de `public.decoys`, événements
  `decoy_access` puis `session_diverted`. Ni la trace ni l'alerte ne citent la
  valeur, seulement le nom du leurre et son jeton.
- **Jetons du coffre** — le détecteur transmet les valeurs des leurres au
  coffre : elles reçoivent un jeton `LEURRE_<TYPE>_<n>` (le même pour la forme
  brute et la forme encodée), jamais `SECRET_…`. `vault.is_decoy_token(jeton)`
  permet au Confineur de ne pas révoquer un leurre et d'exclure celui-ci du
  rayon d'impact réel. Le type se lit dans `token_vault.token_prefix`.
- **Bac à sable** (`tarpit.py`) — une session déroutée reçoit des réponses
  factices, volumineuses et répétitives (`TARPIT_PAYLOAD_CHARS`, 120 000
  caractères par défaut), sans aucun accès réel. Garde-fou : il refuse toute
  session non déroutée (`NotDiverted`).

**Limites à connaître**

- Aucun leurre dans la boîte mail : résumer la boîte est un usage légitime, il
  déclencherait à tort.
- Les documents pièges sont plantés sans embedding, comme les 30 documents
  actuels : ils entreront dans l'index vectoriel quand il sera calculé.
- Une session déroutée l'est en mémoire : un redémarrage du backend l'oublie.
- Les écritures de ce bloc passent par le compte de `DATABASE_URL`, sans rôle dédié.

## Contrôle des packages (`packages/`)

Tout appel à `install_package` arrive dans `PackageReviewer.review`. Un package
sain est installé ; un package suspect reste en quarantaine jusqu'à la décision
d'un analyste. Le système ne l'approuve ni ne le rejette seul.

1. **Interception** — faite par la passerelle ; une demande mal formée (écosystème
   inconnu, nom ou version invalides) est refusée avant tout appel réseau.
2. **Existence** (`existence.py`) — liste interne `public.package_versions`
   d'abord (une version approuvée passe sans autre contrôle), sinon PyPI ou npm.
   Nom introuvable, version inexistante ou registre injoignable : bloquant.
   Typosquatting par distance d'édition sur `popular.py`.
3. **Analyse statique** (`static.py`) — l'archive est téléchargée dans
   `backend/.quarantine/` (empreinte vérifiée), lue sans être extraite ni
   exécutée. Sur PyPI on analyse la wheel quand elle existe, comme le ferait pip.
   GuardDog s'ajoute s'il est installé (`checks.steps.guarddog`).
4. **Réputation** (`reputation.py`) — OSV, dépôt source, nombre de versions.
5. **Score** (`score.py`) — somme des poids de la table `RULES`, seuil 0,3.

Écritures, selon le schéma en place :

- `package_reviews` : `state` vaut `proposed`, `pending_approval`, `approved`,
  `rejected`, `executed` ou `failed` ; signaux et score dans `checks`, extraits
  de code et archive dans `evidence` (pseudonymisés). Une approbation
  automatique porte `decided_by = 'automatique'`.
- `alerts` : `source = 'sentinelle'`, `signal = 'suspicious_package_install'`,
  résumé préfixé « [contrôle des packages] ».
- `events` : `package_review` (analyse, puis décision de l'analyste) et
  `dependency_installed`, enfants de l'événement `package_install_requested`.
- `quarantine_artifacts`, `inventory` (`kind = 'dependency'`) et `inventory_access`.

**Décision** — `POST /packages/{review_id}/decision`, en-tête
`Authorization: Bearer <jeton de session Supabase>` :

```json
{"decision": "approve" | "reject" | "replace", "note": "…", "replacement": {"name": "requests", "version": null}}
```

Le jeton est validé par Supabase Auth (`SUPABASE_URL` et une clé d'API) et le
compte doit figurer dans `public.analysts` avec `can_approve_packages`. Réponses :
401, 403, 404, 409 si la décision est déjà prise, 422 si le remplacement
n'existe pas. Le banc de test appelle directement `PackageReviewer.decide`.

**Limites à connaître**

- Sans `PACKAGE_AGENT_ENV`, l'installation est seulement enregistrée
  (`execution_result.simulated = true`) : rien n'est installé pour de bon.
- Les écritures de ce bloc passent par le compte de `DATABASE_URL` : il n'a pas
  encore de rôle Postgres dédié.
- Remplacer n'a pas d'état propre : la revue d'origine passe à `rejected` avec
  la note « Remplacé par … », et une seconde revue est créée pour le remplaçant.
