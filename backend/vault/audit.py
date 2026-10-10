"""Contrôle des prompts envoyés aux LLM défenseurs. Objectif affiché : 0 secret en clair."""

from __future__ import annotations

from dataclasses import dataclass, field

from vault.scanner import Scanner


@dataclass(frozen=True)
class PromptCheck:
    agent: str
    secrets: int
    pii: int
    kinds: tuple[str, ...]  # préfixes détectés, jamais les valeurs

    @property
    def clean(self) -> bool:
        return self.secrets == 0 and self.pii == 0


@dataclass
class PromptAudit:
    """À appeler sur chaque prompt juste avant l'envoi au LLM."""

    scanner: Scanner
    prompts_checked: int = 0
    secrets_seen: int = 0
    pii_seen: int = 0
    history: list[PromptCheck] = field(default_factory=list)

    def check(self, prompt: str, *, agent: str) -> PromptCheck:
        secrets = self.scanner.scan_secrets(prompt)
        pii = self.scanner.scan_pii(prompt)
        result = PromptCheck(
            agent=agent,
            secrets=len(secrets),
            pii=len(pii),
            kinds=tuple(sorted({d.prefix for d in secrets + pii})),
        )
        self.prompts_checked += 1
        self.secrets_seen += result.secrets
        self.pii_seen += result.pii
        self.history.append(result)
        return result
