"""Appels OpenAI de l'agent victime : complétion avec outils, et embeddings."""

from __future__ import annotations

from typing import Any, Protocol

import httpx

CHAT_URL = "https://api.openai.com/v1/chat/completions"
EMBEDDINGS_URL = "https://api.openai.com/v1/embeddings"
EMBEDDING_MODEL = "text-embedding-3-small"  # 1536 dimensions, comme la colonne documents.embedding
SEED = 7


class LLMError(RuntimeError):
    pass


class ChatModel(Protocol):
    async def complete(self, messages: list[dict[str, Any]], tools: list[dict[str, Any]]) -> dict[str, Any]:
        """Rend le message de l'assistant (content et, s'il y en a, tool_calls)."""
        ...


class Embedder(Protocol):
    async def embed(self, texts: list[str]) -> list[list[float]]: ...


class OpenAIClient:
    def __init__(self, client: httpx.AsyncClient, api_key: str, model: str) -> None:
        self._client = client
        self._headers = {"authorization": f"Bearer {api_key}"}
        self._model = model

    async def complete(self, messages: list[dict[str, Any]], tools: list[dict[str, Any]]) -> dict[str, Any]:
        # Température 0 et graine fixe : la même question redonne la même attaque.
        payload: dict[str, Any] = {"model": self._model, "messages": messages, "temperature": 0, "seed": SEED}
        if tools:
            payload["tools"] = tools
        data = await self._post(CHAT_URL, payload)
        try:
            return data["choices"][0]["message"]
        except (KeyError, IndexError, TypeError) as exc:
            raise LLMError("réponse OpenAI illisible") from exc

    async def embed(self, texts: list[str]) -> list[list[float]]:
        data = await self._post(EMBEDDINGS_URL, {"model": EMBEDDING_MODEL, "input": texts})
        try:
            return [item["embedding"] for item in sorted(data["data"], key=lambda item: item["index"])]
        except (KeyError, TypeError) as exc:
            raise LLMError("réponse OpenAI illisible") from exc

    async def _post(self, url: str, payload: dict[str, Any]) -> dict[str, Any]:
        try:
            response = await self._client.post(url, headers=self._headers, json=payload, timeout=90)
        except httpx.HTTPError as exc:
            raise LLMError(type(exc).__name__) from exc
        if response.status_code != 200:
            # Le corps de l'erreur peut citer la requête : on ne remonte que le code.
            raise LLMError(f"OpenAI a répondu HTTP {response.status_code}")
        try:
            return response.json()
        except ValueError as exc:
            raise LLMError("réponse OpenAI illisible") from exc
