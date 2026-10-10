"""Routes HTTP de la passerelle (agent victime, banc de test, interface)."""

from __future__ import annotations

import hmac
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
    return {"event_id": event_id}


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
    return {"event_id": await _traced(gateway.record_response(session, body.text))}


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
