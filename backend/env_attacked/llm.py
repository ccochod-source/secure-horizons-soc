"""Appels LLM de l'agent victime : complétion avec outils (Mistral ou OpenAI) et embeddings.

La complétion de DevBot passe par Mistral dès qu'une clé Mistral est fournie (API compatible OpenAI).
Les embeddings restent sur OpenAI (text-embedding-3-small, 1536 dimensions) pour coller à la colonne
`documents.embedding` partagée ; sans clé OpenAI, la recherche documentaire retombe sur les mots-clés.
"""

from __future__ import annotations

from typing import Any, Protocol

import httpx

CHAT_URL = "https://api.openai.com/v1/chat/completions"
MISTRAL_CHAT_URL = "https://api.mistral.ai/v1/chat/completions"
EMBEDDINGS_URL = "https://api.openai.com/v1/embeddings"
EMBEDDING_MODEL = "text-embedding-3-small"  # 1536 dimensions, comme la colonne documents.embedding
SEED = 7
_PROVIDER_LABEL = {"openai": "OpenAI", "mistral": "Mistral"}


class LLMError(RuntimeError):
    pass


class ChatModel(Protocol):
    async def complete(self, messages: list[dict[str, Any]], tools: list[dict[str, Any]]) -> dict[str, Any]:
        """Rend le message de l'assistant (content et, s'il y en a, tool_calls)."""
        ...


class Embedder(Protocol):
    async def embed(self, texts: list[str]) -> list[list[float]]: ...


class OpenAIClient:
    """Client de l'agent victime. `provider` choisit l'API de complétion (openai/mistral).

    Les embeddings restent sur OpenAI : `embed_key` (clé OpenAI) peut différer de la clé de complétion.
    """

    def __init__(self, client: httpx.AsyncClient, api_key: str, model: str, *,
                 chat_url: str = CHAT_URL, provider: str = "openai",
                 embed_key: str | None = None, embed_model: str = EMBEDDING_MODEL) -> None:
        self._client = client
        self._headers = {"authorization": f"Bearer {api_key}"}
        self._model = model
        self._chat_url = chat_url
        self._provider = provider
        # Embeddings sur OpenAI : clé dédiée, ou la clé de complétion si celle-ci est déjà OpenAI.
        embed = embed_key or (api_key if provider == "openai" else None)
        self._embed_headers = {"authorization": f"Bearer {embed}"} if embed else None
        self._embed_model = embed_model

    async def complete(self, messages: list[dict[str, Any]], tools: list[dict[str, Any]]) -> dict[str, Any]:
        # Température 0 et graine fixe : la même question redonne la même attaque.
        # OpenAI attend « seed », Mistral « random_seed ».
        payload: dict[str, Any] = {"model": self._model, "messages": messages, "temperature": 0}
        payload["random_seed" if self._provider == "mistral" else "seed"] = SEED
        if tools:
            payload["tools"] = tools
        data = await self._post(self._chat_url, payload, self._headers)
        try:
            return data["choices"][0]["message"]
        except (KeyError, IndexError, TypeError) as exc:
            raise LLMError("réponse du modèle illisible") from exc

    async def embed(self, texts: list[str]) -> list[list[float]]:
        if self._embed_headers is None:
            raise LLMError("embeddings indisponibles : aucune clé OpenAI pour text-embedding-3-small")
        data = await self._post(EMBEDDINGS_URL, {"model": self._embed_model, "input": texts}, self._embed_headers)
        try:
            return [item["embedding"] for item in sorted(data["data"], key=lambda item: item["index"])]
        except (KeyError, TypeError) as exc:
            raise LLMError("réponse du modèle illisible") from exc

    async def _post(self, url: str, payload: dict[str, Any], headers: dict[str, str]) -> dict[str, Any]:
        try:
            response = await self._client.post(url, headers=headers, json=payload, timeout=90)
        except httpx.HTTPError as exc:
            raise LLMError(type(exc).__name__) from exc
        if response.status_code != 200:
            # Le corps de l'erreur peut citer la requête : on ne remonte que le code.
            label = _PROVIDER_LABEL.get("openai" if url == EMBEDDINGS_URL else self._provider, "Le modèle")
            raise LLMError(f"{label} a répondu HTTP {response.status_code}")
        try:
            return response.json()
        except ValueError as exc:
            raise LLMError("réponse du modèle illisible") from exc
