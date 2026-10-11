"""Installation d'un package approuvé, uniquement dans l'environnement de l'agent victime.

Jamais dans l'environnement du backend. Sans PACKAGE_AGENT_ENV, l'installation
est seulement enregistrée (inventaire et trace) et annoncée comme simulée.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any, Protocol

INSTALL_TIMEOUT = 300


class InstallError(RuntimeError):
    pass


class Installer(Protocol):
    async def install(self, ecosystem: str, name: str, version: str, archive: Path | None) -> dict[str, Any]: ...

    async def uninstall(self, ecosystem: str, name: str) -> dict[str, Any]: ...


class RecordingInstaller:
    """N'exécute rien : l'installation est journalisée, pas réalisée."""

    async def install(self, ecosystem: str, name: str, version: str, archive: Path | None) -> dict[str, Any]:
        return {"installed": True, "simulated": True, "note": "Installation enregistrée, aucun code exécuté."}

    async def uninstall(self, ecosystem: str, name: str) -> dict[str, Any]:
        return {"removed": True, "simulated": True, "note": "Rien n'avait été installé : retrait enregistré."}


class AgentEnvInstaller:
    """Installe l'archive mise en quarantaine, et elle seule, dans le dossier isolé de l'agent."""

    def __init__(self, env_dir: Path) -> None:
        self._env = env_dir

    async def install(self, ecosystem: str, name: str, version: str, archive: Path | None) -> dict[str, Any]:
        if archive is None:
            raise InstallError("aucune archive en quarantaine pour ce package")
        if ecosystem == "pypi":
            python = self._env / "bin" / "python"
            if not python.is_file():
                raise InstallError("environnement virtuel de l'agent introuvable")
            command = [str(python), "-m", "pip", "install", "--no-deps", "--no-index",
                       "--disable-pip-version-check", str(archive)]
        else:
            command = ["npm", "install", "--ignore-scripts", "--no-audit", "--no-fund",
                       "--prefix", str(self._env / "node"), str(archive)]
        try:
            process = await asyncio.create_subprocess_exec(
                *command, stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.PIPE)
            _, stderr = await asyncio.wait_for(process.communicate(), INSTALL_TIMEOUT)
        except (OSError, asyncio.TimeoutError) as exc:
            raise InstallError(type(exc).__name__) from exc
        if process.returncode != 0:
            raise InstallError(stderr.decode("utf-8", errors="replace")[-300:].strip() or "échec de l'installation")
        return {"installed": True, "simulated": False, "environment": str(self._env)}

    async def uninstall(self, ecosystem: str, name: str) -> dict[str, Any]:
        """Désinstalle le package du dossier isolé de l'agent (jamais de l'environnement du backend)."""
        if ecosystem == "pypi":
            command = [str(self._env / "bin" / "python"), "-m", "pip", "uninstall", "-y", "--disable-pip-version-check", name]
        else:
            command = ["npm", "uninstall", "--no-audit", "--no-fund", "--prefix", str(self._env / "node"), name]
        try:
            process = await asyncio.create_subprocess_exec(
                *command, stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.PIPE)
            _, stderr = await asyncio.wait_for(process.communicate(), INSTALL_TIMEOUT)
        except (OSError, asyncio.TimeoutError) as exc:
            raise InstallError(type(exc).__name__) from exc
        if process.returncode != 0:
            raise InstallError(stderr.decode("utf-8", errors="replace")[-300:].strip() or "échec de la désinstallation")
        return {"removed": True, "simulated": False, "environment": str(self._env)}
