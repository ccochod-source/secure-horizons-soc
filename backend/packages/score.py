"""Étape 5 — score de risque par règles fixes. Aucun LLM n'intervient ici.

Chaque signal a un poids écrit à l'avance et garde son explication. Le score
est la somme des poids (un code ne compte qu'une fois), plafonnée à 1. Sous le
seuil et sans signal bloquant, le package est installé ; sinon il part en
décision humaine.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable

THRESHOLD = 0.3

EXISTENCE = "existence"
STATIC = "static"
REPUTATION = "reputation"

# code → (étape, poids, bloquant). Bloquant : décision humaine quel que soit le score.
RULES: dict[str, tuple[str, float, bool]] = {
    "package_not_found": (EXISTENCE, 1.0, True),
    "version_not_found": (EXISTENCE, 1.0, True),
    "registry_unavailable": (EXISTENCE, 1.0, True),
    "internal_denied": (EXISTENCE, 1.0, True),
    "internal_pending": (EXISTENCE, 1.0, True),
    "dependency_confusion": (EXISTENCE, 0.4, False),
    "typosquat": (EXISTENCE, 0.4, False),
    "recently_created": (EXISTENCE, 0.2, False),
    "recent_version": (EXISTENCE, 0.1, False),
    "digest_mismatch": (STATIC, 1.0, True),
    "archive_unavailable": (STATIC, 0.3, False),
    "analysis_incomplete": (STATIC, 0.3, False),
    "install_script": (STATIC, 0.3, False),
    "network_in_install_script": (STATIC, 0.3, False),
    "obfuscated_code": (STATIC, 0.4, False),
    "guarddog_alert": (STATIC, 0.4, False),
    "exfiltration_pattern": (STATIC, 0.4, False),
    "credential_file_access": (STATIC, 0.2, False),
    "embedded_secret": (STATIC, 0.2, False),
    "critical_vulnerability": (REPUTATION, 0.3, False),
    "known_vulnerability": (REPUTATION, 0.1, False),
    "no_source_repository": (REPUTATION, 0.1, False),
    "single_release": (REPUTATION, 0.1, False),
    "reputation_unavailable": (REPUTATION, 0.1, False),
}


@dataclass(frozen=True)
class Signal:
    code: str
    explanation: str
    evidence: tuple[dict[str, Any], ...] = ()  # extraits : fichier, ligne, code
    data: dict[str, Any] = field(default_factory=dict)

    @property
    def step(self) -> str:
        return RULES[self.code][0]

    @property
    def weight(self) -> float:
        return RULES[self.code][1]

    @property
    def blocking(self) -> bool:
        return RULES[self.code][2]

    def as_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {
            "code": self.code, "step": self.step, "weight": self.weight,
            "blocking": self.blocking, "explanation": self.explanation,
        }
        if self.data:
            out["data"] = self.data
        return out


def signal(code: str, explanation: str, evidence: Iterable[dict[str, Any]] = (), **data: Any) -> Signal:
    if code not in RULES:
        raise KeyError(f"signal sans règle : {code}")
    return Signal(code, explanation, tuple(evidence), data)


def risk_score(signals: Iterable[Signal]) -> float:
    weights = {s.code: s.weight for s in signals}
    return round(min(1.0, sum(weights.values())), 2)


def is_blocking(signals: Iterable[Signal]) -> bool:
    return any(s.blocking for s in signals)


def needs_human(signals: Iterable[Signal], threshold: float = THRESHOLD) -> bool:
    signals = list(signals)
    return is_blocking(signals) or risk_score(signals) >= threshold


def risk_level(signals: Iterable[Signal], threshold: float = THRESHOLD) -> str:
    signals = list(signals)
    score = risk_score(signals)
    if is_blocking(signals) or score >= 0.9:
        return "critical"
    if score >= 0.6:
        return "high"
    return "medium" if score >= threshold else "low"
