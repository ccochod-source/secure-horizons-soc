"""Passerelle de traçage : point de passage obligatoire entre l'agent et ses outils.

Chaque requête, document récupéré, appel d'outil et réponse devient un
événement de public.events, pseudonymisé, relié à sa cause par parent_event_id.
Si la trace ne peut pas être écrite, rien n'est relayé ni rendu à l'agent.
"""

from __future__ import annotations

import inspect
import json
import logging
from dataclasses import dataclass
from typing import Any, Awaitable, Callable, Literal
from uuid import UUID, uuid4

from gateway.events import EventRecord, EventStore
from gateway.hooks import DecoyLayer, Direction, NoDecoys, PackageControl, PackagesBlocked
from gateway.session import Session
from gateway.upstream import ToolSpec, Upstream
from vault.pseudonymize import Pseudonymizer

logger = logging.getLogger(__name__)

INSTALL_TOOL = "install_package"
MAX_CONTENT_CHARS = 20_000

# Statuts rendus par le contrôle des packages → résultat de l'événement.
_PACKAGE_RESULTS = {"installed": "success", "blocked_pending_review": "pending", "blocked": "blocked"}

_DOCUMENT_EVENTS = {
    "document": ("document_retrieved", "retrieve"),
    "email": ("email_read", "read"),
    "file": ("file_read", "read"),
}
DocumentSource = Literal["document", "email", "file"]


class GatewayError(RuntimeError):
    pass


class UnknownSession(GatewayError):
    pass


class UnknownTool(GatewayError):
    pass


class ToolFailed(GatewayError):
    """L'outil, ou un bloc de protection, a échoué ; l'échec est tracé."""


class TraceUnavailable(GatewayError):
    """L'événement n'a pas pu être écrit : l'opération est refusée."""


@dataclass(frozen=True)
class _Registered:
    upstream: Upstream
    spec: ToolSpec
    description_event: UUID


class Gateway:
    def __init__(
        self,
        events: EventStore,
        pseudonymizer: Pseudonymizer,
        *,
        decoys: DecoyLayer | None = None,
        packages: PackageControl | None = None,
    ) -> None:
        self._events = events
        self._pseudonymizer = pseudonymizer
        self._decoys: DecoyLayer = decoys or NoDecoys()
        self._packages: PackageControl = packages or PackagesBlocked()
        self._tools: dict[str, _Registered] = {}
        self._sessions: dict[UUID, Session] = {}

    # --- serveurs et outils -------------------------------------------------

    async def register(self, upstream: Upstream) -> list[ToolSpec]:
        """Enregistre un serveur et trace le texte de chaque description d'outil.

        Les descriptions sont tracées avant tout appel : c'est ce qui permet de
        repérer une description piégée (tool poisoning) puis d'y remonter.
        """
        specs = await upstream.list_tools()
        trace_id = uuid4()
        server_event = await self._write(
            trace_id=trace_id, run_id=None, parent=None,
            event_type="mcp_server_registered", actor_type="system", actor_id="passerelle",
            action="register", result="success", resource_type="mcp_server", resource_id=upstream.name,
            content={"server": upstream.name, "tools": [s.name for s in specs]},
        )
        for spec in specs:
            description_event = await self._write(
                trace_id=trace_id, run_id=None, parent=server_event,
                event_type="tool_description", actor_type="tool", actor_id=upstream.name,
                action="describe", result="success", resource_type="mcp_tool", resource_id=spec.name,
                content={"name": spec.name, "description": spec.description, "input_schema": spec.input_schema},
                metadata={"mcp_server": upstream.name},
            )
            if spec.name in self._tools and self._tools[spec.name].upstream.name != upstream.name:
                logger.warning("outil %s redéfini par le serveur %s", spec.name, upstream.name)
            self._tools[spec.name] = _Registered(upstream, spec, description_event)
        return specs

    def tools(self) -> list[dict[str, Any]]:
        return [
            {"name": r.spec.name, "description": r.spec.description, "input_schema": r.spec.input_schema,
             "server": r.upstream.name}
            for r in self._tools.values()
        ]

    # --- sessions -----------------------------------------------------------

    def open_session(
        self, agent_id: str, *, user_id: str | None = None, trace_id: UUID | None = None,
        run_id: UUID | None = None,
    ) -> Session:
        session = Session(agent_id=agent_id, user_id=user_id, run_id=run_id)
        if trace_id is not None:
            if trace_id in self._sessions:
                raise GatewayError(f"session déjà ouverte : {trace_id}")
            session.trace_id = trace_id
        self._sessions[session.trace_id] = session
        return session

    def session(self, trace_id: UUID) -> Session:
        try:
            return self._sessions[trace_id]
        except KeyError:
            raise UnknownSession(str(trace_id)) from None

    # --- ce que l'agent voit et dit -----------------------------------------

    async def record_query(self, session: Session, text: str) -> UUID:
        """La requête de l'utilisateur, premier événement de la conversation."""
        async with session.lock:
            return await self._record(
                session, event_type="user_request", actor_type="user",
                actor_id=session.user_id or "utilisateur", action="query", result="success",
                content={"text": text},
            )

    async def record_document(
        self, session: Session, *, source: DocumentSource, resource_id: str, content: str,
        title: str | None = None,
    ) -> UUID:
        """Un document, e-mail ou fichier arrivé dans le contexte de l'agent (callback RAG)."""
        event_type, action = _DOCUMENT_EVENTS[source]
        async with session.lock:
            event_id = await self._record(
                session, event_type=event_type, actor_type="agent", actor_id=session.agent_id,
                action=action, result="success", resource_type=source, resource_id=resource_id,
                content={"title": title, "text": content},
            )
            await self._watch(session, source, {"resource_id": resource_id, "title": title, "text": content}, "result")
            return event_id

    async def record_response(self, session: Session, text: str) -> UUID:
        """La réponse finale de l'agent à l'utilisateur."""
        async with session.lock:
            event_id = await self._record(
                session, event_type="agent_response", actor_type="agent", actor_id=session.agent_id,
                action="respond", result="success", content={"text": text},
            )
            await self._watch(session, "agent_response", {"text": text}, "call")
            return event_id

    async def _watch(self, session: Session, channel: str, payload: Any, direction: Direction) -> None:
        """Contenu passé hors appel d'outil : un leurre y déroute aussi la session.

        Le contenu est déjà chez l'agent, rien n'est à bloquer ici ; une panne du
        détecteur ne doit donc pas faire échouer l'enregistrement.
        """
        if session.diverted:
            return
        try:
            if await _maybe_await(self._decoys.trips(session, channel, payload, direction)):
                session.diverted = True
        except Exception as exc:
            logger.error("détecteur de leurres en échec sur %s (%s)", channel, type(exc).__name__)

    # --- appels d'outils ----------------------------------------------------

    async def dispatch(self, session: Session, tool: str, args: dict[str, Any] | None = None) -> Any:
        """Trace l'appel, le soumet aux deux blocs de protection, puis relaie ou non."""
        args = dict(args or {})
        async with session.lock:
            registered = self._tools.get(tool)
            is_install = tool == INSTALL_TOOL
            metadata: dict[str, Any] = {}
            if registered is not None:
                metadata = {
                    "mcp_server": registered.upstream.name,
                    "tool_description_event_id": str(registered.description_event),
                }

            if registered is None and not is_install:
                await self._record(
                    session, event_type="tool_call", actor_type="agent", actor_id=session.agent_id,
                    action=tool, result="denied", resource_type="mcp_tool", resource_id=tool,
                    content={"arguments": args}, metadata={"reason": "unknown_tool"},
                )
                raise UnknownTool(tool)

            # Le résultat d'un appel est porté par son événement enfant (tool_response).
            if is_install:
                resource = ("package", _package_ref(args))
                call_id = await self._record(
                    session, event_type="package_install_requested", actor_type="agent",
                    actor_id=session.agent_id, action=tool, resource_type=resource[0],
                    resource_id=resource[1], content={"arguments": args}, metadata=metadata,
                )
            else:
                resource = ("mcp_tool", tool)
                call_id = await self._record(
                    session, event_type="tool_call", actor_type="agent", actor_id=session.agent_id,
                    action=tool, resource_type=resource[0], resource_id=resource[1],
                    content={"arguments": args}, metadata=metadata,
                )

            async def respond(result: str | None, outcome: Any, actor: tuple[str, str], **extra: Any) -> None:
                await self._record(
                    session, parent=call_id, event_type="tool_response", actor_type=actor[0],
                    actor_id=actor[1], action=tool, result=result, resource_type=resource[0],
                    resource_id=resource[1], content=outcome, metadata=extra,
                )

            async def guarded(actor: tuple[str, str], call: Callable[[], Any]) -> Any:
                try:
                    return await _maybe_await(call())
                except Exception as exc:
                    await respond("error", {"error": f"{type(exc).__name__}: {exc}"}, actor)
                    raise ToolFailed(tool) from exc

            async def divert() -> Any:
                session.diverted = True
                tarpit = ("system", "tarpit")
                payload = await guarded(tarpit, lambda: self._decoys.tarpit_response(session, tool, args))
                size = len(json.dumps(payload, ensure_ascii=False, default=str))
                await respond("blocked", {"decoy": True, "size": size}, tarpit, diverted=True)
                return payload

            async def trips(payload: Any, direction: Direction) -> bool:
                detector = ("system", "detecteur_piege")
                return bool(await guarded(detector, lambda: self._decoys.trips(session, tool, payload, direction)))

            # Bloc 1 : couche de leurres. Une session déroutée ne touche plus rien de réel.
            if session.diverted or await trips(args, "call"):
                return await divert()

            # Bloc 2 : contrôle des packages. install_package n'est jamais relayé tel quel.
            if is_install:
                control = ("system", "controle_packages")
                outcome = await guarded(control, lambda: self._packages.review(session, call_id, **args))
                status = outcome.get("status") if isinstance(outcome, dict) else None
                await respond(_PACKAGE_RESULTS.get(status), {"result": outcome}, control, package_status=status)
                return outcome

            source = ("tool", tool)
            outcome = await guarded(source, lambda: registered.upstream.call_tool(tool, args))
            if await trips(outcome, "result"):
                return await divert()
            await respond("success", {"result": outcome}, source)
            return outcome

    # --- lecture ------------------------------------------------------------

    async def graph(self, trace_id: UUID) -> dict[str, list[dict[str, Any]]]:
        """Nœuds et arêtes « a causé » d'une conversation, au format React Flow."""
        rows = await self._events.graph(trace_id)
        ids = {str(row["event_id"]) for row in rows}
        nodes = [
            {"id": str(row["event_id"]), "type": row["event_type"],
             "data": {k: _plain(v) for k, v in row.items() if k not in ("event_id", "parent_event_id")}}
            for row in rows
        ]
        edges = [
            {"id": f"{row['parent_event_id']}->{row['event_id']}", "source": str(row["parent_event_id"]),
             "target": str(row["event_id"])}
            for row in rows
            if row["parent_event_id"] is not None and str(row["parent_event_id"]) in ids
        ]
        return {"nodes": nodes, "edges": edges}

    # --- écriture -----------------------------------------------------------

    async def _record(self, session: Session, *, parent: UUID | None = None, **event: Any) -> UUID:
        event_id = await self._write(
            trace_id=session.trace_id, run_id=session.run_id, parent=parent or session.last_event, **event
        )
        session.last_event = event_id
        return event_id

    async def _write(
        self, *, trace_id: UUID, run_id: UUID | None, parent: UUID | None, event_type: str,
        actor_type: str, actor_id: str, action: str | None = None, result: str | None = None,
        resource_type: str | None = None, resource_id: str | None = None, content: Any = None,
        metadata: dict[str, Any] | None = None,
    ) -> UUID:
        try:
            safe = await self._pseudonymizer.pseudonymize(
                {"actor_id": actor_id, "resource_id": resource_id, "content": content, "metadata": metadata or {}}
            )
            fields = safe.value
            meta = dict(fields["metadata"])
            body = None
            if content is not None:
                body = json.dumps(fields["content"], ensure_ascii=False)
                if len(body) > MAX_CONTENT_CHARS:
                    body = body[:MAX_CONTENT_CHARS]
                    meta["content_truncated"] = True
            if safe.tokens:
                meta["tokens"] = list(safe.tokens)
            return await self._events.insert(
                EventRecord(
                    trace_id=trace_id, parent_event_id=parent, run_id=run_id, event_type=event_type,
                    actor_type=actor_type, actor_id=fields["actor_id"], action=action, result=result,
                    resource_type=resource_type, resource_id=fields["resource_id"], content=body,
                    metadata=meta,
                )
            )
        except Exception as exc:
            # Le message d'origine peut citer le contenu : on ne remonte que son type.
            raise TraceUnavailable(f"événement {event_type} non tracé ({type(exc).__name__})") from exc


def _package_ref(args: dict[str, Any]) -> str:
    ref = f"{args.get('ecosystem', '?')}:{args.get('name', '?')}"
    return f"{ref}@{args['version']}" if args.get("version") else ref


def _plain(value: Any) -> Any:
    return value if value is None or isinstance(value, (bool, int, float, str)) else str(value)


async def _maybe_await(value: Any | Awaitable[Any]) -> Any:
    return await value if inspect.isawaitable(value) else value
