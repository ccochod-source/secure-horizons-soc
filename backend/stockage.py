"""Stockage des incidents : la base Supabase de l'équipe (PostgreSQL), ou un fichier SQLite pour tester seul.

- DATABASE_URL défini (chaîne de connexion Supabase) : tout va dans Supabase, dans le schéma « trace ».
  Ce schéma n'est pas exposé par l'API publique de Supabase : seul le backend, avec son mot de passe, y accède.
- DATABASE_URL vide : fichier SQLite local (SQLITE_PATH), pratique pour les tests sans réseau.

Seules les fonctions de ce fichier touchent à la base ; le reste du code ne sait pas laquelle est utilisée.

Deux protections :
- L'identifiant d'un incident est RÉSERVÉ dès la réception des événements (compteur automatique de la base).
  Deux demandes simultanées ne peuvent donc jamais recevoir le même numéro ni s'écraser.
- Une décision d'analyste est « prise » de façon atomique : si deux clics arrivent en même temps,
  un seul passe, l'autre reçoit une erreur.
"""
import atexit
import json
import os
import re
import sqlite3
import threading

DATABASE_URL = os.getenv("DATABASE_URL", "")
SCHEMA = os.getenv("DATABASE_SCHEMA", "trace")
if not re.fullmatch(r"[a-z_][a-z0-9_]*", SCHEMA):
    raise ValueError("DATABASE_SCHEMA ne doit contenir que des minuscules, chiffres et _")


def options_postgres() -> dict:
    """Réglages de connexion communs (aussi utilisés par la mémoire du pipeline).
    prepare_threshold=None : compatible avec les deux « poolers » de Supabase."""
    return {"autocommit": True, "prepare_threshold": None, "options": f"-c search_path={SCHEMA}"}


class _Resultat:
    """Les lignes lues et le nombre de lignes modifiées, récupérés avant de rendre la connexion."""
    def __init__(self, lignes, rowcount):
        self.lignes, self.rowcount = lignes, rowcount

    def fetchone(self):
        return self.lignes[0] if self.lignes else None

    def fetchall(self):
        return self.lignes or []


if DATABASE_URL:
    # ------------------------------------------------------------------ Supabase / PostgreSQL
    from psycopg_pool import ConnectionPool

    _pool = ConnectionPool(DATABASE_URL, kwargs=options_postgres(), min_size=1, max_size=5, open=True)
    atexit.register(_pool.close)
    with _pool.connection() as _c:
        _c.execute(f"CREATE SCHEMA IF NOT EXISTS {SCHEMA}")
        _c.execute(f"""CREATE TABLE IF NOT EXISTS {SCHEMA}.incidents (
            numero BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            id TEXT UNIQUE,
            agent_id TEXT,
            statut TEXT,
            contenu JSONB,
            decision_prise BOOLEAN NOT NULL DEFAULT FALSE,
            cree_le TIMESTAMPTZ NOT NULL DEFAULT now(),
            maj_le TIMESTAMPTZ NOT NULL DEFAULT now())""")
        # Ceinture et bretelles : même si quelqu'un expose ce schéma, aucune lecture via l'API publique.
        _c.execute(f"ALTER TABLE {SCHEMA}.incidents ENABLE ROW LEVEL SECURITY")

    def _sql(requete: str, parametres: tuple = ()):
        with _pool.connection() as c:
            curseur = c.execute(requete.replace("?", "%s"), parametres)
            return _Resultat(curseur.fetchall() if curseur.description else None, curseur.rowcount)

    def reserver_identifiant() -> str:
        """Réserve un numéro unique (INC-0001, INC-0002...) avant même de lancer le pipeline."""
        with _pool.connection() as c, c.transaction():
            (numero,) = c.execute(f"INSERT INTO {SCHEMA}.incidents DEFAULT VALUES RETURNING numero").fetchone()
            incident_id = f"INC-{numero:04d}"
            c.execute(f"UPDATE {SCHEMA}.incidents SET id = %s WHERE numero = %s", (incident_id, numero))
        return incident_id

    def enregistrer(incident: dict) -> None:
        _sql(f"UPDATE {SCHEMA}.incidents SET contenu = ?::jsonb, agent_id = ?, statut = ?, maj_le = now() WHERE id = ?",
             (json.dumps(incident, ensure_ascii=False), incident["agentId"], incident["status"], incident["id"]))

    def _lire_contenu(ligne) -> dict:
        return ligne[0]  # psycopg renvoie déjà le JSONB sous forme de dictionnaire

    _VRAI, _FAUX = "TRUE", "FALSE"

else:
    # ------------------------------------------------------------------ fichier SQLite (tests en local)
    _verrou = threading.Lock()
    _connexion = sqlite3.connect(os.getenv("SQLITE_PATH", "trace.sqlite"), check_same_thread=False)
    # L'ancienne table « incidents » des premières versions n'est plus lue.
    _connexion.execute("""CREATE TABLE IF NOT EXISTS incidents_v2 (
        numero INTEGER PRIMARY KEY AUTOINCREMENT,
        id TEXT UNIQUE,
        contenu TEXT,
        decision_prise INTEGER NOT NULL DEFAULT 0)""")
    _connexion.commit()

    def _sql(requete: str, parametres: tuple = ()):
        requete = requete.replace(f"{SCHEMA}.incidents", "incidents_v2")
        with _verrou:
            curseur = _connexion.execute(requete, parametres)
            resultat = curseur.fetchall() if curseur.description else None
            _connexion.commit()
        return _Resultat(resultat, curseur.rowcount)

    def reserver_identifiant() -> str:
        """Réserve un numéro unique (INC-0001, INC-0002...) avant même de lancer le pipeline."""
        with _verrou:
            numero = _connexion.execute("INSERT INTO incidents_v2 (id) VALUES (NULL)").lastrowid
            incident_id = f"INC-{numero:04d}"
            _connexion.execute("UPDATE incidents_v2 SET id = ? WHERE numero = ?", (incident_id, numero))
            _connexion.commit()
        return incident_id

    def enregistrer(incident: dict) -> None:
        _sql(f"UPDATE {SCHEMA}.incidents SET contenu = ? WHERE id = ?",
             (json.dumps(incident, ensure_ascii=False), incident["id"]))

    def _lire_contenu(ligne) -> dict:
        return json.loads(ligne[0])

    _VRAI, _FAUX = "1", "0"


# ---------------------------------------------------------------------- commun aux deux bases
def liberer(incident_id: str) -> None:
    """Supprime une réservation qui n'a pas donné d'incident (rien de suspect, ou erreur)."""
    _sql(f"DELETE FROM {SCHEMA}.incidents WHERE id = ? AND contenu IS NULL", (incident_id,))


def lire(incident_id: str) -> dict | None:
    ligne = _sql(f"SELECT contenu FROM {SCHEMA}.incidents WHERE id = ? AND contenu IS NOT NULL",
                 (incident_id,)).fetchone()
    return _lire_contenu(ligne) if ligne else None


def lister() -> list[dict]:
    lignes = _sql(f"SELECT contenu FROM {SCHEMA}.incidents WHERE contenu IS NOT NULL ORDER BY numero DESC").fetchall()
    return [_lire_contenu(l) for l in lignes]


def prendre_decision(incident_id: str) -> bool:
    """Vrai pour le premier clic seulement. Les suivants (même simultanés) reçoivent Faux."""
    return _sql(f"UPDATE {SCHEMA}.incidents SET decision_prise = {_VRAI} "
                f"WHERE id = ? AND decision_prise = {_FAUX} AND contenu IS NOT NULL", (incident_id,)).rowcount == 1


def rendre_decision(incident_id: str) -> None:
    """Annule la prise de décision si son application a planté, pour pouvoir recliquer."""
    _sql(f"UPDATE {SCHEMA}.incidents SET decision_prise = {_FAUX} WHERE id = ?", (incident_id,))
