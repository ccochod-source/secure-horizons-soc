"""Étape 3 — analyse statique : le code est lu dans l'archive, jamais extrait ni exécuté."""

from __future__ import annotations

import asyncio
import json
import logging
import re
import shutil
import tarfile
import zipfile
from pathlib import Path, PurePosixPath
from typing import Any, Iterator

from packages.score import Signal, signal
from vault.scanner import Scanner

logger = logging.getLogger(__name__)

MAX_FILE_BYTES = 1_000_000
MAX_TOTAL_BYTES = 30_000_000
MAX_FILES = 5_000
MAX_SECRET_SCAN_BYTES = 200_000
MAX_EXCERPTS = 3
GUARDDOG_TIMEOUT = 120

_CODE = (".py", ".pyw", ".pth", ".js", ".cjs", ".mjs", ".ts", ".sh")
_READ = _CODE + (".json", ".cfg", ".toml", ".yml", ".yaml", ".txt", ".env")
_NPM_INSTALL_HOOKS = ("preinstall", "install", "postinstall")

_NETWORK = re.compile(
    r"urllib\.request|urlopen\(|requests\.(?:get|post|put)\(|http\.client|socket\.socket\(|"
    r"https?\.(?:request|get)\(|(?<![\w.])fetch\(|XMLHttpRequest|net\.connect\(|\bcurl\s|\bwget\s|"
    r"require\([\"'](?:node:)?(?:https?|net|dgram)[\"']\)|from\s+[\"'](?:node:)?(?:https?|net|dgram)[\"']"
)
_PROCESS = re.compile(r"os\.system\(|subprocess\.|os\.popen\(|child_process|execSync\(|(?<![\w.])spawn\(")
_DECODE = re.compile(
    r"b64decode|atob\(|Buffer\.from\([^)\n]*base64|marshal\.loads|zlib\.decompress|codecs\.decode\([^)\n]*rot"
)
_DYNAMIC = re.compile(r"(?<![\w.])exec\(|(?<![\w.])eval\(|new Function\(")
_CREDENTIALS = re.compile(
    r"\.ssh/|\bid_rsa\b|\.aws/credentials|\.npmrc|\.git-credentials|/etc/passwd|[\"'/]\.env[\"']"
)
_ENV_DUMP = re.compile(
    r"dict\(os\.environ\)|os\.environ\.copy\(\)|os\.environ\.items\(\)|JSON\.stringify\(process\.env\)"
)
_NODE_SCRIPT = re.compile(r"\bnode\s+(?:\./)?([\w./-]+\.[cm]?js)")
_SHELL_FETCH = re.compile(r"\bcurl\b|\bwget\b|https?://|\bnode\s+-e\b|base64")


def read_archive(path: Path) -> Iterator[tuple[str, str]]:
    """(chemin, texte) des fichiers lisibles, bornés en nombre et en taille."""
    total = 0
    for count, (name, size, read) in enumerate(_members(path)):
        if count >= MAX_FILES or total >= MAX_TOTAL_BYTES:
            return
        if size > MAX_FILE_BYTES or not name.lower().endswith(_READ):
            continue
        total += size
        yield name, read().decode("utf-8", errors="replace")


def _members(path: Path) -> Iterator[tuple[str, int, Any]]:
    if zipfile.is_zipfile(path):
        with zipfile.ZipFile(path) as archive:
            for entry in archive.infolist():
                if not entry.is_dir():
                    yield entry.filename, entry.file_size, lambda e=entry: archive.read(e)
        return
    with tarfile.open(path, "r:*") as archive:
        for member in archive:
            if member.isfile():
                yield member.name, member.size, lambda m=member: archive.extractfile(m).read()


def analyze_archive(path: Path, ecosystem: str, install_from_source: bool, scanner: Scanner) -> list[Signal]:
    files = dict(read_archive(path))
    hooks: dict[str, str] = {}
    install_files: set[str] = set()
    for name, text in files.items():
        parts = PurePosixPath(name).parts
        if ecosystem == "npm" and len(parts) == 2 and parts[1] == "package.json":
            hooks = _npm_hooks(text)
            for command in hooks.values():
                install_files |= {str(PurePosixPath(parts[0], ref)) for ref in _NODE_SCRIPT.findall(command)}
        if ecosystem == "pypi" and install_from_source and len(parts) == 2 and parts[1] == "setup.py":
            install_files.add(name)

    found: dict[str, list[dict[str, Any]]] = {}

    def add(code: str, name: str, text: str, match: re.Match[str] | None) -> None:
        excerpts = found.setdefault(code, [])
        if match is not None and len(excerpts) < MAX_EXCERPTS:
            excerpts.append(_excerpt(name, text, match.start()))

    for hook, command in hooks.items():
        found.setdefault("install_script", []).append({"file": "package.json", "line": None, "code": f"{hook}: {command}"[:240]})
        if _SHELL_FETCH.search(command):
            found.setdefault("network_in_install_script", []).append(
                {"file": "package.json", "line": None, "code": f"{hook}: {command}"[:240]})

    for name, text in files.items():
        lowered = name.lower()
        if not lowered.endswith(_CODE):
            continue
        network = _NETWORK.search(text)
        if lowered.endswith(".pth"):
            executed = re.search(r"(?m)^import\s.+", text)
            if executed:
                add("install_script", name, text, executed)
            continue
        if name in install_files:
            runs = _PROCESS.search(text) or network or _DECODE.search(text)
            if runs:
                add("install_script", name, text, runs)
            if network:
                add("network_in_install_script", name, text, network)
        decode, dynamic = _DECODE.search(text), _DYNAMIC.search(text)
        if decode and dynamic:
            add("obfuscated_code", name, text, dynamic)
        credentials = _CREDENTIALS.search(text)
        # Copier l'environnement est banal ; le copier et parler au réseau ne l'est pas.
        leaked = credentials or _ENV_DUMP.search(text)
        if leaked and network:
            add("exfiltration_pattern", name, text, leaked)
        elif credentials:
            add("credential_file_access", name, text, credentials)
        if len(text) <= MAX_SECRET_SCAN_BYTES:
            for detection in scanner.scan_secrets(text):
                if detection.prefix != "SECRET_GENERIC":
                    excerpts = found.setdefault("embedded_secret", [])
                    if len(excerpts) < MAX_EXCERPTS:
                        excerpts.append({"file": name, "line": text.count("\n", 0, detection.start) + 1,
                                         "code": f"[{detection.prefix} masqué]"})

    explanations = {
        "install_script": "Du code s'exécute à l'installation (setup.py, .pth ou script npm).",
        "network_in_install_script": "Le script d'installation ouvre une connexion réseau.",
        "obfuscated_code": "Code décodé puis exécuté dynamiquement (base64 + exec/eval).",
        "exfiltration_pattern": "Lecture d'identifiants ou de l'environnement et envoi réseau dans le même fichier.",
        "credential_file_access": "Lecture de fichiers d'identifiants (clés SSH, .env, .npmrc…).",
        "embedded_secret": "Secret embarqué dans le code du package.",
    }
    return [signal(code, explanations[code], excerpts) for code, excerpts in found.items()]


def _npm_hooks(package_json: str) -> dict[str, str]:
    try:
        scripts = json.loads(package_json).get("scripts") or {}
    except (ValueError, AttributeError):
        return {}
    return {h: str(scripts[h]) for h in _NPM_INSTALL_HOOKS if isinstance(scripts, dict) and scripts.get(h)}


def _excerpt(name: str, text: str, position: int) -> dict[str, Any]:
    start = text.rfind("\n", 0, position) + 1
    end = text.find("\n", position)
    line = text[start: end if end != -1 else len(text)].strip()
    return {"file": name, "line": text.count("\n", 0, position) + 1, "code": line[:240]}


async def guarddog(path: Path, ecosystem: str) -> tuple[str, list[Signal]]:
    """GuardDog en complément des règles maison, s'il est installé. Rend (état, signaux)."""
    binary = shutil.which("guarddog")
    if binary is None:
        return "unavailable", []
    try:
        process = await asyncio.create_subprocess_exec(
            binary, ecosystem, "scan", str(path), "--output-format", "json",
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL,
        )
        output, _ = await asyncio.wait_for(process.communicate(), GUARDDOG_TIMEOUT)
        results = json.loads(output).get("results") or {}
    except (OSError, ValueError, AttributeError, asyncio.TimeoutError) as exc:
        logger.warning("GuardDog en échec (%s)", type(exc).__name__)
        return "error", []
    rules = sorted(rule for rule, hits in results.items() if hits)
    if not rules:
        return "clean", []
    return "alert", [signal("guarddog_alert", "GuardDog signale : " + ", ".join(rules) + ".", rules=rules)]
