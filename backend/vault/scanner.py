"""Règles locales de détection : secrets (regex + entropie) et données personnelles.

Toujours actives, sans dépendance réseau. GitGuardian vient en complément
(voir gitguardian.py), jamais en remplacement.
"""

from __future__ import annotations

import math
import re
from collections import Counter
from dataclasses import dataclass
from typing import Iterable

# Forme des jetons produits par le coffre (SECRET_AWS_101, PERSONNE_117…).
TOKEN_RE = re.compile(r"\b[A-Z][A-Z_]{1,29}_\d{3,}\b")

SECRET = "secret"
PII = "pii"


@dataclass(frozen=True)
class Detection:
    prefix: str  # préfixe du jeton : SECRET_AWS, EMAIL, PERSONNE…
    value: str  # valeur canonique rangée dans le coffre
    start: int
    end: int
    category: str  # SECRET ou PII
    priority: int  # plus petit = plus spécifique, gagne en cas de chevauchement


# Formats connus, du plus spécifique au plus générique.
_FORMATS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("SECRET_PRIVKEY", re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----[\s\S]+?-----END [A-Z ]*PRIVATE KEY-----")),
    ("SECRET_PG", re.compile(r"\bpostgres(?:ql)?://[^\s:@/'\"]+:[^\s@'\"]+@[^\s'\"<>]+")),
    ("SECRET_ANTHROPIC", re.compile(r"\bsk-ant-[A-Za-z0-9_-]{20,}")),
    ("SECRET_OPENAI", re.compile(r"\bsk-(?:proj-|svcacct-|admin-)?[A-Za-z0-9_-]{20,}")),
    ("SECRET_AWS", re.compile(r"\b(?:AKIA|ASIA)[A-Z0-9]{16}\b")),
    ("SECRET_GITHUB", re.compile(r"\b(?:gh[pousr]_[A-Za-z0-9]{36,}|github_pat_[A-Za-z0-9_]{22,})")),
    ("SECRET_NPM", re.compile(r"\bnpm_[A-Za-z0-9]{36}\b")),
    ("SECRET_SLACK", re.compile(r"\bxox[abprs]-[A-Za-z0-9-]{10,}")),
    ("SECRET_STRIPE", re.compile(r"\b[sr]k_(?:live|test)_[A-Za-z0-9]{16,}")),
    ("SECRET_GOOGLE", re.compile(r"\bAIza[A-Za-z0-9_-]{35}")),
    ("SECRET_SUPABASE", re.compile(r"\bsb_secret_[A-Za-z0-9_-]{20,}")),
    ("SECRET_JWT", re.compile(r"\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}")),
)

_SENSITIVE_NAME = (
    r"pass(?:word|wd)?|pwd|mot[_ ]de[_ ]passe|secret|api[_-]?key|apikey|access[_-]?key|"
    r"(?:access|auth|refresh|bearer)[_-]?token|token|client[_-]?secret|private[_-]?key|credentials?"
)
# « password = hunter2 », « api_key: "abc…" » dans un texte libre.
_ASSIGNMENT = re.compile(
    rf"(?i)(?<![A-Za-z])(?:{_SENSITIVE_NAME})(?![A-Za-z])[\"']?\s*[:=]\s*[\"']?([^\s\"',;]{{8,}})"
)
# Clé de dictionnaire dont la valeur est un secret par nature.
SENSITIVE_KEY = re.compile(rf"(?i)(?:^|[^A-Za-z])(?:{_SENSITIVE_NAME}|authorization)(?:$|[^A-Za-z])")

_HIGH_ENTROPY_CANDIDATE = re.compile(r"(?<![A-Za-z0-9+/_.-])[A-Za-z0-9+/_-]{24,}={0,2}(?![A-Za-z0-9+/_-])")
# Un chemin d'URL entier ressemble à du base64 : dans une URL, on juge chaque
# segment séparément (jeton de webhook, paramètre…).
_URL = re.compile(r"\bhttps?://[^\s\"'<>]+")
_URL_SEGMENT = re.compile(r"(?<![A-Za-z0-9+_-])[A-Za-z0-9+_-]{24,}={0,2}(?![A-Za-z0-9+_-])")

# Le domaine finit par une extension alphabétique : « requests@2.32.0 » n'est pas un e-mail.
_EMAIL = re.compile(r"(?<![A-Za-z0-9._%+-])[A-Za-z0-9._%+-]+@(?:[A-Za-z0-9-]+\.)+[A-Za-z]{2,}(?![A-Za-z0-9-])")
_PHONE = re.compile(
    r"(?<![\dA-Za-z])(?:(?:\+33|0033)[\s.-]?[1-9]|0[1-9])(?:[\s.-]?\d{2}){4}(?!\d)"
    r"|(?<![\dA-Za-z+])\+\d{1,3}(?:[\s.-]?\d){7,12}(?!\d)"
)
_IBAN = re.compile(r"\b[A-Z]{2}\d{2}(?:[ ]?[A-Z0-9]{4}){3,7}(?:[ ]?[A-Z0-9]{1,3})?\b")


def shannon_entropy(text: str) -> float:
    if not text:
        return 0.0
    n = len(text)
    return -sum(c / n * math.log2(c / n) for c in Counter(text).values())


def is_token(text: str) -> bool:
    return TOKEN_RE.fullmatch(text) is not None


def _looks_random(candidate: str) -> bool:
    """Longue chaîne aléatoire : mélange de casse et de chiffres, entropie élevée."""
    if not (any(c.isdigit() for c in candidate) and any(c.islower() for c in candidate)
            and any(c.isupper() for c in candidate)):
        return False
    # Une chaîne courte ne peut pas atteindre l'entropie d'une longue : seuil adapté.
    return shannon_entropy(candidate) >= (3.9 if len(candidate) < 32 else 4.1)


def _plausible_assigned_secret(value: str) -> bool:
    if is_token(value):
        return False
    # Écarte la prose (« le secret : personne ne… ») sans rater « hunter2 ».
    return any(c.isdigit() for c in value) or (len(value) >= 12 and shannon_entropy(value) >= 3.0)


class Scanner:
    def __init__(self, names: Iterable[str] = ()) -> None:
        self._names: dict[str, str] = {}
        self._names_re: re.Pattern[str] | None = None
        self.set_names(names)

    def set_names(self, names: Iterable[str]) -> None:
        """Annuaire des personnes à pseudonymiser (noms complets)."""
        clean = {" ".join(n.split()) for n in names if n and len(n.strip()) >= 3}
        self._names = {n.casefold(): n for n in clean}
        if not clean:
            self._names_re = None
            return
        alternatives = "|".join(
            r"\s+".join(re.escape(part) for part in n.split())
            for n in sorted(clean, key=len, reverse=True)
        )
        self._names_re = re.compile(rf"(?<!\w)(?:{alternatives})(?!\w)", re.IGNORECASE)

    def scan_secrets(self, text: str) -> list[Detection]:
        found: list[Detection] = []
        for rank, (prefix, pattern) in enumerate(_FORMATS):
            for m in pattern.finditer(text):
                found.append(Detection(prefix, m.group(), m.start(), m.end(), SECRET, rank))
        for m in _ASSIGNMENT.finditer(text):
            if _plausible_assigned_secret(m.group(1)):
                found.append(Detection("SECRET_GENERIC", m.group(1), m.start(1), m.end(1), SECRET, 50))
        urls = [u.span() for u in _URL.finditer(text)]
        candidates = [m for m in _HIGH_ENTROPY_CANDIDATE.finditer(text)
                      if not any(start < m.end() and m.start() < end for start, end in urls)]
        for start, end in urls:
            candidates += _URL_SEGMENT.finditer(text, start, end)
        for m in candidates:
            if not TOKEN_RE.search(m.group()) and _looks_random(m.group()):
                found.append(Detection("SECRET_GENERIC", m.group(), m.start(), m.end(), SECRET, 60))
        return _without_overlaps(found)

    def scan_pii(self, text: str) -> list[Detection]:
        found: list[Detection] = []
        for m in _EMAIL.finditer(text):
            found.append(Detection("EMAIL", m.group().lower(), m.start(), m.end(), PII, 70))
        for m in _PHONE.finditer(text):
            found.append(Detection("TELEPHONE", re.sub(r"[\s.-]", "", m.group()), m.start(), m.end(), PII, 71))
        for m in _IBAN.finditer(text):
            found.append(Detection("IBAN", m.group().replace(" ", ""), m.start(), m.end(), PII, 72))
        if self._names_re is not None:
            for m in self._names_re.finditer(text):
                canonical = self._names[" ".join(m.group().split()).casefold()]
                found.append(Detection("PERSONNE", canonical, m.start(), m.end(), PII, 73))
        return _without_overlaps(found)

    def scan(self, text: str) -> list[Detection]:
        """Secrets et données personnelles, sans chevauchement, triés par position."""
        return _without_overlaps(self.scan_secrets(text) + self.scan_pii(text))


def _without_overlaps(detections: list[Detection]) -> list[Detection]:
    kept: list[Detection] = []
    for d in sorted(detections, key=lambda d: (d.priority, -(d.end - d.start), d.start)):
        if all(d.end <= k.start or d.start >= k.end for k in kept):
            kept.append(d)
    return sorted(kept, key=lambda d: d.start)
