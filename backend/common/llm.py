"""Fabrique du modèle de chat des agents défenseurs.

Mistral dès que MISTRAL_API_KEY est présent (modèle par défaut : ministral-3b-2512),
sinon OpenAI. Les appels passent par LangChain (sortie structurée), comme avant.
"""
from __future__ import annotations

import os
from typing import Any


def mistral_enabled() -> bool:
    return bool(os.getenv("MISTRAL_API_KEY", "").strip())


def default_chat_model() -> str:
    if mistral_enabled():
        return os.getenv("MISTRAL_MODEL", "").strip() or "ministral-3b-2512"
    return os.getenv("OPENAI_MODEL", "").strip() or "gpt-4o-mini"


def build_chat(*, model: str | None = None, rate_limiter: Any = None,
               timeout: float | None = None, max_retries: int | None = None) -> Any:
    """Modèle de chat LangChain prêt pour `.with_structured_output(...)`."""
    name = model or default_chat_model()
    if mistral_enabled():
        from langchain_mistralai import ChatMistralAI
        kwargs: dict[str, Any] = {"model": name, "temperature": 0}
        if rate_limiter is not None:
            kwargs["rate_limiter"] = rate_limiter
        if timeout is not None:
            kwargs["timeout"] = timeout
        if max_retries is not None:
            kwargs["max_retries"] = max_retries
        return ChatMistralAI(**kwargs)
    from langchain_openai import ChatOpenAI
    kwargs = {"model": name}
    if rate_limiter is not None:
        kwargs["rate_limiter"] = rate_limiter
    if timeout is not None:
        kwargs["timeout"] = timeout
    if max_retries is not None:
        kwargs["max_retries"] = max_retries
    return ChatOpenAI(**kwargs)
