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
    for nom, contenu in contenu_brut_des_bases():
        assert SECRET_URL.encode() not in contenu, nom
        assert b"sk-demo1234567890abcdef" not in contenu, nom


def contenu_brut_des_bases():
    """Tout ce qui est écrit sur disque : incidents ET mémoire du pipeline."""
    if not stockage.DATABASE_URL:
        for fichier in (os.environ["SQLITE_PATH"], os.environ["CHECKPOINT_PATH"]):
            yield fichier, open(fichier, "rb").read()
        return
    import psycopg
    with psycopg.connect(stockage.DATABASE_URL) as c:
        tables = [t for (t,) in c.execute("SELECT table_name FROM information_schema.tables WHERE table_schema = %s",
                                          (stockage.SCHEMA,))]
        for table in tables:
            for ligne in c.execute(f'SELECT * FROM {stockage.SCHEMA}."{table}"'):
                yield table, b"".join(v if isinstance(v, bytes) else str(v).encode() for v in ligne)


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


# 7. Contrôle des packages : les agents défenseurs enquêtent sur une installation refusée -------------
# Lots réels : sessions de la passerelle exportées depuis Supabase (voir le champ « _source »).
PACKAGE_SUSPECT = json.load(open(os.path.join(ICI, "exemple_package_suspect.json"), encoding="utf-8"))
PACKAGE_SAIN = json.load(open(os.path.join(ICI, "exemple_package_sain.json"), encoding="utf-8"))


def lot(source: dict) -> dict:
    return {"agent_id": source["agent_id"], "events": source["events"]}


def etat_package(**enquete) -> dict:
    events = pipeline.preparer_evenements(PACKAGE_SUSPECT["events"])
    etat = {"agent_id": "DevBot", "events": events}
    etat.update(pipeline.regle(etat))
    base = {"title": "t", "description": "d", "severity": "Élevée", "conclusions": [],
            "action": "suspendre_outil", "cible": "install_package", "impact": "i"}
    etat["enquete"] = {**base, **enquete}
    return etat


def test_package_refuse_declenche_la_regle():
    etat = {"agent_id": "DevBot", "events": pipeline.preparer_evenements(PACKAGE_SUSPECT["events"])}
    alerte = pipeline.regle(etat)["alerte"]
    assert alerte["motif"] == "installation d'un package bloquée par la passerelle"
    demande, refus = (next(e for e in etat["events"] if e["id"] == i) for i in alerte["evenements"])
    assert demande["type"] == "package_install_requested" and refus["type"] == "tool_response"


def test_package_sain_installe_ne_declenche_rien():
    reponse = client.post("/events", json=lot(PACKAGE_SAIN))
    assert reponse.status_code == 200
    assert reponse.json()["incident"] is None


def test_package_refuse_cree_un_incident_avec_enquete_verifiee():
    incident = creer_incident(lot(PACKAGE_SUSPECT))
    assert incident["status"] == "À examiner"
    assert incident["confidence"] == 1.0
    assert all(c["verifiee"] for c in incident["conclusions"])
    assert incident["action"] == {"type": "suspendre_outil", "cible": "install_package", "origine": "enqueteur", "correction": ""}


def test_conclusion_package_suspect_sans_le_refus_est_rejetee():
    demande = next(e["id"] for e in PACKAGE_SUSPECT["events"] if e["type"] == "package_install_requested")
    etat = etat_package(conclusions=[{"type": "package_suspect", "affirmation": "x", "evidence_ids": [demande]}])
    resultat = pipeline.verificateur(etat)
    assert not resultat["conclusions"][0]["verifiee"]
    assert resultat["confiance"] == 0


def test_conclusion_package_suspect_complete_est_acceptee():
    etat = etat_package()
    etat["enquete"]["conclusions"] = [{"type": "package_suspect", "affirmation": "x", "evidence_ids": etat["alerte"]["evenements"]}]
    resultat = pipeline.verificateur(etat)
    assert resultat["conclusions"][0]["verifiee"] and resultat["confiance"] == 1.0


def test_cible_inventee_pour_un_package_remplacee_par_l_outil_d_installation():
    etat = etat_package(cible="pip-inexistant")
    action = pipeline.verificateur(etat)["action"]
    assert action["origine"] == "regle" and action["cible"] == "install_package"


def test_installation_en_attente_compte_comme_un_blocage():
    """Cas réel : l'enquêteur cite la réponse « blocked_pending_review » de la passerelle comme un blocage."""
    etat = etat_package()
    refus = etat["alerte"]["evenements"][1]
    etat["enquete"]["conclusions"] = [
        {"type": "package_suspect", "affirmation": "x", "evidence_ids": etat["alerte"]["evenements"]},
        {"type": "blocage", "affirmation": "L'installation a été suspendue en attente d'un analyste.", "evidence_ids": [refus]}]
    resultat = pipeline.verificateur(etat)
    assert all(c["verifiee"] for c in resultat["conclusions"]) and resultat["confiance"] == 1.0


def test_blocage_cite_sur_la_demande_seule_reste_rejete():
    demande = next(e["id"] for e in PACKAGE_SUSPECT["events"] if e["type"] == "package_install_requested")
    etat = etat_package(conclusions=[{"type": "blocage", "affirmation": "x", "evidence_ids": [demande]}])
    assert not pipeline.verificateur(etat)["conclusions"][0]["verifiee"]


# 8. Couche de leurres : un accès à un leurre ouvre une enquête ---------------------------------------
LEURRE = json.load(open(os.path.join(ICI, "exemple_leurre.json"), encoding="utf-8"))


def test_acces_a_un_leurre_declenche_la_regle():
    etat = {"agent_id": "DevBot", "events": pipeline.preparer_evenements(LEURRE["events"])}
    alerte = pipeline.regle(etat)["alerte"]
    assert alerte["motif"].startswith("accès à un leurre")
    appel, leurre = (next(e for e in etat["events"] if e["id"] == i) for i in alerte["evenements"])
    assert appel["type"] == "tool_call" and leurre["type"] == "decoy_access"


def test_acces_a_un_leurre_cree_un_incident_verifie():
    incident = creer_incident(lot(LEURRE))
    assert incident["severity"] == "Critique" and incident["confidence"] == 1.0
    assert incident["conclusions"][0]["type"] == "acces_leurre" and incident["conclusions"][0]["verifiee"]
    assert incident["action"]["cible"] == "search_docs"


def test_conclusion_acces_leurre_sans_l_acces_est_rejetee():
    events = pipeline.preparer_evenements(LEURRE["events"])
    etat = {"agent_id": "DevBot", "events": events}
    etat.update(pipeline.regle(etat))
    appel = etat["alerte"]["evenements"][0]
    etat["enquete"] = {"title": "t", "description": "d", "severity": "Critique", "action": "suspendre_outil",
                       "cible": "search_docs", "impact": "i",
                       "conclusions": [{"type": "acces_leurre", "affirmation": "x", "evidence_ids": [appel]}]}
    assert not pipeline.verificateur(etat)["conclusions"][0]["verifiee"]


def test_conversation_normale_ne_declenche_pas_la_regle_des_leurres():
    assert client.post("/events", json=NORMAL).json()["incident"] is None
