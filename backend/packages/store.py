"""Lectures et écritures du contrôle des packages dans le schéma public.

Colonnes et valeurs suivent le schéma existant : l'état d'une revue est
proposed → pending_approval → approved / rejected → executed / failed, et
l'alerte part avec la source « sentinelle » et le signal
« suspicious_package_install », seuls admis par les contraintes en place.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Protocol
from uuid import UUID, uuid4

from psycopg import sql
from psycopg.types.json import Jsonb

from common.db import Database

PENDING = "pending_approval"
ALERT_SOURCE = "sentinelle"
ALERT_SIGNAL = "suspicious_package_install"
INVENTORY_SOURCE = "controle_packages"

_REVIEW_COLUMNS = frozenset({
    "version", "artifact_sha256", "checks", "evidence", "risk_level", "recommendation", "state",
    "decided_by", "decided_at", "decision_note", "execution_result", "executed_at",
})


class ReviewStore(Protocol):
    async def internal_versions(self, registry: str, name: str) -> list[dict[str, Any]]: ...

    async def create_review(self, **fields: Any) -> UUID: ...

    async def update_review(self, review_id: UUID, **fields: Any) -> None: ...

    async def get_review(self, review_id: UUID) -> dict[str, Any] | None: ...

    async def find_pending(self, trace_id: UUID, registry: str, name: str) -> dict[str, Any] | None: ...

    async def claim_decision(
        self, review_id: UUID, state: str, decided_by: str, note: str | None
    ) -> dict[str, Any] | None:
        """Passe une revue en attente à l'état décidé. None si elle n'attend plus de décision."""
        ...

    async def raise_alert(self, **fields: Any) -> UUID: ...

    async def record_quarantine(self, **fields: Any) -> None: ...

    async def record_install(self, agent: str, dependency: str, attributes: dict[str, Any]) -> None: ...

    async def remove_install(self, dependency: str) -> int:
        """Retire une dépendance de l'inventaire (ses droits d'accès partent en cascade). Rend le nombre retiré."""
        ...

    async def analyst(self, user_id: str) -> dict[str, Any] | None: ...


class PostgresReviewStore:
    """Écrit avec le compte de DATABASE_URL : aucun rôle dédié n'existe encore pour ce bloc."""

    def __init__(self, db: Database) -> None:
        self._db = db

    async def internal_versions(self, registry: str, name: str) -> list[dict[str, Any]]:
        async with self._db.as_owner() as conn:
            cur = await conn.execute(
                "select version, status, artifact_sha256, artifact_location from public.package_versions "
                "where registry = %s and name = %s", (registry, name))
            return await cur.fetchall()

    async def create_review(self, **fields: Any) -> UUID:
        return await self._insert("package_reviews", fields)

    async def update_review(self, review_id: UUID, **fields: Any) -> None:
        unknown = set(fields) - _REVIEW_COLUMNS
        if unknown:
            raise ValueError(f"colonnes non modifiables : {sorted(unknown)}")
        assignments = sql.SQL(", ").join(
            sql.SQL("{} = {}").format(sql.Identifier(column), sql.Placeholder()) for column in fields)
        async with self._db.as_owner() as conn:
            await conn.execute(
                sql.SQL("update public.package_reviews set {} where id = %s").format(assignments),
                [*(_adapt(v) for v in fields.values()), review_id])

    async def get_review(self, review_id: UUID) -> dict[str, Any] | None:
        async with self._db.as_owner() as conn:
            cur = await conn.execute("select * from public.package_reviews where id = %s", (review_id,))
            return await cur.fetchone()

    async def find_pending(self, trace_id: UUID, registry: str, name: str) -> dict[str, Any] | None:
        async with self._db.as_owner() as conn:
            cur = await conn.execute(
                "select * from public.package_reviews where trace_id = %s and registry = %s "
                "and package_name = %s and state = %s order by created_at limit 1",
                (trace_id, registry, name, PENDING))
            return await cur.fetchone()

    async def claim_decision(
        self, review_id: UUID, state: str, decided_by: str, note: str | None
    ) -> dict[str, Any] | None:
        async with self._db.as_owner() as conn:
            cur = await conn.execute(
                "update public.package_reviews set state = %s, decided_by = %s, decided_at = now(), "
                "decision_note = %s where id = %s and state = %s returning *",
                (state, decided_by, note, review_id, PENDING))
            return await cur.fetchone()

    async def raise_alert(self, **fields: Any) -> UUID:
        return await self._insert("alerts", fields)

    async def record_quarantine(self, **fields: Any) -> None:
        await self._insert("quarantine_artifacts", fields)

    async def record_install(self, agent: str, dependency: str, attributes: dict[str, Any]) -> None:
        async with self._db.as_owner() as conn:
            cur = await conn.execute(
                "select id from public.inventory where kind = 'dependency' and name = %s", (dependency,))
            row = await cur.fetchone()
            if row is None:
                cur = await conn.execute(
                    "insert into public.inventory (kind, name, description, attributes) "
                    "values ('dependency', %s, %s, %s) returning id",
                    (dependency, "Package installé via le contrôle des packages", Jsonb(attributes)))
                row = await cur.fetchone()
            await conn.execute(
                "insert into public.inventory_access (subject_id, object_id, granted_actions, source) "
                "select a.id, %s, array['use'], %s from public.inventory a "
                "where a.kind = 'agent' and a.name = %s and not exists ("
                "  select 1 from public.inventory_access x where x.subject_id = a.id and x.object_id = %s)",
                (row["id"], INVENTORY_SOURCE, agent, row["id"]))

    async def remove_install(self, dependency: str) -> int:
        async with self._db.as_owner() as conn:
            cur = await conn.execute(
                "delete from public.inventory where kind = 'dependency' and name = %s", (dependency,))
            return cur.rowcount

    async def analyst(self, user_id: str) -> dict[str, Any] | None:
        async with self._db.as_owner() as conn:
            cur = await conn.execute(
                "select user_id, display_name, can_approve_packages from public.analysts where user_id = %s",
                (user_id,))
            return await cur.fetchone()

    async def _insert(self, table: str, fields: dict[str, Any]) -> UUID:
        query = sql.SQL("insert into public.{} ({}) values ({}) returning id").format(
            sql.Identifier(table),
            sql.SQL(", ").join(sql.Identifier(column) for column in fields),
            sql.SQL(", ").join(sql.Placeholder() for _ in fields))
        async with self._db.as_owner() as conn:
            cur = await conn.execute(query, [_adapt(v) for v in fields.values()])
            return (await cur.fetchone())["id"]


def _adapt(value: Any) -> Any:
    return Jsonb(value) if isinstance(value, (dict, list)) else value


class MemoryReviewStore:
    """État en mémoire, pour les tests et le développement hors ligne."""

    def __init__(self) -> None:
        self.internal: list[dict[str, Any]] = []
        self.reviews: dict[UUID, dict[str, Any]] = {}
        self.alerts: list[dict[str, Any]] = []
        self.quarantined: list[dict[str, Any]] = []
        self.installed: list[dict[str, Any]] = []
        self.analysts: dict[str, dict[str, Any]] = {}

    async def internal_versions(self, registry: str, name: str) -> list[dict[str, Any]]:
        return [v for v in self.internal if v["registry"] == registry and v["name"] == name]

    async def create_review(self, **fields: Any) -> UUID:
        review_id = uuid4()
        self.reviews[review_id] = {
            "id": review_id, "checks": {}, "evidence": {}, "risk_level": None, "recommendation": None,
            "decided_by": None, "decided_at": None, "decision_note": None, "execution_result": None,
            "executed_at": None, "created_at": datetime.now(timezone.utc), **fields,
        }
        return review_id

    async def update_review(self, review_id: UUID, **fields: Any) -> None:
        unknown = set(fields) - _REVIEW_COLUMNS
        if unknown:
            raise ValueError(f"colonnes non modifiables : {sorted(unknown)}")
        self.reviews[review_id].update(fields)

    async def get_review(self, review_id: UUID) -> dict[str, Any] | None:
        review = self.reviews.get(review_id)
        return dict(review) if review else None

    async def find_pending(self, trace_id: UUID, registry: str, name: str) -> dict[str, Any] | None:
        for review in self.reviews.values():
            if (review["trace_id"], review["registry"], review["package_name"], review["state"]) == (
                    trace_id, registry, name, PENDING):
                return dict(review)
        return None

    async def claim_decision(
        self, review_id: UUID, state: str, decided_by: str, note: str | None
    ) -> dict[str, Any] | None:
        review = self.reviews.get(review_id)
        if review is None or review["state"] != PENDING:
            return None
        review.update(state=state, decided_by=decided_by, decided_at=datetime.now(timezone.utc),
                      decision_note=note)
        return dict(review)

    async def raise_alert(self, **fields: Any) -> UUID:
        alert_id = uuid4()
        self.alerts.append({"id": alert_id, **fields})
        return alert_id

    async def record_quarantine(self, **fields: Any) -> None:
        self.quarantined.append(fields)

    async def record_install(self, agent: str, dependency: str, attributes: dict[str, Any]) -> None:
        self.installed.append({"agent": agent, "dependency": dependency, "attributes": attributes})

    async def remove_install(self, dependency: str) -> int:
        before = len(self.installed)
        self.installed = [i for i in self.installed if i["dependency"] != dependency]
        return before - len(self.installed)

    async def analyst(self, user_id: str) -> dict[str, Any] | None:
        return self.analysts.get(user_id)
