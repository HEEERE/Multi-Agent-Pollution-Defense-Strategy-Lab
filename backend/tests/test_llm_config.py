from app.core.config import Settings


def test_default_mimo_model_matches_provider_model_id(monkeypatch):
    monkeypatch.delenv("MIMO_MODEL", raising=False)

    settings = Settings(_env_file=None)

    assert settings.mimo_model == "mimo-v2.5-pro"
