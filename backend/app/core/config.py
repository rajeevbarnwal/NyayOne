from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "LegalSaathi"
    app_env: str = "development"
    cors_origins: list[str] = ["http://localhost:5173"]

    github_repository: str = "rajeevbarnwal/legalsaathi"
    github_repo_url: str = "https://github.com/rajeevbarnwal/legalsaathi"
    github_token: SecretStr | None = None

    jira_base_url: str = "https://legalsaathi.atlassian.net"
    jira_project_key: str = "SAATHI"
    jira_board_id: int = 2
    jira_email: str | None = None
    jira_api_token: SecretStr | None = None

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")


def has_secret(secret: SecretStr | None) -> bool:
    return bool(secret and secret.get_secret_value())


settings = Settings()
