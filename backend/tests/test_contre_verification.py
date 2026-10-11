"""Contre-vérification d'un package approuvé par un analyste, puis confirmation par ce même analyste.

Registre et OSV sont servis en mémoire (aucun réseau) ; l'enquêteur est simulé (MOCK_LLM).
"""
import json
import os

import httpx
import pytest
from fastapi.testclient import TestClient

import contre_verification as cv
import execution
import main
import stockage

ICI = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PACKAGE_SUSPECT = json.load(open(os.path.join(ICI, "exemple_package_suspect.json"), encoding="utf-8"))
REQUETE = next(e["id"] for e in PACKAGE_SUSPECT["events"] if e["type"] == "package_install_requested")
client = TestClient(main.app)
ANALYSTE = "analyste-qui-a-approuve"


def registre(existants: dict[str, int] | None = None, vulns: dict[str, list] | None = None) -> httpx.Client:
    existants, vulns = existants or {}, vulns or {}

    def repondre(requete: httpx.Request) -> httpx.Response:
        url = str(requete.url)
        if url == "https://api.osv.dev/v1/query":
            return httpx.Response(200, json={"vulns": vulns.get(json.loads(requete.content)["package"]["name"], [])})
        nom = url.split("/")[4]
        if nom not in existants:
            return httpx.Response(404, json={"message": "Not Found"})
        releases = {f"1.{i}.0": [{"upload_time_iso_8601": "2019-03-01T10:00:00Z"}] for i in range(existants[nom])}
        return httpx.Response(200, json={"info": {"project_urls": {"Source": "https://github.com/x"}}, "releases": releases})
    return httpx.Client(transport=httpx.MockTransport(repondre))


def demande(nom="pdfreport-turbo", signaux=None, request_event_id=None, etat="executed") -> cv.DemandeContreVerification:
    return cv.DemandeContreVerification(
        review_id=f"rev-{nom}-{os.urandom(3).hex()}", registre="pypi", nom=nom, version="", approuve_par=ANALYSTE,
        etat_installation=etat, signaux=signaux or [], request_event_id=request_event_id)


def incident_avec_confiance(confiance: float) -> dict:
    incident = client.post("/events", json={"agent_id": "DevBot", "events": PACKAGE_SUSPECT["events"]}).json()["incident"]
    incident["confidence"] = confiance
    stockage.enregistrer(incident)
    return incident


def test_agents_surs_que_c_est_suspect_confirmation_demandee_meme_si_le_paquet_semble_sain():
    """L'humain passe outre une conclusion solide des agents : deuxième vérification ET confirmation d'office."""
    incident_avec_confiance(0.9)
    resultat = cv.contre_verifier(demande(nom="requests", request_event_id=REQUETE), registre({"requests": 40}))
    assert resultat["faits"] and resultat["verdict"] == "sur"
    assert resultat["statut"] == "attente_confirmation" and len(resultat["motifs_confirmation"]) == 1
    assert "sûrs à 90 %" in resultat["question"]


def test_enquete_fragile_et_deuxieme_verification_positive_pas_de_confirmation():
    incident_avec_confiance(0.5)
    resultat = cv.contre_verifier(demande(nom="requests", request_event_id=REQUETE), registre({"requests": 40}))
    assert resultat["statut"] == "confirmee" and resultat["question"] is None


def test_enquete_peu_fiable_et_package_introuvable_demande_confirmation():
    incident = incident_avec_confiance(0.67)
    resultat = cv.contre_verifier(demande(request_event_id=REQUETE), registre())
    assert resultat["incident_id"] == incident["id"] and resultat["confiance_initiale"] == 0.67
    assert resultat["statut"] == "attente_confirmation" and resultat["verdict"] == "dangereux"
    assert any("n'existe pas" in f["texte"] and f["critique"] for f in resultat["faits"])
    assert "Voulez-vous toujours l'ajouter" in resultat["question"]


def test_package_sain_sans_enquete_est_confirme_par_les_agents():
    resultat = cv.contre_verifier(demande(nom="requests"), registre({"requests": 40}))
    assert resultat["confiance_initiale"] is None
    assert resultat["statut"] == "confirmee" and resultat["positive"]


def test_vulnerabilite_connue_empeche_un_verdict_positif():
    resultat = cv.contre_verifier(demande(nom="vieuxpaquet"), registre({"vieuxpaquet": 9}, {"vieuxpaquet": [{"id": "GHSA-x"}]}))
    assert resultat["statut"] == "attente_confirmation"


def test_verdict_sur_contredit_par_un_fait_critique_est_refuse():
    faits = [{"id": "F1", "texte": "PyPI : le package n'existe pas.", "critique": True, "source": "registre"}]
    controle = cv.verifier(cv.VerdictIA(verdict="sur", resume="r", raisons=[cv.Raison(affirmation="a", faits=["F1"])]), faits)
    assert controle["verdict_ia"] == "sur" and controle["verdict"] == "douteux" and not controle["positive"]
    assert "F1" in controle["correction"]


def test_raison_citant_un_fait_inexistant_est_rejetee():
    faits = [{"id": "F1", "texte": "ok", "critique": False, "source": "registre"}]
    controle = cv.verifier(cv.VerdictIA(verdict="sur", resume="r", raisons=[cv.Raison(affirmation="a", faits=["F9"])]), faits)
    assert not controle["raisons"][0]["verifiee"] and controle["verdict"] == "douteux"


def a_confirmer() -> dict:
    return cv.contre_verifier(demande(), registre())


def test_seul_l_analyste_qui_a_approuve_peut_confirmer():
    en_attente = a_confirmer()
    reponse = client.post(f"/contre-verifications/{en_attente['id']}/confirmation", json={"maintenir": False, "analyste": "quelqu-un-d-autre"})
    assert reponse.status_code == 403


def test_l_analyste_maintient_son_choix():
    en_attente = a_confirmer()
    fin = client.post(f"/contre-verifications/{en_attente['id']}/confirmation", json={"maintenir": True, "analyste": ANALYSTE}).json()
    assert fin["statut"] == "maintenu"
    deuxieme = client.post(f"/contre-verifications/{en_attente['id']}/confirmation", json={"maintenir": False, "analyste": ANALYSTE})
    assert deuxieme.status_code == 409


def test_l_analyste_refuse_le_package_est_retire_par_la_passerelle(monkeypatch):
    demandes = []
    monkeypatch.setattr(execution, "retirer_package", lambda review_id, par, raison: demandes.append((review_id, par)) or
                        {"etat": "execute", "detail": "retiré"})
    en_attente = a_confirmer()
    fin = client.post(f"/contre-verifications/{en_attente['id']}/confirmation", json={"maintenir": False, "analyste": ANALYSTE}).json()
    assert fin["statut"] == "retire" and demandes == [(en_attente["review_id"], ANALYSTE)]


def test_retrait_en_echec_peut_etre_redemande(monkeypatch):
    monkeypatch.setattr(execution, "retirer_package", lambda *a: {"etat": "echec", "detail": "passerelle injoignable"})
    en_attente = a_confirmer()
    fin = client.post(f"/contre-verifications/{en_attente['id']}/confirmation", json={"maintenir": False, "analyste": ANALYSTE}).json()
    assert fin["statut"] == "retrait_en_echec"
    monkeypatch.setattr(execution, "retirer_package", lambda *a: {"etat": "execute", "detail": "retiré"})
    fin = client.post(f"/contre-verifications/{en_attente['id']}/confirmation", json={"maintenir": False, "analyste": ANALYSTE}).json()
    assert fin["statut"] == "retire"


def test_sans_passerelle_configuree_le_retrait_n_est_pas_annonce(monkeypatch):
    monkeypatch.delenv("RETRAIT_URL", raising=False)
    monkeypatch.delenv("CONFINEMENT_URL", raising=False)
    assert execution.retirer_package("rev", "a", "r")["etat"] == "echec"


def test_routes_protegees_par_les_jetons(monkeypatch):
    monkeypatch.setenv("PASSERELLE_TOKEN", "jeton-passerelle")
    monkeypatch.setenv("ANALYSTE_TOKEN", "jeton-analyste")
    assert client.post("/packages/contre-verification", json={}).status_code == 401
    assert client.get("/contre-verifications").status_code == 401
