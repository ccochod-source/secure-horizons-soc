# TRACE — Interface de travail

Tableau de bord provisoire du hackathon Secure Horizons : une page blanche et simple avec les indicateurs, connexions, agents, packages à valider, incidents, activité et résultats des tests.

## Démarrer

Node.js 20.9 ou supérieur, depuis la racine du dépôt :

```sh
npm ci
npm run dev
```

Ouvrir http://localhost:3100. Le serveur de développement écoute sur 127.0.0.1.

## État réel

La connexion Supabase est conservée. `/api/soc` vérifie un accès en lecture à `inventory` (une ligne, uniquement son identifiant). La clé privée reste côté serveur, avec les noms `SUPABASE_URL` / `SUPABASE_SERVICE_ROLE_KEY` ou les noms existants `DATABASE_URL` / `service_role_key`.

**Les agents et le workflow ne sont pas encore raccordés.** L’API renvoie donc des listes vides et des mesures nulles. Les noms présents dans l’inventaire, les incidents et les benchmarks préparés en base ne sont pas présentés comme une activité réelle. La base n’est ni effacée ni modifiée. Aucun mode de simulation, faux rejeu ou fausse validation ne figure dans l’interface.

- Agents branchés : 0.
- Validations, incidents, blocages et tests : non mesurés tant que le workflow n’est pas intégré.
- Rafraîchissement automatique toutes les 15 secondes, ou bouton Actualiser.
- Erreur de connexion explicite ; aucun remplacement par des données fictives.
- Validation humaine et actions : non raccordées, aucune écriture depuis cette interface.

Au raccordement des vrais agents, adapter le lecteur serveur au contrat `SocOverview` dans `src/lib/soc-overview.ts`, après vérification des endpoints, des événements réellement produits et de leur provenance. Ne pas activer la pipeline parce qu’un agent est simplement inventorié ou qu’une branche existe sur GitHub. Le mapper historique `soc-data.ts` reste disponible pour l’intégration ultérieure des tables d’incidents.

## Accès

Passerelle réservée au serveur local de développement : les accès en production, les origines externes et les requêtes non locales sont refusés. Un déploiement partagé nécessitera une authentification et des autorisations analystes. Les décisions doivent être authentifiées et exécutées par le backend ; un statut approuvé ne prouve pas une exécution.

## Vérification

```sh
npm run typecheck
# Tests : Node.js 22.6+
node --experimental-strip-types --test tests/*.test.ts
```

La planche dans `design/` est une ancienne recherche visuelle et ne représente plus l’interface actuelle.
