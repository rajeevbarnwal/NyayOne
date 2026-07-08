from app.core.config import Settings, has_secret, settings


def test_settings_defaults_load() -> None:
    assert settings.app_name == "LegalSaathi"
    assert settings.app_version
    # Frontend dev origin must point at the LegalSaathi dev port (1030), not the old default.
    assert any("1030" in origin for origin in settings.cors_origins)
    assert not any("5173" in origin for origin in settings.cors_origins)


def test_database_url_defaults_to_local_postgres_on_1032() -> None:
    fresh = Settings()
    # DB is now provisioned: default points at the local Postgres (host port 1032).
    assert fresh.database_url.startswith("postgresql+psycopg://")
    assert ":1032/" in fresh.database_url


def test_config_ready_placeholders_still_unset() -> None:
    fresh = Settings()
    # These remain declared-but-unset until their own tickets wire them.
    assert fresh.valkey_url is None
    assert fresh.storage_endpoint_url is None
    assert fresh.llm_gateway_url is None
    assert fresh.log_file_path is None


def test_has_secret_helper() -> None:
    assert has_secret(None) is False
