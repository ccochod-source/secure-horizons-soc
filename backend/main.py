"""Le serveur du backend : c'est lui que l'interface et la passerelle d'Elyott appellent.

Lancer :  uvicorn main:app --reload --port 8000
Puis ouvrir http://localhost:8000/docs pour tester chaque route à la main.

POST /events                     (passerelle) reçoit les événements d'un agent -> crée un incident si la règle se déclenche
POST /incidents/{id}/execution   (passerelle) confirme que l'action approuvée a été appliquée, ou a échoué
GET  /incidents                  (interface) liste des incidents (le plus récent d'abord)
GET  /incidents/{id}             (interface) un incident
POST /incidents/{id}/decision    (interface) l'analyste approuve ou refuse l'action proposée

Authentification (facultative en local, à activer dès qu'on partage le serveur) :
- PASSERELLE_TOKEN : la passerelle envoie l'en-tête  Authorization: Bearer <PASSERELLE_TOKEN>
- ANALYSTE_TOKEN   : l'interface envoie l'en-tête    Authorization: Bearer <ANALYSTE_TOKEN>
Si la variable est vide, la route correspondante est ouverte (pratique pour tester, jamais en entreprise).
"""
import os
import secrets
import threading
import time
from contextlib import asynccontextmanager
from typing import Literal
from uuid import UUID

from dotenv import load_dotenv
from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from langgraph.types import Command
from pydantic import BaseModel

import knowledge
import stockage
from formats import CompteRenduExecution, DecisionAnalyste, Incident, LotEvenements
from pipeline import construire_pipeline, maintenant, nouveau_thread, preparer_evenements

load_dotenv()


@asynccontextmanager
async def lifespan(_app: FastAPI):
    stop = threading.Event()
    worker = None
    if stockage.DATABASE_URL:
        worker = threading.Thread(target=knowledge.watch, args=(stop,), daemon=True, name="knowledge-review")
        worker.start()
    try:
        yield
    finally:
        stop.set()
        if worker:
            worker.join(timeout=3)


app = FastAPI(title="TRACE — backend", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=[os.getenv("FRONTEND_ORIGIN", "http://localhost:3100")],
                   allow_methods=["*"], allow_headers=["*"])
pipeline = construire_pipeline()


def _controle(variable: str):
    """Fabrique une vérification d'en-tête Authorization pour le jeton rangé dans la variable d'environnement."""
    def verifier(authorization: str | None = Header(default=None)):
        attendu = os.getenv(variable, "")
        if attendu and not secrets.compare_digest(authorization or "", f"Bearer {attendu}"):
            raise HTTPException(401, "Jeton d'accès manquant ou invalide")
    return verifier


passerelle = Depends(_controle("PASSERELLE_TOKEN"))
analyste = Depends(_controle("ANALYSTE_TOKEN"))


class KnowledgeDecision(BaseModel):
    decision: Literal["approve", "reject"]
    analyst: str = "analyste"


@app.get("/health")
def sante():
    return {"ok": True}


@app.get("/knowledge/reviews", dependencies=[analyste])
def connaissances_a_verifier():
    if not stockage.DATABASE_URL:
        return []
    try:
        return knowledge.list_reviews()
    except Exception as exc:
        raise HTTPException(503, "Revue des connaissances indisponible.") from exc


@app.post("/knowledge/{table}/{item_id}/decision", dependencies=[analyste])
def decider_connaissance(table: Literal["documents", "repo_files"], item_id: UUID, body: KnowledgeDecision):
    if not stockage.DATABASE_URL:
        raise HTTPException(503, "Base de connaissances indisponible.")
    try:
        changed = knowledge.decide(table, item_id, body.decision, body.analyst)
    except Exception as exc:
        raise HTTPException(503, "Décision non enregistrée.") from exc
    if not changed:
        raise HTTPException(409, "Connaissance déjà traitée ou introuvable.")
    return {"status": "approved" if body.decision == "approve" else "rejected"}


@app.post("/knowledge/demo", dependencies=[passerelle])
def simuler_ajout_connaissance():
    if not stockage.DATABASE_URL:
        raise HTTPException(503, "Base de connaissances indisponible.")
    try:
        result = knowledge.plant_demo()
        for _ in range(24):
            result["status"], result["reason"] = knowledge.status("documents", result["id"])
            if result["status"] != "pending":
                break
            time.sleep(0.5)
        return result
    except Exception as exc:
        raise HTTPException(503, "Ajout de démonstration impossible.") from exc


@app.post("/events", dependencies=[passerelle])
def recevoir_evenements(lot: LotEvenements):
    # Les secrets sont masqués AVANT d'entrer dans le pipeline : ni l'IA, ni la mémoire du pipeline, ni la base ne les voient.
    events = preparer_evenements([e.model_dump() for e in lot.events])
    incident_id = stockage.reserver_identifiant()  # numéro unique réservé tout de suite
    thread_id = nouveau_thread(incident_id)
    try:
        resultat = pipeline.invoke({"incident_id": incident_id, "thread_id": thread_id, "agent_id": lot.agent_id,
                                    "events": events}, {"configurable": {"thread_id": thread_id}})
    except Exception as erreur:
        stockage.liberer(incident_id)
        raise HTTPException(502, f"L'analyse a échoué : {type(erreur).__name__}") from erreur
    if "__interrupt__" not in resultat:
        stockage.liberer(incident_id)
        return {"incident": None, "message": "Aucun comportement suspect détecté."}
    return {"incident": Incident(**resultat["__interrupt__"][0].value)}


@app.get("/incidents", response_model=list[Incident], dependencies=[analyste])
def lister_incidents():
    return stockage.lister()


@app.get("/incidents/{incident_id}", response_model=Incident, dependencies=[analyste])
def lire_incident(incident_id: str):
    incident = stockage.lire(incident_id)
    if not incident:
        raise HTTPException(404, "Incident inconnu")
    return incident


@app.post("/incidents/{incident_id}/decision", response_model=Incident, dependencies=[analyste])
def decider(incident_id: str, decision: DecisionAnalyste):
    incident = stockage.lire(incident_id)
    if not incident:
        raise HTTPException(404, "Incident inconnu")
    if not stockage.prendre_decision(incident_id):  # une décision ne s'applique qu'une fois, même si deux clics arrivent
        raise HTTPException(409, "Une décision a déjà été prise pour cet incident")
    try:
        resultat = pipeline.invoke(Command(resume=decision.model_dump()),
                                   {"configurable": {"thread_id": incident["thread_id"]}})
    except Exception as erreur:
        stockage.rendre_decision(incident_id)
        raise HTTPException(502, f"La décision n'a pas pu être appliquée : {type(erreur).__name__}") from erreur
    return resultat["incident"]


@app.post("/incidents/{incident_id}/execution", response_model=Incident, dependencies=[passerelle])
def compte_rendu_execution(incident_id: str, compte_rendu: CompteRenduExecution):
    """La passerelle confirme (ou non) qu'elle a appliqué l'action. C'est le seul moyen de passer à « Confiné »
    quand CONFINEMENT_URL n'est pas configuré."""
    incident = stockage.lire(incident_id)
    if not incident:
        raise HTTPException(404, "Incident inconnu")
    if incident["decision"] != "approved":
        raise HTTPException(409, "L'action de cet incident n'a pas été approuvée par un analyste")
    if incident["execution"]["etat"] == "execute":
        raise HTTPException(409, "L'exécution a déjà été confirmée")
    incident["execution"] = {"etat": compte_rendu.etat, "detail": compte_rendu.detail, "horodatage": maintenant()}
    incident["status"] = "Confiné" if compte_rendu.etat == "execute" else "Approuvé, en attente d'exécution"
    stockage.enregistrer(incident)
    return incident
