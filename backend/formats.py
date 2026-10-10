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


TypeConclusion = Literal["instruction_suspecte", "lecture_sensible", "sortie_externe", "propagation", "blocage"]
Statut = Literal["À examiner", "En enquête", "Approuvé, en attente d'exécution", "Confiné", "Surveillance"]


class Conclusion(BaseModel):
    """Une affirmation de l'enquêteur, avec les événements qui la prouvent.
    Le type dit QUOI vérifier ; le vérificateur (du code) le contrôle sur les événements cités."""
    type: TypeConclusion
    affirmation: str
    evidence_ids: list[str]
    verifiee: bool = False
    raison: str = ""  # pourquoi le vérificateur l'a acceptée ou rejetée


class Action(BaseModel):
    """L'action de confinement proposée. origine = "regle" si la cible de l'IA était invalide et a été remplacée."""
    type: Literal["suspendre_outil", "quarantaine_source", "revoquer_secret", "lecture_seule"]
    cible: str
    origine: Literal["enqueteur", "regle"] = "enqueteur"
    correction: str = ""


class Execution(BaseModel):
    """Ce qui s'est réellement passé après l'approbation.
    non_demandee : pas encore approuvé (ou refusé) ; en_attente : approuvé, la passerelle n'a pas encore confirmé ;
    execute : la passerelle a confirmé ; echec : la passerelle a refusé ou n'a pas répondu."""
    etat: Literal["non_demandee", "en_attente", "execute", "echec"] = "non_demandee"
    detail: str = ""
    horodatage: str = ""


class Incident(BaseModel):
    """Le dossier affiché par l'interface. Les 13 premiers champs sont ceux de demo-data.ts."""
    id: str
    title: str
    agent: str
    agentId: str
    severity: Literal["Critique", "Élevée", "Modérée"]
    status: Statut
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
    decided_by: str = ""
    action: Optional[Action] = None
    execution: Execution = Execution()


class DecisionAnalyste(BaseModel):
    """Ce que l'interface renvoie quand l'analyste clique sur Approuver ou Refuser."""
    decision: Literal["approved", "rejected"]
    reason: str = ""
    analyst: str = "analyste"


class CompteRenduExecution(BaseModel):
    """Ce que la passerelle renvoie quand elle a appliqué (ou pas) l'action approuvée."""
    etat: Literal["execute", "echec"]
    detail: str = ""
