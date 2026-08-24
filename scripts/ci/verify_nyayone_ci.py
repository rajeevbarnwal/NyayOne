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
NYAY5_BROWSER_ORCHESTRATOR = ROOT / "scripts" / "nyay5_profile_browser_gate.sh"
NYAY5_BROWSER_GATE = ROOT / "frontend" / "scripts" / "nyay5-profile-browser.mjs"
NYAY5_BROWSER_CONTRACT = (
    ROOT / "frontend" / "scripts" / "lib" / "nyay5-profile-browser-contract.mjs"
)
NYAY5_BROWSER_CONTRACT_TEST = (
    ROOT
    / "frontend"
    / "scripts"
    / "lib"
    / "nyay5-profile-browser-contract.test.mjs"
)
NYAY5_BROWSER_CONTROL = ROOT / "backend" / "scripts" / "nyay5_browser_gate_control.py"
NYAY5_POSTGRES_GATE = ROOT / "backend" / "scripts" / "nyay5_postgres_profile_gate.py"
NYAY5_ACCEPTANCE_AGGREGATE = (
    ROOT / "frontend" / "scripts" / "nyay5-acceptance-aggregate.mjs"
)
NYAY5_ACCEPTANCE_AGGREGATE_TEST = (
    ROOT
    / "frontend"
    / "scripts"
    / "lib"
    / "nyay5-acceptance-aggregate.test.mjs"
)
NYAY5_ACCEPTANCE_ATTESTATION_PRODUCER = (
    ROOT / "scripts" / "ci" / "nyay5_acceptance_attestations.py"
)
NYAY5_ACCEPTANCE_ATTESTATION_TEST = (
    ROOT / "scripts" / "ci" / "test_nyay5_acceptance_attestations.py"
)
NYAY18_NAMESPACE_GATE = (
    ROOT / "scripts" / "ci" / "check_nyay18_frontend_namespaces.py"
)
NYAY18_NAMESPACE_GATE_TEST = (
    ROOT / "scripts" / "ci" / "test_nyay18_namespace_policy.py"
)
NYAY18_NAMESPACE_CONTRACT = (
    ROOT / "scripts" / "ci" / "nyay18_namespace_contract.json"
)
NYAY18_NAMESPACE_BOUNDARY_DOCUMENT = (
    ROOT / "docs" / "architecture" / "nyay18-frontend-browser-mobile-namespace-boundary.md"
)
NYAY18_NAMESPACE_BOUNDARY_DOCUMENT_TEST = (
    ROOT / "scripts" / "ci" / "test_nyay18_namespace_boundary_doc.py"
)
NYAY18_BROWSER_ORCHESTRATOR = ROOT / "scripts" / "nyay18_browser_namespace_gate.sh"
NYAY18_BROWSER_GATE = (
    ROOT / "frontend" / "scripts" / "nyay18-browser-namespace.mjs"
)
NYAY18_BROWSER_PREVIEW_SERVER = (
    ROOT / "frontend" / "scripts" / "nyay18-preview-server.mjs"
)
NYAY18_BROWSER_CONTRACT = (
    ROOT / "frontend" / "scripts" / "lib" / "nyay18-browser-contract.mjs"
)
NYAY18_BROWSER_CONTRACT_TEST = (
    ROOT
    / "frontend"
    / "scripts"
    / "lib"
    / "nyay18-browser-contract.test.mjs"
)
FRONTEND_PACKAGE = ROOT / "frontend" / "package.json"
EXPECTED_NYAY4_BROWSER_GATE_SHA256 = (
    "ba667ee265ac8ebc039818c4a39301e81568b8fa4a2865f6a6550e2ec6d74d67"
)
EXPECTED_NYAY4_BROWSER_CONTRACT_SHA256 = (
    "c45e97b73d2f180683fe890578fcaac877045f58bc005489c0f7a21939b35b38"
)
EXPECTED_NYAY4_PACKAGE_COMMAND = "node scripts/nyay4-otp-browser-negative.mjs"
EXPECTED_NYAY19_BROWSER_GATE_SHA256 = (
    "011a07b3b702b5145c5154ca806d6569c4fa4ed2ba94a4c79a65e8462f535ff8"
)
EXPECTED_NYAY19_BROWSER_CONTRACT_SHA256 = (
    "7ac2e8fcf4d914d58584f48eb90538dcaebd0c2b222bdcb18bb9066e0d303f6b"
)
EXPECTED_NYAY19_BROWSER_CONTRACT_TEST_SHA256 = (
    "f40bddec8452e9121ab73f2903e9597254c4136d9179673ef32403a0677516ca"
)
EXPECTED_NYAY19_PACKAGE_COMMAND = "node scripts/nyay19-auth-lifecycle-browser.mjs"
EXPECTED_NYAY5_BROWSER_ORCHESTRATOR_SHA256 = (
    "066cb849ec74668544a3489044fac0b7ce5eb54274567f66de3c11ede89a4afc"
)
EXPECTED_NYAY5_BROWSER_GATE_SHA256 = (
    "5a547684bc1441dde1bf129b92f3ea3d978cdb7ab8549b9f5ec4ef3974dd3c87"
)
EXPECTED_NYAY5_BROWSER_CONTRACT_SHA256 = (
    "b3e7323128d4a50ccd80c8605bf9ae8000f4d3059345e7ec9e66f0fc43fa2e72"
)
EXPECTED_NYAY5_BROWSER_CONTRACT_TEST_SHA256 = (
    "239a02072766ccfa12bcd21adb8ccab97bd72fcdeef5bfb15a377759ac6d8336"
)
EXPECTED_NYAY5_BROWSER_CONTROL_SHA256 = (
    "d24b07f325adc630756a6821bd11fecedbcddc76ae42c8cbf5f783ef9615fba8"
)
EXPECTED_NYAY5_POSTGRES_GATE_SHA256 = (
    "b696de5cb796262eaf8ba0b7c9b9a38faae01386e10b6d94c7b26cfb17b4db9b"
)
EXPECTED_NYAY5_ACCEPTANCE_AGGREGATE_SHA256 = (
    "1b0fcb0dfa8238d648d04c27e5abb99ac17add6cd667a0d336ac7dc7030de4ca"
)
EXPECTED_NYAY5_ACCEPTANCE_AGGREGATE_TEST_SHA256 = (
    "efe6745a2e10be9b60cdaae3d62ac1f6865e34a115dcf0c7073793edfd649720"
)
EXPECTED_NYAY5_ACCEPTANCE_ATTESTATION_SHA256 = (
    "98b2b033e87083d4d17246c57fe1765501dcba1cbb8bd2415a66631bcd2d5c32"
)
EXPECTED_NYAY5_ACCEPTANCE_ATTESTATION_TEST_SHA256 = (
    "8768b19f049a803981f37b0378a4e922c8f1c96e20a3fa7c62dbccb900adc13e"
)
EXPECTED_NYAY18_NAMESPACE_GATE_SHA256 = (
    "0421cd86f9624f41e45704fc0917f45313d4aa034dc94b8429be0a87afcc037d"
)
EXPECTED_NYAY18_NAMESPACE_GATE_TEST_SHA256 = (
    "4b7656f92dfc930187e1b55df241529149624f205df24493664e4d885e128564"
)
EXPECTED_NYAY18_NAMESPACE_CONTRACT_SHA256 = (
    "2254d3f0f7de6aafee1b99ca50c7e38daf950d22cf7391fad3f7cf54979073c9"
)
EXPECTED_NYAY18_NAMESPACE_BOUNDARY_DOCUMENT_SHA256 = (
    "4ea549791f349857460e6f65ba274aee81caa0031ed49a426585ff7fdf6e919c"
)
EXPECTED_NYAY18_NAMESPACE_BOUNDARY_DOCUMENT_TEST_SHA256 = (
    "cb0133a5d7ab7e34314139212983c5f653d3624125d0ce5dd3da5782d1649368"
)
EXPECTED_NYAY18_BROWSER_ORCHESTRATOR_SHA256 = (
    "9eb4089410b79d6ef4fd786f79cf6ae92bedf8448ccdf4340ada54acc6da9592"
)
EXPECTED_NYAY18_BROWSER_GATE_SHA256 = (
    "52cc51ab82889b88bf8595e654a0b6f154dfba70958dd2f98acc9725eb64d195"
)
EXPECTED_NYAY18_BROWSER_PREVIEW_SERVER_SHA256 = (
    "935cf8f4039bd6577aa376b799359878d108ea44d3126e932bbb818a7344959c"
)
EXPECTED_NYAY18_BROWSER_CONTRACT_SHA256 = (
    "b595f89fdd2bba8016b795c5a6cbd5c68a7f29f37193f0aebb6b0fb6770b3932"
)
EXPECTED_NYAY18_BROWSER_CONTRACT_TEST_SHA256 = (
    "8abc31e7cc143864a6bcf1231726dc3d9550a0c1bff1a27d0560df63676e9612"
)
EXPECTED_NYAY18_BROWSER_PACKAGE_COMMAND = (
    "node scripts/nyay18-browser-namespace.mjs"
)
EXPECTED_NYAY18_BROWSER_ORCHESTRATOR_EXACT_HEAD = (
    'EXACT_COMMIT="$(git -C "$ROOT" rev-parse HEAD)"',
    'EXACT_TREE="$(git -C "$ROOT" rev-parse \'HEAD^{tree}\')"',
    'PARENT_LINE="$(git -C "$ROOT" rev-list --parents -n 1 HEAD)"',
    'NYAY18_EXACT_COMMIT="$EXACT_COMMIT"',
    'NYAY18_EXACT_TREE="$EXACT_TREE"',
    'NYAY18_EXACT_PARENT="$EXACT_PARENT"',
    'NYAY18_PREVIEW_ROOT="$ROOT/frontend/dist"',
    'NYAY18_PREVIEW_PORT="$PORT"',
    "exec node scripts/nyay18-preview-server.mjs",
    "npm run qa:nyay18:browser-namespace",
)
EXPECTED_NYAY18_BROWSER_GATE_EXACT_HEAD = (
    "const EXACT_COMMIT = requiredEnv('NYAY18_EXACT_COMMIT');",
    "const EXACT_TREE = requiredEnv('NYAY18_EXACT_TREE');",
    "const EXACT_PARENT = requiredEnv('NYAY18_EXACT_PARENT');",
    "commitMatchesHead: initialGit.head === EXACT_COMMIT,",
    "treeMatchesHead: initialGit.tree === EXACT_TREE,",
    "parentMatchesHead: initialGit.parent === EXACT_PARENT,",
    "worktreeClean: initialGit.clean,",
    "exactCommit: EXACT_COMMIT,",
    "exactTree: EXACT_TREE,",
    "exactParent: EXACT_PARENT,",
    "const inspection = inspectNyay18Evidence(report);",
)
EXPECTED_NYAY18_BROWSER_CONTRACT_EXACT_HEAD = (
    "'exactCommit', 'exactParent', 'exactTree'",
    "if (!COMMIT.test(report?.exactCommit ?? ''))",
    "if (!COMMIT.test(report?.exactTree ?? ''))",
    "if (report?.exactParent !== 'ROOT' && !COMMIT.test(report?.exactParent ?? ''))",
    "'bad-exact-commit'",
    "'bad-exact-tree'",
    "'bad-exact-parent'",
)
EXPECTED_NYAY18_BROWSER_CONTRACT_TEST_EXACT_HEAD = (
    "wrongTree.exactTree = 'bad';",
    "wrongParent.exactParent = 'bad';",
    "expect(source).toContain('exactTree: EXACT_TREE');",
    "expect(source).toContain('exactParent: EXACT_PARENT');",
)
EXPECTED_NYAY18_BROWSER_PREVIEW_SEMANTICS = (
    "const HOST = '127.0.0.1';",
    "requiredEnv('NYAY18_PREVIEW_ROOT')",
    "requiredEnv('NYAY18_PREVIEW_PORT')",
    "if (!path.isAbsolute(rootInput))",
    "if (relative.startsWith('..') || path.isAbsolute(relative)) return null;",
    "if (method !== 'GET' && method !== 'HEAD')",
    "if (pathname === METRICS_PATH)",
    "if (pathname === HOSTILE_ASSET_PATH)",
    "if (request.headers.cookie) metrics.hostileAssetCookieHeaders += 1;",
    "'Cache-Control': 'private, no-store'",
    "Vary: 'Cookie'",
    "PRIVATE_SENTINEL",
    "server.listen(PORT, HOST);",
)
EXPECTED_NYAY18_BROWSER_ORCHESTRATOR_PREVIEW_DIGEST = (
    "PREVIEW_SOURCE_SHA256=",
    "hashlib.sha256(pathlib.Path(sys.argv[1]).read_bytes()).hexdigest()",
    '"$ROOT/frontend/scripts/nyay18-preview-server.mjs"',
    'NYAY18_PREVIEW_SOURCE_SHA256="$PREVIEW_SOURCE_SHA256"',
)
EXPECTED_NYAY18_BROWSER_GATE_PREVIEW_DIGEST = (
    "const PREVIEW_SOURCE_SHA256 = requiredEnv('NYAY18_PREVIEW_SOURCE_SHA256');",
    "path.resolve(REPOSITORY, 'frontend/scripts/nyay18-preview-server.mjs')",
    "previewSourceMatches: previewSourceActual === PREVIEW_SOURCE_SHA256,",
    "previewServerSourceSha256: PREVIEW_SOURCE_SHA256,",
)
EXPECTED_NYAY18_BROWSER_CONTRACT_PREVIEW_DIGEST = (
    "'previewServerSourceSha256'",
    "if (!digest(report?.previewServerSourceSha256))",
    "'bad-preview-server-source-sha'",
)
EXPECTED_NYAY18_BROWSER_CONTRACT_TEST_PREVIEW_DIGEST = (
    "wrongPreviewSource.previewServerSourceSha256 = 'bad';",
    "expect(source).toContain('previewServerSourceSha256: PREVIEW_SOURCE_SHA256');",
    "'bad-preview-server-source-sha'",
)
EXPECTED_NYAY18_BROWSER_PREVIEW_INSTALL_SHELL = (
    "const ARM_SHELL_PATH = '/__nyay18-gate/arm-shell';",
    "const PRIVATE_SHELL_SENTINEL = 'nyay18-private-shell-sentinel';",
    "hostileShellCookieHeaders: 0",
    "hostileShellServerRequests: 0",
    "if (pathname === ARM_SHELL_PATH)",
    "hostileShellArmed = true;",
    "if (pathname === '/index.html' && hostileShellArmed)",
    "metrics.hostileShellServerRequests += 1;",
    "if (request.headers.cookie) metrics.hostileShellCookieHeaders += 1;",
)
EXPECTED_NYAY18_BROWSER_GATE_INSTALL_SHELL = (
    "fetch('/__nyay18-gate/arm-shell'",
    "hostileShellServerRequests === 1",
    "hostileShellCookieHeaders === 0",
    "privateCache.hostileShellEntries === 0",
)
EXPECTED_NYAY18_BROWSER_CONTRACT_INSTALL_SHELL = (
    "metrics.hostileShellServerRequests === 1",
    "metrics.hostileShellCookieHeaders === 0",
    "metrics.hostileShellEntries === 0",
    "'unexercised-hostile-shell-probe'",
    "'cookie-bearing-hostile-shell-fetch'",
    "'cached-hostile-private-shell'",
)
EXPECTED_NYAY18_BROWSER_CONTRACT_TEST_INSTALL_SHELL = (
    "'unexercised-hostile-shell-probe'",
    "'cookie-bearing-hostile-shell-fetch'",
    "'cached-hostile-private-shell'",
    "'hostileShellCookieHeaders'",
    "'hostileShellServerRequests'",
)
EXPECTED_NYAY18_BROWSER_GATE_TWO_REALM_PRIVACY = (
    "const migration = instrumentationCanaries.migration;",
    "const final = instrumentationCanaries.final;",
    "const sumAcrossDocuments = (key) => migration[key] + browser[key];",
    (
        "const detectedInBothDocuments = (key) => migration[key] === true "
        "&& final[key] === true;"
    ),
    "Number(migration.probeAvailable === true) + Number(final.probeAvailable === true)",
)
EXPECTED_NYAY18_BROWSER_CONTRACT_TWO_REALM_PRIVACY = (
    "metrics.instrumentationDocumentCount === 2",
    "'privacy-instrumentation-canary-missed'",
    "'single-privacy-probe-document'",
)
EXPECTED_NYAY18_BROWSER_CONTRACT_TEST_TWO_REALM_PRIVACY = (
    "metrics.instrumentationDocumentCount = 1;",
    "'privacy-instrumentation-canary-missed'",
    "'single-privacy-probe-document'",
    "'migrationPrivacyInstrumentation'",
)
EXPECTED_NYAY18_BROWSER_GATE_FINITE_LEADING_PURGE = (
    "NYAY18_LEADING_CANDIDATE_KEYS",
    "NYAY18_LEADING_TARGET_KEYS",
    "targetIndexBeforeBootstrap >= NYAY18_LEADING_UNRELATED_KEYS",
    "unrelatedBeforeTarget >= NYAY18_LEADING_UNRELATED_KEYS",
    "targetSurvivorsBeforeBootstrap === 1",
    "&& leading.leadingBeforeOwned && leading.targetRemoved && leading.valuesExact",
)
EXPECTED_NYAY18_BROWSER_CONTRACT_FINITE_LEADING_PURGE = (
    "'leading-target-survived'",
    "'targetRemoved', 'targetSurvivorsBeforeBootstrap', 'unrelatedBeforeTarget',",
    "&& metrics.targetRemoved === true",
    "&& metrics.targetSurvivorsBeforeBootstrap === 1",
)
EXPECTED_NYAY18_BROWSER_CONTRACT_TEST_FINITE_LEADING_PURGE = (
    "'leading-target-survived'",
    "metrics.targetRemoved = false;",
    "metrics.targetIndexBeforeBootstrap = 256;",
)
EXPECTED_NYAY18_BROWSER_GATE_ACTOR_ROTATION = (
    "const actorRotationResponse = name === 'actor_rotation'",
    "await actorRotationResponse;",
    "actorRotationRediscoveryResponses = 1;",
    "&& lifecycle.actorRotationRediscoveryResponses === 1",
)
EXPECTED_NYAY18_BROWSER_CONTRACT_ACTOR_ROTATION = (
    "'actor-rotation-unobserved'",
    "'actorRotation', 'actorRotationRediscoveryResponses',",
    "&& metrics.actorRotationRediscoveryResponses === 1",
)
EXPECTED_NYAY18_BROWSER_CONTRACT_TEST_ACTOR_ROTATION = (
    "'actor-rotation-unobserved'",
    "metrics.actorRotationRediscoveryResponses = 0;",
    "'actorRotationRediscoveryResponses'",
)
EXPECTED_NYAY18_BROWSER_GATE_AUTHORITY_TRANSITIONS = (
    "'logout', 'expiry', 'deletion', 'revocation', 'canonical_loss',",
    "surface.transitionStarts === 1 && surface.transitionEnds === 1",
    "lifecycle.transitionStarts === 5 && lifecycle.transitionEnds === 5",
)
EXPECTED_NYAY18_BROWSER_CONTRACT_AUTHORITY_TRANSITIONS = (
    "'lifecycle-missing-transition'",
    "&& metrics.transitionStarts === 5",
    "&& metrics.transitionEnds === 5",
)
EXPECTED_NYAY18_BROWSER_CONTRACT_TEST_AUTHORITY_TRANSITIONS = (
    "'lifecycle-missing-transition'",
)
EXPECTED_NYAY5_BROWSER_PACKAGE_COMMAND = "node scripts/nyay5-profile-browser.mjs"
EXPECTED_NYAY5_ACCEPTANCE_PACKAGE_COMMAND = (
    "node scripts/nyay5-acceptance-aggregate.mjs"
)
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
    ("nyay5-profile-boundary-gate.yml", "profile-postgres-production-browser"): (
        "bash scripts/db_gate.sh",
    ),
}
EXPECTED_NYAY19_ALEMBIC_PYTHON_CALLERS = {
    "backend/scripts/nyay2_postgres_authorization_gate.py",
    "backend/scripts/nyay3_postgres_characterization.py",
    "backend/scripts/nyay4_postgres_otp_gate.py",
    "backend/scripts/nyay5_postgres_profile_gate.py",
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
    "scripts/nyay5_profile_browser_gate.sh": "nyay5-owned-scratch-postgresql",
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
EXPECTED_DB_GATE_SHA256 = "648fc1a3959edf7bc147a56b166c5b6bcfa00b66065a1ae0def43964fc277cec"
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
EXPECTED_NYAY5_DB_GATE_COMMAND = (
    'NYAY5_POSTGRES_GATE=1 "$PY" scripts/nyay5_postgres_profile_gate.py '
    '--execute --database-url "$DATABASE_URL" '
    "--output test-results/nyay5-postgres/summary.json"
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
    "nyay18-frontend-namespace-gate.yml",
    "nyayone-policy-gate.yml",
    "registration-db-gate.yml",
    "wave1-foundation-gate.yml",
    "wave2-tutoring-db-gate.yml",
    "wave3-credential-trust-gate.yml",
    "wave4-private-reporting-gate.yml",
    "wave5-calendar-gate.yml",
    "nyay5-profile-boundary-gate.yml",
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
EXPECTED_NYAY18_UPLOAD_IF = (
    "${{ always() && steps.browser_producer.outcome == 'success' && "
    "steps.browser_raw_manifest.outcome == 'success' && "
    "steps.browser_raw_integrity.outcome == 'success' && "
    "steps.browser_prepare.outcome == 'success' && "
    "steps.browser_manifest.outcome == 'success' && "
    "steps.browser_privacy.outcome == 'success' && "
    "steps.browser_integrity.outcome == 'success' }}"
)
EXPECTED_NYAY18_BROWSER_EVIDENCE_CHAIN: tuple[dict[str, object], ...] = (
    {
        "name": "Run exact-head production Chromium namespace producer",
        "id": "browser_producer",
        "run": (
            "bash scripts/nyay18_browser_namespace_gate.sh "
            '"$RUNNER_TEMP/nyay18-browser-raw/results.json"'
        ),
    },
    {
        "name": "Seal raw Chromium evidence inventory",
        "id": "browser_raw_manifest",
        "if": "${{ always() }}",
        "run": (
            'python scripts/ci/evidence_manifest.py --seal '
            '"$RUNNER_TEMP/nyay18-browser-raw"'
        ),
    },
    {
        "name": "Reverify raw Chromium evidence inventory",
        "id": "browser_raw_integrity",
        "if": "${{ always() }}",
        "run": (
            'python scripts/ci/evidence_manifest.py --verify '
            '"$RUNNER_TEMP/nyay18-browser-raw"'
        ),
    },
    {
        "name": "Prepare privacy-safe textual Chromium attestation",
        "id": "browser_prepare",
        "run": (
            'mkdir -p "$RUNNER_TEMP/nyay18-browser-uploadable"\n'
            'install -m 0600 "$RUNNER_TEMP/nyay18-browser-raw/results.json" '
            '"$RUNNER_TEMP/nyay18-browser-uploadable/results.json"\n'
            'install -m 0600 "$RUNNER_TEMP/nyay18-browser-raw/SHA256SUMS.txt" '
            '"$RUNNER_TEMP/nyay18-browser-uploadable/RAW-SHA256SUMS.txt"\n'
        ),
    },
    {
        "name": "Seal uploadable Chromium attestation",
        "id": "browser_manifest",
        "if": "${{ always() }}",
        "run": (
            'python scripts/ci/evidence_manifest.py --seal '
            '"$RUNNER_TEMP/nyay18-browser-uploadable"'
        ),
    },
    {
        "name": "Scan textual Chromium attestation for privacy regressions",
        "id": "browser_privacy",
        "if": "${{ always() }}",
        "run": (
            'python scripts/ci/scan_evidence.py '
            '"$RUNNER_TEMP/nyay18-browser-uploadable"'
        ),
    },
    {
        "name": "Reverify immutable uploadable Chromium attestation",
        "id": "browser_integrity",
        "if": "${{ always() }}",
        "run": (
            'python scripts/ci/evidence_manifest.py --verify '
            '"$RUNNER_TEMP/nyay18-browser-uploadable"'
        ),
    },
    {
        "name": "Upload NYAY-18 Chromium evidence",
        "if": EXPECTED_NYAY18_UPLOAD_IF,
        "uses": "actions/upload-artifact@ea165f8d65b6e75b540449e92b4886f43607fa02",
        "with": {
            "name": "nyay18-browser-namespace-attestation",
            "path": "${{ runner.temp }}/nyay18-browser-uploadable",
            "if-no-files-found": "error",
            "retention-days": "14",
            "include-hidden-files": "false",
        },
    },
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
EXPECTED_NYAY5_ATTESTATION_RUN = (
    'python scripts/ci/nyay5_acceptance_attestations.py --browser '
    '"$GITHUB_WORKSPACE/test-results/nyay5-browser/results.json" '
    '--orchestrator '
    '"$GITHUB_WORKSPACE/test-results/nyay5-browser/orchestrator-summary.json" '
    '--postgres "$GITHUB_WORKSPACE/test-results/nyay5-postgres/summary.json" '
    '--otp-postgres "$GITHUB_WORKSPACE/test-results/nyay4-postgres/summary.json" '
    '--manifest-root "$GITHUB_WORKSPACE/test-results/nyay5-browser" '
    '--output "$GITHUB_WORKSPACE/test-results/nyay5-acceptance/attestations.json"'
)
EXPECTED_NYAY5_ACCEPTANCE_RUN = (
    'npm run qa:nyay5:acceptance -- --browser '
    '"$GITHUB_WORKSPACE/test-results/nyay5-browser/results.json" '
    '--postgres "$GITHUB_WORKSPACE/test-results/nyay5-postgres/summary.json" '
    '--otp-postgres "$GITHUB_WORKSPACE/test-results/nyay4-postgres/summary.json" '
    '--attestations '
    '"$GITHUB_WORKSPACE/test-results/nyay5-acceptance/attestations.json" '
    '--output "$GITHUB_WORKSPACE/test-results/nyay5-acceptance/summary.json"'
)
EXPECTED_EXACT_STEPS: dict[tuple[str, str, str], dict[str, object]] = {
    (
        "nyay18-frontend-namespace-gate.yml",
        "namespace-production-chromium",
        "Prove the browser evidence contract and planted mutants",
    ): {
        "name": "Prove the browser evidence contract and planted mutants",
        "working-directory": "frontend",
        "run": "npm test -- --run scripts/lib/nyay18-browser-contract.test.mjs",
    },
    (
        "nyay5-profile-boundary-gate.yml",
        "profile-postgres-production-browser",
        "Seal and verify raw NYAY-5 browser evidence inventory",
    ): {
        "name": "Seal and verify raw NYAY-5 browser evidence inventory",
        "run": (
            'python scripts/ci/evidence_manifest.py --seal '
            '"$GITHUB_WORKSPACE/test-results/nyay5-browser"'
        ),
    },
    (
        "nyay5-profile-boundary-gate.yml",
        "profile-postgres-production-browser",
        "Produce executed NYAY-5 acceptance attestations",
    ): {
        "name": "Produce executed NYAY-5 acceptance attestations",
        "run": EXPECTED_NYAY5_ATTESTATION_RUN,
    },
    (
        "nyay5-profile-boundary-gate.yml",
        "profile-postgres-production-browser",
        "Run and require exact NYAY-5 acceptance aggregate PASS",
    ): {
        "name": "Run and require exact NYAY-5 acceptance aggregate PASS",
        "working-directory": "frontend",
        "run": EXPECTED_NYAY5_ACCEPTANCE_RUN,
    },
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
    "nyay5-profile-boundary-gate.yml": {
        "profile-postgres-production-browser": (
            "$GITHUB_WORKSPACE/test-results",
            "$RUNNER_TEMP/nyay5-uploadable",
            "nyay5",
        ),
    },
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
    ("nyay5-profile-boundary-gate.yml", "profile-postgres-production-browser"): {
        "DATABASE_URL": "postgresql+psycopg://nyayone_ci:nyayone_ci_ephemeral@127.0.0.1:5432/nyayone_nyay5_ci",
        "NYAY5_POSTGRES_CONTROL_URL": "postgresql+psycopg://nyayone_ci:nyayone_ci_ephemeral@127.0.0.1:5432/nyayone_nyay5_ci",
        "APP_ENV": "testing",
        "REGISTRATION_SECRET": "ci-nyay5-registration-encryption-secret-not-a-default",
        "REGISTRATION_LOOKUP_SECRET": "ci-nyay5-registration-lookup-secret-not-a-default",
        "NYAY19_ISOLATED_MIGRATION_EXECUTE": "1",
    },
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
    (
        "nyay18-frontend-namespace-gate.yml",
        "namespace-production-chromium",
    ): "nyay18-browser-namespace-attestation",
    (
        "nyay5-profile-boundary-gate.yml",
        "profile-postgres-production-browser",
    ): "nyay5-profile-boundary-attestation",
    ("wave1-foundation-gate.yml", "frontend-native"): "v34-s11-s26-browser-attestation",
    ("wave2-tutoring-db-gate.yml", "wave2-postgres-16-pgvector"): "wave2-tutoring-db-gate-attestation",
    ("wave3-credential-trust-gate.yml", "credential-trust-postgres-browser"): "wave3-credential-trust-attestation",
    ("wave4-private-reporting-gate.yml", "private-reporting-postgres-browser"): "wave4-private-reporting-attestation",
    ("wave5-calendar-gate.yml", "calendar-postgres"): "wave5-calendar-postgres-attestation",
    ("wave5-calendar-gate.yml", "calendar-real-browser"): "wave5-calendar-real-browser-attestation",
}
WAVE4_FAILURE_DIAGNOSTIC_UPLOAD = {
    "name": "Upload privacy-safe S-86/S-87 failure diagnostic",
    "condition": "${{ failure() }}",
    "producer": "npm run qa:wave4-reporting",
    "with": {
        "name": "wave4-reporting-failure-diagnostic",
        "path": "${{ github.workspace }}/test-results/wave4-browser/results.json",
        "if-no-files-found": "error",
        "retention-days": "14",
        "include-hidden-files": "false",
    },
}
NYAY4_FAILURE_DIAGNOSTIC_UPLOAD = {
    "name": "Upload privacy-safe NYAY-4 failure diagnostic",
    "condition": (
        "${{ failure() && "
        "hashFiles('backend/test-results/nyay4-postgres/summary.json') != '' }}"
    ),
    "producer": "PYTHON=python bash scripts/db_gate.sh",
    "with": {
        "name": "nyay4-postgres-failure-diagnostic",
        "path": (
            "${{ github.workspace }}/backend/test-results/nyay4-postgres/"
            "summary.json"
        ),
        "if-no-files-found": "error",
        "retention-days": "14",
        "include-hidden-files": "false",
    },
}
FAILURE_DIAGNOSTIC_UPLOADS = {
    (
        "wave4-private-reporting-gate.yml",
        "private-reporting-postgres-browser",
    ): WAVE4_FAILURE_DIAGNOSTIC_UPLOAD,
    (
        "wave1-foundation-gate.yml",
        "backend-postgres16-gate",
    ): NYAY4_FAILURE_DIAGNOSTIC_UPLOAD,
}
DIRECT_EVIDENCE_UPLOAD_PATHS: dict[tuple[str, str], str] = {
    (
        "nyay18-frontend-namespace-gate.yml",
        "namespace-production-chromium",
    ): "$RUNNER_TEMP/nyay18-browser-uploadable",
}
REQUIRED_JOB_RUNS: dict[tuple[str, str], set[str]] = {
    ("nyay18-frontend-namespace-gate.yml", "namespace-static-policy"): {
        "python scripts/ci/test_nyay18_namespace_boundary_doc.py",
        "python scripts/ci/test_nyay18_namespace_policy.py",
        (
            "python scripts/ci/check_nyay18_frontend_namespaces.py "
            "--output $RUNNER_TEMP/nyay18-static/summary.json"
        ),
    },
    ("nyay5-profile-boundary-gate.yml", "profile-postgres-production-browser"): {
        "(cd backend && PYTHON=python bash scripts/db_gate.sh)",
        "bash scripts/nyay5_profile_browser_gate.sh $GITHUB_WORKSPACE/test-results/nyay5-browser/results.json",
        "python scripts/ci/evidence_manifest.py --seal $GITHUB_WORKSPACE/test-results/nyay5-browser",
        (
            "python scripts/ci/nyay5_acceptance_attestations.py --browser "
            "$GITHUB_WORKSPACE/test-results/nyay5-browser/results.json "
            "--orchestrator $GITHUB_WORKSPACE/test-results/nyay5-browser/orchestrator-summary.json "
            "--postgres $GITHUB_WORKSPACE/test-results/nyay5-postgres/summary.json "
            "--otp-postgres $GITHUB_WORKSPACE/test-results/nyay4-postgres/summary.json "
            "--manifest-root $GITHUB_WORKSPACE/test-results/nyay5-browser "
            "--output $GITHUB_WORKSPACE/test-results/nyay5-acceptance/attestations.json"
        ),
    },
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
    EXPECTED_NYAY18_UPLOAD_IF,
}
NO_OP_RUN_COMMANDS = {":", "exit 0", "true"}
EXPECTED_JOB_SEMANTIC_SHA256: dict[tuple[str, str], str] = {
    (
        "nyay18-frontend-namespace-gate.yml",
        "namespace-static-policy",
    ): "43aeca7cc88ae6e4bf980117236dc3e69ce300e4937e3b9c3e8010e2a1c14e13",
    (
        "nyay18-frontend-namespace-gate.yml",
        "namespace-production-chromium",
    ): "2938507619c53fbaa0f319824c4324acdd0518a82dcbc73f02936f01c5b77d33",
    (
        "nyay18-frontend-namespace-gate.yml",
        "required",
    ): "26eb16eddb5471356ee193d4a0817cdab3466eb0d76e38a9aec7ed26bcb279ef",
    (
        "nyay5-profile-boundary-gate.yml",
        "profile-postgres-production-browser",
    ): "d87c17bf770e64a32ac3be6a1d6e480f104e2777e4f738c464cb05071ec05220",
    (
        "nyay5-profile-boundary-gate.yml",
        "required",
    ): "b54939ff87a54c12aa787cd364ef2700d6062a496fbcb08baf99730f5859e5ef",
    ("nyayone-policy-gate.yml", "policy-contracts"): "151bbfbfcab418fa90213523175b7b50ce0597d6504afcc2f5dd30eb79531838",
    ("nyayone-policy-gate.yml", "required"): "cb7fdec8df817040ee48f877cd06a82a80b252603c51a9bd1771abcdffbe54e2",
    ("registration-db-gate.yml", "postgres-16-pgvector"): "4a5fe899f88d2cd98ec5108af462f8f9c08e612459538ccf809fc3aa23500b26",
    ("registration-db-gate.yml", "required"): "826db470f5620527b0929811c10b0550f6ce56c37e1c0225957731358e2f4aee",
    ("wave1-foundation-gate.yml", "frontend-native"): "7cbafa269bc3a7c511f332cb626068e53bf185bd7d9528b2f4fac707ce1372d3",
    ("wave1-foundation-gate.yml", "backend-postgres16-gate"): "087d03fac8cc5b4105c10b187485581d934878b39185855132fd99d186dad652",
    ("wave1-foundation-gate.yml", "required"): "819f6d6b3187a38058f07e01be6573b315be27a9b296c2239731d33c12d8e67f",
    ("wave2-tutoring-db-gate.yml", "wave2-postgres-16-pgvector"): "449af3381247ff7d91c5b6c7a60ab220ecc63308af4553af6dd22a32bdaab758",
    ("wave2-tutoring-db-gate.yml", "required"): "3e311e18909eee9d1d5b63e2aa231a02296d1d17af0edbf5f3fb3f5609c6fd78",
    ("wave3-credential-trust-gate.yml", "credential-trust-postgres-browser"): "a5c8c25d7f98d6536e8b8968747a4b3f09ca6e01b8d23e2568dca2964a12ce35",
    ("wave3-credential-trust-gate.yml", "required"): "fb8b82abae6dcda07b3b8ab376d13882184fef23e2e17d7941a52656840e33de",
    ("wave4-private-reporting-gate.yml", "private-reporting-postgres-browser"): "97d1faf91f019d316ca23bcf72a95b05bc25e146b491434c8c6219100b43eeaa",
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
            diagnostic_contract = FAILURE_DIAGNOSTIC_UPLOADS.get(
                (path.name, job_id)
            )
            diagnostic_upload = bool(
                diagnostic_contract is not None
                and step.get("name") == diagnostic_contract["name"]
            )
            diagnostic_condition = (
                diagnostic_contract["condition"]
                if diagnostic_contract is not None
                else None
            )
            if (
                condition is not None
                and condition not in ALLOWED_STEP_CONDITIONS
                and not (diagnostic_upload and condition == diagnostic_condition)
            ):
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
                if diagnostic_upload:
                    if (
                        condition != diagnostic_condition
                        or step.get("with") != diagnostic_contract["with"]
                    ):
                        failures.append(
                            f"{path}: job {job_id} diagnostic upload configuration is not exact"
                        )
                    continue
                contract = EVIDENCE_CONTRACTS.get(path.name, {}).get(job_id)
                evidence_key = (path.name, job_id)
                expected_name = EVIDENCE_UPLOAD_NAMES.get(evidence_key)
                direct_path = DIRECT_EVIDENCE_UPLOAD_PATHS.get(evidence_key)
                canonical_path = direct_path or (contract[1] if contract else None)
                expected_path = (
                    canonical_path.replace("$RUNNER_TEMP", "${{ runner.temp }}")
                    if canonical_path
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

        if (
            path.name == "nyay18-frontend-namespace-gate.yml"
            and job_id == "namespace-production-chromium"
        ):
            chain_length = len(EXPECTED_NYAY18_BROWSER_EVIDENCE_CHAIN)
            actual_chain = tuple(steps[-chain_length:])
            if actual_chain != EXPECTED_NYAY18_BROWSER_EVIDENCE_CHAIN:
                failures.append(
                    f"{path}: NYAY-18 browser evidence chain differs from the exact "
                    "raw-integrity and privacy-safe upload contract"
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
    NYAY-2, NYAY-5, NYAY-17, NYAY-4, or NYAY-19 cannot produce a false green.
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
    nyay5 = _canonical_shell(EXPECTED_NYAY5_DB_GATE_COMMAND)
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
    if canonical.count(nyay5) != 1:
        failures.append(
            f"{path}: database gate must invoke the exact NYAY-5 PostgreSQL gate once"
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
        or nyay5 not in canonical
        or canonical.index(nyay5) < canonical.index(nyay2)
    ):
        failures.append(
            f"{path}: NYAY-5 PostgreSQL gate must remain after the NYAY-2 stage"
        )
    if (
        nyay5 not in canonical
        or nyay17 not in canonical
        or canonical.index(nyay17) < canonical.index(nyay5)
    ):
        failures.append(
            f"{path}: NYAY-17 PostgreSQL gate must remain after the NYAY-5 stage"
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


def check_nyay5_gate_contract(
    orchestrator_path: Path = NYAY5_BROWSER_ORCHESTRATOR,
    browser_path: Path = NYAY5_BROWSER_GATE,
    contract_path: Path = NYAY5_BROWSER_CONTRACT,
    contract_test_path: Path = NYAY5_BROWSER_CONTRACT_TEST,
    control_path: Path = NYAY5_BROWSER_CONTROL,
    postgres_path: Path = NYAY5_POSTGRES_GATE,
    aggregate_path: Path = NYAY5_ACCEPTANCE_AGGREGATE,
    aggregate_test_path: Path = NYAY5_ACCEPTANCE_AGGREGATE_TEST,
    attestation_path: Path = NYAY5_ACCEPTANCE_ATTESTATION_PRODUCER,
    attestation_test_path: Path = NYAY5_ACCEPTANCE_ATTESTATION_TEST,
    package_path: Path = FRONTEND_PACKAGE,
) -> list[str]:
    """Seal the complete executable NYAY-5 producer and aggregate chain."""

    failures: list[str] = []
    pinned_files = (
        (
            orchestrator_path,
            EXPECTED_NYAY5_BROWSER_ORCHESTRATOR_SHA256,
            "NYAY-5 browser orchestrator",
        ),
        (
            browser_path,
            EXPECTED_NYAY5_BROWSER_GATE_SHA256,
            "NYAY-5 browser gate",
        ),
        (
            contract_path,
            EXPECTED_NYAY5_BROWSER_CONTRACT_SHA256,
            "NYAY-5 browser assertion contract",
        ),
        (
            contract_test_path,
            EXPECTED_NYAY5_BROWSER_CONTRACT_TEST_SHA256,
            "NYAY-5 browser assertion contract tests",
        ),
        (
            control_path,
            EXPECTED_NYAY5_BROWSER_CONTROL_SHA256,
            "NYAY-5 scratch-database control",
        ),
        (
            postgres_path,
            EXPECTED_NYAY5_POSTGRES_GATE_SHA256,
            "NYAY-5 PostgreSQL gate",
        ),
        (
            aggregate_path,
            EXPECTED_NYAY5_ACCEPTANCE_AGGREGATE_SHA256,
            "NYAY-5 acceptance aggregate",
        ),
        (
            aggregate_test_path,
            EXPECTED_NYAY5_ACCEPTANCE_AGGREGATE_TEST_SHA256,
            "NYAY-5 acceptance aggregate tests",
        ),
        (
            attestation_path,
            EXPECTED_NYAY5_ACCEPTANCE_ATTESTATION_SHA256,
            "NYAY-5 acceptance attestation producer",
        ),
        (
            attestation_test_path,
            EXPECTED_NYAY5_ACCEPTANCE_ATTESTATION_TEST_SHA256,
            "NYAY-5 acceptance attestation producer tests",
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
    commands = {
        "qa:nyay5:profile-boundary": EXPECTED_NYAY5_BROWSER_PACKAGE_COMMAND,
        "qa:nyay5:acceptance": EXPECTED_NYAY5_ACCEPTANCE_PACKAGE_COMMAND,
    }
    for gate_name, expected_command in commands.items():
        if scripts.get(gate_name) != expected_command:
            failures.append(
                f"{package_path}: NYAY-5 {gate_name} package command differs "
                "from the exact contract"
            )
        for hook in (f"pre{gate_name}", f"post{gate_name}"):
            if hook in scripts:
                failures.append(
                    f"{package_path}: NYAY-5 package command may not have an "
                    "npm lifecycle wrapper"
                )
    return failures


def check_nyay18_static_gate_contract(
    detector_path: Path = NYAY18_NAMESPACE_GATE,
    test_path: Path = NYAY18_NAMESPACE_GATE_TEST,
    contract_path: Path = NYAY18_NAMESPACE_CONTRACT,
    document_path: Path = NYAY18_NAMESPACE_BOUNDARY_DOCUMENT,
    document_test_path: Path = NYAY18_NAMESPACE_BOUNDARY_DOCUMENT_TEST,
) -> list[str]:
    """Seal the NYAY-18 detector, planted mutants and compatibility inventory."""

    failures: list[str] = []
    pinned_files = (
        (
            detector_path,
            EXPECTED_NYAY18_NAMESPACE_GATE_SHA256,
            "NYAY-18 detector SHA-256",
        ),
        (
            test_path,
            EXPECTED_NYAY18_NAMESPACE_GATE_TEST_SHA256,
            "NYAY-18 detector tests SHA-256",
        ),
        (
            contract_path,
            EXPECTED_NYAY18_NAMESPACE_CONTRACT_SHA256,
            "NYAY-18 namespace contract SHA-256",
        ),
        (
            document_path,
            EXPECTED_NYAY18_NAMESPACE_BOUNDARY_DOCUMENT_SHA256,
            "NYAY-18 boundary document SHA-256",
        ),
        (
            document_test_path,
            EXPECTED_NYAY18_NAMESPACE_BOUNDARY_DOCUMENT_TEST_SHA256,
            "NYAY-18 boundary document tests SHA-256",
        ),
    )
    for path, expected, label in pinned_files:
        if not path.is_file() or path.is_symlink():
            failures.append(f"{path}: {label} source is missing or unsafe")
            continue
        try:
            actual = hashlib.sha256(path.read_bytes()).hexdigest()
        except OSError:
            failures.append(f"{path}: {label} source is unreadable")
            continue
        if actual != expected:
            failures.append(f"{path}: {label} differs from the sealed contract")

    if contract_path.is_file() and not contract_path.is_symlink():
        try:
            contract = json.loads(contract_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError):
            failures.append(f"{contract_path}: NYAY-18 namespace contract is unreadable")
        else:
            expected_keys = {
                "schema_version",
                "source_inventory_sha256",
                "metadata",
                "required_runtime_namespaces",
                "compatibility_sources",
            }
            if (
                not isinstance(contract, dict)
                or set(contract) != expected_keys
                or contract.get("schema_version") != 1
                or not isinstance(contract.get("source_inventory_sha256"), str)
                or re.fullmatch(
                    r"[0-9a-f]{64}", str(contract.get("source_inventory_sha256"))
                )
                is None
            ):
                failures.append(
                    f"{contract_path}: NYAY-18 namespace contract schema is not exact"
                )
    return failures


def check_nyay18_browser_gate_contract(
    orchestrator_path: Path = NYAY18_BROWSER_ORCHESTRATOR,
    browser_path: Path = NYAY18_BROWSER_GATE,
    preview_path: Path = NYAY18_BROWSER_PREVIEW_SERVER,
    contract_path: Path = NYAY18_BROWSER_CONTRACT,
    contract_test_path: Path = NYAY18_BROWSER_CONTRACT_TEST,
    package_path: Path = FRONTEND_PACKAGE,
) -> list[str]:
    """Seal the executable production-Chromium producer reached by NYAY-18 CI."""

    failures: list[str] = []
    source_texts: dict[Path, str] = {}
    pinned_files = (
        (
            orchestrator_path,
            EXPECTED_NYAY18_BROWSER_ORCHESTRATOR_SHA256,
            "NYAY-18 browser orchestrator",
        ),
        (
            browser_path,
            EXPECTED_NYAY18_BROWSER_GATE_SHA256,
            "NYAY-18 browser gate",
        ),
        (
            preview_path,
            EXPECTED_NYAY18_BROWSER_PREVIEW_SERVER_SHA256,
            "NYAY-18 browser preview canary server",
        ),
        (
            contract_path,
            EXPECTED_NYAY18_BROWSER_CONTRACT_SHA256,
            "NYAY-18 browser assertion contract",
        ),
        (
            contract_test_path,
            EXPECTED_NYAY18_BROWSER_CONTRACT_TEST_SHA256,
            "NYAY-18 browser assertion contract tests",
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
        try:
            source_texts[path] = raw.decode("utf-8")
        except UnicodeError:
            failures.append(f"{path}: {label} must be UTF-8 text")

    semantic_contracts = (
        (
            orchestrator_path,
            EXPECTED_NYAY18_BROWSER_ORCHESTRATOR_EXACT_HEAD,
            "exact-head environment plumbing",
        ),
        (
            browser_path,
            EXPECTED_NYAY18_BROWSER_GATE_EXACT_HEAD,
            "exact-head evidence semantics",
        ),
        (
            contract_path,
            EXPECTED_NYAY18_BROWSER_CONTRACT_EXACT_HEAD,
            "exact-head evidence contract semantics",
        ),
        (
            contract_test_path,
            EXPECTED_NYAY18_BROWSER_CONTRACT_TEST_EXACT_HEAD,
            "exact-head contract-test semantics",
        ),
        (
            preview_path,
            EXPECTED_NYAY18_BROWSER_PREVIEW_SEMANTICS,
            "preview credential-canary semantics",
        ),
        (
            orchestrator_path,
            EXPECTED_NYAY18_BROWSER_ORCHESTRATOR_PREVIEW_DIGEST,
            "preview-source digest plumbing",
        ),
        (
            browser_path,
            EXPECTED_NYAY18_BROWSER_GATE_PREVIEW_DIGEST,
            "preview-source digest semantics",
        ),
        (
            contract_path,
            EXPECTED_NYAY18_BROWSER_CONTRACT_PREVIEW_DIGEST,
            "preview-source evidence contract semantics",
        ),
        (
            contract_test_path,
            EXPECTED_NYAY18_BROWSER_CONTRACT_TEST_PREVIEW_DIGEST,
            "preview-source contract-test semantics",
        ),
        (
            preview_path,
            EXPECTED_NYAY18_BROWSER_PREVIEW_INSTALL_SHELL,
            "install-shell preview telemetry semantics",
        ),
        (
            browser_path,
            EXPECTED_NYAY18_BROWSER_GATE_INSTALL_SHELL,
            "install-shell credential-canary semantics",
        ),
        (
            contract_path,
            EXPECTED_NYAY18_BROWSER_CONTRACT_INSTALL_SHELL,
            "install-shell evidence contract semantics",
        ),
        (
            contract_test_path,
            EXPECTED_NYAY18_BROWSER_CONTRACT_TEST_INSTALL_SHELL,
            "install-shell contract-test semantics",
        ),
        (
            browser_path,
            EXPECTED_NYAY18_BROWSER_GATE_TWO_REALM_PRIVACY,
            "two-realm privacy-instrumentation semantics",
        ),
        (
            contract_path,
            EXPECTED_NYAY18_BROWSER_CONTRACT_TWO_REALM_PRIVACY,
            "two-realm privacy-instrumentation contract semantics",
        ),
        (
            contract_test_path,
            EXPECTED_NYAY18_BROWSER_CONTRACT_TEST_TWO_REALM_PRIVACY,
            "two-realm privacy-instrumentation contract-test semantics",
        ),
        (
            browser_path,
            EXPECTED_NYAY18_BROWSER_GATE_FINITE_LEADING_PURGE,
            "finite leading-key purge semantics",
        ),
        (
            contract_path,
            EXPECTED_NYAY18_BROWSER_CONTRACT_FINITE_LEADING_PURGE,
            "finite leading-key purge contract semantics",
        ),
        (
            contract_test_path,
            EXPECTED_NYAY18_BROWSER_CONTRACT_TEST_FINITE_LEADING_PURGE,
            "finite leading-key purge contract-test semantics",
        ),
        (
            browser_path,
            EXPECTED_NYAY18_BROWSER_GATE_ACTOR_ROTATION,
            "actor-rotation rediscovery semantics",
        ),
        (
            contract_path,
            EXPECTED_NYAY18_BROWSER_CONTRACT_ACTOR_ROTATION,
            "actor-rotation rediscovery contract semantics",
        ),
        (
            contract_test_path,
            EXPECTED_NYAY18_BROWSER_CONTRACT_TEST_ACTOR_ROTATION,
            "actor-rotation rediscovery contract-test semantics",
        ),
        (
            browser_path,
            EXPECTED_NYAY18_BROWSER_GATE_AUTHORITY_TRANSITIONS,
            "authority-loss transition semantics",
        ),
        (
            contract_path,
            EXPECTED_NYAY18_BROWSER_CONTRACT_AUTHORITY_TRANSITIONS,
            "authority-loss transition contract semantics",
        ),
        (
            contract_test_path,
            EXPECTED_NYAY18_BROWSER_CONTRACT_TEST_AUTHORITY_TRANSITIONS,
            "authority-loss transition contract-test semantics",
        ),
    )
    for path, required_fragments, label in semantic_contracts:
        source = source_texts.get(path)
        if source is not None and any(
            fragment not in source for fragment in required_fragments
        ):
            failures.append(f"{path}: NYAY-18 {label} are not exact")

    browser_source = source_texts.get(browser_path)
    contract_source = source_texts.get(contract_path)
    contract_test_source = source_texts.get(contract_test_path)
    # This row proves reused contract/mutant integrity only. The canonical
    # NYAY-5 workflow remains independently present, hash-bound and required.
    nyay5_separation_exact = (
        browser_source is not None
        and "failureStage = 'inherited_nyay5_contract_integrity';" in browser_source
        and "record('inherited_nyay5_contract_integrity'" in browser_source
        and contract_source is not None
        and "inherited_nyay5_contract_integrity: validInheritedNyay5Contract"
        in contract_source
        and "'inherited-nyay5-contract-failed'" in contract_source
        and contract_test_source is not None
        and "'inherited_nyay5_contract_integrity'" in contract_test_source
        and all(
            "inherited_nyay5_oracles_green" not in source
            for source in (browser_source, contract_source, contract_test_source)
        )
    )
    if not nyay5_separation_exact:
        failures.append(
            "NYAY-18 browser chain: NYAY-5 contract-integrity separation is not exact"
        )

    legacy_brand_runtime_exact = (
        browser_source is not None
        and browser_source.count(r"legal[\s._-]*saathi") >= 3
        and r"legal\s*saathi" not in browser_source
        and "runLegacyBrandSeparatorCanary" in browser_source
        and contract_source is not None
        and "metrics.brandSeparatorCanariesDetected === 6" in contract_source
        and "'brand-separator-canary-missed'" in contract_source
        and contract_test_source is not None
        and "'brand-separator-canary-missed'" in contract_test_source
    )
    if not legacy_brand_runtime_exact:
        failures.append(
            "NYAY-18 browser chain: legacy-brand separator runtime semantics are not exact"
        )

    if orchestrator_path.is_file() and not orchestrator_path.is_symlink():
        try:
            executable_bits = orchestrator_path.stat().st_mode & 0o111
        except OSError:
            executable_bits = 0
        if executable_bits != 0o111:
            failures.append(
                f"{orchestrator_path}: NYAY-18 browser orchestrator is not executable"
            )

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
    gate_name = "qa:nyay18:browser-namespace"
    if scripts.get(gate_name) != EXPECTED_NYAY18_BROWSER_PACKAGE_COMMAND:
        failures.append(
            f"{package_path}: NYAY-18 browser package command differs from the exact contract"
        )
    for hook in (f"pre{gate_name}", f"post{gate_name}"):
        if hook in scripts:
            failures.append(
                f"{package_path}: NYAY-18 browser package command may not have an npm lifecycle wrapper"
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
        diagnostic_contract = FAILURE_DIAGNOSTIC_UPLOADS.get(
            (path.name, job_id)
        )
        diagnostic_indexes = []
        if diagnostic_contract is not None:
            diagnostic_indexes = [
                step_index
                for step_index in upload_indexes
                if re.search(
                    r"^      - name:\s*"
                    + re.escape(str(diagnostic_contract["name"]))
                    + r"\s*$",
                    steps[step_index],
                    re.MULTILINE,
                )
            ]
            if len(diagnostic_indexes) != 1:
                failures.append(
                    f"{path}: job {job_id} needs exactly one privacy-safe diagnostic upload"
                )
            elif (
                diagnostic_indexes[0] == 0
                or _run_payload(steps[diagnostic_indexes[0] - 1])
                != diagnostic_contract["producer"]
            ):
                failures.append(
                    f"{path}: job {job_id} diagnostic upload must immediately follow its producer"
                )
        canonical_upload_indexes = [
            step_index
            for step_index in upload_indexes
            if step_index not in diagnostic_indexes
        ]
        if diagnostic_contract is not None and job_id not in contracts:
            if canonical_upload_indexes:
                failures.append(
                    f"{path}: job {job_id} diagnostic-only contract forbids other artifact uploads"
                )
            continue
        if len(canonical_upload_indexes) != 1:
            failures.append(
                f"{path}: job {job_id} must have exactly one artifact upload "
                "for the canonical attestation"
            )
        if job_id not in contracts:
            if (path.name, job_id) in DIRECT_EVIDENCE_UPLOAD_PATHS:
                # The full direct chain is bound structurally above, including
                # raw sealing, raw verification, textual preparation, privacy
                # scanning, uploadable sealing and the exact upload condition.
                continue
            failures.append(f"{path}: job {job_id} has no canonical evidence contract")
            continue

        source, destination, profile = contracts[job_id]
        if not canonical_upload_indexes:
            continue
        upload_index = canonical_upload_indexes[0]
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
        elif classification == "nyay5-owned-scratch-postgresql":
            canonical = _canonical_shell(re.sub(r"\\\s*\n", " ", executable))
            control_guard = _canonical_shell(
                'CONTROL_URL="${NYAY5_POSTGRES_CONTROL_URL:?NYAY5_POSTGRES_CONTROL_URL is required}"'
            )
            create_scratch = _canonical_shell(
                'PYTHONPATH="$ROOT/backend" "$PYTHON" '
                '"$ROOT/backend/scripts/nyay5_browser_gate_control.py" create '
                '--control-url "$CONTROL_URL" --state-file "$STATE_FILE" '
                '>"$PRIVATE_DIR/create-summary.json" 2>"$PRIVATE_DIR/create-error.log"'
            )
            isolated_upgrade = _canonical_shell(
                "APP_ENV=testing DATABASE_URL=\"$SCRATCH_URL\" "
                "REGISTRATION_SECRET='nyay5-browser-synthetic-registration-key-v1' "
                "REGISTRATION_LOOKUP_SECRET='nyay5-browser-synthetic-lookup-key-v1' "
                f"{NYAY19_ISOLATED_MIGRATION_ENV}=1 "
                '"$PYTHON" -m alembic upgrade head'
            )
            if (
                canonical.count(control_guard) != 1
                or canonical.count(create_scratch) != 1
                or canonical.count(isolated_upgrade) != 1
                or f"export {NYAY19_ISOLATED_MIGRATION_ENV}" in executable
            ):
                failures.append(
                    f"{path}: NYAY-5 Alembic caller lacks exact owned-scratch isolated authority"
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
            "workflow filename inventory differs from the nine canonical required gates"
        )
    failures.extend(check_db_gate_contract())
    failures.extend(check_nyay4_browser_gate_contract())
    failures.extend(check_nyay19_browser_gate_contract())
    failures.extend(check_nyay5_gate_contract())
    failures.extend(check_nyay18_static_gate_contract())
    failures.extend(check_nyay18_browser_gate_contract())
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
