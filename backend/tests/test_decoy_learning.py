"""Boucle des leurres : un verdict d'analyste propose, un analyste applique, le semeur suit."""

from uuid import uuid4

import httpx
import pytest

from app.main import create_app
from common.rules import MemoryRuleStore, RulesetVersion
from decoys import Seeder
from decoys.learning import NEW_DECOY_LOCATION, DecoyLearning
from packages import MemoryReviewStore
from packages.learning import PackageLearning
from tests.test_decoys import Env
from tests.test_packages import ANALYST, FakeAuth

pytestmark = pytest.mark.anyio

GOOD = {"authorization": "Bearer good"}


@pytest.fixture
def anyio_backend():
    return "asyncio"


class Reviews:
    """Ce que les routes lisent du contrôle des packages : l'annuaire des analystes."""

    def __init__(self):
        self.store = MemoryReviewStore()
        self.store.analysts[ANALYST] = {"user_id": ANALYST, "can_approve_packages": True}


@pytest.fixture
async def env():
    env = Env()
    await env.start()
    version = RulesetVersion()  # compteur partagé entre les deux listes, comme ruleset_meta
    env.rules = MemoryRuleStore(version)
    env.learning = DecoyLearning(env.rules, env.store)
    reviews = Reviews()
    env.package_rules = MemoryRuleStore(version)
    env.app = create_app(
        gateway=env.gateway, packages=reviews, analyst_auth=FakeAuth({"good": ANALYST, "outsider": str(uuid4())}),
        learning=PackageLearning(env.package_rules, reviews.store), decoy_learning=env.learning)
    return env


async def attack(env):
    """Un agent lit le leurre backup.key : l'alerte critique est levée."""
    session = env.gateway.open_session("DevBot")
    await env.gateway.record_query(session, "récupère la clé de sauvegarde")
    await env.gateway.dispatch(session, "read_file", {"path": "backup.key"})
    assert session.diverted
    return env.store.alerts[-1]["id"]


def http(env):
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=env.app), base_url="http://test")


async def test_verdict_requires_an_authenticated_analyst_and_records_who_gave_it(env):
    alert_id = await attack(env)
    url, body = f"/alerts/{alert_id}/verdict", {"verdict": "confirmed"}
    async with http(env) as client:
        assert (await client.post(url, json=body)).status_code == 401
        assert (await client.post(url, json=body, headers={"authorization": "Bearer forged"})).status_code == 401
        assert (await client.post(url, json=body, headers={"authorization": "Bearer outsider"})).status_code == 403
        assert env.store.alerts[-1]["analyst_verdict"] is None and env.rules.rules == []
        assert (await client.post(url, json={"verdict": "maybe"}, headers=GOOD)).status_code == 422

        ok = await client.post(url, json=body, headers=GOOD)
        assert ok.status_code == 200 and ok.json()["decided_by"] == ANALYST
        assert (env.store.alerts[-1]["analyst_verdict"], str(env.store.alerts[-1]["analyst_verdict_by"])) == (
            "confirmed", ANALYST)
        assert (await client.post(url, json=body, headers=GOOD)).status_code == 409
        assert (await client.post(f"/alerts/{uuid4()}/verdict", json=body, headers=GOOD)).status_code == 404


async def test_confirmed_attack_proposes_a_nearby_lure_sown_only_once_applied(env):
    alert_id = await attack(env)
    async with http(env) as client:
        result = (await client.post(f"/alerts/{alert_id}/verdict", json={"verdict": "confirmed"},
                                    headers=GOOD)).json()
        [rule] = result["rule_proposals"]
        assert (rule["kind"], rule["status"], rule["list"]) == (NEW_DECOY_LOCATION, "proposed", "decoy")
        assert rule["value"] == {
            "decoy_type": "honeytoken_key", "near": "HONEYTOKEN_002",
            "near_location": "repo:infra-tools/backup.key", "location": "repo:infra-tools/backup.key.old"}

        # Proposée seulement : le semis suivant ne plante rien de plus.
        report = await Seeder(env.store, rules=env.rules).seed()
        assert report.planted == [] and len(env.store.files) == 3

        applied = await client.post(f"/rules/decoy/{rule['id']}/apply", headers=GOOD)
        assert applied.status_code == 200 and applied.json()["rule"]["version"] == 1
        report = await Seeder(env.store, rules=env.rules).seed()
        assert report.planted == ["HONEYTOKEN_R001"]
        planted = env.file("backup.key.old")
        assert planted.repository == "infra-tools" and "BACKUP_ENCRYPTION_SECRET=" in planted.content
        assert planted.content != env.file("backup.key").content  # valeur neuve, fabriquée au semis
        row = env.row("HONEYTOKEN_R001")
        assert (row.decoy_type, row.location) == ("honeytoken_key", "repo:infra-tools/backup.key.old")

        # Le détecteur reconnaît le nouveau leurre après rechargement.
        await env.detector.load()
        session = env.gateway.open_session("DevBot")
        await env.gateway.record_query(session, "et l'ancienne clé ?")
        await env.gateway.dispatch(session, "read_file", {"path": "backup.key.old"})
        assert session.diverted

        listed = (await client.get("/rules/proposals", headers=GOOD)).json()
        assert [(r["list"], r["id"]) for r in listed["active"]] == [("decoy", rule["id"])]

        rolled = await client.post(f"/rules/decoy/{rule['id']}/rollback", headers=GOOD)
        assert rolled.json()["current_version"] == 2 and len(env.rules.rules) == 1
        assert await env.package_rules.current_version() == 2  # même compteur que les packages
        # Annulée : la règle n'est plus semée ; le leurre déjà planté n'est pas supprimé.
        assert (await Seeder(env.store, rules=env.rules).seed()).planted == []
        assert env.file("backup.key.old") is planted


async def test_false_positive_creates_no_rule(env):
    alert_id = await attack(env)
    async with http(env) as client:
        result = await client.post(f"/alerts/{alert_id}/verdict", json={"verdict": "false_positive"},
                                   headers=GOOD)
    assert result.status_code == 200 and result.json()["rule_proposals"] == []
    assert env.rules.rules == [] and env.store.alerts[-1]["analyst_verdict"] == "false_positive"


async def test_no_proposal_without_a_recorded_verdict_and_no_duplicate(env):
    first = await attack(env)
    assert await env.learning.propose(first) == []  # alerte sans verdict : rien
    second = await attack(env)
    async with http(env) as client:
        for alert_id, expected in ((first, 1), (second, 0)):
            result = await client.post(f"/alerts/{alert_id}/verdict", json={"verdict": "confirmed"},
                                       headers=GOOD)
            assert len(result.json()["rule_proposals"]) == expected
    assert len(env.rules.rules) == 1


async def test_unreadable_rules_do_not_prevent_seeding_the_handwritten_lures(env):
    async def broken(kind):
        raise RuntimeError("table absente")

    env.rules.active = broken
    report = await Seeder(env.store, rules=env.rules).seed()
    assert len(report.existing) == 6 and report.planted == []
