"""Le pipeline de défense, écrit avec LangGraph.

Chaque étape est une fonction. Elles s'enchaînent dans cet ordre :

    règle  ->  enquêteur  ->  vérificateur  ->  dossier  ->  attente de l'analyste  ->  décision

- La règle est du code simple : elle repère un comportement suspect, sans IA.
- L'enquêteur est le seul appel à l'IA (OpenAI). Il doit citer les événements qui prouvent chaque conclusion.
- Le vérificateur est du code : il rejette toute conclusion qui cite un événement inexistant
  et calcule lui-même le score de confiance (l'IA ne le choisit pas).
- L'attente de l'analyste met le pipeline en pause jusqu'au clic dans l'interface.
  Aucune action de confinement ne peut partir sans ce clic.

Test sans clé OpenAI :  MOCK_LLM=1 python pipeline.py
"""
import os
import re
import sqlite3
from datetime import datetime
from typing import Literal, TypedDict

from dotenv import load_dotenv
from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import Command, interrupt
from pydantic import BaseModel

import stockage

load_dotenv()  # lit le fichier .env (clé OpenAI, modèle...)

MOCK_LLM = os.getenv("MOCK_LLM") == "1"
MODELE = os.getenv("OPENAI_MODEL") or "gpt-5-mini"
SEUIL_CONFIANCE = 0.7

# ---------------------------------------------------------------------------
# Réglages de la règle (plus tard dans un fichier que le RSSI pourra modifier)
# ---------------------------------------------------------------------------
MOTS_SENSIBLES = re.compile(r"\.env|secret|credential|password|mot de passe|token|api[_-]?key|clé", re.I)
OUTILS_SORTANTS = {"github.publish", "http.post", "send_message", "email.send", "slack.post", "webhook.send"}
FORMAT_SECRET = re.compile(r"(sk-[A-Za-z0-9_\-]{8,}|AKIA[0-9A-Z]{16}|ghp_[A-Za-z0-9]{20,})")

# Les seules actions que l'enquêteur a le droit de proposer.
ACTIONS = {
    "suspendre_outil": "Suspendre le connecteur {cible}",
    "quarantaine_source": "Mettre la source {cible} en quarantaine",
    "revoquer_secret": "Révoquer et remplacer le secret {cible}",
    "lecture_seule": "Passer l'agent {cible} en lecture seule",
}


# ---------------------------------------------------------------------------
# L'état : le dossier qui passe d'étape en étape
# ---------------------------------------------------------------------------
class Etat(TypedDict, total=False):
    incident_id: str
    agent_id: str
    events: list[dict]
    alerte: dict | None
    enquete: dict
    conclusions: list[dict]
    confiance: float
    incident: dict


# Le format que l'IA est obligée de respecter.
class ConclusionIA(BaseModel):
    affirmation: str
    evidence_ids: list[str]


class SortieEnqueteur(BaseModel):
    title: str
    description: str
    severity: Literal["Critique", "Élevée", "Modérée"]
    conclusions: list[ConclusionIA]
    action: Literal[tuple(ACTIONS)]
    cible: str
    impact: str


# ---------------------------------------------------------------------------
# Étape 1 : la règle (sans IA)
# ---------------------------------------------------------------------------
def descend_de(event: dict, ancetre_id: str, par_id: dict) -> bool:
    """Vrai si l'événement découle (directement ou non) de l'événement ancetre_id."""
    parent = event.get("parent_event_id")
    while parent:
        if parent == ancetre_id:
            return True
        parent = par_id.get(parent, {}).get("parent_event_id")
    return False


def regle(etat: Etat) -> dict:
    """Comportement suspect = l'agent lit une ressource sensible, puis une action qui en découle sort vers l'extérieur."""
    events = etat["events"]
    par_id = {e["id"]: e for e in events}
    lectures = [e for e in events if MOTS_SENSIBLES.search(e["resource"])]
    sorties = [e for e in events if e["tool"] in OUTILS_SORTANTS or e["resource"].startswith("external/")]
    for lecture in lectures:
        for sortie in sorties:
            if descend_de(sortie, lecture["id"], par_id):
                return {"alerte": {"motif": "lecture d'une ressource sensible suivie d'une sortie vers l'extérieur",
                                   "evenements": [lecture["id"], sortie["id"]]}}
    return {"alerte": None}


# ---------------------------------------------------------------------------
# Étape 2 : l'enquêteur (le seul appel à l'IA)
# ---------------------------------------------------------------------------
def masquer(texte: str) -> str:
    """On ne montre jamais un vrai secret à l'IA."""
    return FORMAT_SECRET.sub("[SECRET_MASQUÉ]", texte)


def enqueteur(etat: Etat) -> dict:
    events = etat["events"]
    if MOCK_LLM:
        lecture_id, sortie_id = etat["alerte"]["evenements"]
        sortie = next(e for e in events if e["id"] == sortie_id)
        resultat = SortieEnqueteur(
            title="Tentative d'extraction de secrets",
            description="L'agent a lu une ressource sensible puis a tenté de l'envoyer vers l'extérieur.",
            severity="Critique",
            conclusions=[ConclusionIA(affirmation="L'agent a consulté une ressource sensible.", evidence_ids=[lecture_id]),
                         ConclusionIA(affirmation="Une sortie vers l'extérieur découle de cette lecture.",
                                      evidence_ids=[lecture_id, sortie_id])],
            action="suspendre_outil", cible=sortie["tool"],
            impact=f"Le connecteur {sortie['tool']} sera suspendu. Les autres outils de l'agent resteront disponibles.")
    else:
        from langchain.chat_models import init_chat_model
        lignes = "\n".join(
            f"- {e['id']} (parent {e.get('parent_event_id')}) {e['timestamp']} | outil {e['tool']} | "
            f"ressource {e['resource']} | résultat {e['result']} | {masquer(e['title'])} : {masquer(e['description'])}"
            for e in events)
        consigne = (
            "Tu es l'enquêteur d'un SOC. Un agent IA d'entreprise a peut-être été détourné.\n"
            f"Alerte levée par la règle : {etat['alerte']['motif']} (événements {etat['alerte']['evenements']}).\n"
            f"Événements observés par la passerelle :\n{lignes}\n\n"
            "Explique ce qui s'est passé en français, simplement. Chaque conclusion doit citer les identifiants "
            "des événements qui la prouvent, uniquement parmi ceux de la liste. N'invente rien. "
            "Propose une seule action de confinement, la plus ciblée possible, et décris son impact pour les employés."
        )
        modele = init_chat_model(f"openai:{MODELE}")
        resultat = modele.with_structured_output(SortieEnqueteur).invoke(consigne)
    return {"enquete": resultat.model_dump()}


# ---------------------------------------------------------------------------
# Étape 3 : le vérificateur (sans IA)
# ---------------------------------------------------------------------------
def verificateur(etat: Etat) -> dict:
    ids_existants = {e["id"] for e in etat["events"]}
    conclusions = []
    for c in etat["enquete"]["conclusions"]:
        ok = bool(c["evidence_ids"]) and set(c["evidence_ids"]) <= ids_existants
        conclusions.append({**c, "verifiee": ok})
    confiance = sum(c["verifiee"] for c in conclusions) / max(len(conclusions), 1)
    return {"conclusions": conclusions, "confiance": round(confiance, 2)}


# ---------------------------------------------------------------------------
# Étape 4 : le dossier d'incident, au format de l'interface
# ---------------------------------------------------------------------------
def heure(ts: str) -> datetime | None:
    """Accepte "14:32:01" ou une date complète "2026-10-10T14:32:01Z"."""
    try:
        return datetime.fromisoformat(ts.replace("Z", "+00:00")) if "T" in ts else datetime.strptime(ts, "%H:%M:%S")
    except ValueError:
        return None


def dossier(etat: Etat) -> dict:
    enquete, events = etat["enquete"], etat["events"]
    preuves = {i for c in etat["conclusions"] if c["verifiee"] for i in c["evidence_ids"]}
    debut, fin = heure(events[0]["timestamp"]), heure(events[-1]["timestamp"])
    incident = {
        "id": etat["incident_id"],
        "title": enquete["title"],
        "agent": events[0]["actor"],
        "agentId": etat["agent_id"],
        "severity": enquete["severity"],
        "status": "À examiner" if etat["confiance"] >= SEUIL_CONFIANCE else "En enquête",
        "time": debut.strftime("%H:%M") if debut else events[0]["timestamp"],
        "duration": f"{int((fin - debut).total_seconds())} secondes" if debut and fin else "",
        "description": enquete["description"],
        "evidence": [e["id"] for e in events if e["id"] in preuves],  # dans l'ordre chronologique
        "events": events,
        "proposal": ACTIONS[enquete["action"]].format(cible=enquete["cible"]),
        "impact": enquete["impact"],
        "confidence": etat["confiance"],
        "conclusions": etat["conclusions"],
        "decision": "pending",
        "decision_reason": "",
        "action": {"type": enquete["action"], "cible": enquete["cible"]},
    }
    stockage.enregistrer(incident)
    return {"incident": incident}


# ---------------------------------------------------------------------------
# Étape 5 : la pause. Rien d'autre ici : à la reprise, cette fonction est rejouée depuis le début.
# ---------------------------------------------------------------------------
def attente_analyste(etat: Etat) -> dict:
    decision = interrupt(etat["incident"])  # le pipeline s'arrête ici jusqu'au clic de l'analyste
    return {"incident": {**etat["incident"], "decision": decision["decision"],
                         "decision_reason": decision.get("reason", ""), "decided_by": decision.get("analyst", "")}}


# ---------------------------------------------------------------------------
# Étape 6 : appliquer la décision de l'analyste
# ---------------------------------------------------------------------------
def appliquer_decision(etat: Etat) -> dict:
    incident = dict(etat["incident"])
    if incident["decision"] == "approved":
        incident["status"] = "Confiné"
        # Pour l'instant l'action est simulée. Plus tard : appel au proxy MCP ou au coffre à secrets.
        print(f"[action] {incident['proposal']} (approuvé par {incident.get('decided_by')})")
    else:
        incident["status"] = "Surveillance"
    stockage.enregistrer(incident)
    return {"incident": incident}


# ---------------------------------------------------------------------------
# Assemblage
# ---------------------------------------------------------------------------
def apres_regle(etat: Etat) -> str:
    return "enqueteur" if etat["alerte"] else END


def construire_pipeline():
    g = StateGraph(Etat)
    g.add_node("regle", regle)
    g.add_node("enqueteur", enqueteur)
    g.add_node("verificateur", verificateur)
    g.add_node("dossier", dossier)
    g.add_node("attente_analyste", attente_analyste)
    g.add_node("appliquer_decision", appliquer_decision)
    g.add_edge(START, "regle")
    g.add_conditional_edges("regle", apres_regle, ["enqueteur", END])
    g.add_edge("enqueteur", "verificateur")
    g.add_edge("verificateur", "dossier")
    g.add_edge("dossier", "attente_analyste")
    g.add_edge("attente_analyste", "appliquer_decision")
    g.add_edge("appliquer_decision", END)
    # La mémoire du pipeline est dans un fichier : la pause survit même si on relance le programme.
    memoire = SqliteSaver(sqlite3.connect(os.getenv("CHECKPOINT_PATH", "checkpoints.sqlite"), check_same_thread=False))
    return g.compile(checkpointer=memoire)


# ---------------------------------------------------------------------------
# Petit test : python pipeline.py
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    import json
    pipeline = construire_pipeline()
    lot = json.load(open("exemple_attaque.json", encoding="utf-8"))
    incident_id = stockage.nouvel_identifiant()
    config = {"configurable": {"thread_id": incident_id}}

    print("1) Le pipeline reçoit les événements...")
    resultat = pipeline.invoke({"incident_id": incident_id, "agent_id": lot["agent_id"], "events": lot["events"]}, config)
    incident = resultat["__interrupt__"][0].value
    print(f"   Incident {incident['id']} : {incident['title']}")
    print(f"   Explication : {incident['description']}")
    print(f"   Preuves : {incident['evidence']}  |  confiance {incident['confidence']}")
    print(f"   Action proposée : {incident['proposal']}")
    print("   -> en pause, en attente de l'analyste")

    print("2) L'analyste approuve...")
    fin = pipeline.invoke(Command(resume={"decision": "approved", "reason": "test", "analyst": "alex"}), config)
    print(f"   Statut final : {fin['incident']['status']}")
