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
    return Settings(
        database_url=database_url,
        gitguardian_api_key=os.getenv("GITGUARDIAN_API_KEY", "").strip() or None,
        frontend_origin=os.getenv("FRONTEND_ORIGIN", "http://localhost:3100").strip(),
        gateway_token=os.getenv("GATEWAY_TOKEN", "").strip() or None,
        mcp_upstream_urls=urls,
    )
