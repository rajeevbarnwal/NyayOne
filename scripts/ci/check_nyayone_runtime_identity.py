#!/usr/bin/env python3
"""Fail closed when NyayOne active runtime defaults drift to LegalSaathi.

This is intentionally a scoped operational policy, not a repository-wide word
ban. Historical migrations, traceability references, QA fixtures and the shared
Atlassian tenant remain legitimate. Active configuration, service metadata,
Compose resources and CI database identities do not.
"""

from __future__ import annotations

import argparse
import ast
import json
import re
import sys
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlsplit


ROOT = Path(__file__).resolve().parents[2]

EXPECTED_SETTINGS: dict[str, object] = {
    "app_name": "NyayOne",
    "database_url": (
        "postgresql+psycopg://nyayone:nyayone_dev_only@localhost:1132/nyayone"
    ),
    "worker_broker_url": "valkey://localhost:1133/0",
    "github_repository": "rajeevbarnwal/NyayOne",
    "github_repo_url": "https://github.com/rajeevbarnwal/NyayOne",
    "credential_storage_root": "/tmp/nyayone_credential_storage",
    "credential_public_base_url": "https://localhost:1130/verify",
    "internship_report_storage_root": "/tmp/nyayone_internship_report_storage",
    "internship_response_public_base_url": "https://localhost:1130/s-89",
    "calendar_public_base_url": "https://localhost:1130",
    "auth_session_cookie_name": "nyayone_session",
    "jira_base_url": "https://legalsaathi.atlassian.net",
    "jira_project_key": "NYAY",
    "jira_board_id": 68,
}

EXPECTED_ENV = {
    "BACKEND_PORT": "1131",
    "DATABASE_URL": (
        "postgresql+psycopg://nyayone:nyayone_dev_only@localhost:1132/nyayone"
    ),
    "VITE_API_BASE_URL": "http://localhost:1131",
    "VITE_APP_NAME": "NyayOne",
    "GITHUB_REPOSITORY": "rajeevbarnwal/NyayOne",
    "GITHUB_REPO_URL": "https://github.com/rajeevbarnwal/NyayOne",
    "JIRA_BASE_URL": "https://legalsaathi.atlassian.net",
    "JIRA_PROJECT_KEY": "NYAY",
    "JIRA_BOARD_ID": "68",
}

REQUIRED_OPERATIONAL_SNIPPETS = {
    "backend/app/api/v1/health.py": ('"service": "nyayone-backend"',),
    "backend/app/main.py": (
        'get_logger("nyayone.app")',
        '"service": "nyayone-backend"',
    ),
    "backend/app/core/middleware.py": ('get_logger("nyayone.request")',),
    "backend/app/core/exceptions.py": ('get_logger("nyayone.error")',),
    "backend/app/api/v1/tutoring.py": ('get_logger("nyayone.tutoring.api")',),
    "backend/app/workers/entrypoint.py": ('get_logger("nyayone.worker")',),
    "backend/app/integrations/github.py": ('"User-Agent": "NyayOne"',),
    "backend/app/integrations/storage.py": (
        '"http://localhost:1135"',
        'root or "/tmp/nyayone_storage"',
    ),
    "backend/app/services/otp_sender.py": ("Your NyayOne verification code",),
    "backend/app/services/providers/payment_provider.py": (
        'b"nyayone-deterministic-payment-test-key"',
    ),
    "backend/app/services/providers/video_provider.py": (
        'b"nyayone-deterministic-video-test-key"',
    ),
    "Logs/logstash/pipeline/logstash.conf": (
        'id => "nyayone-backend-jsonl"',
        '"service" => "nyayone-backend"',
    ),
    "scripts/check_integrations.py": (
        '"rajeevbarnwal/NyayOne"',
        '"User-Agent": "NyayOne"',
        '"NYAY"',
        '"68"',
    ),
    "scripts/render_video_infra_config.py": ("NYAYONE-VIDEO-MODE",),
    "frontend/src/lib/apiClient.ts": ("http://localhost:1131",),
    "frontend/vite.config.ts": ("port: 1130",),
    "frontend/scripts/wave4-moderation-e2e.mjs": ("'nyayone_session'",),
    "frontend/scripts/wave4-risk-labels-e2e.mjs": ("'nyayone_session'",),
    "frontend/scripts/wave5-calendar-real-e2e.mjs": ("'nyayone_session'",),
    "frontend/scripts/saathi60-internship-real-e2e.mjs": (
        "cookie.name === 'nyayone_session'",
    ),
    "README.md": ("# NyayOne", "`rajeevbarnwal/NyayOne`", "board `68`"),
    "backend/README.md": ("# NyayOne Backend", "localhost:1131", "localhost:1132/nyayone"),
    "frontend/README.md": ("# NyayOne Frontend", "localhost:1130"),
    "Logs/README.md": ("# NyayOne Logging", "localhost:1138"),
    "docs/integrations/github-jira.md": (
        "`rajeevbarnwal/NyayOne`",
        "Jira project key: `NYAY`",
        "Jira board ID: `68`",
    ),
    "docs/operations/nyayone-runtime-isolation.md": (
        "NyayOne starts with its own empty PostgreSQL volume",
        "The historical public-organisation UUID namespace remains unchanged",
        "Frontend package IDs, Capacitor application IDs",
    ),
}

FORBIDDEN_ACTIVE_PATTERNS = (
    re.compile(r'get_logger\(["\']legalsaathi', re.IGNORECASE),
    re.compile(r'logging\.getLogger\(["\']legalsaathi', re.IGNORECASE),
    re.compile(r'User-Agent["\']?\s*[:=]\s*["\']LegalSaathi', re.IGNORECASE),
    re.compile(r"Your LegalSaathi verification code", re.IGNORECASE),
    re.compile(r"/tmp/legalsaathi(?:_|/)", re.IGNORECASE),
    re.compile(r"legalsaathi-deterministic-(?:payment|video)-test-key", re.IGNORECASE),
    re.compile(r"LEGALSAATHI-VIDEO-MODE", re.IGNORECASE),
)

WORKFLOW_LEGACY_DB_PATTERNS = (
    re.compile(r"POSTGRES_USER:\s*legalsaathi\s*$", re.MULTILINE | re.IGNORECASE),
    re.compile(r"POSTGRES_PASSWORD:\s*legalsaathi\s*$", re.MULTILINE | re.IGNORECASE),
    re.compile(r"POSTGRES_DB:\s*legalsaathi(?:[_a-z0-9-]*)?\s*$", re.MULTILINE | re.IGNORECASE),
    re.compile(r"://legalsaathi:legalsaathi@", re.IGNORECASE),
    re.compile(r"PGPASSWORD=legalsaathi\b", re.IGNORECASE),
    re.compile(r"(?:^|\s)-U\s+legalsaathi\b", re.IGNORECASE),
)

REQUIRED_DB_WORKFLOW_SERVICES = {
    "registration-db-gate.yml": 1,
    "wave1-foundation-gate.yml": 1,
    "wave2-tutoring-db-gate.yml": 1,
    "wave3-credential-trust-gate.yml": 1,
    "wave4-private-reporting-gate.yml": 1,
    "wave5-calendar-gate.yml": 2,
}


def _settings_defaults(path: Path) -> dict[str, object]:
    module = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    for node in module.body:
        if isinstance(node, ast.ClassDef) and node.name == "Settings":
            values: dict[str, object] = {}
            for item in node.body:
                if not isinstance(item, ast.AnnAssign) or not isinstance(item.target, ast.Name):
                    continue
                try:
                    values[item.target.id] = ast.literal_eval(item.value)
                except (TypeError, ValueError):
                    continue
            return values
    raise ValueError("Settings class not found")


def parse_env(text: str) -> dict[str, str]:
    values: dict[str, str] = {}
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        name, value = line.split("=", 1)
        values[name.strip()] = value.strip()
    return values


def check_env_text(text: str, *, label: str = ".env.example") -> list[str]:
    values = parse_env(text)
    failures = [
        f"{label}: {name} must use the NyayOne default"
        for name, expected in EXPECTED_ENV.items()
        if values.get(name) != expected
    ]
    expected_cors = '["http://localhost:1130","http://127.0.0.1:1130"]'
    if values.get("CORS_ORIGINS") != expected_cors:
        failures.append(f"{label}: CORS_ORIGINS must use NyayOne host port 1130")
    return failures


def check_workflow_text(text: str, *, label: str) -> list[str]:
    failures: list[str] = []
    for pattern in WORKFLOW_LEGACY_DB_PATTERNS:
        if pattern.search(text):
            failures.append(f"{label}: legacy PostgreSQL identity is forbidden")
            break
    postgres_users = re.findall(
        r"^\s*POSTGRES_USER:\s*([^\s#]+)", text, re.MULTILINE
    )
    if any(value != "nyayone_ci" for value in postgres_users):
        failures.append(f"{label}: POSTGRES_USER must be nyayone_ci")
    postgres_passwords = re.findall(
        r"^\s*POSTGRES_PASSWORD:\s*([^\s#]+)", text, re.MULTILINE
    )
    if any(value != "nyayone_ci_ephemeral" for value in postgres_passwords):
        failures.append(f"{label}: POSTGRES_PASSWORD must be ephemeral NyayOne CI")
    postgres_databases = re.findall(
        r"^\s*POSTGRES_DB:\s*([^\s#]+)", text, re.MULTILINE
    )
    if any(not re.fullmatch(r"nyayone(?:[_a-z0-9-]*)", value) for value in postgres_databases):
        failures.append(f"{label}: POSTGRES_DB must use a NyayOne CI identity")
    required_services = REQUIRED_DB_WORKFLOW_SERVICES.get(Path(label).name)
    if required_services is not None:
        for key, values in (
            ("POSTGRES_USER", postgres_users),
            ("POSTGRES_PASSWORD", postgres_passwords),
            ("POSTGRES_DB", postgres_databases),
        ):
            if len(values) != required_services:
                failures.append(
                    f"{label}: {key} must appear in {required_services} PostgreSQL service(s)"
                )
        nyayone_database_urls = re.findall(
            r"postgresql\+psycopg://nyayone_ci:nyayone_ci_ephemeral@"
            r"[^/\s]+/nyayone(?:[_a-z0-9-]*)",
            text,
        )
        if len(nyayone_database_urls) < required_services:
            failures.append(
                f"{label}: NyayOne PostgreSQL DATABASE_URL contract is missing"
            )
    return failures


def _is_active_source(relative: Path) -> bool:
    if "db/migrations" in relative.as_posix() or "rendered" in relative.parts:
        return False
    if relative.as_posix() in {
        "scripts/ci/check_nyayone_runtime_identity.py",
        "scripts/ci/test_ci_policies.py",
    }:
        return False
    if relative.suffix not in {".py", ".sh", ".mjs", ".yml", ".yaml", ".tmpl", ".example"}:
        return False
    return True


def check_active_source_text(relative: Path, text: str) -> list[str]:
    """Check one active source file while preserving explicit historical exclusions."""
    if not _is_active_source(relative):
        return []
    for pattern in FORBIDDEN_ACTIVE_PATTERNS:
        if pattern.search(text):
            return [f"{relative}: active legacy runtime identity is forbidden"]
    return []


def check_required_operational_text(relative: str, text: str) -> list[str]:
    return [
        f"{relative}: missing NyayOne operational identity"
        for snippet in REQUIRED_OPERATIONAL_SNIPPETS.get(relative, ())
        if snippet not in text
    ]


def _published_ports(service: dict[str, Any]) -> set[int]:
    ports: set[int] = set()
    for value in service.get("ports") or []:
        published: object | None = None
        if isinstance(value, dict):
            published = value.get("published")
        elif isinstance(value, str):
            published = value.split(":", 1)[0]
        if published is None:
            continue
        raw = str(published).split("/", 1)[0]
        if "-" in raw:
            low, high = raw.split("-", 1)
            ports.update(range(int(low), int(high) + 1))
        else:
            ports.add(int(raw))
    return ports


def check_compose_payload(payload: dict[str, Any], *, label: str) -> list[str]:
    failures: list[str] = []
    if payload.get("name") != "nyayone":
        failures.append(f"{label}: Compose project must be nyayone")
    services = payload.get("services") or {}
    legacy_service_names = sorted(
        name for name in services if "legalsaathi" in str(name).casefold()
    )
    if legacy_service_names:
        failures.append(f"{label}: legacy Compose service identity is forbidden")
    expected_ports = {
        "postgres": {1132},
        "backend": {1131},
        "frontend": {1130},
        "logstash": {1138},
    }
    for service_name, expected in expected_ports.items():
        service = services.get(service_name) or {}
        if _published_ports(service) != expected:
            failures.append(f"{label}: {service_name} host ports must be {sorted(expected)}")
    legacy_host_ports = sorted(
        {
            port
            for service in services.values()
            for port in _published_ports(service or {})
            if 1030 <= port <= 1049
        }
    )
    if legacy_host_ports:
        failures.append(f"{label}: legacy 1030-1049 host ports are forbidden")
    postgres_env = (services.get("postgres") or {}).get("environment") or {}
    for key, expected in {
        "POSTGRES_USER": "nyayone",
        "POSTGRES_PASSWORD": "nyayone_dev_only",
        "POSTGRES_DB": "nyayone",
    }.items():
        if postgres_env.get(key) != expected:
            failures.append(f"{label}: postgres {key} must use the NyayOne identity")
    backend_env = (services.get("backend") or {}).get("environment") or {}
    database_url = str(backend_env.get("DATABASE_URL") or "")
    try:
        parsed_database = urlsplit(database_url)
        database_contract_matches = (
            parsed_database.scheme in {"postgresql", "postgresql+psycopg"}
            and (parsed_database.hostname or "").casefold() == "postgres"
            and parsed_database.port == 5432
            and unquote(parsed_database.username or "") == "nyayone"
            and unquote(parsed_database.password or "") == "nyayone_dev_only"
            and unquote(parsed_database.path.lstrip("/")) == "nyayone"
            and not parsed_database.query
            and not parsed_database.fragment
        )
    except ValueError:
        database_contract_matches = False
    if not database_contract_matches:
        failures.append(f"{label}: backend must use the isolated Compose database")
    frontend_env = (services.get("frontend") or {}).get("environment") or {}
    if frontend_env.get("VITE_API_BASE_URL") != "http://localhost:1131":
        failures.append(f"{label}: frontend API origin must use NyayOne host port 1131")
    if frontend_env.get("VITE_APP_NAME") != "NyayOne":
        failures.append(f"{label}: frontend app identity must be NyayOne")
    volume_names = {
        str((definition or {}).get("name") or name)
        for name, definition in (payload.get("volumes") or {}).items()
    }
    if "nyayone_pgdata" not in volume_names:
        failures.append(f"{label}: NyayOne PostgreSQL volume is missing")
    if any("legalsaathi" in name.casefold() for name in volume_names):
        failures.append(f"{label}: legacy volume identity is forbidden")
    network_names = {
        str((definition or {}).get("name") or name)
        for name, definition in (payload.get("networks") or {}).items()
    }
    if any("legalsaathi" in name.casefold() for name in network_names):
        failures.append(f"{label}: legacy network identity is forbidden")
    return failures


def _check_compose_sources(root: Path) -> list[str]:
    failures: list[str] = []
    expected = {
        "docker-compose.yml": (
            "name: nyayone",
            '"1130:1030"',
            '"1131:1031"',
            '"1132:5432"',
            '"1138:9600"',
            "nyayone_pgdata",
        ),
        "infra/video/docker-compose.video.yml": (
            '"1139:7880"',
            '"1142:6789"',
            '"1143:3478/tcp"',
            '"1143:3478/udp"',
            '"21500-21549:21500-21549/udp"',
            "172.29.31.0/24",
        ),
        "infra/video/docker-compose.video.direct.yml": (
            '"1140:1140"',
            '"1141:1141/udp"',
        ),
    }
    for relative, snippets in expected.items():
        text = (root / relative).read_text(encoding="utf-8")
        for snippet in snippets:
            if snippet not in text:
                failures.append(f"{relative}: missing NyayOne Compose contract")
    return failures


def check(root: Path = ROOT) -> list[str]:
    failures: list[str] = []
    settings_path = root / "backend/app/core/config.py"
    try:
        defaults = _settings_defaults(settings_path)
    except (OSError, SyntaxError, ValueError) as error:
        failures.append(f"{settings_path.relative_to(root)}: cannot inspect Settings ({type(error).__name__})")
    else:
        for name, expected in EXPECTED_SETTINGS.items():
            if defaults.get(name) != expected:
                failures.append(f"backend/app/core/config.py: {name} must use the NyayOne default")

    failures.extend(check_env_text((root / ".env.example").read_text(encoding="utf-8")))
    failures.extend(_check_compose_sources(root))

    for relative, snippets in REQUIRED_OPERATIONAL_SNIPPETS.items():
        text = (root / relative).read_text(encoding="utf-8")
        failures.extend(check_required_operational_text(relative, text))

    active_roots = (
        root / "backend/app",
        root / "infra/video",
        root / "scripts",
    )
    for active_root in active_roots:
        for path in active_root.rglob("*"):
            if not path.is_file():
                continue
            relative = path.relative_to(root)
            if not _is_active_source(relative):
                continue
            text = path.read_text(encoding="utf-8")
            failures.extend(check_active_source_text(relative, text))

    workflows = root / ".github/workflows"
    for path in sorted(workflows.glob("*.y*ml")):
        failures.extend(check_workflow_text(path.read_text(encoding="utf-8"), label=str(path.relative_to(root))))
    return failures


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--compose-json", type=Path)
    args = parser.parse_args()
    failures = check(args.root.resolve())
    if args.compose_json:
        try:
            payload = json.loads(args.compose_json.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as error:
            failures.append(f"compose config: unreadable ({type(error).__name__})")
        else:
            failures.extend(check_compose_payload(payload, label="rendered compose config"))
    if failures:
        print("\n".join(failures), file=sys.stderr)
        return 1
    print("NyayOne runtime identity policy passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
