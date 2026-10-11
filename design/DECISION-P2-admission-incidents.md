# Décision P2 — Relier (ou non) l'admission des connaissances au pipeline d'incidents d'Alex

> Document d'aide à la décision. **Aucun code n'est modifié par ce document.** Il décrit le choix à trancher, les deux options, le format d'événement proposé et son impact. L'objectif de la passation est d'« aligner précisément le traitement des nouvelles connaissances avec la pipeline comportementale d'Alex, sans confondre revue préventive de données et réponse à incident ».
>
> Rédigé après lecture du code réel : `backend/main.py`, `backend/pipeline.py`, `backend/formats.py`, `backend/knowledge.py`, `backend/masquage.py`, `victim_agent/relay.py`.

---

## 1. La question

Aujourd'hui, deux circuits sont **totalement découplés** :

- **Admission des connaissances** (`backend/knowledge.py`) : un ajout/une modification dans `public.documents` / `public.repo_files` est mis en `pending` par trigger, puis le worker décide `approved` ou `quarantined`. Un analyste peut ensuite `approve`/`reject`. Chaque décision est inscrite dans `trace.knowledge_review_log`. **`knowledge.py` n'appelle jamais `/events` ni le pipeline** (vérifié : aucun import `httpx`, `pipeline`, `ALEX_API_URL`).
- **Pipeline d'incidents** (`backend/pipeline.py`) : reçoit des lots d'événements via `POST /events` et crée un incident **uniquement** si une règle comportementale se déclenche.

Faut-il garder cette séparation, ou faire remonter les quarantaines/rejets de connaissances vers le pipeline d'Alex ?

---

## 2. Faits techniques qui cadrent la décision

Ces points sont établis par lecture du code et déterminent ce qui est faisable proprement.

### 2.1 Un incident n'est créé que si une règle se déclenche
`POST /events` (`backend/main.py`) réserve un numéro d'incident, invoque le pipeline, puis :
- **si aucune interruption** (la règle ne s'est pas déclenchée) → le numéro réservé est **libéré** (`stockage.liberer`) et la réponse est `{"incident": None, "message": "Aucun comportement suspect détecté."}`.
- **si interruption** → un incident est présenté à l'analyste.

**Un lot bénin ne crée donc aucun incident, par construction.** Recevoir des événements ≠ créer un incident.

### 2.2 La règle unique (`regle` dans `pipeline.py`)
Un incident naît seulement si, **dans le même lot** :
1. un événement est **sensible** — son `resource` contient un mot de `MOTS_SENSIBLES` (`.env`, `secret`, `credential`, `password`, `mot de passe`, `token`, `api_key`, `clé`) ; **et**
2. un événement est **sortant** — son `tool` ∈ `OUTILS_SORTANTS` (`github.publish`, `http.post`, `send_message`, `email.send`, `slack.post`, `webhook.send`) **ou** son `resource` commence par `external/` ; **et**
3. l'événement sensible est un **ancêtre** (via `parent_event_id`) de l'événement sortant.

Conséquence pratique : il suffit de **ne pas** fabriquer cette chaîne (lecture sensible → sortie externe liée) pour qu'un événement d'admission **ne déclenche jamais** d'incident à tort.

### 2.3 Le contrat d'événement (`backend/formats.py`)
`POST /events` attend un `LotEvenements` : `{ "agent_id": str, "events": [TraceEvent, ...] }`.
Un `TraceEvent` : `id` (requis), `parent_event_id` (optionnel, lien causal), `timestamp` (ISO-8601 accepté), `actor`, `type`, `title`, `description`, `tool`, `resource` (tous requis), `result` ∈ `allowed | blocked | flagged` (requis).

### 2.4 Masquage avant tout
`recevoir_evenements` masque chaque champ texte (`preparer_evenements` → `masquer_evenement`) **avant** le pipeline. Le pipeline, le LLM, la mémoire LangGraph et le stockage ne voient que du texte masqué. Côté `relay.py`, les champs sensibles sont déjà masqués à l'émission (défense en profondeur).

### 2.5 Authentification
`POST /events` exige `Authorization: Bearer <PASSERELLE_TOKEN>`. Le `victim_agent/relay.py` est l'émetteur de référence : il poste `{agent_id, events}` avec ce bearer, en un seul appel non rejoué.

### 2.6 Pas d'idempotence intégrée côté événements
Chaque `POST /events` réserve un **nouveau** numéro d'incident et un nouveau thread. **Rien n'est dédupliqué sur l'`id` d'événement.** Reposter le même lot créerait deux incidents (ou deux no-op). Si l'on veut une émission idempotente, il faut la construire côté `knowledge.py`. Les clés stables disponibles y sont déjà : `(table, id, xmin)` pour le worker, `(table, id)` pour la décision analyste.

---

## 3. Les deux options

### Option A — Garder les circuits séparés *(état actuel)*

L'admission reste une **barrière préventive à l'entrée** ; le pipeline reste la **réponse à un comportement observé**. La trace d'admission vit dans `trace.knowledge_review_log` et la queue humaine de l'interface.

**Avantages**
- Séparation conceptuelle nette (préventif ≠ réactif), exactement ce que la passation demande de ne pas confondre.
- Aucun risque de polluer la liste d'incidents avec des entrées de données.
- Zéro nouveau code, zéro nouvelle dépendance dans `knowledge.py`, zéro surface d'erreur.
- Narratif de pitch simple : « à gauche le filtre d'entrée des connaissances, à droite la détection d'actions ».

**Inconvénients**
- Une quarantaine n'apparaît **pas** dans la vue unifiée des incidents ; un analyste qui ne regarde que les incidents peut la manquer.
- Pas de corrélation automatique entre « document piégé introduit » et « action suspecte observée » plus tard.

### Option B — Émettre un **événement d'admission** vers le pipeline

Quand le worker met en `quarantined` (ou qu'un analyste `reject`), `knowledge.py` émet **un** `TraceEvent` d'admission vers `/events`, **conçu pour ne jamais déclencher la règle tout seul** (voir §4). Objectif : rendre l'événement **visible/corrélable** dans le circuit de défense, pas en faire un incident automatique.

**Avantages**
- La défense « voit » les tentatives d'empoisonnement de la base, au même endroit que les actions.
- Base pour une future corrélation (ex. document piégé + exfiltration ultérieure du même acteur).

**Inconvénients**
- Nouveau couplage : `knowledge.py` doit connaître l'URL backend + `PASSERELLE_TOKEN` et ajouter `httpx`.
- Risque de confusion « donnée ≠ incident » si mal cadré. **Il ne faut pas** transformer chaque écriture en incident.
- Le pipeline actuel ne « range » pas les événements qui ne déclenchent pas la règle : un événement d'admission bénin **no-op** (numéro libéré) — donc sans travail supplémentaire côté pipeline, l'événement n'est **pas conservé**. Rendre l'admission réellement *visible* demanderait soit une nouvelle règle/branche, soit un stockage d'événements d'admission dédié → **plus que du branchement, un vrai lot de travail.**

---

## 4. Si tu choisis B — spécification de l'événement d'admission

### 4.1 Forme (réutilise le contrat existant, aucun changement de schéma d'événement)

```jsonc
// POST /events   Authorization: Bearer <PASSERELLE_TOKEN>
{
  "agent_id": "soc-knowledge-reviewer",
  "events": [
    {
      "id": "admission:documents:<uuid>:<xmin>",   // clé stable = idempotence (voir 4.3)
      "parent_event_id": null,                       // JAMAIS enfant d'un événement sensible
      "timestamp": "2026-10-11T12:00:00Z",
      "actor": "soc-knowledge-reviewer",             // ou l'analyste pour un reject
      "type": "knowledge_admission",
      "title": "Connaissance mise en quarantaine",
      "description": "<reason, déjà ≤500 car. et masquée>",
      "tool": "knowledge.review",                    // PAS dans OUTILS_SORTANTS
      "resource": "admission/documents/<uuid>",      // PAS de mot sensible, PAS de préfixe external/
      "result": "blocked"                            // quarantined/rejected => blocked
    }
  ]
}
```

### 4.2 Pourquoi il ne déclenche jamais la règle tout seul
- Un **seul** événement, `parent_event_id = null` → impossible d'avoir « lecture sensible ancêtre d'une sortie ».
- `tool = "knowledge.review"` n'est pas dans `OUTILS_SORTANTS`.
- `resource = "admission/..."` ne contient aucun mot de `MOTS_SENSIBLES` et ne commence pas par `external/`.
→ `regle` renvoie `alerte: None` → pipeline s'arrête → `{"incident": None}` → numéro libéré. **Aucun incident créé.** C'est voulu.

### 4.3 Idempotence (à construire, le pipeline n'en fournit pas)
- `id` déterministe : `admission:{table}:{item_id}:{xmin}`. Même décision ré-émise = même `id`.
- Émission **au plus une fois par transition** : poster seulement quand `_record`/`decide` renvoie `True` (c.-à-d. la transition a réellement eu lieu, grâce au garde xmin existant). Si l'écriture DB échoue, pas d'émission.
- L'émission **ne doit pas** bloquer ni faire échouer l'admission : si `/events` est injoignable, journaliser et continuer (l'admission reste la source de vérité ; `trace.knowledge_review_log` garde la trace).
- Ne jamais rejouer automatiquement une émission au résultat incertain (même principe que le relais RAG → Alex déjà en place).

### 4.4 Confidentialité
- N'envoyer que `reason` (déjà ≤500 car.) comme `description`, **jamais** le contenu brut du document. `reason` passe quand même par le masquage côté backend (défense en profondeur).
- `resource` ne contient que `table` + `uuid`, pas de titre ni d'extrait.

### 4.5 Portée minimale vs portée « visible »
- **Minimale (branchement seul)** : émettre l'événement idempotent. Effet réel : trace d'audit côté réception, mais **no-op pipeline** → non conservé tel quel. Faible valeur sans l'étape suivante.
- **Visible (recommandée si B)** : ajouter côté pipeline/stockage un enregistrement des événements d'admission (p. ex. un type d'entrée distinct des incidents) ou une règle dédiée « document piégé = alerte de niveau information ». → travail non trivial, à spécifier séparément.

---

## 5. Recommandation

**Court terme (pitch) : Option A.** C'est l'état actuel, il est cohérent avec le message « ne pas confondre revue préventive et réponse à incident », il n'ajoute aucun risque, et le durcissement de la PR #2 l'a déjà rendu solide. Le pitch montre les deux circuits côte à côte, chacun avec sa preuve visible.

**Moyen terme (si tu veux la corrélation) : Option B « visible »**, mais seulement après avoir décidé **où** vivent les événements d'admission (nouvelle règle d'information vs stockage dédié). Le simple branchement « minimal » apporte peu tant que le pipeline no-op les événements qui ne déclenchent pas la règle.

---

## 6. Ce dont j'ai besoin de toi

Choisis une direction :

- **A** — on garde séparé. Je documente juste proprement la frontière (court) et on passe à la fiabilité (Phase 3) et au script de démo (Phase 4).
- **B minimal** — j'implémente l'émission idempotente décrite au §4, en acceptant qu'elle n'apporte de la valeur que couplée à l'étape « visible ».
- **B visible** — même émission + conception du stockage/règle d'information côté pipeline. Je te proposerais d'abord une mini-spéc technique de cette partie avant de coder.

Dis-moi A, B minimal ou B visible, et j'enchaîne.
