import httpx


class Relay:
    def __init__(self, store, settings, client):
        self.store, self.settings, self.client = store, settings, client

    async def deliver_events(self, events, agent_id):
        """Send one completed RAG trace to Alex once; never retry an uncertain POST."""
        payload = {
            "agent_id": agent_id,
            "events": [
                {
                    "id": event.id,
                    "parent_event_id": event.parent_event_id,
                    "timestamp": event.timestamp,
                    "actor": event.actor,
                    "type": event.type,
                    "title": event.title,
                    "description": self.store.masker.text(event.description),
                    "tool": event.tool,
                    "resource": self.store.masker.text(event.resource),
                    "result": event.result,
                }
                for event in events
            ],
        }
        headers = {"Authorization": "Bearer " + self.settings.alex_token} if self.settings.alex_token else {}
        try:
            response = await self.client.post(
                self.settings.alex_url + "/events", json=payload, headers=headers, timeout=12
            )
            response.raise_for_status()
            result = response.json()
            if not isinstance(result, dict) or "incident" not in result:
                raise ValueError("Réponse du pipeline inconnue.")
            incident = result["incident"]
            if incident is not None and (not isinstance(incident, dict) or not isinstance(incident.get("id"), str)):
                raise ValueError("Incident au format inconnu.")
            return {"status": "delivered", "incident_id": incident.get("id") if incident else None}
        except (httpx.HTTPError, ValueError):
            # Do not retry: a timeout can mean Alex already processed the trace.
            return {"status": "unknown"}
