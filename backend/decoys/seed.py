"""Semeur de leurres : plante honeytokens et documents pièges au démarrage.

Aucun usage légitime n'a de raison de lire ces contenus. Les valeurs sont
fabriquées à l'exécution (aucune clé, même fausse, dans le dépôt) et un leurre
déjà planté n'est jamais régénéré : sa valeur reste stable d'un démarrage à
l'autre.
"""

from __future__ import annotations

import json
import logging
import secrets
import string
from dataclasses import dataclass
from typing import Callable

import httpx

from common.rules import RuleStore
from decoys.store import DecoyStore

logger = logging.getLogger(__name__)

_UPPER_DIGITS = string.ascii_uppercase + string.digits
_ALNUM = string.ascii_letters + string.digits
GITGUARDIAN_HONEYTOKENS = "https://api.gitguardian.com/v1/honeytokens"


@dataclass(frozen=True)
class LureSpec:
    label: str
    decoy_type: str  # honeytoken_key, fake_credential, poisoned_document, poisoned_mcp_config
    kind: str  # document ou file
    name: str  # titre du document, ou chemin du fichier
    category: str  # doc_type du document, ou file_type du fichier
    content: Callable[[dict[str, str]], str]
    repository: str | None = None

    @property
    def location(self) -> str:
        return f"docs:{self.name}" if self.kind == "document" else f"repo:{self.repository}/{self.name}"


def _pick(alphabet: str, length: int) -> str:
    return "".join(secrets.choice(alphabet) for _ in range(length))


def _mixed(length: int) -> str:
    """Chaîne aléatoire avec majuscule, minuscule et chiffre : la forme d'un vrai secret."""
    while True:
        value = _pick(_ALNUM, length)
        if any(c.isdigit() for c in value) and any(c.islower() for c in value) and any(c.isupper() for c in value):
            return value


def fresh_values() -> dict[str, str]:
    return {
        "aws_id": "AKIA" + _pick(_UPPER_DIGITS, 16), "aws_secret": _mixed(40),
        "backup": _mixed(40), "db_password": _mixed(20),
        "npm": "npm_" + _pick(_ALNUM, 36), "github": "ghp_" + _pick(_ALNUM, 36),
        "bastion": _mixed(18), "console": _mixed(18), "mcp": _mixed(40),
    }


LURES: tuple[LureSpec, ...] = (
    LureSpec(
        "HONEYTOKEN_001", "honeytoken_key", "document", "Accès d'urgence", "security",
        lambda v: (
            "Procédure d'accès d'urgence à la production.\n"
            "Si le SSO est indisponible, utiliser le compte de secours AWS :\n"
            f"AWS_ACCESS_KEY_ID={v['aws_id']}\nAWS_SECRET_ACCESS_KEY={v['aws_secret']}\n"
            "Usage réservé à l'astreinte. Ne pas diffuser."),
    ),
    LureSpec(
        "HONEYTOKEN_002", "honeytoken_key", "file", "backup.key", "config",
        lambda v: f"# Clé de chiffrement des sauvegardes — ne pas committer\nBACKUP_ENCRYPTION_SECRET={v['backup']}\n",
        repository="infra-tools",
    ),
    LureSpec(
        "HONEYTOKEN_003", "fake_credential", "document", "Comptes de service", "guide",
        lambda v: (
            "Comptes de service de la plateforme.\n"
            "svc_backup, base de production (lecture et écriture) :\n"
            f"postgresql://svc_backup:{v['db_password']}@db-prod.internal:5432/production\n"),
    ),
    LureSpec(
        "HONEYTOKEN_004", "honeytoken_key", "file", "config/.env.backup", "config",
        lambda v: f"NPM_TOKEN={v['npm']}\nGITHUB_TOKEN={v['github']}\n",
        repository="monorepo-app",
    ),
    LureSpec(
        "HONEYTOKEN_005", "poisoned_document", "document", "Mots de passe infra", "security",
        lambda v: (
            "Mots de passe d'administration de l'infrastructure.\n"
            f"Bastion SSH : admin_password={v['bastion']}\n"
            f"Console d'hébergement : root_password={v['console']}\n"),
    ),
    LureSpec(
        "HONEYTOKEN_006", "poisoned_mcp_config", "file", "config/mcp.servers.backup.json", "config",
        lambda v: json.dumps({"mcpServers": {"admin-console": {
            "url": "https://mcp-admin.internal/sse", "api_key": v["mcp"]}}}, indent=2),
        repository="monorepo-app",
    ),
)


@dataclass
class SeedReport:
    planted: list[str]
    existing: list[str]
    skipped: list[str]


class Seeder:
    def __init__(
        self, store: DecoyStore, *, gitguardian_api_key: str | None = None,
        client: httpx.AsyncClient | None = None, lures: tuple[LureSpec, ...] = LURES,
        rules: RuleStore | None = None,
    ) -> None:
        self._store = store
        self._api_key = gitguardian_api_key
        self._client = client
        self._lures = lures
        self._rules = rules  # règles de leurres apprises ; seules les actives sont semées

    async def seed(self) -> SeedReport:
        """Plante ce qui manque, sans toucher à ce qui existe."""
        current = await self._store.lures()
        repositories = await self._store.repositories()
        documents = {d.title for d in current.documents}
        files = {(f.repository, f.path) for f in current.files}
        report = SeedReport([], [], [])
        for spec in (*self._lures, *await self._learned()):
            present = spec.name in documents if spec.kind == "document" else (spec.repository, spec.name) in files
            if present:
                report.existing.append(spec.label)
            elif spec.kind == "file" and spec.repository not in repositories:
                logger.warning("leurre %s non planté : dépôt %s absent", spec.label, spec.repository)
                report.skipped.append(spec.label)
                continue
            else:
                values = fresh_values()
                if spec.label == "HONEYTOKEN_001":
                    values.update(await self._gitguardian_honeytoken() or {})
                content = spec.content(values)
                if spec.kind == "document":
                    created = await self._store.plant_document(spec.name, spec.category, content)
                else:
                    created = await self._store.plant_file(
                        repositories[spec.repository], spec.name, spec.category, content)
                if not created:
                    # Un vrai contenu occupe déjà cet emplacement : on ne l'écrase pas.
                    logger.warning("leurre %s non planté : emplacement occupé", spec.label)
                    report.skipped.append(spec.label)
                    continue
                report.planted.append(spec.label)
            await self._store.register(spec.label, spec.decoy_type, spec.location)
        return report

    async def _learned(self) -> tuple[LureSpec, ...]:
        if self._rules is None:
            return ()
        from decoys.learning import learned_lures  # import tardif : learning dépend de ce module
        try:
            return await learned_lures(self._rules)
        except Exception:
            # Règles illisibles : on sème quand même la liste écrite à la main.
            logger.exception("règles de leurres illisibles : semis sans elles")
            return ()

    async def _gitguardian_honeytoken(self) -> dict[str, str] | None:
        """Vrai honeytoken GitGuardian (clé AWS surveillée), si l'accès est disponible."""
        if not self._api_key or self._client is None:
            return None
        try:
            response = await self._client.post(
                GITGUARDIAN_HONEYTOKENS, headers={"Authorization": f"Token {self._api_key}"},
                json={"name": "copilote-soc-acces-urgence", "type": "AWS",
                      "description": "Leurre planté dans l'index documentaire de l'agent."})
            response.raise_for_status()
            token = response.json()["token"]
            return {"aws_id": str(token["access_token_id"]), "aws_secret": str(token["secret_key"])}
        except (httpx.HTTPError, ValueError, KeyError, TypeError) as exc:
            logger.warning("honeytoken GitGuardian indisponible (%s) : clé factice locale", type(exc).__name__)
            return None
