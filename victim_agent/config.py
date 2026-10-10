from dataclasses import dataclass
from pathlib import Path
import os
from urllib.parse import urlsplit

from dotenv import dotenv_values

ROOT = Path(__file__).resolve().parents[1]
NAMESPACE = "elyott_v0"
REPOSITORY = "trace-elyott-v0"
FAKE_SECRETS = ("FAKE_NX_KEY_demo_0000", "FAKE_NPM_TOKEN_demo_0000")
@dataclass(frozen=True)
class Settings:
    supabase_url: str
    supabase_key: str
    openai_key: str
    model: str
    gateway_token: str
    confinement_token: str
    rag_key: str = ""
    rag_model: str = "gpt-6-luna"
    alex_url: str = "http://127.0.0.1:8000"
    alex_token: str = ""
    receiver_url: str = "http://127.0.0.1:8001/demo-receiver"
    receiver_db: str = str(ROOT / ".runtime" / "victim-receiver.sqlite")
    max_rounds: int = 6
    max_tools: int = 10
    run_timeout: float = 90
    model_timeout: float = 25

    @classmethod
    def from_env(cls):
        # Load before reading any module-level database configuration. Existing
        # shell variables take precedence; the root .env remains compatible.
        # Blank placeholders in .env.example must not hide generated tokens.
        values = {**{k: v for k, v in dotenv_values(ROOT / ".env.victim").items() if v},
                  **{k: v for k, v in dotenv_values(ROOT / ".env").items() if v},
                  **{k: v for k, v in os.environ.items() if v}}
        raw = values.get("SUPABASE_URL") or values.get("DATABASE_URL", "")
        parsed = urlsplit(raw)
        if parsed.scheme != "https" or not (parsed.hostname or "").endswith(".supabase.co") or parsed.username:
            raise ValueError("SUPABASE_URL doit désigner le projet Supabase en HTTPS.")
        key = values.get("SUPABASE_SERVICE_ROLE_KEY") or values.get("service_role_key", "")
        token = values.get("VICTIM_GATEWAY_TOKEN", "")
        confinement = values.get("CONFINEMENT_TOKEN", "")
        if not key or len(token) < 24:
            raise ValueError("Clé Supabase et jeton privé de passerelle requis (24 caractères minimum).")
        alex_url = values.get("ALEX_API_URL", "http://127.0.0.1:8000").rstrip("/")
        receiver = values.get("VICTIM_RECEIVER_URL", "http://127.0.0.1:8001/demo-receiver")
        for address in (alex_url, receiver):
            url = urlsplit(address)
            if url.scheme != "http" or url.hostname not in ("127.0.0.1", "localhost") or url.username or url.query or url.fragment:
                raise ValueError("La V0 utilise exclusivement des serveurs HTTP locaux.")
        return cls(
            supabase_url=f"{parsed.scheme}://{parsed.netloc}", supabase_key=key,
            # Preserve shared settings used by the existing defense backend;
            # this RAG service gets its own key and model fields.
            openai_key=values.get("OPENAI_API_KEY", ""),
            model=values.get("AGENT_MODEL") or values.get("OPENAI_MODEL") or "gpt-4.1-2025-04-14",
            gateway_token=token, confinement_token=confinement,
            rag_key=values.get("OPENAI_API_KEY_RAG") or values.get("OPENAI_API_KEY", ""),
            rag_model=values.get("RAG_MODEL") or "gpt-6-luna",
            alex_url=alex_url, alex_token=values.get("PASSERELLE_TOKEN", ""),
            receiver_url=receiver, receiver_db=values.get("VICTIM_RECEIVER_DB", cls.receiver_db),
        )
