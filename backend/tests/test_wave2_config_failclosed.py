"""Fail-closed Wave 2 configuration gate (SAATHI-123 / SAATHI-127).

``Settings.validate_wave2_configuration`` must refuse to CONSTRUCT rather than
let the process boot into a state where it could only degrade silently: taking a
payment through an unconfigured gateway, minting a join credential no provider
will honour, expiring every hold instantly, or writing a reminder offset the
schema's CHECK constraint rejects.

Two things are asserted for EVERY misconfiguration:

1. it raises :class:`ConfigurationError` and the message NAMES the offending
   setting, so an operator can fix it;
2. the message does NOT contain the secret VALUE that was supplied — the
   privacy contract in the validator's docstring.

Every construction passes ``_env_file=None`` and the relevant environment
variables are cleared, so these tests never read (or reveal) a deployment's
``.env``.
"""
from __future__ import annotations

import pytest
from pydantic import SecretStr, ValidationError as PydanticValidationError

from app.core.config import (
    PAYMENT_PROVIDER_CHOICES,
    REMINDER_OFFSET_CHOICES,
    VIDEO_PROVIDER_CHOICES,
    ConfigurationError,
    Settings,
    settings as live_settings,
)
from app.models.wave2 import REMINDER_OFFSETS
from app.services.providers.payment_provider import (
    DeterministicPaymentAdapter,
    build_payment_provider,
)
from app.services.providers.video_provider import (
    DeterministicVideoAdapter,
    build_video_provider,
)

#: Realistic, obviously-secret values. Nothing here is a real credential; the
#: point is that NONE of them may ever appear in an error message.
KEY_ID = "rzp_live_QQ7hV2mNbXk91z"
KEY_SECRET = "Zt9k4WpLq2sVbN7xYd1RfE"
#: The scheme matters. ``LiveKitCommunityAdapter._twirp`` POSTs to
#: ``{livekit_url}/twirp/livekit.RoomService/<Method>`` with httpx, so this fixture
#: MUST model a value the adapter can actually reach. It used to be
#: ``wss://livekit.legalsaathi.example``, which is exactly the mistake the gate now
#: refuses — see ``test_livekit_url_must_be_reachable_over_http``.
LIVEKIT_URL = "https://livekit.legalsaathi.example"
LIVEKIT_KEY = "APIabcLiveKeyValue987"
LIVEKIT_SECRET = "sTvUxYzabcdefGHIJKlmnopQRS"
SECRETS = (KEY_ID, KEY_SECRET, LIVEKIT_KEY, LIVEKIT_SECRET)

POSITIVE_INT_SETTINGS = (
    "booking_hold_minutes",
    "join_credential_ttl_seconds",
    "rate_limit_tutor_search_per_min",
    "rate_limit_booking_per_min",
    "rate_limit_review_per_hour",
    "refund_free_cancel_hours",
)

_WAVE2_ENV = (
    "PAYMENT_PROVIDER",
    "RAZORPAY_KEY_ID",
    "RAZORPAY_KEY_SECRET",
    "VIDEO_PROVIDER",
    "VIDEO_CALLS_ENABLED",
    "LIVEKIT_URL",
    "LIVEKIT_PUBLIC_URL",
    "LIVEKIT_API_KEY",
    "LIVEKIT_API_SECRET",
    "BOOKING_HOLD_MINUTES",
    "JOIN_CREDENTIAL_TTL_SECONDS",
    "RATE_LIMIT_TUTOR_SEARCH_PER_MIN",
    "RATE_LIMIT_BOOKING_PER_MIN",
    "RATE_LIMIT_REVIEW_PER_HOUR",
    "REFUND_FREE_CANCEL_HOURS",
    "REMINDER_OFFSETS",
)


@pytest.fixture(autouse=True)
def _hermetic_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Never let a deployment's environment decide what these tests prove."""
    for name in _WAVE2_ENV:
        monkeypatch.delenv(name, raising=False)


def _build(**overrides) -> Settings:
    return Settings(_env_file=None, **overrides)


def _refuses(*, names: tuple[str, ...], secrets: tuple[str, ...] = (), **overrides):
    """Assert the construction fails, names every setting, and leaks no secret."""
    with pytest.raises(ConfigurationError) as refused:
        _build(**overrides)
    message = str(refused.value)
    assert "refusing to start" in message
    for name in names:
        assert name in message, f"{name!r} is not named in: {message}"
    for secret in secrets:
        assert secret, "an empty 'secret' cannot be asserted absent"
        assert secret not in message
    return message


# --------------------------------------------------------------------------- #
# The valid / default configuration still constructs
# --------------------------------------------------------------------------- #


def test_default_wave2_configuration_constructs(monkeypatch: pytest.MonkeyPatch):
    fresh = _build()
    assert fresh.payment_provider == "deterministic"
    assert fresh.video_calls_enabled is False
    assert fresh.video_provider == "none"
    assert fresh.booking_hold_minutes == 10
    assert fresh.join_credential_ttl_seconds == 300
    assert fresh.rate_limit_tutor_search_per_min == 60
    assert fresh.rate_limit_booking_per_min == 10
    assert fresh.rate_limit_review_per_hour == 5
    assert fresh.refund_free_cancel_hours == 24
    assert fresh.reminder_offsets == ["7d", "1d", "3h"]
    # No Wave 2 credential is needed for the default deployment.
    assert fresh.razorpay_key_id is None and fresh.razorpay_key_secret is None
    assert fresh.livekit_url is None and fresh.livekit_public_url is None
    assert fresh.livekit_api_secret is None


def test_video_enablement_and_provider_are_independent_and_fail_closed():
    assert _build(video_calls_enabled=False, video_provider="none")
    message = _refuses(
        names=("video_provider", "video_calls_enabled"),
        video_calls_enabled=True,
        video_provider="none",
    )
    assert "deterministic or livekit" in message


def test_deterministic_video_is_forbidden_in_staging_and_production():
    for environment in ("staging", "production"):
        message = _refuses(
            names=("video_provider", "deterministic"),
            app_env=environment,
            video_calls_enabled=True,
            video_provider="deterministic",
        )
        assert "forbidden" in message


def test_enabled_livekit_requires_a_browser_facing_websocket_url():
    common = {
        "video_calls_enabled": True,
        "video_provider": "livekit",
        "livekit_url": LIVEKIT_URL,
        "livekit_api_key": SecretStr(LIVEKIT_KEY),
        "livekit_api_secret": SecretStr(LIVEKIT_SECRET),
    }
    _refuses(names=("livekit_public_url",), **common)
    assert _build(**common, livekit_public_url="ws://localhost:1039")
    assert _build(**common, livekit_public_url="wss://video.example.test")


def test_production_livekit_requires_wss_and_never_echoes_userinfo():
    common = {
        "app_env": "production",
        "video_calls_enabled": True,
        "video_provider": "livekit",
        "livekit_url": LIVEKIT_URL,
        "livekit_api_key": SecretStr(LIVEKIT_KEY),
        "livekit_api_secret": SecretStr(LIVEKIT_SECRET),
    }
    message = _refuses(
        names=("livekit_public_url", "wss://"),
        secrets=("browser-user", "browser-password"),
        livekit_public_url="ws://browser-user:browser-password@localhost:1039",
        **common,
    )
    assert "browser-user" not in message and "browser-password" not in message
    assert _build(**common, livekit_public_url="wss://video.example.test")


def test_the_choice_tables_match_the_schema_and_the_code():
    assert PAYMENT_PROVIDER_CHOICES == ("deterministic", "razorpay", "none")
    assert VIDEO_PROVIDER_CHOICES == ("deterministic", "livekit", "none")
    # An offset that Settings accepts must be one the CHECK constraint accepts.
    assert REMINDER_OFFSET_CHOICES == REMINDER_OFFSETS == ("7d", "1d", "3h")


def test_the_live_settings_singleton_passed_the_gate():
    """The imported process settings satisfy the gate (or import would have failed)."""
    assert live_settings.payment_provider.strip().lower() in PAYMENT_PROVIDER_CHOICES
    assert live_settings.video_provider.strip().lower() in VIDEO_PROVIDER_CHOICES
    for name in POSITIVE_INT_SETTINGS:
        assert getattr(live_settings, name) > 0
    assert live_settings.reminder_offsets
    assert set(live_settings.reminder_offsets) <= set(REMINDER_OFFSET_CHOICES)


def test_deterministic_providers_remain_selectable_without_credentials(
    monkeypatch: pytest.MonkeyPatch,
):
    fresh = _build(payment_provider="deterministic", video_provider="deterministic")
    assert fresh.razorpay_key_secret is None and fresh.livekit_api_secret is None

    monkeypatch.setattr(live_settings, "payment_provider", "deterministic")
    monkeypatch.setattr(live_settings, "video_provider", "deterministic")
    monkeypatch.setattr(live_settings, "razorpay_key_id", None, raising=False)
    monkeypatch.setattr(live_settings, "razorpay_key_secret", None, raising=False)
    monkeypatch.setattr(live_settings, "livekit_url", None, raising=False)
    monkeypatch.setattr(live_settings, "livekit_api_key", None, raising=False)
    monkeypatch.setattr(live_settings, "livekit_api_secret", None, raising=False)
    assert isinstance(build_payment_provider(), DeterministicPaymentAdapter)
    assert isinstance(build_video_provider(), DeterministicVideoAdapter)

    # 'none' is a legal, explicitly fail-closed selection: it CONSTRUCTS, and the
    # seams then return None so callers must raise PROVIDER_UNAVAILABLE.
    assert _build(payment_provider="none", video_provider="none")
    monkeypatch.setattr(live_settings, "payment_provider", "none")
    monkeypatch.setattr(live_settings, "video_provider", "none")
    assert build_payment_provider() is None
    assert build_video_provider() is None


# --------------------------------------------------------------------------- #
# payment_provider='razorpay' requires its key pair
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    ("key_id", "key_secret", "missing"),
    [
        (None, None, ("razorpay_key_id", "razorpay_key_secret")),
        (KEY_ID, None, ("razorpay_key_secret",)),
        (None, KEY_SECRET, ("razorpay_key_id",)),
    ],
    ids=["neither", "secret_missing", "key_id_missing"],
)
def test_razorpay_requires_both_credentials(key_id, key_secret, missing):
    message = _refuses(
        names=missing + ("razorpay",),
        secrets=tuple(value for value in (key_id, key_secret) if value),
        payment_provider="razorpay",
        razorpay_key_id=SecretStr(key_id) if key_id else None,
        razorpay_key_secret=SecretStr(key_secret) if key_secret else None,
    )
    # The setting that WAS supplied must not be reported as missing.
    for supplied, name in ((key_id, "razorpay_key_id"), (key_secret, "razorpay_key_secret")):
        if supplied and name not in missing:
            assert f"{name} is required" not in message


@pytest.mark.parametrize(
    # NB: the literal string "placeholder" is deliberately NOT parametrised here —
    # it appears in the (correct) error text, so it could not be asserted absent.
    "placeholder",
    ["changeme", "change-me", "  TODO  ", "tbd", "your-key", "xxx", "test"],
)
def test_razorpay_rejects_placeholder_credentials(placeholder):
    _refuses(
        names=("razorpay_key_id", "razorpay_key_secret", "placeholder"),
        secrets=(placeholder,),
        payment_provider="razorpay",
        razorpay_key_id=SecretStr(placeholder),
        razorpay_key_secret=SecretStr(placeholder),
    )


@pytest.mark.parametrize("blank", ["", "   "])
def test_razorpay_rejects_blank_credentials(blank):
    _refuses(
        names=("razorpay_key_id", "razorpay_key_secret"),
        payment_provider="razorpay",
        razorpay_key_id=SecretStr(blank),
        razorpay_key_secret=SecretStr(blank),
    )


def test_razorpay_with_real_credentials_constructs_and_keeps_them_secret():
    configured = _build(
        payment_provider="razorpay",
        razorpay_key_id=SecretStr(KEY_ID),
        razorpay_key_secret=SecretStr(KEY_SECRET),
    )
    assert configured.payment_provider == "razorpay"
    assert configured.razorpay_key_secret.get_secret_value() == KEY_SECRET
    # SecretStr masks the value in every incidental rendering.
    for rendering in (repr(configured), str(configured.razorpay_key_secret)):
        assert KEY_SECRET not in rendering
        assert KEY_ID not in rendering


# --------------------------------------------------------------------------- #
# video_provider='livekit' requires url + api key pair
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    ("url", "api_key", "api_secret", "missing"),
    [
        (None, None, None, ("livekit_url", "livekit_api_key", "livekit_api_secret")),
        ("", LIVEKIT_KEY, LIVEKIT_SECRET, ("livekit_url",)),
        ("   ", LIVEKIT_KEY, LIVEKIT_SECRET, ("livekit_url",)),
        (LIVEKIT_URL, None, LIVEKIT_SECRET, ("livekit_api_key",)),
        (LIVEKIT_URL, LIVEKIT_KEY, None, ("livekit_api_secret",)),
        (LIVEKIT_URL, "changeme", LIVEKIT_SECRET, ("livekit_api_key",)),
    ],
    ids=["nothing", "empty_url", "blank_url", "no_key", "no_secret", "placeholder_key"],
)
def test_livekit_requires_url_and_api_key_pair(url, api_key, api_secret, missing):
    message = _refuses(
        names=missing + ("livekit",),
        secrets=tuple(v for v in (api_key, api_secret) if v and v != "changeme"),
        video_provider="livekit",
        livekit_url=url,
        livekit_api_key=SecretStr(api_key) if api_key else None,
        livekit_api_secret=SecretStr(api_secret) if api_secret else None,
    )
    # A URL is an endpoint, not a credential, but it is still never echoed.
    if url:
        assert url.strip() == "" or url not in message


#: Values that are present, non-blank, and completely unusable by the adapter.
#: ``wss://`` is the one a real operator actually writes (it is the URL the
#: BROWSER needs), which is what made this defect likely rather than theoretical.
#: A host token that appears in NO validator message, so "the value was not
#: echoed back at the operator" is actually falsifiable.
UNREACHABLE_HOST = "vid7yq.legalsaathi.example"
UNREACHABLE_LIVEKIT_URLS = (
    f"wss://{UNREACHABLE_HOST}",           # what an operator actually writes
    f"ws://{UNREACHABLE_HOST}",
    UNREACHABLE_HOST,                      # scheme-less host
    f"{UNREACHABLE_HOST}:7880",            # scheme-less host:port
    f"//{UNREACHABLE_HOST}",               # protocol-relative
    f"turn://{UNREACHABLE_HOST}",
    "http://",                             # a scheme with no host at all
    "https://",
)


@pytest.mark.parametrize("url", UNREACHABLE_LIVEKIT_URLS)
def test_livekit_url_must_be_reachable_over_http(url):
    """A URL the adapter cannot POST to is a refusal to boot, not a runtime 5xx.

    ``LiveKitCommunityAdapter._twirp`` sends
    ``POST {livekit_url}/twirp/livekit.RoomService/<Method>`` with httpx. Before
    this rule, a ``wss://`` value satisfied every fail-closed check and the
    deployment came up healthy — then failed EVERY ``revoke_participant`` /
    ``close_room`` at runtime as ``PROVIDER_UNREACHABLE``, i.e. exactly the class
    of misconfiguration this gate exists to prevent.
    """
    message = _refuses(
        names=("livekit_url", "LIVEKIT_URL", "livekit"),
        secrets=(LIVEKIT_KEY, LIVEKIT_SECRET),
        video_provider="livekit",
        livekit_url=url,
        livekit_api_key=SecretStr(LIVEKIT_KEY),
        livekit_api_secret=SecretStr(LIVEKIT_SECRET),
    )
    # The refusal never echoes the supplied host, nor either credential.
    assert UNREACHABLE_HOST not in message
    for secret in SECRETS:
        assert secret not in message
    # ...and it does not pretend anything else is missing.
    assert "livekit_api_key is required" not in message
    assert "livekit_api_secret is required" not in message


def test_the_wss_refusal_explains_the_rule_it_is_enforcing():
    """The message has to be actionable: an operator sees WHY wss:// is wrong."""
    message = _refuses(
        names=("livekit_url", "LIVEKIT_URL"),
        video_provider="livekit",
        livekit_url=f"wss://{UNREACHABLE_HOST}",
        livekit_api_key=SecretStr(LIVEKIT_KEY),
        livekit_api_secret=SecretStr(LIVEKIT_SECRET),
    )
    assert "http://" in message and "https://" in message
    assert "wss://" in message
    assert "twirp" in message.lower()


@pytest.mark.parametrize(
    "url",
    [
        "http://livekit:7880",
        "http://localhost:1039",
        "https://livekit.legalsaathi.example",
        "https://livekit.legalsaathi.example:443/",
        "http://172.29.30.10:7880",
        "  https://livekit.legalsaathi.example  ",
    ],
)
def test_livekit_url_accepts_http_and_https(url):
    """Both schemes httpx can POST to construct, including the compose-internal one."""
    configured = _build(
        video_provider="livekit",
        livekit_url=url,
        livekit_api_key=SecretStr(LIVEKIT_KEY),
        livekit_api_secret=SecretStr(LIVEKIT_SECRET),
    )
    assert configured.livekit_url == url
    # And the adapter that consumes it agrees the value is usable. Surrounding
    # whitespace is tolerated in both places or in neither — the gate strips
    # before validating, so the adapter must strip before building a URL.
    from app.services.providers.video_provider import LiveKitCommunityAdapter

    adapter = LiveKitCommunityAdapter(url, LIVEKIT_KEY, LIVEKIT_SECRET)
    assert adapter._url.startswith(("http://", "https://"))


def test_livekit_url_scheme_is_only_enforced_when_livekit_is_selected():
    """A stale/leftover URL must not block a deterministic or 'none' deployment.

    Selecting a provider is the explicit deployment act; an unused variable is
    not a misconfiguration, so the rule is scoped to ``video_provider='livekit'``.
    """
    for provider in ("deterministic", "none"):
        assert _build(
            video_provider=provider,
            livekit_url="wss://livekit.legalsaathi.example",
        ).video_provider == provider


def test_livekit_with_full_configuration_constructs():
    configured = _build(
        video_provider="livekit",
        livekit_url=LIVEKIT_URL,
        livekit_api_key=SecretStr(LIVEKIT_KEY),
        livekit_api_secret=SecretStr(LIVEKIT_SECRET),
    )
    assert configured.video_provider == "livekit"
    assert configured.livekit_api_secret.get_secret_value() == LIVEKIT_SECRET
    assert LIVEKIT_SECRET not in repr(configured)


# --------------------------------------------------------------------------- #
# Unknown provider bindings
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("provider", ["stripe", "paypal", "", "  ", "razorpay-live"])
def test_an_unknown_payment_provider_is_rejected(provider):
    message = _refuses(names=("payment_provider",), payment_provider=provider)
    assert ", ".join(PAYMENT_PROVIDER_CHOICES) in message
    # The gate reports the SETTING and the allowed set; it never asks the caller
    # to trust an unknown binding.
    assert "razorpay_key_id" not in message


@pytest.mark.parametrize("provider", ["zoom", "twilio", "", "livekit-cloud"])
def test_an_unknown_video_provider_is_rejected(provider):
    message = _refuses(names=("video_provider",), video_provider=provider)
    assert ", ".join(VIDEO_PROVIDER_CHOICES) in message


def test_provider_names_are_normalised_before_the_gate_is_applied():
    """``RAZORPAY`` selects razorpay — and therefore still needs its keys."""
    _refuses(
        names=("razorpay_key_id", "razorpay_key_secret"),
        payment_provider="  RAZORPAY  ",
    )
    _refuses(names=("livekit_url",), video_provider="LiveKit")
    assert _build(payment_provider="  Deterministic  ").payment_provider


# --------------------------------------------------------------------------- #
# Strictly positive integers
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("name", POSITIVE_INT_SETTINGS)
@pytest.mark.parametrize("value", [0, -1, -3600])
def test_positive_integer_settings_reject_zero_and_negatives(name, value):
    message = _refuses(names=(name,), **{name: value})
    assert "strictly positive integer" in message
    # Only the offending setting is reported.
    for other in POSITIVE_INT_SETTINGS:
        if other != name:
            assert other not in message


@pytest.mark.parametrize("name", POSITIVE_INT_SETTINGS)
def test_positive_integer_settings_accept_one(name):
    assert getattr(_build(**{name: 1}), name) == 1


def test_several_non_positive_settings_are_all_reported_at_once():
    message = _refuses(
        names=POSITIVE_INT_SETTINGS,
        booking_hold_minutes=0,
        join_credential_ttl_seconds=0,
        rate_limit_tutor_search_per_min=-1,
        rate_limit_booking_per_min=0,
        rate_limit_review_per_hour=-5,
        refund_free_cancel_hours=0,
    )
    assert message.count("strictly positive integer") == len(POSITIVE_INT_SETTINGS)


# --------------------------------------------------------------------------- #
# reminder_offsets
# --------------------------------------------------------------------------- #


def test_reminder_offsets_must_not_be_empty():
    message = _refuses(names=("reminder_offsets",), reminder_offsets=[])
    assert "non-empty list" in message


@pytest.mark.parametrize(
    "offsets",
    [["2h"], ["7d", "2h"], ["30m"], ["7 d"], ["1w", "1d"], ["7D"]],
    ids=["2h", "7d_plus_2h", "30m", "spaced", "1w", "uppercase"],
)
def test_reminder_offsets_must_be_drawn_from_the_allowed_set(offsets):
    message = _refuses(names=("reminder_offsets",), reminder_offsets=offsets)
    assert ", ".join(REMINDER_OFFSET_CHOICES) in message


@pytest.mark.parametrize(
    "offsets", [["7d", "1d", "3h"], ["3h"], ["1d", "3h"], [" 7d ", "1d"]]
)
def test_any_non_empty_subset_of_the_allowed_offsets_constructs(offsets):
    assert _build(reminder_offsets=offsets).reminder_offsets == offsets


# --------------------------------------------------------------------------- #
# The privacy + typing contract of the failure itself
# --------------------------------------------------------------------------- #


def test_configuration_error_is_a_runtime_error_and_not_a_field_validation_error():
    assert issubclass(ConfigurationError, RuntimeError)
    assert not issubclass(ConfigurationError, PydanticValidationError)
    with pytest.raises(ConfigurationError):
        _build(payment_provider="razorpay")
    # It propagates out of Settings(...) UNWRAPPED: pydantic must not have
    # rewritten it into a field-level ValidationError.
    try:
        _build(payment_provider="razorpay")
    except PydanticValidationError as exc:  # pragma: no cover - contract guard
        pytest.fail(f"ConfigurationError was wrapped by pydantic: {exc}")
    except ConfigurationError:
        pass


def test_no_supplied_secret_value_ever_reaches_the_error_message():
    """Everything wrong at once: names every setting, leaks not one value."""
    message = _refuses(
        names=(
            "razorpay_key_secret",
            "livekit_api_secret",
            "booking_hold_minutes",
            "reminder_offsets",
        ),
        secrets=SECRETS,
        payment_provider="razorpay",
        razorpay_key_id=SecretStr(KEY_ID),
        razorpay_key_secret=None,
        video_provider="livekit",
        livekit_url=LIVEKIT_URL,
        livekit_api_key=SecretStr(LIVEKIT_KEY),
        livekit_api_secret=None,
        booking_hold_minutes=0,
        reminder_offsets=["2h"],
    )
    for secret in SECRETS:
        assert secret not in message
        assert secret not in repr(message)
    # The already-configured halves are not reported as problems.
    assert "razorpay_key_id is required" not in message
    assert "livekit_api_key is required" not in message
    assert "livekit_url is required" not in message
