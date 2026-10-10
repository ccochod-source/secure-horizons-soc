"""Load shared private configuration, then launch Alex's existing backend.

No checkout, merge, dependency installation or source changes are performed.
"""
import argparse
import os
from pathlib import Path
import sys

from dotenv import dotenv_values
from .config import ROOT, Settings


def main():
    parser = argparse.ArgumentParser(description="Lancer le backend d'Alex avec les mêmes jetons que la passerelle.")
    parser.add_argument("--backend-dir", type=Path, default=ROOT / "backend")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--mock-llm", action="store_true", help="Seulement pour les tests : enquêteur scripté.")
    args = parser.parse_args()
    folder = args.backend_dir.resolve()
    if not (folder / "main.py").is_file():
        raise SystemExit("Dossier backend d'Alex absent. Indiquer --backend-dir vers son checkout existant.")
    settings = Settings.from_env()
    private = {**dotenv_values(ROOT / ".env.victim"), **{k: v for k, v in os.environ.items() if v}}
    data = ROOT / ".runtime"
    data.mkdir(exist_ok=True)
    os.environ.update(
        PASSERELLE_TOKEN=settings.alex_token, ANALYSTE_TOKEN=private["ANALYSTE_TOKEN"],
        CONFINEMENT_TOKEN=settings.confinement_token,
        # The current RAG assistant is read-only and exposes no tool to suspend.
        # Leave confinement unconfigured until a real guarded tool exists.
        CONFINEMENT_URL="",
        OPENAI_API_KEY=settings.openai_key, OPENAI_MODEL=settings.model,
        SQLITE_PATH=str(data / f"alex-{args.port}-incidents.sqlite"),
        CHECKPOINT_PATH=str(data / f"alex-{args.port}-checkpoints.sqlite"),
        MOCK_LLM="1" if args.mock_llm else "0", FRONTEND_ORIGIN="http://localhost:3100",
    )
    if not settings.alex_token or not private.get("ANALYSTE_TOKEN"):
        raise SystemExit("Créer les jetons privés avec python -m victim_agent.cli init.")
    os.chdir(folder)
    os.execv(sys.executable, [sys.executable, "-m", "uvicorn", "main:app", "--host", "127.0.0.1", "--port", str(args.port)])


if __name__ == "__main__":
    main()
