"""Tests for the current read-only RAG assistant and its trace relay."""
import json
import uuid

import httpx
from fastapi.testclient import TestClient

from victim_agent.app import create_app
from victim_agent.config import FAKE_SECRETS, Settings
from victim_agent.models import RAGChatRequest
from victim_agent.relay import Relay
from victim_agent.runtime import RAGAssistant
from victim_agent.security import Masker


class MemoryStore:
    def __init__(self, documents=None):
        self.documents = documents or []
        self.events = []
        self.masker = Masker()

    async def health(self):
        return None

    async def search_documents(self, question):
        self.question = question
        return self.documents

    async def append_events(self, events, agent_id, conversation_id):
        self.events.extend(events)


class Answerer:
    async def answer(self, question, documents):
        return "La procédure est documentée [D1]."


def settings():
    return Settings(
        supabase_url="https://test.supabase.co", supabase_key="test-key", openai_key="",
        model="test-model", gateway_token="g" * 32, confinement_token="c" * 32,
        alex_url="http://127.0.0.1:8000", alex_token="p" * 32,
    )


def test_rag_logs_causal_trace_and_relays_the_exact_contract():
    received = []

    def handler(request):
        assert request.url.path == "/events"
        assert request.headers["Authorization"] == "Bearer " + "p" * 32
        body = json.loads(request.content)
        received.append(body)
        return httpx.Response(200, json={"incident": None, "message": "Aucun comportement suspect détecté."})

    async def scenario():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            store = MemoryStore([{
                "id": str(uuid.uuid4()), "title": "Revue de code", "doc_type": "procedure",
                "source": "review.md", "content": "Une revue nécessite deux approbations.",
            }])
            relay = Relay(store, settings(), client)
            assistant = RAGAssistant(store, settings(), client, Answerer(), relay)
            result = await assistant.chat(RAGChatRequest(question="Comment faire une revue ?"))
            return store, result

    import asyncio
    store, result = asyncio.run(scenario())
    assert result["documents_found"] == 1
    assert result["sources"][0]["title"] == "Revue de code"
    assert result["pipeline_delivery"] == {"status": "delivered", "incident_id": None}
    assert len(store.events) == 3
    batch = received[0]
    assert batch["agent_id"] == "dev-01"
    assert [set(event) for event in batch["events"]] == [
        {"id", "parent_event_id", "timestamp", "actor", "type", "title", "description", "tool", "resource", "result"}
    ] * 3
    assert batch["events"][1]["parent_event_id"] == batch["events"][0]["id"]
    assert batch["events"][2]["parent_event_id"] == batch["events"][1]["id"]
    assert all(event["result"] in {"allowed", "blocked", "flagged"} for event in batch["events"])


def test_fake_credentials_are_masked_before_trace_relay():
    received = []

    def handler(request):
        received.append(request.content.decode())
        return httpx.Response(200, json={"incident": None})

    async def scenario():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            store = MemoryStore()
            relay = Relay(store, settings(), client)
            from victim_agent.storage import new_event
            event = new_event(parent=None, actor="user", kind="user_request", title="Question",
                              description="clé=" + FAKE_SECRETS[0], tool="rag.chat", resource="knowledge-base")
            return await relay.deliver_events([event], "dev-01")

    import asyncio
    assert asyncio.run(scenario())["status"] == "delivered"
    assert FAKE_SECRETS[0] not in received[0]
    assert "SECRET_001" in received[0]


def test_uncertain_pipeline_post_is_not_retried():
    calls = []

    def timeout(request):
        calls.append(request)
        raise httpx.ReadTimeout("unconfirmed", request=request)

    async def scenario():
        async with httpx.AsyncClient(transport=httpx.MockTransport(timeout)) as client:
            relay = Relay(MemoryStore(), settings(), client)
            from victim_agent.storage import new_event
            event = new_event(parent=None, actor="user", kind="user_request", title="Question",
                              description="bonjour", tool="rag.chat", resource="knowledge-base")
            return await relay.deliver_events([event], "dev-01")

    import asyncio
    assert asyncio.run(scenario()) == {"status": "unknown"}
    assert len(calls) == 1


def test_http_chat_is_authenticated_and_reports_pipeline_delivery():
    def handler(request):
        return httpx.Response(200, json={"incident": None})

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    store = MemoryStore()
    app = create_app(settings(), store, client, Answerer())
    with TestClient(app) as browser:
        assert browser.get("/health").status_code == 401
        headers = {"Authorization": "Bearer " + "g" * 32}
        assert browser.get("/health", headers=headers).json()["database_connected"] is True
        response = browser.post("/chat", headers=headers, json={"question": "bonjour"})
        assert response.status_code == 200
        assert response.json()["pipeline_delivery"]["status"] == "delivered"
    import asyncio
    asyncio.run(client.aclose())
