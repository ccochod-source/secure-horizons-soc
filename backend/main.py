"""Le serveur du backend : c'est lui que l'interface et l'agent d'Elyott appellent.

Lancer :  uvicorn main:app --reload --port 8000
Puis ouvrir http://localhost:8000/docs pour tester chaque route à la main.

POST /events                    reçoit les événements d'un agent -> crée un incident si la règle se déclenche
GET  /incidents                 liste des incidents (le plus récent d'abord)
GET  /incidents/{id}            un incident
POST /incidents/{id}/decision   l'analyste approuve ou refuse l'action proposée
"""
import os

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from langgraph.types import Command

import stockage
from formats import DecisionAnalyste, Incident, LotEvenements
from pipeline import construire_pipeline

load_dotenv()
app = FastAPI(title="TRACE — backend")
app.add_middleware(CORSMiddleware, allow_origins=[os.getenv("FRONTEND_ORIGIN", "http://localhost:3100")],
                   allow_methods=["*"], allow_headers=["*"])
pipeline = construire_pipeline()


@app.get("/health")
def sante():
    return {"ok": True}


@app.post("/events")
def recevoir_evenements(lot: LotEvenements):
    incident_id = stockage.nouvel_identifiant()
    config = {"configurable": {"thread_id": incident_id}}
    resultat = pipeline.invoke({"incident_id": incident_id, "agent_id": lot.agent_id,
                                "events": [e.model_dump() for e in lot.events]}, config)
    if "__interrupt__" not in resultat:
        return {"incident": None, "message": "Aucun comportement suspect détecté."}
    return {"incident": Incident(**resultat["__interrupt__"][0].value)}


@app.get("/incidents", response_model=list[Incident])
def lister_incidents():
    return stockage.lister()


@app.get("/incidents/{incident_id}", response_model=Incident)
def lire_incident(incident_id: str):
    incident = stockage.lire(incident_id)
    if not incident:
        raise HTTPException(404, "Incident inconnu")
    return incident


@app.post("/incidents/{incident_id}/decision", response_model=Incident)
def decider(incident_id: str, decision: DecisionAnalyste):
    incident = stockage.lire(incident_id)
    if not incident:
        raise HTTPException(404, "Incident inconnu")
    if incident["decision"] != "pending":  # une décision ne s'applique qu'une fois
        raise HTTPException(409, "Une décision a déjà été prise pour cet incident")
    config = {"configurable": {"thread_id": incident_id}}
    resultat = pipeline.invoke(Command(resume=decision.model_dump()), config)
    return resultat["incident"]
