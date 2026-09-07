import base64
import binascii
from ipaddress import ip_address
import math
from pathlib import Path
import re
import tempfile
from urllib.parse import unquote, urlsplit

from pydantic import SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class ConfigurationError(RuntimeError):
    """Raised when the process is configured in a way that must not start.

    Same fail-closed philosophy as ``app.core.crypto.CryptoConfigError``: the
    application refuses to boot rather than silently degrading (pretending an
    OTP was sent, minting a join credential no provider will honour, or taking a
    payment through an unconfigured gateway).

    PRIVACY CONTRACT: the message names the missing/invalid SETTING only. It
    never contains a secret value, and it must never be built by interpolating
    one — see ``_missing`` below, which takes names, not values.
    """


# Values that are present but are obviously not real credentials. A deployment
# that ships one of these is misconfigured, not configured.
_PLACEHOLDER_SECRETS = frozenset(
    {
        "", "changeme", "change-me", "change_me", "placeholder", "todo", "tbd",
        "none", "null", "test", "testing", "secret", "dev", "devkey", "devsecret",
        "dev-secret", "example", "xxx", "xxxx", "your-key", "your-key-id",
        "your-secret", "razorpay", "livekit", "rzp_test_key", "key", "api_key",
    }
)
_OTP_STRICT_INTEGER_FIELDS = (
    "otp_challenge_ttl_seconds",
    "otp_resend_cooldown_seconds",
    "otp_lockout_seconds",
    "otp_max_attempts",
    "otp_attempt_window_seconds",
    "otp_resend_window_seconds",
    "otp_max_resends_per_window",
    "otp_issue_rate_window_seconds",
    "otp_issue_identity_limit",
    "otp_issue_ip_limit",
    "otp_issue_global_limit",
    "otp_resend_rate_window_seconds",
    "otp_resend_identity_limit",
    "otp_resend_ip_limit",
    "otp_resend_global_limit",
    "otp_verify_rate_window_seconds",
    "otp_verify_identity_limit",
    "otp_verify_ip_limit",
    "otp_verify_global_limit",
    "otp_outbox_lease_seconds",
    "otp_outbox_max_attempts",
    "otp_outbox_retry_base_seconds",
    "otp_outbox_retry_max_seconds",
    "otp_rate_bucket_retention_seconds",
    "otp_security_state_retention_seconds",
    "otp_outbox_legacy_destination_retention_seconds",
    "otp_flow_ttl_seconds",
    "otp_recovery_proof_ttl_seconds",
)
_MENTOR_STRICT_INTEGER_FIELDS = (
    "mentor_bootstrap_ttl_seconds",
    "mentor_ceremony_ttl_seconds",
    "mentor_session_absolute_ttl_seconds",
    "mentor_session_idle_ttl_seconds",
    "mentor_authority_step_up_ttl_seconds",
    "mentor_provider_deadline_seconds",
    "mentor_provider_circuit_breaker_failures",
    "mentor_rate_window_seconds",
    "mentor_rate_max_requests",
    "mentor_session_max_generation",
    "mentor_terminal_retention_seconds",
    "mentor_audit_link_retention_seconds",
    "mentor_retention_batch_size",
)
#: Wave 2 provider bindings that the code can actually honour.
PAYMENT_PROVIDER_CHOICES = ("deterministic", "razorpay", "none")
VIDEO_PROVIDER_CHOICES = ("deterministic", "livekit", "none")
VIDEO_ICE_TRANSPORT_POLICY_CHOICES = ("all", "relay")
#: The only reminder offsets ``session_reminder_jobs.offset_kind`` accepts.
REMINDER_OFFSET_CHOICES = ("7d", "1d", "3h")


def is_isolated_wave4_database_url(value: str | None) -> bool:
    """Recognise an explicit local QA/test target, never credentials/query.

    Merely searching the full URL would allow a username, password or query
    parameter containing ``test`` to open the publication seam.  Only the final
    path component (the PostgreSQL database or SQLite filename) is considered,
    and the marker must be a delimited token rather than a substring. Remote
    databases are rejected even when named ``wave4_qa``; publication testing is
    intentionally limited to loopback PostgreSQL or an explicit temp SQLite
    file on this host.
    """
    if not value:
        return False
    parsed = urlsplit(value)
    decoded_path = unquote(parsed.path)
    target = (decoded_path.rsplit("/", 1)[-1] or "").casefold()
    tokens = {item for item in re.split(r"[^a-z0-9]+", target) if item}
    # A feature/ticket name is not an isolation claim.  Destructive seed and
    # target-runtime gates require an explicit environment token in the actual
    # database name/path; credentials and query parameters never participate.
    if not tokens & {"test", "testing", "qa", "e2e"}:
        return False
    # Never let a positive QA token override an explicit production/staging
    # token (for example ``production_qa`` or ``legalsaathi_prod_test``).
    if tokens & {"prod", "production", "stage", "staging"}:
        return False
    scheme = parsed.scheme.casefold()
    if scheme.startswith("postgresql") or scheme.startswith("postgres"):
        host = (parsed.hostname or "").casefold()
        if host == "localhost":
            return True
        try:
            return ip_address(host).is_loopback
        except ValueError:
            return False
    if scheme.startswith("sqlite"):
        if target == ":memory:":
            return True
        raw_path = decoded_path
        if not raw_path:
            return False
        try:
            resolved = Path(raw_path).expanduser().resolve()
            temp_roots = {
                Path(tempfile.gettempdir()).resolve(),
                Path("/tmp").resolve(),
                Path("/private/tmp").resolve(),
            }
            return any(resolved == root or resolved.is_relative_to(root) for root in temp_roots)
        except (OSError, RuntimeError):
            return False
    return False


def _is_placeholder_secret(secret: "SecretStr | str | None") -> bool:
    """True when a secret is absent or a known non-credential placeholder.

    Only the CLASSIFICATION escapes this function; the value never does.
    """
    if secret is None:
        return True
    raw = secret.get_secret_value() if isinstance(secret, SecretStr) else str(secret)
    return raw.strip().lower() in _PLACEHOLDER_SECRETS


#: Schemes ``LIVEKIT_URL`` may use. NOT a style preference: the adapter POSTs to
#: ``{livekit_url}/twirp/livekit.RoomService/<Method>`` with httpx, so anything
#: else — ``wss://`` above all — is a value that passes every fail-closed check
#: and then fails every ``revoke_participant`` / ``close_room`` at runtime.
LIVEKIT_URL_SCHEMES = ("http", "https")


def _livekit_url_problem(url: "str | None") -> str | None:
    """Classify ``livekit_url`` for the fail-closed gate, or ``None`` if usable.

    Returns a message naming the SETTING and describing the RULE. The supplied
    value is never interpolated: a URL is an endpoint rather than a credential,
    but it can still carry ``user:password@`` userinfo, and this validator's
    privacy contract is that nothing an operator supplied is echoed back.
    """
    raw = (url or "").strip()
    if not raw:
        return "livekit_url is required when video_provider='livekit'"
    parsed = urlsplit(raw)
    if parsed.scheme.lower() not in LIVEKIT_URL_SCHEMES:
        return (
            "livekit_url (env LIVEKIT_URL) must be an "
            f"{' or '.join(s + '://' for s in LIVEKIT_URL_SCHEMES)} URL when "
            "video_provider='livekit'; the adapter POSTs to "
            "{livekit_url}/twirp/livekit.RoomService/<Method>, so a wss:// or "
            "scheme-less value fails every server-side call at runtime. The "
            "wss:// URL browsers connect to is a separate frontend setting"
        )
    if not parsed.hostname:
        return (
            "livekit_url (env LIVEKIT_URL) must include a host when "
            "video_provider='livekit'"
        )
    return None


def _livekit_public_url_problem(url: "str | None", *, production: bool) -> str | None:
    """Classify the browser-facing LiveKit WebSocket URL without echoing it.

    ``LIVEKIT_URL`` is the server-to-server HTTP endpoint. Browsers need a
    distinct ``ws://``/``wss://`` endpoint, because the compose-internal host
    (``http://livekit:7880``) is deliberately not browser-addressable. Local
    development may use plain ``ws://localhost``; staging/production must use
    trusted TLS and therefore ``wss://``.
    """
    raw = (url or "").strip()
    if not raw:
        return (
            "livekit_public_url is required when video calls use "
            "video_provider='livekit'"
        )
    parsed = urlsplit(raw)
    allowed = ("wss",) if production else ("ws", "wss")
    if parsed.scheme.lower() not in allowed or not parsed.hostname:
        scheme = "wss://" if production else "ws:// or wss://"
        return f"livekit_public_url must be a {scheme} URL with a host"
    if parsed.username or parsed.password:
        return "livekit_public_url must not contain userinfo"
    return None


class Settings(BaseSettings):
    # Application
    app_name: str = "NyayOne"
    app_version: str = "0.1.0"
    app_env: str = "development"
    log_level: str = "INFO"
    # Optional JSONL file sink used by Logstash/Filebeat-style collectors.
    # Keep stdout JSON logging enabled; this adds a second local file handler.
    log_file_path: str | None = None

    # CORS: frontend is published on NyayOne's isolated host port 1130.
    cors_origins: list[str] = ["http://localhost:1130", "http://127.0.0.1:1130"]

    # --- Database (Postgres + pgvector; host port 1132 -> container 5432) ---
    # Default targets the local docker-compose Postgres. Override via DATABASE_URL.
    database_url: str = "postgresql+psycopg://nyayone:nyayone_dev_only@localhost:1132/nyayone"
    # Optional separate URL used by the test suite; when unset, tests use SQLite in-memory.
    test_database_url: str | None = None
    db_pool_size: int = 5
    db_max_overflow: int = 10
    db_echo: bool = False

    # --- Worker / broker (Valkey-preferred; host port 1133) ---
    # Broker URL for the worker; Valkey is the default (BSD, Redis-compatible).
    # No Redis-specific product assumptions. Not connected in the foundation stage.
    worker_broker_url: str = "valkey://localhost:1133/0"
    worker_max_attempts: int = 3
    worker_base_delay_s: float = 0.5
    worker_backoff_factor: float = 2.0

    # --- Config-ready placeholders (declared here, not wired in the foundation tickets) ---
    # Cache / queue broker. Valkey is the default (BSD-licensed, Redis-compatible); host port 1133
    valkey_url: str | None = None
    # Object storage: S3-compatible abstraction. Local default SeaweedFS S3 API on host port 1135
    storage_endpoint_url: str | None = None
    storage_bucket: str | None = None
    storage_access_key: SecretStr | None = None
    storage_secret_key: SecretStr | None = None
    # Internal LLM Gateway fronting local open-weight inference (Ollama dev, vLLM prod); host port 1137
    llm_gateway_url: str | None = None

    # Existing integrations
    github_repository: str = "rajeevbarnwal/NyayOne"
    github_repo_url: str = "https://github.com/rajeevbarnwal/NyayOne"
    github_token: SecretStr | None = None
    # Registration crypto (SAATHI-366/448): key material for keyed lookup hashes
    # and Fernet ciphertext of sensitive registration fields. Override in prod.
    # In production/staging the app FAILS CLOSED if this is absent or still the
    # known development default (see app.core.crypto.assert_crypto_ready).
    registration_secret: SecretStr = SecretStr("dev-registration-secret-change-me")
    # Stable HMAC lookup key. Encryption keys may rotate without invalidating
    # uniqueness/search hashes already stored in the database.
    registration_lookup_secret: SecretStr = SecretStr("dev-registration-lookup-change-me")
    # Active encryption key version stamped onto every ciphertext produced
    # (`<version>:<token>`); decrypt tries the active key then any prior key.
    registration_key_version: str = "v1"
    # Optional PRIOR key material for rotation — old ciphertext stays decryptable
    # after the active secret is rotated. Format: "<version>:<secret>".
    registration_prior_keys: list[str] = []
    # --- Wave 1 (SAATHI-63) comparison rules — Product decision 2026-07-27 ---
    # Backend-authoritative bounds for law-school comparison sets. Config-driven
    # so Product can retune without a migration (recorded on SAATHI-63).
    compare_max_schools: int = 4
    compare_min_schools: int = 2

    # --- Wave 3 credential trust (SAATHI-253/258) --------------------------
    credential_max_file_bytes: int = 10 * 1024 * 1024
    credential_max_evidence_files: int = 5
    credential_token_lifetime_days: int = 90
    credential_public_rate_per_minute: int = 30
    credential_storage_root: str = "/tmp/nyayone_credential_storage"
    credential_scanner_provider: str = "deterministic"
    credential_public_base_url: str = "https://localhost:1130/verify"
    retention_days_credential_audit: int | None = None
    retention_days_credential_evidence: int | None = None

    # --- Wave 4 private internship reporting (SAATHI-269 / SAATHI-450) ----
    internship_report_max_file_bytes: int = 5 * 1024 * 1024
    internship_report_max_evidence_files: int = 5
    internship_report_storage_root: str = "/tmp/nyayone_internship_report_storage"
    internship_report_scanner_provider: str = "deterministic"
    internship_report_clamav_host: str = "127.0.0.1"
    internship_report_clamav_port: int = 3310
    internship_report_clamav_timeout_seconds: float = 10.0
    internship_report_consent_version: str = "internship-report-v1"
    retention_days_internship_report_evidence: int | None = None
    # Product approval W4-PRODUCT-APPROVAL-20260801 permits implementation but
    # explicitly forbids activation until counsel/security + target gates pass.
    internship_risk_labels_enabled: bool = False
    # Isolated gate-runner seam. This does not authorize a deployment and is
    # rejected unless APP_ENV=testing and TEST_DATABASE_URL clearly names an
    # isolated QA/test database.
    wave4_gate_allow_publication_test: bool = False
    wave4_security_approval_ref: str | None = None
    wave4_policy_approval_ref: str | None = None
    wave4_target_runtime_gate_ref: str | None = None
    internship_response_token_rate_per_minute: int = 10
    internship_response_ip_rate_per_minute: int = 60
    internship_identity_access_ttl_minutes: int = 30
    internship_response_public_base_url: str = "https://localhost:1130/s-89"
    internship_response_notification_provider: str = "none"
    # Approved SAATHI-452 internal aggregation defaults. These values may build
    # a privacy-safe candidate but never enable a public projection.
    internship_risk_min_distinct_reporters: int = 3
    internship_risk_window_months: int = 24
    internship_risk_public_count_suppression: int = 5

    # --- Wave 5 calendar interoperability (SAATHI-285/290/295) -----------
    # Opaque external-feed URLs expire unless the owner explicitly rotates or
    # revokes them earlier. The database stores only a keyed token hash.
    calendar_export_token_ttl_days: int = 90
    # Absolute subscriber-facing origin. It is non-secret; the bearer token is
    # appended only to the one-time response and never persisted or logged.
    calendar_public_base_url: str = "https://localhost:1130"

    # --- Wave 2 tutoring marketplace (SAATHI-123 / SAATHI-127) -------------
    # Booking hold TTL: how long a slot stays reserved while the student pays.
    booking_hold_minutes: int = 10
    # Payment provider binding. "deterministic" is the in-process, no-network
    # adapter used by dev/test; "razorpay" requires the key pair below.
    payment_provider: str = "deterministic"
    razorpay_key_id: SecretStr | None = None
    razorpay_key_secret: SecretStr | None = None
    # Product enablement and provider selection are deliberately separate.
    # Production defaults fail closed: no call is offered and no deterministic
    # adapter is selected accidentally. Tests/development opt in explicitly.
    video_calls_enabled: bool = False
    # "deterministic" is test/development only; "livekit" is the production
    # adapter; "none" is the safe default.
    video_provider: str = "none"
    livekit_url: str | None = None
    # Browser-facing signalling URL. This is NOT the server-side Twirp URL.
    livekit_public_url: str | None = None
    # Browser ICE selection is server-authoritative. ``all`` permits the best
    # direct path and falls back to TURN; ``relay`` proves/forces that media
    # traverses the configured TURN service on restrictive networks. This is
    # safe to expose to browsers and contains no provider credential.
    video_ice_transport_policy: str = "all"
    livekit_api_key: SecretStr | None = None
    livekit_api_secret: SecretStr | None = None
    # Join credential lifetime. Short-lived by design; only the hash is stored.
    join_credential_ttl_seconds: int = 300
    # Abuse limits (per identity) for the Wave 2 surfaces.
    rate_limit_tutor_search_per_min: int = 60
    rate_limit_booking_per_min: int = 10
    rate_limit_review_per_hour: int = 5
    # Default session price, in INTEGER PAISE, stamped onto a tutor profile that
    # has not published its own. This is the DEPLOYMENT-WIDE fallback for the
    # server-authoritative price; it is never read from a request and never sent
    # to a browser as an authority. Strictly positive: zero is not "free
    # tutoring", it is a mispriced product (a free offering would need its own
    # explicit product flag, never an inferred 0).
    tutoring_default_session_price_paise: int = 250_000
    # Reminder offsets scheduled per confirmed session.
    reminder_offsets: list[str] = ["7d", "1d", "3h"]
    # Cancellation window that earns an automatic full refund, in hours.
    refund_free_cancel_hours: int = 24

    # OTP delivery must be explicitly enabled + provider-bound in a deployment;
    # otherwise the API fails closed rather than pretending an OTP was sent.
    otp_delivery_enabled: bool = False
    # Concrete provider to bind when delivery is enabled: "none" (fail closed),
    # "capturing" (in-memory, dev/test), or "http" (real POST adapter).
    otp_provider: str = "none"
    otp_provider_url: str | None = None
    otp_provider_token: SecretStr | None = None
    otp_provider_timeout_s: float = 10.0
    # Deployment acknowledgement that retries with the same delivery key are
    # deduplicated by the configured provider.
    otp_provider_supports_idempotency: bool = False
    # NYAY-4 server authority. Defaults reproduce the approved product
    # contract (3 attempts, 15-minute lock, 30-second cooldown, 5-minute OTP)
    # while every abuse/relay budget remains explicit deployment config.
    otp_challenge_ttl_seconds: int = 5 * 60
    otp_resend_cooldown_seconds: int = 30
    otp_lockout_seconds: int = 15 * 60
    otp_max_attempts: int = 3
    otp_attempt_window_seconds: int = 15 * 60
    otp_resend_window_seconds: int = 15 * 60
    otp_max_resends_per_window: int = 3
    otp_issue_rate_window_seconds: int = 10 * 60
    otp_issue_identity_limit: int = 5
    otp_issue_ip_limit: int = 20
    otp_issue_global_limit: int = 200
    otp_resend_rate_window_seconds: int = 15 * 60
    otp_resend_identity_limit: int = 3
    otp_resend_ip_limit: int = 10
    otp_resend_global_limit: int = 100
    otp_verify_rate_window_seconds: int = 15 * 60
    otp_verify_identity_limit: int = 10
    otp_verify_ip_limit: int = 30
    otp_verify_global_limit: int = 300
    otp_outbox_lease_seconds: int = 30
    otp_outbox_max_attempts: int = 5
    otp_outbox_retry_base_seconds: int = 10
    otp_outbox_retry_max_seconds: int = 5 * 60
    otp_rate_bucket_retention_seconds: int = 7 * 24 * 60 * 60
    # Terminal flow capabilities and inactive subject/purpose authorities are
    # retained only for this bounded security/audit window.
    otp_security_state_retention_seconds: int = 7 * 24 * 60 * 60
    otp_outbox_legacy_destination_retention_seconds: int = 7 * 24 * 60 * 60
    otp_flow_cookie_name: str = "nyayone_otp_flow"
    otp_flow_ttl_seconds: int = 10 * 60
    otp_recovery_proof_ttl_seconds: int = 5 * 60

    # --- NYAY-12 verified-email login identity ------------------------------
    # Server-owned, fail-closed feature flag: the S-04 email channel exists only
    # when this is true AND the caller owns an independently verified identity.
    email_login_enabled: bool = False
    email_otp_provider: str = "none"
    email_otp_provider_url: str | None = None
    email_otp_provider_token: SecretStr | None = None
    email_otp_provider_timeout_s: float = 10.0
    email_otp_provider_supports_idempotency: bool = False
    email_identity_max_per_user: int = 3

    # --- Student OTP login + cookie session --------------------------------
    # Login challenges remain separate from signup/recovery challenges. The
    # browser receives only an HttpOnly cookie; the database stores its hash.
    auth_session_cookie_name: str = "nyayone_session"
    auth_session_ttl_seconds: int = 7 * 24 * 60 * 60
    login_attempt_ttl_seconds: int = 10 * 60

    # --- NYAY-22 isolated mentor ceremony/session --------------------------
    # Deployments may shorten these design ceilings but can never lengthen
    # them.  The mentor authority remains a distinct session class.
    mentor_bootstrap_ttl_seconds: int = 15 * 60
    mentor_ceremony_ttl_seconds: int = 15 * 60
    mentor_session_absolute_ttl_seconds: int = 8 * 60 * 60
    mentor_session_idle_ttl_seconds: int = 30 * 60
    mentor_authority_step_up_ttl_seconds: int = 5 * 60
    mentor_identity_provider_class: str = "nyayone_reviewed_identity"
    mentor_identity_provider_assurance: str = "high"
    mentor_identity_provider_policy_version: str = "mentor-proof.v1"
    mentor_identity_provider_issuer: str = "nyayone-identity-boundary.v1"
    mentor_identity_provider_audience: str = "nyayone-mentor-ceremony.v1"
    mentor_identity_provider_algorithm: str = "EdDSA"
    # Deterministic development verifier. Production/staging must override it.
    mentor_identity_provider_public_key_b64: str = (
        "oJql9HpnWYAv+VX43C0qFKXJnSO+l/hkEn/5ODRVpPA="
    )
    # Non-public, server-to-server start/result exchange.  A deployment may
    # leave this absent only when the relay is not run; the relay builder then
    # fails closed before claiming any transaction.  Browser routes never read
    # or expose this value.
    mentor_identity_provider_start_url: str | None = None
    mentor_identity_provider_allowed_hosts: list[str] = []
    mentor_provider_deadline_seconds: int = 30
    mentor_provider_circuit_breaker_failures: int = 3
    mentor_rate_window_seconds: int = 60
    mentor_rate_max_requests: int = 20
    mentor_session_max_generation: int = 64
    mentor_privacy_notice_version: str = "mentor-privacy.v1"
    mentor_authority_step_up_notice_version: str = "mentor-authority-deletion.v1"
    mentor_retention_notice_version: str = "mentor-retention.v1"
    mentor_terminal_retention_seconds: int = 30 * 24 * 60 * 60
    mentor_audit_link_retention_seconds: int = 30 * 24 * 60 * 60
    mentor_retention_batch_size: int = 128
    mentor_retention_mode: str = "bounded_crypto_erasure"

    # --- DPDP retention / deletion (SAATHI-366 C5) -------------------------
    # Config-driven retention windows per data category, in days. NO statutory
    # duration is hard-coded: unset (None) means "retain until explicit erasure"
    # and the purge job is a no-op for that category. Operators set these to the
    # value their counsel approves.
    retention_days_registration_pending: int | None = None
    retention_days_registration_inactive: int | None = None
    retention_days_otp_challenge: int | None = None
    retention_days_recovery_session: int | None = None
    retention_days_login_attempt: int | None = None
    retention_days_auth_session: int | None = None
    retention_days_audit_events: int | None = None
    # Whether the purge job anonymises (keep row, scrub PII/ciphertext) or hard
    # deletes when a window elapses. "anonymise" is the DPDP-safe default.
    retention_mode: str = "anonymise"

    jira_base_url: str = "https://legalsaathi.atlassian.net"
    jira_project_key: str = "NYAY"
    jira_board_id: int = 68
    # Explicit deployment binding; an arbitrary administrator is not the owner.
    authority_platform_owner_id: str | None = None
    authority_institution_domains: dict[str, list[str]] = {}
    jira_email: str | None = None
    jira_api_token: SecretStr | None = None

    @field_validator(
        "retention_days_registration_pending",
        "retention_days_registration_inactive",
        "retention_days_otp_challenge",
        "retention_days_recovery_session",
        "retention_days_login_attempt",
        "retention_days_auth_session",
        "retention_days_audit_events",
        mode="before",
    )
    @classmethod
    def validate_retention_days(cls, value):
        """Accept only bounded, canonical whole-day retention windows.

        ``None`` deliberately means that counsel has not authorised an
        automated terminal-history erasure window.  The upper bound is an
        arithmetic/operational safety limit, not a statutory recommendation.
        """

        if value is None:
            return None
        if isinstance(value, bool):
            raise ValueError("retention days must be a positive integer")
        if isinstance(value, str):
            if value == "":
                return None
            if re.fullmatch(r"[1-9][0-9]*", value) is None:
                raise ValueError("retention days must be a positive integer")
            parsed = int(value)
        elif isinstance(value, int):
            parsed = value
        else:
            raise ValueError("retention days must be a positive integer")
        if not 1 <= parsed <= 36_500:
            raise ValueError("retention days exceed the safety range")
        return parsed

    @field_validator("retention_mode")
    @classmethod
    def validate_retention_mode(cls, value: str) -> str:
        if value not in {"anonymise", "delete"}:
            raise ValueError("retention_mode must be anonymise or delete")
        return value

    @model_validator(mode="before")
    @classmethod
    def reject_coerced_otp_numeric_types(cls, values):
        """Permit only canonical positive decimal source strings or integers."""

        if isinstance(values, dict):
            for name in _OTP_STRICT_INTEGER_FIELDS:
                value = values.get(name)
                invalid_string = isinstance(value, str) and re.fullmatch(
                    r"[1-9][0-9]*", value
                ) is None
                invalid_literal = (
                    value is not None
                    and not isinstance(value, (int, str))
                )
                if isinstance(value, bool) or invalid_string or invalid_literal:
                    raise ConfigurationError(
                        "OTP configuration is invalid; refusing to start: "
                        f"{name} must be an integer"
                    )
            if isinstance(values.get("otp_provider_timeout_s"), bool):
                raise ConfigurationError(
                    "OTP configuration is invalid; refusing to start: "
                    "otp_provider_timeout_s must be numeric, not boolean"
                )
            ceilings = {
                "mentor_bootstrap_ttl_seconds": 900,
                "mentor_ceremony_ttl_seconds": 900,
                "mentor_session_absolute_ttl_seconds": 28_800,
                "mentor_session_idle_ttl_seconds": 1_800,
                "mentor_authority_step_up_ttl_seconds": 300,
                "mentor_provider_deadline_seconds": 120,
                "mentor_provider_circuit_breaker_failures": 20,
                # Buckets live for two windows.  This ceiling guarantees that
                # every exact retry-after value remains within the sealed
                # MentorFailure maximum of 900 seconds.
                "mentor_rate_window_seconds": 450,
                "mentor_rate_max_requests": 1_000,
                "mentor_session_max_generation": 256,
                "mentor_terminal_retention_seconds": 31_536_000,
                "mentor_audit_link_retention_seconds": 31_536_000,
                "mentor_retention_batch_size": 256,
            }
            for name in _MENTOR_STRICT_INTEGER_FIELDS:
                value = values.get(name)
                if value is None:
                    continue
                invalid_string = isinstance(value, str) and re.fullmatch(
                    r"[1-9][0-9]*", value
                ) is None
                invalid_literal = value is not None and not isinstance(value, (int, str))
                if (
                    isinstance(value, bool)
                    or invalid_string
                    or invalid_literal
                    or int(value) < 1
                    or int(value) > ceilings[name]
                ):
                    raise ValueError(
                        f"{name} must be a positive integer no greater than its security ceiling"
                    )
        return values

    @model_validator(mode="after")
    def reject_legacy_runtime_defaults(self) -> "Settings":
        """Reject known LegalSaathi operational defaults without echoing values.

        NyayOne deliberately shares one approved Atlassian tenant. Its exact
        HTTPS origin is enforced alongside the NyayOne project and board
        identities; arbitrary Jira origins are refused to protect credentials.
        """
        problems: list[str] = []
        if (self.app_name or "").strip() != "NyayOne":
            problems.append("app_name must use the NyayOne application identity")

        environment = (self.app_env or "").strip().casefold()
        if environment in {"production", "prod", "staging", "stage"}:
            canonical_origins: list[str] = []
            for raw_origin in self.cors_origins:
                try:
                    parsed_origin = urlsplit(raw_origin)
                    origin_port = parsed_origin.port
                    origin_host = (parsed_origin.hostname or "").casefold()
                except (TypeError, ValueError):
                    parsed_origin = None
                    origin_port = -1
                    origin_host = ""
                if parsed_origin is None:
                    canonical_origin = ""
                    valid_host = False
                else:
                    try:
                        origin_address = ip_address(origin_host)
                    except ValueError:
                        canonical_host = origin_host
                        valid_host = bool(
                            "*" not in origin_host
                            and re.fullmatch(
                                r"(?=.{1,253}$)(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+"
                                r"[a-z](?:[a-z0-9-]{0,61}[a-z0-9])?",
                                origin_host,
                            )
                        )
                    else:
                        canonical_host = (
                            f"[{origin_address.compressed}]"
                            if origin_address.version == 6
                            else origin_address.compressed
                        )
                        valid_host = not (
                            origin_address.is_loopback
                            or origin_address.is_unspecified
                        )
                    authority = (
                        canonical_host
                        if origin_port in {None, 443}
                        else f"{canonical_host}:{origin_port}"
                    )
                    canonical_origin = f"https://{authority}"
                if (
                    parsed_origin is None
                    or parsed_origin.scheme != "https"
                    or not valid_host
                    or origin_port == -1
                    or (
                        origin_port is not None
                        and not 1 <= origin_port <= 65_535
                    )
                    or parsed_origin.username is not None
                    or parsed_origin.password is not None
                    or parsed_origin.path
                    or parsed_origin.query
                    or parsed_origin.fragment
                    or raw_origin != canonical_origin
                ):
                    problems.append(
                        "cors_origins must contain only exact canonical HTTPS origins in production"
                    )
                    break
                canonical_origins.append(canonical_origin)
            if (
                not self.cors_origins
                or len(canonical_origins) != len(set(canonical_origins))
            ):
                problems.append(
                    "cors_origins must be non-empty and unique in production"
                )
        for setting_name in ("database_url", "test_database_url"):
            raw_url = getattr(self, setting_name)
            if not raw_url:
                continue
            database = urlsplit(raw_url)
            database_name = unquote(database.path).rstrip("/").rsplit("/", 1)[-1]
            if (
                unquote(database.username or "").casefold() == "legalsaathi"
                or database_name.casefold() == "legalsaathi"
                or database_name.casefold().startswith("legalsaathi_")
            ):
                problems.append(
                    f"{setting_name} must not use the legacy database identity"
                )
            if (
                setting_name == "database_url"
                and environment not in {"development", "dev", "local", "test", "testing"}
                and unquote(database.password or "") == "nyayone_dev_only"
            ):
                problems.append(
                    "database_url must not use development credentials outside local/test"
                )

        if (self.auth_session_cookie_name or "") != "nyayone_session":
            problems.append("auth_session_cookie_name must use the NyayOne cookie identity")
        if (self.otp_flow_cookie_name or "") != "nyayone_otp_flow":
            problems.append("otp_flow_cookie_name must use the NyayOne cookie identity")
        if self.email_login_enabled and environment not in {
            "development", "dev", "local", "test", "testing"
        }:
            email_provider = (self.email_otp_provider or "none").strip().casefold()
            if (
                email_provider != "http"
                or not (self.email_otp_provider_url or "").startswith("https://")
                or not self.email_otp_provider_supports_idempotency
                or _is_placeholder_secret(self.email_otp_provider_token)
            ):
                problems.append(
                    "email login requires an HTTPS, idempotent, authenticated email OTP provider"
                )
        if not 1 <= int(self.email_identity_max_per_user) <= 10:
            problems.append("email_identity_max_per_user must be between 1 and 10")
        if self.mentor_identity_provider_class not in {
            "nyayone_reviewed_identity",
            "approved_federated_attestation",
        }:
            problems.append("mentor identity provider class is not approved")
        if self.mentor_identity_provider_assurance != "high":
            problems.append("mentor identity provider assurance is not approved")
        if self.mentor_identity_provider_policy_version != "mentor-proof.v1":
            problems.append("mentor identity provider policy is not approved")
        if self.mentor_identity_provider_algorithm != "EdDSA":
            problems.append("mentor identity provider algorithm is not approved")
        try:
            mentor_provider_public_key = base64.b64decode(
                self.mentor_identity_provider_public_key_b64,
                validate=True,
            )
        except (binascii.Error, ValueError):
            mentor_provider_public_key = b""
        if len(mentor_provider_public_key) != 32:
            problems.append(
                "mentor identity provider public key must be a canonical "
                "Ed25519 public key"
            )
        if not self.mentor_identity_provider_issuer.strip():
            problems.append("mentor identity provider issuer is required")
        if not self.mentor_identity_provider_audience.strip():
            problems.append("mentor identity provider audience is required")
        provider_endpoint = (self.mentor_identity_provider_start_url or "").strip()
        provider_hosts = [
            item.strip().casefold()
            for item in self.mentor_identity_provider_allowed_hosts
            if isinstance(item, str) and item.strip()
        ]
        if bool(provider_endpoint) != bool(provider_hosts):
            problems.append(
                "mentor identity provider endpoint and host allowlist must be configured together"
            )
        elif provider_endpoint:
            try:
                parsed_provider = urlsplit(provider_endpoint)
                provider_port = parsed_provider.port
                provider_host = (parsed_provider.hostname or "").casefold()
            except (TypeError, ValueError):
                parsed_provider = None
                provider_port = -1
                provider_host = ""
                provider_is_ip = True
            else:
                try:
                    ip_address(provider_host)
                except ValueError:
                    provider_is_ip = False
                else:
                    provider_is_ip = True
            valid_host = bool(
                provider_host
                and not provider_is_ip
                and provider_host != "localhost"
                and "." in provider_host
                and re.fullmatch(
                    r"(?=.{1,253}$)(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+"
                    r"[a-z](?:[a-z0-9-]{0,61}[a-z0-9])?",
                    provider_host,
                )
            )
            valid_allowlist = bool(
                provider_hosts
                and len(provider_hosts) == len(self.mentor_identity_provider_allowed_hosts)
                and len(provider_hosts) == len(set(provider_hosts))
                and provider_host in provider_hosts
                and all(
                    "*" not in item
                    and item != "localhost"
                    and "." in item
                    and re.fullmatch(
                        r"(?=.{1,253}$)(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+"
                        r"[a-z](?:[a-z0-9-]{0,61}[a-z0-9])?",
                        item,
                    )
                    is not None
                    for item in provider_hosts
                )
            )
            if (
                parsed_provider is None
                or parsed_provider.scheme != "https"
                or not valid_host
                or provider_port not in {None, 443}
                or parsed_provider.username is not None
                or parsed_provider.password is not None
                or parsed_provider.query
                or parsed_provider.fragment
                or parsed_provider.path in {"", "/"}
                or not valid_allowlist
            ):
                problems.append(
                    "mentor identity provider endpoint or host allowlist is invalid"
                )
        if (
            environment not in {"development", "dev", "local", "test", "testing"}
            and not {
                "mentor_terminal_retention_seconds",
                "mentor_audit_link_retention_seconds",
                "mentor_retention_mode",
            }.issubset(self.model_fields_set)
        ):
            problems.append(
                "mentor retention policy must be deployment-explicit outside local/test"
            )
        if self.mentor_retention_mode != "bounded_crypto_erasure":
            problems.append("mentor retention mode must be bounded_crypto_erasure")
        if self.mentor_audit_link_retention_seconds > self.mentor_terminal_retention_seconds:
            problems.append(
                "mentor audit-link retention cannot exceed terminal authority retention"
            )
        for name in (
            "mentor_privacy_notice_version",
            "mentor_authority_step_up_notice_version",
            "mentor_retention_notice_version",
        ):
            if re.fullmatch(r"[a-z0-9][a-z0-9._-]{0,63}", getattr(self, name)) is None:
                problems.append(f"{name} must be a canonical contract version")
        if (
            environment not in {"development", "dev", "local", "test", "testing"}
            and provider_endpoint
            and (
            self.mentor_identity_provider_public_key_b64
            == "oJql9HpnWYAv+VX43C0qFKXJnSO+l/hkEn/5ODRVpPA="
            )
        ):
            problems.append("mentor identity provider key must be deployment-bound")
        if (self.github_repository or "").strip().casefold() != "rajeevbarnwal/nyayone":
            problems.append("github_repository must identify the NyayOne repository")
        github_url = urlsplit(self.github_repo_url or "")
        github_path = github_url.path.strip("/").casefold()
        try:
            github_port = github_url.port
        except ValueError:
            github_port = -1
        if (
            github_url.scheme.casefold() != "https"
            or (github_url.hostname or "").casefold() != "github.com"
            or github_port not in {None, 443}
            or github_url.username
            or github_url.password
            or github_url.query
            or github_url.fragment
            or github_path.removesuffix(".git") != "rajeevbarnwal/nyayone"
        ):
            problems.append("github_repo_url must identify the NyayOne repository")
        if (self.jira_project_key or "").strip().casefold() != "nyay":
            problems.append("jira_project_key must identify the NyayOne project")
        if self.jira_board_id != 68:
            problems.append("jira_board_id must identify the NyayOne board")
        jira_url = urlsplit(self.jira_base_url or "")
        try:
            jira_port = jira_url.port
        except ValueError:
            jira_port = -1
        if (
            jira_url.scheme.casefold() != "https"
            or (jira_url.hostname or "").casefold() != "legalsaathi.atlassian.net"
            or jira_port not in {None, 443}
            or jira_url.username
            or jira_url.password
            or jira_url.path.rstrip("/")
            or jira_url.query
            or jira_url.fragment
        ):
            problems.append("jira_base_url must identify the approved shared Atlassian tenant")
        for name in ("credential_storage_root", "internship_report_storage_root"):
            if "legalsaathi" in (getattr(self, name) or "").casefold():
                problems.append(f"{name} must not use the legacy storage namespace")

        if problems:
            raise ConfigurationError(
                "NyayOne runtime identity is invalid; refusing to start: "
                + "; ".join(problems)
            )
        return self

    @model_validator(mode="after")
    def validate_otp_configuration(self) -> "Settings":
        """Refuse unsafe OTP budgets or provider bindings at process start."""

        problems: list[str] = []
        positive_integers = (
            "otp_challenge_ttl_seconds",
            "otp_resend_cooldown_seconds",
            "otp_lockout_seconds",
            "otp_max_attempts",
            "otp_attempt_window_seconds",
            "otp_resend_window_seconds",
            "otp_max_resends_per_window",
            "otp_issue_rate_window_seconds",
            "otp_issue_identity_limit",
            "otp_issue_ip_limit",
            "otp_issue_global_limit",
            "otp_resend_rate_window_seconds",
            "otp_resend_identity_limit",
            "otp_resend_ip_limit",
            "otp_resend_global_limit",
            "otp_verify_rate_window_seconds",
            "otp_verify_identity_limit",
            "otp_verify_ip_limit",
            "otp_verify_global_limit",
            "otp_outbox_lease_seconds",
            "otp_outbox_max_attempts",
            "otp_outbox_retry_base_seconds",
            "otp_outbox_retry_max_seconds",
            "otp_rate_bucket_retention_seconds",
            "otp_security_state_retention_seconds",
            "otp_outbox_legacy_destination_retention_seconds",
            "otp_flow_ttl_seconds",
            "otp_recovery_proof_ttl_seconds",
        )
        for name in positive_integers:
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
                problems.append(f"{name} must be a strictly positive integer")
        bounded: dict[str, int] = {
            "otp_challenge_ttl_seconds": 30 * 60,
            "otp_resend_cooldown_seconds": 10 * 60,
            "otp_lockout_seconds": 24 * 60 * 60,
            "otp_max_attempts": 10,
            "otp_attempt_window_seconds": 24 * 60 * 60,
            "otp_resend_window_seconds": 24 * 60 * 60,
            "otp_max_resends_per_window": 10,
            "otp_issue_rate_window_seconds": 24 * 60 * 60,
            "otp_resend_rate_window_seconds": 24 * 60 * 60,
            "otp_verify_rate_window_seconds": 24 * 60 * 60,
            "otp_issue_identity_limit": 100,
            "otp_resend_identity_limit": 100,
            "otp_verify_identity_limit": 100,
            "otp_issue_ip_limit": 1_000,
            "otp_resend_ip_limit": 1_000,
            "otp_verify_ip_limit": 1_000,
            "otp_issue_global_limit": 100_000,
            "otp_resend_global_limit": 100_000,
            "otp_verify_global_limit": 100_000,
            "otp_outbox_lease_seconds": 5 * 60,
            "otp_outbox_max_attempts": 10,
            "otp_outbox_retry_base_seconds": 15 * 60,
            "otp_outbox_retry_max_seconds": 60 * 60,
            "otp_rate_bucket_retention_seconds": 90 * 24 * 60 * 60,
            "otp_security_state_retention_seconds": 90 * 24 * 60 * 60,
            "otp_outbox_legacy_destination_retention_seconds": 90 * 24 * 60 * 60,
            "otp_flow_ttl_seconds": 60 * 60,
            "otp_recovery_proof_ttl_seconds": 30 * 60,
        }
        for name, maximum in bounded.items():
            value = getattr(self, name)
            if isinstance(value, int) and not isinstance(value, bool) and value > maximum:
                problems.append(f"{name} exceeds the fail-closed safety maximum")
        if self.otp_outbox_retry_max_seconds < self.otp_outbox_retry_base_seconds:
            problems.append(
                "otp_outbox_retry_max_seconds must be at least "
                "otp_outbox_retry_base_seconds"
            )
        if self.otp_resend_cooldown_seconds >= self.otp_challenge_ttl_seconds:
            problems.append("otp_resend_cooldown_seconds must be below the challenge TTL")
        if self.otp_outbox_lease_seconds >= self.otp_challenge_ttl_seconds:
            problems.append("otp_outbox_lease_seconds must be below the challenge TTL")
        if self.otp_flow_ttl_seconds < self.otp_challenge_ttl_seconds:
            problems.append("otp_flow_ttl_seconds must cover the challenge TTL")
        if self.otp_recovery_proof_ttl_seconds > self.otp_flow_ttl_seconds:
            problems.append("otp_recovery_proof_ttl_seconds must not exceed the flow TTL")
        if self.otp_resend_window_seconds < self.otp_resend_cooldown_seconds:
            problems.append("otp_resend_window_seconds must cover the resend cooldown")
        if self.otp_attempt_window_seconds < self.otp_lockout_seconds:
            problems.append("otp_attempt_window_seconds must cover the lockout window")
        if self.otp_outbox_retry_max_seconds > self.otp_flow_ttl_seconds:
            problems.append("otp_outbox_retry_max_seconds must not exceed the flow TTL")
        for action in ("issue", "resend", "verify"):
            identity = getattr(self, f"otp_{action}_identity_limit")
            ip_limit = getattr(self, f"otp_{action}_ip_limit")
            global_limit = getattr(self, f"otp_{action}_global_limit")
            if not identity <= ip_limit <= global_limit:
                problems.append(
                    f"otp_{action} limits must satisfy identity <= ip <= global"
                )
        if self.otp_rate_bucket_retention_seconds < max(
            self.otp_issue_rate_window_seconds,
            self.otp_resend_rate_window_seconds,
            self.otp_verify_rate_window_seconds,
        ):
            problems.append("otp_rate_bucket_retention_seconds must cover every rate window")
        if self.otp_security_state_retention_seconds < self.otp_flow_ttl_seconds:
            problems.append(
                "otp_security_state_retention_seconds must cover the flow TTL"
            )

        raw_provider = self.otp_provider or ""
        provider = raw_provider.casefold()
        if raw_provider != provider:
            problems.append("otp_provider must use canonical lowercase without whitespace")
        if provider not in {"none", "capturing", "http"}:
            problems.append("otp_provider must be none, capturing or http")
        environment = (self.app_env or "").strip().casefold()
        isolated_test = environment in {"test", "testing"}
        non_local_environment = environment not in {
            "development",
            "dev",
            "local",
            "test",
            "testing",
        }
        if non_local_environment and not self.otp_delivery_enabled:
            problems.append("otp_delivery_enabled must be true outside local/test")
        if self.otp_delivery_enabled and provider == "none":
            problems.append("otp_provider must be configured when OTP delivery is enabled")
        if provider == "capturing" and not isolated_test:
            problems.append("otp_provider capturing is allowed only in testing")
        if non_local_environment and provider != "http":
            problems.append("otp_provider must be http outside local/test")
        if provider == "http":
            raw_provider_url = self.otp_provider_url or ""
            parsed = urlsplit(raw_provider_url)
            try:
                provider_port = parsed.port
            except ValueError:
                provider_port = -1
            allowed_schemes = {"http", "https"} if isolated_test else {"https"}
            unsafe_provider_url_bytes = (
                not raw_provider_url
                or any(
                    not 0x21 <= ord(character) <= 0x7E
                    for character in raw_provider_url
                )
            )
            if (
                unsafe_provider_url_bytes
                or parsed.geturl() != raw_provider_url
                or
                parsed.scheme.casefold() not in allowed_schemes
                or not parsed.hostname
                or provider_port == -1
                or (provider_port is not None and not 1 <= provider_port <= 65535)
                or parsed.username
                or parsed.password
                or parsed.query
                or parsed.fragment
            ):
                problems.append(
                    "otp_provider_url must be an absolute provider URL without "
                    "userinfo, query or fragment"
                )
            provider_token = (
                self.otp_provider_token.get_secret_value()
                if self.otp_provider_token is not None
                else ""
            )
            if not isolated_test and (
                _is_placeholder_secret(self.otp_provider_token)
                or provider_token != provider_token.strip()
                or not 16 <= len(provider_token) <= 4096
                or any(
                    not 0x21 <= ord(character) <= 0x7E
                    for character in provider_token
                )
            ):
                problems.append("otp_provider_token has an unsafe shape outside testing")
            if not self.otp_provider_supports_idempotency:
                problems.append(
                    "otp_provider_supports_idempotency must be explicitly true "
                    "for the HTTP provider"
                )
        if (
            isinstance(self.otp_provider_timeout_s, bool)
            or not isinstance(self.otp_provider_timeout_s, (int, float))
            or not math.isfinite(float(self.otp_provider_timeout_s))
            or self.otp_provider_timeout_s <= 0
        ):
            problems.append("otp_provider_timeout_s must be finite and positive")
        elif self.otp_provider_timeout_s > 30:
            problems.append("otp_provider_timeout_s exceeds the safety maximum")
        if problems:
            raise ConfigurationError(
                "OTP configuration is invalid; refusing to start: "
                + "; ".join(problems)
            )
        return self

    @field_validator("credential_public_base_url")
    @classmethod
    def validate_credential_public_base_url(cls, value: str) -> str:
        normalized = value.rstrip("/")
        if not normalized.startswith("https://") or not normalized.endswith("/verify"):
            raise ValueError(
                "credential_public_base_url must be an HTTPS URL ending in /verify"
            )
        return normalized

    @field_validator("calendar_public_base_url")
    @classmethod
    def validate_calendar_public_base_url(cls, value: str) -> str:
        normalized = (value or "").strip().rstrip("/")
        parsed = urlsplit(normalized)
        if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
            raise ValueError(
                "calendar_public_base_url must be an absolute HTTPS origin without userinfo"
            )
        if parsed.path not in {"", "/"} or parsed.query or parsed.fragment:
            raise ValueError("calendar_public_base_url must not contain a path, query or fragment")
        return normalized

    # ------------------------------------------------------------------ #
    # Wave 2 fail-closed configuration gate (SAATHI-123 / SAATHI-127)
    # ------------------------------------------------------------------ #
    @model_validator(mode="after")
    def validate_wave2_configuration(self) -> "Settings":
        """Refuse to construct Settings when Wave 2 could only degrade silently.

        Fail-closed rules, all enforced regardless of ``app_env`` because
        SELECTING a real provider is an explicit deployment act — a razorpay
        deployment with no keys must not boot and then answer "payment
        unavailable" on every checkout, and a livekit deployment with no API
        secret must not boot and then be unable to mint a join credential:

        * ``payment_provider='razorpay'`` REQUIRES ``razorpay_key_id`` and
          ``razorpay_key_secret``, both non-placeholder;
        * ``video_provider='livekit'`` REQUIRES ``livekit_url``,
          ``livekit_api_key`` and ``livekit_api_secret``, same treatment — and
          ``livekit_url`` must be an ``http://``/``https://`` URL WITH A HOST,
          because the adapter reaches the room service over HTTP. A ``wss://``
          value used to satisfy every check here and then fail every
          ``revoke_participant``/``close_room`` at runtime as
          ``PROVIDER_UNREACHABLE``; that is now a refusal to boot (see
          ``_livekit_url_problem``);
        * ``booking_hold_minutes``, ``join_credential_ttl_seconds``, the three
          rate limits, ``refund_free_cancel_hours`` and
          ``tutoring_default_session_price_paise`` must be STRICTLY POSITIVE
          integers (a zero TTL would mint dead credentials; a zero hold window
          would expire every booking instantly; a zero default price would make
          every unpriced tutor free by accident, which is exactly the
          client-authoritative-amount defect this gate exists to stop);
        * ``reminder_offsets`` must be a non-empty list drawn from
          ``REMINDER_OFFSET_CHOICES`` — an unknown offset is rejected here rather
          than violating ``ck_session_reminder_jobs_offset_kind`` at write time.

        Raises :class:`ConfigurationError` naming ONLY the offending setting.
        ``ConfigurationError`` is a ``RuntimeError``, so it propagates out of
        ``Settings(...)`` unwrapped and cannot be mistaken for a field-level
        validation problem — and no secret VALUE is ever interpolated into it.
        """
        problems: list[str] = []

        payment_provider = (self.payment_provider or "").strip().lower()
        if payment_provider not in PAYMENT_PROVIDER_CHOICES:
            problems.append(
                "payment_provider must be one of "
                f"{', '.join(PAYMENT_PROVIDER_CHOICES)}"
            )
        elif payment_provider == "razorpay":
            for name in ("razorpay_key_id", "razorpay_key_secret"):
                if _is_placeholder_secret(getattr(self, name)):
                    problems.append(
                        f"{name} is required (and must not be a placeholder) "
                        "when payment_provider='razorpay'"
                    )

        video_provider = (self.video_provider or "").strip().lower()
        environment = (self.app_env or "").strip().lower()
        if video_provider not in VIDEO_PROVIDER_CHOICES:
            problems.append(
                f"video_provider must be one of {', '.join(VIDEO_PROVIDER_CHOICES)}"
            )
        elif video_provider == "livekit":
            url_problem = _livekit_url_problem(self.livekit_url)
            if url_problem is not None:
                problems.append(url_problem)
            for name in ("livekit_api_key", "livekit_api_secret"):
                if _is_placeholder_secret(getattr(self, name)):
                    problems.append(
                        f"{name} is required (and must not be a placeholder) "
                        "when video_provider='livekit'"
                    )
            if self.video_calls_enabled:
                public_problem = _livekit_public_url_problem(
                    self.livekit_public_url,
                    production=environment in {"staging", "production"},
                )
                if public_problem is not None:
                    problems.append(public_problem)
        elif video_provider == "deterministic" and environment in {"staging", "production"}:
            problems.append(
                "video_provider='deterministic' is forbidden in staging/production"
            )

        if self.video_calls_enabled and video_provider == "none":
            problems.append(
                "video_provider must be deterministic or livekit when "
                "video_calls_enabled=true"
            )

        ice_policy = (self.video_ice_transport_policy or "").strip().lower()
        if ice_policy not in VIDEO_ICE_TRANSPORT_POLICY_CHOICES:
            problems.append(
                "video_ice_transport_policy must be one of "
                f"{', '.join(VIDEO_ICE_TRANSPORT_POLICY_CHOICES)}"
            )

        for name in (
            "booking_hold_minutes",
            "join_credential_ttl_seconds",
            "rate_limit_tutor_search_per_min",
            "rate_limit_booking_per_min",
            "rate_limit_review_per_hour",
            "refund_free_cancel_hours",
            "tutoring_default_session_price_paise",
        ):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
                problems.append(f"{name} must be a strictly positive integer")

        offsets = self.reminder_offsets
        if not isinstance(offsets, list) or not offsets:
            problems.append("reminder_offsets must be a non-empty list")
        else:
            unknown = sorted(
                {
                    str(offset).strip()
                    for offset in offsets
                    if str(offset).strip() not in REMINDER_OFFSET_CHOICES
                }
            )
            if unknown:
                problems.append(
                    "reminder_offsets contains unknown offsets "
                    f"({', '.join(unknown)}); allowed: "
                    f"{', '.join(REMINDER_OFFSET_CHOICES)}"
                )

        if problems:
            raise ConfigurationError(
                "Wave 2 configuration is invalid; refusing to start: "
                + "; ".join(problems)
            )
        return self

    @model_validator(mode="after")
    def validate_wave4_configuration(self) -> "Settings":
        """Fail closed on unsafe private-reporting deployment settings.

        Public labels cannot be enabled in this release build.  Making the
        process refuse to boot is stronger than relying on a UI toggle and
        prevents an operator typo from exposing an unapproved projection.
        """
        problems: list[str] = []
        for name in (
            "internship_report_max_file_bytes",
            "internship_report_max_evidence_files",
            "internship_risk_min_distinct_reporters",
            "internship_risk_window_months",
            "internship_risk_public_count_suppression",
            "internship_response_token_rate_per_minute",
            "internship_response_ip_rate_per_minute",
            "internship_identity_access_ttl_minutes",
        ):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
                problems.append(f"{name} must be a strictly positive integer")
        if (
            self.internship_risk_public_count_suppression
            < self.internship_risk_min_distinct_reporters
        ):
            problems.append(
                "internship_risk_public_count_suppression must be at least "
                "internship_risk_min_distinct_reporters"
            )
        if self.internship_report_scanner_provider not in {"deterministic", "clamav"}:
            problems.append(
                "internship_report_scanner_provider must be deterministic or clamav"
            )
        if self.internship_report_clamav_port <= 0 or self.internship_report_clamav_port > 65535:
            problems.append("internship_report_clamav_port must be between 1 and 65535")
        if self.internship_report_clamav_timeout_seconds <= 0:
            problems.append("internship_report_clamav_timeout_seconds must be positive")
        if (self.app_env or "").strip().lower() in {"production", "prod", "staging", "stage"} \
                and self.internship_report_scanner_provider != "clamav":
            problems.append(
                "internship_report_scanner_provider must be clamav in staging/production"
            )
        if not (self.internship_report_consent_version or "").strip():
            problems.append("internship_report_consent_version must not be empty")
        if self.internship_response_notification_provider not in {"none", "deterministic"}:
            problems.append(
                "internship_response_notification_provider must be none or deterministic"
            )
        response_base = urlsplit(self.internship_response_public_base_url)
        if (
            response_base.scheme not in {"http", "https"}
            or not response_base.hostname
            or response_base.username
            or response_base.password
            or response_base.query
            or response_base.fragment
            or not response_base.path.rstrip("/").endswith("/s-89")
        ):
            problems.append(
                "internship_response_public_base_url must be an absolute S-89 URL without credentials, query or fragment"
            )
        environment = (self.app_env or "").strip().casefold()
        if environment not in {"test", "testing", "development", "dev", "local"} \
                and self.internship_response_notification_provider != "none":
            problems.append(
                "internship_response_notification_provider must be none outside local/test"
            )
        if environment not in {"test", "testing", "development", "dev", "local"} \
                and response_base.scheme != "https":
            problems.append(
                "internship_response_public_base_url must use HTTPS outside local/test"
            )
        if self.internship_risk_labels_enabled:
            problems.append(
                "internship_risk_labels_enabled must remain false until "
                "counsel/security approval and all target-runtime gates pass"
            )
        if self.internship_risk_min_distinct_reporters < 3:
            problems.append(
                "internship_risk_min_distinct_reporters must be at least 3"
            )
        if not 1 <= self.internship_risk_window_months <= 24:
            problems.append(
                "internship_risk_window_months must be between 1 and 24"
            )
        if (
            self.internship_risk_public_count_suppression < 5
            or self.internship_risk_public_count_suppression
            < self.internship_risk_min_distinct_reporters
        ):
            problems.append(
                "internship_risk_public_count_suppression must be at least 5 "
                "and not less than internship_risk_min_distinct_reporters"
            )
        if self.wave4_gate_allow_publication_test:
            environment = (self.app_env or "").strip().casefold()
            test_url = (self.test_database_url or "").strip()
            actual_url = (self.database_url or "").strip()
            if environment not in {"test", "testing"}:
                problems.append(
                    "wave4_gate_allow_publication_test is allowed only in testing"
                )
            if not is_isolated_wave4_database_url(actual_url):
                problems.append(
                    "wave4_gate_allow_publication_test requires an isolated test/qa DATABASE_URL"
                )
            if not test_url or test_url != actual_url:
                problems.append(
                    "wave4_gate_allow_publication_test requires TEST_DATABASE_URL to equal DATABASE_URL"
                )
            for name in (
                "wave4_security_approval_ref",
                "wave4_policy_approval_ref",
                "wave4_target_runtime_gate_ref",
            ):
                value = (getattr(self, name) or "").strip()
                if not value.startswith("QA-"):
                    problems.append(f"{name} requires an explicit QA-only reference")
        if problems:
            raise ConfigurationError(
                "Wave 4 configuration is invalid; refusing to start: "
                + "; ".join(problems)
            )
        return self

    @model_validator(mode="after")
    def validate_wave5_configuration(self) -> "Settings":
        value = self.calendar_export_token_ttl_days
        if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= 365:
            raise ConfigurationError(
                "calendar_export_token_ttl_days must be an integer between 1 and 365"
            )
        environment = (self.app_env or "").strip().casefold()
        local_environments = {"development", "dev", "local", "test", "testing"}
        parsed = urlsplit(self.calendar_public_base_url)
        hostname = (parsed.hostname or "").casefold()
        loopback = hostname == "localhost"
        try:
            address = ip_address(hostname)
            loopback = loopback or address.is_loopback or address.is_unspecified
        except ValueError:
            pass
        if environment not in local_environments and loopback:
            raise ConfigurationError(
                "calendar_public_base_url must use a non-loopback public HTTPS origin "
                "outside local/test environments"
            )
        return self

    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )


def has_secret(secret: SecretStr | None) -> bool:
    return bool(secret and secret.get_secret_value())


settings = Settings()
