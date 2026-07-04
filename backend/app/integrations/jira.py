from typing import Any

import httpx
from pydantic import SecretStr

from app.core.config import settings


class JiraConfigurationError(RuntimeError):
    pass


class JiraClient:
    def __init__(
        self,
        base_url: str | None = None,
        email: str | None = None,
        api_token: SecretStr | str | None = None,
    ) -> None:
        self.base_url = (base_url or settings.jira_base_url).rstrip("/")
        self.email = email if email is not None else settings.jira_email
        raw_token = api_token if api_token is not None else settings.jira_api_token
        self.api_token = raw_token.get_secret_value() if isinstance(raw_token, SecretStr) else raw_token

    def _auth(self) -> httpx.BasicAuth:
        if not self.email or not self.api_token:
            raise JiraConfigurationError("JIRA_EMAIL and JIRA_API_TOKEN are required for Jira API access.")
        return httpx.BasicAuth(self.email, self.api_token)

    async def get_project(self, project_key: str | None = None) -> dict[str, Any]:
        key = project_key or settings.jira_project_key
        url = f"{self.base_url}/rest/api/3/project/{key}"
        async with httpx.AsyncClient(timeout=20) as client:
            response = await client.get(url, auth=self._auth(), headers={"Accept": "application/json"})
            response.raise_for_status()
            return response.json()

    async def get_board(self, board_id: int | None = None) -> dict[str, Any]:
        resolved_board_id = board_id or settings.jira_board_id
        url = f"{self.base_url}/rest/agile/1.0/board/{resolved_board_id}"
        async with httpx.AsyncClient(timeout=20) as client:
            response = await client.get(url, auth=self._auth(), headers={"Accept": "application/json"})
            response.raise_for_status()
            return response.json()
