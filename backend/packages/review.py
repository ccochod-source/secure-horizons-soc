"""Contrôle des packages : tout package demandé par un agent passe ici avant d'être installé.

Règle centrale : un package suspect n'est jamais installé ni rejeté pour de
bon sans décision humaine. Le système recommande, l'analyste tranche.
"""

from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable, Literal
from uuid import UUID

import httpx

from gateway.events import EventRecord, EventStore
from gateway.session import Session
from packages import existence, static
from packages.existence import PackageInfo, RegistryUnavailable, VersionNotFound
from packages.learning import Learned, PackageLearning
from packages.install import InstallError, Installer, RecordingInstaller
from packages.quarantine import Archive, ArchiveUnavailable, DigestMismatch, LocalQuarantine
from packages.reputation import reputation
from packages.score import THRESHOLD, Signal, is_blocking, needs_human, risk_level, risk_score, signal
from packages.store import ALERT_SIGNAL, ALERT_SOURCE, PENDING, ReviewStore
from vault.pseudonymize import Pseudonymizer

logger = logging.getLogger(__name__)

ACTOR = "controle_packages"
AUTOMATIC = "automatique"
UNKNOWN_VERSION = "non précisée"
NO_ARTIFACT = "indisponible"

Decision = Literal["approve", "reject", "replace"]


class PackageControlError(RuntimeError):
    pass


class UnknownReview(PackageControlError):
    pass


class NotPending(PackageControlError):
    """La revue n'attend pas, ou plus, de décision."""


class ReplacementRefused(PackageControlError):
    """Le package de remplacement proposé ne peut pas être installé."""


@dataclass
class Analysis:
    version: str
    signals: list[Signal] = field(default_factory=list)
    steps: dict[str, str] = field(default_factory=dict)
    info: PackageInfo | None = None
    archive: Archive | None = None
    sha256: str | None = None
    internal: bool = False  # version approuvée de la liste interne
    learned_replacement: dict[str, Any] | None = None  # règle replacement_map active pour ce nom


class PackageReviewer:
    """Implémente gateway.hooks.PackageControl, et la décision de l'analyste."""

    def __init__(
        self,
        store: ReviewStore,
        events: EventStore,
        pseudonymizer: Pseudonymizer,
        client: httpx.AsyncClient,
        quarantine: LocalQuarantine,
        installer: Installer | None = None,
        *,
        learning: PackageLearning | None = None,
        threshold: float = THRESHOLD,
        now: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
    ) -> None:
        self._store = store
        self._events = events
        self._pseudonymizer = pseudonymizer
        self._client = client
        self._quarantine = quarantine
        self._installer: Installer = installer or RecordingInstaller()
        self._learning = learning
        self._threshold = threshold
        self._now = now

    @property
    def store(self) -> ReviewStore:
        return self._store

    # --- demande d'un agent (étapes 1 à 5) ----------------------------------

    async def review(
        self, session: Session, event_id: UUID, ecosystem: str, name: str, version: str | None = None
    ) -> dict[str, Any]:
        refusal = existence.valid_request(ecosystem, name, version)
        if refusal is not None:
            return {"status": "blocked", "reason": refusal}
        waiting = await self._store.find_pending(session.trace_id, ecosystem, name)
        if waiting is not None:
            return _pending_answer(waiting["id"])

        review_id = await self._store.create_review(
            run_id=session.run_id, trace_id=session.trace_id, package_name=name, registry=ecosystem,
            version=version or UNKNOWN_VERSION, artifact_sha256=NO_ARTIFACT,
            requested_by_agent=session.agent_id, state="proposed",
            checks={"request_event_id": str(event_id)},
        )
        analysis = await self._analyze(ecosystem, name, version)
        score = risk_score(analysis.signals)
        level = risk_level(analysis.signals, self._threshold)
        human = needs_human(analysis.signals, self._threshold)
        decision, replacement = _recommended(analysis.signals, human)
        learned_rule = analysis.learned_replacement
        if human and replacement is None and learned_rule is not None:
            decision, replacement = "replace", learned_rule["value"]["to"]
        safe = (await self._pseudonymizer.pseudonymize({
            "checks": {
                "request_event_id": str(event_id), "requested_version": version, "score": score,
                "threshold": self._threshold, "blocking": is_blocking(analysis.signals),
                "signals": [s.as_dict() for s in analysis.signals], "steps": analysis.steps,
                "recommended_decision": decision, "suggested_replacement": replacement,
                "internal_allowlist": analysis.internal,
                "learned_replacement": _rule_dict(learned_rule),
            },
            "evidence": {
                "excerpts": [{"signal": s.code, **e} for s in analysis.signals for e in s.evidence],
                "quarantine": _archive_dict(analysis.archive),
                "registry": _registry_dict(analysis.info),
            },
        })).value
        fields: dict[str, Any] = {
            "version": analysis.version, "artifact_sha256": analysis.sha256 or NO_ARTIFACT,
            "checks": safe["checks"], "evidence": safe["evidence"], "risk_level": level,
            "recommendation": _recommendation_text(analysis.signals, decision, replacement),
        }
        reference = _reference(ecosystem, name, analysis.version)
        summary = {"package": reference, "score": score, "risk_level": level,
                   "signals": [{"code": s.code, "explanation": s.explanation} for s in analysis.signals]}

        learned_block = next((s for s in analysis.signals if s.code == "known_malicious"), None)
        if learned_block is not None:
            # Un analyste a déjà rejeté ce package et appliqué la règle : pas de seconde file d'attente.
            decided_by = f"regle_apprise_v{learned_block.data['version']}"
            await self._store.update_review(
                review_id, state="rejected", decided_by=decided_by, decided_at=self._now(),
                decision_note=learned_block.explanation, **fields)
            await self._trace(
                session.trace_id, session.run_id, event_id, event_type="package_review",
                actor_type="system", actor_id=ACTOR, action="review", result="blocked",
                resource_id=reference, content=summary,
                metadata={"review_id": str(review_id), "rule_id": learned_block.data["rule_id"],
                          "ruleset_version": learned_block.data["version"]})
            return {"status": "blocked", "review_id": str(review_id), "reason": learned_block.explanation,
                    "risk_score": score, "rule_version": learned_block.data["version"]}

        if human:
            await self._store.update_review(review_id, state=PENDING, **fields)
            if analysis.archive is not None:
                await self._store.record_quarantine(
                    package_name=name, version=analysis.version, artifact_sha256=analysis.archive.sha256,
                    storage_ref=analysis.archive.storage_ref,
                    reason="; ".join(s.explanation for s in analysis.signals)[:500])
            await self._store.raise_alert(
                run_id=session.run_id, trace_id=session.trace_id, event_id=event_id, severity=level,
                source=ALERT_SOURCE, signal=ALERT_SIGNAL, affected_agent=session.agent_id,
                status="awaiting_decision",
                summary=f"[contrôle des packages] {reference} en quarantaine, score {score:.2f} : "
                        + "; ".join(s.explanation for s in analysis.signals)[:400])
            await self._trace(
                session.trace_id, session.run_id, event_id, event_type="package_review",
                actor_type="system", actor_id=ACTOR, action="review", result="pending",
                resource_id=reference, content=summary, metadata={"review_id": str(review_id)})
            return _pending_answer(review_id, score)

        await self._store.update_review(
            review_id, state="approved", decided_by=AUTOMATIC, decided_at=self._now(),
            decision_note="Approbation automatique : score sous le seuil.", **fields)
        await self._trace(
            session.trace_id, session.run_id, event_id, event_type="package_review",
            actor_type="system", actor_id=ACTOR, action="review", result="success",
            resource_id=reference, content=summary, metadata={"review_id": str(review_id)})
        outcome = await self._install(
            review_id, agent=session.agent_id, ecosystem=ecosystem, name=name, version=analysis.version,
            archive=analysis.archive.path if analysis.archive else None,
            trace_id=session.trace_id, run_id=session.run_id, parent=event_id, decided_by=AUTOMATIC)
        if not outcome.get("installed"):
            return {"status": "blocked", "review_id": str(review_id), "reason": "installation en échec"}
        return {"status": "installed", "review_id": str(review_id), "package": reference,
                "risk_score": score, "simulated": bool(outcome.get("simulated"))}

    async def _analyze(self, ecosystem: str, name: str, version: str | None) -> Analysis:
        analysis = Analysis(version=version or UNKNOWN_VERSION)

        # Liste interne d'abord : une version déjà approuvée par l'équipe passe sans autre contrôle.
        internal = await self._store.internal_versions(ecosystem, name)
        if internal:
            match = _internal_match(internal, version)
            if match is not None:
                analysis.version, analysis.sha256 = match["version"], match["artifact_sha256"]
                if match["status"] == "approved":
                    analysis.internal = True
                    analysis.steps["existence"] = "internal_approved"
                elif match["status"] == "pending":
                    analysis.signals.append(signal(
                        "internal_pending", "Version en attente d'approbation dans la liste interne."))
                else:
                    analysis.signals.append(signal(
                        "internal_denied", f"Version marquée « {match['status']} » dans la liste interne."))
                return analysis
            analysis.signals.append(signal(
                "dependency_confusion",
                "Le nom appartient à la liste interne mais cette version n'y figure pas "
                "(risque de confusion de dépendances)."))

        # Règles apprises : seules les lignes actives, appliquées par un analyste, comptent.
        learned = await self._learned(ecosystem)
        normalized = existence.normalize(ecosystem, name)
        rule = learned.malicious.get(normalized)
        if rule is not None:
            analysis.steps["existence"] = "learned_block"
            analysis.signals.append(signal(
                "known_malicious", f"Bloqué par règle apprise v{rule['version']}.",
                rule_id=rule["id"], version=rule["version"]))
            return analysis
        analysis.learned_replacement = learned.replacements.get(normalized)

        analysis.signals += existence.name_signals(ecosystem, name, learned.popular)
        try:
            info = await existence.lookup(self._client, ecosystem, name, version)
        except RegistryUnavailable:
            analysis.steps["existence"] = "unavailable"
            analysis.signals.append(signal(
                "registry_unavailable", "Registre injoignable : existence du package non vérifiée."))
            return analysis
        except VersionNotFound:
            analysis.steps["existence"] = "version_not_found"
            analysis.signals.append(signal(
                "version_not_found", f"La version {version} n'existe pas sur le registre."))
            return analysis
        if info is None:
            analysis.steps["existence"] = "not_found"
            analysis.signals.append(signal(
                "package_not_found", "Package introuvable sur le registre : nom probablement halluciné."))
            return analysis
        analysis.info, analysis.version = info, info.version
        analysis.steps["existence"] = "found"
        analysis.signals += existence.age_signals(info, self._now())

        try:
            analysis.archive = await self._quarantine.fetch(self._client, info)
            analysis.sha256 = analysis.archive.sha256
        except DigestMismatch:
            analysis.steps["static"] = "digest_mismatch"
            analysis.signals.append(signal(
                "digest_mismatch", "L'archive téléchargée ne correspond pas à l'empreinte annoncée par le registre."))
            return analysis
        except ArchiveUnavailable as exc:
            analysis.steps["static"] = "archive_unavailable"
            analysis.signals.append(signal("archive_unavailable", f"Archive non analysée : {exc}."))
        else:
            try:
                analysis.signals += await asyncio.to_thread(
                    static.analyze_archive, analysis.archive.path, ecosystem, info.install_from_source,
                    self._pseudonymizer.scanner)
                analysis.steps["static"] = "done"
            except Exception as exc:  # archive illisible ou piégée : on n'approuve pas à l'aveugle
                logger.warning("analyse statique en échec (%s)", type(exc).__name__)
                analysis.steps["static"] = "error"
                analysis.signals.append(signal("analysis_incomplete", "L'archive n'a pas pu être analysée."))
            analysis.steps["guarddog"], found = await static.guarddog(analysis.archive.path, ecosystem)
            analysis.signals += found

        analysis.signals += await reputation(self._client, info)
        analysis.steps["reputation"] = (
            "unavailable" if any(s.code == "reputation_unavailable" for s in analysis.signals) else "done")
        return analysis

    async def _learned(self, ecosystem: str) -> Learned:
        if self._learning is None:
            return Learned()
        try:
            return await self._learning.learned(ecosystem)
        except Exception:
            # Listes illisibles : on retombe sur l'analyse complète, jamais sur une approbation.
            logger.exception("règles apprises illisibles : analyse sans elles")
            return Learned()

    # --- décision de l'analyste ---------------------------------------------

    async def decide(
        self,
        review_id: UUID,
        decision: Decision,
        *,
        decided_by: str,
        note: str | None = None,
        replacement_name: str | None = None,
        replacement_version: str | None = None,
    ) -> dict[str, Any]:
        """Seul chemin par lequel un package suspect peut être installé."""
        review = await self._store.get_review(review_id)
        if review is None:
            raise UnknownReview(str(review_id))
        if review["state"] != PENDING:
            raise NotPending(review["state"])
        ecosystem, name = review["registry"], review["package_name"]
        trace_id, run_id = review["trace_id"], review["run_id"]
        parent = _request_event(review)
        reference = _reference(ecosystem, name, review["version"])

        async def traced(result: str, content: dict[str, Any]) -> None:
            if trace_id is not None:
                await self._trace(
                    trace_id, run_id, parent, event_type="package_review", actor_type="user",
                    actor_id=decided_by, action=decision, result=result, resource_id=reference,
                    content=content, metadata={"review_id": str(review_id)})

        if decision == "approve":
            if await self._store.claim_decision(review_id, "approved", decided_by, note) is None:
                raise NotPending("décision déjà prise")
            await traced("success", {"decision": "approve", "package": reference, "note": note})
            archive = self._quarantine.path((review["evidence"].get("quarantine") or {}).get("storage_ref"))
            # Un nom halluciné reste introuvable même approuvé : rien à installer.
            installable = archive is not None or review["artifact_sha256"] != NO_ARTIFACT
            outcome = await self._install(
                review_id, agent=review["requested_by_agent"], ecosystem=ecosystem, name=name,
                version=review["version"], archive=archive, trace_id=trace_id, run_id=run_id,
                parent=parent, decided_by=decided_by,
                impossible=None if installable else "aucune archive : package introuvable ou non téléchargé")
            return {"review_id": str(review_id), "state": "executed" if outcome.get("installed") else "failed",
                    "execution_result": outcome}

        if decision == "reject":
            if await self._store.claim_decision(review_id, "rejected", decided_by, note) is None:
                raise NotPending("décision déjà prise")
            # L'événement de rejet est ce que la Sentinelle et l'Enquêteur remontent.
            await traced("blocked", {"decision": "reject", "package": reference, "note": note})
            return {"review_id": str(review_id), "state": "rejected"}

        if decision != "replace":
            raise PackageControlError(f"décision inconnue : {decision}")
        refusal = existence.valid_request(ecosystem, replacement_name, replacement_version)
        if refusal is not None:
            raise ReplacementRefused(refusal)
        analysis = await self._analyze(ecosystem, replacement_name, replacement_version)
        if is_blocking(analysis.signals):
            raise ReplacementRefused("; ".join(s.explanation for s in analysis.signals if s.blocking))
        substitute = _reference(ecosystem, replacement_name, analysis.version)
        replaced_note = f"Remplacé par {substitute}." + (f" {note}" if note else "")
        if await self._store.claim_decision(review_id, "rejected", decided_by, replaced_note) is None:
            raise NotPending("décision déjà prise")
        safe = (await self._pseudonymizer.pseudonymize({
            "checks": {
                "request_event_id": str(parent) if parent else None, "replaces_review_id": str(review_id),
                "score": risk_score(analysis.signals), "threshold": self._threshold, "blocking": False,
                "signals": [s.as_dict() for s in analysis.signals], "steps": analysis.steps,
                "internal_allowlist": analysis.internal,
            },
            "evidence": {
                "excerpts": [{"signal": s.code, **e} for s in analysis.signals for e in s.evidence],
                "quarantine": _archive_dict(analysis.archive), "registry": _registry_dict(analysis.info),
            },
        })).value
        new_id = await self._store.create_review(
            run_id=run_id, trace_id=trace_id, package_name=replacement_name, registry=ecosystem,
            version=analysis.version, artifact_sha256=analysis.sha256 or NO_ARTIFACT,
            requested_by_agent=review["requested_by_agent"], state="approved",
            checks=safe["checks"], evidence=safe["evidence"],
            risk_level=risk_level(analysis.signals, self._threshold),
            recommendation=f"Choisi par l'analyste en remplacement de {reference}.",
            decided_by=decided_by, decided_at=self._now(), decision_note=note)
        await self._store.update_review(review_id, execution_result={"replaced_by_review_id": str(new_id)})
        await traced("blocked", {"decision": "replace", "package": reference, "replaced_by": substitute,
                                 "note": note})
        outcome = await self._install(
            new_id, agent=review["requested_by_agent"], ecosystem=ecosystem, name=replacement_name,
            version=analysis.version, archive=analysis.archive.path if analysis.archive else None,
            trace_id=trace_id, run_id=run_id, parent=parent, decided_by=decided_by)
        return {"review_id": str(review_id), "state": "rejected", "replacement_review_id": str(new_id),
                "replacement_state": "executed" if outcome.get("installed") else "failed",
                "execution_result": outcome}

    # --- retrait après contre-vérification -----------------------------------

    async def remove(self, review_id: UUID, *, decided_by: str, reason: str) -> dict[str, Any]:
        """Retire un package approuvé : désinstallation chez l'agent, suppression de l'inventaire, revue rejetée.
        Seul chemin par lequel une approbation humaine est annulée ; demandé par le backend de défense après
        une contre-vérification non positive confirmée par l'analyste qui avait approuvé."""
        review = await self._store.get_review(review_id)
        if review is None:
            raise UnknownReview(str(review_id))
        if review["state"] not in ("executed", "failed", "approved"):
            raise NotPending(review["state"])
        ecosystem, name = review["registry"], review["package_name"]
        reference = _reference(ecosystem, name, review["version"])
        uninstalled: dict[str, Any] = {"removed": False, "note": "rien n'était installé"}
        if review["state"] == "executed":
            try:
                uninstalled = await self._installer.uninstall(ecosystem, name)
            except InstallError as exc:
                uninstalled = {"removed": False, "error": str(exc)}
        removed_rows = await self._store.remove_install(reference)
        result = {"removed_at": self._now().isoformat(), "removed_by": decided_by, "reason": reason,
                  "uninstall": uninstalled, "inventory_rows_removed": removed_rows,
                  "previous_state": review["state"]}
        await self._store.update_review(
            review_id, state="rejected", decision_note=f"Retiré : {reason}",
            execution_result={**(review.get("execution_result") or {}), "removal": result})
        if review.get("trace_id") is not None:
            await self._trace(
                review["trace_id"], review.get("run_id"), _request_event(review), event_type="package_review",
                actor_type="user", actor_id=decided_by, action="remove", result="success", resource_id=reference,
                content={"decision": "remove", "package": reference, "reason": reason, **result},
                metadata={"review_id": str(review_id)})
        return {"review_id": str(review_id), "state": "rejected", "package": reference, **result}

    # --- installation et traces ---------------------------------------------

    async def _install(
        self, review_id: UUID, *, agent: str, ecosystem: str, name: str, version: str, archive: Any,
        trace_id: UUID | None, run_id: UUID | None, parent: UUID | None, decided_by: str,
        impossible: str | None = None,
    ) -> dict[str, Any]:
        reference = _reference(ecosystem, name, version)
        try:
            if impossible is not None:
                raise InstallError(impossible)
            outcome = await self._installer.install(ecosystem, name, version, archive)
        except InstallError as exc:
            outcome = {"installed": False, "error": str(exc)}
            await self._store.update_review(review_id, state="failed", execution_result=outcome)
            if trace_id is not None:
                await self._trace(
                    trace_id, run_id, parent, event_type="package_review", actor_type="system",
                    actor_id=ACTOR, action="install", result="error", resource_id=reference,
                    content=outcome, metadata={"review_id": str(review_id)})
            return outcome
        await self._store.update_review(
            review_id, state="executed", execution_result=outcome, executed_at=self._now())
        await self._store.record_install(agent, reference, {
            "ecosystem": ecosystem, "name": name, "version": version, "installed_for": agent,
            "review_id": str(review_id), "decided_by": decided_by,
            "simulated": bool(outcome.get("simulated")),
        })
        if trace_id is not None:
            await self._trace(
                trace_id, run_id, parent, event_type="dependency_installed", actor_type="system",
                actor_id=ACTOR, action="install", result="success", resource_id=reference,
                content={"package": reference, "decided_by": decided_by, **outcome},
                metadata={"review_id": str(review_id)})
        return outcome

    async def _trace(
        self, trace_id: UUID, run_id: UUID | None, parent: UUID | None, *, event_type: str,
        actor_type: str, actor_id: str, action: str, result: str, resource_id: str,
        content: dict[str, Any], metadata: dict[str, Any],
    ) -> None:
        safe = await self._pseudonymizer.pseudonymize(
            {"actor_id": actor_id, "content": content, "metadata": metadata})
        meta = dict(safe.value["metadata"])
        if safe.tokens:
            meta["tokens"] = list(safe.tokens)
        await self._events.insert(EventRecord(
            trace_id=trace_id, parent_event_id=parent, run_id=run_id, event_type=event_type,
            actor_type=actor_type, actor_id=safe.value["actor_id"], action=action, result=result,
            resource_type="package", resource_id=resource_id,
            content=json.dumps(safe.value["content"], ensure_ascii=False), metadata=meta))


def _pending_answer(review_id: UUID, score: float | None = None) -> dict[str, Any]:
    answer: dict[str, Any] = {
        "status": "blocked_pending_review", "review_id": str(review_id),
        "message": "Installation suspendue : en attente de la décision d'un analyste.",
    }
    if score is not None:
        answer["risk_score"] = score
    return answer


def _reference(ecosystem: str, name: str, version: str) -> str:
    return f"{ecosystem}:{name}" if version == UNKNOWN_VERSION else f"{ecosystem}:{name}@{version}"


def _internal_match(rows: list[dict[str, Any]], version: str | None) -> dict[str, Any] | None:
    if version is not None:
        return next((r for r in rows if r["version"] == version), None)
    approved = [r for r in rows if r["status"] == "approved"]
    return max(approved, key=lambda r: _version_key(r["version"]), default=None)


def _version_key(version: str) -> tuple[int, ...]:
    return tuple(int(part) if part.isdigit() else 0 for part in version.split("."))


def _recommended(signals: list[Signal], human: bool) -> tuple[str, str | None]:
    if not human:
        return "approve", None
    typosquat = next((s for s in signals if s.code == "typosquat"), None)
    if typosquat is not None:
        return "replace", typosquat.data["similar_to"]
    return ("reject" if is_blocking(signals) or risk_score(signals) >= 0.6 else "review"), None


def _recommendation_text(signals: list[Signal], decision: str, replacement: str | None) -> str:
    if decision == "approve":
        return "Installation automatique : aucun signal au-dessus du seuil."
    reasons = " ".join(s.explanation for s in signals)
    if decision == "replace":
        return f"Remplacer par « {replacement} ». {reasons}"
    if decision == "reject":
        return f"Rejeter. {reasons}"
    return f"À examiner avant d'approuver. {reasons}"


def _archive_dict(archive: Archive | None) -> dict[str, Any] | None:
    if archive is None:
        return None
    return {"storage_ref": archive.storage_ref, "sha256": archive.sha256, "size": archive.size,
            "filename": archive.filename, "scripts_executed": False}


def _rule_dict(rule: dict[str, Any] | None) -> dict[str, Any] | None:
    if rule is None:
        return None
    return {"rule_id": rule["id"], "version": rule["version"], "to": rule["value"]["to"]}


def _registry_dict(info: PackageInfo | None) -> dict[str, Any] | None:
    if info is None:
        return None
    return {
        "created_at": info.created_at.isoformat() if info.created_at else None,
        "version_published_at": info.version_published_at.isoformat() if info.version_published_at else None,
        "versions_count": info.versions_count, "maintainers": info.maintainers,
        "repository": info.repository, "install_from_source": info.install_from_source,
    }


def _request_event(review: dict[str, Any]) -> UUID | None:
    try:
        return UUID(str((review.get("checks") or {}).get("request_event_id")))
    except ValueError:
        return None
