# Déploiement sur Vercel

L'interface Next.js (racine du dépôt) se déploie sur Vercel. Les deux backends Python
(défense, passerelle) ne tournent **pas** sur Vercel (process avec état, serveurs MCP
en mémoire, SQLite local) : ils doivent être hébergés à part (Render, Railway, Fly.io…).

Deux modes de déploiement.

## Mode A — Interface + tableau de bord (rapide)
Le tableau de bord lit **directement Supabase** : il affiche de vraies données (KPIs,
protections apprises, événements) sans les backends Python. Le château, l'arsenal et le
chat restent inertes (ils ont besoin de la passerelle).

Variables d'environnement à définir sur Vercel (Project → Settings → Environment Variables) :

    ALLOW_PUBLIC_ACCESS = 1
    SUPABASE_URL = https://<ref>.supabase.co
    SUPABASE_SERVICE_ROLE_KEY = <clé service role>
    SUPABASE_ANON_KEY = <clé anon>

## Mode B — Démo complète (interface Vercel + backends hébergés ailleurs)
Héberger `scripts/castle/run_backend.sh` (port 8000) et `scripts/castle/run_gateway.sh`
(port 8002) sur un hébergeur de processus, puis ajouter, en plus des variables du mode A :

    DEFENSE_API_URL  = https://<votre-backend-defense>
    GATEWAY_API_URL  = https://<votre-passerelle>
    RAG_API_URL      = https://<votre-rag>            # optionnel
    GATEWAY_TOKEN     = <jeton passerelle>
    ANALYSTE_TOKEN    = <jeton analyste>
    CONFINEMENT_TOKEN = <jeton confinement>
    MISTRAL_API_KEY   = <clé Mistral>                 # pour les backends
    DATABASE_URL      = postgresql://…                # pour les backends

Les backends eux-mêmes ont besoin de DATABASE_URL, MISTRAL_API_KEY et des jetons
(voir .env.example et scripts/castle/init_tokens.py).

## Déployer
Depuis la racine du dépôt :

    npm i -g vercel
    vercel link
    vercel --prod

Vercel détecte Next.js automatiquement. Ne jamais mettre de secret dans le dépôt :
tout passe par les variables d'environnement du projet Vercel.

## Sécurité
- `ALLOW_PUBLIC_ACCESS=1` ouvre les routes de lecture au public (par défaut, tout est
  réservé au serveur local de dev). Les décisions analyste restent protégées par la
  connexion Supabase (table `public.analysts`).
- La clé service role reste côté serveur (jamais envoyée au navigateur).
