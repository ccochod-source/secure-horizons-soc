"""Verdict de l'analyste sur une alerte, point de départ de la boucle des leurres."""

from __future__ import annotations

import logging
from typing import Any, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from decoys.learning import DecoyLearning
from packages.routes import _analyst, _rule

logger = logging.getLogger(__name__)

router = APIRouter()


class VerdictIn(BaseModel):
    verdict: Literal["confirmed", "false_positive"]


@router.post("/alerts/{alert_id}/verdict")
async def verdict(
    alert_id: UUID, body: VerdictIn, request: Request, analyst: str = Depends(_analyst)
) -> dict[str, Any]:
    learning: DecoyLearning | None = getattr(request.app.state, "decoy_learning", None)
    if learning is None:
        raise HTTPException(status_code=503, detail="Boucle d'apprentissage des leurres non branchée.")
    recorded = await learning.record_verdict(alert_id, body.verdict, analyst)
    if recorded is None:
        raise HTTPException(status_code=404, detail="Alerte inconnue.")
    if not recorded:
        raise HTTPException(status_code=409, detail="Un verdict a déjà été rendu sur cette alerte.")
    result: dict[str, Any] = {"alert_id": str(alert_id), "verdict": body.verdict, "decided_by": analyst,
                              "rule_proposals": []}
    try:
        result["rule_proposals"] = [_rule(r, "decoy") for r in await learning.propose(alert_id)]
    except Exception:
        # Le verdict est enregistré : un échec ici ne l'annule pas.
        logger.exception("proposition de leurre en échec")
    return result
