"""Masquage des secrets : aucun secret ne doit atteindre l'IA, la mémoire du pipeline ou la base.

Module purement stdlib (`re`) : testable sans réseau ni base. On vérifie chaque format de secret,
la stabilité des jetons, l'idempotence (un jeton déjà masqué n'est pas re-masqué) et le masquage
d'un événement complet.
"""
import importlib

import pytest

import masquage


@pytest.fixture(autouse=True)
def reset_jetons():
    """Chaque test repart d'une table de jetons vierge (le module la garde en mémoire globale)."""
    masquage._jetons.clear()
    yield
    masquage._jetons.clear()


# --- formats de secret reconnus ----------------------------------------------------------

@pytest.mark.parametrize("secret", [
    "sk-ABCDEFGHij1234567890",                       # clé type OpenAI
    "AKIAABCDEFGHIJKLMNOP",                            # clé d'accès AWS (AKIA + 16)
    "ghp_ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789",       # jeton GitHub classique
    "github_pat_ABCDEFGHIJKLMNOPQRSTUVWXYZ0123",      # jeton GitHub à grain fin
    "xoxb-ABCDEFGHIJ-abcdefghij",                     # jeton bot Slack
    "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiAxMjM0NTY3ODkwfQ.c2lnbmF0dXJlX2RlbW8",  # JWT à trois segments
])
def test_formats_de_secret_sont_masques(secret):
    masque = masquage.masquer(f"valeur = {secret}")
    assert secret not in masque
    assert "SECRET_" in masque


def test_cle_aws_trop_courte_non_masquee():
    """AKIA doit être suivi d'exactement 16 caractères : une chaîne plus courte n'est pas un secret."""
    texte = "AKIA123"  # trop court pour le motif
    assert masquage.masquer(texte) == texte


# --- paramètres sensibles clé=valeur -----------------------------------------------------

@pytest.mark.parametrize("texte,fuite", [
    ("token=abcdef123456", "abcdef123456"),
    ("api_key: MaValeurSecrete", "MaValeurSecrete"),
    ("api-key=xyz987", "xyz987"),
    ("password=Hunter2Hunter2", "Hunter2Hunter2"),
    ("passwd = s3cr3t", "s3cr3t"),
    ("pwd:motdepasse", "motdepasse"),
    ("signature=ZmFrZXNpZw", "ZmFrZXNpZw"),
    ("secret = deadbeefcafe", "deadbeefcafe"),
])
def test_parametre_sensible_valeur_masquee_cle_conservee(texte, fuite):
    masque = masquage.masquer(texte)
    assert fuite not in masque
    # Le nom du paramètre (gauche du séparateur) doit rester lisible pour l'audit.
    cle = texte.split("=")[0].split(":")[0].strip()
    assert cle.split()[0] in masque
    assert "SECRET_" in masque


def test_parametre_insensible_non_masque():
    texte = "page=12&sort=asc"
    assert masquage.masquer(texte) == texte


# --- identifiants dans une URL -----------------------------------------------------------

def test_identifiants_url_mot_de_passe_masque_utilisateur_conserve():
    masque = masquage.masquer("postgres://admin:SuperSecret@db.interne.example/prod")
    assert "SuperSecret" not in masque
    assert "admin" in masque           # l'utilisateur reste visible
    assert "db.interne.example" in masque
    assert "SECRET_" in masque


def test_cle_dans_un_parametre_d_url():
    masque = masquage.masquer("https://api.example/v1?token=abc123def456&page=2")
    assert "abc123def456" not in masque
    assert "page=2" in masque          # le reste de l'URL est intact


# --- stabilité et idempotence des jetons -------------------------------------------------

def test_meme_secret_meme_jeton():
    s = "sk-STABLEstable1234567890"
    a = masquage.masquer(f"a {s}")
    b = masquage.masquer(f"b {s}")
    jeton_a = a.split()[-1]
    jeton_b = b.split()[-1]
    assert jeton_a == jeton_b          # indispensable pour savoir quel secret révoquer

def test_secrets_differents_jetons_differents():
    masque = masquage.masquer("sk-AAAAAAAAAA11111111 et sk-BBBBBBBBBB22222222")
    assert masque.count("SECRET_") == 2
    assert "SECRET_001" in masque and "SECRET_002" in masque


def test_numerotation_sequentielle():
    masquage.masquer("sk-PREMIERpremier12345")
    masquage.masquer("sk-DEUXIEMEdeuxieme1234")
    assert set(masquage._jetons.values()) == {"SECRET_001", "SECRET_002"}


def test_masquage_idempotent():
    """Masquer deux fois ne doit pas produire SECRET_ d'un SECRET_ déjà posé."""
    une_fois = masquage.masquer("clé sk-IDEMPOTENTidem12345")
    deux_fois = masquage.masquer(une_fois)
    assert une_fois == deux_fois
    assert deux_fois.count("SECRET_") == 1


def test_jeton_deja_masque_non_remasque():
    assert masquage.masquer("SECRET_001") == "SECRET_001"
    # et aucun nouveau jeton n'a été créé pour ce faux secret
    assert masquage._jetons == {}


# --- plusieurs secrets dans un même texte ------------------------------------------------

def test_plusieurs_secrets_dans_un_texte():
    texte = "openai=sk-XXXXXXXXXX1234567890 aws=AKIAABCDEFGHIJKLMNOP url=https://u:p@h/x"
    masque = masquage.masquer(texte)
    for fuite in ("sk-XXXXXXXXXX1234567890", "AKIAABCDEFGHIJKLMNOP"):
        assert fuite not in masque
    assert ":p@" not in masque
    assert masque.count("SECRET_") >= 3


def test_texte_sans_secret_inchange():
    texte = "Procédure de déploiement ordinaire, voir le tableau de bord interne."
    assert masquage.masquer(texte) == texte


# --- masquage d'un événement complet -----------------------------------------------------

def test_masquer_evenement_masque_tous_les_champs_texte():
    evenement = {
        "id": "evt-1",
        "parent_event_id": None,
        "description": "clé sk-EVENTevent1234567890",
        "resource": "https://admin:motdepasse@h/x",
        "result": "flagged",
        "count": 3,                     # non-str : laissé tel quel
    }
    masque = masquage.masquer_evenement(evenement)
    assert "sk-EVENTevent1234567890" not in masque["description"]
    assert "motdepasse" not in masque["resource"]
    assert masque["id"] == "evt-1"            # pas de secret, inchangé
    assert masque["parent_event_id"] is None  # None préservé
    assert masque["count"] == 3               # entier préservé
    assert masque["result"] == "flagged"


def test_meme_secret_dans_deux_champs_meme_jeton():
    s = "sk-SHAREDshared1234567890"
    masque = masquage.masquer_evenement({"description": f"a {s}", "resource": f"b {s}"})
    jeton_desc = masque["description"].split()[-1]
    jeton_res = masque["resource"].split()[-1]
    assert jeton_desc == jeton_res
