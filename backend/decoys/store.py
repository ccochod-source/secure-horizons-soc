"""Registre des leurres dans le schéma public.

Un leurre est une ligne de public.decoys (son nom et son emplacement) et un
contenu planté : un document ou un fichier marqué is_decoy. La valeur du
honeytoken n'est rangée nulle part ailleurs que dans ce contenu.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Protocol
from uuid import UUID, uuid4

from common.db import Database

ALERT_SOURCE = "detecteur_piege"
ALERT_SIGNAL = "decoy_access"


@dataclass(frozen=True)
class DecoyRow:
    id: UUID
    label: str
    location: str
    decoy_type: str


@dataclass(frozen=True)
class DecoyDocument:
    id: UUID
    title: str
    content: str


@dataclass(frozen=True)
class DecoyFile:
    id: UUID
    repository: str
    path: str
    content: str


@dataclass(frozen=True)
class Lures:
    rows: list[DecoyRow] = field(default_factory=list)
    documents: list[DecoyDocument] = field(default_factory=list)
    files: list[DecoyFile] = field(default_factory=list)


class DecoyStore(Protocol):
    async def lures(self) -> Lures: ...

    async def repositories(self) -> dict[str, UUID]: ...

    async def plant_document(self, title: str, doc_type: str, content: str) -> bool:
        """Vrai si le document piège vient d'être créé, faux s'il existait déjà."""
        ...

    async def plant_file(self, repository_id: UUID, path: str, file_type: str, content: str) -> bool: ...

    async def register(self, label: str, decoy_type: str, location: str) -> bool: ...

    async def record_trigger(self, decoy_ids: list[UUID], alert: dict[str, Any]) -> UUID:
        """Compte le déclenchement sur chaque leurre et lève l'alerte, d'un seul tenant."""
        ...


class PostgresDecoyStore:
    """Écrit avec le compte de DATABASE_URL : aucun rôle dédié n'existe encore pour ce bloc."""

    def __init__(self, db: Database) -> None:
        self._db = db

    async def lures(self) -> Lures:
        async with self._db.as_owner() as conn:
            cur = await conn.execute("select id, label, location, decoy_type from public.decoys")
            rows = [DecoyRow(**r) for r in await cur.fetchall()]
            cur = await conn.execute("select id, title, content from public.documents where is_decoy")
            documents = [DecoyDocument(**r) for r in await cur.fetchall()]
            cur = await conn.execute(
                "select f.id, r.name as repository, f.path, f.content from public.repo_files f "
                "join public.repositories r on r.id = f.repository_id where f.is_decoy")
            files = [DecoyFile(**r) for r in await cur.fetchall()]
        return Lures(rows, documents, files)

    async def repositories(self) -> dict[str, UUID]:
        async with self._db.as_owner() as conn:
            cur = await conn.execute("select name, id from public.repositories")
            return {r["name"]: r["id"] for r in await cur.fetchall()}

    async def plant_document(self, title: str, doc_type: str, content: str) -> bool:
        async with self._db.as_owner() as conn:
            cur = await conn.execute(
                "insert into public.documents (title, doc_type, content, is_decoy) "
                "select %s, %s, %s, true where not exists ("
                "  select 1 from public.documents where is_decoy and title = %s) returning id",
                (title, doc_type, content, title))
            return await cur.fetchone() is not None

    async def plant_file(self, repository_id: UUID, path: str, file_type: str, content: str) -> bool:
        async with self._db.as_owner() as conn:
            # Un vrai fichier au même chemin n'est jamais écrasé.
            cur = await conn.execute(
                "insert into public.repo_files (repository_id, path, file_type, sensitivity, content, "
                "contains_fake_secret, is_decoy) values (%s, %s, %s, 'secret', %s, true, true) "
                "on conflict (repository_id, path) do nothing returning id",
                (repository_id, path, file_type, content))
            return await cur.fetchone() is not None

    async def register(self, label: str, decoy_type: str, location: str) -> bool:
        async with self._db.as_owner() as conn:
            cur = await conn.execute(
                "insert into public.decoys (decoy_type, label, location) "
                "select %s, %s, %s where not exists (select 1 from public.decoys where label = %s) "
                "returning id", (decoy_type, label, location, label))
            return await cur.fetchone() is not None

    async def record_trigger(self, decoy_ids: list[UUID], alert: dict[str, Any]) -> UUID:
        async with self._db.as_owner() as conn:
            if decoy_ids:
                await conn.execute(
                    "update public.decoys set trigger_count = trigger_count + 1, "
                    "first_triggered_at = coalesce(first_triggered_at, now()) where id = any(%s)",
                    (decoy_ids,))
            cur = await conn.execute(
                "insert into public.alerts (run_id, trace_id, event_id, severity, source, signal, "
                "affected_agent, summary, status) values (%s, %s, %s, %s, %s, %s, %s, %s, 'open') "
                "returning id",
                (alert["run_id"], alert["trace_id"], alert["event_id"], alert["severity"],
                 ALERT_SOURCE, ALERT_SIGNAL, alert["affected_agent"], alert["summary"]))
            return (await cur.fetchone())["id"]


class MemoryDecoyStore:
    """Leurres en mémoire, pour les tests et le développement hors ligne."""

    def __init__(self, repositories: tuple[str, ...] = ("monorepo-app", "infra-tools")) -> None:
        self._repositories = {name: uuid4() for name in repositories}
        self.rows: list[DecoyRow] = []
        self.documents: list[DecoyDocument] = []
        self.files: list[DecoyFile] = []
        self.real_files: set[tuple[UUID, str]] = set()
        self.triggers: dict[UUID, int] = {}
        self.first_triggered: dict[UUID, datetime] = {}
        self.alerts: list[dict[str, Any]] = []

    async def lures(self) -> Lures:
        return Lures(list(self.rows), list(self.documents), list(self.files))

    async def repositories(self) -> dict[str, UUID]:
        return dict(self._repositories)

    async def plant_document(self, title: str, doc_type: str, content: str) -> bool:
        if any(d.title == title for d in self.documents):
            return False
        self.documents.append(DecoyDocument(uuid4(), title, content))
        return True

    async def plant_file(self, repository_id: UUID, path: str, file_type: str, content: str) -> bool:
        name = next(n for n, i in self._repositories.items() if i == repository_id)
        if (repository_id, path) in self.real_files or any(
                (f.repository, f.path) == (name, path) for f in self.files):
            return False
        self.files.append(DecoyFile(uuid4(), name, path, content))
        return True

    async def register(self, label: str, decoy_type: str, location: str) -> bool:
        if any(r.label == label for r in self.rows):
            return False
        self.rows.append(DecoyRow(uuid4(), label, location, decoy_type))
        return True

    async def record_trigger(self, decoy_ids: list[UUID], alert: dict[str, Any]) -> UUID:
        for decoy_id in decoy_ids:
            self.triggers[decoy_id] = self.triggers.get(decoy_id, 0) + 1
            self.first_triggered.setdefault(decoy_id, datetime.now(timezone.utc))
        alert_id = uuid4()
        self.alerts.append({"id": alert_id, "source": ALERT_SOURCE, "signal": ALERT_SIGNAL,
                            "status": "open", **alert})
        return alert_id
