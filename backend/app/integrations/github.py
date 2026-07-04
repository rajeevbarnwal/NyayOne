from typing import Any

import httpx
from pydantic import SecretStr

from app.core.config import settings


class GitHubClient:
    def __init__(
        self,
        repository: str | None = None,
        token: SecretStr | str | None = None,
    ) -> None:
        self.repository = repository or settings.github_repository
        raw_token = token if token is not None else settings.github_token
        self.token = raw_token.get_secret_value() if isinstance(raw_token, SecretStr) else raw_token

    @property
    def repository_url(self) -> str:
        return f"https://api.github.com/repos/{self.repository}"

    def _headers(self) -> dict[str, str]:
        headers = {
            "Accept": "application/vnd.github+json",
            "User-Agent": "LegalSaathi",
        }
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        return headers

    async def get_repository(self) -> dict[str, Any]:
        async with httpx.AsyncClient(timeout=20) as client:
            response = await client.get(self.repository_url, headers=self._headers())
            response.raise_for_status()
            return response.json()
