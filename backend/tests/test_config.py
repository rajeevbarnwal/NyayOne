from app.core.config import Settings, has_secret, settings


def test_settings_defaults_load() -> None:
    assert settings.app_name == "LegalSaathi"
    assert settings.app_version
    # Frontend dev origin must point at the LegalSaathi dev port (1030), not the old default.
    assert any("1030" in origin for origin in settings.cors_origins)
    assert not any("5173" in origin for origin in settings.cors_origins)


def test_config_ready_placeholders_present_and_unset() -> None:
    fresh = Settings()
    # These are declared for later wiring but must be unset in the foundation stage.
    assert fresh.database_url is None
    assert fresh.valkey_url is None
    assert fresh.storage_endpoint_url is None
    assert fresh.llm_gateway_url is None


def test_has_secret_helper() -> None:
    assert has_secret(None) is False
