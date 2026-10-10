# Backend — passerelle de traçage et coffre de pseudonymisation

Deux briques de l'architecture, en Python + FastAPI. Elles écrivent dans le
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

Tant qu'ils ne sont pas branchés : aucun leurre ne déclenche, et toute
installation est refusée.

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
