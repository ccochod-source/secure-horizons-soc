"""Les vrais serveurs d'outils vers lesquels la passerelle relaie."""

from __future__ import annotations

import inspect
import json
from contextlib import AsyncExitStack
from dataclasses import dataclass, field
from typing import Any, Callable, Protocol

from mcp import Client, StdioServerParameters


@dataclass(frozen=True)
class ToolSpec:
    name: str
    description: str
    input_schema: dict[str, Any] = field(default_factory=dict)


class Upstream(Protocol):
    name: str

    async def list_tools(self) -> list[ToolSpec]: ...

    async def call_tool(self, tool: str, args: dict[str, Any]) -> Any: ...


class ToolError(RuntimeError):
    """L'outil a répondu par une erreur."""


class McpUpstream:
    """Un serveur MCP : URL (Streamable HTTP), commande stdio, ou serveur en mémoire."""

    def __init__(self, name: str, server: Any | StdioServerParameters | str) -> None:
        self.name = name
        self._server = server
        self._stack: AsyncExitStack | None = None
        self._client: Client | None = None

    async def start(self) -> None:
        self._stack = AsyncExitStack()
        # cache=None : les descriptions d'outils sont relues à chaque enregistrement,
        # une description modifiée après coup (tool poisoning) ne doit pas être masquée.
        self._client = await self._stack.enter_async_context(Client(self._server, cache=None))

    async def close(self) -> None:
        if self._stack is not None:
            await self._stack.aclose()
        self._stack = self._client = None

    def _connected(self) -> Client:
        if self._client is None:
            raise RuntimeError(f"serveur MCP {self.name} non démarré")
        return self._client

    async def list_tools(self) -> list[ToolSpec]:
        client = self._connected()
        specs: list[ToolSpec] = []
        cursor: str | None = None
        while True:
            page = await client.list_tools(cursor=cursor)
            specs += [ToolSpec(t.name, t.description or "", dict(t.input_schema or {})) for t in page.tools]
            cursor = page.next_cursor
            if not cursor:
                return specs

    async def call_tool(self, tool: str, args: dict[str, Any]) -> Any:
        result = await self._connected().call_tool(tool, args)
        texts = [block.text for block in result.content if getattr(block, "type", None) == "text"]
        if result.is_error:
            raise ToolError("\n".join(texts) or f"erreur de l'outil {tool}")
        if result.structured_content is not None:
            return result.structured_content
        text = "\n".join(texts)
        try:
            # Sans schéma de sortie, le SDK sérialise dict et listes en texte JSON.
            parsed = json.loads(text)
        except ValueError:
            return {"result": text}
        return parsed if isinstance(parsed, (dict, list)) else {"result": text}


class InProcessUpstream:
    """Des fonctions Python exposées comme outils, sans serveur MCP (tests, démo locale)."""

    def __init__(self, name: str) -> None:
        self.name = name
        self._tools: dict[str, tuple[ToolSpec, Callable[..., Any]]] = {}

    def add(self, fn: Callable[..., Any], *, name: str | None = None, description: str | None = None) -> None:
        spec = ToolSpec(name or fn.__name__, description if description is not None else (fn.__doc__ or ""))
        self._tools[spec.name] = (spec, fn)

    async def list_tools(self) -> list[ToolSpec]:
        return [spec for spec, _ in self._tools.values()]

    async def call_tool(self, tool: str, args: dict[str, Any]) -> Any:
        result = self._tools[tool][1](**args)
        return await result if inspect.isawaitable(result) else result
