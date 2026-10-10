import hashlib
import re
from .config import FAKE_SECRETS


class Masker:
    """Stable placeholders, including raw fake values without an assignment."""
    def __init__(self):
        self.values = {value: f"SECRET_{i:03d}" for i, value in enumerate(FAKE_SECRETS, 1)}
        self.assignment = re.compile(r"(?i)((?:api[_-]?key|_authToken|password|secret|token)\s*[=:]\s*)([^\s,;]+)")

    def placeholder(self, value):
        if value not in self.values:
            # Stable across processes; no need to persist a secret dictionary.
            self.values[value] = "SECRET_" + hashlib.sha256(value.encode()).hexdigest()[:12]
        return self.values[value]

    def text(self, value: str):
        for secret, label in sorted(self.values.items(), key=lambda pair: -len(pair[0])):
            value = value.replace(secret, label)
        value = self.assignment.sub(lambda m: m.group(1) + (m.group(2) if m.group(2).startswith("SECRET_") else self.placeholder(m.group(2))), value)
        return re.sub(r"sk-[A-Za-z0-9_-]{12,}|AKIA[A-Z0-9]{16}|gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,}", lambda m: self.placeholder(m.group()), value)

    def clean(self, value):
        if isinstance(value, str):
            return self.text(value)
        if isinstance(value, dict):
            return {self.text(str(k)): self.clean(v) for k, v in value.items()}
        if isinstance(value, list):
            return [self.clean(v) for v in value]
        return value
