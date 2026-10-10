"""Correspondance valeur → jeton. La valeur réelle ne quitte jamais la base."""

from __future__ import annotations

import hashlib
import hmac
import secrets
from typing import Protocol, Sequence

from common.db import ROLE_GATEWAY, Database


class TokenStore(Protocol):
    async def tokens_for(self, items: Sequence[tuple[str, str]]) -> list[str]:
        """Pour chaque (préfixe, valeur), rend le jeton stable de la valeur."""
        ...


class PostgresTokenStore:
    """Délègue à public.pseudonymize_values : HMAC de la valeur, Supabase Vault, public.token_vault."""

    def __init__(self, db: Database) -> None:
        self._db = db

    async def tokens_for(self, items: Sequence[tuple[str, str]]) -> list[str]:
        if not items:
            return []
        prefixes = [prefix for prefix, _ in items]
        values = [value for _, value in items]
        async with self._db.as_role(ROLE_GATEWAY) as conn:
            cur = await conn.execute(
                "select public.pseudonymize_values(%s::text[], %s::text[]) as tokens", (prefixes, values)
            )
            row = await cur.fetchone()
        return list(row["tokens"])


class MemoryTokenStore:
    """Coffre en mémoire, pour les tests et le développement hors ligne."""

    def __init__(self, start: int = 101) -> None:
        self._key = secrets.token_bytes(32)
        self._by_hmac: dict[str, str] = {}
        self._values: dict[str, str] = {}
        self._next = start

    async def tokens_for(self, items: Sequence[tuple[str, str]]) -> list[str]:
        out = []
        for prefix, value in items:
            digest = hmac.new(self._key, value.encode(), hashlib.sha256).hexdigest()
            token = self._by_hmac.get(digest)
            if token is None:
                token = f"{prefix.upper()}_{self._next:03d}"
                self._next += 1
                self._by_hmac[digest] = token
                self._values[token] = value
            out.append(token)
        return out

    def reveal(self, token: str) -> str | None:
        return self._values.get(token)
