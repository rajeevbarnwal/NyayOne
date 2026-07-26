from pydantic import SecretStr
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

    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )


def has_secret(secret: SecretStr | None) -> bool:
    return bool(secret and secret.get_secret_value())


settings = Settings()
