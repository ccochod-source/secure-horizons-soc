"""Connexion Postgres partagée.

Chaque opération s'exécute dans une transaction qui endosse d'abord le rôle
dédié de l'appelant (SET LOCAL ROLE) : la passerelle ne peut pas lire le
coffre, même si DATABASE_URL est un compte puissant. SET LOCAL reste valable
derrière le pooler Supabase en mode transaction.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import AsyncIterator

from psycopg import AsyncConnection, sql
from psycopg.rows import dict_row
from psycopg_pool import AsyncConnectionPool

ROLE_GATEWAY = "soc_gateway"
ROLE_CONFINEUR = "soc_confineur"
_ROLES = frozenset({ROLE_GATEWAY, ROLE_CONFINEUR})


class Database:
    def __init__(self, dsn: str, *, max_size: int = 5) -> None:
        self._pool = AsyncConnectionPool(
            dsn,
            min_size=1,
            max_size=max_size,
            open=False,
            # prepare_threshold=None : pas de requêtes préparées, exigé par le pooler.
            kwargs={"prepare_threshold": None, "row_factory": dict_row},
        )

    async def open(self) -> None:
        await self._pool.open(wait=True, timeout=15)

    async def close(self) -> None:
        await self._pool.close()

    @asynccontextmanager
    async def as_role(self, role: str) -> AsyncIterator[AsyncConnection]:
        if role not in _ROLES:
            raise ValueError(f"rôle inconnu : {role}")
        async with self._pool.connection() as conn:
            async with conn.transaction():
                await conn.execute(sql.SQL("set local role {}").format(sql.Identifier(role)))
                yield conn
