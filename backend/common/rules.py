"""Listes de règles versionnées : proposées par le système, appliquées par un analyste.

Une règle n'a d'effet que dans l'état « active ». Rien n'est jamais supprimé :
le retour en arrière passe la ligne à « rolled_back ». Chaque activation ou
annulation incrémente le compteur unique public.ruleset_meta (trigger en base).
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Protocol
from uuid import UUID

from psycopg import sql
from psycopg.types.json import Jsonb

from common.db import Database

PROPOSED = "proposed"
ACTIVE = "active"
ROLLED_BACK = "rolled_back"

_TABLES = frozenset({"package_rules", "decoy_rules"})


class RuleStore(Protocol):
    async def propose(self, kind: str, value: dict[str, Any], source_decision_id: UUID) -> dict[str, Any] | None:
        """Ajoute une proposition. None si la même règle est déjà proposée ou active."""
        ...

    async def rows(self, status: str | None = None) -> list[dict[str, Any]]: ...

    async def active(self, kind: str) -> list[dict[str, Any]]: ...

    async def get(self, rule_id: int) -> dict[str, Any] | None: ...

    async def apply(self, rule_id: int, decided_by: str) -> dict[str, Any] | None:
        """proposed → active. None si la règle n'est pas (ou plus) proposée."""
        ...

    async def rollback(self, rule_id: int, decided_by: str) -> dict[str, Any] | None:
        """active → rolled_back. None si la règle n'est pas active."""
        ...

    async def current_version(self) -> int: ...


class PostgresRuleStore:
    """Écrit avec le compte de DATABASE_URL, comme le reste du contrôle des packages."""

    def __init__(self, db: Database, table: str = "package_rules") -> None:
        if table not in _TABLES:
            raise ValueError(f"table de règles inconnue : {table}")
        self._db = db
        self._table = sql.Identifier("public", table)

    async def propose(self, kind: str, value: dict[str, Any], source_decision_id: UUID) -> dict[str, Any] | None:
        async with self._db.as_owner() as conn:
            cur = await conn.execute(
                sql.SQL("insert into {} (kind, value, source_decision_id) values (%s, %s, %s) "
                        "on conflict (kind, value) where status in ('proposed', 'active') do nothing "
                        "returning *").format(self._table),
                (kind, Jsonb(value), source_decision_id))
            return await cur.fetchone()

    async def rows(self, status: str | None = None) -> list[dict[str, Any]]:
        async with self._db.as_owner() as conn:
            cur = await conn.execute(
                sql.SQL("select * from {} where %s::text is null or status = %s order by id").format(self._table),
                (status, status))
            return await cur.fetchall()

    async def active(self, kind: str) -> list[dict[str, Any]]:
        async with self._db.as_owner() as conn:
            cur = await conn.execute(
                sql.SQL("select * from {} where status = 'active' and kind = %s order by id").format(self._table),
                (kind,))
            return await cur.fetchall()

    async def get(self, rule_id: int) -> dict[str, Any] | None:
        async with self._db.as_owner() as conn:
            cur = await conn.execute(sql.SQL("select * from {} where id = %s").format(self._table), (rule_id,))
            return await cur.fetchone()

    async def apply(self, rule_id: int, decided_by: str) -> dict[str, Any] | None:
        return await self._transition(rule_id, decided_by, PROPOSED, ACTIVE)

    async def rollback(self, rule_id: int, decided_by: str) -> dict[str, Any] | None:
        return await self._transition(rule_id, decided_by, ACTIVE, ROLLED_BACK)

    async def current_version(self) -> int:
        async with self._db.as_owner() as conn:
            cur = await conn.execute("select current_version from public.ruleset_meta")
            row = await cur.fetchone()
            return row["current_version"] if row else 0

    async def _transition(self, rule_id: int, decided_by: str, before: str, after: str) -> dict[str, Any] | None:
        # La version et l'horodatage sont posés par le trigger rules_apply_transition.
        async with self._db.as_owner() as conn:
            cur = await conn.execute(
                sql.SQL("update {} set status = %s, decided_by = %s where id = %s and status = %s "
                        "returning *").format(self._table),
                (after, UUID(decided_by), rule_id, before))
            return await cur.fetchone()


class RulesetVersion:
    """Compteur en mémoire, partagé entre les listes comme public.ruleset_meta."""

    def __init__(self) -> None:
        self.current = 0

    def bump(self) -> int:
        self.current += 1
        return self.current


class MemoryRuleStore:
    """État en mémoire, pour les tests et la preuve hors base."""

    def __init__(self, meta: RulesetVersion | None = None) -> None:
        self.meta = meta or RulesetVersion()
        self.rules: list[dict[str, Any]] = []

    async def propose(self, kind: str, value: dict[str, Any], source_decision_id: UUID) -> dict[str, Any] | None:
        if any(r["kind"] == kind and r["value"] == value and r["status"] in (PROPOSED, ACTIVE)
               for r in self.rules):
            return None
        rule = {"id": len(self.rules) + 1, "kind": kind, "value": dict(value), "status": PROPOSED,
                "version": None, "source_decision_id": source_decision_id,
                "proposed_at": datetime.now(timezone.utc), "decided_by": None, "decided_at": None}
        self.rules.append(rule)
        return dict(rule)

    async def rows(self, status: str | None = None) -> list[dict[str, Any]]:
        return [dict(r) for r in self.rules if status is None or r["status"] == status]

    async def active(self, kind: str) -> list[dict[str, Any]]:
        return [dict(r) for r in self.rules if r["status"] == ACTIVE and r["kind"] == kind]

    async def get(self, rule_id: int) -> dict[str, Any] | None:
        return next((dict(r) for r in self.rules if r["id"] == rule_id), None)

    async def apply(self, rule_id: int, decided_by: str) -> dict[str, Any] | None:
        return self._transition(rule_id, decided_by, PROPOSED, ACTIVE)

    async def rollback(self, rule_id: int, decided_by: str) -> dict[str, Any] | None:
        return self._transition(rule_id, decided_by, ACTIVE, ROLLED_BACK)

    async def current_version(self) -> int:
        return self.meta.current

    def _transition(self, rule_id: int, decided_by: str, before: str, after: str) -> dict[str, Any] | None:
        rule = next((r for r in self.rules if r["id"] == rule_id and r["status"] == before), None)
        if rule is None:
            return None
        version = self.meta.bump()
        rule.update(status=after, decided_by=UUID(decided_by), decided_at=datetime.now(timezone.utc))
        if after == ACTIVE:
            rule["version"] = version
        return dict(rule)
