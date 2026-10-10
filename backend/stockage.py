"""Stockage des incidents dans un fichier SQLite (rien à installer).

Plus tard, on pourra passer à la base PostgreSQL de Léon sans changer le reste du code :
seules les fonctions de ce fichier touchent à la base.

Deux protections :
- L'identifiant d'un incident est RÉSERVÉ dès la réception des événements (compteur automatique de la base).
  Deux demandes simultanées ne peuvent donc jamais recevoir le même numéro ni s'écraser.
- Une décision d'analyste est « prise » de façon atomique : si deux clics arrivent en même temps,
  un seul passe, l'autre reçoit une erreur.
"""
import json
import os
import sqlite3
import threading

FICHIER = os.getenv("SQLITE_PATH", "trace.sqlite")
_verrou = threading.Lock()
_connexion = sqlite3.connect(FICHIER, check_same_thread=False)
# Nouvelle table (l'ancienne table « incidents » n'est plus lue) :
# numero = compteur automatique, contenu = NULL tant que l'incident n'est qu'une réservation.
_connexion.execute("""CREATE TABLE IF NOT EXISTS incidents_v2 (
    numero INTEGER PRIMARY KEY AUTOINCREMENT,
    id TEXT UNIQUE,
    contenu TEXT,
    decision_prise INTEGER NOT NULL DEFAULT 0)""")
_connexion.commit()


def reserver_identifiant() -> str:
    """Réserve un numéro unique (INC-0001, INC-0002...) avant même de lancer le pipeline."""
    with _verrou:
        numero = _connexion.execute("INSERT INTO incidents_v2 (id) VALUES (NULL)").lastrowid
        incident_id = f"INC-{numero:04d}"
        _connexion.execute("UPDATE incidents_v2 SET id = ? WHERE numero = ?", (incident_id, numero))
        _connexion.commit()
    return incident_id


def liberer(incident_id: str) -> None:
    """Supprime une réservation qui n'a pas donné d'incident (rien de suspect, ou erreur)."""
    with _verrou:
        _connexion.execute("DELETE FROM incidents_v2 WHERE id = ? AND contenu IS NULL", (incident_id,))
        _connexion.commit()


def enregistrer(incident: dict) -> None:
    with _verrou:
        _connexion.execute("UPDATE incidents_v2 SET contenu = ? WHERE id = ?",
                           (json.dumps(incident, ensure_ascii=False), incident["id"]))
        _connexion.commit()


def lire(incident_id: str) -> dict | None:
    with _verrou:
        ligne = _connexion.execute("SELECT contenu FROM incidents_v2 WHERE id = ? AND contenu IS NOT NULL",
                                   (incident_id,)).fetchone()
    return json.loads(ligne[0]) if ligne else None


def lister() -> list[dict]:
    with _verrou:
        lignes = _connexion.execute(
            "SELECT contenu FROM incidents_v2 WHERE contenu IS NOT NULL ORDER BY numero DESC").fetchall()
    return [json.loads(l[0]) for l in lignes]


def prendre_decision(incident_id: str) -> bool:
    """Vrai pour le premier clic seulement. Les suivants (même simultanés) reçoivent Faux."""
    with _verrou:
        modifie = _connexion.execute(
            "UPDATE incidents_v2 SET decision_prise = 1 WHERE id = ? AND decision_prise = 0 AND contenu IS NOT NULL",
            (incident_id,)).rowcount
        _connexion.commit()
    return modifie == 1


def rendre_decision(incident_id: str) -> None:
    """Annule la prise de décision si son application a planté, pour pouvoir recliquer."""
    with _verrou:
        _connexion.execute("UPDATE incidents_v2 SET decision_prise = 0 WHERE id = ?", (incident_id,))
        _connexion.commit()
