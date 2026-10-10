"""Retrouver la valeur réelle d'un jeton. Réservé au Confineur (code déterministe).

Aucun autre module ne doit importer ce fichier : ni la passerelle, ni un agent
LLM. Chaque appel est journalisé dans public.token_vault_log.
"""

from __future__ import annotations

from common.db import ROLE_CONFINEUR, Database


class UnknownToken(LookupError):
    pass


async def reveal(db: Database, token: str) -> str:
    async with db.as_role(ROLE_CONFINEUR) as conn:
        cur = await conn.execute("select public.vault_reveal(%s) as value", (token,))
        row = await cur.fetchone()
    if row is None or row["value"] is None:
        raise UnknownToken(token)
    return row["value"]
