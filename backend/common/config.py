"""Configuration du backend, lue depuis l'environnement (.env à la racine du dépôt)."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

REPO_ROOT = Path(__file__).resolve().parents[2]


class ConfigError(RuntimeError):
    pass


@dataclass(frozen=True)
class Settings:
    database_url: str
    gitguardian_api_key: str | None
    frontend_origin: str
    gateway_token: str | None
    mcp_upstream_urls: tuple[str, ...]
    supabase_url: str | None = None
    supabase_api_key: str | None = None  # clé envoyée à Supabase Auth pour valider un jeton d'analyste
    package_quarantine_dir: Path = REPO_ROOT / "backend" / ".quarantine"
    package_agent_env: Path | None = None  # absent : installations enregistrées, non réalisées
    openai_api_key: str | None = None  # absent : pas d'agent victime, recherche documentaire par mots
    openai_model: str = "gpt-4o-mini"
    decoys_seed_on_start: bool = True
    tarpit_payload_chars: int = 120_000


def load_settings() -> Settings:
    load_dotenv(REPO_ROOT / ".env")
    database_url = os.getenv("DATABASE_URL", "").strip()
    if not database_url.startswith(("postgres://", "postgresql://")):
        # L'ancien .env de l'équipe y mettait l'URL REST du projet : inutilisable ici.
        raise ConfigError(
            "DATABASE_URL doit être la chaîne de connexion PostgreSQL du projet Supabase "
            "(postgresql://…), pas son URL HTTPS."
        )
    urls = tuple(u.strip() for u in os.getenv("MCP_UPSTREAM_URLS", "").split(",") if u.strip())
    supabase_url = os.getenv("SUPABASE_URL", "").strip()
    api_key = next((v for v in (os.getenv(n, "").strip() for n in (
        "SUPABASE_ANON_KEY", "NEXT_PUBLIC_SUPABASE_ANON_KEY", "SUPABASE_SERVICE_ROLE_KEY")) if v), None)
    quarantine_dir = os.getenv("PACKAGE_QUARANTINE_DIR", "").strip()
    agent_env = os.getenv("PACKAGE_AGENT_ENV", "").strip()
    return Settings(
        database_url=database_url,
        gitguardian_api_key=os.getenv("GITGUARDIAN_API_KEY", "").strip() or None,
        frontend_origin=os.getenv("FRONTEND_ORIGIN", "http://localhost:3100").strip(),
        gateway_token=os.getenv("GATEWAY_TOKEN", "").strip() or None,
        mcp_upstream_urls=urls,
        supabase_url=supabase_url if supabase_url.startswith("https://") else None,
        supabase_api_key=api_key,
        package_quarantine_dir=Path(quarantine_dir) if quarantine_dir else REPO_ROOT / "backend" / ".quarantine",
        package_agent_env=Path(agent_env) if agent_env else None,
        openai_api_key=os.getenv("OPENAI_API_KEY", "").strip() or None,
        openai_model=os.getenv("OPENAI_MODEL", "").strip() or "gpt-4o-mini",
        decoys_seed_on_start=os.getenv("DECOYS_SEED_ON_START", "true").strip().lower() not in ("0", "false", "no"),
        tarpit_payload_chars=_positive_int("TARPIT_PAYLOAD_CHARS", 120_000),
    )


def _positive_int(name: str, default: int) -> int:
    raw = os.getenv(name, "").strip()
    if not raw:
        return default
    if not raw.isdigit() or int(raw) == 0:
        raise ConfigError(f"{name} doit être un entier strictement positif.")
    return int(raw)
