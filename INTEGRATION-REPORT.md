# Rapport d’intégration — 11 octobre 2026

## Résultat

Le prototype local est opérationnel sur les parcours testés : RAG sourcé, passerelle avec coffre, contrôle des packages, relais vers la défense d’Alex, décision analyste et suspension effective d’un outil. Les quatre services sont lancés depuis le même checkout `main`.

Publication sur main autorisée par Clément après revue des résultats. Les derniers raccordements et ce rapport sont regroupés dans le commit de publication, avec les merges précédents. Les identifiants et fichiers de runtime sont exclus de Git.

## Branches intégrées précédemment

- `clement/agent-supabase` et `clement/interface-soc`.
- `controle_package` et `passerelle_coffre`.
- Dernière version de `backend-pipeline` d’Alex depuis son fork `amc-boop`, via la PR #1, jusqu’au commit `d0136d1`.

Les références récupérées sont incluses dans main. Les intégrations ont été réalisées localement avant publication ; aucune branche de collègue n’a été réécrite.

## Ce qui a été terminé

### Passerelle, coffre et base

Application de la migration SQL 20 existante : rôles `soc_gateway` et `soc_confineur`, fonction de pseudonymisation par lot et restrictions de révélation du coffre. Le rôle passerelle écrit les traces et crée les jetons ; il ne peut pas récupérer leur valeur réelle. Les secrets de test sont conservés dans Supabase Vault et absents des traces en clair.

La connexion PostgreSQL fonctionne avec le partage mobile utilisé pendant les tests. Le réseau précédent refusait le port 5432.

### Relais vers Alex

`POST /gateway/sessions/{trace_id}/complete` ferme une conversation et transmet ses événements masqués à Alex. La route `/chat` de l’agent avec outils termine et transmet automatiquement la conversation. L’adaptateur conserve les UUID, les liens parents, les dates, les chemins de fichiers sensibles et les noms de sorties reconnus par Alex.

Les résultats de livraison sont persistés dans `.runtime/gateway-state.sqlite`. Une livraison incertaine n’est pas automatiquement rejouée pour éviter des incidents en double. Une conversation terminée ne peut plus recevoir de nouvelles actions ; il faut ouvrir une nouvelle session.

### Confinement effectif

Avec `npm run dev:full`, Alex appelle `POST http://127.0.0.1:8002/confinement` après approbation. La passerelle applique `suspendre_outil` pour le couple agent/outil, vérifie sa persistance, puis confirme l’exécution. Toute nouvelle utilisation de cet outil par cet agent est tracée et bloquée, y compris après redémarrage.

Les autres actions proposées par Alex (`quarantaine_source`, `revoquer_secret`, `lecture_seule`) ne sont pas exécutées par ce connecteur : elles renvoient une erreur explicite. Elles ne doivent pas être présentées comme fonctionnelles au pitch.

### Front et packages

Le front affiche les connexions réelles, les incidents d’Alex et les packages en attente. Un formulaire permet de demander une analyse npm ou PyPI. Le résultat indique une installation simulée lorsque c’est le cas.

La décision package utilise une session Supabase Auth et vérifie `public.analysts.can_approve_packages`. Les clés serveur restent côté serveur. Le jeton utilisateur reste en mémoire dans l’interface, sans stockage local permanent. Les appels d’écriture du front sont limités à l’interface locale.

Compte analyste préparé à la demande de Clément : `ccochod@eugeniaschool.com`. Un compte a été créé, confirmé et autorisé à décider sur les packages. Aucun e-mail envoyé. Les identifiants initiaux sont dans `.env.analyst`, permissions locales 0600, ignoré par Git. Aucun compte n’est créé automatiquement au démarrage.

### RAG simple préservé

Le RAG du front reste un assistant de recherche dans les documents Supabase. Il ne modifie pas les connaissances et n’installe pas de package. Son parcours existant journalise dans Supabase et transmet les traces à Alex. L’agent avec outils de la passerelle est un parcours distinct, disponible sur 8002 : il ne remplace pas le RAG simple.

## Vérifications effectuées

- 128 tests Python passent, dont les nouveaux tests du relais, de l’absence de retransmission après résultat incertain et de la suspension persistante/authentifiée.
- 6 tests frontend passent ; compilation Next.js et vérification TypeScript réussies ; dépendances Python cohérentes.
- Test réel passerelle/coffre contre Supabase : aucun échec, traces liées, pseudonymisation stable, révélation uniquement côté Confineur, accès au coffre refusé à la passerelle, package fictif bloqué, revue et alerte créées, décisions sans authentification refusées.
- RAG depuis le navigateur : réponse réelle, deux sources citées, transmission à Alex confirmée, aucune alerte créée.
- Analyse de package depuis le navigateur : `trace-integration-demo-package-20261011` bloqué en attente de revue.
- Connexion analyste via l’API du front : HTTP 200. Refus de ce package fictif : HTTP 200 et état `rejected` confirmé en base. Cette décision de test n’a pas installé de code.
- Chaîne de test fictive : lecture de `.env.demo` → message dans la boîte simulée → relais à Alex → incident `INC-0002` → approbation technique sur l’agent fictif `integration-demo-01` → suspension `send_message` confirmée → deuxième appel bloqué.
- Après redémarrage des quatre services : incident toujours `Confiné`, suspension toujours effective.
- Agent avec outils en mode normal : HTTP 200, appel réel `search_docs`, réponse reçue, livraison à Alex confirmée, aucun incident.

Le scénario de confinement utilise des événements de test contrôlés et un vrai pipeline d’enquête : il ne prouve pas qu’une attaque provoquera systématiquement un comportement malveillant du modèle. Le modèle peut refuser une instruction piégée.

## Démarrage et utilisation

Depuis la racine du dépôt : `npm run dev:full`.

- Interface : http://127.0.0.1:3100/
- Défense Alex : http://127.0.0.1:8000/docs
- RAG simple : http://127.0.0.1:8001/docs
- Passerelle / agent avec outils : http://127.0.0.1:8002/docs

Les anciennes instances ont été arrêtées puis remplacées par ces services de main. Les incidents d’Alex et ses checkpoints sont désormais dans PostgreSQL, schéma `trace`. Les anciens fichiers SQLite sont conservés, sans migration automatique de leur contenu. Le lancement groupé vérifie les ports et PostgreSQL ; il n’arrête pas d’autres processus pour libérer un port.

## Limites de cette version

- Les installations de packages restent simulées en l’absence de `PACKAGE_AGENT_ENV`. Aucun package n’a été installé pendant les essais.
- Les messages de l’agent de démonstration sont écrits dans `mailbox`, sans envoi vers une vraie boîte externe.
- La clé GitGuardian n’est pas configurée : le masquage local fonctionne, mais le scan distant GitGuardian n’a pas été testé.
- Le semis automatique de leurres est désactivé. Aucun leurre n’a été ajouté aux connaissances pendant cette intégration.
- Le pipeline d’Alex traite les chaînes de lecture sensible vers une sortie ; il n’analyse pas continuellement tous les documents pour garantir une base saine.
- Les alertes packages sont des revues Supabase : elles ne deviennent pas artificiellement des incidents d’exfiltration dans Alex.
- La persistance du relais et des suspensions est locale à cette machine. Une version multi-serveurs devra utiliser un stockage partagé.
- Les KPI de blocage et de benchmark non raccordés restent affichés « — », sans chiffres inventés.
- Des traces, revues, messages simulés et un incident de test sont conservés. Les connaissances saines n’ont pas été remplacées par des données malveillantes. Le recalcul normal des embeddings au démarrage peut renseigner les embeddings des documents existants.

## Contrôle de publication

Clément a autorisé le commit et le push. Vérification des valeurs privées connues dans les fichiers et dans l’historique local à publier : aucune correspondance détectée. Les fichiers `.env`, `.env.victim`, `.env.analyst` et `.runtime/` sont ignorés par Git. Aucun secret ne doit être ajouté au commit.
