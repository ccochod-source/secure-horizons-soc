"""Vérifie sur la vraie base que la version des listes s'incrémente toute seule.

    cd backend
    .venv/bin/python -m scripts.learning_db_check

Crée une règle de test au nom explicite, l'applique puis l'annule au nom du
premier analyste autorisé. Elle finit à l'état « rolled_back » (rien ne se
supprime) et n'a donc aucun effet ; le compteur ruleset_meta monte de 2.
"""

from __future__ import annotations

import asyncio
import sys

from common.config import load_settings
from common.db import Database
from common.rules import PostgresRuleStore

VALUE = {"ecosystem": "pypi", "name": "zz-test-auto-increment-ne-pas-utiliser"}


async def main() -> int:
    db = Database(load_settings().database_url)
    await db.open()
    ok = True

    def check(label: str, passed: bool, detail: str = "") -> None:
        nonlocal ok
        ok = ok and passed
        print(f"{'OK    ' if passed else 'ECHEC '} {label}{' — ' + detail if detail else ''}")

    async def refused(query: str, params: tuple) -> str | None:
        try:
            async with db.as_owner() as conn:
                await conn.execute(query, params)
        except Exception as exc:
            return str(exc).splitlines()[0]
        return None

    try:
        rules = PostgresRuleStore(db)
        async with db.as_owner() as conn:
            cur = await conn.execute("select user_id from public.analysts where can_approve_packages limit 1")
            row = await cur.fetchone()
        if row is None:
            print("Aucun analyste autorisé dans public.analysts : test impossible.")
            return 1
        analyst = str(row["user_id"])
        start = await rules.current_version()
        print(f"Version de départ : {start}")

        rule = await rules.propose("known_malicious", VALUE, None)
        if rule is None:
            print("Une règle de test identique est déjà proposée ou active : rien n'a été fait.")
            return 1
        check("proposition créée sans toucher au compteur",
              rule["status"] == "proposed" and rule["version"] is None and await rules.current_version() == start)
        check("doublon refusé", await rules.propose("known_malicious", VALUE, None) is None)

        error = await refused("update public.package_rules set status = 'active' where id = %s", (rule["id"],))
        check("application sans analyste refusée", error is not None, error or "acceptée")

        applied = await rules.apply(rule["id"], analyst)
        check("apply : la règle prend la version suivante",
              applied is not None and applied["status"] == "active" and applied["version"] == start + 1
              and str(applied["decided_by"]) == analyst and await rules.current_version() == start + 1,
              f"version de la règle {applied and applied['version']}, compteur {await rules.current_version()}")
        check("second apply refusé", await rules.apply(rule["id"], analyst) is None)

        rolled = await rules.rollback(rule["id"], analyst)
        check("rollback : le compteur avance encore, la version d'activation reste",
              rolled is not None and rolled["status"] == "rolled_back" and rolled["version"] == start + 1
              and await rules.current_version() == start + 2,
              f"compteur {await rules.current_version()}")

        error = await refused(
            "update public.package_rules set status = 'active', decided_by = %s where id = %s",
            (analyst, rule["id"]))
        check("réactivation après annulation refusée", error is not None, error or "acceptée")
        check("la ligne existe toujours et plus aucune règle de test n'est active",
              await rules.get(rule["id"]) is not None
              and not any(r["value"] == VALUE for r in await rules.active("known_malicious")))
        print(f"Version finale : {await rules.current_version()} (départ {start})")
    finally:
        await db.close()
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
