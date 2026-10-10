"""Point d'entrée FastAPI : passerelle de traçage et coffre de pseudonymisation.

Lancer depuis backend/ : uvicorn app.main:app --reload
"""

from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager
from typing import AsyncIterator

from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from common.config import REPO_ROOT, load_settings
from common.db import ROLE_GATEWAY, Database
from gateway.events import PostgresEventStore
from gateway.proxy import Gateway
from gateway.routes import router
from gateway.upstream import McpUpstream
from vault.gitguardian import GitGuardianClient
from vault.pseudonymize import Pseudonymizer
from vault.scanner import Scanner
from vault.tokens import PostgresTokenStore

logger = logging.getLogger(__name__)


@asynccontextmanager
async def _lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = load_settings()
    db = Database(settings.database_url)
    await db.open()
    gitguardian = GitGuardianClient(settings.gitguardian_api_key) if settings.gitguardian_api_key else None
    upstreams: list[McpUpstream] = []
    try:
        async with db.as_role(ROLE_GATEWAY) as conn:
            cur = await conn.execute("select full_name from public.employees")
            names = [row["full_name"] for row in await cur.fetchall()]
        pseudonymizer = Pseudonymizer(PostgresTokenStore(db), Scanner(names), gitguardian)
        gateway = Gateway(PostgresEventStore(db), pseudonymizer)
        for index, url in enumerate(settings.mcp_upstream_urls, start=1):
            upstream = McpUpstream(f"mcp_{index}", url)
            await upstream.start()
            upstreams.append(upstream)
            await gateway.register(upstream)
        app.state.db = db
        app.state.gateway = gateway
        app.state.gateway_token = settings.gateway_token
        logger.info("passerelle prête : %d nom(s) dans l'annuaire, GitGuardian %s",
                    len(names), "actif" if gitguardian else "absent")
        yield
    finally:
        for upstream in reversed(upstreams):
            await upstream.close()
        if gitguardian is not None:
            await gitguardian.aclose()
        await db.close()


def create_app(*, gateway: Gateway | None = None, gateway_token: str | None = None) -> FastAPI:
    """Sans argument : application réelle. Avec une passerelle : application de test."""
    load_dotenv(REPO_ROOT / ".env")
    app = FastAPI(title="Copilote SOC — passerelle", lifespan=None if gateway else _lifespan)
    if gateway is not None:
        app.state.gateway = gateway
        app.state.gateway_token = gateway_token
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[os.getenv("FRONTEND_ORIGIN", "http://localhost:3100")],
        allow_methods=["GET", "POST"],
        allow_headers=["authorization", "content-type"],
    )
    app.include_router(router)

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    return app


app = create_app()
