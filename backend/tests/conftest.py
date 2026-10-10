"""Réglages communs aux tests : pas d'appel OpenAI, et des fichiers SQLite jetables."""
import os
import sys
import tempfile

DOSSIER = tempfile.mkdtemp(prefix="trace-tests-")
os.environ["MOCK_LLM"] = "1"
os.environ["SQLITE_PATH"] = os.path.join(DOSSIER, "trace.sqlite")
os.environ["CHECKPOINT_PATH"] = os.path.join(DOSSIER, "checkpoints.sqlite")
for variable in ("CONFINEMENT_URL", "PASSERELLE_TOKEN", "ANALYSTE_TOKEN"):
    os.environ.pop(variable, None)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
