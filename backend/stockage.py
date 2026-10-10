"""Stockage des incidents dans un fichier SQLite (rien à installer).

Plus tard, on pourra passer à la base PostgreSQL de Léon sans changer le reste du code.
"""
import json
import os
import sqlite3
import threading

FICHIER = os.getenv("SQLITE_PATH", "trace.sqlite")
_verrou = threading.Lock()
_connexion = sqlite3.connect(FICHIER, check_same_thread=False)
_connexion.execute("CREATE TABLE IF NOT EXISTS incidents (id TEXT PRIMARY KEY, numero INTEGER, contenu TEXT)")
_connexion.commit()


def nouvel_identifiant() -> str:
    with _verrou:
        (dernier,) = _connexion.execute("SELECT COALESCE(MAX(numero), 0) FROM incidents").fetchone()
    return f"INC-{dernier + 1:04d}"


def enregistrer(incident: dict) -> None:
    numero = int(incident["id"].split("-")[-1])
    with _verrou:
        _connexion.execute("INSERT OR REPLACE INTO incidents VALUES (?, ?, ?)",
                           (incident["id"], numero, json.dumps(incident, ensure_ascii=False)))
        _connexion.commit()


def lire(incident_id: str) -> dict | None:
    with _verrou:
        ligne = _connexion.execute("SELECT contenu FROM incidents WHERE id = ?", (incident_id,)).fetchone()
    return json.loads(ligne[0]) if ligne else None


def lister() -> list[dict]:
    with _verrou:
        lignes = _connexion.execute("SELECT contenu FROM incidents ORDER BY numero DESC").fetchall()
    return [json.loads(l[0]) for l in lignes]
