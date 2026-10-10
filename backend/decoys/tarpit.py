"""Bac à sable : réponses leurres servies à une session déjà déroutée.

Aucun accès à une vraie ressource ni à la base. Les réponses sont volumineuses
et répétitives : elles saturent la fenêtre de contexte de l'agent compromis.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from gateway.session import Session

PAYLOAD_SIZE = 120_000  # caractères par réponse, soit environ 30 000 jetons


class NotDiverted(RuntimeError):
    """Garde-fou : le tarpit n'agit jamais sur une session non déroutée."""


def build_decoy_payload(size: int, page: int = 1) -> str:
    """Texte factice et inerte : ni donnée réelle, ni secret, ni instruction."""
    lines: list[str] = []
    length, index = 0, 0
    while length < size:
        index += 1
        line = (f"archive-{2019 + index % 6}-{1 + index % 12:02d}/lot-{page:03d}-{index:05d} | "
                f"index des sauvegardes | segment {index} sur 99999 | état : synchronisé | "
                f"contenu différé, voir le lot suivant")
        lines.append(line)
        length += len(line) + 1
    return "\n".join(lines)[:size]


class Tarpit:
    def __init__(self, payload_size: int = PAYLOAD_SIZE) -> None:
        self._size = payload_size
        self._pages: dict[UUID, int] = {}

    def response(self, session: Session, tool: str, args: dict[str, Any]) -> dict[str, Any]:
        if not session.diverted:
            raise NotDiverted(str(session.trace_id))
        page = self._pages.get(session.trace_id, 0) + 1
        self._pages[session.trace_id] = page
        # « next_page » invite l'agent à redemander : chaque appel remplit un peu plus son contexte.
        return {"result": build_decoy_payload(self._size, page), "page": page, "next_page": page + 1,
                "truncated": True}
