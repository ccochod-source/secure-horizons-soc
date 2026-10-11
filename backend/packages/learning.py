"""Boucle d'amélioration du contrôle des packages.

Une décision d'analyste produit des propositions de règles ; une proposition
ne change rien tant qu'un analyste ne l'a pas appliquée. Les propositions ne
naissent que d'une revue rejetée par un analyste connu : jamais du contenu
d'un agent, d'un document ou d'un package. Une approbation ne crée aucune
règle, et il n'existe pas de liste « sûre » : on n'apprend que des refus.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any
from uuid import UUID

from common.rules import RuleStore
from packages import existence
from packages.popular import BY_ECOSYSTEM
from packages.store import ReviewStore

logger = logging.getLogger(__name__)

KNOWN_MALICIOUS = "known_malicious"
REPLACEMENT_MAP = "replacement_map"
POPULAR = "popular"
KINDS = (KNOWN_MALICIOUS, REPLACEMENT_MAP, POPULAR)

_NOT_FOUND = "package_not_found"
_TYPOSQUAT = "typosquat"


@dataclass(frozen=True)
class Learned:
    """Règles actives d'un écosystème, telles que lues au début d'une analyse."""

    malicious: dict[str, dict[str, Any]] = field(default_factory=dict)  # nom → règle
    popular: frozenset[str] = frozenset()
    replacements: dict[str, dict[str, Any]] = field(default_factory=dict)  # nom inventé → règle


class PackageLearning:
    def __init__(self, rules: RuleStore, reviews: ReviewStore) -> None:
        self._rules = rules
        self._reviews = reviews

    @property
    def rules(self) -> RuleStore:
        return self._rules

    async def propose(self, review_id: UUID) -> list[dict[str, Any]]:
        """Propositions tirées d'une décision déjà enregistrée. Rend celles réellement créées."""
        review = await self._reviews.get_review(review_id)
        if review is None or review["state"] != "rejected":
            return []  # une approbation ne crée aucune règle
        if not await self._decided_by_analyst(review):
            return []
        ecosystem = review["registry"]
        if ecosystem not in BY_ECOSYSTEM:
            return []
        name = existence.normalize(ecosystem, review["package_name"])
        signals = {s.get("code"): s for s in (review.get("checks") or {}).get("signals") or []}
        replacement = await self._replacement(review)

        wanted: list[tuple[str, dict[str, Any]]] = []
        if _NOT_FOUND in signals and replacement is not None:
            # Nom halluciné remplacé par un package de confiance : on retient la correspondance.
            wanted.append((REPLACEMENT_MAP, {"ecosystem": ecosystem, "from": name, "to": replacement}))
        elif not await self._protected(ecosystem, name):
            wanted.append((KNOWN_MALICIOUS, {"ecosystem": ecosystem, "name": name}))
        if _TYPOSQUAT in signals:
            target = (signals[_TYPOSQUAT].get("data") or {}).get("similar_to")
            if isinstance(target, str) and not await self._is_popular(ecosystem, target):
                wanted.append((POPULAR, {"ecosystem": ecosystem, "name": target}))

        created = []
        for kind, value in wanted:
            rule = await self._rules.propose(kind, value, review_id)
            if rule is not None:
                created.append(rule)
        return created

    async def active_rules(self, kind: str) -> list[dict[str, Any]]:
        if kind not in KINDS:
            raise ValueError(f"type de règle inconnu : {kind}")
        return await self._rules.active(kind)

    async def learned(self, ecosystem: str) -> Learned:
        def mine(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
            return [r for r in rows if r["value"].get("ecosystem") == ecosystem]

        return Learned(
            malicious={r["value"]["name"]: r for r in mine(await self.active_rules(KNOWN_MALICIOUS))},
            popular=frozenset(r["value"]["name"] for r in mine(await self.active_rules(POPULAR))),
            replacements={r["value"]["from"]: r for r in mine(await self.active_rules(REPLACEMENT_MAP))},
        )

    async def _decided_by_analyst(self, review: dict[str, Any]) -> bool:
        # Les décisions automatiques portent un libellé, pas un identifiant d'analyste.
        try:
            UUID(str(review.get("decided_by")))
        except ValueError:
            return False
        return await self._reviews.analyst(str(review["decided_by"])) is not None

    async def _replacement(self, review: dict[str, Any]) -> str | None:
        """Nom du package choisi par l'analyste à la place de celui-ci, s'il y en a un."""
        try:
            new_id = UUID(str((review.get("execution_result") or {}).get("replaced_by_review_id")))
        except ValueError:
            return None
        chosen = await self._reviews.get_review(new_id)
        return existence.normalize(review["registry"], chosen["package_name"]) if chosen else None

    async def _is_popular(self, ecosystem: str, name: str) -> bool:
        if name in BY_ECOSYSTEM[ecosystem]:
            return True
        return any(r["value"] == {"ecosystem": ecosystem, "name": name} for r in await self.active_rules(POPULAR))

    async def _protected(self, ecosystem: str, name: str) -> bool:
        """Un package répandu ou interne ne se retrouve pas bloqué par un rejet ponctuel."""
        if await self._is_popular(ecosystem, name):
            return True
        return bool(await self._reviews.internal_versions(ecosystem, name))
