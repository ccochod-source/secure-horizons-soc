"""Données de la fausse entreprise lues par les outils de l'agent victime.

L'agent a volontairement trop de droits : ses outils lisent toute la
documentation et tous les fichiers, secrets compris, avec le compte de
DATABASE_URL. C'est l'axe « compte sur-privilégié » de la démo.
"""

from __future__ import annotations

import re
from typing import Any, Protocol
from uuid import UUID, uuid4

from common.db import Database

AGENT_MAILBOX = "assistant@demo-devco.example"
_WORD = re.compile(r"\w{4,}")


class CompanyData(Protocol):
    async def search_documents(
        self, query: str, embedding: list[float] | None, limit: int = 3
    ) -> list[dict[str, Any]]: ...

    async def list_files(self, directory: str) -> list[str]: ...

    async def read_file(self, path: str) -> dict[str, Any] | None: ...

    async def send_message(self, to: str, body: str) -> None: ...

    async def documents_without_embedding(self) -> list[dict[str, Any]]: ...

    async def set_embedding(self, document_id: UUID, embedding: list[float]) -> None: ...


def _vector(embedding: list[float]) -> str:
    return "[" + ",".join(f"{x:.8f}" for x in embedding) + "]"


class PostgresCompanyData:
    def __init__(self, db: Database) -> None:
        self._db = db

    async def search_documents(
        self, query: str, embedding: list[float] | None, limit: int = 3
    ) -> list[dict[str, Any]]:
        async with self._db.as_owner() as conn:
            if embedding is not None:
                cur = await conn.execute(
                    "select id, title, content from public.documents where review_status = 'approved' and embedding is not null "
                    "order by embedding operator(extensions.<=>) %s::extensions.vector limit %s",
                    (_vector(embedding), limit))
                rows = await cur.fetchall()
                if rows:
                    return rows
            # Sans index vectoriel : recherche par mots, les titres comptent double.
            words = [f"%{w}%" for w in dict.fromkeys(_WORD.findall(query.lower()))][:8]
            if not words:
                return []
            cur = await conn.execute(
                "select id, title, content from ("
                "  select d.id, d.title, d.content, d.created_at, ("
                "    select count(*) filter (where d.content ilike w) + 2 * count(*) filter (where d.title ilike w)"
                "    from unnest(%s::text[]) w) as score from public.documents d "
                "    where d.review_status = 'approved') ranked "
                "where score > 0 order by score desc, created_at limit %s", (words, limit))
            return await cur.fetchall()

    async def list_files(self, directory: str) -> list[str]:
        prefix = directory.strip().strip("/").removeprefix("./")
        async with self._db.as_owner() as conn:
            cur = await conn.execute(
                "select r.name || '/' || f.path as path from public.repo_files f "
                "join public.repositories r on r.id = f.repository_id "
                "where f.review_status = 'approved' and (%s = '' or f.path like %s or r.name || '/' || f.path like %s) "
                "order by 1 limit 200",
                (prefix, prefix + "%", prefix + "%"))
            return [row["path"] for row in await cur.fetchall()]

    async def read_file(self, path: str) -> dict[str, Any] | None:
        wanted = path.strip().removeprefix("./")
        async with self._db.as_owner() as conn:
            cur = await conn.execute(
                "select r.name || '/' || f.path as path, f.content from public.repo_files f "
                "join public.repositories r on r.id = f.repository_id "
                "where f.review_status = 'approved' and (f.path = %s or r.name || '/' || f.path = %s) "
                "order by r.name desc limit 1",
                (wanted, wanted))
            return await cur.fetchone()

    async def send_message(self, to: str, body: str) -> None:
        async with self._db.as_owner() as conn:
            await conn.execute(
                "insert into public.mailbox (sender, recipient, subject, body, is_read) "
                "values (%s, %s, %s, %s, true)", (AGENT_MAILBOX, to, "[sortant] Message de l'assistant", body))

    async def documents_without_embedding(self) -> list[dict[str, Any]]:
        async with self._db.as_owner() as conn:
            cur = await conn.execute(
                "select id, title, content from public.documents "
                "where review_status = 'approved' and embedding is null order by created_at")
            return await cur.fetchall()

    async def set_embedding(self, document_id: UUID, embedding: list[float]) -> None:
        async with self._db.as_owner() as conn:
            await conn.execute(
                "update public.documents set embedding = %s::extensions.vector where id = %s",
                (_vector(embedding), document_id))


class MemoryCompanyData:
    """Fausse entreprise en mémoire, pour les tests et le développement hors ligne."""

    def __init__(self) -> None:
        self.documents: list[dict[str, Any]] = []
        self.files: dict[str, str] = {}
        self.sent: list[dict[str, str]] = []

    def add_document(self, title: str, content: str, embedding: list[float] | None = None) -> UUID:
        document_id = uuid4()
        self.documents.append({"id": document_id, "title": title, "content": content, "embedding": embedding})
        return document_id

    async def search_documents(
        self, query: str, embedding: list[float] | None, limit: int = 3
    ) -> list[dict[str, Any]]:
        embedded = [d for d in self.documents if d["embedding"] is not None]
        if embedding is not None and embedded:
            ranked = sorted(embedded, key=lambda d: -sum(a * b for a, b in zip(d["embedding"], embedding)))
        else:
            words = set(_WORD.findall(query.lower()))
            scored = [(sum((w in d["content"].lower()) + 2 * (w in d["title"].lower()) for w in words), d)
                      for d in self.documents]
            ranked = [d for score, d in sorted(scored, key=lambda s: -s[0]) if score > 0]
        return [{"id": d["id"], "title": d["title"], "content": d["content"]} for d in ranked[:limit]]

    async def list_files(self, directory: str) -> list[str]:
        prefix = directory.strip().strip("/").removeprefix("./")
        return sorted(p for p in self.files if p.startswith(prefix) or p.split("/", 1)[-1].startswith(prefix))

    async def read_file(self, path: str) -> dict[str, Any] | None:
        wanted = path.strip().removeprefix("./")
        for full, content in self.files.items():
            if wanted in (full, full.split("/", 1)[-1]):
                return {"path": full, "content": content}
        return None

    async def send_message(self, to: str, body: str) -> None:
        self.sent.append({"to": to, "body": body})

    async def documents_without_embedding(self) -> list[dict[str, Any]]:
        return [{"id": d["id"], "title": d["title"], "content": d["content"]}
                for d in self.documents if d["embedding"] is None]

    async def set_embedding(self, document_id: UUID, embedding: list[float]) -> None:
        next(d for d in self.documents if d["id"] == document_id)["embedding"] = embedding
