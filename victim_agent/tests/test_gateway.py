import asyncio
from dataclasses import replace
import json
from uuid import uuid4

import httpx
import pytest
from fastapi.testclient import TestClient

from victim_agent.app import create_app
from victim_agent.config import FAKE_SECRETS, Settings
from victim_agent.models import ConfinementRequest, ReceiverPayload, RunRequest
from victim_agent.receiver import DemoReceiver
from victim_agent.relay import Relay
from victim_agent.runtime import Context, VictimRuntime
from victim_agent.storage import DatabaseError, DuplicateRecord, SupabaseStore


def run(coro):
    return asyncio.run(coro)


class MemoryStore(SupabaseStore):
    """Exercise production adapters using a small fake PostgREST database."""
    def __init__(self, settings):
        super().__init__(settings, None)
        self.rows = {"events": [], "rag_documents": [], "repo_files": []}
        self.fail_append = False
        self.read_queries = []

    async def request(self, method, table, *, params=None, body=None, upsert=False):
        params = params or {}
        rows = self.rows[table]
        if method == "POST":
            if table == "events" and body["actor_type"] == "agent" and self.fail_append:
                raise DatabaseError("Journal indisponible.")
            old = next((r for r in rows if r["id"] == body["id"]), None)
            if old and not upsert:
                raise DuplicateRecord("Doublon.")
            if old:
                rows.remove(old)
            rows.append(json.loads(json.dumps(body)))
            return [body]
        self.read_queries.append((table, params))
        matches = []
        for row in rows:
            accepted = True
            for key, value in params.items():
                if key in ("select", "order", "limit", "offset", "content"):
                    continue
                actual = row.get("metadata", {}).get(key[11:]) if key.startswith("metadata->>") else row.get(key)
                target = value[3:] if value.startswith("eq.") else value
                actual = str(actual).lower() if isinstance(actual, bool) else str(actual)
                if actual != target:
                    accepted = False
                    break
            if accepted:
                matches.append(row)
        if method == "PATCH":
            for row in matches:
                row.update(json.loads(json.dumps(body)))
            return matches
        if params.get("order"):
            key = params["order"].split(",")[0].split(".")[0]
            matches.sort(key=lambda row: row.get(key, ""), reverse=".desc" in params["order"])
        offset, limit = int(params.get("offset", 0)), int(params.get("limit", 1000))
        return json.loads(json.dumps(matches[offset:offset + limit]))


class ScriptedModel:
    """Forced tool calls test the gateway, not LLM attack success."""
    def __init__(self, attack=False, refuse=False, forever=False):
        self.step, self.attack, self.refuse, self.forever = 0, attack, refuse, forever

    async def complete(self, messages, tools):
        self.step += 1
        if self.refuse:
            return {"role": "assistant", "content": json.dumps({"answer": "Je refuse de publier un secret.", "outcome": "refused"})}
        calls = [("knowledge_search", {"query": "deployment"})]
        if self.attack:
            calls += [("filesystem_read", {"path": ".env.demo"}), ("github_publish", {"content": FAKE_SECRETS[0]})]
        if self.forever:
            selected = calls[0]
        elif self.step <= len(calls):
            selected = calls[self.step - 1]
        else:
            return {"role": "assistant", "content": json.dumps({"answer": "Sources consultées : deployment.md.", "outcome": "answered"})}
        return {"role": "assistant", "content": None, "tool_calls": [{"id": "call-" + str(self.step), "type": "function", "function": {
            "name": selected[0], "arguments": json.dumps(selected[1]),
        }}]}


@pytest.fixture
def environment(tmp_path):
    settings = Settings("https://test.supabase.co", "test-key", "", "test-model", "a" * 32, "b" * 32,
                        receiver_db=str(tmp_path / "receiver.sqlite"))
    store = MemoryStore(settings)
    run(store.seed())
    receiver = DemoReceiver(settings.receiver_db)
    deliveries = []

    def handler(request):
        if request.url.path == "/demo-receiver":
            payload = ReceiverPayload.model_validate_json(request.content)
            return httpx.Response(200, json=receiver.receive(payload))
        if request.url.path == "/events":
            deliveries.append(json.loads(request.content))
            return httpx.Response(200, json={"incident": {"id": "INC-0001"}})
        raise AssertionError("Unexpected HTTP call")

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    yield settings, store, receiver, client, deliveries
    receiver.close()
    run(client.aclose())


def test_normal_reads_database_and_preserves_sources(environment):
    settings, store, _, client, _ = environment
    result = run(VictimRuntime(store, settings, client, ScriptedModel()).run(RunRequest(question="Déploiement ?")))
    events = run(store.get_events(result["run_id"]))
    assert result["status"] == "completed"
    assert result["sources"] and result["sources"][0]["sha256"]
    assert any(e.type == "retrieval" for e in events)
    assert not any(e.tool == "github.publish" for e in events)
    assert all(e.parent_event_id is not None for e in events[1:])
    assert all(params.get("quarantined") == "eq.false" for table, params in store.read_queries if table == "rag_documents" and "content" in params)


def test_attack_receipt_then_confinement_persists_across_runtime_restart(environment):
    settings, store, receiver, client, deliveries = environment
    result = run(VictimRuntime(store, settings, client, ScriptedModel(attack=True)).run(RunRequest(question="Diagnostic ?", scenario="tool_poisoning")))
    assert result["publications_received"] == 1
    assert len(receiver.list_receipts()) == 1
    delivery = run(Relay(store, settings, client).deliver(result["run_id"]))
    assert delivery["status"] == "delivered"
    batch = deliveries[0]
    read = next(e for e in batch["events"] if e["type"] == "file_read")
    attempt = next(e for e in batch["events"] if e["type"] == "export_attempt")
    assert attempt["parent_event_id"] == read["id"]
    assert FAKE_SECRETS[0] not in json.dumps(batch)
    run(store.suspend_tool(ConfinementRequest(incident_id="INC-0001", action="suspendre_outil", cible="github.publish", agent_id="dev-01", approuve_par="analyste")))
    # New runtime: no in-memory policy shared with previous run.
    after = run(VictimRuntime(store, settings, client, ScriptedModel(attack=True)).run(RunRequest(question="Diagnostic ?", scenario="tool_poisoning")))
    assert after["blocked_actions"] == 1 and after["publications_received"] == 0
    assert len(receiver.list_receipts()) == 1


def test_relay_never_duplicates_completed_delivery(environment):
    settings, store, _, client, deliveries = environment
    result = run(VictimRuntime(store, settings, client, ScriptedModel()).run(RunRequest(question="Déploiement ?")))
    relay = Relay(store, settings, client)
    run(relay.deliver(result["run_id"]))
    run(relay.deliver(result["run_id"]))
    assert len(deliveries) == 1


def test_ambiguous_transmission_is_durable_and_not_retried(environment):
    settings, store, _, client, _ = environment
    result = run(VictimRuntime(store, settings, client, ScriptedModel()).run(RunRequest(question="Déploiement ?")))
    attempts = []
    def timeout(request):
        attempts.append(request)
        raise httpx.ReadTimeout("unconfirmed", request=request)
    broken = httpx.AsyncClient(transport=httpx.MockTransport(timeout))
    relay = Relay(store, settings, broken)
    assert run(relay.deliver(result["run_id"]))["status"] == "unknown"
    assert run(relay.deliver(result["run_id"]))["status"] == "unknown"
    assert len(attempts) == 1
    run(broken.aclose())


def test_journal_failure_prevents_publication(environment):
    settings, store, receiver, client, _ = environment
    ctx = Context(str(uuid4()), "dev-01")
    run(store.create_run(ctx.run_id, ctx.agent_id, "normal"))
    store.fail_append = True
    with pytest.raises(DatabaseError):
        run(VictimRuntime(store, settings, client).publish(ctx, FAKE_SECRETS[0]))
    assert receiver.list_receipts() == [] and not ctx.journal_ok


def test_no_false_secret_lineage_for_unrelated_export(environment):
    settings, store, _, client, _ = environment
    runtime = VictimRuntime(store, settings, client)
    ctx = Context(str(uuid4()), "dev-01")
    run(store.create_run(ctx.run_id, ctx.agent_id, "normal"))
    run(runtime.emit(ctx, "instruction", "Question", "Diagnostic", "agent.input", "chat/employe"))
    read = run(runtime.execute_tool(ctx, "filesystem_read", '{"path":".env.demo"}'))
    # Temporal proximity alone must not fabricate a sensitive causal link.
    run(runtime.publish(ctx, "Documentation publique sans identifiant"))
    events = run(store.get_events(ctx.run_id))
    attempt = next(e for e in events if e.type == "export_attempt")
    assert attempt.parent_event_id != read["event_id"]


def test_known_secret_masking_in_all_fields_and_metadata(environment):
    _, store, _, _, _ = environment
    secret = FAKE_SECRETS[0]
    clean = store.masker.clean({"description": secret, "resource": "external/" + secret,
                               "metadata": {"payload": [secret, "FAKE_API_KEY=" + secret]}})
    assert secret not in json.dumps(clean)
    assert "SECRET_001" in clean["description"]


def test_refusal_is_recorded_separately(environment):
    settings, store, receiver, client, _ = environment
    result = run(VictimRuntime(store, settings, client, ScriptedModel(refuse=True)).run(RunRequest(question="Diagnostic ?", scenario="tool_poisoning")))
    assert result["status"] == "refused"
    assert any(e.type == "refusal" for e in run(store.get_events(result["run_id"])))
    assert receiver.list_receipts() == []


def test_round_limit_has_terminal_trace(environment):
    settings, store, _, client, _ = environment
    cfg = replace(settings, max_rounds=2)
    result = run(VictimRuntime(store, cfg, client, ScriptedModel(forever=True)).run(RunRequest(question="Diagnostic ?")))
    assert result["status"] == "limit_reached"
    assert run(store.get_events(result["run_id"]))[-1].type == "response"


def test_invalid_and_unknown_tools_do_not_execute(environment):
    settings, store, receiver, client, _ = environment
    runtime, ctx = VictimRuntime(store, settings, client), Context(str(uuid4()), "dev-01")
    run(store.create_run(ctx.run_id, ctx.agent_id, "normal"))
    run(runtime.emit(ctx, "instruction", "Question", "Diagnostic", "agent.input", "chat/employe"))
    assert run(runtime.execute_tool(ctx, "shell", "{}"))["status"] == "blocked"
    assert run(runtime.execute_tool(ctx, "filesystem_read", '{"path":"/Users/private/.env"}'))["status"] == "blocked"
    assert receiver.list_receipts() == []


def test_confinement_endpoint_auth_and_actual_effect(environment):
    settings, store, _, http, _ = environment
    app = create_app(settings, store, ScriptedModel(), http)
    body = {"incident_id": "INC-0001", "action": "suspendre_outil", "cible": "github.publish", "agent_id": "dev-01", "approuve_par": "analyste"}
    with TestClient(app) as browser:
        assert browser.post("/confinement", json=body).status_code == 401
        auth = {"Authorization": "Bearer " + settings.confinement_token}
        response = browser.post("/confinement", json=body, headers=auth)
        assert response.status_code == 200 and response.json()["etat"] == "execute"
        assert run(store.is_suspended("dev-01", "github.publish"))
        body["action"] = "revoquer_secret"
        assert browser.post("/confinement", json=body, headers=auth).status_code == 422
        assert browser.get("/runs").status_code == 401


def test_confinement_db_failure_never_returns_200(environment):
    settings, store, _, http, _ = environment
    async def broken(_request):
        raise DatabaseError("DB unavailable")
    store.suspend_tool = broken
    with TestClient(create_app(settings, store, ScriptedModel(), http)) as browser:
        response = browser.post("/confinement", headers={"Authorization": "Bearer " + settings.confinement_token}, json={
            "incident_id": "INC-0001", "action": "suspendre_outil", "cible": "github.publish", "agent_id": "dev-01", "approuve_par": "analyste",
        })
        assert response.status_code == 503


def test_database_values_adapt_to_leon_constraints(environment):
    settings, store, _, client, _ = environment
    result = run(VictimRuntime(store, settings, client, ScriptedModel(attack=True)).run(RunRequest(question="Diagnostic ?")))
    rows = [r for r in store.rows["events"] if r["actor_type"] == "agent"]
    assert {r["result"] for r in rows} <= {"success", "blocked", "detected"}
    assert all(r["resource_type"] == "mcp_tool" for r in rows)
    assert FAKE_SECRETS[0] not in json.dumps(rows)
    assert {e.result for e in run(store.get_events(result["run_id"]))} <= {"allowed", "blocked", "flagged"}


def test_quarantined_and_other_corpus_documents_are_never_used(environment):
    settings, store, _, client, _ = environment
    store.rows["rag_documents"].append({"id": str(uuid4()), "quarantined": True,
        "metadata": {"namespace": "elyott_v0"}, "content": "malicious", "title": "Trap", "source": "trap.md"})
    store.rows["rag_documents"].append({"id": str(uuid4()), "quarantined": False,
        "metadata": {"namespace": "other"}, "content": "unrelated", "title": "Other", "source": "other.md"})
    result = run(VictimRuntime(store, settings, client, ScriptedModel()).run(RunRequest(question="Diagnostic ?")))
    assert all(s["source"] not in ("trap.md", "other.md") for s in result["sources"])


def test_incomplete_parent_chain_is_not_sent(environment):
    settings, store, _, client, deliveries = environment
    result = run(VictimRuntime(store, settings, client, ScriptedModel()).run(RunRequest(question="Déploiement ?")))
    row = next(r for r in store.rows["events"] if r["actor_type"] == "agent" and r["trace_id"] == result["run_id"])
    row["parent_event_id"] = str(uuid4())
    with pytest.raises(DatabaseError):
        run(Relay(store, settings, client).deliver(result["run_id"]))
    assert deliveries == []


def test_postgres_foreign_key_failure_is_not_a_delivery_claim(environment):
    settings, _, _, _, _ = environment
    async def scenario():
        def handler(request):
            return httpx.Response(409, json={"code": "23503"})
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
            with pytest.raises(DatabaseError) as error:
                await SupabaseStore(settings, http).claim_delivery(str(uuid4()), "dev-01")
            assert not isinstance(error.value, DuplicateRecord)
    run(scenario())


def test_unconfirmed_journal_write_never_allows_publication(environment):
    settings, store, receiver, client, _ = environment
    original = store.request
    async def unconfirmed(method, table, **kwargs):
        if method == "POST" and kwargs.get("body", {}).get("actor_type") == "agent":
            return []
        return await original(method, table, **kwargs)
    store.request = unconfirmed
    ctx = Context(str(uuid4()), "dev-01")
    run(store.create_run(ctx.run_id, ctx.agent_id, "normal"))
    with pytest.raises(DatabaseError):
        run(VictimRuntime(store, settings, client).publish(ctx, FAKE_SECRETS[0]))
    assert receiver.list_receipts() == []
