"""Score de risque des packages (packages/score.py) : règles fixes, sans LLM ni réseau.

On vérifie les propriétés d'un signal, la déduplication par code, le plafond à 1,
la priorité du caractère bloquant, le seuil de décision humaine et les paliers de niveau.
"""
import pytest

from packages.score import (
    RULES, THRESHOLD, Signal, is_blocking, needs_human, risk_level, risk_score, signal,
)


# --- fabrique signal() -------------------------------------------------------------------

def test_signal_expose_etape_poids_et_bloquant_depuis_les_regles():
    s = signal("typosquat", "nom proche d'un package connu")
    assert (s.step, s.weight, s.blocking) == RULES["typosquat"]
    assert s.weight == 0.4 and s.blocking is False


def test_signal_bloquant():
    assert signal("package_not_found", "introuvable").blocking is True


def test_signal_code_inconnu_leve():
    with pytest.raises(KeyError):
        signal("code_qui_n_existe_pas", "x")


def test_as_dict_inclut_les_donnees_seulement_si_presentes():
    sans = signal("recent_version", "version récente").as_dict()
    assert "data" not in sans
    avec = signal("recent_version", "version récente", age_days=2).as_dict()
    assert avec["data"] == {"age_days": 2}
    assert avec["code"] == "recent_version" and avec["step"] == "existence"


def test_evidence_conservee_comme_tuple():
    s = signal("install_script", "script d'installation", evidence=[{"file": "setup.py", "line": 10}])
    assert s.evidence == ({"file": "setup.py", "line": 10},)


# --- risk_score : somme, dédup, plafond --------------------------------------------------

def test_score_vide_est_zero():
    assert risk_score([]) == 0.0


def test_score_somme_des_poids():
    s = [signal("typosquat", ""), signal("recently_created", "")]  # 0.4 + 0.2
    assert risk_score(s) == 0.6


def test_meme_code_compte_une_seule_fois():
    s = [signal("typosquat", "a"), signal("typosquat", "b")]  # 0.4, pas 0.8
    assert risk_score(s) == 0.4


def test_score_plafonne_a_1():
    s = [signal("digest_mismatch", ""), signal("obfuscated_code", ""), signal("exfiltration_pattern", "")]
    assert risk_score(s) == 1.0


def test_score_arrondi_deux_decimales():
    s = [signal("recent_version", ""), signal("known_vulnerability", "")]  # 0.1 + 0.1
    assert risk_score(s) == 0.2


# --- is_blocking -------------------------------------------------------------------------

def test_is_blocking_vrai_si_un_signal_bloquant():
    assert is_blocking([signal("recent_version", ""), signal("version_not_found", "")]) is True


def test_is_blocking_faux_sans_signal_bloquant():
    assert is_blocking([signal("typosquat", ""), signal("recently_created", "")]) is False


# --- needs_human -------------------------------------------------------------------------

def test_needs_human_si_bloquant_meme_score_faible():
    # internal_pending est bloquant (poids 1.0 mais surtout blocking=True)
    assert needs_human([signal("internal_pending", "")]) is True


def test_needs_human_si_score_atteint_le_seuil():
    s = [signal("typosquat", "")]  # 0.4 >= THRESHOLD (0.3)
    assert risk_score(s) >= THRESHOLD
    assert needs_human(s) is True


def test_installe_sous_le_seuil_sans_bloquant():
    s = [signal("recent_version", "")]  # 0.1 < 0.3, non bloquant
    assert needs_human(s) is False


def test_needs_human_au_seuil_exact():
    s = [signal("recently_created", ""), signal("recent_version", "")]  # 0.2 + 0.1 = 0.3
    assert risk_score(s) == THRESHOLD
    assert needs_human(s) is True  # >= seuil


# --- risk_level --------------------------------------------------------------------------

def test_niveau_low_sans_signal():
    assert risk_level([]) == "low"


def test_niveau_medium_au_seuil():
    assert risk_level([signal("typosquat", "")]) == "medium"  # 0.4


def test_niveau_high():
    s = [signal("typosquat", ""), signal("obfuscated_code", "")]  # 0.4 + 0.4 = 0.8
    assert risk_level(s) == "high"


def test_niveau_critical_par_score():
    s = [signal("typosquat", ""), signal("obfuscated_code", ""), signal("guarddog_alert", "")]  # 1.0
    assert risk_level(s) == "critical"


def test_niveau_critical_par_signal_bloquant_meme_score_faible():
    # digest_mismatch est bloquant → critical quel que soit le score
    assert risk_level([signal("digest_mismatch", "")]) == "critical"


def test_tous_les_codes_de_regles_sont_instanciables():
    """Garde-fou : chaque code déclaré doit produire un Signal cohérent."""
    for code in RULES:
        s = signal(code, "test")
        assert isinstance(s, Signal) and 0.0 < s.weight <= 1.0
