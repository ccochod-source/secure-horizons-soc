"""Étape 2 — existence, typosquatting et âge du package.

On interroge le registre public sans rien installer. Un nom introuvable est un
nom halluciné (slopsquatting) : signal bloquant.
"""

from __future__ import annotations

import base64
import re
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any
from urllib.parse import quote

import httpx

from packages.popular import BY_ECOSYSTEM
from packages.score import Signal, signal

ECOSYSTEMS = ("pypi", "npm")
PYPI_URL = "https://pypi.org/pypi/{name}/json"
NPM_URL = "https://registry.npmjs.org/{name}"

NEW_PACKAGE = timedelta(days=30)
NEW_VERSION = timedelta(days=7)

# Le nom finit dans une URL : on n'accepte que la forme admise par chaque registre.
_NAME = {
    "pypi": re.compile(r"[A-Za-z0-9](?:[A-Za-z0-9._-]{0,98}[A-Za-z0-9])?"),
    "npm": re.compile(r"(?:@[a-z0-9~-][a-z0-9._~-]*/)?[a-z0-9~-][a-z0-9._~-]*"),
}
_VERSION = re.compile(r"[A-Za-z0-9][A-Za-z0-9._+!-]{0,63}")
_REPO_HOST = re.compile(r"(?:github\.com|gitlab\.com|bitbucket\.org|codeberg\.org|sr\.ht)/[^\s/]+/[^\s/]+")


class RegistryUnavailable(RuntimeError):
    """Le registre n'a pas répondu : on ne peut pas conclure, donc on n'installe pas."""


class VersionNotFound(RuntimeError):
    pass


@dataclass(frozen=True)
class PackageInfo:
    ecosystem: str
    name: str
    version: str
    created_at: datetime | None
    version_published_at: datetime | None
    versions_count: int
    maintainers: int | None  # inconnu sur PyPI
    repository: str | None
    archive_url: str | None
    archive_filename: str | None
    archive_digest: tuple[str, str] | None  # (algorithme, hexadécimal) annoncé par le registre
    install_from_source: bool  # vrai si l'installation exécuterait un script (sdist)


def valid_request(ecosystem: Any, name: Any, version: Any) -> str | None:
    """Rend la raison du refus, ou None si la demande est bien formée."""
    if ecosystem not in ECOSYSTEMS:
        return "écosystème inconnu (pypi ou npm attendu)"
    if not isinstance(name, str) or len(name) > 214 or _NAME[ecosystem].fullmatch(name) is None:
        return "nom de package invalide"
    if version is not None and (not isinstance(version, str) or _VERSION.fullmatch(version) is None):
        return "version invalide"
    return None


def normalize(ecosystem: str, name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower() if ecosystem == "pypi" else name


async def lookup(client: httpx.AsyncClient, ecosystem: str, name: str, version: str | None) -> PackageInfo | None:
    """Métadonnées du registre, ou None si le package n'existe pas."""
    template = PYPI_URL if ecosystem == "pypi" else NPM_URL
    try:
        response = await client.get(template.format(name=quote(name, safe="@")))
    except httpx.HTTPError as exc:
        raise RegistryUnavailable(type(exc).__name__) from exc
    if response.status_code == 404:
        return None
    if response.status_code != 200:
        raise RegistryUnavailable(f"HTTP {response.status_code}")
    try:
        data = response.json()
        return _pypi(name, version, data) if ecosystem == "pypi" else _npm(name, version, data)
    except (ValueError, KeyError, TypeError, AttributeError) as exc:
        raise RegistryUnavailable(f"réponse illisible ({type(exc).__name__})") from exc


def _pypi(name: str, version: str | None, data: dict[str, Any]) -> PackageInfo | None:
    info = data["info"]
    releases: dict[str, list[dict[str, Any]]] = data.get("releases") or {}
    resolved = version or info.get("version")
    if not resolved or not releases:
        return None
    if resolved not in releases:
        raise VersionNotFound(resolved)
    files = [f for f in releases[resolved] if not f.get("yanked")]
    uploads = [_when(f.get("upload_time_iso_8601")) for fs in releases.values() for f in fs]
    published = [_when(f.get("upload_time_iso_8601")) for f in files]
    # pip installe la wheel quand elle existe : c'est elle qu'on analyse. Sans
    # wheel, l'installation exécuterait setup.py depuis la sdist.
    wheels = [f for f in files if f.get("packagetype") == "bdist_wheel"]
    chosen = next((f for f in wheels if f["filename"].endswith("none-any.whl")), None) \
        or (wheels[0] if wheels else None) \
        or next((f for f in files if f.get("packagetype") == "sdist"), None)
    urls = " ".join([*(info.get("project_urls") or {}).values(), info.get("home_page") or ""])
    return PackageInfo(
        ecosystem="pypi", name=name, version=resolved,
        created_at=min((u for u in uploads if u), default=None),
        version_published_at=min((u for u in published if u), default=None),
        versions_count=len(releases), maintainers=None, repository=_repository(urls),
        archive_url=chosen["url"] if chosen else None,
        archive_filename=chosen["filename"] if chosen else None,
        archive_digest=("sha256", chosen["digests"]["sha256"]) if chosen else None,
        install_from_source=bool(chosen) and chosen.get("packagetype") == "sdist",
    )


def _npm(name: str, version: str | None, data: dict[str, Any]) -> PackageInfo | None:
    versions: dict[str, dict[str, Any]] = data.get("versions") or {}
    resolved = version or (data.get("dist-tags") or {}).get("latest")
    if not versions or not resolved:
        return None  # nom dépublié
    if resolved not in versions:
        raise VersionNotFound(resolved)
    meta = versions[resolved]
    times = data.get("time") or {}
    dist = meta.get("dist") or {}
    repository = data.get("repository") or meta.get("repository") or ""
    if isinstance(repository, dict):
        repository = repository.get("url") or ""
    tarball = dist.get("tarball")
    return PackageInfo(
        ecosystem="npm", name=name, version=resolved,
        created_at=_when(times.get("created")), version_published_at=_when(times.get(resolved)),
        versions_count=len(versions), maintainers=len(data.get("maintainers") or []),
        repository=_repository(str(repository)),
        archive_url=tarball, archive_filename=tarball.rsplit("/", 1)[-1] if tarball else None,
        archive_digest=_npm_digest(dist), install_from_source=False,
    )


def _npm_digest(dist: dict[str, Any]) -> tuple[str, str] | None:
    integrity = str(dist.get("integrity") or "").split(" ")[0]
    algorithm, _, encoded = integrity.partition("-")
    if algorithm in ("sha512", "sha384", "sha256") and encoded:
        return algorithm, base64.b64decode(encoded).hex()
    return ("sha1", dist["shasum"]) if dist.get("shasum") else None


def _repository(text: str) -> str | None:
    found = _REPO_HOST.search(text)
    return found.group() if found else None


def _when(value: Any) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def similar_popular(ecosystem: str, name: str) -> str | None:
    """Package répandu dont le nom est à une faute de frappe de celui demandé."""
    wanted = normalize(ecosystem, name)
    popular = BY_ECOSYSTEM[ecosystem]
    if wanted in popular:
        return None
    best: tuple[int, str] | None = None
    for candidate in popular:
        if len(candidate) < 4 or abs(len(candidate) - len(wanted)) > 2:
            continue
        distance = edit_distance(wanted, candidate)
        # À deux fautes, les noms courts se ressemblent tous : on exige un nom long.
        if distance == 1 or (distance == 2 and len(candidate) >= 8):
            if best is None or (distance, candidate) < best:
                best = (distance, candidate)
    return best[1] if best else None


def edit_distance(a: str, b: str) -> int:
    """Distance d'édition où l'inversion de deux lettres voisines compte pour une faute."""
    previous2: list[int] = []
    previous = list(range(len(b) + 1))
    for i, ca in enumerate(a, start=1):
        current = [i]
        for j, cb in enumerate(b, start=1):
            cost = min(previous[j] + 1, current[j - 1] + 1, previous[j - 1] + (ca != cb))
            if i > 1 and j > 1 and ca == b[j - 2] and a[i - 2] == cb:
                cost = min(cost, previous2[j - 2] + 1)
            current.append(cost)
        previous2, previous = previous, current
    return previous[-1]


def name_signals(ecosystem: str, name: str) -> list[Signal]:
    target = similar_popular(ecosystem, name)
    if target is None:
        return []
    return [signal("typosquat", f"Nom très proche du package répandu « {target} ».", similar_to=target)]


def age_signals(info: PackageInfo, now: datetime) -> list[Signal]:
    found: list[Signal] = []
    if info.created_at is not None and now - info.created_at < NEW_PACKAGE:
        days = max((now - info.created_at).days, 0)
        found.append(signal("recently_created", f"Package créé il y a {days} jour(s).", age_days=days))
    elif info.version_published_at is not None and now - info.version_published_at < NEW_VERSION:
        days = max((now - info.version_published_at).days, 0)
        found.append(signal("recent_version", f"Version {info.version} publiée il y a {days} jour(s).", age_days=days))
    return found
