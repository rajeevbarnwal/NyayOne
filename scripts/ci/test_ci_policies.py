#!/usr/bin/env python3
"""Seeded negative tests proving NyayOne CI policy oracles fail closed."""

from __future__ import annotations

import importlib.util
import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from types import ModuleType


HERE = Path(__file__).resolve().parent


def load(name: str) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, HERE / f"{name}.py")
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {name}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


class PolicyOracleTests(unittest.TestCase):
    def test_migration_ledger_accepts_current_tree_and_rejects_byte_drift(self) -> None:
        verifier = load("verify_migration_ledger")
        self.assertEqual(verifier.verify(verifier.ROOT), [])

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = verifier.ROOT / "backend/app/db/migrations"
            target = root / "backend/app/db/migrations"
            shutil.copytree(source, target)
            migration = target / "versions/0002_registration_schema.py"
            migration.write_bytes(migration.read_bytes() + b"\n# planted drift\n")
            failures = verifier.verify(root)
        self.assertTrue(any("SHA-256 mismatch" in item for item in failures), failures)

    def test_migration_ledger_rejects_inventory_and_registry_mutants(self) -> None:
        verifier = load("verify_migration_ledger")
        source = verifier.ROOT / "backend/app/db/migrations"

        def copied_root(directory: str) -> Path:
            root = Path(directory)
            shutil.copytree(source, root / "backend/app/db/migrations")
            return root

        with tempfile.TemporaryDirectory() as directory:
            root = copied_root(directory)
            (root / "backend/app/db/migrations/versions/0008_wave2_tutoring.py").unlink()
            failures = verifier.verify(root)
            self.assertTrue(any("target is missing" in item for item in failures), failures)

        with tempfile.TemporaryDirectory() as directory:
            root = copied_root(directory)
            ledger = root / verifier.LEDGER_RELATIVE
            document = json.loads(ledger.read_text(encoding="utf-8"))
            document["migrations"][1]["path"] = document["migrations"][0]["path"]
            ledger.write_text(json.dumps(document), encoding="utf-8")
            failures = verifier.verify(root)
            self.assertTrue(any("paths must be unique" in item for item in failures), failures)

        with tempfile.TemporaryDirectory() as directory:
            root = copied_root(directory)
            planted = root / "backend/app/db/migrations/versions/0002_planted.py"
            planted.write_text(
                'revision = "0002_planted"\ndown_revision = "0001_initial_pgvector"\n',
                encoding="utf-8",
            )
            failures = verifier.verify(root)
            self.assertTrue(any("overlaps the frozen baseline" in item for item in failures), failures)

        with tempfile.TemporaryDirectory() as directory:
            root = copied_root(directory)
            ledger = root / verifier.LEDGER_RELATIVE
            document = json.loads(ledger.read_text(encoding="utf-8"))
            document["knownHistoricalDrift"][0]["priorSha256Prefix"] = "00000000"
            ledger.write_text(json.dumps(document), encoding="utf-8")
            failures = verifier.verify(root)
            self.assertTrue(any("drift registry" in item for item in failures), failures)

    def test_migration_ledger_enforces_one_linear_forward_graph(self) -> None:
        verifier = load("verify_migration_ledger")
        source = verifier.ROOT / "backend/app/db/migrations"

        def copied_root(directory: str) -> Path:
            root = Path(directory)
            shutil.copytree(source, root / "backend/app/db/migrations")
            return root

        def write_forward(
            root: Path,
            filename: str,
            *,
            revision: str,
            down_revision: str,
            branch_labels: str = "None",
            depends_on: str = "None",
        ) -> None:
            target = root / "backend/app/db/migrations/versions" / filename
            target.write_text(
                "\n".join(
                    (
                        f"revision = {revision}",
                        f"down_revision = {down_revision}",
                        f"branch_labels = {branch_labels}",
                        f"depends_on = {depends_on}",
                        "",
                    )
                ),
                encoding="utf-8",
            )

        predecessor = repr("0016_dob_hash_reconcile")
        with tempfile.TemporaryDirectory() as directory:
            root = copied_root(directory)
            write_forward(
                root,
                "0017_valid_forward.py",
                revision=repr("0017_valid_forward"),
                down_revision=predecessor,
            )
            self.assertEqual(verifier.verify(root), [])

        mutants = {
            "duplicate root": {
                "filename": "0017_duplicate_root.py",
                "revision": repr("0017_duplicate_root"),
                "down_revision": "None",
                "expected": "exactly one root",
            },
            "duplicate revision": {
                "filename": "0017_duplicate_revision.py",
                "revision": repr("0016_dob_hash_reconcile"),
                "down_revision": predecessor,
                "expected": "duplicate revision id",
            },
            "ordinal gap": {
                "filename": "0018_gap.py",
                "revision": repr("0018_gap"),
                "down_revision": predecessor,
                "expected": "unique and contiguous",
            },
            "wrong predecessor": {
                "filename": "0017_wrong_predecessor.py",
                "revision": repr("0017_wrong_predecessor"),
                "down_revision": repr("0015_wave4_public_risk_labels"),
                "expected": "down_revision must be immediate predecessor",
            },
            "branch label": {
                "filename": "0017_branch.py",
                "revision": repr("0017_branch"),
                "down_revision": predecessor,
                "branch_labels": repr("planted-branch"),
                "expected": "branch_labels must be literal None",
            },
            "dependency": {
                "filename": "0017_dependency.py",
                "revision": repr("0017_dependency"),
                "down_revision": predecessor,
                "depends_on": predecessor,
                "expected": "depends_on must be literal None",
            },
            "multiple parents": {
                "filename": "0017_multiple_parents.py",
                "revision": repr("0017_multiple_parents"),
                "down_revision": repr(
                    ("0016_dob_hash_reconcile", "0015_wave4_public_risk_labels")
                ),
                "expected": "down_revision must be a literal string or null",
            },
        }
        for label, mutant in mutants.items():
            with self.subTest(label=label), tempfile.TemporaryDirectory() as directory:
                root = copied_root(directory)
                write_forward(
                    root,
                    mutant["filename"],
                    revision=mutant["revision"],
                    down_revision=mutant["down_revision"],
                    branch_labels=mutant.get("branch_labels", "None"),
                    depends_on=mutant.get("depends_on", "None"),
                )
                failures = verifier.verify(root)
                self.assertTrue(
                    any(mutant["expected"] in item for item in failures),
                    failures,
                )

    def test_migration_immutability_rejects_ledger_and_history_mutants(self) -> None:
        policy = load("check_migration_immutability")
        forward = (
            "A\tbackend/app/db/migrations/versions/0016_nyay16_baseline.py\n"
            "A\tbackend/app/db/migrations/versions/0017_nyay3_invariants.py"
        )
        self.assertEqual(
            policy.violations_from_name_status(
                forward,
                ledger_existed_at_base=True,
            ),
            [],
        )
        initial_baseline = (
            "A\tbackend/app/db/migrations/MIGRATION_SHA256_LEDGER.json\n" + forward
        )
        self.assertEqual(
            policy.violations_from_name_status(
                initial_baseline,
                ledger_existed_at_base=False,
            ),
            [],
        )

        mutants = {
            "historical content": "M\tbackend/app/db/migrations/versions/0002_registration_schema.py",
            "historical deletion": "D\tbackend/app/db/migrations/versions/0008_wave2_tutoring.py",
            "historical rename": (
                "R100\tbackend/app/db/migrations/versions/0013_wave5_calendar_interop.py\t"
                "backend/app/db/migrations/versions/0013_renamed.py"
            ),
            "baseline overlap": "A\tbackend/app/db/migrations/versions/0015_planted.py",
            "noncanonical forward name": "A\tbackend/app/db/migrations/versions/0016-unsafe.py",
            "ledger content": "M\tbackend/app/db/migrations/MIGRATION_SHA256_LEDGER.json",
            "ledger deletion": "D\tbackend/app/db/migrations/MIGRATION_SHA256_LEDGER.json",
            "ledger replacement": "A\tbackend/app/db/migrations/MIGRATION_SHA256_LEDGER.json",
        }
        for label, mutant in mutants.items():
            with self.subTest(label=label):
                self.assertTrue(
                    policy.violations_from_name_status(
                        mutant,
                        ledger_existed_at_base=True,
                    ),
                    label,
                )

    def test_policy_workflow_requires_the_migration_ledger_verifier(self) -> None:
        policy = load("verify_nyayone_ci")
        workflow = policy.ROOT / ".github/workflows/nyayone-policy-gate.yml"
        original = workflow.read_text(encoding="utf-8")
        self.assertIn("python scripts/ci/verify_migration_ledger.py", original)
        self.assertEqual(policy.check_workflow(workflow), [])

        mutated = original.replace(
            "          python scripts/ci/verify_migration_ledger.py\n",
            "",
            1,
        )
        self.assertNotEqual(mutated, original)
        with tempfile.TemporaryDirectory() as directory:
            planted = Path(directory) / "nyayone-policy-gate.yml"
            planted.write_text(mutated, encoding="utf-8")
            failures = policy.check_workflow(planted)
        self.assertTrue(any("canonical semantic contract" in item for item in failures), failures)

    def test_workflow_validator_rejects_partial_green_and_write_authority(self) -> None:
        policy = load("verify_nyayone_ci")
        with tempfile.TemporaryDirectory() as directory:
            workflow = Path(directory) / "bad.yml"
            workflow.write_text(
                """name: bad
on:
  push:
    branches: [main]
  pull_request:
    branches: [main]
  workflow_dispatch:
permissions:
  contents: read
  id-token: write
concurrency: bad
jobs:
  good:
    runs-on: ubuntu-24.04
    timeout-minutes: 1
    steps:
      - uses: evil/example@0000000000000000000000000000000000000000
  bad:
    runs-on: ubuntu-24.04
    timeout-minutes: 1
    steps:
      - run: exit 1
  required:
    name: nyayone-bad-required
    runs-on: ubuntu-24.04
    timeout-minutes: 1
    needs: [good]
    steps:
      - run: true
""",
                encoding="utf-8",
            )
            failures = policy.check_workflow(workflow)
        for fragment in (
            "write permission",
            "action identity is not allowlisted",
            "if: always",
            "expected",
            "fail-closed needs result contract",
        ):
            self.assertTrue(any(fragment in failure for failure in failures), failures)

    def test_evidence_scanner_rejects_each_credential_shape(self) -> None:
        scanner = load("scan_evidence")
        payloads = (
            b"Authorization: Bearer nyayone-ci-planted-canary-0123456789\n",
            b'{"Authorization":"Bearer nyayone-json-canary-0123456789"}\n',
            b'{"cookie":"nyayone_session=nyayone-cookie-canary-0123456789"}\n',
            b"eyJueWF5b25lIjoiY2FuYXJ5In0.eyJzY29wZSI6InRlc3QifQ.c2lnbmF0dXJlLWNhbmFyeQ\n",
        )
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            leak = root / "evidence.txt"
            for payload in payloads:
                leak.write_bytes(payload)
                self.assertTrue(scanner.scan(root), payload)
            leak.write_text("sanitized evidence\n", encoding="utf-8")
            self.assertEqual(scanner.scan(root), [])

    def test_workflow_validator_rejects_static_bypass_and_unsealed_upload(self) -> None:
        policy = load("verify_nyayone_ci")
        with tempfile.TemporaryDirectory() as directory:
            workflow = Path(directory) / "wave1-foundation-gate.yml"
            workflow.write_text(
                """name: bypass
on:
  push:
    branches: [main]
  pull_request:
    branches: [main]
  workflow_dispatch:
permissions: {contents: "write"}
concurrency: bypass
jobs:
  frontend-native:
    if: ${{ false && github.actor != 'nobody' }}
    runs-on: ubuntu-24.04
    timeout-minutes: 1
    steps:
      - uses: actions/checkout@0000000000000000000000000000000000000000
        with:
          persist-credentials: false
          fetch-depth: 0
      - continue-on-error: ${{ 1 == 1 }}
        run: mkdir -p test-results
      - id: evidence_privacy
        run: python scripts/ci/scan_evidence.py test-results
      - uses: actions/upload-artifact@0000000000000000000000000000000000000000
        if: ${{ always() && steps.evidence_privacy.outcome == 'success' }}
        with:
          path: test-results
          if-no-files-found: error
      - uses: actions/upload-artifact@0000000000000000000000000000000000000000
        with:
          path: unguarded-results
          if-no-files-found: error
  required:
    name: nyayone-bypass-required
    if: ${{ always() }}
    needs: [evidence]
    runs-on: ubuntu-24.04
    timeout-minutes: 1
    steps:
      - env:
          RESULTS: ${{ toJSON(needs) }}
        run: |
          python - <<'PY'
          import json, os, sys
          results = {name: value['result'] for name, value in json.loads(os.environ['RESULTS']).items()}
          if not results or any(value != "success" for value in results.values()):
              sys.exit("one or more required jobs did not succeed")
          PY
""",
                encoding="utf-8",
            )
            failures = policy.check_workflow(workflow)
        for fragment in (
            "statically disabled",
            "continue-on-error override",
            "inline write permission",
            "exactly one artifact upload",
            "exactly one evidence_manifest step",
            "missing evidence manifest seal step",
        ):
            self.assertTrue(any(fragment in failure for failure in failures), failures)

    def test_workflow_validator_rejects_evidence_chain_bypasses(self) -> None:
        policy = load("verify_nyayone_ci")
        source = policy.ROOT / ".github" / "workflows" / "wave1-foundation-gate.yml"
        original = source.read_text(encoding="utf-8")
        self.assertEqual(policy.check_workflow(source), [])
        mutations = {
            "unrelated source": original.replace(
                '"$RUNNER_TEMP/v34-s11-s26" "$RUNNER_TEMP/v34-s11-s26-uploadable"',
                '"$RUNNER_TEMP/fake-evidence" "$RUNNER_TEMP/v34-s11-s26-uploadable"',
                1,
            ),
            "traversal upload": original.replace(
                "path: ${{ runner.temp }}/v34-s11-s26-uploadable",
                "path: ${{ runner.temp }}/v34-s11-s26-uploadable/../v34-s11-s26",
                1,
            ),
            "multiline upload": original.replace(
                "path: ${{ runner.temp }}/v34-s11-s26-uploadable",
                "path: |\n            ${{ runner.temp }}/v34-s11-s26-uploadable\n            ${{ runner.temp }}/v34-s11-s26",
                1,
            ),
            "or condition": original.replace(
                "always() && steps.evidence_prepare.outcome",
                "always() || steps.evidence_prepare.outcome",
                1,
            ),
            "true short circuit": original.replace(
                "if: ${{ always() && steps.evidence_prepare.outcome",
                "if: ${{ true || always() && steps.evidence_prepare.outcome",
                1,
            ),
            "command fail open": original.replace(
                '"$RUNNER_TEMP/v34-s11-s26" "$RUNNER_TEMP/v34-s11-s26-uploadable"',
                '"$RUNNER_TEMP/v34-s11-s26" "$RUNNER_TEMP/v34-s11-s26-uploadable" || true',
                1,
            ),
            "late mutation": original.replace(
                '"$RUNNER_TEMP/v34-s11-s26-uploadable"\n      - name: Upload S-11',
                '"$RUNNER_TEMP/v34-s11-s26-uploadable"\n'
                '      - name: Mutate after integrity\n'
                '        run: printf leak > "$RUNNER_TEMP/v34-s11-s26-uploadable/late.log"\n'
                '      - name: Upload S-11',
                1,
            ),
        }
        with tempfile.TemporaryDirectory() as directory:
            for label, mutated in mutations.items():
                with self.subTest(label=label):
                    self.assertNotEqual(mutated, original)
                    workflow = Path(directory) / "wave1-foundation-gate.yml"
                    workflow.write_text(mutated, encoding="utf-8")
                    failures = policy.check_workflow(workflow)
                    self.assertTrue(failures, label)

    def test_workflow_validator_rejects_yaml_and_shell_grammar_bypasses(self) -> None:
        policy = load("verify_nyayone_ci")
        source = policy.ROOT / ".github" / "workflows" / "wave1-foundation-gate.yml"
        original = source.read_text(encoding="utf-8")
        self.assertEqual(policy.check_workflow(source), [])
        mutations = {
            "spaced uses": original.replace(
                "      - uses: actions/setup-node@",
                "      - uses : actions/setup-node@",
                1,
            ),
            "quoted mutable uses": original.replace(
                "      - uses: actions/setup-node@49933ea5288caeca8642d1e84afbd3f7d6820020 # v4.4.0",
                '      - "uses" : evil/action@main',
                1,
            ),
            "quoted condition": original.replace(
                "        id: evidence_prepare\n        if: ${{ always() }}",
                '        id: evidence_prepare\n        "if" : false',
                1,
            ),
            "quoted workflow permission": original.replace(
                "permissions:\n  contents: read",
                '"permissions" : write-all\npermissions:\n  contents: read',
                1,
            ),
            "quoted permission key": original.replace(
                "  contents: read",
                '  "contents" : write',
                1,
            ),
            "explicit YAML tag": original.replace(
                "  contents: read",
                "  contents: !!str write",
                1,
            ),
            "evidence no-op shell": original.replace(
                "        id: evidence_prepare\n",
                "        id: evidence_prepare\n        shell: true {0}\n",
                1,
            ),
            "aggregator conditional step": original.replace(
                "      - name: Require every upstream job to succeed\n",
                "      - name: Require every upstream job to succeed\n"
                "        if: ${{ github.event_name == 'push' }}\n",
                1,
            ),
            "aggregator fail-open command": original.replace(
                "              sys.exit(\"one or more required jobs did not succeed\")\n",
                "              sys.exit(\"one or more required jobs did not succeed\")\n"
                "          true || true\n",
                1,
            ),
            "bracketed secret": original.replace(
                "concurrency:\n",
                "env:\n  PLANTED: ${{ secrets['PLANTED'] }}\nconcurrency:\n",
                1,
            ),
            "unapproved service image": original.replace(
                "pgvector/pgvector@sha256:",
                "evil/example@sha256:",
                1,
            ),
            "unapproved runner": original.replace(
                "runs-on: ubuntu-24.04",
                "runs-on: macos-15",
                1,
            ),
            "duplicate evidence run key": original.replace(
                '          "$RUNNER_TEMP/v34-s11-s26" "$RUNNER_TEMP/v34-s11-s26-uploadable"\n'
                "      - name: Seal complete",
                '          "$RUNNER_TEMP/v34-s11-s26" "$RUNNER_TEMP/v34-s11-s26-uploadable"\n'
                "        run: true\n"
                "      - name: Seal complete",
                1,
            ),
            "duplicate job id": original.replace(
                "\n  required:\n",
                "\n  frontend-native:\n"
                "    runs-on: ubuntu-24.04\n"
                "    timeout-minutes: 1\n"
                "    steps:\n"
                "      - run: true\n"
                "\n  required:\n",
                1,
            ),
        }
        with tempfile.TemporaryDirectory() as directory:
            workflow = Path(directory) / "wave1-foundation-gate.yml"
            for label, mutated in mutations.items():
                with self.subTest(label=label):
                    self.assertNotEqual(mutated, original)
                    workflow.write_text(mutated, encoding="utf-8")
                    self.assertTrue(policy.check_workflow(workflow), label)

    def test_workflow_validator_rejects_execution_context_and_upload_mutants(self) -> None:
        policy = load("verify_nyayone_ci")
        source = policy.ROOT / ".github" / "workflows" / "wave1-foundation-gate.yml"
        original = source.read_text(encoding="utf-8")
        self.assertEqual(policy.check_workflow(source), [])
        mutations: dict[str, tuple[str, str]] = {
            "required defaults shell": (
                original.replace(
                    "  required:\n    name: nyayone-wave1-required",
                    "  required:\n"
                    "    defaults:\n"
                    "      run:\n"
                    "        shell: bash\n"
                    "    name: nyayone-wave1-required",
                    1,
                ),
                "required aggregator has forbidden job keys",
            ),
            "required gate accepts skipped jobs": (
                original.replace(
                    'if not results or any(value != "success" for value in results.values()):',
                    'if not results or any(value not in ("success", "skipped") '
                    "for value in results.values()):",
                    1,
                ),
                "required aggregator command differs from the exact fail-closed contract",
            ),
            "job container": (
                original.replace(
                    "  frontend-native:\n    runs-on: ubuntu-24.04",
                    "  frontend-native:\n"
                    "    runs-on: ubuntu-24.04\n"
                    "    container: ubuntu:24.04",
                    1,
                ),
                "may not use a job container",
            ),
            "LD_PRELOAD override": (
                original.replace(
                    "    timeout-minutes: 35\n    defaults:\n",
                    "    timeout-minutes: 35\n"
                    "    env:\n"
                    "      LD_PRELOAD: /tmp/planted.so\n"
                    "    defaults:\n",
                    1,
                ),
                "overrides a protected environment key",
            ),
            "checkout ref": (
                original.replace(
                    "          persist-credentials: false\n          fetch-depth: 0",
                    "          persist-credentials: false\n"
                    "          fetch-depth: 0\n"
                    "          ref: main",
                    1,
                ),
                "checkout must use the exact head-safe configuration",
            ),
            "working-directory drift": (
                original.replace(
                    "        working-directory: frontend",
                    "        working-directory: backend",
                    1,
                ),
                "defaults differ from the canonical working directory",
            ),
            "setup-node version drift": (
                original.replace('          node-version: "22"', '          node-version: "20"', 1),
                "canonical semantic contract",
            ),
            "PostgreSQL service identity drift": (
                original.replace("          POSTGRES_DB: nyayone_ci", "          POSTGRES_DB: unrelated", 1),
                "canonical semantic contract",
            ),
            "target-runtime step override": (
                original.replace(
                    "      - name: Wave 1 + registration DB gate (PostgreSQL 16 + pgvector)\n"
                    "        run: PYTHON=python bash scripts/db_gate.sh",
                    "      - name: Wave 1 + registration DB gate (PostgreSQL 16 + pgvector)\n"
                    "        env:\n"
                    "          APP_ENV: test\n"
                    "        run: PYTHON=python bash scripts/db_gate.sh",
                    1,
                ),
                "canonical semantic contract",
            ),
            "cache save action": (
                original.replace(
                    "actions/setup-node@49933ea5288caeca8642d1e84afbd3f7d6820020",
                    "actions/cache/save@0000000000000000000000000000000000000000",
                    1,
                ),
                "action identity is not allowlisted",
            ),
            "upload config extra": (
                original.replace(
                    "          include-hidden-files: false",
                    "          include-hidden-files: false\n"
                    "          compression-level: 9",
                    1,
                ),
                "upload configuration is not exact",
            ),
            "upload config changed": (
                original.replace(
                    "          retention-days: 14",
                    "          retention-days: 1",
                    1,
                ),
                "upload configuration is not exact",
            ),
            "duplicate evidence run": (
                original.replace(
                    '          "$RUNNER_TEMP/v34-s11-s26" '
                    '"$RUNNER_TEMP/v34-s11-s26-uploadable"\n'
                    "      - name: Seal complete",
                    '          "$RUNNER_TEMP/v34-s11-s26" '
                    '"$RUNNER_TEMP/v34-s11-s26-uploadable"\n'
                    "        run: true\n"
                    "      - name: Seal complete",
                    1,
                ),
                "duplicate mapping key",
            ),
            "duplicate job": (
                original.replace(
                    "\n  required:\n",
                    "\n  frontend-native:\n"
                    "    runs-on: ubuntu-24.04\n"
                    "    timeout-minutes: 1\n"
                    "    steps:\n"
                    "      - run: true\n"
                    "\n  required:\n",
                    1,
                ),
                "duplicate mapping key",
            ),
        }
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for label, (mutated, expected) in mutations.items():
                with self.subTest(label=label):
                    self.assertNotEqual(mutated, original)
                    workflow = root / "wave1-foundation-gate.yml"
                    workflow.write_text(mutated, encoding="utf-8")
                    failures = policy.check_workflow(workflow)
                    self.assertTrue(
                        any(expected in failure for failure in failures), failures
                    )

            alias = root / "wave1-foundation-gate.yaml"
            alias.write_text(original, encoding="utf-8")
            failures = policy.check_workflow(alias)
            self.assertTrue(
                any("workflow filename is not canonical" in failure for failure in failures),
                failures,
            )

    def test_registration_gate_cannot_be_skipped_replaced_or_redirected(self) -> None:
        policy = load("verify_nyayone_ci")
        source = policy.ROOT / ".github" / "workflows" / "registration-db-gate.yml"
        original = source.read_text(encoding="utf-8")
        self.assertEqual(policy.check_workflow(source), [])
        gate = "      - run: PYTHON=python bash scripts/db_gate.sh"
        mutations = {
            "hidden condition": original.replace(
                gate,
                "      - if: ${{ github.actor == '__never_nyayone_actor__' }}\n"
                "        run: PYTHON=python bash scripts/db_gate.sh",
                1,
            ),
            "true no-op": original.replace(gate, "      - run: true", 1),
            "exit-zero no-op": original.replace(gate, "      - run: exit 0", 1),
            "working-directory redirect": original.replace(
                gate,
                "      - working-directory: frontend\n"
                "        run: PYTHON=python bash scripts/db_gate.sh",
                1,
            ),
            "SQLite target substitution": original.replace(
                "DATABASE_URL: postgresql+psycopg://nyayone_ci:nyayone_ci_ephemeral@127.0.0.1:5432/nyayone_ci",
                "DATABASE_URL: sqlite:///tmp/false-green.db",
                1,
            ),
            "preceding gate-script replacement": original.replace(
                gate,
                "      - run: printf 'exit 0\\n' > scripts/db_gate.sh\n" + gate,
                1,
            ),
            "preceding runtime environment injection": original.replace(
                gate,
                "      - run: echo 'DATABASE_URL=sqlite:///tmp/false-green.db' >> \"$GITHUB_ENV\"\n"
                + gate,
                1,
            ),
            "preceding command-path injection": original.replace(
                gate,
                "      - run: echo 'PATH=/tmp/planted:$PATH' >> \"$GITHUB_ENV\"\n"
                + gate,
                1,
            ),
        }
        with tempfile.TemporaryDirectory() as directory:
            workflow = Path(directory) / "registration-db-gate.yml"
            for label, mutated in mutations.items():
                with self.subTest(label=label):
                    self.assertNotEqual(mutated, original)
                    workflow.write_text(mutated, encoding="utf-8")
                    self.assertTrue(policy.check_workflow(workflow), label)

    def test_nested_database_gate_cannot_drop_or_bypass_nyay16(self) -> None:
        policy = load("verify_nyayone_ci")
        source = policy.DB_GATE
        original = source.read_text(encoding="utf-8")
        self.assertEqual(policy.check_db_gate_contract(source), [])
        invocation = (
            'NYAY16_GATE_ALLOW_DATABASES=true "$PY" scripts/nyay16_postgres_gate.py \\\n'
            "  --output test-results/nyay16-postgres/summary.json"
        )
        self.assertEqual(original.count(invocation), 1)
        mutations = {
            "deleted invocation": original.replace(invocation, "true", 1),
            "wrong script": original.replace(
                "scripts/nyay16_postgres_gate.py",
                "scripts/not-the-nyay16-gate.py",
                1,
            ),
            "missing database opt-in": original.replace(
                "NYAY16_GATE_ALLOW_DATABASES=true ", "", 1
            ),
            "discarded report": original.replace(
                "test-results/nyay16-postgres/summary.json", "/dev/null", 1
            ),
            "conditional bypass": original.replace(
                invocation,
                "if false; then\n" + invocation + "\nfi",
                1,
            ),
        }
        with tempfile.TemporaryDirectory() as directory:
            candidate = Path(directory) / "db_gate.sh"
            for label, mutated in mutations.items():
                with self.subTest(label=label):
                    self.assertNotEqual(mutated, original)
                    candidate.write_text(mutated, encoding="utf-8")
                    failures = policy.check_db_gate_contract(candidate)
                    self.assertTrue(failures, label)
                    if label == "deleted invocation":
                        self.assertTrue(
                            any("invoke the exact NYAY-16" in item for item in failures),
                            failures,
                        )

    def test_runtime_identity_policy_accepts_the_current_tree(self) -> None:
        policy = load("check_nyayone_runtime_identity")
        self.assertEqual(policy.check(policy.ROOT), [])

    def test_wave3_silent_otp_diagnostic_is_not_uploadable_evidence(self) -> None:
        workflow = (
            HERE.parent.parent / ".github" / "workflows" /
            "wave3-credential-trust-gate.yml"
        ).read_text(encoding="utf-8")
        self.assertIn('$RUNNER_TEMP/otp-capture.log', workflow)
        self.assertNotIn('test-results/otp.log', workflow)

    def test_committed_nyayone_evidence_is_scanned_in_place(self) -> None:
        workflow = (
            HERE.parent.parent / ".github" / "workflows" /
            "nyayone-policy-gate.yml"
        ).read_text(encoding="utf-8")
        self.assertIn('python scripts/ci/scan_evidence.py "$package"', workflow)
        self.assertNotIn(
            'prepare_uploadable_evidence.py "$(dirname "$manifest")"',
            workflow,
        )

    def test_wave4_moderation_results_only_classify_runtime_diagnostics(self) -> None:
        driver = (
            HERE.parent.parent / "frontend" / "scripts" /
            "wave4-moderation-e2e.mjs"
        ).read_text(encoding="utf-8")
        self.assertIn("actualSummary: diagnosticSummary(actual)", driver)
        self.assertIn("diagnostic: diagnosticSummary(error)", driver)
        self.assertNotIn("createHash", driver)
        self.assertNotIn("sha256", driver)
        self.assertNotIn("expected ${expected}; actual ${actual}", driver)
        self.assertNotIn("report.failures.push(String(error))", driver)

    def test_runtime_identity_policy_rejects_planted_legacy_canaries(self) -> None:
        policy = load("check_nyayone_runtime_identity")
        env_text = (policy.ROOT / ".env.example").read_text(encoding="utf-8")
        bad_env = env_text.replace("VITE_APP_NAME=NyayOne", "VITE_APP_NAME=LegalSaathi")
        self.assertTrue(policy.check_env_text(bad_env, label="planted.env"))

        bad_workflow = """env:
  POSTGRES_USER: legalsaathi
  POSTGRES_PASSWORD: legalsaathi
  POSTGRES_DB: legalsaathi
"""
        self.assertTrue(policy.check_workflow_text(bad_workflow, label="planted.yml"))

        drifted_workflow = """env:
  POSTGRES_USER: unrelated_ci
  POSTGRES_PASSWORD: unrelated_ephemeral
  POSTGRES_DB: unrelated_ci
"""
        drift_failures = policy.check_workflow_text(
            drifted_workflow, label="drifted.yml"
        )
        for key in ("POSTGRES_USER", "POSTGRES_PASSWORD", "POSTGRES_DB"):
            self.assertTrue(any(key in item for item in drift_failures), drift_failures)

        removed_postgres = policy.check_workflow_text(
            "name: registration switched to sqlite\njobs: {}\n",
            label="registration-db-gate.yml",
        )
        self.assertTrue(
            any("PostgreSQL service" in item for item in removed_postgres),
            removed_postgres,
        )
        self.assertTrue(
            any("DATABASE_URL contract" in item for item in removed_postgres),
            removed_postgres,
        )

        bad_compose = {
            "name": "legalsaathi",
            "services": {
                "postgres": {
                    "environment": {
                        "POSTGRES_USER": "legalsaathi",
                        "POSTGRES_PASSWORD": "legalsaathi",
                        "POSTGRES_DB": "legalsaathi",
                    },
                    "ports": [{"published": 1032, "target": 5432}],
                },
                "backend": {
                    "environment": {
                        "DATABASE_URL": "postgresql://legacy:redacted@postgres:5432/legacy"
                    },
                    "ports": [{"published": 1031, "target": 1031}],
                },
                "frontend": {
                    "environment": {
                        "VITE_API_BASE_URL": "http://localhost:1031",
                        "VITE_APP_NAME": "LegalSaathi",
                    },
                    "ports": [{"published": 1030, "target": 1030}],
                },
                "logstash": {"ports": [{"published": 1038, "target": 9600}]},
            },
            "volumes": {"pgdata": {"name": "legalsaathi_pgdata"}},
        }
        failures = policy.check_compose_payload(bad_compose, label="planted compose")
        self.assertGreaterEqual(len(failures), 6, json.dumps(failures))

        correct_identity_bad_password = {
            "name": "nyayone",
            "services": {
                "postgres": {
                    "environment": {
                        "POSTGRES_USER": "nyayone",
                        "POSTGRES_PASSWORD": "legalsaathi",
                        "POSTGRES_DB": "nyayone",
                    },
                    "ports": [{"published": 1132, "target": 5432}],
                },
                "backend": {
                    "environment": {
                        "DATABASE_URL": (
                            "postgresql+psycopg://nyayone:nyayone_dev_only"
                            "@postgres:5432/nyayone_evil"
                        )
                    },
                    "ports": [{"published": 1131, "target": 1031}],
                },
                "frontend": {
                    "environment": {
                        "VITE_API_BASE_URL": "http://localhost:1131",
                        "VITE_APP_NAME": "NyayOne",
                    },
                    "ports": [{"published": 1130, "target": 1030}],
                },
                "logstash": {"ports": [{"published": 1138, "target": 9600}]},
            },
            "volumes": {"pgdata": {"name": "nyayone_pgdata"}},
        }
        failures = policy.check_compose_payload(
            correct_identity_bad_password,
            label="password and database path canary",
        )
        self.assertTrue(any("POSTGRES_PASSWORD" in item for item in failures), failures)
        self.assertTrue(any("isolated Compose database" in item for item in failures), failures)

        extra_legacy_service = json.loads(json.dumps(correct_identity_bad_password))
        extra_legacy_service["services"]["postgres"]["environment"][
            "POSTGRES_PASSWORD"
        ] = "nyayone_dev_only"
        extra_legacy_service["services"]["backend"]["environment"][
            "DATABASE_URL"
        ] = (
            "postgresql+psycopg://nyayone:nyayone_dev_only"
            "@postgres:5432/nyayone"
        )
        extra_legacy_service["services"]["legalsaathi-helper"] = {
            "ports": [{"published": 1032, "target": 9999}]
        }
        extra_legacy_service["networks"] = {
            "default": {"name": "legalsaathi_default"}
        }
        failures = policy.check_compose_payload(
            extra_legacy_service,
            label="extra legacy service canary",
        )
        for fragment in ("service identity", "1030-1049", "network identity"):
            self.assertTrue(any(fragment in item for item in failures), failures)

        bad_cookie = (
            policy.ROOT / "frontend/scripts/wave4-moderation-e2e.mjs"
        ).read_text(encoding="utf-8").replace("'nyayone_session'", "'legalsaathi_session'")
        self.assertTrue(
            policy.check_required_operational_text(
                "frontend/scripts/wave4-moderation-e2e.mjs", bad_cookie
            )
        )

    def test_runtime_identity_policy_allows_shared_tenant_and_historical_migrations(self) -> None:
        policy = load("check_nyayone_runtime_identity")
        shared_tenant = "JIRA_BASE_URL=https://legalsaathi.atlassian.net\n"
        values = policy.parse_env(shared_tenant)
        self.assertEqual(values["JIRA_BASE_URL"], "https://legalsaathi.atlassian.net")
        migration_canary = policy.check_active_source_text(
            Path("backend/app/db/migrations/versions/0001_historical.py"),
            'MESSAGE = "Your LegalSaathi verification code"\n',
        )
        active_canary = policy.check_active_source_text(
            Path("backend/app/services/planted.py"),
            'MESSAGE = "Your LegalSaathi verification code"\n',
        )
        self.assertEqual(migration_canary, [])
        self.assertTrue(active_canary)


if __name__ == "__main__":
    unittest.main()
