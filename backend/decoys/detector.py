"""Détecteur de piège : tout leurre lu ou exfiltré est une compromission quasi certaine.

Appelé par la passerelle sur chaque appel d'outil et chaque contenu échangé.
Il reçoit le contenu réel mais n'en écrit rien : la trace et l'alerte ne
citent que le nom du leurre.
"""

from __future__ import annotations

import base64
import json
import logging
import re
from dataclasses import dataclass
from typing import Any, Iterator
from urllib.parse import quote
from uuid import UUID

from decoys.store import DecoyRow, DecoyStore, Lures
from gateway.events import EventRecord, EventStore
from gateway.hooks import Direction
from gateway.session import Session
from vault.pseudonymize import Pseudonymizer
from vault.scanner import DECOY_PREFIX, Scanner

logger = logging.getLogger(__name__)

ACTOR = "detecteur_piege"
MIN_VALUE_LENGTH = 12  # en dessous, une valeur pourrait apparaître par hasard
_PG_PASSWORD = re.compile(r"://[^\s:@/]+:([^\s@]+)@")
_SUFFIX = " (leurre)"


@dataclass(frozen=True)
class Hit:
    label: str
    location: str
    decoy_id: UUID | None
    kind: str  # value : valeur du honeytoken ; label : nom du leurre ; resource : accès direct


@dataclass(frozen=True)
class _Lure:
    label: str
    location: str
    decoy_id: UUID | None


class Detector:
    def __init__(
        self, store: DecoyStore, events: EventStore, pseudonymizer: Pseudonymizer,
        scanner: Scanner | None = None,
    ) -> None:
        self._store = store
        self._events = events
        self._pseudonymizer = pseudonymizer
        self._scanner = scanner or Scanner()
        self._markers: dict[str, tuple[_Lure, str]] = {}  # chaîne à repérer → (leurre, nature)
        self._pattern: re.Pattern[str] | None = None
        self._resources: dict[str, _Lure] = {}  # identifiant ou chemin exact → leurre

    @property
    def lure_count(self) -> int:
        return len({lure.label for lure, _ in self._markers.values()})

    async def load(self) -> int:
        """Relit les leurres plantés. Rend le nombre de leurres reconnus."""
        lures = await self._store.lures()
        markers: dict[str, tuple[_Lure, str]] = {}
        resources: dict[str, _Lure] = {}
        forms: dict[str, tuple[str, str]] = {}
        for row in lures.rows:
            markers[row.label] = (_Lure(row.label, _clean(row.location), row.id), "label")
        for document in lures.documents:
            lure = _owner(lures, {document.title}, f"docs:{document.title}")
            resources[str(document.id)] = lure
            for value, kind in self._values(document.content).items():
                _add(markers, forms, value, kind, lure)
        for file in lures.files:
            full = f"{file.repository}/{file.path}"
            lure = _owner(lures, {full, file.path}, f"repo:{full}")
            resources[str(file.id)] = resources[full] = resources[file.path] = lure
            for value, kind in self._values(file.content).items():
                _add(markers, forms, value, kind, lure)
        self._markers, self._resources = markers, resources
        self._pattern = re.compile("|".join(
            re.escape(m) for m in sorted(markers, key=len, reverse=True))) if markers else None
        # Le coffre apprend ces valeurs : elles porteront un jeton LEURRE_…, distinct d'un vrai secret.
        self._pseudonymizer.set_decoys(forms)
        return self.lure_count

    def _values(self, content: str) -> dict[str, str]:
        """Valeurs à surveiller dans un contenu piège → type du secret imité (AWS, GITHUB…)."""
        found = {password: "PG" for password in _PG_PASSWORD.findall(content)}
        found.update({d.value: d.prefix.removeprefix("SECRET_") for d in self._scanner.scan_secrets(content)})
        return {value: kind for value, kind in found.items() if len(value) >= MIN_VALUE_LENGTH}

    def match(self, payload: Any, direction: Direction) -> list[Hit]:
        """Leurres présents dans le contenu. Fonction pure : n'écrit rien."""
        return self._scan(payload, direction)[0]

    def _scan(self, payload: Any, direction: Direction) -> tuple[list[Hit], list[str]]:
        hits: dict[tuple[str, str], Hit] = {}
        seen: dict[str, None] = {}  # formes de honeytokens rencontrées, telles qu'écrites
        strings = list(_strings(payload))
        if self._pattern is not None:
            for found in self._pattern.findall("\n".join(strings)):
                lure, kind = self._markers[found]
                hits.setdefault((lure.label, kind), Hit(lure.label, lure.location, lure.decoy_id, kind))
                if kind == "value":
                    seen[found] = None
        if direction == "call":
            # Un chemin de leurre dans une liste de fichiers ne prouve rien ; le demander, si.
            for text in strings:
                lure = self._resources.get(text.strip().removeprefix("./"))
                if lure is not None:
                    hits.setdefault((lure.label, "resource"),
                                    Hit(lure.label, lure.location, lure.decoy_id, "resource"))
        return list(hits.values()), list(seen)

    async def trips(self, session: Session, tool: str, payload: Any, direction: Direction) -> bool:
        hits, seen = self._scan(payload, direction)
        if not hits:
            return False
        # Les jetons que ces valeurs portent dans les traces : le lien entre LEURRE_… et le leurre.
        tokens = list((await self._pseudonymizer.pseudonymize(seen)).tokens)
        labels = sorted({h.label for h in hits})
        locations = sorted({h.location for h in hits})
        how = "utilisé dans un appel sortant" if direction == "call" else "lu"
        access = await self._trace(
            session, session.last_event, event_type="decoy_access", action=tool,
            content={"decoys": labels, "locations": locations, "tool": tool, "direction": direction,
                     "match": sorted({h.kind for h in hits}), "tokens": tokens})
        await self._store.record_trigger(
            sorted({h.decoy_id for h in hits if h.decoy_id is not None}, key=str),
            {"run_id": session.run_id, "trace_id": session.trace_id, "event_id": access,
             "severity": "critical", "affected_agent": session.agent_id,
             "summary": f"Leurre {', '.join(labels)} {how} via {tool} ({', '.join(locations)}). "
                        "Session déroutée vers le bac à sable."})
        await self._trace(
            session, access, event_type="session_diverted", action="divert",
            content={"reason": "decoy_access", "decoys": labels, "tokens": tokens})
        logger.warning("leurre %s déclenché (trace %s)", ", ".join(labels), session.trace_id)
        return True

    async def _trace(
        self, session: Session, parent: UUID | None, *, event_type: str, action: str,
        content: dict[str, Any],
    ) -> UUID:
        safe = await self._pseudonymizer.pseudonymize({"content": content})
        metadata = {"tokens": content["tokens"]} if content["tokens"] else {}
        return await self._events.insert(EventRecord(
            trace_id=session.trace_id, parent_event_id=parent, run_id=session.run_id,
            event_type=event_type, actor_type="system", actor_id=ACTOR, action=action,
            result="detected", resource_type="decoy", resource_id=", ".join(content["decoys"]),
            content=json.dumps(safe.value["content"], ensure_ascii=False), metadata=metadata))


def _clean(location: str) -> str:
    return location.removesuffix(_SUFFIX).strip()


def _owner(lures: Lures, keys: set[str], fallback: str) -> _Lure:
    """Ligne de public.decoys dont l'emplacement désigne ce contenu."""
    for row in lures.rows:
        if _clean(row.location).split(":", 1)[-1] in keys:
            return _lure(row)
    return _Lure(fallback, fallback, None)


def _lure(row: DecoyRow) -> _Lure:
    return _Lure(row.label, _clean(row.location), row.id)


def _add(
    markers: dict[str, tuple[_Lure, str]], forms: dict[str, tuple[str, str]], value: str, kind: str,
    lure: _Lure,
) -> None:
    # La valeur brute, et ses formes encodées les plus courantes pour une exfiltration.
    prefix = f"{DECOY_PREFIX}_{re.sub(r'[^A-Z]+', '_', kind.upper()).strip('_') or 'GENERIC'}"[:30].rstrip("_")
    for form in {value, base64.b64encode(value.encode()).decode().rstrip("="), quote(value, safe="")}:
        markers.setdefault(form, (lure, "value"))
        forms.setdefault(form, (value, prefix))


def _strings(payload: Any) -> Iterator[str]:
    if isinstance(payload, str):
        yield payload
    elif isinstance(payload, dict):
        for key, value in payload.items():
            yield str(key)
            yield from _strings(value)
    elif isinstance(payload, (list, tuple, set, frozenset)):
        for value in payload:
            yield from _strings(value)
    elif isinstance(payload, (bytes, bytearray)):
        yield bytes(payload).decode("utf-8", errors="replace")
    elif payload is not None and not isinstance(payload, (bool, int, float)):
        yield str(payload)
