"""Masquage des secrets : aucun vrai secret ne doit atteindre l'IA ni la base de données.

Chaque secret trouvé est remplacé par un jeton stable (SECRET_001, SECRET_002...).
Le même secret donne toujours le même jeton, ce qui permet de savoir lequel révoquer.
Le masquage s'applique à TOUS les champs texte d'un événement, y compris `resource` (une clé peut être dans une URL).
"""
import re

FORMATS_SECRET = [
    re.compile(r"sk-[A-Za-z0-9_\-]{8,}"),                    # clés OpenAI et similaires
    re.compile(r"AKIA[0-9A-Z]{16}"),                          # clés d'accès AWS
    re.compile(r"gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,}"),  # jetons GitHub
    re.compile(r"xox[abpr]-[A-Za-z0-9\-]{10,}"),              # jetons Slack
    re.compile(r"eyJ[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}"),  # jetons JWT
]
# Valeur d'un paramètre sensible dans une URL ou une config : ?token=..., password=..., api_key: ...
PARAMETRE_SENSIBLE = re.compile(
    r"((?:token|access_token|api[_-]?key|apikey|secret|password|passwd|pwd|sig|signature)\s*[=:]\s*)([^&\s\"',;#]+)", re.I)
# Identifiants dans une URL : https://utilisateur:motdepasse@hote
IDENTIFIANTS_URL = re.compile(r"(://[^/\s:@]+:)([^@\s/]+)(@)")
JETON_DEJA_MASQUE = re.compile(r"^SECRET_\d{3,}$")

_jetons: dict[str, str] = {}  # vrai secret -> jeton. Plus tard : rangé dans le coffre à secrets, pas en mémoire.


def _jeton(valeur: str) -> str:
    if JETON_DEJA_MASQUE.match(valeur):
        return valeur
    return _jetons.setdefault(valeur, f"SECRET_{len(_jetons) + 1:03d}")


def masquer(texte: str) -> str:
    for motif in FORMATS_SECRET:
        texte = motif.sub(lambda m: _jeton(m.group(0)), texte)
    texte = PARAMETRE_SENSIBLE.sub(lambda m: m.group(1) + _jeton(m.group(2)), texte)
    texte = IDENTIFIANTS_URL.sub(lambda m: m.group(1) + _jeton(m.group(2)) + m.group(3), texte)
    return texte


def masquer_evenement(evenement: dict) -> dict:
    return {cle: masquer(valeur) if isinstance(valeur, str) else valeur for cle, valeur in evenement.items()}
