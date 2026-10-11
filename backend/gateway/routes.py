"""Routes HTTP de la passerelle (agent victime, banc de test, interface)."""

from __future__ import annotations

import hmac
import re
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from gateway.proxy import (
    DocumentSource, Gateway, ToolFailed, TraceUnavailable, UnknownSession, UnknownTool,
)


class SessionIn(BaseModel):
    agent_id: str = Field(min_length=1)
    user_id: str | None = None
    run_id: UUID | None = None
    query: str | None = None


class DocumentIn(BaseModel):
    source: DocumentSource
    resource_id: str = Field(min_length=1)
    content: str
    title: str | None = None


class ToolCallIn(BaseModel):
    arguments: dict[str, Any] = Field(default_factory=dict)


class ResponseIn(BaseModel):
    text: str


def _gateway(request: Request) -> Gateway:
    return request.app.state.gateway


def _authorized(request: Request) -> None:
    expected: str | None = request.app.state.gateway_token
    if expected is None:
        return
    given = request.headers.get("authorization", "")
    if not hmac.compare_digest(given.encode(), f"Bearer {expected}".encode()):
        raise HTTPException(status_code=401, detail="Jeton de passerelle manquant ou invalide.")


router = APIRouter(dependencies=[Depends(_authorized)])


def _session(gateway: Gateway, trace_id: UUID):
    try:
        return gateway.session(trace_id)
    except UnknownSession:
        raise HTTPException(status_code=404, detail="Session inconnue.") from None


@router.post("/gateway/sessions", status_code=201)
async def open_session(body: SessionIn, gateway: Gateway = Depends(_gateway)) -> dict[str, Any]:
    session = gateway.open_session(body.agent_id, user_id=body.user_id, run_id=body.run_id)
    event_id = None
    if body.query is not None:
        event_id = await _traced(gateway.record_query(session, body.query))
    return {"trace_id": session.trace_id, "event_id": event_id}


@router.post("/gateway/sessions/{trace_id}/documents", status_code=201)
async def record_document(trace_id: UUID, body: DocumentIn, gateway: Gateway = Depends(_gateway)) -> dict[str, Any]:
    session = _session(gateway, trace_id)
    event_id = await _traced(
        gateway.record_document(
            session, source=body.source, resource_id=body.resource_id, content=body.content, title=body.title
        )
    )
    return {"event_id": event_id, "diverted": session.diverted}


@router.post("/gateway/sessions/{trace_id}/tools/{tool}")
async def call_tool(trace_id: UUID, tool: str, body: ToolCallIn, gateway: Gateway = Depends(_gateway)) -> dict[str, Any]:
    session = _session(gateway, trace_id)
    try:
        result = await gateway.dispatch(session, tool, body.arguments)
    except UnknownTool:
        raise HTTPException(status_code=404, detail="Outil inconnu de la passerelle.") from None
    except ToolFailed:
        raise HTTPException(status_code=502, detail="L'outil a échoué ; l'échec est tracé.") from None
    except TraceUnavailable:
        raise HTTPException(status_code=503, detail="Traçage indisponible : appel refusé.") from None
    return {"result": result, "diverted": session.diverted}


@router.post("/gateway/sessions/{trace_id}/response", status_code=201)
async def record_response(trace_id: UUID, body: ResponseIn, gateway: Gateway = Depends(_gateway)) -> dict[str, Any]:
    session = _session(gateway, trace_id)
    event_id = await _traced(gateway.record_response(session, body.text))
    return {"event_id": event_id, "diverted": session.diverted}


@router.get("/gateway/tools")
async def list_tools(gateway: Gateway = Depends(_gateway)) -> dict[str, Any]:
    return {"tools": gateway.tools()}


@router.get("/incidents/{trace_id}/graph")
async def provenance_graph(trace_id: UUID, gateway: Gateway = Depends(_gateway)) -> dict[str, Any]:
    return await gateway.graph(trace_id)


async def _traced(operation):
    try:
        return await operation
    except TraceUnavailable:
        raise HTTPException(status_code=503, detail="Traçage indisponible : opération refusée.") from None


class ConfinementIn(BaseModel):
    incident_id: str = Field(min_length=1, max_length=100)
    action: str
    cible: str = Field(min_length=1, max_length=100)
    agent_id: str = Field(min_length=1, max_length=100)
    approuve_par: str = Field(min_length=1, max_length=100)


_PACKAGE_REF = re.compile(r"(pypi|npm):[A-Za-z0-9@/_.-]{1,214}")
_UUID = re.compile(r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}")


def _confinement_auth(request: Request) -> None:
    expected = getattr(request.app.state, "confinement_token", "")
    if not expected or not hmac.compare_digest(request.headers.get("authorization", ""), "Bearer " + expected):
        raise HTTPException(401, "Jeton de confinement invalide.")

# Separate auth: the defense backend cannot borrow the gateway agent token.
confinement_router = APIRouter()


@confinement_router.post("/confinement")
async def confine(body: ConfinementIn, request: Request):
    expected = getattr(request.app.state, "confinement_token", "")
    if not expected or not hmac.compare_digest(request.headers.get("authorization", ""), "Bearer " + expected):
        raise HTTPException(401, "Jeton de confinement invalide.")
    gateway = request.app.state.gateway
    if body.action == "quarantaine_source" and _PACKAGE_REF.fullmatch(body.cible):
        # Source = un package : il est refusé à tous les agents, quelle que soit sa version, jusqu'à levée.
        key = request.app.state.defense.quarantine_package(body.cible, body.incident_id, body.approuve_par)
        return {"etat": "execute", "package": key, "quarantaine": True}
    if body.action == "quarantaine_source" and _UUID.fullmatch(body.cible):
        # Source = un document de la base : il n'est plus jamais rendu par la recherche de l'agent.
        title = await request.app.state.defense.quarantine_document(body.cible, body.incident_id, body.approuve_par)
        if title is None:
            raise HTTPException(422, "Document inconnu.")
        return {"etat": "execute", "document": body.cible, "titre": title, "quarantaine": True}
    if body.action != "suspendre_outil":
        raise HTTPException(422, "Prises en charge : suspension d’outil, quarantaine d’un package (pypi:… / npm:…) ou d’un document.")
    if body.cible not in {t["name"] for t in gateway.tools()} and body.cible != "install_package":
        raise HTTPException(422, "Outil inconnu.")
    request.app.state.defense.suspend(body.agent_id, body.cible, body.incident_id, body.approuve_par)
    return {"etat": "execute", "tool": body.cible, "agent_id": body.agent_id}


@confinement_router.get("/confinement/documents")
async def quarantined_documents(request: Request):
    _confinement_auth(request)
    return {"documents": request.app.state.defense.quarantined_documents()}


@confinement_router.delete("/confinement/documents/{document_id}")
async def release_document(document_id: UUID, request: Request):
    """Lève la quarantaine d'un document : il retrouve son statut précédent."""
    _confinement_auth(request)
    if not await request.app.state.defense.release_document(document_id):
        raise HTTPException(404, "Ce document n'est pas en quarantaine.")
    return {"document": str(document_id), "quarantaine": False}


class RemovalIn(BaseModel):
    demande_par: str = Field(min_length=1, max_length=100)
    raison: str = Field(default="Retiré après contre-vérification", max_length=500)


@confinement_router.post("/packages/{review_id}/removal")
async def remove_package(review_id: UUID, body: RemovalIn, request: Request):
    """Retire un package approuvé, à la demande du backend de défense, après confirmation de l'analyste
    qui l'avait approuvé. Même jeton que le confinement."""
    expected = getattr(request.app.state, "confinement_token", "")
    if not expected or not hmac.compare_digest(request.headers.get("authorization", ""), "Bearer " + expected):
        raise HTTPException(401, "Jeton de confinement invalide.")
    from packages.review import NotPending, UnknownReview
    try:
        return await request.app.state.packages.remove(review_id, decided_by=body.demande_par, reason=body.raison)
    except UnknownReview:
        raise HTTPException(404, "Revue de package inconnue.") from None
    except NotPending as exc:
        raise HTTPException(409, f"Ce package n'est pas approuvé (état : {exc}).") from None


@router.post("/gateway/sessions/{trace_id}/complete")
async def complete(trace_id: UUID, request: Request):
    gateway = request.app.state.gateway
    session = _session(gateway, trace_id)
    async with session.lock:
        session.closed = True
        return await request.app.state.defense.complete(session)


@router.get('/gateway/package-reviews')
async def package_reviews(request: Request):
    async with request.app.state.db.as_owner() as conn:
        rows = await (await conn.execute(
            "select id,package_name,registry,version,state,risk_level,recommendation from public.package_reviews "
            "where state='pending_approval' order by created_at desc limit 30")).fetchall()
    return {'reviews': rows}
