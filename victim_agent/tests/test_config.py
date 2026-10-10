import pytest
from victim_agent.config import Settings
import victim_agent.config as config


def test_blank_template_does_not_override_private_tokens(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "ROOT", tmp_path)
    for key in ("SUPABASE_URL", "DATABASE_URL", "SUPABASE_SERVICE_ROLE_KEY", "service_role_key", "VICTIM_GATEWAY_TOKEN", "CONFINEMENT_TOKEN", "VICTIM_RECEIVER_URL", "ALEX_API_URL"):
        monkeypatch.delenv(key, raising=False)
    (tmp_path / ".env").write_text("DATABASE_URL=https://test.supabase.co/rest/v1/\nservice_role_key=test-key\nVICTIM_GATEWAY_TOKEN=\nCONFINEMENT_TOKEN=\n")
    (tmp_path / ".env.victim").write_text("VICTIM_GATEWAY_TOKEN=" + "a" * 32 + "\nCONFINEMENT_TOKEN=" + "b" * 32 + "\n")
    settings = Settings.from_env()
    assert settings.supabase_url == "https://test.supabase.co"
    assert settings.gateway_token == "a" * 32
    monkeypatch.setenv("VICTIM_RECEIVER_URL", "https://example.com/collect")
    with pytest.raises(ValueError):
        Settings.from_env()
