#!/usr/bin/env python3
"""Check configured GitHub and Jira API access for LegalSaathi.

This script uses only the Python standard library so it can run before backend
dependencies are installed. It reads `.env` if present, then falls back to the
current shell environment.
"""

from __future__ import annotations

import base64
import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def load_dotenv() -> None:
    env_path = ROOT / ".env"
    if not env_path.exists():
        return

    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def request_json(url: str, headers: dict[str, str]) -> tuple[int, object]:
    request = urllib.request.Request(url, headers=headers, method="GET")
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            body = response.read().decode("utf-8")
            return response.status, json.loads(body) if body else {}
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        try:
            payload: object = json.loads(body) if body else {}
        except json.JSONDecodeError:
            payload = body
        return exc.code, payload


def basic_auth_header(email: str, token: str) -> str:
    encoded = base64.b64encode(f"{email}:{token}".encode("utf-8")).decode("ascii")
    return f"Basic {encoded}"


def check_github() -> int:
    repository = os.getenv("GITHUB_REPOSITORY", "rajeevbarnwal/legalsaathi")
    token = os.getenv("GITHUB_TOKEN", "")
    headers = {"Accept": "application/vnd.github+json", "User-Agent": "LegalSaathi"}
    if token:
        headers["Authorization"] = f"Bearer {token}"

    status, payload = request_json(f"https://api.github.com/repos/{repository}", headers)
    print(f"GitHub {repository}: HTTP {status}")
    if isinstance(payload, dict) and payload.get("full_name"):
        print(f"  full_name: {payload['full_name']}")
        print(f"  private: {payload.get('private')}")
        print(f"  default_branch: {payload.get('default_branch')}")
    return 0 if status == 200 else 1


def check_jira() -> int:
    base_url = os.getenv("JIRA_BASE_URL", "https://legalsaathi.atlassian.net").rstrip("/")
    project_key = os.getenv("JIRA_PROJECT_KEY", "SAATHI")
    board_id = os.getenv("JIRA_BOARD_ID", "2")
    email = os.getenv("JIRA_EMAIL", "")
    token = os.getenv("JIRA_API_TOKEN", "")

    if not email or not token:
        print("Jira: skipped, set JIRA_EMAIL and JIRA_API_TOKEN in .env to verify API access.")
        return 1

    headers = {
        "Accept": "application/json",
        "Authorization": basic_auth_header(email, token),
    }
    project_status, project_payload = request_json(f"{base_url}/rest/api/3/project/{project_key}", headers)
    board_status, board_payload = request_json(f"{base_url}/rest/agile/1.0/board/{board_id}", headers)

    print(f"Jira project {project_key}: HTTP {project_status}")
    if isinstance(project_payload, dict) and project_payload.get("key"):
        print(f"  name: {project_payload.get('name')}")
        print(f"  key: {project_payload.get('key')}")

    print(f"Jira board {board_id}: HTTP {board_status}")
    if isinstance(board_payload, dict) and board_payload.get("name"):
        print(f"  name: {board_payload.get('name')}")
        print(f"  type: {board_payload.get('type')}")

    return 0 if project_status == 200 and board_status == 200 else 1


def main() -> int:
    load_dotenv()
    github_result = check_github()
    jira_result = check_jira()
    return 0 if github_result == 0 and jira_result == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
