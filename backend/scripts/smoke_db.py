"""Essai réel contre la base Supabase : la passerelle, le coffre et le contrôle des packages écrivent-ils ?

    cd backend && .venv/bin/python -m scripts.smoke_db          # écrit, vérifie, puis nettoie
    cd backend && .venv/bin/python -m scripts.smoke_db --keep   # laisse les lignes en base

Le secret d'essai est fabriqué à l'exécution. Prérequis : .env et migration 20.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import secrets
import string
import sys
from uuid import uuid4

import httpx

from app.main import create_app
from common.config import ConfigError, load_settings
from common.db import ROLE_GATEWAY, Database
from gateway import Gateway
from gateway.events import PostgresEventStore
from gateway.upstream import InProcessUpstream
from packages import LocalQuarantine, PackageReviewer, PostgresReviewStore
from packages.routes import SupabaseAuth
from vault import Pseudonymizer, Scanner
from vault.reveal import reveal
from vault.tokens import PostgresTokenStore

UPSTREAM = "mcp_smoke"
AGENT = "smoke-test"


class Report:
    def __init__(self) -> None:
        self.failed = 0

    def check(self, label: str, ok: bool, detail: str = "") -> bool:
        self.failed += not ok
        print(f"  [{'OK' if ok else 'ÉCHEC'}] {label}" + (f" — {detail}" if detail else ""))
        return ok


async def _denied(db: Database, query: str) -> bool:
    """Vrai si le rôle de la passerelle se voit refuser la requête."""
    try:
        async with db.as_role(ROLE_GATEWAY) as conn:
            await conn.execute(query)
    except Exception as exc:
        return "permission denied" in str(exc).lower()
    return False


async def main(keep: bool) -> int:
    report = Report()
    try:
        settings = load_settings()
    except ConfigError as exc:
        print(f"Configuration : {exc}")
        return 2
    db = Database(settings.database_url)
    await db.open()
    http = httpx.AsyncClient(timeout=20, follow_redirects=True)
    secret = "AKIA" + "".join(secrets.choice(string.ascii_uppercase + string.digits) for _ in range(16))
    package = "soc-smoke-" + secrets.token_hex(6)
    trace_id = None
    token = None
    try:
        print("1. Rôles de la migration 20")
        async with db.as_owner() as conn:
            cur = await conn.execute(
                "select rolname from pg_roles where rolname in ('soc_gateway', 'soc_confineur')")
            roles = {row["rolname"] for row in await cur.fetchall()}
        if not report.check("rôles soc_gateway et soc_confineur présents", len(roles) == 2,
                            "" if len(roles) == 2 else "appliquer la migration 20 puis relancer"):
            return 1

        print("2. Passerelle : un appel d'outil tracé et pseudonymisé")
        pseudonymizer = Pseudonymizer(PostgresTokenStore(db), Scanner())
        events = PostgresEventStore(db)
        reviewer = PackageReviewer(PostgresReviewStore(db), events, pseudonymizer, http,
                                   LocalQuarantine(settings.package_quarantine_dir))
        gateway = Gateway(events, pseudonymizer, packages=reviewer)
        upstream = InProcessUpstream(UPSTREAM)
        upstream.add(lambda text: {"echo": text}, name="smoke_echo", description="Renvoie le texte reçu.")
        await gateway.register(upstream)
        session = gateway.open_session(AGENT, user_id="smoke")
        trace_id = session.trace_id
        await gateway.record_query(session, "essai de la passerelle")
        result = await gateway.dispatch(session, "smoke_echo", {"text": f"clé {secret}"})
        report.check("l'agent reçoit la vraie réponse de l'outil", result == {"echo": f"clé {secret}"})
        async with db.as_owner() as conn:
            cur = await conn.execute(
                "select id, parent_event_id, event_type, content, metadata from public.events "
                "where trace_id = %s order by occurred_at, id", (trace_id,))
            rows = await cur.fetchall()
        report.check("3 événements écrits (requête, appel, réponse)",
                     [r["event_type"] for r in rows] == ["user_request", "tool_call", "tool_response"],
                     ", ".join(r["event_type"] for r in rows))
        ids = {r["id"] for r in rows}
        report.check("chaîne parent_event_id complète",
                     bool(rows) and rows[0]["parent_event_id"] is None
                     and all(r["parent_event_id"] in ids for r in rows[1:]))
        tokens = [t for r in rows for t in r["metadata"].get("tokens", []) if t.startswith("SECRET_AWS_")]
        token = tokens[0] if tokens else None
        report.check("le secret est remplacé par un jeton SECRET_AWS_…", token is not None, str(token))
        graph = await gateway.graph(trace_id)
        report.check("graphe de provenance reconstruit", len(graph["nodes"]) == 3 and len(graph["edges"]) == 2,
                     f"{len(graph['nodes'])} nœuds, {len(graph['edges'])} arêtes")

        print("3. Coffre : Supabase Vault et HMAC")
        if token is not None:
            async with db.as_owner() as conn:
                cur = await conn.execute(
                    "select token_prefix, value_hmac, vault_secret_id from public.token_vault where token = %s",
                    (token,))
                entry = await cur.fetchone()
            report.check("entrée dans token_vault avec empreinte HMAC et référence Vault",
                         entry is not None and len(entry["value_hmac"]) == 64 and entry["vault_secret_id"] is not None)
            again = (await pseudonymizer.pseudonymize(f"encore {secret}")).tokens
            report.check("le même secret redonne le même jeton", list(again) == [token])
            report.check("le Confineur retrouve la valeur réelle", await reveal(db, token) == secret)
        report.check("la passerelle ne peut pas lire token_vault",
                     await _denied(db, "select 1 from public.token_vault limit 1"))
        report.check("la passerelle ne peut pas appeler vault_reveal",
                     await _denied(db, "select public.vault_reveal('SECRET_X_000')"))

        print("4. Contrôle des packages : revue et alerte")
        request = await gateway.dispatch(session, "install_package", {"ecosystem": "pypi", "name": package})
        report.check("un nom inventé est bloqué en attente de décision",
                     request.get("status") == "blocked_pending_review", str(request.get("status")))
        async with db.as_owner() as conn:
            cur = await conn.execute(
                "select id, state, risk_level, checks from public.package_reviews where trace_id = %s", (trace_id,))
            reviews = await cur.fetchall()
            cur = await conn.execute(
                "select severity, source, signal, status, summary from public.alerts where trace_id = %s", (trace_id,))
            alerts = await cur.fetchall()
        report.check("revue en pending_approval avec score et signaux",
                     len(reviews) == 1 and reviews[0]["state"] == "pending_approval"
                     and reviews[0]["checks"].get("score") == 1.0 and bool(reviews[0]["checks"].get("signals")))
        report.check("alerte suspicious_package_install levée",
                     len(alerts) == 1 and alerts[0]["signal"] == "suspicious_package_install")
        async with db.as_owner() as conn:
            cur = await conn.execute(
                "select count(*) as n from public.events where trace_id = %s and event_type = 'dependency_installed'",
                (trace_id,))
            report.check("rien n'est installé", (await cur.fetchone())["n"] == 0)

        print("5. Décision humaine : la route refuse un appel non authentifié")
        if reviews:
            auth = (SupabaseAuth(http, settings.supabase_url, settings.supabase_api_key)
                    if settings.supabase_url and settings.supabase_api_key else None)
            app = create_app(gateway=gateway, packages=reviewer, analyst_auth=auth)
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://smoke") as api:
                url, body = f"/packages/{reviews[0]['id']}/decision", {"decision": "approve"}
                if auth is None:
                    refused = await api.post(url, json=body, headers={"authorization": "Bearer faux"})
                    report.check("sans SUPABASE_URL ni clé, la route est fermée (503)", refused.status_code == 503)
                else:
                    report.check("sans jeton : 401", (await api.post(url, json=body)).status_code == 401)
                    forged = await api.post(url, json=body, headers={"authorization": "Bearer jeton.invente.xyz"})
                    report.check("jeton inventé, vérifié par Supabase Auth : 401", forged.status_code == 401,
                                 f"HTTP {forged.status_code}")
            async with db.as_owner() as conn:
                cur = await conn.execute("select state from public.package_reviews where id = %s", (reviews[0]["id"],))
                report.check("la revue attend toujours", (await cur.fetchone())["state"] == "pending_approval")

        print("6. Aucune valeur en clair hors du coffre")
        async with db.as_owner() as conn:
            cur = await conn.execute(
                "select coalesce(string_agg(e::text, ' '), '') as dump from public.events e where trace_id = %s",
                (trace_id,))
            dump = (await cur.fetchone())["dump"]
            cur = await conn.execute(
                "select coalesce(string_agg(a::text, ' '), '') as dump from public.alerts a where trace_id = %s",
                (trace_id,))
            dump += (await cur.fetchone())["dump"]
            cur = await conn.execute(
                "select coalesce(string_agg(r::text, ' '), '') as dump from public.package_reviews r "
                "where trace_id = %s", (trace_id,))
            dump += (await cur.fetchone())["dump"]
            cur = await conn.execute(
                "select count(*) as n from public.token_vault t where t::text like %s", (f"%{secret}%",))
            in_index = (await cur.fetchone())["n"]
        report.check("le secret d'essai est absent de events, alerts et package_reviews", secret not in dump)
        report.check("token_vault ne contient que l'empreinte, pas la valeur", in_index == 0)
        return 1 if report.failed else 0
    finally:
        if trace_id is not None and not keep:
            try:
                async with db.as_owner() as conn:
                    await conn.execute("delete from public.alerts where trace_id = %s", (trace_id,))
                    await conn.execute("delete from public.package_reviews where trace_id = %s", (trace_id,))
                    await conn.execute(
                        "delete from public.events where trace_id = %s or actor_id = %s or resource_id = %s",
                        (trace_id, UPSTREAM, UPSTREAM))
                    if token is not None:
                        await conn.execute(
                            "delete from vault.secrets where id = (select vault_secret_id from "
                            "public.token_vault where token = %s)", (token,))
                        await conn.execute("delete from public.token_vault where token = %s", (token,))
                        await conn.execute("delete from public.token_vault_log where token = %s", (token,))
                print("Lignes d'essai supprimées.")
            except Exception as exc:
                print(f"Nettoyage incomplet ({type(exc).__name__}) : trace {trace_id}, jeton {token}.")
        elif trace_id is not None:
            print(f"Lignes conservées : trace {trace_id}.")
        print(json.dumps({"echecs": report.failed}))
        await http.aclose()
        await db.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--keep", action="store_true", help="ne pas supprimer les lignes d'essai")
    sys.exit(asyncio.run(main(parser.parse_args().keep)))
