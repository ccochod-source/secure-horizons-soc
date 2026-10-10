import httpx
from .storage import DatabaseError


class Relay:
    def __init__(self, store, settings, client):
        self.store, self.settings, self.client = store, settings, client

    async def deliver(self, run_id):
        run = await self.store.get_management("run", run_id)
        if not run:
            raise LookupError("Conversation inconnue.")
        if run["metadata"]["status"] not in ("completed", "refused", "failed", "limit_reached"):
            raise ValueError("La conversation doit être terminée avant transmission.")
        events = await self.store.get_events(run_id)
        if not events:
            raise ValueError("Aucun événement enregistré.")
        agent = run["metadata"]["agent_id"]
        if not await self.store.claim_delivery(run_id, agent):
            row = await self.store.get_management("delivery", run_id)
            return row["metadata"] if row else {"status": "unknown"}
        payload = {"agent_id": agent, "events": [event.model_dump() for event in events]}
        headers = {"Authorization": "Bearer " + self.settings.alex_token} if self.settings.alex_token else {}
        try:
            response = await self.client.post(self.settings.alex_url + "/events", json=payload, headers=headers, timeout=45)
            response.raise_for_status()
            result = response.json()
            if not isinstance(result, dict) or "incident" not in result:
                raise ValueError("Réponse du pipeline inconnue.")
            incident = result["incident"]
            if incident is not None and (not isinstance(incident, dict) or not isinstance(incident.get("id"), str)):
                raise ValueError("Incident au format inconnu.")
        except (httpx.HTTPError, ValueError):
            details = {"detail": "Résultat de transmission incertain. Vérifier les incidents chez Alex avant toute intervention."}
            await self.store.finish_delivery(run_id, "unknown", details)
            return {"status": "unknown", **details}
        details = {"incident_id": incident["id"] if incident else None,
                   "incident": self.store.masker.clean(incident) if incident else None}
        await self.store.finish_delivery(run_id, "delivered", details)
        return {"status": "delivered", **details}
