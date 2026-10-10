"""Couche de leurres vue par la passerelle : détecteur et bac à sable réunis."""

from __future__ import annotations

from typing import Any

from decoys.detector import Detector
from decoys.tarpit import Tarpit
from gateway.hooks import Direction
from gateway.session import Session


class DecoyDefense:
    """Implémente gateway.hooks.DecoyLayer."""

    def __init__(self, detector: Detector, tarpit: Tarpit | None = None) -> None:
        self.detector = detector
        self.tarpit = tarpit or Tarpit()

    async def trips(self, session: Session, tool: str, payload: Any, direction: Direction) -> bool:
        return await self.detector.trips(session, tool, payload, direction)

    def tarpit_response(self, session: Session, tool: str, args: dict[str, Any]) -> Any:
        return self.tarpit.response(session, tool, args)
