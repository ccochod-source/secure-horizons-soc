"""Scan GitGuardian, en complément des règles locales (optionnel).

Une panne ou un refus de l'API ne bloque rien : les règles locales ont déjà
tourné. Le contenu scanné n'est jamais journalisé.
"""

from __future__ import annotations

import logging
import re

import httpx

logger = logging.getLogger(__name__)

_MAX_DOCUMENT_BYTES = 1_000_000  # limite de l'API par document
_MIN_MATCH_LENGTH = 8  # en dessous, remplacer la chaîne partout ferait trop de bruit


class GitGuardianClient:
    def __init__(
        self,
        api_key: str,
        *,
        base_url: str = "https://api.gitguardian.com",
        timeout: float = 5.0,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self._client = client or httpx.AsyncClient(timeout=timeout)
        self._url = f"{base_url.rstrip('/')}/v1/scan"
        self._headers = {"Authorization": f"Token {api_key}"}

    async def aclose(self) -> None:
        await self._client.aclose()

    async def scan(self, document: str) -> list[tuple[str, str]]:
        """Rend les (préfixe de jeton, chaîne secrète) trouvés dans le document."""
        if not document.strip():
            return []
        if len(document.encode()) > _MAX_DOCUMENT_BYTES:
            logger.warning("GitGuardian : document trop volumineux, règles locales seules")
            return []
        try:
            response = await self._client.post(self._url, headers=self._headers, json={"document": document})
            response.raise_for_status()
            breaks = response.json().get("policy_breaks", [])
        except (httpx.HTTPError, ValueError) as exc:
            logger.warning("GitGuardian indisponible (%s), règles locales seules", type(exc).__name__)
            return []
        found: list[tuple[str, str]] = []
        for policy_break in breaks:
            prefix = _prefix(str(policy_break.get("type", "")))
            for match in policy_break.get("matches", []):
                value = match.get("match")
                if isinstance(value, str) and len(value) >= _MIN_MATCH_LENGTH:
                    found.append((prefix, value))
        return found


def _prefix(detector: str) -> str:
    # public.pseudonymize_value n'accepte que lettres et « _ », 30 caractères au plus.
    slug = re.sub(r"[^A-Za-z]+", "_", detector).strip("_").upper()[:23].rstrip("_")
    return f"SECRET_{slug}" if slug else "SECRET_GENERIC"
