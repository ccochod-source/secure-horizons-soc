"""Small read/write adapter for the existing Supabase REST API."""

from datetime import datetime, timezone
import asyncio
import re
from uuid import uuid4

import httpx

from .models import TraceEvent
from .security import Masker


class DatabaseError(RuntimeError):
    pass


def now():
    return datetime.now(timezone.utc).isoformat()


def search_terms(text: str) -> list[str]:
    words = re.findall(r"[^\W_]+", text, re.UNICODE)
    stopwords = {
        "a", "au", "aux", "avec", "ce", "ces", "dans", "de", "des", "du",
        "elle", "en", "est", "et", "il", "je", "la", "le", "les", "leur",
        "mais", "mon", "ne", "nos", "notre", "on", "ou", "par", "pas",
        "pour", "que", "qui", "sa", "se", "ses", "son", "sur", "un", "une",
        "vos", "votre", "comment", "quelle", "quelles", "quels", "quel",
    }
    useful = [word for word in words if len(word) > 2 and word.casefold() not in stopwords]
    return list(dict.fromkeys(useful or [word for word in words if len(word) > 1]))[:10]


def to_tsquery_or(text: str) -> str:
    # Tokens contain only letters and digits, so user punctuation cannot alter
    # Postgres full-text query operators.
    return " OR ".join(search_terms(text))


class SupabaseStore:
    def __init__(self, settings, client: httpx.AsyncClient):
        self.base = settings.supabase_url.rstrip("/") + "/rest/v1/"
        self.headers = {
            "apikey": settings.supabase_key,
            "Authorization": "Bearer " + settings.supabase_key,
        }
        self.client = client
        self.masker = Masker()

    async def request(self, method, table, *, params=None, body=None):
        headers = {**self.headers, "Prefer": "return=representation"}
        try:
            response = await self.client.request(
                method, self.base + table, params=params, json=body,
                headers=headers, timeout=12,
            )
        except httpx.HTTPError as exc:
            raise DatabaseError("Supabase est momentanément inaccessible.") from exc
        if response.is_error:
            try:
                error = response.json()
                code = error.get("code")
                message = error.get("message")
            except ValueError:
                code, message = None, None
            suffix = f" {code}: {message}" if code and message else ""
            raise DatabaseError(f"Lecture ou écriture Supabase refusée (HTTP {response.status_code}).{suffix}")
        try:
            payload = response.json()
        except ValueError as exc:
            raise DatabaseError("Réponse Supabase invalide.") from exc
        if not isinstance(payload, list):
            raise DatabaseError("Format de réponse Supabase inattendu.")
        return payload

    async def health(self):
        await self.request("GET", "documents", params={"select": "id", "limit": "1"})
        await self.request("GET", "events", params={"select": "id", "limit": "1"})

    async def search_documents(self, question: str, limit: int = 100):
        query = to_tsquery_or(question)
        if not query:
            return []

        common = {
            "select": "id,title,doc_type,source,content,is_decoy",
            "is_decoy": "eq.false",
            "limit": str(limit),
        }
        # The existing table has no combined title/content search function.
        # Search both indexed text fields independently, then merge by UUID.
        title_rows, content_rows = await asyncio.gather(
            self.request("GET", "documents", params={**common, "title": "wfts(simple)." + query}),
            self.request("GET", "documents", params={**common, "content": "wfts(simple)." + query}),
        )
        merged = {}
        for rank, rows in ((2, title_rows), (1, content_rows)):
            for row in rows:
                identifier = row.get("id")
                if not identifier or not isinstance(row.get("content"), str):
                    continue
                item = merged.setdefault(identifier, {**row, "_match_weight": 0})
                item["_match_weight"] += rank
        return sorted(merged.values(), key=lambda row: (-row["_match_weight"], row.get("title", "")))[:8]

    async def append_events(self, events: list[TraceEvent], agent_id: str, conversation_id: str):
        rows = []
        database_event_types = {
            "user_request": "user_request",
            "document_retrieved": "tool_call",
            "assistant_response": "tool_call",
        }
        for event in events:
            rows.append({
                "id": event.id,
                "run_id": None,
                "trace_id": conversation_id,
                "parent_event_id": event.parent_event_id,
                "occurred_at": event.timestamp,
                # Keep Léon's constrained event vocabulary in the table while
                # preserving the RAG-specific type for Alex in metadata.
                "event_type": database_event_types[event.type],
                "actor_type": "agent",
                "actor_id": agent_id,
                "action": event.tool,
                "result": "success" if event.result == "allowed" else event.result,
                "resource_type": "document" if event.type == "document_retrieved" else "rag_assistant",
                "resource_id": event.resource,
                "content": event.description,
                "metadata": {
                    "title": event.title,
                    "actor": event.actor,
                    "wire_type": event.type,
                    "wire_result": event.result,
                    "conversation_id": conversation_id,
                    **(event.metadata or {}),
                },
            })
        # Insert in causal order so every parent is already present for the
        # events.parent_event_id foreign key.
        for row, event in zip(rows, events, strict=True):
            saved = await self.request("POST", "events", body=self.masker.clean(row))
            if len(saved) != 1 or saved[0].get("id") != event.id:
                raise DatabaseError("Une trace de la conversation n’a pas été enregistrée.")


def new_event(*, parent, actor, kind, title, description, tool, resource, metadata=None):
    return TraceEvent(
        id=str(uuid4()), parent_event_id=parent, timestamp=now(), actor=actor,
        type=kind, title=title, description=description, tool=tool,
        resource=resource, result="allowed", metadata=metadata or {},
    )
