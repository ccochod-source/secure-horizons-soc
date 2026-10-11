#!/usr/bin/env bash
# Lance le backend de défense RÉEL en local : enquêteur OpenAI (clé obligatoire), incidents et admission des
# connaissances sur Supabase (DATABASE_URL PostgreSQL, comme `npm run dev:all`).
# Les jetons PASSERELLE_TOKEN / ANALYSTE_TOKEN viennent de .env.victim ; OPENAI_API_KEY (et OPENAI_MODEL) de .env.
# Pour la stack complète (Supabase, RAG, passerelle), utiliser `npm run dev:all` à la place.
set -euo pipefail
cd "$(dirname "$0")/../.."
# Lecture clé=valeur des fichiers d'environnement, sans les interpréter comme du shell (valeurs avec espaces ou guillemets).
load_env() {
  [ -f "$1" ] || return 0
  while IFS= read -r line || [ -n "$line" ]; do
    case "$line" in ''|'#'*) continue ;; esac
    key="${line%%=*}"; val="${line#*=}"
    key="${key## }"; key="${key%% }"
    case "$key" in *[!A-Za-z0-9_]*|'') continue ;; esac
    val="${val#"${val%%[! ]*}"}"; val="${val%"${val##*[! ]}"}"
    case "$val" in \"*\") val="${val#\"}"; val="${val%\"}" ;; \'*\') val="${val#\'}"; val="${val%\'}" ;; esac
    [ -n "$val" ] && export "$key=$val"
  done < "$1"
}
load_env .env.victim
load_env .env
# Même convention que scripts/dev.py : la clé et le modèle « enquêteur » priment pour le backend de défense.
export OPENAI_API_KEY="${OPENAI_API_KEY_ENQUETEUR:-${OPENAI_API_KEY:-}}"
export OPENAI_MODEL="${OPENAI_MODEL_ENQUETEUR:-${OPENAI_MODEL:-}}"
: "${PASSERELLE_TOKEN:?PASSERELLE_TOKEN manquant : python3 scripts/castle/init_tokens.py}"
: "${ANALYSTE_TOKEN:?ANALYSTE_TOKEN manquant : python3 scripts/castle/init_tokens.py}"
if [ -z "${OPENAI_API_KEY:-}" ]; then
  echo "OPENAI_API_KEY manquante dans .env : le backend réel ne peut pas démarrer (l'enquêteur est un appel OpenAI)." >&2
  echo "Remplir .env puis relancer. (Mode scripté sans IA, pour tests unitaires seulement : MOCK_LLM=1 $0)" >&2
  exit 1
fi
mkdir -p .runtime
case "${DATABASE_URL:-}" in postgres://*|postgresql://*) ;; *) echo "DATABASE_URL PostgreSQL requis dans .env (admission des connaissances)." >&2; exit 1 ;; esac
export MOCK_LLM="${MOCK_LLM:-0}" CHECKPOINT_PATH="$PWD/.runtime/alex-8000-checkpoints.sqlite"
# Le confinement approuvé est exécuté pour de vrai par la passerelle (8002), qui suspend l’outil.
export FRONTEND_ORIGIN=http://localhost:3100 CONFINEMENT_URL="${CONFINEMENT_URL:-http://127.0.0.1:8002/confinement}"
[ "$MOCK_LLM" = "1" ] && echo "ATTENTION : MOCK_LLM=1, enquêteur scripté (pas un vrai test)." >&2
cd backend
exec ../.venv/bin/python -m uvicorn main:app --host 127.0.0.1 --port "${PORT:-8000}"
