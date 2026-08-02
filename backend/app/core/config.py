from urllib.parse import urlsplit

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
#: Wave 2 provider bindings that the code can actually honour.
PAYMENT_PROVIDER_CHOICES = ("deterministic", "razorpay", "none")
VIDEO_PROVIDER_CHOICES = ("deterministic", "livekit", "none")
VIDEO_ICE_TRANSPORT_POLICY_CHOICES = ("all", "relay")
#: The only reminder offsets ``session_reminder_jobs.offset_kind`` accepts.
REMINDER_OFFSET_CHOICES = ("7d", "1d", "3h")


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
    app_name: str = "LegalSaathi"
    app_version: str = "0.1.0"
    app_env: str = "development"
    log_level: str = "INFO"
    # Optional JSONL file sink used by Logstash/Filebeat-style collectors.
    # Keep stdout JSON logging enabled; this adds a second local file handler.
    log_file_path: str | None = None

    # CORS: frontend dev server runs on 1030 (LegalSaathi local dev port range 1030-1049)
    cors_origins: list[str] = ["http://localhost:1030", "http://127.0.0.1:1030"]

    # --- Database (Postgres + pgvector; host port 1032 -> container 5432) ---
    # Default targets the local docker-compose Postgres. Override via DATABASE_URL.
    database_url: str = "postgresql+psycopg://legalsaathi:legalsaathi@localhost:1032/legalsaathi"
    # Optional separate URL used by the test suite; when unset, tests use SQLite in-memory.
    test_database_url: str | None = None
    db_pool_size: int = 5
    db_max_overflow: int = 10
    db_echo: bool = False

    # --- Worker / broker (Valkey-preferred; host port 1033) ---
    # Broker URL for the worker; Valkey is the default (BSD, Redis-compatible).
    # No Redis-specific product assumptions. Not connected in the foundation stage.
    worker_broker_url: str = "valkey://localhost:1033/0"
    worker_max_attempts: int = 3
    worker_base_delay_s: float = 0.5
    worker_backoff_factor: float = 2.0

    # --- Config-ready placeholders (declared here, not wired in the foundation tickets) ---
    # Cache / queue broker. Valkey is the default (BSD-licensed, Redis-compatible); host port 1033
    valkey_url: str | None = None
    # Object storage: S3-compatible abstraction. Local default SeaweedFS S3 API on host port 1035
    storage_endpoint_url: str | None = None
    storage_bucket: str | None = None
    storage_access_key: SecretStr | None = None
    storage_secret_key: SecretStr | None = None
    # Internal LLM Gateway fronting local open-weight inference (Ollama dev, vLLM prod); host port 1037
    llm_gateway_url: str | None = None

    # Existing integrations
    github_repository: str = "rajeevbarnwal/legalsaathi"
    github_repo_url: str = "https://github.com/rajeevbarnwal/legalsaathi"
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
    credential_storage_root: str = "/tmp/legalsaathi_credential_storage"
    credential_scanner_provider: str = "deterministic"
    credential_public_base_url: str = "https://localhost:1030/verify"
    retention_days_credential_audit: int | None = None
    retention_days_credential_evidence: int | None = None

    # --- Wave 4 private internship reporting (SAATHI-269 / SAATHI-450) ----
    internship_report_max_file_bytes: int = 5 * 1024 * 1024
    internship_report_max_evidence_files: int = 5
    internship_report_storage_root: str = "/tmp/legalsaathi_internship_report_storage"
    internship_report_scanner_provider: str = "deterministic"
    internship_report_clamav_host: str = "127.0.0.1"
    internship_report_clamav_port: int = 3310
    internship_report_clamav_timeout_seconds: float = 10.0
    internship_report_consent_version: str = "internship-report-v1"
    retention_days_internship_report_evidence: int | None = None
    # Product approval W4-PRODUCT-APPROVAL-20260801 permits implementation but
    # explicitly forbids activation until counsel/security + target gates pass.
    internship_risk_labels_enabled: bool = False
    # Approved SAATHI-452 internal aggregation defaults. These values may build
    # a privacy-safe candidate but never enable a public projection.
    internship_risk_min_distinct_reporters: int = 3
    internship_risk_window_months: int = 24
    internship_risk_public_count_suppression: int = 5

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

    # --- Student OTP login + cookie session --------------------------------
    # Login challenges remain separate from signup/recovery challenges. The
    # browser receives only an HttpOnly cookie; the database stores its hash.
    auth_session_cookie_name: str = "legalsaathi_session"
    auth_session_ttl_seconds: int = 7 * 24 * 60 * 60
    login_attempt_ttl_seconds: int = 10 * 60

    # --- DPDP retention / deletion (SAATHI-366 C5) -------------------------
    # Config-driven retention windows per data category, in days. NO statutory
    # duration is hard-coded: unset (None) means "retain until explicit erasure"
    # and the purge job is a no-op for that category. Operators set these to the
    # value their counsel approves.
    retention_days_registration_pending: int | None = None
    retention_days_registration_inactive: int | None = None
    retention_days_otp_challenge: int | None = None
    retention_days_recovery_session: int | None = None
    retention_days_audit_events: int | None = None
    # Whether the purge job anonymises (keep row, scrub PII/ciphertext) or hard
    # deletes when a window elapses. "anonymise" is the DPDP-safe default.
    retention_mode: str = "anonymise"

    jira_base_url: str = "https://legalsaathi.atlassian.net"
    jira_project_key: str = "SAATHI"
    jira_board_id: int = 2
    jira_email: str | None = None
    jira_api_token: SecretStr | None = None

    @field_validator("credential_public_base_url")
    @classmethod
    def validate_credential_public_base_url(cls, value: str) -> str:
        normalized = value.rstrip("/")
        if not normalized.startswith("https://") or not normalized.endswith("/verify"):
            raise ValueError(
                "credential_public_base_url must be an HTTPS URL ending in /verify"
            )
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
        if self.internship_risk_labels_enabled:
            problems.append(
                "internship_risk_labels_enabled must remain false until "
                "counsel/security approval and all target-runtime gates pass"
            )
        if problems:
            raise ConfigurationError(
                "Wave 4 configuration is invalid; refusing to start: "
                + "; ".join(problems)
            )
        return self

    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )


def has_secret(secret: SecretStr | None) -> bool:
    return bool(secret and secret.get_secret_value())


settings = Settings()
