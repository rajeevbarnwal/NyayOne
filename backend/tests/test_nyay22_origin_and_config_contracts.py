"""Fail-closed NYAY-22 origin and provider-configuration contracts."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.api.v1 import auth_mentor
from app.core.config import ConfigurationError, Settings


@pytest.mark.parametrize(
    "origin,configured,environment,expected",
    (
        ("http://[::1]:1130", ["http://[::1]:1130"], "testing", True),
        ("http://[::1]:1131", ["http://[::1]:1130"], "testing", False),
        ("http://localhost:1130", ["http://localhost:1130"], "testing", False),
        ("http://127.0.0.1:1130", ["http://127.0.0.1:1130"], "production", False),
        ("https://mentor.example", ["https://mentor.example"], "production", True),
        ("https://mentor.example?", ["https://mentor.example"], "production", False),
        ("https://mentor.example#", ["https://mentor.example"], "production", False),
        ("https://mentor.example?#", ["https://mentor.example"], "production", False),
    ),
)
def test_mentor_origin_policy_is_exact_and_ipv6_canonical(
    monkeypatch: pytest.MonkeyPatch,
    origin: str,
    configured: list[str],
    environment: str,
    expected: bool,
) -> None:
    monkeypatch.setattr(
        auth_mentor,
        "settings",
        SimpleNamespace(cors_origins=configured, app_env=environment),
    )
    assert auth_mentor._mentor_origin_is_trusted(origin) is expected


def _nonlocal_settings_with_cors(cors_origins, *, app_env: str = "production") -> Settings:
    return Settings(
        _env_file=None,
        app_env=app_env,
        cors_origins=cors_origins,
        database_url="postgresql://nyayone:production@db.example.test/nyayone",
        otp_delivery_enabled=True,
        otp_provider="http",
        otp_provider_url="https://otp-provider.example.test/send",
        otp_provider_token="nyay22-config-only-token",
        otp_provider_supports_idempotency=True,
        internship_report_scanner_provider="clamav",
        calendar_public_base_url="https://calendar.example.test",
        mentor_terminal_retention_seconds=2_592_000,
        mentor_audit_link_retention_seconds=2_592_000,
        mentor_retention_mode="bounded_crypto_erasure",
    )


@pytest.mark.parametrize("app_env", ("production", "prod", "staging", "stage"))
@pytest.mark.parametrize(
    "origins",
    (
        ["*"],
        [],
        [""],
        None,
        ["app.example.test"],
        ["http://app.example.test"],
        ["https://app.example.test/"],
        ["https://app.example.test/path"],
        ["https://user@app.example.test"],
        ["https://*.example.test"],
    ),
)
def test_production_cors_origins_fail_closed_on_wildcard_empty_and_noncanonical(
    origins, app_env: str,
) -> None:
    with pytest.raises((ConfigurationError, ValueError)) as refused:
        _nonlocal_settings_with_cors(origins, app_env=app_env)
    assert "cors_origins" in str(refused.value)


def test_production_cors_origins_accept_exact_canonical_https_origins() -> None:
    for app_env in ("production", "prod", "staging", "stage"):
        configured = _nonlocal_settings_with_cors(
            ["https://app.example.test", "https://admin.example.test:8443"],
            app_env=app_env,
        )
        assert configured.cors_origins == [
            "https://app.example.test",
            "https://admin.example.test:8443",
        ]


@pytest.mark.parametrize(
    "public_key",
    (
        "not-base64",
        "YWJjZA==",  # canonical Base64, but not a 32-byte Ed25519 key
        "oJql9HpnWYAv+VX43C0qFKXJnSO+l/hkEn/5ODRVpPA=trailing",
    ),
)
def test_mentor_provider_public_key_shape_fails_closed_without_echo(
    public_key: str,
) -> None:
    with pytest.raises(ConfigurationError) as refused:
        Settings(
            _env_file=None,
            mentor_identity_provider_public_key_b64=public_key,
        )
    diagnostic = str(refused.value)
    assert "mentor identity provider public key" in diagnostic
    assert public_key not in diagnostic


def test_mentor_provider_accepts_exact_ed25519_public_key_shape() -> None:
    configured = Settings(
        _env_file=None,
        mentor_identity_provider_public_key_b64=(
            "F8t5+ytBIPKx7GXkGY1uCLKOgT/rAeSkAIObheGAgM4="
        ),
    )
    assert configured.mentor_identity_provider_algorithm == "EdDSA"


@pytest.mark.parametrize(
    ("endpoint", "hosts"),
    (
        ("http://idp.example.test/mentor/start", ["idp.example.test"]),
        ("https://127.0.0.1/mentor/start", ["127.0.0.1"]),
        ("https://localhost/mentor/start", ["localhost"]),
        ("https://user@idp.example.test/mentor/start", ["idp.example.test"]),
        ("https://idp.example.test/", ["idp.example.test"]),
        ("https://idp.example.test/mentor/start?q=1", ["idp.example.test"]),
        ("https://idp.example.test/mentor/start", ["*.example.test"]),
        ("https://idp.example.test/mentor/start", ["other.example.test"]),
        ("https://idp.example.test/mentor/start", []),
        (None, ["idp.example.test"]),
    ),
)
def test_optional_provider_relay_configuration_is_all_or_nothing_and_canonical(
    endpoint, hosts
) -> None:
    with pytest.raises(ConfigurationError) as refused:
        Settings(
            _env_file=None,
            app_env="production",
            database_url="postgresql://nyayone:production@db.example.test/nyayone",
            mentor_identity_provider_public_key_b64=(
                "F8t5+ytBIPKx7GXkGY1uCLKOgT/rAeSkAIObheGAgM4="
            ),
            mentor_identity_provider_start_url=endpoint,
            mentor_identity_provider_allowed_hosts=hosts,
        )
    diagnostic = str(refused.value)
    assert "mentor identity provider" in diagnostic
    if endpoint:
        assert endpoint not in diagnostic


def test_provider_relay_may_be_disabled_but_valid_configuration_is_accepted() -> None:
    disabled = Settings(_env_file=None)
    assert disabled.mentor_identity_provider_start_url is None
    configured = Settings(
        _env_file=None,
        mentor_identity_provider_start_url="https://idp.example.test/mentor/start",
        mentor_identity_provider_allowed_hosts=["idp.example.test"],
    )
    assert configured.mentor_identity_provider_allowed_hosts == ["idp.example.test"]


def test_nonlocal_default_provider_key_is_inert_when_disabled_and_rejected_when_enabled() -> None:
    common = {
        "_env_file": None,
        "app_env": "staging",
        "cors_origins": ["https://app.example.test"],
        "database_url": "postgresql://nyayone:production@db.example.test/nyayone",
        "otp_delivery_enabled": True,
        "otp_provider": "http",
        "otp_provider_url": "https://otp-provider.example.test/send",
        "otp_provider_token": "nyay22-config-only-token",
        "otp_provider_supports_idempotency": True,
        "internship_report_scanner_provider": "clamav",
        "calendar_public_base_url": "https://calendar.example.test",
        "mentor_terminal_retention_seconds": 2_592_000,
        "mentor_audit_link_retention_seconds": 2_592_000,
        "mentor_retention_mode": "bounded_crypto_erasure",
    }
    disabled = Settings(**common)
    assert disabled.mentor_identity_provider_start_url is None

    with pytest.raises(ConfigurationError, match="key must be deployment-bound"):
        Settings(
            **common,
            mentor_identity_provider_start_url=(
                "https://idp.example.test/mentor/start"
            ),
            mentor_identity_provider_allowed_hosts=["idp.example.test"],
        )


def test_production_relay_requires_explicit_retention_policy() -> None:
    common = {
        "_env_file": None,
        "app_env": "production",
        "cors_origins": ["https://app.example.test"],
        "database_url": "postgresql://nyayone:production@db.example.test/nyayone",
        "mentor_identity_provider_public_key_b64": (
            "F8t5+ytBIPKx7GXkGY1uCLKOgT/rAeSkAIObheGAgM4="
        ),
        "mentor_identity_provider_start_url": (
            "https://idp.example.test/mentor/start"
        ),
        "mentor_identity_provider_allowed_hosts": ["idp.example.test"],
        "otp_delivery_enabled": True,
        "otp_provider": "http",
        "otp_provider_url": "https://otp-provider.example.test/send",
        "otp_provider_token": "nyay22-config-only-token",
        "otp_provider_supports_idempotency": True,
        "internship_report_scanner_provider": "clamav",
        "calendar_public_base_url": "https://calendar.example.test",
    }
    with pytest.raises(ConfigurationError, match="retention policy"):
        Settings(**common)
    configured = Settings(
        **common,
        mentor_terminal_retention_seconds=2_592_000,
        mentor_audit_link_retention_seconds=2_592_000,
        mentor_retention_mode="bounded_crypto_erasure",
    )
    assert configured.mentor_terminal_retention_seconds == 2_592_000


@pytest.mark.parametrize(
    "missing",
    (
        "mentor_terminal_retention_seconds",
        "mentor_audit_link_retention_seconds",
        "mentor_retention_mode",
    ),
)
def test_nonlocal_retention_policy_is_explicit_even_when_relay_is_disabled(
    missing: str,
) -> None:
    """No external provider is needed for retained bootstrap authority."""

    common = {
        "_env_file": None,
        "app_env": "staging",
        "cors_origins": ["https://app.example.test"],
        "database_url": "postgresql://nyayone:production@db.example.test/nyayone",
        "otp_delivery_enabled": True,
        "otp_provider": "http",
        "otp_provider_url": "https://otp-provider.example.test/send",
        "otp_provider_token": "nyay22-config-only-token",
        "otp_provider_supports_idempotency": True,
        "internship_report_scanner_provider": "clamav",
        "calendar_public_base_url": "https://calendar.example.test",
        "mentor_terminal_retention_seconds": 2_592_000,
        "mentor_audit_link_retention_seconds": 2_592_000,
        "mentor_retention_mode": "bounded_crypto_erasure",
    }
    common.pop(missing)
    with pytest.raises(ConfigurationError, match="deployment-explicit"):
        Settings(**common)


def test_nonlocal_explicit_retention_policy_is_valid_with_relay_disabled() -> None:
    configured = Settings(
        _env_file=None,
        app_env="staging",
        cors_origins=["https://app.example.test"],
        database_url="postgresql://nyayone:production@db.example.test/nyayone",
        otp_delivery_enabled=True,
        otp_provider="http",
        otp_provider_url="https://otp-provider.example.test/send",
        otp_provider_token="nyay22-config-only-token",
        otp_provider_supports_idempotency=True,
        internship_report_scanner_provider="clamav",
        calendar_public_base_url="https://calendar.example.test",
        mentor_terminal_retention_seconds=2_592_000,
        mentor_audit_link_retention_seconds=2_592_000,
        mentor_retention_mode="bounded_crypto_erasure",
    )
    assert configured.mentor_identity_provider_start_url is None
    assert configured.mentor_retention_mode == "bounded_crypto_erasure"


@pytest.mark.parametrize("value", (0, -1, True, 257, "0", "01"))
def test_session_generation_ceiling_is_strict_and_bounded(value) -> None:
    with pytest.raises(ValueError) as refused:
        Settings(_env_file=None, mentor_session_max_generation=value)
    assert "mentor_session_max_generation" in str(refused.value)


def test_rate_window_ceiling_keeps_exact_retry_after_inside_sealed_contract() -> None:
    accepted = Settings(_env_file=None, mentor_rate_window_seconds=450)
    assert accepted.mentor_rate_window_seconds * 2 == 900
    with pytest.raises(ValueError) as refused:
        Settings(_env_file=None, mentor_rate_window_seconds=451)
    assert "mentor_rate_window_seconds" in str(refused.value)
