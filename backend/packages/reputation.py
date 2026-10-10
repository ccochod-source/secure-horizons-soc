"""Étape 4 — réputation : vulnérabilités connues (OSV), ancienneté, dépôt source."""

from __future__ import annotations

from typing import Any

import httpx

from packages.existence import PackageInfo
from packages.score import Signal, signal

OSV_URL = "https://api.osv.dev/v1/query"
_OSV_ECOSYSTEM = {"pypi": "PyPI", "npm": "npm"}


async def reputation(client: httpx.AsyncClient, info: PackageInfo) -> list[Signal]:
    found: list[Signal] = []
    try:
        response = await client.post(OSV_URL, json={
            "package": {"name": info.name, "ecosystem": _OSV_ECOSYSTEM[info.ecosystem]},
            "version": info.version,
        })
        response.raise_for_status()
        vulnerabilities: list[dict[str, Any]] = response.json().get("vulns") or []
    except (httpx.HTTPError, ValueError, AttributeError):
        found.append(signal("reputation_unavailable", "Base de vulnérabilités OSV injoignable."))
    else:
        critical = [v["id"] for v in vulnerabilities if _severity(v) == "CRITICAL"]
        others = [v["id"] for v in vulnerabilities if _severity(v) != "CRITICAL"]
        if critical:
            found.append(signal("critical_vulnerability",
                                "Vulnérabilité critique connue : " + ", ".join(critical[:5]) + ".", ids=critical))
        if others:
            found.append(signal("known_vulnerability",
                                f"{len(others)} vulnérabilité(s) connue(s) sur cette version.", ids=others[:20]))
    if info.repository is None:
        detail = " et un seul mainteneur" if info.maintainers == 1 else ""
        found.append(signal("no_source_repository", f"Aucun dépôt source déclaré{detail}."))
    if info.versions_count <= 1:
        found.append(signal("single_release", "Une seule version publiée."))
    return found


def _severity(vulnerability: dict[str, Any]) -> str:
    return str((vulnerability.get("database_specific") or {}).get("severity") or "").upper()
