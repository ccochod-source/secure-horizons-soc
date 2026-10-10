"""Réglages communs aux tests : pas d'appel OpenAI, et une base jetable.

Par défaut : fichiers SQLite temporaires.
Pour tester sur PostgreSQL :  TEST_DATABASE_URL=postgresql://... python -m pytest -q
(un schéma temporaire est créé, jamais le schéma « trace » des vrais incidents)
"""
import os
import sys
import tempfile
import uuid

DOSSIER = tempfile.mkdtemp(prefix="trace-tests-")
os.environ["MOCK_LLM"] = "1"
os.environ["SQLITE_PATH"] = os.path.join(DOSSIER, "trace.sqlite")
os.environ["CHECKPOINT_PATH"] = os.path.join(DOSSIER, "checkpoints.sqlite")
os.environ.pop("DATABASE_URL", None)
if os.getenv("TEST_DATABASE_URL"):
    os.environ["DATABASE_URL"] = os.environ["TEST_DATABASE_URL"]
    os.environ["DATABASE_SCHEMA"] = f"test_{uuid.uuid4().hex[:8]}"
for variable in ("CONFINEMENT_URL", "PASSERELLE_TOKEN", "ANALYSTE_TOKEN"):
    os.environ.pop(variable, None)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
