from pydantic import SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


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

    # --- Wave 2 tutoring marketplace (SAATHI-123 / SAATHI-127) -------------
    # Booking hold TTL: how long a slot stays reserved while the student pays.
    booking_hold_minutes: int = 10
    # Payment provider binding. "deterministic" is the in-process, no-network
    # adapter used by dev/test; "razorpay" requires the key pair below.
    payment_provider: str = "deterministic"
    razorpay_key_id: SecretStr | None = None
    razorpay_key_secret: SecretStr | None = None
    # Video provider binding. "deterministic" issues local, hashed join grants;
    # "livekit" requires the URL + API key pair below.
    video_provider: str = "deterministic"
    livekit_url: str | None = None
    livekit_api_key: SecretStr | None = None
    livekit_api_secret: SecretStr | None = None
    # Join credential lifetime. Short-lived by design; only the hash is stored.
    join_credential_ttl_seconds: int = 300
    # Abuse limits (per identity) for the Wave 2 surfaces.
    rate_limit_tutor_search_per_min: int = 60
    rate_limit_booking_per_min: int = 10
    rate_limit_review_per_hour: int = 5
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

    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )


def has_secret(secret: SecretStr | None) -> bool:
    return bool(secret and secret.get_secret_value())


settings = Settings()
