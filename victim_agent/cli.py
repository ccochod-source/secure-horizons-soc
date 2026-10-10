"""Command-line access to the local RAG assistant."""

import argparse
import asyncio
import json
from pathlib import Path
import secrets

import httpx

from .config import ROOT, Settings


def initialize_gateway_token():
    path = ROOT / ".env.victim"
    content = path.read_text() if path.exists() else ""
    name = "VICTIM_GATEWAY_TOKEN"
    configured = any(
        line.startswith(name + "=") and line.split("=", 1)[1].strip()
        for line in content.splitlines()
    )
    if not configured:
        content = content.rstrip() + "\n" + name + "=" + secrets.token_urlsafe(32) + "\n"
        path.write_text(content)
        path.chmod(0o600)
        print("Jeton local créé dans .env.victim. Sa valeur n’est pas affichée.")
    else:
        print("Le jeton local est déjà configuré.")


async def main(args):
    if args.command == "init":
        initialize_gateway_token()
        return

    settings = Settings.from_env()
    headers = {"Authorization": "Bearer " + settings.gateway_token}
    base = "http://127.0.0.1:8001"
    async with httpx.AsyncClient(timeout=45) as client:
        if args.command == "chat":
            response = await client.post(
                base + "/chat",
                headers=headers,
                json={"question": " ".join(args.question)},
            )
        else:
            response = await client.get(base + "/health", headers=headers)
        response.raise_for_status()
        print(json.dumps(response.json(), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Utiliser l’assistant RAG local.")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("init", help="Créer le jeton privé du service local.")
    commands.add_parser("health", help="Vérifier l’API, Supabase et le modèle.")
    commands.add_parser("chat", help="Poser une question à l’assistant RAG.").add_argument(
        "question", nargs="+", help="Question en langage naturel."
    )
    try:
        asyncio.run(main(parser.parse_args()))
    except httpx.HTTPStatusError as exc:
        raise SystemExit(f"Échec HTTP {exc.response.status_code} : vérifier les services et les accès.") from None
    except (httpx.HTTPError, RuntimeError, ValueError) as exc:
        raise SystemExit("Échec : vérifier la configuration et les services locaux.") from exc
