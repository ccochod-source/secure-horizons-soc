"""HTTP interface for the simple Supabase-backed RAG assistant."""

import secrets
from contextlib import asynccontextmanager

import httpx
from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.responses import JSONResponse

from .config import Settings
from .models import RAGChatRequest
from .relay import Relay
from .runtime import ModelError, RAGAssistant
from .storage import DatabaseError, SupabaseStore


def create_app(settings=None, store=None, client=None, answerer=None):
    @asynccontextmanager
    async def lifespan(app):
        cfg = settings or Settings.from_env()
        own_client = client is None
        http = client or httpx.AsyncClient()
        app.state.settings = cfg
        app.state.store = store or SupabaseStore(cfg, http)
        app.state.assistant = RAGAssistant(app.state.store, cfg, http, answerer, Relay(app.state.store, cfg, http))
        try:
            yield
        finally:
            if own_client:
                await http.aclose()

    app = FastAPI(
        title="Assistant développeur RAG",
        description="Répond aux questions à partir des documents de Supabase.",
        version="0.1.0",
        lifespan=lifespan,
    )

    def require_gateway_token(authorization: str | None = Header(default=None)):
        expected = app.state.settings.gateway_token
        if not expected or not secrets.compare_digest(authorization or "", "Bearer " + expected):
            raise HTTPException(401, "Jeton d’accès manquant ou invalide.")

    @app.exception_handler(DatabaseError)
    async def database_error(_request, _error):
        return JSONResponse(status_code=503, content={"detail": "La base de connaissances est momentanément indisponible."})

    @app.exception_handler(ModelError)
    async def model_error(_request, _error):
        return JSONResponse(status_code=502, content={"detail": "Le service de réponse est momentanément indisponible."})

    @app.get("/health", dependencies=[Depends(require_gateway_token)])
    async def health():
        await app.state.store.health()
        return {"ok": True, "database_connected": True, "model": app.state.settings.rag_model}

    @app.post("/chat", dependencies=[Depends(require_gateway_token)])
    async def chat(request: RAGChatRequest):
        return await app.state.assistant.chat(request)

    return app


app = create_app()
