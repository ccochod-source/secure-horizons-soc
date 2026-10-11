"""Masquage des secrets : aucun secret ne doit atteindre l'IA, la mémoire du pipeline ou la base.

Module purement stdlib (`re`) : testable sans réseau ni base. On vérifie chaque format de secret,
la stabilité des jetons, l'idempotence (un jeton déjà masqué n'est pas re-masqué) et le masquage
d'un événement complet.

Tous les secrets ci-dessous sont FICTIFS et assemblés à l'exécution (`_fake`) : aucune valeur
au format d'un secret n'apparaît en clair dans le source, pour ne pas déclencher les scanners
de secrets (GitGuardian) ni laisser croire à une fuite.
"""
import pytest

import masquage


def _fake(*parts: str) -> str:
    """Assemble un faux secret à l'exécution ; il n'existe jamais d'un seul tenant dans le fichier."""
    return "".join(parts)


OPENAI = _fake("sk-", "ABCDEFGHij", "1234567890")
AWS = _fake("AK", "IA", "ABCDEFGHIJKLMNOP")
GITHUB = _fake("gh", "p_", "ABCDEFGHIJKLMNOPQRSTUVWXYZ", "0123456789")
GITHUB_PAT = _fake("github", "_pat_", "ABCDEFGHIJKLMNOPQRSTUVWXYZ", "0123")
SLACK = _fake("xo", "xb-", "ABCDEFGHIJ-", "abcdefghij")
JWT = _fake("ey", "JhbGciOiJIUzI1NiJ9", ".", "ey", "JzdWIiOiAxMjM0NTY3ODkwfQ", ".", "c2lnbmF0dXJlX2RlbW8")


@pytest.fixture(autouse=True)
def reset_jetons():
    """Chaque test repart d'une table de jetons vierge (le module la garde en mémoire globale)."""
    masquage._jetons.clear()
    yield
    masquage._jetons.clear()


# --- formats de secret reconnus ----------------------------------------------------------

@pytest.mark.parametrize("secret", [OPENAI, AWS, GITHUB, GITHUB_PAT, SLACK, JWT],
                         ids=["openai", "aws", "github", "github_pat", "slack", "jwt"])
def test_formats_de_secret_sont_masques(secret):
    masque = masquage.masquer(f"valeur = {secret}")
    assert secret not in masque
    assert "SECRET_" in masque


def test_cle_aws_trop_courte_non_masquee():
    """AKIA doit être suivi d'exactement 16 caractères : une chaîne plus courte n'est pas un secret."""
    texte = _fake("AK", "IA", "123")  # trop court pour le motif
    assert masquage.masquer(texte) == texte


# --- paramètres sensibles clé=valeur -----------------------------------------------------

@pytest.mark.parametrize("cle,sep,valeur", [
    ("token", "=", "abcdef123456"),
    ("api_key", ": ", "MaValeurFictive"),
    ("api-key", "=", "xyz987"),
    ("pass" "word", "=", _fake("Valeur", "Fictive", "42")),
    ("passwd", " = ", "fictif9"),
    ("pwd", ":", "fictive"),
    ("signature", "=", "ZmFrZXNpZw"),
    ("secret", " = ", "deadbeefcafe"),
])
def test_parametre_sensible_valeur_masquee_cle_conservee(cle, sep, valeur):
    masque = masquage.masquer(cle + sep + valeur)
    assert valeur not in masque
    assert cle in masque               # le nom du paramètre reste lisible pour l'audit
    assert "SECRET_" in masque


def test_parametre_insensible_non_masque():
    texte = "page=12&sort=asc"
    assert masquage.masquer(texte) == texte


# --- identifiants dans une URL -----------------------------------------------------------

def test_identifiants_url_mot_de_passe_masque_utilisateur_conserve():
    mdp = _fake("Fictif", "Pass")
    masque = masquage.masquer("postgres://admin:" + mdp + "@db.interne.example/prod")
    assert mdp not in masque
    assert "admin" in masque           # l'utilisateur reste visible
    assert "db.interne.example" in masque
    assert "SECRET_" in masque


def test_cle_dans_un_parametre_d_url():
    valeur = _fake("abc123", "def456")
    masque = masquage.masquer("https://api.example/v1?token=" + valeur + "&page=2")
    assert valeur not in masque
    assert "page=2" in masque          # le reste de l'URL est intact


# --- stabilité et idempotence des jetons -------------------------------------------------

def test_meme_secret_meme_jeton():
    s = _fake("sk-", "STABLEstable", "1234567890")
    jeton_a = masquage.masquer(f"a {s}").split()[-1]
    jeton_b = masquage.masquer(f"b {s}").split()[-1]
    assert jeton_a == jeton_b          # indispensable pour savoir quel secret révoquer


def test_secrets_differents_jetons_differents():
    a, b = _fake("sk-", "AAAAAAAAAA", "11111111"), _fake("sk-", "BBBBBBBBBB", "22222222")
    masque = masquage.masquer(f"{a} et {b}")
    assert masque.count("SECRET_") == 2
    assert "SECRET_001" in masque and "SECRET_002" in masque


def test_numerotation_sequentielle():
    masquage.masquer(_fake("sk-", "PREMIERpremier", "12345"))
    masquage.masquer(_fake("sk-", "DEUXIEMEdeuxieme", "1234"))
    assert set(masquage._jetons.values()) == {"SECRET_001", "SECRET_002"}


def test_masquage_idempotent():
    """Masquer deux fois ne doit pas produire SECRET_ d'un SECRET_ déjà posé."""
    une_fois = masquage.masquer("clé " + _fake("sk-", "IDEMPOTENTidem", "12345"))
    deux_fois = masquage.masquer(une_fois)
    assert une_fois == deux_fois
    assert deux_fois.count("SECRET_") == 1


def test_jeton_deja_masque_non_remasque():
    assert masquage.masquer("SECRET_001") == "SECRET_001"
    # et aucun nouveau jeton n'a été créé pour ce faux secret
    assert masquage._jetons == {}


# --- plusieurs secrets dans un même texte ------------------------------------------------

def test_plusieurs_secrets_dans_un_texte():
    openai = _fake("sk-", "XXXXXXXXXX", "1234567890")
    texte = f"openai={openai} aws={AWS} url=https://u:" + "p" + "@h/x"
    masque = masquage.masquer(texte)
    for fuite in (openai, AWS):
        assert fuite not in masque
    assert ":p@" not in masque
    assert masque.count("SECRET_") >= 3


def test_texte_sans_secret_inchange():
    texte = "Procédure de déploiement ordinaire, voir le tableau de bord interne."
    assert masquage.masquer(texte) == texte


# --- masquage d'un événement complet -----------------------------------------------------

def test_masquer_evenement_masque_tous_les_champs_texte():
    cle = _fake("sk-", "EVENTevent", "1234567890")
    mdp = _fake("mot", "fictif")
    evenement = {
        "id": "evt-1",
        "parent_event_id": None,
        "description": "clé " + cle,
        "resource": "https://admin:" + mdp + "@h/x",
        "result": "flagged",
        "count": 3,                     # non-str : laissé tel quel
    }
    masque = masquage.masquer_evenement(evenement)
    assert cle not in masque["description"]
    assert mdp not in masque["resource"]
    assert masque["id"] == "evt-1"            # pas de secret, inchangé
    assert masque["parent_event_id"] is None  # None préservé
    assert masque["count"] == 3               # entier préservé
    assert masque["result"] == "flagged"


def test_meme_secret_dans_deux_champs_meme_jeton():
    s = _fake("sk-", "SHAREDshared", "1234567890")
    masque = masquage.masquer_evenement({"description": f"a {s}", "resource": f"b {s}"})
    assert masque["description"].split()[-1] == masque["resource"].split()[-1]
