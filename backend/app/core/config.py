from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # Application
    app_name: str = "LegalSaathi"
    app_version: str = "0.1.0"
    app_env: str = "development"
    log_level: str = "INFO"

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
