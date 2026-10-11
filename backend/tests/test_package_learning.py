"""Boucle d'amélioration : le système propose, l'analyste applique, rien ne change seul."""

from uuid import uuid4

import httpx
import pytest

from app.main import create_app
from common.rules import MemoryRuleStore
from gateway import Gateway
from packages import LocalQuarantine, PackageReviewer
from packages.learning import KNOWN_MALICIOUS, POPULAR, REPLACEMENT_MAP, PackageLearning
from tests.test_packages import ANALYST, CLEAN, NOW, Env, FakeAuth

pytestmark = pytest.mark.anyio

GOOD = {"authorization": "Bearer good"}


@pytest.fixture
def anyio_backend():
    return "asyncio"


class LearningEnv(Env):
    def __init__(self, tmp_path):
        super().__init__(tmp_path)
        self.rules = MemoryRuleStore()
        self.learning = PackageLearning(self.rules, self.store)
        self.reviewer = PackageReviewer(
            self.store, self.events, self.pseudonymizer, self.client,
            LocalQuarantine(self.quarantine_dir), self.installs, learning=self.learning, now=lambda: NOW)
        self.store.analysts[ANALYST] = {"user_id": ANALYST, "can_approve_packages": True}
        self.registry.add_pypi("requests", "2.32.0", CLEAN)
        self.outsider = str(uuid4())
        self.app = create_app(
            gateway=Gateway(self.events, self.pseudonymizer, packages=self.reviewer), packages=self.reviewer,
            analyst_auth=FakeAuth({"good": ANALYST, "outsider": self.outsider}), learning=self.learning)

    def http(self):
        return httpx.AsyncClient(transport=httpx.ASGITransport(app=self.app), base_url="http://test")

    async def fresh_request(self, ecosystem, name):
        """Même demande dans une nouvelle conversation, avec le compte des appels au registre."""
        from gateway.session import Session
        self.session = Session(agent_id="DevBot")
        before = len(self.registry.requests)
        outcome = await self.request(ecosystem, name)
        return outcome, len(self.registry.requests) - before

    async def decide(self, http, outcome, **body):
        response = await http.post(f"/packages/{outcome['review_id']}/decision", json=body, headers=GOOD)
        assert response.status_code == 200, response.text
        return response.json()


@pytest.fixture
def env(tmp_path):
    return LearningEnv(tmp_path)


async def test_rejection_proposes_a_rule_that_changes_nothing_until_applied(env):
    async with env.http() as http:
        first = await env.request("pypi", "ghostpkg")
        decided = await env.decide(http, first, decision="reject")

        assert [(r["kind"], r["value"], r["status"], r["version"]) for r in decided["rule_proposals"]] == [
            (KNOWN_MALICIOUS, {"ecosystem": "pypi", "name": "ghostpkg"}, "proposed", None)]
        assert await env.learning.active_rules(KNOWN_MALICIOUS) == []
        assert await env.rules.current_version() == 0

        again, lookups = await env.fresh_request("pypi", "ghostpkg")
        # Comportement inchangé : analyse complète, puis attente d'un analyste.
        assert again["status"] == "blocked_pending_review" and lookups > 0
        assert env.codes(again) == {"package_not_found"}


async def test_applied_rule_blocks_at_once_and_rollback_restores_the_full_analysis(env):
    async with env.http() as http:
        rule_id = (await env.decide(http, await env.request("pypi", "ghostpkg"), decision="reject")
                   )["rule_proposals"][0]["id"]

        applied = await http.post(f"/rules/package/{rule_id}/apply", headers=GOOD)
        assert applied.status_code == 200
        assert (applied.json()["rule"]["status"], applied.json()["rule"]["version"],
                applied.json()["rule"]["decided_by"], applied.json()["current_version"]) == (
            "active", 1, ANALYST, 1)

        blocked, lookups = await env.fresh_request("pypi", "ghostpkg")
        assert blocked["status"] == "blocked" and lookups == 0  # arrêté avant tout appel au registre
        assert blocked["reason"] == "Bloqué par règle apprise v1."
        review = env.review(blocked)
        assert (review["state"], review["decided_by"]) == ("rejected", "regle_apprise_v1")
        assert env.codes(blocked) == {"known_malicious"} and review["checks"]["blocking"] is True
        assert env.installs.calls == [] and env.event_types()[-1] == ("package_review", "blocked")
        # Un blocage par règle n'est pas une décision d'analyste : il ne propose rien.
        assert await env.learning.propose(review["id"]) == []
        assert (await http.post(f"/rules/package/{rule_id}/apply", headers=GOOD)).status_code == 409

        rolled = await http.post(f"/rules/package/{rule_id}/rollback", headers=GOOD)
        assert rolled.status_code == 200 and rolled.json()["current_version"] == 2
        assert rolled.json()["rule"]["status"] == "rolled_back"
        assert len(env.rules.rules) == 1  # la ligne reste, rien n'est supprimé

        after, lookups = await env.fresh_request("pypi", "ghostpkg")
        assert after["status"] == "blocked_pending_review" and lookups > 0
        assert env.codes(after) == {"package_not_found"}
        assert (await http.post(f"/rules/package/{rule_id}/rollback", headers=GOOD)).status_code == 409
        assert (await http.post("/rules/package/999/apply", headers=GOOD)).status_code == 404


async def test_rule_routes_refuse_a_missing_or_invalid_token(env):
    async with env.http() as http:
        rule_id = (await env.decide(http, await env.request("pypi", "ghostpkg"), decision="reject")
                   )["rule_proposals"][0]["id"]
        for method, url in (("GET", "/rules/proposals"), ("POST", f"/rules/package/{rule_id}/apply"),
                            ("POST", f"/rules/package/{rule_id}/rollback")):
            assert (await http.request(method, url)).status_code == 401
            assert (await http.request(method, url, headers={"authorization": "Bearer forged"})).status_code == 401
            assert (await http.request(method, url, headers={"authorization": "Bearer outsider"})).status_code == 403
        assert env.rules.rules[0]["status"] == "proposed" and await env.rules.current_version() == 0

        listed = (await http.get("/rules/proposals", headers=GOOD)).json()
        assert listed["current_version"] == 0 and listed["active"] == []
        assert [r["id"] for r in listed["proposed"]] == [rule_id]


async def test_approval_creates_no_rule(env):
    async with env.http() as http:
        env.registry.add_pypi("reqeusts", "1.0.0", CLEAN)
        outcome = await env.request("pypi", "reqeusts")
        decided = await env.decide(http, outcome, decision="approve")

        assert decided["state"] == "executed" and decided["rule_proposals"] == []
        assert env.rules.rules == []
        # Aucune liste « sûre » : la même demande repasse par l'analyse et attend un analyste.
        again, _ = await env.fresh_request("pypi", "reqeusts")
        assert again["status"] == "blocked_pending_review"


async def test_rejected_typosquat_proposes_the_block_and_the_missing_popular_target(env):
    # « acmelib » n'est dans la liste de comparaison que par une règle apprise active.
    seed = await env.rules.propose(POPULAR, {"ecosystem": "pypi", "name": "acmelib"}, uuid4())
    await env.rules.apply(seed["id"], ANALYST)
    env.registry.add_pypi("acmelibb", "1.0.0", CLEAN)
    async with env.http() as http:
        outcome = await env.request("pypi", "acmelibb")
        assert env.codes(outcome) == {"typosquat"}
        assert env.review(outcome)["checks"]["suggested_replacement"] == "acmelib"

        await env.rules.rollback(seed["id"], ANALYST)  # la cible n'est plus dans la liste
        decided = await env.decide(http, outcome, decision="reject")
        assert [(r["kind"], r["value"]["name"]) for r in decided["rule_proposals"]] == [
            (KNOWN_MALICIOUS, "acmelibb"), (POPULAR, "acmelib")]

        # Cible déjà dans la liste écrite à la main : seule la règle de blocage est proposée.
        other = await env.fresh_request("pypi", "reqeusts")
        decided = await env.decide(http, other[0], decision="reject")
        assert [(r["kind"], r["value"]["name"]) for r in decided["rule_proposals"]] == [
            (KNOWN_MALICIOUS, "reqeusts")]


async def test_replacing_a_hallucinated_name_proposes_a_mapping_shown_as_suggestion(env):
    async with env.http() as http:
        outcome = await env.request("pypi", "fastjsonparse")
        decided = await env.decide(http, outcome, decision="replace", replacement={"name": "requests"})
        assert [(r["kind"], r["value"]) for r in decided["rule_proposals"]] == [
            (REPLACEMENT_MAP, {"ecosystem": "pypi", "from": "fastjsonparse", "to": "requests"})]
        rule_id = decided["rule_proposals"][0]["id"]

        before, _ = await env.fresh_request("pypi", "fastjsonparse")
        assert env.review(before)["checks"]["suggested_replacement"] is None
        await env.decide(http, before, decision="reject")

        assert (await http.post(f"/rules/package/{rule_id}/apply", headers=GOOD)).status_code == 200
        after, _ = await env.fresh_request("pypi", "fastjsonparse")
        checks = env.review(after)["checks"]
        # La correspondance est une suggestion : le package attend toujours un analyste.
        assert after["status"] == "blocked_pending_review"
        assert (checks["recommended_decision"], checks["suggested_replacement"]) == ("replace", "requests")
        assert checks["learned_replacement"]["rule_id"] == rule_id


async def test_identical_proposals_are_not_duplicated(env):
    async with env.http() as http:
        first = await env.decide(http, await env.request("pypi", "ghostpkg"), decision="reject")
        second = await env.decide(http, (await env.fresh_request("pypi", "ghostpkg"))[0], decision="reject")
        assert len(first["rule_proposals"]) == 1 and second["rule_proposals"] == []

        await http.post(f"/rules/package/{first['rule_proposals'][0]['id']}/apply", headers=GOOD)
        assert await env.rules.propose(KNOWN_MALICIOUS, {"ecosystem": "pypi", "name": "ghostpkg"}, uuid4()) is None
        assert len(env.rules.rules) == 1


async def test_proposals_only_come_from_a_known_analyst_and_never_target_a_popular_package(env):
    outcome = await env.request("pypi", "ghostpkg")
    review_id = env.review(outcome)["id"]
    assert await env.learning.propose(review_id) == []  # pas encore de décision

    await env.reviewer.decide(review_id, "reject", decided_by=str(uuid4()))  # identité inconnue
    assert await env.learning.propose(review_id) == []

    # Un package répandu rejeté ponctuellement ne devient pas une règle de blocage.
    env.registry.vulns["requests"] = [{"id": "OSV-1", "database_specific": {"severity": "CRITICAL"}}]
    popular, _ = await env.fresh_request("pypi", "requests")
    assert popular["status"] == "blocked_pending_review"
    await env.reviewer.decide(env.review(popular)["id"], "reject", decided_by=ANALYST)
    assert await env.learning.propose(env.review(popular)["id"]) == []
    assert env.rules.rules == []


async def test_unreadable_rules_fall_back_to_the_full_analysis(env):
    async def broken(kind):
        raise RuntimeError("table absente")

    env.rules.active = broken
    outcome, lookups = await env.fresh_request("pypi", "ghostpkg")
    assert outcome["status"] == "blocked_pending_review" and lookups > 0
