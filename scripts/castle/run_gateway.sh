#!/usr/bin/env bash
# Lance la VRAIE passerelle (port 8002) : traçage, coffre, couche de leurres (détecteur + bac à sable),
# contrôle des packages et l'agent victime DevBot (OpenAI). Exige DATABASE_URL PostgreSQL Supabase dans .env
# et un réseau qui laisse passer les ports 5432/6543.
set -euo pipefail
cd "$(dirname "$0")/../.."
load_env() {
  [ -f "$1" ] || return 0
  while IFS= read -r line || [ -n "$line" ]; do
    case "$line" in ''|'#'*) continue ;; esac
    key="${line%%=*}"; val="${line#*=}"
    case "$key" in *[!A-Za-z0-9_]*|'') continue ;; esac
    val="${val#"${val%%[! ]*}"}"; val="${val%"${val##*[! ]}"}"
    case "$val" in \"*\") val="${val#\"}"; val="${val%\"}" ;; \'*\') val="${val#\'}"; val="${val%\'}" ;; esac
    [ -n "$val" ] && export "$key=$val"
  done < "$1"
}
load_env .env.victim
load_env .env
case "${DATABASE_URL:-}" in postgres://*|postgresql://*) ;; *) echo "DATABASE_URL PostgreSQL requis dans .env" >&2; exit 1 ;; esac
: "${OPENAI_API_KEY:?OPENAI_API_KEY requis dans .env (agent DevBot)}"
export GATEWAY_TOKEN="${GATEWAY_TOKEN:-${VICTIM_GATEWAY_TOKEN:-}}"
# Modèle de DevBot : OPENAI_MODEL_DEVBOT s’il est défini (sans toucher aux autres services), sinon gpt-4o-mini.
[ -n "${OPENAI_MODEL_DEVBOT:-}" ] && export OPENAI_MODEL="$OPENAI_MODEL_DEVBOT"
export ALEX_API_URL="${ALEX_API_URL:-http://127.0.0.1:8000}" FRONTEND_ORIGIN=http://localhost:3100
mkdir -p .runtime
cd backend
exec ../.venv/bin/python -m uvicorn app.main:app --host 127.0.0.1 --port "${PORT:-8002}"
