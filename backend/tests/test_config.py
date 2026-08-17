import pytest
from pydantic import ValidationError

from app.core.config import ConfigurationError, Settings, has_secret


def test_settings_defaults_load(monkeypatch: pytest.MonkeyPatch) -> None:
    # This test proves class defaults, so it must not accidentally assert
    # against a deployment's intentional CORS_ORIGINS override (for example
    # the browser URL used by CI).
    monkeypatch.delenv("CORS_ORIGINS", raising=False)
    fresh = Settings(_env_file=None)
    assert fresh.app_name == "NyayOne"
    assert fresh.app_version
    # Frontend dev origin must use NyayOne's isolated host port.
    assert any("1130" in origin for origin in fresh.cors_origins)
    assert not any("5173" in origin for origin in fresh.cors_origins)


def test_database_url_defaults_to_isolated_local_postgres(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("DATABASE_URL", raising=False)
    fresh = Settings(_env_file=None)
    # Default points at NyayOne's local Postgres identity and host port.
    assert fresh.database_url.startswith("postgresql+psycopg://")
    assert ":1132/nyayone" in fresh.database_url
    assert fresh.github_repository == "rajeevbarnwal/NyayOne"
    assert fresh.auth_session_cookie_name == "nyayone_session"
    assert fresh.jira_project_key == "NYAY"
    assert fresh.jira_board_id == 68


@pytest.mark.parametrize(
    ("field", "invalid_value"),
    (
        ("app_name", "LegalSaathi"),
        ("app_name", "Another Product"),
        (
            "database_url",
            "postgresql+psycopg://legalsaathi:safe-placeholder@localhost:1132/nyayone",
        ),
        (
            "database_url",
            "postgresql+psycopg://nyayone:safe-placeholder@localhost:1132/legalsaathi",
        ),
        (
            "test_database_url",
            "postgresql+psycopg://nyayone:safe-placeholder@localhost:1132/legalsaathi_qa",
        ),
        (
            "database_url",
            "postgresql+psycopg://%6cegalsaathi:safe-placeholder@localhost:1132/nyayone",
        ),
        ("auth_session_cookie_name", "legalsaathi_session"),
        ("auth_session_cookie_name", "another_session"),
        ("github_repository", "rajeevbarnwal/legalsaathi"),
        ("github_repository", "another-owner/NyayOne"),
        ("github_repo_url", "https://github.com/rajeevbarnwal/legalsaathi"),
        ("github_repo_url", "http://github.com/rajeevbarnwal/NyayOne"),
        ("github_repo_url", "https://evil.example/rajeevbarnwal/NyayOne"),
        ("github_repo_url", "https://github.com:444/rajeevbarnwal/NyayOne"),
        ("github_repo_url", "https://github.com:bad/rajeevbarnwal/NyayOne"),
        ("jira_project_key", "SAATHI"),
        ("jira_project_key", "OTHER"),
        ("jira_board_id", 2),
        ("jira_board_id", 999),
        ("jira_base_url", "https://evil.example"),
        ("jira_base_url", "https://legalsaathi.atlassian.net:444"),
        ("jira_base_url", "https://legalsaathi.atlassian.net:bad"),
        ("credential_storage_root", "/tmp/legalsaathi_credential_storage"),
        (
            "internship_report_storage_root",
            "/tmp/legalsaathi_internship_report_storage",
        ),
    ),
)
def test_settings_reject_each_invalid_runtime_identity(
    field: str,
    invalid_value: object,
) -> None:
    with pytest.raises(ConfigurationError, match="refusing to start"):
        Settings(_env_file=None, **{field: invalid_value})


def test_legacy_runtime_rejection_does_not_echo_database_credentials() -> None:
    marker = "do-not-echo-this-value"
    with pytest.raises(ConfigurationError) as excinfo:
        Settings(
            _env_file=None,
            database_url=(
                "postgresql+psycopg://legalsaathi:"
                f"{marker}@localhost:1132/nyayone"
            ),
        )
    assert marker not in str(excinfo.value)


def test_integration_origin_rejection_does_not_echo_userinfo() -> None:
    marker = "do-not-echo-integration-secret"
    with pytest.raises(ConfigurationError) as excinfo:
        Settings(
            _env_file=None,
            jira_base_url=(
                "https://operator:"
                f"{marker}@legalsaathi.atlassian.net:444"
            ),
        )
    assert marker not in str(excinfo.value)


def test_development_database_credentials_fail_closed_outside_local() -> None:
    marker = "nyayone_dev_only"
    with pytest.raises(ConfigurationError) as excinfo:
        Settings(
            _env_file=None,
            app_env="staging",
            database_url=(
                "postgresql+psycopg://nyayone:"
                f"{marker}@localhost:1132/nyayone"
            ),
            calendar_public_base_url="https://calendar.example",
            internship_report_scanner_provider="clamav",
            registration_secret="staging-registration-secret-not-default",
            registration_lookup_secret="staging-registration-lookup-not-default",
        )
    assert marker not in str(excinfo.value)


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
