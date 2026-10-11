"""Point d'entrée FastAPI : passerelle de traçage, coffre et contrôle des packages.

Lancer depuis backend/ : uvicorn app.main:app --reload
"""

from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager
from typing import AsyncIterator

import httpx
from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from common.config import REPO_ROOT, load_settings
from common.db import ROLE_GATEWAY, Database
from common.rules import PostgresRuleStore
from decoys import DecoyDefense, Detector, PostgresDecoyStore, Seeder, Tarpit
from decoys.learning import DecoyLearning
from decoys.routes import router as decoys_router
from env_attacked import OpenAIClient, PostgresCompanyData, VictimAgent, build_servers, embed_documents
from env_attacked.routes import router as chat_router
from gateway.events import PostgresEventStore
from gateway.defense import DefenseBridge
from gateway.proxy import Gateway
from gateway.routes import router, confinement_router
from gateway.upstream import McpUpstream
from packages import AgentEnvInstaller, LocalQuarantine, PackageReviewer, PostgresReviewStore
from packages.learning import PackageLearning
from packages.routes import AnalystAuth, SupabaseAuth
from packages.routes import router as packages_router
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
    http = httpx.AsyncClient(timeout=20, follow_redirects=True, headers={"user-agent": "copilote-soc-packages"})
    try:
        async with db.as_role(ROLE_GATEWAY) as conn:
            cur = await conn.execute("select full_name from public.employees")
            names = [row["full_name"] for row in await cur.fetchall()]
        pseudonymizer = Pseudonymizer(PostgresTokenStore(db), Scanner(names), gitguardian)
        events = PostgresEventStore(db)
        review_store = PostgresReviewStore(db)
        # LEARNING_ENABLED absent ou faux : aucune règle apprise n'est lue ni proposée.
        learning = (PackageLearning(PostgresRuleStore(db), review_store)
                    if settings.learning_enabled else None)
        packages = PackageReviewer(
            review_store, events, pseudonymizer, http,
            LocalQuarantine(settings.package_quarantine_dir),
            AgentEnvInstaller(settings.package_agent_env) if settings.package_agent_env else None,
            learning=learning,
        )
        decoy_store = PostgresDecoyStore(db)
        decoy_learning = (DecoyLearning(PostgresRuleStore(db, "decoy_rules"), decoy_store)
                          if settings.learning_enabled else None)
        if settings.decoys_seed_on_start:
            try:
                report = await Seeder(
                    decoy_store, gitguardian_api_key=settings.gitguardian_api_key, client=http,
                    rules=decoy_learning.rules if decoy_learning else None).seed()
                logger.info("leurres : %d planté(s), %d déjà en place, %d ignoré(s)",
                            len(report.planted), len(report.existing), len(report.skipped))
            except Exception:
                # Les leurres déjà plantés restent utilisables : on démarre avec eux.
                logger.exception("semis des leurres en échec")
        detector = Detector(decoy_store, events, pseudonymizer)
        if await detector.load() == 0:
            logger.error("aucun leurre reconnu : la couche de leurres ne déclenchera rien")
        decoys = DecoyDefense(detector, Tarpit(settings.tarpit_payload_chars))
        bridge = DefenseBridge(db, http, os.getenv("ALEX_API_URL", "http://127.0.0.1:8000"),
                               os.getenv("PASSERELLE_TOKEN", ""), REPO_ROOT / ".runtime/gateway-state.sqlite")
        gateway = Gateway(events, pseudonymizer, decoys=decoys, packages=packages, defense=bridge)
        app.state.defense = bridge
        app.state.confinement_token = os.getenv("CONFINEMENT_TOKEN", "")
        # Environnement attaqué : ses serveurs MCP tournent dans ce processus, derrière la passerelle.
        company = PostgresCompanyData(db)
        openai = (OpenAIClient(http, settings.openai_api_key, settings.openai_model)
                  if settings.openai_api_key else None)
        if openai is not None:
            try:
                logger.info("embeddings calculés pour %d document(s)", await embed_documents(company, openai))
            except Exception:
                logger.exception("calcul des embeddings en échec : recherche documentaire par mots")
        servers = [(server.name, server) for server in build_servers(company, openai)]
        servers += [(f"mcp_{index}", url) for index, url in enumerate(settings.mcp_upstream_urls, start=1)]
        for name, server in servers:
            upstream = McpUpstream(name, server)
            await upstream.start()
            upstreams.append(upstream)
            await gateway.register(upstream)
        app.state.db = db
        app.state.company, app.state.openai = company, openai
        app.state.gateway = gateway
        app.state.gateway_token = settings.gateway_token
        app.state.packages = packages
        app.state.learning = learning
        app.state.decoy_learning = decoy_learning
        app.state.decoys = decoys
        app.state.victim = VictimAgent(gateway, openai) if openai is not None else None
        app.state.analyst_auth = (
            SupabaseAuth(http, settings.supabase_url, settings.supabase_api_key)
            if settings.supabase_url and settings.supabase_api_key else None
        )
        logger.info("passerelle prête : %d nom(s) dans l'annuaire, GitGuardian %s",
                    len(names), "actif" if gitguardian else "absent")
        logger.info("boucle d'amélioration %s", "active" if learning else "éteinte (LEARNING_ENABLED)")
        yield
    finally:
        for upstream in reversed(upstreams):
            await upstream.close()
        if gitguardian is not None:
            await gitguardian.aclose()
        await http.aclose()
        await db.close()


def create_app(
    *, gateway: Gateway | None = None, gateway_token: str | None = None,
    packages: PackageReviewer | None = None, analyst_auth: AnalystAuth | None = None,
    victim: VictimAgent | None = None, learning: PackageLearning | None = None,
    decoy_learning: DecoyLearning | None = None,
) -> FastAPI:
    """Sans argument : application réelle. Avec une passerelle : application de test."""
    load_dotenv(REPO_ROOT / ".env")
    app = FastAPI(title="Copilote SOC — passerelle", lifespan=None if gateway else _lifespan)
    if gateway is not None:
        app.state.gateway = gateway
        app.state.gateway_token = gateway_token
        app.state.packages = packages
        app.state.analyst_auth = analyst_auth
        app.state.victim = victim
        app.state.learning = learning
        app.state.decoy_learning = decoy_learning
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[os.getenv("FRONTEND_ORIGIN", "http://localhost:3100")],
        allow_methods=["GET", "POST"],
        allow_headers=["authorization", "content-type"],
    )
    app.include_router(router)
    app.include_router(confinement_router)
    app.include_router(packages_router)
    app.include_router(decoys_router)
    app.include_router(chat_router)

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    return app


app = create_app()
