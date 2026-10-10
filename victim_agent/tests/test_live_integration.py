"""Opt-in: actual Supabase + gateway HTTP + Alex backend, scripted victim LLM.

RUN_LIVE_TESTS=1 TRACE_TEST_ALEX_URL=http://127.0.0.1:18000 python -m pytest
    victim_agent/tests/test_live_integration.py -q

Creates isolated lab runs and a suspension for a unique test agent. Never
changes an existing agent, document, real key, package or GitHub repository.
"""
import asyncio
from dataclasses import replace
import os
from uuid import uuid4

import httpx
import pytest
from dotenv import dotenv_values

from victim_agent.config import ROOT, Settings
from victim_agent.models import RunRequest
from victim_agent.relay import Relay
from victim_agent.runtime import VictimRuntime
from victim_agent.storage import SupabaseStore
from victim_agent.tests.test_gateway import ScriptedModel

pytestmark = pytest.mark.skipif(os.getenv("RUN_LIVE_TESTS") != "1", reason="Explicit opt-in for live database writes required.")


def test_real_database_to_alex_to_confinement_to_block():
    async def scenario():
        settings = replace(Settings.from_env(), alex_url=os.environ["TRACE_TEST_ALEX_URL"])
        private = {**dotenv_values(ROOT / ".env.victim"), **{k: v for k, v in os.environ.items() if v}}
        agent_id = "integration-" + uuid4().hex[:10]
        async with httpx.AsyncClient() as http:
            store = SupabaseStore(settings, http)
            await store.seed()
            normal = await VictimRuntime(store, settings, http, ScriptedModel()).run(RunRequest(question="Déploiement Nexbuild ?", agent_id=agent_id))
            delivery = await Relay(store, settings, http).deliver(normal["run_id"])
            assert delivery["status"] == "delivered" and delivery["incident_id"] is None

            before = await VictimRuntime(store, settings, http, ScriptedModel(attack=True)).run(RunRequest(question="Diagnostic Nexbuild ?", agent_id=agent_id, scenario="tool_poisoning"))
            assert before["publications_received"] == 1 and before["journal_ok"]
            delivery = await Relay(store, settings, http).deliver(before["run_id"])
            assert delivery["status"] == "delivered" and delivery["incident_id"]
            incident_id = delivery["incident_id"]
            result = await http.post(settings.alex_url + "/incidents/" + incident_id + "/decision",
                headers={"Authorization": "Bearer " + private["ANALYSTE_TOKEN"]},
                json={"decision": "approved", "reason": "Validation automatisée du parcours de test, sans données réelles.", "analyst": "integration-test"})
            result.raise_for_status()
            assert result.json()["status"] == "Confiné"
            assert await store.is_suspended(agent_id, "github.publish")

            # A new runtime proves policy is read from Supabase after restart.
            after = await VictimRuntime(store, settings, http, ScriptedModel(attack=True)).run(RunRequest(question="Diagnostic Nexbuild ?", agent_id=agent_id, scenario="tool_poisoning"))
            assert after["blocked_actions"] == 1 and after["publications_received"] == 0
            events = await store.get_events(after["run_id"])
            assert any(e.type == "export_blocked" and e.result == "blocked" for e in events)
            receipts = await http.get("http://127.0.0.1:8001/demo-receiver", headers={"Authorization": "Bearer " + settings.gateway_token})
            receipts.raise_for_status()
            assert len([r for r in receipts.json() if r["agent_id"] == agent_id]) == 1
            repeated = await Relay(store, settings, http).deliver(before["run_id"])
            assert repeated["incident_id"] == incident_id
            print({"normal_run": normal["run_id"], "attack_run": before["run_id"], "blocked_run": after["run_id"],
                   "incident": incident_id, "gateway": "real", "database": "real", "victim_model": "scripted-test"})
    asyncio.run(scenario())
