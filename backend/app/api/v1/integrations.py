from fastapi import APIRouter

from app.core.config import has_secret, settings

router = APIRouter(prefix="/integrations", tags=["integrations"])


@router.get("/status")
def integration_status() -> dict[str, object]:
    return {
        "github": {
            "repository": settings.github_repository,
            "repo_url": settings.github_repo_url,
            "api_url": f"https://api.github.com/repos/{settings.github_repository}",
            "token_configured": has_secret(settings.github_token),
        },
        "jira": {
            "base_url": settings.jira_base_url,
            "project_key": settings.jira_project_key,
            "board_id": settings.jira_board_id,
            "project_api_url": f"{settings.jira_base_url.rstrip('/')}/rest/api/3/project/{settings.jira_project_key}",
            "board_api_url": f"{settings.jira_base_url.rstrip('/')}/rest/agile/1.0/board/{settings.jira_board_id}",
            "credentials_configured": bool(settings.jira_email) and has_secret(settings.jira_api_token),
        },
    }
