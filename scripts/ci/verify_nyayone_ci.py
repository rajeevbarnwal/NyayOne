#!/usr/bin/env python3
"""Fail-closed static policy checks for NyayOne GitHub Actions workflows."""

from __future__ import annotations

import ast
import hashlib
import json
import re
import sys
from pathlib import Path
from urllib.parse import urlsplit

try:
    import yaml
except ModuleNotFoundError:  # pragma: no cover - exercised by the CI bootstrap
    yaml = None


ROOT = Path(__file__).resolve().parents[2]
WORKFLOWS = ROOT / ".github" / "workflows"
DB_GATE = ROOT / "backend" / "scripts" / "db_gate.sh"
NYAY4_BROWSER_GATE = ROOT / "frontend" / "scripts" / "nyay4-otp-browser-negative.mjs"
NYAY4_BROWSER_CONTRACT = (
    ROOT / "frontend" / "scripts" / "lib" / "nyay4-otp-runner-contract.mjs"
)
NYAY19_BROWSER_GATE = (
    ROOT / "frontend" / "scripts" / "nyay19-auth-lifecycle-browser.mjs"
)
NYAY19_BROWSER_CONTRACT = (
    ROOT
    / "frontend"
    / "scripts"
    / "lib"
    / "nyay19-auth-lifecycle-runner-contract.mjs"
)
NYAY19_BROWSER_CONTRACT_TEST = (
    ROOT
    / "frontend"
    / "scripts"
    / "lib"
    / "nyay19-auth-lifecycle-runner-contract.test.mjs"
)
FRONTEND_PACKAGE = ROOT / "frontend" / "package.json"
EXPECTED_NYAY4_BROWSER_GATE_SHA256 = (
    "1920889d94816417792dcc9b5a7aa739869b34fcc8616f8c17df3359c58a45b9"
)
EXPECTED_NYAY4_BROWSER_CONTRACT_SHA256 = (
    "c45e97b73d2f180683fe890578fcaac877045f58bc005489c0f7a21939b35b38"
)
EXPECTED_NYAY4_PACKAGE_COMMAND = "node scripts/nyay4-otp-browser-negative.mjs"
EXPECTED_NYAY19_BROWSER_GATE_SHA256 = (
    "b334661270c52e407b6ca09cd4f2eaa5e150db8bb15671c7e911f2d1a63a91d5"
)
EXPECTED_NYAY19_BROWSER_CONTRACT_SHA256 = (
    "b026dec7d7e9eca408a8960bb497479587a604f3b3314b0aa12bd9d049ee5350"
)
EXPECTED_NYAY19_BROWSER_CONTRACT_TEST_SHA256 = (
    "7c81e2d4a6b11131539cabc230e62e399b08051f4ced703453a6b862f917ca83"
)
EXPECTED_NYAY19_PACKAGE_COMMAND = "node scripts/nyay19-auth-lifecycle-browser.mjs"
NYAY19_ISOLATED_MIGRATION_ENV = "NYAY19_ISOLATED_MIGRATION_EXECUTE"
EXPECTED_NYAY19_ALEMBIC_WORKFLOW_JOBS: dict[
    tuple[str, str], tuple[str, ...]
] = {
    ("registration-db-gate.yml", "postgres-16-pgvector"): (
        "bash scripts/db_gate.sh",
    ),
    ("wave1-foundation-gate.yml", "backend-postgres16-gate"): (
        "bash scripts/db_gate.sh",
        "python -m alembic upgrade head",
    ),
    ("wave2-tutoring-db-gate.yml", "wave2-postgres-16-pgvector"): (
        "bash scripts/wave2_db_gate.sh",
    ),
    ("wave3-credential-trust-gate.yml", "credential-trust-postgres-browser"): (
        "bash scripts/db_gate.sh",
    ),
    ("wave4-private-reporting-gate.yml", "private-reporting-postgres-browser"): (
        "bash scripts/wave4_db_gate.sh",
    ),
    ("wave5-calendar-gate.yml", "calendar-postgres"): (
        "python scripts/wave5_postgres_gate.py",
    ),
    ("wave5-calendar-gate.yml", "calendar-real-browser"): (
        "alembic upgrade head",
    ),
}
EXPECTED_NYAY19_ALEMBIC_PYTHON_CALLERS = {
    "backend/scripts/nyay2_postgres_authorization_gate.py",
    "backend/scripts/nyay3_postgres_characterization.py",
    "backend/scripts/nyay4_postgres_otp_gate.py",
    "backend/scripts/nyay16_postgres_gate.py",
    "backend/scripts/nyay17_postgres_idempotency_gate.py",
    "backend/scripts/nyay19_migrate.py",
    "backend/scripts/nyay19_postgres_auth_retention_gate.py",
    "backend/scripts/wave2_postgres_gate.py",
    "backend/scripts/wave4_postgres_gate.py",
    "backend/scripts/wave5_postgres_gate.py",
}
EXPECTED_NYAY19_ALEMBIC_SHELL_CALLERS = {
    "backend/scripts/db_gate.sh": "isolated-postgresql",
    "scripts/wave2_tutoring_browser_gate.sh": "local-sqlite",
}
NYAY19_ISOLATED_DATABASE_MARKERS = {
    "ci",
    "gate",
    "nyay2",
    "nyay3",
    "nyay4",
    "nyay16",
    "nyay17",
    "nyay19",
    "qa",
    "scratch",
    "test",
    "testing",
    "w2gate",
}
NYAY19_FORBIDDEN_DATABASE_MARKERS = {"prod", "production", "stage", "staging"}
NYAY19_ISOLATED_APP_ENVS = {
    "development",
    "dev",
    "local",
    "test",
    "testing",
    "stage",
    "staging",
}
EXPECTED_DB_GATE_SHA256 = "41065fdde2ff466444826a2e78b317bd953f2cbae4543102abc305911efbc7c3"
EXPECTED_NYAY16_DB_GATE_COMMAND = (
    'NYAY16_GATE_ALLOW_DATABASES=true "$PY" scripts/nyay16_postgres_gate.py '
    "--output test-results/nyay16-postgres/summary.json"
)
EXPECTED_NYAY3_DB_GATE_COMMAND = (
    '"$PY" scripts/nyay3_postgres_characterization.py '
    "--expect hardened --output test-results/nyay3-postgres/summary.json"
)
EXPECTED_NYAY2_DB_GATE_COMMAND = (
    '"$PY" scripts/nyay2_postgres_authorization_gate.py '
    "--report test-results/nyay2-postgres/summary.json"
)
EXPECTED_NYAY17_DB_GATE_COMMAND = (
    '"$PY" scripts/nyay17_postgres_idempotency_gate.py '
    "--report test-results/nyay17-postgres/summary.json"
)
EXPECTED_NYAY4_DB_GATE_COMMAND = (
    'NYAY4_POSTGRES_GATE=1 "$PY" scripts/nyay4_postgres_otp_gate.py '
    '--execute --database-url "$DATABASE_URL" '
    "--output test-results/nyay4-postgres/summary.json"
)
EXPECTED_NYAY19_DB_GATE_COMMAND = (
    'NYAY19_POSTGRES_GATE_EXECUTE=1 "$PY" '
    "scripts/nyay19_postgres_auth_retention_gate.py "
    '--execute --database-url "$DATABASE_URL" '
    "--output test-results/nyay19-postgres/summary.json"
)
ACTION_REF = re.compile(r"^\s*-?\s*uses:\s*([^\s#]+)", re.MULTILINE)
IMAGE_REF = re.compile(r"^\s*image:\s*([^\s#]+)", re.MULTILINE)
PINNED_ACTION = re.compile(r"^[^@\s]+@[0-9a-f]{40}$")
PINNED_IMAGE = re.compile(r"^[^@\s]+@sha256:[0-9a-f]{64}$")
PINNED_SETUP_NODE_ACTION = (
    "actions/setup-node@49933ea5288caeca8642d1e84afbd3f7d6820020"
)
EXPECTED_NYAY4_SETUP_NODE_WITH = {
    "node-version": "22",
    "cache": "npm",
    "cache-dependency-path": "frontend/package-lock.json",
}
ALLOWED_SERVICE_IMAGE_REFS = {
    "clamav/clamav@sha256:78810772a92b4a9168115bc6b2e0ffd702640893b9577f8c3d0432762d2655c4",
    "pgvector/pgvector@sha256:ccc6e83d6e35e931dc7c5def2022729d5a6c370318d099181995567ff1fb4d6b",
}
ALLOWED_RUNNERS = {"ubuntu-24.04"}
ALLOWED_ACTIONS = {
    "actions/checkout@11d5960a326750d5838078e36cf38b85af677262",
    PINNED_SETUP_NODE_ACTION,
    "actions/setup-python@a26af69be951a213d495a4c3e4e4022e16d87065",
    "actions/upload-artifact@ea165f8d65b6e75b540449e92b4886f43607fa02",
}
CANONICAL_WORKFLOW_FILES = {
    "nyayone-policy-gate.yml",
    "registration-db-gate.yml",
    "wave1-foundation-gate.yml",
    "wave2-tutoring-db-gate.yml",
    "wave3-credential-trust-gate.yml",
    "wave4-private-reporting-gate.yml",
    "wave5-calendar-gate.yml",
}
DANGEROUS_ENV_KEYS = {
    "BASH_ENV",
    "ENV",
    "GITHUB_ENV",
    "LD_AUDIT",
    "LD_LIBRARY_PATH",
    "LD_PRELOAD",
    "NODE_OPTIONS",
    "PATH",
    "PYTHONHOME",
    "PYTHONPATH",
    "RUBYOPT",
    "SHELLOPTS",
}
EXPECTED_UPLOAD_IF = (
    "${{ always() && steps.evidence_prepare.outcome == 'success' && "
    "steps.evidence_manifest.outcome == 'success' && "
    "steps.evidence_privacy.outcome == 'success' && "
    "steps.evidence_integrity.outcome == 'success' && "
    "steps.evidence_schema.outcome == 'success' }}"
)
EXPECTED_REQUIRED_RUN = """python - <<'PY'
import json, os, sys
results = {
    name: value["result"]
    for name, value in json.loads(os.environ["RESULTS"]).items()
}
print(results)
if not results or any(value != "success" for value in results.values()):
    sys.exit("one or more required jobs did not succeed")
PY"""
EXPECTED_NYAY19_START_RUN = (
    "(cd backend && python -m uvicorn app.main:app --host 127.0.0.1 --port 1181 "
    '> "$RUNNER_TEMP/nyay19-backend.log" 2>&1 &)\n'
    "(cd frontend && npm run dev -- --host 127.0.0.1 --port 1180 --strictPort "
    '> "$RUNNER_TEMP/nyay19-frontend.log" 2>&1 &)\n'
    "for url in \\\n"
    "  http://127.0.0.1:1181/health \\\n"
    "  http://127.0.0.1:1180; do\n"
    "  for attempt in {1..60}; do\n"
    '    curl --fail --silent "$url" >/dev/null && break\n'
    '    if [[ "$attempt" == 60 ]]; then\n'
    '      echo "Timed out waiting for $url"\n'
    "      exit 1\n"
    "    fi\n"
    "    sleep 1\n"
    "  done\n"
    "done\n"
)
EXPECTED_EXACT_STEPS: dict[tuple[str, str, str], dict[str, object]] = {
    (
        "wave3-credential-trust-gate.yml",
        "credential-trust-postgres-browser",
        "NYAY-4 OTP authority Chromium regression",
    ): {
        "name": "NYAY-4 OTP authority Chromium regression",
        "working-directory": "frontend",
        "env": {
            "NYAY4_WEB_BASE_URL": "http://127.0.0.1:1170",
            "NYAY4_API_BASE_URL": "http://127.0.0.1:1171",
            "NYAY4_OTP_CAPTURE_URL": "http://127.0.0.1:1099",
        },
        "run": "npm run qa:nyay4:otp-negative",
    },
    (
        "wave3-credential-trust-gate.yml",
        "credential-trust-postgres-browser",
        "Start NYAY-19 isolated auth lifecycle backend and frontend",
    ): {
        "name": "Start NYAY-19 isolated auth lifecycle backend and frontend",
        "env": {
            "APP_ENV": "test",
            "CORS_ORIGINS": '["http://127.0.0.1:1180"]',
            "OTP_DELIVERY_ENABLED": "true",
            "OTP_PROVIDER": "http",
            "OTP_PROVIDER_URL": "http://127.0.0.1:1099/send",
            "OTP_PROVIDER_SUPPORTS_IDEMPOTENCY": "true",
            "OTP_RESEND_COOLDOWN_SECONDS": "1",
            "OTP_FLOW_TTL_SECONDS": "600",
            "OTP_RECOVERY_PROOF_TTL_SECONDS": "300",
            "AUTH_SESSION_TTL_SECONDS": "20",
            "VITE_API_BASE_URL": "http://127.0.0.1:1181",
        },
        "run": EXPECTED_NYAY19_START_RUN,
    },
    (
        "wave3-credential-trust-gate.yml",
        "credential-trust-postgres-browser",
        "NYAY-19 authentication lifecycle Chromium regression",
    ): {
        "name": "NYAY-19 authentication lifecycle Chromium regression",
        "working-directory": "frontend",
        "env": {
            "NYAY19_WEB_BASE_URL": "http://127.0.0.1:1180",
            "NYAY19_API_BASE_URL": "http://127.0.0.1:1181",
            "NYAY19_OTP_CAPTURE_URL": "http://127.0.0.1:1099",
            "NYAY19_SESSION_TTL_SECONDS": "20",
            "NYAY19_OTP_RESEND_COOLDOWN_SECONDS": "1",
            "NYAY19_OTP_FLOW_TTL_SECONDS": "600",
            "NYAY19_RECOVERY_PROOF_TTL_SECONDS": "300",
        },
        "run": "npm run qa:nyay19:auth-lifecycle",
    },
}
EVIDENCE_CONTRACTS: dict[str, dict[str, tuple[str, str, str]]] = {
    "wave1-foundation-gate.yml": {
        "frontend-native": (
            "$RUNNER_TEMP/v34-s11-s26",
            "$RUNNER_TEMP/v34-s11-s26-uploadable",
            "wave1",
        ),
    },
    "wave2-tutoring-db-gate.yml": {
        "wave2-postgres-16-pgvector": (
            "$GITHUB_WORKSPACE/test-results",
            "$RUNNER_TEMP/wave2-uploadable",
            "wave2",
        ),
    },
    "wave3-credential-trust-gate.yml": {
        "credential-trust-postgres-browser": (
            "$GITHUB_WORKSPACE/test-results",
            "$RUNNER_TEMP/wave3-uploadable",
            "wave3",
        ),
    },
    "wave4-private-reporting-gate.yml": {
        "private-reporting-postgres-browser": (
            "$GITHUB_WORKSPACE/test-results",
            "$RUNNER_TEMP/wave4-uploadable",
            "wave4",
        ),
    },
    "wave5-calendar-gate.yml": {
        "calendar-postgres": (
            "$GITHUB_WORKSPACE/test-results",
            "$RUNNER_TEMP/wave5-postgres-uploadable",
            "wave5-postgres",
        ),
        "calendar-real-browser": (
            "$GITHUB_WORKSPACE/test-results",
            "$RUNNER_TEMP/wave5-real-uploadable",
            "wave5-real",
        ),
    },
}
EXPECTED_JOB_DEFAULTS: dict[tuple[str, str], dict[str, object]] = {
    ("registration-db-gate.yml", "postgres-16-pgvector"): {
        "run": {"working-directory": "backend"},
    },
    ("wave1-foundation-gate.yml", "frontend-native"): {
        "run": {"working-directory": "frontend"},
    },
    ("wave1-foundation-gate.yml", "backend-postgres16-gate"): {
        "run": {"working-directory": "backend"},
    },
    ("wave2-tutoring-db-gate.yml", "wave2-postgres-16-pgvector"): {
        "run": {"working-directory": "backend"},
    },
}
EXPECTED_JOB_ENVS: dict[tuple[str, str], dict[str, object]] = {
    ("registration-db-gate.yml", "postgres-16-pgvector"): {
        "DATABASE_URL": "postgresql+psycopg://nyayone_ci:nyayone_ci_ephemeral@127.0.0.1:5432/nyayone_ci",
        "REGISTRATION_SECRET": "ci-registration-encryption-secret",
        "REGISTRATION_LOOKUP_SECRET": "ci-registration-lookup-secret",
        "APP_ENV": "test",
        "NYAY19_ISOLATED_MIGRATION_EXECUTE": "1",
    },
    ("wave1-foundation-gate.yml", "backend-postgres16-gate"): {
        "DATABASE_URL": "postgresql+psycopg://nyayone_ci:nyayone_ci_ephemeral@127.0.0.1:1032/nyayone_ci",
        "APP_ENV": "staging",
        "CALENDAR_PUBLIC_BASE_URL": "https://calendar.example.test",
        "INTERNSHIP_REPORT_SCANNER_PROVIDER": "clamav",
        "REGISTRATION_SECRET": "ci-registration-secret-not-a-dev-default",
        "REGISTRATION_LOOKUP_SECRET": "ci-registration-lookup-secret-not-a-dev-default",
        "OTP_DELIVERY_ENABLED": "true",
        "OTP_PROVIDER": "http",
        "OTP_PROVIDER_URL": "https://otp-provider.example.test/send",
        "OTP_PROVIDER_TOKEN": "ci-otp-provider-token-not-a-default",
        "OTP_PROVIDER_SUPPORTS_IDEMPOTENCY": "true",
        "NYAY19_ISOLATED_MIGRATION_EXECUTE": "1",
    },
    ("wave2-tutoring-db-gate.yml", "wave2-postgres-16-pgvector"): {
        "DATABASE_URL": "postgresql+psycopg://nyayone_ci:nyayone_ci_ephemeral@127.0.0.1:5432/nyayone_ci",
        "APP_ENV": "test",
        "REGISTRATION_SECRET": "ci-registration-encryption-secret-not-a-default",
        "REGISTRATION_LOOKUP_SECRET": "ci-registration-lookup-secret-not-a-default",
        "NYAY19_ISOLATED_MIGRATION_EXECUTE": "1",
    },
    ("wave3-credential-trust-gate.yml", "credential-trust-postgres-browser"): {
        "DATABASE_URL": "postgresql+psycopg://nyayone_ci:nyayone_ci_ephemeral@127.0.0.1:5432/nyayone_ci",
        "APP_ENV": "staging",
        "CALENDAR_PUBLIC_BASE_URL": "https://calendar.example.test",
        "INTERNSHIP_REPORT_SCANNER_PROVIDER": "clamav",
        "REGISTRATION_SECRET": "ci-registration-encryption-secret-not-a-default",
        "REGISTRATION_LOOKUP_SECRET": "ci-registration-lookup-secret-not-a-default",
        "CREDENTIAL_TOKEN_SECRET": "ci-credential-token-secret-not-a-default",
        "CREDENTIAL_STORAGE_ROOT": "${{ github.workspace }}/test-results/credential-objects",
        "CREDENTIAL_PUBLIC_BASE_URL": "https://verify.example.test/verify",
        "CORS_ORIGINS": '["http://127.0.0.1:1170","http://localhost:1170"]',
        "OTP_DELIVERY_ENABLED": "true",
        "OTP_PROVIDER": "http",
        "OTP_PROVIDER_URL": "https://otp-provider.example.test/send",
        "OTP_PROVIDER_TOKEN": "ci-otp-provider-token-not-a-default",
        "OTP_PROVIDER_SUPPORTS_IDEMPOTENCY": "true",
        "NYAY19_ISOLATED_MIGRATION_EXECUTE": "1",
    },
    ("wave4-private-reporting-gate.yml", "private-reporting-postgres-browser"): {
        "DATABASE_URL": "postgresql+psycopg://nyayone_ci:nyayone_ci_ephemeral@127.0.0.1:5432/nyayone_wave4_qa",
        "TEST_DATABASE_URL": "postgresql+psycopg://nyayone_ci:nyayone_ci_ephemeral@127.0.0.1:5432/nyayone_wave4_qa",
        "APP_ENV": "testing",
        "WAVE4_GATE_ALLOW_MUTATION": "true",
        "INTERNSHIP_RISK_LABELS_ENABLED": "false",
        "REGISTRATION_SECRET": "ci-registration-encryption-secret-not-a-default",
        "REGISTRATION_LOOKUP_SECRET": "ci-registration-lookup-secret-not-a-default",
        "INTERNSHIP_REPORT_STORAGE_ROOT": "${{ github.workspace }}/test-results/report-evidence",
        "INTERNSHIP_REPORT_SCANNER_PROVIDER": "clamav",
        "INTERNSHIP_REPORT_CLAMAV_HOST": "127.0.0.1",
        "INTERNSHIP_REPORT_CLAMAV_PORT": "3310",
        "CORS_ORIGINS": '["http://127.0.0.1:1260","http://localhost:1260","http://127.0.0.1:1263","http://localhost:1263"]',
        "NYAY19_ISOLATED_MIGRATION_EXECUTE": "1",
    },
    ("wave5-calendar-gate.yml", "calendar-postgres"): {
        "DATABASE_URL": "postgresql+psycopg://nyayone_ci:nyayone_ci_ephemeral@127.0.0.1:5432/nyayone_wave5_qa",
        "APP_ENV": "testing",
        "WAVE5_GATE_ALLOW_MUTATION": "true",
        "REGISTRATION_SECRET": "ci-registration-encryption-secret-not-a-default",
        "REGISTRATION_LOOKUP_SECRET": "ci-registration-lookup-secret-not-a-default",
        "NYAY19_ISOLATED_MIGRATION_EXECUTE": "1",
    },
    ("wave5-calendar-gate.yml", "calendar-real-browser"): {
        "DATABASE_URL": "postgresql+psycopg://nyayone_ci:nyayone_ci_ephemeral@127.0.0.1:5432/nyayone_wave5_browser_qa",
        "APP_ENV": "testing",
        "WAVE5_E2E_ALLOW_SEED": "true",
        "REGISTRATION_SECRET": "ci-wave5-browser-encryption-secret-not-a-default",
        "REGISTRATION_LOOKUP_SECRET": "ci-wave5-browser-lookup-secret-not-a-default",
        "CORS_ORIGINS": '["https://127.0.0.1:1290"]',
        "CALENDAR_PUBLIC_BASE_URL": "https://127.0.0.1:1291",
        "VITE_DISABLE_SERVICE_WORKER": "true",
        "NYAY19_ISOLATED_MIGRATION_EXECUTE": "1",
    },
}
EVIDENCE_UPLOAD_NAMES: dict[tuple[str, str], str] = {
    ("wave1-foundation-gate.yml", "frontend-native"): "v34-s11-s26-browser-attestation",
    ("wave2-tutoring-db-gate.yml", "wave2-postgres-16-pgvector"): "wave2-tutoring-db-gate-attestation",
    ("wave3-credential-trust-gate.yml", "credential-trust-postgres-browser"): "wave3-credential-trust-attestation",
    ("wave4-private-reporting-gate.yml", "private-reporting-postgres-browser"): "wave4-private-reporting-attestation",
    ("wave5-calendar-gate.yml", "calendar-postgres"): "wave5-calendar-postgres-attestation",
    ("wave5-calendar-gate.yml", "calendar-real-browser"): "wave5-calendar-real-browser-attestation",
}
REQUIRED_JOB_RUNS: dict[tuple[str, str], set[str]] = {
    ("registration-db-gate.yml", "postgres-16-pgvector"): {
        "PYTHON=python bash scripts/db_gate.sh",
    },
    ("wave1-foundation-gate.yml", "backend-postgres16-gate"): {
        "PYTHON=python bash scripts/db_gate.sh",
    },
}
ALLOWED_STEP_CONDITIONS = {
    "${{ always() }}",
    "always()",
    EXPECTED_UPLOAD_IF,
}
NO_OP_RUN_COMMANDS = {":", "exit 0", "true"}
EXPECTED_JOB_SEMANTIC_SHA256: dict[tuple[str, str], str] = {
    ("nyayone-policy-gate.yml", "policy-contracts"): "151bbfbfcab418fa90213523175b7b50ce0597d6504afcc2f5dd30eb79531838",
    ("nyayone-policy-gate.yml", "required"): "cb7fdec8df817040ee48f877cd06a82a80b252603c51a9bd1771abcdffbe54e2",
    ("registration-db-gate.yml", "postgres-16-pgvector"): "4a5fe899f88d2cd98ec5108af462f8f9c08e612459538ccf809fc3aa23500b26",
    ("registration-db-gate.yml", "required"): "826db470f5620527b0929811c10b0550f6ce56c37e1c0225957731358e2f4aee",
    ("wave1-foundation-gate.yml", "frontend-native"): "7cbafa269bc3a7c511f332cb626068e53bf185bd7d9528b2f4fac707ce1372d3",
    ("wave1-foundation-gate.yml", "backend-postgres16-gate"): "91fca0d807f2c7e209ff5cff4b624a466d6a7d2fd09cf1c964940e33cb76f14a",
    ("wave1-foundation-gate.yml", "required"): "819f6d6b3187a38058f07e01be6573b315be27a9b296c2239731d33c12d8e67f",
    ("wave2-tutoring-db-gate.yml", "wave2-postgres-16-pgvector"): "449af3381247ff7d91c5b6c7a60ab220ecc63308af4553af6dd22a32bdaab758",
    ("wave2-tutoring-db-gate.yml", "required"): "3e311e18909eee9d1d5b63e2aa231a02296d1d17af0edbf5f3fb3f5609c6fd78",
    ("wave3-credential-trust-gate.yml", "credential-trust-postgres-browser"): "a5c8c25d7f98d6536e8b8968747a4b3f09ca6e01b8d23e2568dca2964a12ce35",
    ("wave3-credential-trust-gate.yml", "required"): "fb8b82abae6dcda07b3b8ab376d13882184fef23e2e17d7941a52656840e33de",
    ("wave4-private-reporting-gate.yml", "private-reporting-postgres-browser"): "741e06de64ef3a6be76fc5646cc74f8268990f4ae912dee0e0ca6696b0bd8418",
    ("wave4-private-reporting-gate.yml", "required"): "e7dba929f69d1c9783aecf806fed473f2eeb3d5f8155ed95a3e50f71d058e861",
    ("wave5-calendar-gate.yml", "calendar-postgres"): "3e53e60acd87ec409045c0e7fc1dd0bcc474c4c8a13275545d72e0dfd4de7a27",
    ("wave5-calendar-gate.yml", "calendar-real-browser"): "538128276a071cafcc082999f0b912756b4cd71500552432b49659eedd74f6d4",
    ("wave5-calendar-gate.yml", "required"): "c4c8cefe36440feecc52c6968ae30095e94900cf677dbd9d203d2e8c3d07e3f1",
}


if yaml is not None:
    class _NoDuplicateBaseLoader(yaml.BaseLoader):
        """YAML loader with string scalars and recursive duplicate rejection."""

        pass


    def _construct_unique_mapping(loader, node, deep=False):
        mapping: dict[object, object] = {}
        for key_node, value_node in node.value:
            key = loader.construct_object(key_node, deep=deep)
            try:
                duplicate = key in mapping
            except TypeError as exc:
                raise yaml.constructor.ConstructorError(
                    "while constructing a mapping",
                    node.start_mark,
                    "mapping keys must be scalar values",
                    key_node.start_mark,
                ) from exc
            if duplicate:
                raise yaml.constructor.ConstructorError(
                    "while constructing a mapping",
                    node.start_mark,
                    "duplicate mapping key",
                    key_node.start_mark,
                )
            mapping[key] = loader.construct_object(value_node, deep=deep)
        return mapping


    _NoDuplicateBaseLoader.add_constructor(
        yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG,
        _construct_unique_mapping,
    )


def _mapping(value: object) -> dict[str, object] | None:
    if not isinstance(value, dict) or not all(isinstance(key, str) for key in value):
        return None
    return value


def _run_reaches_nyay4_transitively(run: str) -> bool:
    """Classify jobs whose backend command loads the sealed NYAY-4 source probe."""

    canonical = _canonical_shell(run)
    calls_database_gate = re.search(
        r"(?:^|[ (;&|])bash (?:backend/)?scripts/db_gate\.sh(?:$|[ );&|])",
        canonical,
    ) is not None
    runs_complete_backend_suite = re.search(
        r"(?:^|[ (;&|])(?:python(?:3)? -m )?pytest -q(?=$|[);&|])",
        canonical,
    ) is not None
    return calls_database_gate or runs_complete_backend_suite


def _effective_working_directory(
    job: dict[str, object], step: dict[str, object]
) -> object:
    if "working-directory" in step:
        return step["working-directory"]
    defaults = _mapping(job.get("defaults")) or {}
    run_defaults = _mapping(defaults.get("run")) or {}
    return run_defaults.get("working-directory")


def _exact_npm_ci_count(run: str) -> int:
    return sum(
        _canonical_shell(line) == "npm ci"
        for line in run.splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    )


def _nyay4_frontend_dependency_failures(
    path: Path, jobs: dict[str, object]
) -> list[str]:
    """Require Node/Vitest dependencies in every NYAY-4-transitive job.

    GitHub jobs do not share filesystems. A sibling frontend job cannot provide
    ``node_modules`` to a backend job whose complete suite or ``db_gate.sh``
    reaches NYAY-4's frontend source contracts, so provisioning must be exact,
    local to the job, and ordered before the first transitive invocation.
    """

    failures: list[str] = []
    for job_id, raw_job in jobs.items():
        job = _mapping(raw_job)
        if job is None:
            continue
        raw_steps = job.get("steps")
        if not isinstance(raw_steps, list):
            continue
        steps = [_mapping(step) for step in raw_steps]
        transitive_indexes = [
            index
            for index, step in enumerate(steps)
            if step is not None
            and isinstance(step.get("run"), str)
            and _run_reaches_nyay4_transitively(str(step["run"]))
        ]
        if not transitive_indexes:
            continue
        first_gate = min(transitive_indexes)

        setup_node = [
            (index, step)
            for index, step in enumerate(steps)
            if step is not None and step.get("uses") == PINNED_SETUP_NODE_ACTION
        ]
        if not (
            len(setup_node) == 1
            and setup_node[0][0] < first_gate
            and setup_node[0][1].get("with") == EXPECTED_NYAY4_SETUP_NODE_WITH
        ):
            failures.append(
                f"{path}: job {job_id} NYAY-4-transitive job must provision "
                "exact pinned Node 22 before its backend gate"
            )

        npm_ci = [
            (index, _exact_npm_ci_count(str(step["run"])))
            for index, step in enumerate(steps)
            if step is not None
            and isinstance(step.get("run"), str)
            and _effective_working_directory(job, step) == "frontend"
            and _exact_npm_ci_count(str(step["run"]))
        ]
        if not (
            sum(count for _, count in npm_ci) == 1
            and len(npm_ci) == 1
            and npm_ci[0][0] < first_gate
        ):
            failures.append(
                f"{path}: job {job_id} NYAY-4-transitive job must run exact "
                "npm ci from frontend before its backend gate"
            )
    return failures


def _nyay19_isolated_postgres_url_is_exact(value: object) -> bool:
    """Match the release guard's static, fail-closed CI target subset."""

    if not isinstance(value, str) or not value.startswith("postgresql+"):
        return False
    try:
        parsed = urlsplit(value)
        port = parsed.port
    except ValueError:
        return False
    if (
        parsed.hostname != "127.0.0.1"
        or port is None
        or not 1 <= port <= 65535
        or not parsed.username
        or parsed.password is None
        or parsed.query
        or parsed.fragment
    ):
        return False
    database = parsed.path.removeprefix("/")
    if not database or any(
        marker in database.casefold()
        for marker in NYAY19_FORBIDDEN_DATABASE_MARKERS
    ):
        return False
    tokens = {
        token
        for token in re.split(r"[^a-z0-9]+", database.casefold())
        if token
    }
    return bool(tokens & NYAY19_ISOLATED_DATABASE_MARKERS)


def _nyay19_workflow_alembic_failures(
    path: Path,
    jobs: dict[str, object],
) -> list[str]:
    """Require explicit isolated authority only on sealed Alembic CI jobs."""

    failures: list[str] = []
    all_caller_markers = {
        marker
        for markers in EXPECTED_NYAY19_ALEMBIC_WORKFLOW_JOBS.values()
        for marker in markers
    }
    for job_id, raw_job in jobs.items():
        job = _mapping(raw_job)
        if job is None:
            continue
        job_env = _mapping(job.get("env")) if "env" in job else {}
        if job_env is None:
            job_env = {}
        steps = job.get("steps")
        step_mappings = [
            step
            for step in steps if isinstance(step, dict)
        ] if isinstance(steps, list) else []
        run_text = "\n".join(
            str(step["run"])
            for step in step_mappings
            if isinstance(step.get("run"), str)
        )
        canonical_run = _canonical_shell(run_text)
        key = (path.name, job_id)
        expected_markers = EXPECTED_NYAY19_ALEMBIC_WORKFLOW_JOBS.get(key)
        has_known_caller = any(
            marker in canonical_run for marker in all_caller_markers
        )
        has_direct_alembic = (
            "-m alembic" in canonical_run
            or re.search(
                r"(?:^| )alembic (?:[^ ]+ )*"
                r"(?:upgrade|downgrade|check|current|stamp)(?: |$)",
                canonical_run,
            ) is not None
        )
        step_opt_ins = [
            _mapping(step.get("env")).get(NYAY19_ISOLATED_MIGRATION_ENV)
            for step in step_mappings
            if _mapping(step.get("env")) is not None
            and NYAY19_ISOLATED_MIGRATION_ENV in _mapping(step.get("env"))
        ]

        if expected_markers is None:
            if (
                has_known_caller
                or has_direct_alembic
                or NYAY19_ISOLATED_MIGRATION_ENV in job_env
                or step_opt_ins
            ):
                failures.append(
                    f"{path}: job {job_id} has unclassified NYAY-19 isolated Alembic authority"
                )
            continue

        if job_env.get(NYAY19_ISOLATED_MIGRATION_ENV) != "1":
            failures.append(
                f"{path}: job {job_id} NYAY-19 isolated Alembic authority must be exactly 1 at job scope"
            )
        if step_opt_ins:
            failures.append(
                f"{path}: job {job_id} NYAY-19 isolated Alembic authority may not be shadowed at step scope"
            )
        if job_env.get("APP_ENV") not in NYAY19_ISOLATED_APP_ENVS:
            failures.append(
                f"{path}: job {job_id} NYAY-19 isolated Alembic APP_ENV is not allowlisted"
            )
        if not any(
            isinstance(_mapping(service), dict)
            and isinstance(_mapping(service).get("image"), str)
            and (
                "postgres" in str(_mapping(service)["image"]).casefold()
                or "pgvector" in str(_mapping(service)["image"]).casefold()
            )
            for service in (_mapping(job.get("services")) or {}).values()
        ):
            failures.append(
                f"{path}: job {job_id} NYAY-19 isolated Alembic requires its own PostgreSQL service"
            )
        for marker in expected_markers:
            if marker not in canonical_run:
                failures.append(
                    f"{path}: job {job_id} NYAY-19 isolated Alembic caller is missing: {marker}"
                )

        url_values = [
            value
            for name, value in job_env.items()
            if name.endswith("DATABASE_URL")
        ]
        url_values.extend(
            re.findall(
                r"postgresql(?:\+[A-Za-z0-9_]+)?://[^\s'\"\\]+",
                run_text,
            )
        )
        if not url_values or any(
            not _nyay19_isolated_postgres_url_is_exact(value)
            for value in url_values
        ):
            failures.append(
                f"{path}: job {job_id} NYAY-19 isolated Alembic URLs must use a marker-named database on literal 127.0.0.1"
            )
    return failures


def _structural_workflow_failures(text: str, path: Path) -> list[str]:
    """Validate security-sensitive workflow semantics with a real YAML parser.

    Text checks below intentionally retain canonical formatting and exact shell
    command contracts. This parser is the authority for YAML equivalence:
    quoted keys, inline maps, explicit keys and duplicate last-key-wins forms
    cannot become invisible to the policy oracle.
    """

    if yaml is None:
        return [f"{path}: PyYAML 6.0.3 is required for structural workflow policy"]
    try:
        document = yaml.load(text, Loader=_NoDuplicateBaseLoader)
    except yaml.YAMLError:
        return [f"{path}: workflow YAML is invalid or contains a duplicate mapping key"]
    root = _mapping(document)
    if root is None:
        return [f"{path}: workflow root must be a YAML mapping"]

    failures: list[str] = []
    if "env" in root:
        failures.append(f"{path}: workflow-level env is forbidden")
    if "defaults" in root:
        failures.append(f"{path}: workflow-level defaults are forbidden")
    if root.get("permissions") != {"contents": "read"}:
        failures.append(f"{path}: workflow permissions must be exactly contents: read")

    jobs = _mapping(root.get("jobs"))
    if not jobs:
        return failures + [f"{path}: jobs must be a non-empty mapping"]
    failures.extend(_nyay19_workflow_alembic_failures(path, jobs))
    failures.extend(_nyay4_frontend_dependency_failures(path, jobs))
    expected_job_ids = {
        job_id
        for workflow_name, job_id in EXPECTED_JOB_SEMANTIC_SHA256
        if workflow_name == path.name
    }
    if set(jobs) != expected_job_ids:
        failures.append(f"{path}: job inventory differs from the canonical contract")

    for job_id, raw_job in jobs.items():
        job = _mapping(raw_job)
        if job is None:
            failures.append(f"{path}: job {job_id} must be a mapping")
            continue
        semantic_payload = json.dumps(
            job,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        ).encode("utf-8")
        expected_semantic_digest = EXPECTED_JOB_SEMANTIC_SHA256.get(
            (path.name, job_id)
        )
        if (
            expected_semantic_digest is None
            or hashlib.sha256(semantic_payload).hexdigest()
            != expected_semantic_digest
        ):
            failures.append(
                f"{path}: job {job_id} differs from the canonical semantic contract"
            )
        if "container" in job:
            failures.append(f"{path}: job {job_id} may not use a job container")
        if "uses" in job:
            failures.append(f"{path}: job {job_id} may not call a reusable workflow")
        if "permissions" in job:
            failures.append(f"{path}: job {job_id} may not override token permissions")
        if "continue-on-error" in job:
            failures.append(f"{path}: job {job_id} may not continue on error")
        if job.get("runs-on") != "ubuntu-24.04":
            failures.append(f"{path}: job {job_id} runner must be exactly ubuntu-24.04")
        if job_id == "required":
            if job.get("if") != "${{ always() }}":
                failures.append(
                    f"{path}: required aggregator job condition must be exactly always()"
                )
        elif "if" in job:
            failures.append(f"{path}: producer job {job_id} may not be conditional")

        services = _mapping(job.get("services")) if "services" in job else {}
        if services is None:
            failures.append(f"{path}: job {job_id} services must be a mapping")
            services = {}
        for service_id, raw_service in services.items():
            service = _mapping(raw_service)
            if service is None or service.get("image") not in ALLOWED_SERVICE_IMAGE_REFS:
                failures.append(
                    f"{path}: job {job_id} service {service_id} image reference is not allowlisted"
                )

        expected_defaults = EXPECTED_JOB_DEFAULTS.get((path.name, job_id))
        if job.get("defaults") != expected_defaults and (
            "defaults" in job or expected_defaults is not None
        ):
            failures.append(
                f"{path}: job {job_id} defaults differ from the canonical working directory"
            )

        job_env = _mapping(job.get("env")) if "env" in job else {}
        if job_env is None:
            failures.append(f"{path}: job {job_id} env must be a mapping")
            job_env = {}
        for key in job_env:
            if key.upper() in DANGEROUS_ENV_KEYS:
                failures.append(f"{path}: job {job_id} overrides a protected environment key")
        expected_job_env = EXPECTED_JOB_ENVS.get((path.name, job_id), {})
        if job_env != expected_job_env:
            failures.append(
                f"{path}: job {job_id} environment differs from the canonical target-runtime contract"
            )

        steps = job.get("steps")
        if not isinstance(steps, list) or not steps:
            failures.append(f"{path}: job {job_id} needs a non-empty steps list")
            continue
        for index, raw_step in enumerate(steps, 1):
            step = _mapping(raw_step)
            if step is None:
                failures.append(f"{path}: job {job_id} step {index} must be a mapping")
                continue
            if ("uses" in step) == ("run" in step):
                failures.append(
                    f"{path}: job {job_id} step {index} needs exactly one of uses or run"
                )
            if "continue-on-error" in step:
                failures.append(
                    f"{path}: job {job_id} step {index} may not continue on error"
                )
            if "shell" in step and step.get("shell") != "bash":
                failures.append(
                    f"{path}: job {job_id} step {index} has a noncanonical shell override"
                )
            condition = step.get("if")
            if condition is not None and condition not in ALLOWED_STEP_CONDITIONS:
                failures.append(
                    f"{path}: job {job_id} step {index} has a noncanonical condition"
                )
            step_env = _mapping(step.get("env")) if "env" in step else {}
            if step_env is None:
                failures.append(f"{path}: job {job_id} step {index} env must be a mapping")
                step_env = {}
            for key in step_env:
                if key.upper() in DANGEROUS_ENV_KEYS:
                    failures.append(
                        f"{path}: job {job_id} step {index} overrides a protected environment key"
                    )
            action = step.get("uses")
            if action is not None and action not in ALLOWED_ACTIONS:
                failures.append(
                    f"{path}: job {job_id} step {index} action identity is not allowlisted"
                )
            if action == "actions/checkout@11d5960a326750d5838078e36cf38b85af677262":
                if step.get("with") != {
                    "persist-credentials": "false",
                    "fetch-depth": "0",
                }:
                    failures.append(
                        f"{path}: job {job_id} checkout must use the exact head-safe configuration"
                    )
            if action == "actions/upload-artifact@ea165f8d65b6e75b540449e92b4886f43607fa02":
                contract = EVIDENCE_CONTRACTS.get(path.name, {}).get(job_id)
                expected_name = EVIDENCE_UPLOAD_NAMES.get((path.name, job_id))
                expected_path = (
                    contract[1].replace("$RUNNER_TEMP", "${{ runner.temp }}")
                    if contract
                    else None
                )
                if step.get("with") != {
                    "name": expected_name,
                    "path": expected_path,
                    "if-no-files-found": "error",
                    "retention-days": "14",
                    "include-hidden-files": "false",
                }:
                    failures.append(
                        f"{path}: job {job_id} upload configuration is not exact"
                    )

            run = step.get("run")
            if isinstance(run, str) and _canonical_shell(run) in NO_OP_RUN_COMMANDS:
                failures.append(
                    f"{path}: job {job_id} step {index} is an explicit no-op"
                )

        required_runs = REQUIRED_JOB_RUNS.get((path.name, job_id), set())
        for required_run in sorted(required_runs):
            matching_steps = [
                step
                for step in steps
                if isinstance(step, dict)
                and isinstance(step.get("run"), str)
                and _canonical_shell(str(step["run"])) == required_run
            ]
            if len(matching_steps) != 1:
                failures.append(
                    f"{path}: job {job_id} must contain the required gate command exactly once: {required_run}"
                )
                continue
            extra_keys = sorted(set(matching_steps[0]) - {"name", "run"})
            if extra_keys:
                failures.append(
                    f"{path}: job {job_id} required gate command has forbidden keys: "
                    + ", ".join(extra_keys)
                )

        exact_steps = {
            name: contract
            for (workflow_name, expected_job_id, name), contract
            in EXPECTED_EXACT_STEPS.items()
            if workflow_name == path.name and expected_job_id == job_id
        }
        for name, contract in exact_steps.items():
            matching_steps = [
                step
                for step in steps
                if isinstance(step, dict) and step.get("name") == name
            ]
            if len(matching_steps) != 1 or matching_steps[0] != contract:
                failures.append(
                    f"{path}: job {job_id} step {name!r} differs from the exact required contract"
                )

        if (
            path.name == "wave3-credential-trust-gate.yml"
            and job_id == "credential-trust-postgres-browser"
        ):
            ordered_names = (
                "NYAY-4 OTP authority Chromium regression",
                "Start NYAY-19 isolated auth lifecycle backend and frontend",
                "NYAY-19 authentication lifecycle Chromium regression",
            )
            name_indexes = {
                name: [
                    index
                    for index, step in enumerate(steps)
                    if isinstance(step, dict) and step.get("name") == name
                ]
                for name in ordered_names
            }
            if any(len(indexes) != 1 for indexes in name_indexes.values()):
                failures.append(
                    f"{path}: NYAY-19 isolated startup and browser gate must each "
                    "appear exactly once after NYAY-4"
                )
            else:
                nyay4_index, startup_index, browser_index = (
                    name_indexes[name][0] for name in ordered_names
                )
                if not (
                    startup_index == nyay4_index + 1
                    and browser_index == startup_index + 1
                ):
                    failures.append(
                        f"{path}: NYAY-19 isolated startup and browser gate must be "
                        "adjacent and immediately follow NYAY-4"
                    )

        if job_id == "required":
            forbidden_required = {
                "container", "continue-on-error", "defaults", "env", "permissions",
                "services", "strategy", "uses",
            }
            present = sorted(forbidden_required & set(job))
            if present:
                failures.append(
                    f"{path}: required aggregator has forbidden job keys: {', '.join(present)}"
                )
            if len(steps) == 1 and isinstance(steps[0], dict):
                allowed_step_keys = {"env", "name", "run"}
                extra = sorted(set(steps[0]) - allowed_step_keys)
                if extra:
                    failures.append(
                        f"{path}: required aggregator step has forbidden keys: {', '.join(extra)}"
                    )
                if steps[0].get("env") != {"RESULTS": "${{ toJSON(needs) }}"}:
                    failures.append(f"{path}: required aggregator env is not exact")

    return failures


def _step_blocks(job_block: str) -> list[str]:
    starts = list(re.finditer(r"^      - (?=\S)", job_block, re.MULTILINE))
    return [
        job_block[match.start() : starts[index + 1].start()]
        if index + 1 < len(starts)
        else job_block[match.start() :]
        for index, match in enumerate(starts)
    ]


def _step_id(step: str) -> str | None:
    match = re.search(r"^        id:\s*([a-zA-Z0-9_-]+)\s*$", step, re.MULTILINE)
    return match.group(1) if match else None


def _run_payload(step: str) -> str | None:
    match = re.search(r"^        run:\s*(.*?)\s*$", step, re.MULTILINE)
    if not match:
        return None
    marker = match.group(1)
    if marker not in {"|", "|-", ">", ">-"}:
        return marker
    lines: list[str] = []
    for line in step[match.end() :].splitlines():
        if not line.strip():
            lines.append("")
            continue
        if not line.startswith("          "):
            break
        lines.append(line[10:])
    separator = "\n" if marker.startswith("|") else " "
    return separator.join(lines).strip()


def _canonical_shell(command: str) -> str:
    normalized = re.sub(
        r"\$\{\{\s*runner\.temp\s*\}\}", "$RUNNER_TEMP", command
    )
    normalized = re.sub(
        r"\$\{\{\s*github\.workspace\s*\}\}", "$GITHUB_WORKSPACE", normalized
    )
    normalized = normalized.replace('"', "").replace("'", "")
    return " ".join(normalized.split())


def check_db_gate_contract(path: Path = DB_GATE) -> list[str]:
    """Seal the nested shell gate reached by required registration CI.

    The workflow's semantic digest protects the call *to* db_gate.sh.  This
    companion contract protects the executable reached through that call, so
    leaving the workflow untouched while deleting/bypassing NYAY-16, NYAY-3,
    NYAY-2, NYAY-17, NYAY-4, or NYAY-19 cannot produce a false green.
    """

    if not path.is_file() or path.is_symlink():
        return [f"{path}: database gate is missing or unsafe"]
    try:
        raw = path.read_bytes()
        source = raw.decode("utf-8")
    except (OSError, UnicodeError) as exc:
        return [f"{path}: database gate cannot be read: {type(exc).__name__}"]

    failures: list[str] = []
    if hashlib.sha256(raw).hexdigest() != EXPECTED_DB_GATE_SHA256:
        failures.append(f"{path}: database gate SHA-256 differs from the sealed contract")

    executable = "\n".join(
        line for line in source.splitlines() if not line.lstrip().startswith("#")
    )
    executable = re.sub(r"\\\s*\n", " ", executable)
    canonical = _canonical_shell(executable)
    nyay16 = _canonical_shell(EXPECTED_NYAY16_DB_GATE_COMMAND)
    nyay3 = _canonical_shell(EXPECTED_NYAY3_DB_GATE_COMMAND)
    nyay2 = _canonical_shell(EXPECTED_NYAY2_DB_GATE_COMMAND)
    nyay17 = _canonical_shell(EXPECTED_NYAY17_DB_GATE_COMMAND)
    nyay4 = _canonical_shell(EXPECTED_NYAY4_DB_GATE_COMMAND)
    nyay19 = _canonical_shell(EXPECTED_NYAY19_DB_GATE_COMMAND)
    if canonical.count(nyay16) != 1:
        failures.append(
            f"{path}: database gate must invoke the exact NYAY-16 PostgreSQL gate once"
        )
    if canonical.count(nyay3) != 1:
        failures.append(
            f"{path}: database gate must invoke the exact NYAY-3 PostgreSQL gate once"
        )
    if canonical.count(nyay2) != 1:
        failures.append(
            f"{path}: database gate must invoke the exact NYAY-2 PostgreSQL gate once"
        )
    if canonical.count(nyay17) != 1:
        failures.append(
            f"{path}: database gate must invoke the exact NYAY-17 PostgreSQL gate once"
        )
    if canonical.count(nyay4) != 1:
        failures.append(
            f"{path}: database gate must invoke the exact NYAY-4 PostgreSQL gate once"
        )
    if canonical.count(nyay19) != 1:
        failures.append(
            f"{path}: database gate must invoke the exact NYAY-19 PostgreSQL gate once"
        )
    wave2 = _canonical_shell('PYTHON="$PY" bash scripts/wave2_db_gate.sh')
    if (
        wave2 not in canonical
        or nyay16 not in canonical
        or canonical.index(nyay16) < canonical.index(wave2)
    ):
        failures.append(
            f"{path}: NYAY-16 PostgreSQL gate must remain after the inherited Wave 2 stage"
        )
    if (
        nyay16 not in canonical
        or nyay3 not in canonical
        or canonical.index(nyay3) < canonical.index(nyay16)
    ):
        failures.append(
            f"{path}: NYAY-3 PostgreSQL gate must remain after the NYAY-16 stage"
        )
    if (
        nyay3 not in canonical
        or nyay2 not in canonical
        or canonical.index(nyay2) < canonical.index(nyay3)
    ):
        failures.append(
            f"{path}: NYAY-2 PostgreSQL gate must remain after the NYAY-3 stage"
        )
    if (
        nyay2 not in canonical
        or nyay17 not in canonical
        or canonical.index(nyay17) < canonical.index(nyay2)
    ):
        failures.append(
            f"{path}: NYAY-17 PostgreSQL gate must remain after the NYAY-2 stage"
        )
    if (
        nyay17 not in canonical
        or nyay4 not in canonical
        or canonical.index(nyay4) < canonical.index(nyay17)
    ):
        failures.append(
            f"{path}: NYAY-4 PostgreSQL gate must remain after the NYAY-17 stage"
        )
    if (
        nyay4 not in canonical
        or nyay19 not in canonical
        or canonical.index(nyay19) < canonical.index(nyay4)
    ):
        failures.append(
            f"{path}: NYAY-19 PostgreSQL gate must remain after the NYAY-4 stage"
        )

    # NYAY-19 is the final mandatory nested stage. Requiring its exact command
    # to be the last executable line also rejects wrappers such as ``if
    # false``, ``|| true``, ``--help``, redirection, or a non-executing echo.
    # With db_gate.sh's set -euo pipefail this keeps BLOCKED (78) and FAIL (1)
    # fatal instead of allowing a later command to turn the job green.
    logical_commands = [
        _canonical_shell(line)
        for line in re.sub(r"\\\s*\n", " ", executable).splitlines()
        if line.strip()
    ]
    if not logical_commands or logical_commands[-1] != nyay19:
        failures.append(
            f"{path}: exact NYAY-19 PostgreSQL gate must be the final unconditional command"
        )
    return failures


def check_nyay4_browser_gate_contract(
    browser_path: Path = NYAY4_BROWSER_GATE,
    contract_path: Path = NYAY4_BROWSER_CONTRACT,
    package_path: Path = FRONTEND_PACKAGE,
) -> list[str]:
    """Pin the executable NYAY-4 browser oracle behind the required CI step."""

    failures: list[str] = []
    pinned_files = (
        (
            browser_path,
            EXPECTED_NYAY4_BROWSER_GATE_SHA256,
            "NYAY-4 browser gate",
        ),
        (
            contract_path,
            EXPECTED_NYAY4_BROWSER_CONTRACT_SHA256,
            "NYAY-4 browser assertion contract",
        ),
    )
    for path, expected_sha256, label in pinned_files:
        try:
            raw = path.read_bytes()
        except OSError:
            failures.append(f"{path}: {label} is missing or unreadable")
            continue
        if hashlib.sha256(raw).hexdigest() != expected_sha256:
            failures.append(f"{path}: {label} SHA-256 differs from the sealed contract")

    if not package_path.is_file() or package_path.is_symlink():
        failures.append(f"{package_path}: frontend package contract is missing or unsafe")
        return failures
    try:
        package = json.loads(package_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        failures.append(f"{package_path}: frontend package contract is unreadable")
        return failures
    scripts = package.get("scripts") if isinstance(package, dict) else None
    if not isinstance(scripts, dict):
        failures.append(f"{package_path}: frontend scripts must be a mapping")
        return failures
    gate_name = "qa:nyay4:otp-negative"
    if scripts.get(gate_name) != EXPECTED_NYAY4_PACKAGE_COMMAND:
        failures.append(
            f"{package_path}: NYAY-4 browser package command differs from the exact contract"
        )
    for hook in (f"pre{gate_name}", f"post{gate_name}"):
        if hook in scripts:
            failures.append(
                f"{package_path}: NYAY-4 browser package command may not have an npm lifecycle wrapper"
            )
    return failures


def check_nyay19_browser_gate_contract(
    browser_path: Path = NYAY19_BROWSER_GATE,
    contract_path: Path = NYAY19_BROWSER_CONTRACT,
    package_path: Path = FRONTEND_PACKAGE,
    contract_test_path: Path = NYAY19_BROWSER_CONTRACT_TEST,
) -> list[str]:
    """Pin the executable NYAY-19 browser oracle behind the required CI step."""

    failures: list[str] = []
    pinned_files = (
        (
            browser_path,
            EXPECTED_NYAY19_BROWSER_GATE_SHA256,
            "NYAY-19 browser gate",
        ),
        (
            contract_path,
            EXPECTED_NYAY19_BROWSER_CONTRACT_SHA256,
            "NYAY-19 browser assertion contract",
        ),
        (
            contract_test_path,
            EXPECTED_NYAY19_BROWSER_CONTRACT_TEST_SHA256,
            "NYAY-19 browser assertion contract tests",
        ),
    )
    for path, expected_sha256, label in pinned_files:
        if not path.is_file() or path.is_symlink():
            failures.append(f"{path}: {label} is missing or unsafe")
            continue
        try:
            raw = path.read_bytes()
        except OSError:
            failures.append(f"{path}: {label} is unreadable")
            continue
        if hashlib.sha256(raw).hexdigest() != expected_sha256:
            failures.append(f"{path}: {label} SHA-256 differs from the sealed contract")

    if not package_path.is_file() or package_path.is_symlink():
        failures.append(f"{package_path}: frontend package contract is missing or unsafe")
        return failures
    try:
        package = json.loads(package_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        failures.append(f"{package_path}: frontend package contract is unreadable")
        return failures
    scripts = package.get("scripts") if isinstance(package, dict) else None
    if not isinstance(scripts, dict):
        failures.append(f"{package_path}: frontend scripts must be a mapping")
        return failures
    gate_name = "qa:nyay19:auth-lifecycle"
    if scripts.get(gate_name) != EXPECTED_NYAY19_PACKAGE_COMMAND:
        failures.append(
            f"{package_path}: NYAY-19 browser package command differs from the exact contract"
        )
    for hook in (f"pre{gate_name}", f"post{gate_name}"):
        if hook in scripts:
            failures.append(
                f"{package_path}: NYAY-19 browser package command may not have an npm lifecycle wrapper"
            )
    return failures


def _duplicate_mapping_keys(text: str) -> list[str]:
    """Reject duplicate keys in the repository's intentionally strict YAML subset."""

    failures: list[str] = []
    stack: list[tuple[int, str]] = []
    seen: dict[tuple[str, ...], set[str]] = {}
    sequence_counters: dict[tuple[tuple[str, ...], int], int] = {}
    block_scalar_indent: int | None = None
    mapping = re.compile(
        r"^(?P<indent> *)(?P<sequence>-\s+)?(?P<key>[A-Za-z0-9_-]+):(?P<value>.*)$"
    )

    for raw in text.splitlines():
        if not raw.strip() or raw.lstrip().startswith("#"):
            continue
        indent = len(raw) - len(raw.lstrip(" "))
        if block_scalar_indent is not None:
            if indent > block_scalar_indent:
                continue
            block_scalar_indent = None
        match = mapping.match(raw)
        if not match:
            continue
        indent = len(match.group("indent"))
        while stack and stack[-1][0] >= indent:
            stack.pop()
        parent = tuple(token for _, token in stack)
        if match.group("sequence"):
            counter_key = (parent, indent)
            number = sequence_counters.get(counter_key, 0) + 1
            sequence_counters[counter_key] = number
            stack.append((indent, f"sequence-{number}"))
            parent = tuple(token for _, token in stack)
        key = match.group("key")
        keys = seen.setdefault(parent, set())
        if key in keys:
            failures.append(f"duplicate YAML mapping key: {key}")
        keys.add(key)

        value = match.group("value").strip()
        if value in {"|", "|-", "|+", ">", ">-", ">+"}:
            block_scalar_indent = indent
        elif not value:
            stack.append((indent, key))
    return failures


def check_workflow(path: Path) -> list[str]:
    text = path.read_text(encoding="utf-8")
    failures: list[str] = []
    if path.name not in CANONICAL_WORKFLOW_FILES:
        failures.append(f"{path}: workflow filename is not canonical")
    failures.extend(_structural_workflow_failures(text, path))
    failures.extend(f"{path}: {failure}" for failure in _duplicate_mapping_keys(text))

    canonical_yaml_rejections = {
        "noncanonical YAML key spacing": r"^\s*(?:-\s*)?[A-Za-z0-9_-]+\s+:.*$",
        "quoted YAML mapping key": r"^\s*(?:-\s*)?[\"'][^\"'\n]+[\"']\s*:",
        "inline YAML mapping": r"^\s*(?:-\s*)?[A-Za-z0-9_-]*\s*:\s*\{.*$|^\s*-\s*\{.*$",
        "YAML anchor, alias or merge key": r"^\s*(?:<<:|[-A-Za-z0-9_]+:\s*[&*]|-\s*[&*]).*$",
        "explicit YAML mapping key": r"^\s*[?:](?:\s|$)",
        "explicit YAML type tag": r"(?:^|:\s+)!![A-Za-z0-9_.:/-]+",
        "non-executing shell override": r"^\s*shell:\s*(?:true|false)(?:\s+\{0\})?\s*$",
    }
    for label, pattern in canonical_yaml_rejections.items():
        if re.search(pattern, text, re.MULTILINE):
            failures.append(f"{path}: forbidden {label}")
    if re.search(r"\$\{\{[^}\n]*\bsecrets\b", text, re.IGNORECASE):
        failures.append(f"{path}: forbidden repository secret reference")

    required_fragments = {
        "least-privilege token": "permissions:\n  contents: read",
        "PRs target main": "pull_request:\n    branches: [main]",
        "pushes target main": "push:\n    branches: [main]",
        "manual dispatch": "workflow_dispatch:",
        "concurrency": "concurrency:",
        "required aggregator": "\n  required:\n",
    }
    for label, fragment in required_fragments.items():
        if fragment not in text:
            failures.append(f"{path}: missing {label}")

    forbidden_fragments = {
        "pull_request_target": "pull_request_target:",
        "write-all token permission": "permissions: write-all",
        "write token permission": "contents: write",
        "path-filtered required checks": "    paths:",
        "path-ignored required checks": "    paths-ignore:",
        "fail-open step": "continue-on-error: true",
        "missing evidence warning": "if-no-files-found: warn",
        "mutable runner image": "runs-on: ubuntu-latest",
        "repository secret reference": "${{ secrets.",
        "unpinned pip upgrade": "pip install --upgrade pip",
    }
    for label, fragment in forbidden_fragments.items():
        if fragment in text:
            failures.append(f"{path}: forbidden {label}")

    forbidden_patterns = {
        "continue-on-error override": r"^\s*-?\s*continue-on-error\s*:",
        "statically disabled job or step": r"^\s*-?\s*if:\s*.*\bfalse\b.*$",
        "inline write permission": r"^\s*permissions:\s*\{[^}\n]*\b[a-zA-Z0-9_-]+\s*:\s*[\"']?write[\"']?\b[^}\n]*\}\s*$",
    }
    for label, pattern in forbidden_patterns.items():
        if re.search(pattern, text, re.MULTILINE | re.IGNORECASE):
            failures.append(f"{path}: forbidden {label}")

    for ref in ACTION_REF.findall(text):
        if not PINNED_ACTION.fullmatch(ref):
            failures.append(f"{path}: action is not pinned to 40 hex characters: {ref}")
        if ref not in ALLOWED_ACTIONS:
            failures.append(f"{path}: action identity is not allowlisted: {ref}")

    for ref in IMAGE_REF.findall(text):
        if not PINNED_IMAGE.fullmatch(ref):
            failures.append(f"{path}: service image is not pinned to sha256: {ref}")
        if ref not in ALLOWED_SERVICE_IMAGE_REFS:
            failures.append(f"{path}: service image reference is not allowlisted")

    runners = re.findall(r"^\s*runs-on:\s*([^\s#]+)", text, re.MULTILINE)
    if not runners:
        failures.append(f"{path}: workflow has no explicit runner")
    for runner in runners:
        if runner not in ALLOWED_RUNNERS:
            failures.append(f"{path}: runner identity is not allowlisted: {runner}")

    checkout_starts = [match.start() for match in re.finditer(r"uses:\s*actions/checkout@", text)]
    for start in checkout_starts:
        block = text[start : start + 260]
        if "persist-credentials: false" not in block:
            failures.append(f"{path}: checkout must set persist-credentials: false")
        if "fetch-depth: 0" not in block:
            failures.append(f"{path}: checkout must set fetch-depth: 0")

    jobs_text = text.split("\njobs:\n", maxsplit=1)[1] if "\njobs:\n" in text else ""
    job_count = len(re.findall(r"^  [a-zA-Z0-9_-]+:\n", jobs_text, flags=re.MULTILINE))
    timeout_count = len(
        re.findall(r"^    timeout-minutes:\s*\d+", jobs_text, flags=re.MULTILINE)
    )
    if timeout_count < job_count:
        failures.append(
            f"{path}: every job needs timeout-minutes ({timeout_count}/{job_count})"
        )

    job_ids = set(re.findall(r"^  ([a-zA-Z0-9_-]+):\n", jobs_text, flags=re.MULTILINE))
    required_block = jobs_text.split("\n  required:\n", maxsplit=1)[1] if "\n  required:\n" in jobs_text else ""
    if not re.search(r"^    if:\s*\$\{\{ always\(\) \}\}\s*$", required_block, re.MULTILINE):
        failures.append(f"{path}: required aggregator must run with if: always()")
    needs_match = re.search(r"^    needs:\s*\[([^\]]*)\]", required_block, re.MULTILINE)
    actual_needs = {
        value.strip() for value in needs_match.group(1).split(",") if value.strip()
    } if needs_match else set()
    expected_needs = job_ids - {"required"}
    if actual_needs != expected_needs:
        failures.append(
            f"{path}: required aggregator needs {sorted(actual_needs)}, expected {sorted(expected_needs)}"
        )
    result_contract = (
        "RESULTS: ${{ toJSON(needs) }}",
        'if not results or any(value != "success" for value in results.values()):',
        'sys.exit("one or more required jobs did not succeed")',
    )
    if any(fragment not in required_block for fragment in result_contract):
        failures.append(f"{path}: required aggregator lacks the fail-closed needs result contract")
    required_steps = _step_blocks(required_block)
    if len(required_steps) != 1:
        failures.append(f"{path}: required aggregator must contain exactly one step")
    else:
        required_step = required_steps[0]
        if re.search(r"^        (?:if|shell):", required_step, re.MULTILINE):
            failures.append(
                f"{path}: required aggregator step may not override its condition or shell"
            )
        result_env = re.findall(
            r"^          RESULTS:\s*(.*?)\s*$", required_step, re.MULTILINE
        )
        if result_env != ["${{ toJSON(needs) }}"]:
            failures.append(f"{path}: required aggregator needs the exact needs JSON input")
        if _run_payload(required_step) != EXPECTED_REQUIRED_RUN:
            failures.append(f"{path}: required aggregator command differs from the exact fail-closed contract")

    for match in re.finditer(
        r"^\s+[a-zA-Z0-9_-]+:\s*[\"']?write[\"']?\s*$",
        text,
        re.MULTILINE,
    ):
        failures.append(f"{path}: workflow requests a write permission: {match.group(0).strip()}")
    if re.search(r"^\s*permissions:\s*write-all\s*$", text, re.MULTILINE):
        failures.append(f"{path}: workflow requests permissions: write-all")

    contracts = EVIDENCE_CONTRACTS.get(path.name, {})
    upload_jobs: set[str] = set()
    job_matches = list(re.finditer(r"^  ([a-zA-Z0-9_-]+):\n", jobs_text, re.MULTILINE))
    for index, match in enumerate(job_matches):
        job_id = match.group(1)
        end = job_matches[index + 1].start() if index + 1 < len(job_matches) else len(jobs_text)
        job_block = jobs_text[match.start():end]
        steps = _step_blocks(job_block)
        upload_indexes = [
            step_index
            for step_index, step in enumerate(steps)
            if re.search(
                r"^(?:      - |        )uses:\s*actions/upload-artifact@",
                step,
                re.MULTILINE,
            )
        ]
        if not upload_indexes:
            continue
        upload_jobs.add(job_id)
        if len(upload_indexes) != 1:
            failures.append(f"{path}: job {job_id} must have exactly one artifact upload")
        if job_id not in contracts:
            failures.append(f"{path}: job {job_id} has no canonical evidence contract")
            continue

        source, destination, profile = contracts[job_id]
        upload_index = upload_indexes[0]
        canonical_job = _canonical_shell(job_block)
        if "prepare_uploadable_evidence.py" not in canonical_job:
            failures.append(
                f"{path}: job {job_id} is missing structured evidence preparation"
            )
        if "evidence_manifest.py --seal" not in canonical_job:
            failures.append(
                f"{path}: job {job_id} is missing evidence manifest seal step"
            )
        ids = [_step_id(step) for step in steps]
        required_ids = (
            "evidence_prepare",
            "evidence_manifest",
            "evidence_privacy",
            "evidence_integrity",
            "evidence_schema",
        )
        id_indexes: list[int] = []
        for required_id in required_ids:
            indexes = [step_index for step_index, value in enumerate(ids) if value == required_id]
            if len(indexes) != 1:
                failures.append(
                    f"{path}: job {job_id} needs exactly one {required_id} step"
                )
            else:
                id_indexes.append(indexes[0])
        if len(id_indexes) != len(required_ids):
            continue
        result_indexes = [
            step_index
            for step_index, value in enumerate(ids)
            if value == "evidence_result"
        ]
        if len(result_indexes) != 1:
            failures.append(
                f"{path}: job {job_id} needs exactly one evidence_result step"
            )
            continue
        result_index = result_indexes[0]
        if id_indexes + [upload_index, result_index] != list(
            range(id_indexes[0], id_indexes[0] + len(required_ids) + 2)
        ):
            failures.append(
                f"{path}: job {job_id} evidence chain must be adjacent and ordered "
                "prepare, seal, scan, reverify, validate, upload, require-pass"
            )

        expected_commands = (
            f"prepare_uploadable_evidence.py --profile {profile} {source} {destination}",
            f"evidence_manifest.py --seal {destination}",
            f"scan_evidence.py {destination}",
            f"evidence_manifest.py --verify {destination}",
            f"prepare_uploadable_evidence.py --validate-attestation {destination}",
        )
        for required_id, step_index, expected_command in zip(
            required_ids, id_indexes, expected_commands
        ):
            step = steps[step_index]
            if re.search(
                r"^        (?:env|shell|working-directory):", step, re.MULTILINE
            ):
                failures.append(
                    f"{path}: job {job_id} {required_id} may not override its environment, shell or working directory"
                )
            always = re.findall(
                r"^        if:\s*(.*?)\s*$", step, re.MULTILINE
            )
            if always != ["${{ always() }}"]:
                failures.append(
                    f"{path}: job {job_id} {required_id} must use exact if: always()"
                )
            command = _run_payload(step)
            if command is None:
                failures.append(
                    f"{path}: job {job_id} {required_id} needs one explicit command"
                )
                continue
            canonical = _canonical_shell(command)
            if re.search(r"(?:\|\||&&|;|\n)", command):
                failures.append(
                    f"{path}: job {job_id} {required_id} contains a shell control operator"
                )
            exact_command = re.compile(
                r"^python(?:3)? \$GITHUB_WORKSPACE/scripts/ci/"
                + re.escape(expected_command)
                + r"$"
            )
            if not exact_command.fullmatch(canonical):
                failures.append(
                    f"{path}: job {job_id} {required_id} is not the exact canonical evidence command"
                )
            script_name = expected_command.split(maxsplit=1)[0]
            if canonical.count(script_name) != 1:
                failures.append(
                    f"{path}: job {job_id} {required_id} must invoke its evidence tool exactly once"
                )

        upload_step = steps[upload_index]
        upload_conditions = re.findall(
            r"^        if:\s*(.*?)\s*$", upload_step, re.MULTILINE
        )
        if upload_conditions != [EXPECTED_UPLOAD_IF]:
            failures.append(
                f"{path}: job {job_id} upload condition must be the exact fail-closed contract"
            )
        path_values = re.findall(
            r"^          path:\s*(.*?)\s*$", upload_step, re.MULTILINE
        )
        normalized_paths = [_canonical_shell(value) for value in path_values]
        if normalized_paths != [destination]:
            failures.append(
                f"{path}: job {job_id} upload path must be one exact canonical scalar"
            )
        if re.findall(
            r"^          if-no-files-found:\s*(.*?)\s*$", upload_step, re.MULTILINE
        ) != ["error"]:
            failures.append(
                f"{path}: job {job_id} upload must fail when evidence is missing"
            )
        if re.findall(
            r"^          include-hidden-files:\s*(.*?)\s*$", upload_step, re.MULTILINE
        ) != ["false"]:
            failures.append(
                f"{path}: job {job_id} upload must exclude hidden files"
            )

        result_step = steps[result_index]
        if re.search(
            r"^        (?:env|shell|working-directory):", result_step, re.MULTILINE
        ):
            failures.append(
                f"{path}: job {job_id} evidence_result may not override its environment, shell or working directory"
            )
        if re.findall(
            r"^        if:\s*(.*?)\s*$", result_step, re.MULTILINE
        ) != ["${{ always() }}"]:
            failures.append(
                f"{path}: job {job_id} evidence_result must use exact if: always()"
            )
        result_command = _run_payload(result_step)
        expected_result = re.compile(
            r"^python(?:3)? \$GITHUB_WORKSPACE/scripts/ci/"
            r"prepare_uploadable_evidence\.py --require-pass "
            + re.escape(destination)
            + r"$"
        )
        if (
            result_command is None
            or not expected_result.fullmatch(_canonical_shell(result_command))
        ):
            failures.append(
                f"{path}: job {job_id} evidence_result command is not exact"
            )

    for expected_job in sorted(set(contracts) - upload_jobs):
        failures.append(
            f"{path}: canonical evidence job {expected_job} is missing its artifact upload"
        )

    return failures


def _python_alembic_calls(tree: ast.AST) -> list[ast.Call]:
    command_names = {
        target.id
        for node in ast.walk(tree)
        if isinstance(node, (ast.Assign, ast.AnnAssign))
        for target in (
            node.targets if isinstance(node, ast.Assign) else [node.target]
        )
        if isinstance(target, ast.Name)
        and isinstance(node.value, (ast.List, ast.Tuple))
        and any(
            isinstance(item, ast.Constant) and item.value == "alembic"
            for item in ast.walk(node.value)
        )
    }
    calls: list[ast.Call] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        direct_api = any(
            isinstance(item, ast.Name)
            and item.id in {"alembic", "alembic_command"}
            for item in ast.walk(node.func)
        )
        command = node.args[0] if node.args else None
        command_literal = command is not None and any(
            isinstance(item, ast.Constant) and item.value == "alembic"
            for item in ast.walk(command)
        )
        assigned_command = command is not None and any(
            isinstance(item, ast.Name) and item.id in command_names
            for item in ast.walk(command)
        )
        if direct_api or command_literal or assigned_command:
            calls.append(node)
    return calls


def _call_has_exact_isolated_environment(call: ast.Call) -> bool:
    environment = next(
        (keyword.value for keyword in call.keywords if keyword.arg == "env"),
        None,
    )
    if not isinstance(environment, ast.Dict):
        return False
    matches = [
        index
        for index, (key, value) in enumerate(
            zip(environment.keys, environment.values)
        )
        if isinstance(key, ast.Constant)
        and key.value == NYAY19_ISOLATED_MIGRATION_ENV
        and isinstance(value, ast.Constant)
        and value.value == "1"
    ]
    # The exact authority must be the final dictionary item. A later **mapping
    # could otherwise replace it at runtime while leaving a misleading literal
    # in the source for a weak static checker to find.
    return matches == [len(environment.keys) - 1]


def _production_wrapper_is_fail_closed(tree: ast.AST, call: ast.Call) -> bool:
    call_line = getattr(call, "lineno", 0)
    environment_keyword = next(
        (keyword.value for keyword in call.keywords if keyword.arg == "env"),
        None,
    )
    command = call.args[0]
    command_nodes = list(ast.walk(command))
    if (
        not isinstance(environment_keyword, ast.Name)
        or environment_keyword.id != "environment"
        or not any(
            isinstance(node, ast.Constant) and node.value == "upgrade"
            for node in command_nodes
        )
        or not any(
            isinstance(node, ast.Name) and node.id == "TARGET_REVISION"
            for node in command_nodes
        )
    ):
        return False

    copied_environment = False
    removed_isolated_authority = False
    forced_production_approval = False
    for node in ast.walk(tree):
        if getattr(node, "lineno", call_line + 1) >= call_line:
            continue
        if isinstance(node, ast.Assign) and any(
            isinstance(target, ast.Name) and target.id == "environment"
            for target in node.targets
        ):
            copied_environment = (
                isinstance(node.value, ast.Call)
                and isinstance(node.value.func, ast.Name)
                and node.value.func.id == "dict"
                and bool(node.value.args)
                and isinstance(node.value.args[0], ast.Attribute)
                and isinstance(node.value.args[0].value, ast.Name)
                and node.value.args[0].value.id == "os"
                and node.value.args[0].attr == "environ"
            )
        if isinstance(node, ast.For) and isinstance(node.target, ast.Name):
            isolated_in_iterable = any(
                isinstance(item, ast.Name)
                and item.id == "ISOLATED_EXECUTION_ENV"
                for item in ast.walk(node.iter)
            )
            removes_loop_name = any(
                isinstance(item, ast.Call)
                and isinstance(item.func, ast.Attribute)
                and isinstance(item.func.value, ast.Name)
                and item.func.value.id == "environment"
                and item.func.attr == "pop"
                and bool(item.args)
                and isinstance(item.args[0], ast.Name)
                and item.args[0].id == node.target.id
                for statement in node.body
                for item in ast.walk(statement)
            )
            removed_isolated_authority = (
                removed_isolated_authority
                or (isolated_in_iterable and removes_loop_name)
            )
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and isinstance(node.func.value, ast.Name)
            and node.func.value.id == "environment"
            and node.func.attr == "update"
            and node.args
            and isinstance(node.args[0], ast.Dict)
        ):
            values: dict[str, object] = {}
            for key, value in zip(node.args[0].keys, node.args[0].values):
                if isinstance(key, ast.Constant) and isinstance(key.value, str):
                    name = key.value
                elif isinstance(key, ast.Name):
                    name = key.id
                else:
                    continue
                if isinstance(value, ast.Constant):
                    values[name] = value.value
            forced_production_approval = (
                forced_production_approval
                or values.get("APP_ENV") == "production"
                and values.get("FORCE_APPROVAL_ENV") == "1"
            )
    return copied_environment and removed_isolated_authority and forced_production_approval


def _shell_executable_source(source: str) -> str:
    return "\n".join(
        line.split("#", 1)[0]
        for line in source.splitlines()
        if not line.lstrip().startswith("#")
    )


def check_alembic_execution_contracts(root: Path = ROOT) -> list[str]:
    """Inventory every shipped Alembic entry point and seal its authority."""

    failures: list[str] = []
    root = Path(root)
    python_callers: set[str] = set()
    python_root = root / "backend" / "scripts"
    if python_root.is_dir():
        for path in sorted(python_root.rglob("*.py")):
            if path.is_symlink():
                failures.append(f"{path}: Alembic script inventory may not contain symlinks")
                continue
            try:
                tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            except (OSError, UnicodeError, SyntaxError) as exc:
                failures.append(
                    f"{path}: Python script cannot be audited: {type(exc).__name__}"
                )
                continue
            calls = _python_alembic_calls(tree)
            if not calls:
                continue
            relative = path.relative_to(root).as_posix()
            python_callers.add(relative)
            if relative == "backend/scripts/nyay19_migrate.py":
                if len(calls) != 1 or not _production_wrapper_is_fail_closed(
                    tree, calls[0]
                ):
                    failures.append(
                        f"{path}: production Alembic wrapper must remove isolated authority and force exact approval"
                    )
                continue
            for call in calls:
                if not _call_has_exact_isolated_environment(call):
                    failures.append(
                        f"{path}:{getattr(call, 'lineno', 0)}: missing exact isolated subprocess authority"
                    )

    shell_callers: set[str] = set()
    shell_roots = (root / "backend" / "scripts", root / "scripts")
    shell_paths = {
        path
        for shell_root in shell_roots
        if shell_root.is_dir()
        for path in shell_root.rglob("*.sh")
    }
    for path in sorted(shell_paths):
        if path.is_symlink():
            failures.append(f"{path}: Alembic shell inventory may not contain symlinks")
            continue
        try:
            source = path.read_text(encoding="utf-8")
        except (OSError, UnicodeError) as exc:
            failures.append(f"{path}: shell script cannot be audited: {type(exc).__name__}")
            continue
        executable = _shell_executable_source(source)
        if (
            "-m alembic" not in executable
            and re.search(
                r"(?:^|[;&|(]\s*)alembic\s+(?:upgrade|downgrade|check|current|stamp)\b",
                executable,
                re.MULTILINE,
            ) is None
        ):
            continue
        relative = path.relative_to(root).as_posix()
        shell_callers.add(relative)
        classification = EXPECTED_NYAY19_ALEMBIC_SHELL_CALLERS.get(relative)
        if classification is None:
            failures.append(f"{path}: unclassified Alembic shell caller")
        elif classification == "isolated-postgresql":
            if re.findall(
                rf"^export {re.escape(NYAY19_ISOLATED_MIGRATION_ENV)}=1$",
                executable,
                re.MULTILINE,
            ) != [f"export {NYAY19_ISOLATED_MIGRATION_ENV}=1"]:
                failures.append(
                    f"{path}: missing exact isolated shell authority"
                )
        elif classification == "local-sqlite":
            if (
                NYAY19_ISOLATED_MIGRATION_ENV in executable
                or 'export DATABASE_URL="sqlite+pysqlite:///$DB_FILE"' not in executable
                or "export APP_ENV=development" not in executable
            ):
                failures.append(
                    f"{path}: local SQLite Alembic caller must not receive PostgreSQL isolated authority"
                )

    workflow_root = root / ".github" / "workflows"
    seen_workflow_callers: set[tuple[str, str]] = set()
    if workflow_root.is_dir() and yaml is not None:
        workflow_paths = sorted(workflow_root.glob("*.yml")) + sorted(
            workflow_root.glob("*.yaml")
        )
        for path in workflow_paths:
            try:
                document = yaml.load(
                    path.read_text(encoding="utf-8"),
                    Loader=_NoDuplicateBaseLoader,
                )
            except (OSError, UnicodeError, yaml.YAMLError):
                failures.append(f"{path}: workflow cannot be audited for Alembic authority")
                continue
            document_mapping = _mapping(document)
            jobs = _mapping(document_mapping.get("jobs")) if document_mapping else None
            if jobs is None:
                failures.append(f"{path}: workflow jobs cannot be audited for Alembic authority")
                continue
            failures.extend(_nyay19_workflow_alembic_failures(path, jobs))
            seen_workflow_callers.update(
                (path.name, job_id)
                for job_id in jobs
                if (path.name, job_id) in EXPECTED_NYAY19_ALEMBIC_WORKFLOW_JOBS
            )

        for missing in sorted(
            set(EXPECTED_NYAY19_ALEMBIC_WORKFLOW_JOBS) - seen_workflow_callers
        ):
            failures.append(
                f"{workflow_root}: missing NYAY-19 isolated Alembic workflow caller {missing}"
            )
        if python_callers != EXPECTED_NYAY19_ALEMBIC_PYTHON_CALLERS:
            failures.append(
                f"{python_root}: Alembic Python caller inventory differs from the sealed contract; "
                f"found={sorted(python_callers)}"
            )
        if shell_callers != set(EXPECTED_NYAY19_ALEMBIC_SHELL_CALLERS):
            failures.append(
                f"{root}: Alembic shell caller inventory differs from the sealed contract; "
                f"found={sorted(shell_callers)}"
            )
    return failures


def main() -> int:
    workflow_paths = sorted(WORKFLOWS.glob("*.yml")) + sorted(WORKFLOWS.glob("*.yaml"))
    if not workflow_paths:
        print("no workflows found", file=sys.stderr)
        return 1

    failures: list[str] = []
    if {path.name for path in workflow_paths} != CANONICAL_WORKFLOW_FILES:
        failures.append(
            "workflow filename inventory differs from the seven canonical required gates"
        )
    failures.extend(check_db_gate_contract())
    failures.extend(check_nyay4_browser_gate_contract())
    failures.extend(check_nyay19_browser_gate_contract())
    failures.extend(check_alembic_execution_contracts())
    failures.extend(
        failure for path in workflow_paths for failure in check_workflow(path)
    )
    required_names: list[tuple[Path, str]] = []
    for path in workflow_paths:
        text = path.read_text(encoding="utf-8")
        match = re.search(r"^  required:\n    name:\s*([^\s#]+)", text, re.MULTILINE)
        if not match:
            failures.append(f"{path}: required aggregator needs an explicit stable name")
            continue
        name = match.group(1)
        required_names.append((path, name))
        if not re.fullmatch(r"nyayone-[a-z0-9-]+-required", name):
            failures.append(f"{path}: invalid required check name: {name}")
    counts = {name: sum(candidate == name for _, candidate in required_names) for _, name in required_names}
    for path, name in required_names:
        if counts[name] != 1:
            failures.append(f"{path}: duplicate required check name: {name}")
    if failures:
        print("\n".join(failures), file=sys.stderr)
        return 1

    print(f"NyayOne workflow policy passed for {len(workflow_paths)} workflows")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
