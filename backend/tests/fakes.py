"""Valeurs factices fabriquées à l'exécution : aucun secret, même faux, dans le dépôt."""

import random
import string

_rng = random.Random(7)
_UPPER_DIGITS = string.ascii_uppercase + string.digits
_ALNUM = string.ascii_letters + string.digits


def _pick(alphabet: str, n: int) -> str:
    return "".join(_rng.choice(alphabet) for _ in range(n))


def aws_key() -> str:
    return "AKIA" + _pick(_UPPER_DIGITS, 16)


def openai_key() -> str:
    return "sk-" + "proj-" + _pick(_ALNUM, 40)


def github_token() -> str:
    return "ghp_" + _pick(_ALNUM, 36)


def postgres_url() -> str:
    return "postgresql://app:" + _pick(_ALNUM, 12) + "@db.internal:5432/prod"


def jwt() -> str:
    return ".".join(("eyJ" + _pick(_ALNUM, 20), _pick(_ALNUM, 30), _pick(_ALNUM, 30)))


def private_key() -> str:
    return "-----BEGIN RSA PRIVATE KEY-----\n" + _pick(_ALNUM, 64) + "\n-----END RSA PRIVATE KEY-----"
