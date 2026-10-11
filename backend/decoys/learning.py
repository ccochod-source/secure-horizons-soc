"""Boucle d'amélioration des leurres.

Quand un analyste confirme qu'une alerte de leurre était une vraie attaque, le
système propose un nouveau leurre du même type près de celui qui a été touché.
La proposition ne naît que de ce verdict : jamais du contenu d'un agent ou
d'un document. Elle n'est semée qu'une fois appliquée par un analyste. Un
verdict « false_positive » ne crée aucune règle.
"""

from __future__ import annotations

import logging
from dataclasses import replace
from typing import Any
from uuid import UUID

from common.rules import RuleStore
from decoys.seed import LURES, LureSpec
from decoys.store import ALERT_SOURCE, DecoyStore

logger = logging.getLogger(__name__)

NEW_DECOY_LOCATION = "new_decoy_location"
CONFIRMED = "confirmed"
FALSE_POSITIVE = "false_positive"

_BASE = {spec.label: spec for spec in LURES}


def nearby(spec: LureSpec, rule_id: int | None = None) -> LureSpec:
    """Leurre voisin d'un leurre écrit à la main : même type, même dossier, contenu fabriqué au semis."""
    name = f"{spec.name} (archive)" if spec.kind == "document" else f"{spec.name}.old"
    label = f"HONEYTOKEN_R{rule_id:03d}" if rule_id is not None else spec.label
    return replace(spec, label=label, name=name)


class DecoyLearning:
    def __init__(self, rules: RuleStore, store: DecoyStore) -> None:
        self._rules = rules
        self._store = store

    @property
    def rules(self) -> RuleStore:
        return self._rules

    async def record_verdict(self, alert_id: UUID, verdict: str, analyst: str) -> bool | None:
        """Enregistre le verdict et son auteur. None : alerte inconnue ; False : verdict déjà rendu."""
        if await self._store.alert(alert_id) is None:
            return None
        return await self._store.set_verdict(alert_id, verdict, analyst)

    async def propose(self, alert_id: UUID) -> list[dict[str, Any]]:
        """Propositions tirées d'un verdict déjà enregistré. Rend celles réellement créées."""
        alert = await self._store.alert(alert_id)
        if (alert is None or alert["analyst_verdict"] != CONFIRMED or alert["analyst_verdict_by"] is None
                or alert["source"] != ALERT_SOURCE):
            return []
        created = []
        for label in alert["decoys"]:
            base = _BASE.get(label)
            if base is None:
                continue  # seuls les leurres écrits à la main servent de modèle
            rule = await self._rules.propose(NEW_DECOY_LOCATION, {
                "decoy_type": base.decoy_type, "near": base.label, "near_location": base.location,
                "location": nearby(base).location}, alert_id)
            if rule is not None:
                created.append(rule)
        return created


async def learned_lures(rules: RuleStore) -> tuple[LureSpec, ...]:
    """Leurres à semer en plus de la liste écrite à la main : règles actives uniquement."""
    specs = []
    for rule in await rules.active(NEW_DECOY_LOCATION):
        base = _BASE.get(rule["value"].get("near"))
        if base is None or nearby(base).location != rule["value"].get("location"):
            logger.warning("règle de leurre %s ignorée : modèle inconnu", rule["id"])
            continue
        specs.append(nearby(base, rule["id"]))
    return tuple(specs)
