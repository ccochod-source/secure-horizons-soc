"""Zone de quarantaine : l'archive est téléchargée, jamais installée ni exécutée.

Faute de bucket Supabase Storage « package-quarantine », les archives sont
rangées dans un dossier local hors dépôt ; storage_ref y renvoie.
"""

from __future__ import annotations

import hashlib
import re
import tempfile
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse

import httpx

from packages.existence import PackageInfo

# Seuls les hôtes de fichiers des registres sont joignables, même si le registre annonce autre chose.
ALLOWED_HOSTS = frozenset({"files.pythonhosted.org", "registry.npmjs.org"})
MAX_ARCHIVE_BYTES = 50 * 1024 * 1024
_SAFE_FILENAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9._+-]{0,200}")
_REF = re.compile(r"quarantine/([0-9a-f]{64})/([A-Za-z0-9][A-Za-z0-9._+-]{0,200})")


class ArchiveUnavailable(RuntimeError):
    pass


class DigestMismatch(RuntimeError):
    """L'archive reçue n'est pas celle que le registre annonce."""


@dataclass(frozen=True)
class Archive:
    path: Path
    sha256: str
    size: int
    storage_ref: str
    filename: str


class LocalQuarantine:
    def __init__(self, root: Path) -> None:
        self._root = root

    async def fetch(self, client: httpx.AsyncClient, info: PackageInfo) -> Archive:
        if not info.archive_url:
            raise ArchiveUnavailable("aucune archive publiée pour cette version")
        url = urlparse(info.archive_url)
        if url.scheme != "https" or url.hostname not in ALLOWED_HOSTS:
            raise ArchiveUnavailable("archive hébergée hors du registre")
        filename = info.archive_filename or ""
        if _SAFE_FILENAME.fullmatch(filename) is None:
            filename = "archive"
        self._root.mkdir(parents=True, exist_ok=True)
        sha256 = hashlib.sha256()
        declared = hashlib.new(info.archive_digest[0]) if info.archive_digest else None
        size = 0
        with tempfile.NamedTemporaryFile(dir=self._root, delete=False) as partial:
            temporary = Path(partial.name)
            try:
                # Pas de redirection suivie : elle pourrait sortir des hôtes autorisés.
                async with client.stream("GET", info.archive_url, follow_redirects=False) as response:
                    if response.status_code != 200:
                        raise ArchiveUnavailable(f"HTTP {response.status_code}")
                    async for chunk in response.aiter_bytes():
                        size += len(chunk)
                        if size > MAX_ARCHIVE_BYTES:
                            raise ArchiveUnavailable("archive trop volumineuse")
                        sha256.update(chunk)
                        if declared is not None:
                            declared.update(chunk)
                        partial.write(chunk)
            except httpx.HTTPError as exc:
                temporary.unlink(missing_ok=True)
                raise ArchiveUnavailable(type(exc).__name__) from exc
            except BaseException:
                temporary.unlink(missing_ok=True)
                raise
        digest = sha256.hexdigest()
        if declared is not None and declared.hexdigest() != info.archive_digest[1].lower():
            temporary.unlink(missing_ok=True)
            raise DigestMismatch(info.archive_digest[0])
        target = self._root / digest / filename
        target.parent.mkdir(parents=True, exist_ok=True)
        temporary.replace(target)
        target.chmod(0o400)
        return Archive(target, digest, size, f"quarantine/{digest}/{filename}", filename)

    def path(self, storage_ref: str | None) -> Path | None:
        """Chemin local d'une archive déjà en quarantaine, ou None."""
        found = _REF.fullmatch(storage_ref or "")
        if found is None:
            return None
        path = self._root / found.group(1) / found.group(2)
        return path if path.is_file() else None
