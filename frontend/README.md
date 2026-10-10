# TRACE — interface analyste

Console locale de démonstration : incidents, enquête, chaîne de preuves, inventaire et évaluations.

## Démarrer

Node.js 20.9 ou supérieur.

```sh
cd frontend
npm ci
npm run dev
```

Ouvrir http://localhost:3100. Le serveur écoute uniquement sur la machine locale.

```sh
npm run typecheck
npm run build
```

## Ce qui fonctionne

- Recherche et filtres dans la liste des incidents.
- Navigation entre incidents, enquête, agents et évaluations.
- Chaîne interactive et traces structurées avec `parent_event_id`.
- Approbation/refus du confinement avec commentaire et historique de session.
- Export JSON des preuves et décisions.
- Rejeu local qui réinitialise les décisions fictives.

Tout est simulé. Aucune donnée réelle, connexion Supabase, appel IA, permission GitHub ou action de confinement réelle. Les décisions sont en mémoire et disparaissent au rechargement. Les évaluations sont des exemples de résultats attendus, pas des mesures du backend.

## Raccordement équipe

Léon : les types de `src/lib/demo-data.ts` définissent les objets attendus par les écrans. Conserver les identifiants d'événements stables et les liens parent-enfant. Le fichier est une fixture frontend, pas une migration SQL.

Alex : remplacer les fixtures par les réponses du backend. L'approbation doit appeler une route authentifiée qui vérifie le rôle de l'analyste et le statut de l'action, enregistre la décision et exécute l'action de façon idempotente. Le frontend n'est jamais l'autorité de sécurité.

Elyott : produire les événements normalisés, avec les ressources, outils, résultats et relations parent-enfant. Les traces affichées doivent être celles observées par la passerelle, pas une histoire inventée par un LLM.

Ne jamais fournir de clé d'administration, de secret d'agent ou de token de connecteur au navigateur. Les secrets du scénario restent des marqueurs fictifs.

## Direction visuelle

Nom de travail TRACE. Graphite, menthe, ambre et rouge doux ; interface française ; identifiants en monospace ; priorité aux preuves et à la décision humaine. Les polices Google Fonts ont un repli système et ne bloquent pas le build.
