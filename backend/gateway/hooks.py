"""Points d'accroche des deux blocs de protection branchés sur la passerelle.

La couche de leurres (backend/decoys) et le contrôle des packages
(backend/packages) implémentent ces interfaces ; les méthodes peuvent être
synchrones ou asynchrones. Tant qu'ils ne sont pas branchés, les
implémentations par défaut s'appliquent.
"""

from __future__ import annotations

from typing import Any, Literal, Protocol
from uuid import UUID

from gateway.session import Session

Direction = Literal["call", "result"]


class DecoyLayer(Protocol):
    def trips(self, session: Session, tool: str, payload: Any, direction: Direction) -> bool:
        """Vrai si un leurre apparaît dans les paramètres d'un appel ou dans son résultat.

        Reçoit le contenu réel (non pseudonymisé) : il ne doit ni l'écrire ni le
        transmettre. C'est à lui de lever l'alerte ; la passerelle déroute la session.
        """
        ...

    def tarpit_response(self, session: Session, tool: str, args: dict[str, Any]) -> Any:
        """Réponse leurre servie à une session déroutée, sans accès réel."""
        ...


class PackageControl(Protocol):
    def review(
        self, session: Session, event_id: UUID, ecosystem: str, name: str, version: str | None = None
    ) -> dict[str, Any]:
        """Traite une demande d'installation ; rend un dict avec au moins « status »."""
        ...


class NoDecoys:
    """Aucun leurre semé : rien ne déclenche, aucune session n'est déroutée."""

    def trips(self, session: Session, tool: str, payload: Any, direction: Direction) -> bool:
        return False

    def tarpit_response(self, session: Session, tool: str, args: dict[str, Any]) -> Any:
        return {"result": ""}


class PackagesBlocked:
    """Sans contrôle des packages branché, rien ne s'installe (refus par défaut)."""

    def review(
        self, session: Session, event_id: UUID, ecosystem: str, name: str, version: str | None = None
    ) -> dict[str, Any]:
        return {"status": "blocked", "reason": "contrôle des packages non branché"}
