import pytest
from pydantic import ValidationError

from app.core.config import Settings, has_secret


def test_settings_defaults_load(monkeypatch: pytest.MonkeyPatch) -> None:
    # This test proves class defaults, so it must not accidentally assert
    # against a deployment's intentional CORS_ORIGINS override (for example
    # the browser URL used by CI).
    monkeypatch.delenv("CORS_ORIGINS", raising=False)
    fresh = Settings(_env_file=None)
    assert fresh.app_name == "LegalSaathi"
    assert fresh.app_version
    # Frontend dev origin must point at the LegalSaathi dev port (1030), not the old default.
    assert any("1030" in origin for origin in fresh.cors_origins)
    assert not any("5173" in origin for origin in fresh.cors_origins)


def test_database_url_defaults_to_local_postgres_on_1032(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("DATABASE_URL", raising=False)
    fresh = Settings(_env_file=None)
    # DB is now provisioned: default points at the local Postgres (host port 1032).
    assert fresh.database_url.startswith("postgresql+psycopg://")
    assert ":1032/" in fresh.database_url


def test_config_ready_placeholders_still_unset(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    for variable in (
        "VALKEY_URL",
        "STORAGE_ENDPOINT_URL",
        "LLM_GATEWAY_URL",
        "LOG_FILE_PATH",
    ):
        monkeypatch.delenv(variable, raising=False)
    fresh = Settings(_env_file=None)
    # These remain declared-but-unset until their own tickets wire them.
    assert fresh.valkey_url is None
    assert fresh.storage_endpoint_url is None
    assert fresh.llm_gateway_url is None
    assert fresh.log_file_path is None


def test_has_secret_helper() -> None:
    assert has_secret(None) is False


def test_credential_verification_base_requires_https_verify_path() -> None:
    assert (
        Settings(
            credential_public_base_url="https://credentials.example/verify/"
        ).credential_public_base_url
        == "https://credentials.example/verify"
    )
    with pytest.raises(ValidationError):
        Settings(credential_public_base_url="http://credentials.example/verify")
    with pytest.raises(ValidationError):
        Settings(credential_public_base_url="https://credentials.example")
