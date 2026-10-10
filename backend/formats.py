"""Les formats échangés avec le reste de l'équipe.

Ils recopient les types de l'interface (frontend/src/lib/demo-data.ts) :
si Léon ou l'interface changent un champ, c'est ici qu'il faut le changer aussi.
"""
from typing import Literal, Optional

from pydantic import BaseModel


class TraceEvent(BaseModel):
    """Un événement observé par la passerelle (produit par l'agent d'Elyott)."""
    id: str
    parent_event_id: Optional[str] = None
    timestamp: str
    actor: str
    type: str
    title: str
    description: str
    tool: str
    resource: str
    result: Literal["allowed", "blocked", "flagged"]


class LotEvenements(BaseModel):
    """Ce qu'on envoie au pipeline : les événements d'une même conversation de l'agent."""
    agent_id: str
    events: list[TraceEvent]


class Conclusion(BaseModel):
    """Une affirmation de l'enquêteur, avec les événements qui la prouvent."""
    affirmation: str
    evidence_ids: list[str]
    verifiee: bool = False


class Incident(BaseModel):
    """Le dossier affiché par l'interface. Les 13 premiers champs sont ceux de demo-data.ts."""
    id: str
    title: str
    agent: str
    agentId: str
    severity: Literal["Critique", "Élevée", "Modérée"]
    status: Literal["À examiner", "En enquête", "Confiné", "Surveillance"]
    time: str
    duration: str
    description: str
    evidence: list[str]
    events: list[TraceEvent]
    proposal: str
    impact: str
    # Champs en plus, que l'interface peut afficher si elle le souhaite :
    confidence: float = 0.0
    conclusions: list[Conclusion] = []
    decision: Literal["pending", "approved", "rejected"] = "pending"
    decision_reason: str = ""


class DecisionAnalyste(BaseModel):
    """Ce que l'interface renvoie quand l'analyste clique sur Approuver ou Refuser."""
    decision: Literal["approved", "rejected"]
    reason: str = ""
    analyst: str = "analyste"
