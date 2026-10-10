"""Écriture des traces dans public.events (ajout seul)."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol
from uuid import UUID, uuid4

from psycopg.types.json import Jsonb

from common.db import ROLE_GATEWAY, Database


@dataclass(frozen=True)
class EventRecord:
    """Un événement prêt à écrire : tout son contenu est déjà pseudonymisé."""

    trace_id: UUID
    event_type: str
    actor_type: str
    actor_id: str
    parent_event_id: UUID | None = None
    run_id: UUID | None = None
    action: str | None = None
    result: str | None = None
    resource_type: str | None = None
    resource_id: str | None = None
    content: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


class EventStore(Protocol):
    async def insert(self, event: EventRecord) -> UUID: ...

    async def graph(self, trace_id: UUID) -> list[dict[str, Any]]: ...


class PostgresEventStore:
    def __init__(self, db: Database) -> None:
        self._db = db

    async def insert(self, event: EventRecord) -> UUID:
        async with self._db.as_role(ROLE_GATEWAY) as conn:
            cur = await conn.execute(
                """
                insert into public.events (trace_id, parent_event_id, run_id, event_type, actor_type,
                                        actor_id, action, result, resource_type, resource_id,
                                        content, metadata)
                values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                returning id
                """,
                (
                    event.trace_id, event.parent_event_id, event.run_id, event.event_type,
                    event.actor_type, event.actor_id, event.action, event.result,
                    event.resource_type, event.resource_id, event.content, Jsonb(event.metadata),
                ),
            )
            row = await cur.fetchone()
        return row["id"]

    async def graph(self, trace_id: UUID) -> list[dict[str, Any]]:
        async with self._db.as_role(ROLE_GATEWAY) as conn:
            cur = await conn.execute("select * from public.provenance_graph(%s)", (trace_id,))
            return await cur.fetchall()


class MemoryEventStore:
    """Traces en mémoire, pour les tests et le développement hors ligne."""

    def __init__(self) -> None:
        self.events: list[tuple[UUID, EventRecord]] = []

    async def insert(self, event: EventRecord) -> UUID:
        if event.parent_event_id is not None and all(i != event.parent_event_id for i, _ in self.events):
            raise ValueError("parent_event_id inconnu")
        event_id = uuid4()
        self.events.append((event_id, event))
        return event_id

    async def graph(self, trace_id: UUID) -> list[dict[str, Any]]:
        return [
            {
                "event_id": i, "parent_event_id": e.parent_event_id, "event_type": e.event_type,
                "actor_type": e.actor_type, "actor_id": e.actor_id, "action": e.action,
                "result": e.result, "resource_type": e.resource_type, "resource_id": e.resource_id,
                "occurred_at": None,
            }
            for i, e in self.events
            if e.trace_id == trace_id
        ]
