"""Les cinq points de la relecture, plus l'authentification.

Lancer depuis le dossier backend :  python -m pytest -q
"""
import copy
import json
import os
import threading
from concurrent.futures import ThreadPoolExecutor

import pytest
from fastapi.testclient import TestClient

import execution
import main
import pipeline
import stockage

ICI = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ATTAQUE = json.load(open(os.path.join(ICI, "exemple_attaque.json"), encoding="utf-8"))
NORMAL = json.load(open(os.path.join(ICI, "exemple_normal.json"), encoding="utf-8"))
client = TestClient(main.app)


def creer_incident(lot=ATTAQUE) -> dict:
    reponse = client.post("/events", json=lot)
    assert reponse.status_code == 200, reponse.text
    return reponse.json()["incident"]


def etat_attaque(**enquete) -> dict:
    """Un état de pipeline prêt pour le vérificateur, avec une enquête choisie par le test."""
    events = pipeline.preparer_evenements(ATTAQUE["events"])
    etat = {"agent_id": "dev-01", "events": events}
    etat.update(pipeline.regle(etat))
    base = {"title": "t", "description": "d", "severity": "Critique", "conclusions": [],
            "action": "suspendre_outil", "cible": "github.publish", "impact": "i"}
    etat["enquete"] = {**base, **enquete}
    return etat


# 1. Pas de « Confiné » sans exécution réelle -----------------------------------------------------
def test_approbation_sans_passerelle_reste_en_attente():
    incident = creer_incident()
    fin = client.post(f"/incidents/{incident['id']}/decision", json={"decision": "approved", "analyst": "alex"}).json()
    assert fin["status"] == "Approuvé, en attente d'exécution"
    assert fin["execution"]["etat"] == "en_attente"

    # La passerelle confirme plus tard : là seulement, l'incident est confiné.
    fin = client.post(f"/incidents/{incident['id']}/execution", json={"etat": "execute", "detail": "outil retiré"}).json()
    assert fin["status"] == "Confiné"


def test_approbation_avec_passerelle_qui_confirme(monkeypatch):
    class Reponse:
        is_success, status_code, text = True, 200, "ok"
    envoye = {}
    monkeypatch.setenv("CONFINEMENT_URL", "https://passerelle.exemple/confiner")
    monkeypatch.setattr(execution.httpx, "post", lambda url, json, **k: envoye.update(json) or Reponse())
    incident = creer_incident()
    fin = client.post(f"/incidents/{incident['id']}/decision", json={"decision": "approved"}).json()
    assert fin["status"] == "Confiné"
    assert envoye["action"] == "suspendre_outil" and envoye["cible"] == "github.publish"


def test_approbation_avec_passerelle_injoignable(monkeypatch):
    monkeypatch.setenv("CONFINEMENT_URL", "http://127.0.0.1:9/confiner")
    incident = creer_incident()
    fin = client.post(f"/incidents/{incident['id']}/decision", json={"decision": "approved"}).json()
    assert fin["status"] == "Approuvé, en attente d'exécution"
    assert fin["execution"]["etat"] == "echec"


def test_execution_refusee_si_pas_approuve():
    incident = creer_incident()
    assert client.post(f"/incidents/{incident['id']}/execution", json={"etat": "execute"}).status_code == 409


# 2. Le vérificateur contrôle le contenu des preuves ---------------------------------------------
def test_conclusion_fausse_citant_un_evenement_normal_est_rejetee():
    # evt-003 (écriture d'un inventaire) existe et est dans la chaîne, mais ce n'est pas une lecture sensible.
    etat = etat_attaque(conclusions=[{"type": "lecture_sensible", "affirmation": "faux", "evidence_ids": ["evt-003"]}])
    sortie = pipeline.verificateur(etat)
    assert sortie["conclusions"][0]["verifiee"] is False
    assert sortie["confiance"] < pipeline.SEUIL_CONFIANCE


def test_evenement_hors_de_la_chaine_est_rejete():
    etat = etat_attaque(conclusions=[{"type": "sortie_externe", "affirmation": "x", "evidence_ids": ["evt-099"]}])
    etat["events"].append({**etat["events"][3], "id": "evt-099", "parent_event_id": None})  # sortie sans lien
    assert pipeline.verificateur(etat)["conclusions"][0]["verifiee"] is False


def test_dossier_juste_obtient_la_confiance_maximale():
    etat = etat_attaque(conclusions=[
        {"type": "instruction_suspecte", "affirmation": "a", "evidence_ids": ["evt-001"]},
        {"type": "propagation", "affirmation": "b", "evidence_ids": ["evt-002", "evt-004"]},
        {"type": "blocage", "affirmation": "c", "evidence_ids": ["evt-004"]}])
    sortie = pipeline.verificateur(etat)
    assert all(c["verifiee"] for c in sortie["conclusions"])
    assert sortie["confiance"] == 1.0


def test_conclusions_vraies_mais_incompletes_plafonnees():
    # Une seule conclusion vraie (la lecture), mais la sortie n'est jamais prouvée : pas 100 %.
    etat = etat_attaque(conclusions=[{"type": "lecture_sensible", "affirmation": "a", "evidence_ids": ["evt-002"]}])
    assert pipeline.verificateur(etat)["confiance"] <= 0.5


def test_cible_inventee_remplacee_par_l_action_de_la_regle():
    etat = etat_attaque(action="suspendre_outil", cible="tous les outils de l'entreprise")
    action = pipeline.verificateur(etat)["action"]
    assert action["origine"] == "regle" and action["cible"] == "github.publish"


def test_revocation_du_jeton_masque_acceptee():
    etat = etat_attaque(action="revoquer_secret", cible="SECRET_001")
    jeton = pipeline.JETON_SECRET.search(etat["events"][1]["description"]).group(0)
    etat["enquete"]["cible"] = jeton
    assert pipeline.verificateur(etat)["action"]["origine"] == "enqueteur"


# 3. Aucun secret dans le prompt ni dans les bases ------------------------------------------------
SECRET_URL = "Zx9QmL4tWv7RkP2s"


def lot_avec_secret_dans_resource() -> dict:
    lot = copy.deepcopy(ATTAQUE)
    lot["events"][3]["resource"] = f"external/https://evil.exemple/up?token={SECRET_URL}"
    lot["events"][2]["resource"] = f"https://bot:{SECRET_URL}@interne.exemple/inventaire"
    return lot


def test_secret_dans_resource_absent_du_prompt():
    events = pipeline.preparer_evenements(lot_avec_secret_dans_resource()["events"])
    etat = {"agent_id": "dev-01", "events": events}
    etat.update(pipeline.regle(etat))
    consigne = pipeline.construire_consigne(etat)
    assert SECRET_URL not in consigne and "sk-demo1234567890abcdef" not in consigne
    assert "SECRET_" in consigne


def test_secret_absent_des_fichiers_sqlite():
    incident = creer_incident(lot_avec_secret_dans_resource())
    client.post(f"/incidents/{incident['id']}/decision", json={"decision": "rejected"})
    for fichier in (os.environ["SQLITE_PATH"], os.environ["CHECKPOINT_PATH"]):
        contenu = open(fichier, "rb").read()
        assert SECRET_URL.encode() not in contenu, fichier
        assert b"sk-demo1234567890abcdef" not in contenu, fichier


# 4. Identifiants uniques, même avec des demandes simultanées -------------------------------------
def test_reservations_simultanees_toutes_differentes():
    with ThreadPoolExecutor(16) as pool:
        ids = list(pool.map(lambda _: stockage.reserver_identifiant(), range(200)))
    assert len(set(ids)) == 200
    for i in ids:
        stockage.liberer(i)


def test_deux_requetes_simultanees_deux_incidents():
    with ThreadPoolExecutor(2) as pool:
        incidents = list(pool.map(lambda _: creer_incident(), range(2)))
    assert incidents[0]["id"] != incidents[1]["id"]
    assert stockage.lire(incidents[0]["id"]) and stockage.lire(incidents[1]["id"])


def test_lot_normal_ne_cree_rien_et_libere_le_numero():
    avant = len(stockage.lister())
    assert client.post("/events", json=NORMAL).json()["incident"] is None
    assert len(stockage.lister()) == avant


def test_double_decision_simultanee_une_seule_passe():
    incident = creer_incident()
    with ThreadPoolExecutor(4) as pool:
        codes = list(pool.map(lambda _: client.post(f"/incidents/{incident['id']}/decision",
                                                    json={"decision": "approved"}).status_code, range(4)))
    assert sorted(codes) == [200, 409, 409, 409]


# 5. Une chaîne circulaire ne bloque pas le pipeline ----------------------------------------------
def test_chaine_circulaire_se_termine():
    lot = copy.deepcopy(ATTAQUE)
    lot["events"][0]["parent_event_id"] = "evt-004"  # evt-001 -> ... -> evt-004 -> evt-001
    lot["events"].append({**lot["events"][0], "id": "evt-boucle", "parent_event_id": "evt-boucle"})
    resultat = {}
    fil = threading.Thread(target=lambda: resultat.update(r=client.post("/events", json=lot)), daemon=True)
    fil.start()
    fil.join(timeout=10)
    assert not fil.is_alive(), "le pipeline tourne en boucle"
    assert resultat["r"].status_code == 200


# Authentification -------------------------------------------------------------------------------
def test_jetons_obligatoires_quand_configures(monkeypatch):
    monkeypatch.setenv("PASSERELLE_TOKEN", "jeton-passerelle")
    monkeypatch.setenv("ANALYSTE_TOKEN", "jeton-analyste")
    assert client.post("/events", json=ATTAQUE).status_code == 401
    reponse = client.post("/events", json=ATTAQUE, headers={"Authorization": "Bearer jeton-passerelle"})
    incident_id = reponse.json()["incident"]["id"]
    url = f"/incidents/{incident_id}/decision"
    assert client.post(url, json={"decision": "approved"}).status_code == 401
    # Le jeton de la passerelle ne permet pas de décider à la place de l'analyste.
    assert client.post(url, json={"decision": "approved"},
                       headers={"Authorization": "Bearer jeton-passerelle"}).status_code == 401
    assert client.post(url, json={"decision": "approved"},
                       headers={"Authorization": "Bearer jeton-analyste"}).status_code == 200
