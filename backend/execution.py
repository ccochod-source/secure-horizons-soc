"""Exécution réelle de l'action de confinement, une fois l'analyste d'accord.

Le backend n'invente pas un succès : il demande à la passerelle (le proxy d'Elyott) d'appliquer l'action,
et l'incident ne passe à « Confiné » que si la passerelle confirme.

- CONFINEMENT_URL défini : on envoie l'action à cette adresse (POST JSON). Réponse 2xx = action exécutée.
- CONFINEMENT_URL absent : rien n'est exécuté, l'incident reste « Approuvé, en attente d'exécution ».
  La passerelle pourra confirmer plus tard via POST /incidents/{id}/execution.
"""
import os

import httpx


def executer(incident: dict) -> dict:
    url = os.getenv("CONFINEMENT_URL", "")
    if not url:
        return {"etat": "en_attente", "detail": "Aucun connecteur de confinement configuré (CONFINEMENT_URL)."}
    demande = {"incident_id": incident["id"], "action": incident["action"]["type"],
               "cible": incident["action"]["cible"], "agent_id": incident["agentId"],
               "approuve_par": incident.get("decided_by", "")}
    try:
        reponse = httpx.post(url, json=demande, timeout=10,
                             headers={"Authorization": f"Bearer {os.getenv('CONFINEMENT_TOKEN', '')}"})
    except httpx.HTTPError as erreur:
        return {"etat": "echec", "detail": f"Passerelle injoignable : {erreur}"}
    if reponse.is_success:
        return {"etat": "execute", "detail": reponse.text[:300]}
    return {"etat": "echec", "detail": f"La passerelle a répondu {reponse.status_code} : {reponse.text[:300]}"}
