"""Route d'entrée de la démo : une question posée à l'agent victime."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from env_attacked.llm import LLMError
from env_attacked.victim import VictimAgent
from gateway import TraceUnavailable
from gateway.routes import _authorized


class ChatIn(BaseModel):
    question: str = Field(min_length=1, max_length=4000)
    user_id: str | None = None
    run_id: UUID | None = None
    poisoned: bool = False  # connecte le serveur MCP tiers piégé (scénario 1)


router = APIRouter(dependencies=[Depends(_authorized)])


@router.post("/chat")
async def chat(body: ChatIn, request: Request) -> dict[str, Any]:
    victim: VictimAgent | None = getattr(request.app.state, "victim", None)
    if victim is None:
        raise HTTPException(status_code=503, detail="Agent victime non configuré (OPENAI_API_KEY absent).")
    try:
        result = await victim.chat(body.question, user_id=body.user_id, poisoned=body.poisoned, run_id=body.run_id)
        bridge = getattr(request.app.state, "defense", None)
        if bridge:
            session = request.app.state.gateway.session(UUID(result["trace_id"]))
            session.closed = True
            result["pipeline_delivery"] = await bridge.complete(session)
        return result
    except LLMError as exc:
        raise HTTPException(status_code=502, detail=f"Modèle indisponible : {exc}") from None
    except TraceUnavailable:
        raise HTTPException(status_code=503, detail="Traçage indisponible : conversation interrompue.") from None
