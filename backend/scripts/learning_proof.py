"""Preuve avant / après de la boucle d'amélioration du contrôle des packages.

    cd backend
    .venv/bin/python -m scripts.learning_proof

Déroulé : des variantes de packages malveillants passent dans le contrôle avec
la version N des listes ; l'analyste (décision simulée) les rejette, puis
applique les propositions ; les mêmes variantes et des packages légitimes sont
rejoués avec la nouvelle version.

Ce qui est réel : les registres PyPI, npm et OSV sont interrogés en direct, et
le code du contrôle est celui de la passerelle. Ce qui est simulé : l'analyste
(aucun jeton, donc rien n'est écrit dans la base partagée : revues et règles
restent en mémoire) et l'installation (enregistrée, jamais exécutée).

Sorties : demo/learning_proof.json et demo/learning_proof.md.
"""

from __future__ import annotations

import asyncio
import json
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

import httpx

from common.rules import MemoryRuleStore
from gateway.events import EventRecord, MemoryEventStore
from gateway.session import Session
from packages import LocalQuarantine, MemoryReviewStore, PackageReviewer
from packages.learning import PackageLearning
from vault import MemoryTokenStore, Pseudonymizer, Scanner

OUT = Path(__file__).resolve().parents[1] / "demo"

# Noms inventés ou à une faute de frappe d'un package répandu.
MALICIOUS = [
    ("pypi", "reqeusts"),
    ("pypi", "pandass"),
    ("pypi", "numpyy-fast"),
    ("pypi", "fastjsonparse-turbo"),
    ("npm", "lodahs"),
]
LEGITIMATE = [("pypi", "requests"), ("pypi", "httpx"), ("npm", "lodash")]

HUMAN = "blocked_pending_review"


class Bench:
    def __init__(self, client: httpx.AsyncClient, quarantine: Path) -> None:
        self.reviews = MemoryReviewStore()
        self.rules = MemoryRuleStore()
        self.events = MemoryEventStore()
        self.learning = PackageLearning(self.rules, self.reviews)
        self.reviewer = PackageReviewer(
            self.reviews, self.events, Pseudonymizer(MemoryTokenStore(), Scanner()), client,
            LocalQuarantine(quarantine), learning=self.learning)
        self.analyst = str(uuid4())
        self.reviews.analysts[self.analyst] = {"user_id": self.analyst, "can_approve_packages": True}
        self.registry_calls = 0

    async def check(self, phase: str, kind: str, ecosystem: str, name: str) -> dict[str, Any]:
        session = Session(agent_id="DevBot")
        event_id = await self.events.insert(EventRecord(
            trace_id=session.trace_id, event_type="package_install_requested", actor_type="agent",
            actor_id="DevBot"))
        version, calls = await self.rules.current_version(), self.registry_calls
        outcome = await self.reviewer.review(session, event_id, ecosystem, name)
        review = self.reviews.reviews.get(_uuid(outcome.get("review_id")))
        checks = (review or {}).get("checks") or {}
        return {
            "phase": phase, "kind": kind, "ecosystem": ecosystem, "package": name,
            "ruleset_version": version, "score": checks.get("score"), "decision": outcome.get("status"),
            "review_state": (review or {}).get("state"), "reason": outcome.get("reason"),
            "signals": [{"code": s["code"], "explanation": s["explanation"]} for s in checks.get("signals", [])],
            "network_calls": self.registry_calls - calls, "review_id": outcome.get("review_id"),
        }

    async def count(self, request: httpx.Request) -> None:
        self.registry_calls += 1


def _uuid(value: Any) -> Any:
    from uuid import UUID
    try:
        return UUID(str(value))
    except ValueError:
        return None


def _metrics(rows: list[dict[str, Any]]) -> dict[str, Any]:
    malicious = [r for r in rows if r["kind"] == "malicious"]
    legitimate = [r for r in rows if r["kind"] == "legitimate"]
    return {
        "ruleset_version": rows[0]["ruleset_version"],
        "malicious_total": len(malicious),
        "malicious_stopped_before_install": sum(r["decision"] != "installed" for r in malicious),
        "malicious_blocked_without_human": sum(r["decision"] == "blocked" for r in malicious),
        "malicious_needing_human_decision": sum(r["decision"] == HUMAN for r in malicious),
        "malicious_network_calls": sum(r["network_calls"] for r in malicious),
        "legitimate_total": len(legitimate),
        "legitimate_installed": sum(r["decision"] == "installed" for r in legitimate),
        "legitimate_sent_to_human": sum(r["decision"] == HUMAN for r in legitimate),
        "legitimate_blocked_by_learned_rule": sum(
            any(s["code"] == "known_malicious" for s in r["signals"]) for r in legitimate),
    }


def _markdown(report: dict[str, Any]) -> str:
    before, after = report["metrics"]["before"], report["metrics"]["after"]
    by_package = {(r["phase"], r["ecosystem"], r["package"]): r for r in report["runs"]}

    def cell(row: dict[str, Any]) -> str:
        score = "—" if row["score"] is None else f"{row['score']:.2f}"
        return f"{row['decision']} (score {score} ; {', '.join(s['code'] for s in row['signals']) or 'aucun signal'})"

    lines = [
        "# Boucle d'amélioration : preuve avant / après",
        "",
        f"Mesuré le {report['generated_at']} — registres PyPI, npm et OSV interrogés en direct ; "
        "analyste et installation simulés, rien n'est écrit en base.",
        "",
        f"| Mesure | Avant (listes v{before['ruleset_version']}) | Après (listes v{after['ruleset_version']}) |",
        "|---|---|---|",
    ]
    for label, key in (
        ("Packages malveillants arrêtés avant installation", "malicious_stopped_before_install"),
        ("… dont bloqués d'emblée, sans analyste", "malicious_blocked_without_human"),
        ("… dont en attente d'une décision humaine", "malicious_needing_human_decision"),
        ("Appels réseau (registres, archives) pour ces packages", "malicious_network_calls"),
        ("Packages légitimes installés", "legitimate_installed"),
        ("Packages légitimes envoyés à tort en décision humaine", "legitimate_sent_to_human"),
        ("Packages légitimes bloqués par une règle apprise", "legitimate_blocked_by_learned_rule"),
    ):
        total = "malicious_total" if key.startswith("malicious") and "network" not in key else (
            "legitimate_total" if key.startswith("legitimate") else None)
        fmt = (lambda m: f"{m[key]} / {m[total]}") if total else (lambda m: str(m[key]))
        lines.append(f"| {label} | {fmt(before)} | {fmt(after)} |")
    lines += ["", "| Package | Type | Avant | Après |", "|---|---|---|---|"]
    for kind, packages in (("malveillant", MALICIOUS), ("légitime", LEGITIMATE)):
        for ecosystem, name in packages:
            lines.append(f"| {ecosystem}:{name} | {kind} | {cell(by_package['before', ecosystem, name])} "
                         f"| {cell(by_package['after', ecosystem, name])} |")
    lines += ["", "Règles appliquées par l'analyste entre les deux passes :", ""]
    lines += [f"- v{r['version']} — {r['kind']} : {json.dumps(r['value'], ensure_ascii=False)}"
              for r in report["rules_applied"]]
    if report["warnings"]:
        lines += ["", "**Alertes :**", ""] + [f"- {w}" for w in report["warnings"]]
    return "\n".join(lines) + "\n"


async def main() -> int:
    with tempfile.TemporaryDirectory(prefix="learning-proof-") as quarantine:
        async with httpx.AsyncClient(timeout=20, follow_redirects=True,
                                     headers={"user-agent": "copilote-soc-packages"}) as client:
            bench = Bench(client, Path(quarantine))
            client.event_hooks["request"].append(bench.count)
            packages = [("malicious", *p) for p in MALICIOUS] + [("legitimate", *p) for p in LEGITIMATE]

            before = [await bench.check("before", *p) for p in packages]

            # Analyste (simulé) : rejette chaque variante malveillante en attente, puis applique
            # les propositions qui en découlent. Sans ces deux gestes, rien ne change.
            decisions = []
            for row in before:
                if row["kind"] == "malicious" and row["decision"] == HUMAN:
                    review_id = _uuid(row["review_id"])
                    await bench.reviewer.decide(review_id, "reject", decided_by=bench.analyst,
                                                note="Preuve : variante malveillante rejetée.")
                    proposed = await bench.learning.propose(review_id)
                    decisions.append({"package": row["package"], "decision": "reject",
                                      "proposals": [{"id": r["id"], "kind": r["kind"], "value": r["value"]}
                                                    for r in proposed]})
            unchanged = await bench.check("proposed_only", *packages[0])
            applied = [await bench.rules.apply(r["id"], bench.analyst) for r in await bench.rules.rows("proposed")]

            after = [await bench.check("after", *p) for p in packages]

    warnings = []
    if any(r["decision"] == "installed" for r in before + after if r["kind"] == "malicious"):
        warnings.append("Un package malveillant a été installé (simulation) : voir le détail.")
    for row in after:
        if row["kind"] == "legitimate" and row["decision"] != "installed":
            warnings.append(f"Package légitime non installé après les nouvelles règles : "
                            f"{row['ecosystem']}:{row['package']} → {row['decision']}.")
    if any(any(s["code"] == "registry_unavailable" for s in r["signals"]) for r in before + after):
        warnings.append("Registre injoignable pendant la mesure : relancer avec un accès réseau.")

    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "real": ["registres PyPI / npm / OSV en direct", "code du contrôle des packages de la passerelle"],
        "simulated": ["décisions de l'analyste (aucun jeton Supabase)", "installation des packages",
                      "stockage en mémoire : rien n'est écrit dans la base partagée"],
        "metrics": {"before": _metrics(before), "after": _metrics(after)},
        "proposal_alone_changes_nothing": {
            "package": unchanged["package"], "ruleset_version": unchanged["ruleset_version"],
            "decision": unchanged["decision"], "signals": unchanged["signals"]},
        "analyst_decisions": decisions,
        "rules_applied": [{"id": r["id"], "kind": r["kind"], "value": r["value"], "version": r["version"]}
                          for r in applied],
        "runs": [{k: v for k, v in r.items() if k != "review_id"} for r in before + after],
        "warnings": warnings,
    }
    OUT.mkdir(exist_ok=True)
    (OUT / "learning_proof.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    table = _markdown(report)
    (OUT / "learning_proof.md").write_text(table)
    print(table)
    return 1 if warnings else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
