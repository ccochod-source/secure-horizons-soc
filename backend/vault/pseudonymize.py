"""Remplace secrets et données personnelles par des jetons typés et stables.

Tout contenu passe ici avant d'être écrit en base ou montré à un LLM
défenseur. Le même secret donne toujours le même jeton, ce qui permet de
suivre sa trajectoire sans connaître sa valeur.
"""

from __future__ import annotations

import hashlib
import hmac
import re
import secrets
from dataclasses import dataclass
from typing import Any, Iterable

from vault.gitguardian import GitGuardianClient
from vault.scanner import SECRET, SENSITIVE_KEY, Detection, Scanner, is_token
from vault.tokens import TokenStore

_CACHE_LIMIT = 10_000


class VaultError(RuntimeError):
    """La pseudonymisation a échoué : l'appelant ne doit rien écrire ni transmettre."""


@dataclass(frozen=True)
class Pseudonymized:
    value: Any
    tokens: tuple[str, ...]  # jetons substitués dans value, sans doublon


class Pseudonymizer:
    def __init__(
        self,
        tokens: TokenStore,
        scanner: Scanner | None = None,
        gitguardian: GitGuardianClient | None = None,
    ) -> None:
        self._tokens = tokens
        self.scanner = scanner or Scanner()
        self._gitguardian = gitguardian
        # Cache valeur → jeton, indexé par HMAC pour ne pas garder de clair en mémoire.
        self._cache_key = secrets.token_bytes(32)
        self._cache: dict[bytes, str] = {}
        # Honeytokens connus : forme repérable (brute ou encodée) → (valeur brute, préfixe du jeton).
        self._decoys: dict[str, tuple[str, str]] = {}
        self._decoys_re: re.Pattern[str] | None = None

    def set_decoys(self, forms: dict[str, tuple[str, str]]) -> None:
        """Valeurs des leurres plantés : elles reçoivent un jeton LEURRE_…, jamais SECRET_…

        Une forme encodée renvoie à la valeur brute, donc au même jeton qu'elle.
        """
        self._decoys = dict(forms)
        self._decoys_re = re.compile("|".join(
            re.escape(form) for form in sorted(forms, key=len, reverse=True))) if forms else None
        self._cache.clear()

    async def pseudonymize(self, obj: Any) -> Pseudonymized:
        """Rend une copie JSON-compatible de obj où chaque valeur sensible est un jeton."""
        plain = _jsonable(obj)
        extra = await self._gitguardian_matches(plain)

        plans: dict[tuple[str, bool], list[Detection]] = {}
        for text, sensitive in _strings(plain):
            if (text, sensitive) not in plans:
                plans[(text, sensitive)] = self._detect(text, sensitive, extra)

        wanted: dict[str, str] = {}
        for detections in plans.values():
            for d in detections:
                wanted.setdefault(d.value, d.prefix)
        mapping = await self._resolve(wanted)

        used: dict[str, None] = {}

        def rewrite(text: str, sensitive: bool) -> str:
            for d in reversed(plans[(text, sensitive)]):
                token = mapping[d.value]
                used[token] = None
                text = text[: d.start] + token + text[d.end :]
            return text

        return Pseudonymized(_rebuild(plain, rewrite), tuple(used))

    def _detect(self, text: str, sensitive: bool, extra: list[tuple[str, str]]) -> list[Detection]:
        if not text or is_token(text):
            return []
        detections = self.scanner.scan(text)
        if extra:
            reported = [
                Detection(prefix, value, start, start + len(value), SECRET, 40)
                for prefix, value in extra
                for start in _occurrences(text, value)
            ]
            detections = _merge(detections, reported)
        lures: list[Detection] = []
        if self._decoys_re is not None:
            for found in self._decoys_re.finditer(text):
                value, prefix = self._decoys[found.group()]
                lures.append(Detection(prefix, value, found.start(), found.end(), SECRET, -1))
            detections = _merge(detections, lures)
        if sensitive and not lures and not any(d.start == 0 and d.end == len(text) for d in detections):
            # Valeur d'un champ « password », « api_key »… : secrète en entier.
            return [Detection("SECRET_GENERIC", text, 0, len(text), SECRET, 0)]
        return detections

    async def _gitguardian_matches(self, plain: Any) -> list[tuple[str, str]]:
        if self._gitguardian is None:
            return []
        document = "\n".join(dict.fromkeys(text for text, _ in _strings(plain)))
        return await self._gitguardian.scan(document)

    async def _resolve(self, wanted: dict[str, str]) -> dict[str, str]:
        mapping: dict[str, str] = {}
        missing: list[tuple[str, str]] = []
        for value, prefix in wanted.items():
            token = self._cache.get(self._digest(value))
            if token is None:
                missing.append((prefix, value))
            else:
                mapping[value] = token
        if missing:
            try:
                tokens = await self._tokens.tokens_for(missing)
            except Exception as exc:
                raise VaultError(f"coffre indisponible ({type(exc).__name__})") from exc
            if len(tokens) != len(missing):
                raise VaultError("réponse du coffre incohérente")
            if len(self._cache) + len(missing) > _CACHE_LIMIT:
                self._cache.clear()
            for (_, value), token in zip(missing, tokens):
                mapping[value] = token
                self._cache[self._digest(value)] = token
        return mapping

    def _digest(self, value: str) -> bytes:
        return hmac.new(self._cache_key, value.encode(), hashlib.sha256).digest()


def _jsonable(obj: Any) -> Any:
    if obj is None or isinstance(obj, (bool, int, float, str)):
        return obj
    if isinstance(obj, dict):
        return {str(k): _jsonable(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple, set, frozenset)):
        return [_jsonable(v) for v in obj]
    if isinstance(obj, (bytes, bytearray)):
        return bytes(obj).decode("utf-8", errors="replace")
    if hasattr(obj, "model_dump"):
        return _jsonable(obj.model_dump(mode="json"))
    # Type inconnu : on le passe en texte pour qu'il soit scanné comme le reste.
    return str(obj)


def _strings(plain: Any, sensitive: bool = False) -> Iterable[tuple[str, bool]]:
    """Toutes les chaînes de la structure, avec « sa clé désigne un secret »."""
    if isinstance(plain, str):
        yield plain, sensitive
    elif isinstance(plain, dict):
        for key, value in plain.items():
            yield key, False
            yield from _strings(value, isinstance(value, str) and SENSITIVE_KEY.search(key) is not None)
    elif isinstance(plain, list):
        for value in plain:
            yield from _strings(value)


def _rebuild(plain: Any, rewrite, sensitive: bool = False) -> Any:
    if isinstance(plain, str):
        return rewrite(plain, sensitive)
    if isinstance(plain, dict):
        return {
            rewrite(key, False): _rebuild(
                value, rewrite, isinstance(value, str) and SENSITIVE_KEY.search(key) is not None
            )
            for key, value in plain.items()
        }
    if isinstance(plain, list):
        return [_rebuild(value, rewrite) for value in plain]
    return plain


def _occurrences(text: str, value: str) -> Iterable[int]:
    start = text.find(value)
    while start != -1:
        yield start
        start = text.find(value, start + len(value))


def _merge(local: list[Detection], reported: list[Detection]) -> list[Detection]:
    kept: list[Detection] = []
    for d in sorted(local + reported, key=lambda d: (d.priority, -(d.end - d.start), d.start)):
        if all(d.end <= k.start or d.start >= k.end for k in kept):
            kept.append(d)
    return sorted(kept, key=lambda d: d.start)
