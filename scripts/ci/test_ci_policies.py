#!/usr/bin/env python3
"""Seeded negative tests proving NyayOne CI policy oracles fail closed."""

from __future__ import annotations

import importlib.util
import json
import os
import shutil
import subprocess
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
    def test_nyay66_calibration_workflow_registered_and_mutation_rejected(self) -> None:
        policy = load("verify_nyayone_ci")
        path = policy.ROOT / ".github/workflows/nyay66-conformance.yml"
        self.assertIn(path.name, policy.CANONICAL_WORKFLOW_FILES)
        self.assertEqual(policy.check_workflow(path), [])
        self.assertNotIn("${{ runner.temp }}", path.read_text().split("    steps:")[0])
        with tempfile.TemporaryDirectory() as directory:
            altered = Path(directory) / path.name
            altered.write_text(path.read_text().replace("node scripts/nyay66-live.mjs", "echo skipped"))
            self.assertTrue(policy.check_workflow(altered))

    def test_nyay12_native_gate_is_wired_and_sealed(self) -> None:
        policy = load("verify_nyayone_ci")
        source = (policy.ROOT / "backend/scripts/db_gate.sh").read_text()
        self.assertIn('NYAY12_POSTGRES_GATE=1 "$PY" tests/nyay12_native_gate.py', source)
        self.assertIn("backend/tests/nyay12_native_gate.py", policy.EXPECTED_NYAY19_ALEMBIC_PYTHON_CALLERS)
        self.assertEqual(policy.check_db_gate_contract(policy.ROOT / "backend/scripts/db_gate.sh"), [])

    def test_nyay12_relocated_alembic_caller_is_audited(self) -> None:
        policy = load("verify_nyayone_ci")
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = root / "backend/tests/nyay12_native_gate.py"
            path.parent.mkdir(parents=True)
            path.write_text("import subprocess\nsubprocess.run(['python', '-m', 'alembic', 'upgrade', 'head'], env={})\n")
            failures = policy.check_alembic_execution_contracts(root)
            self.assertTrue(any("nyay12_native_gate.py" in item and "missing exact isolated" in item for item in failures), failures)

    def test_nyay19_alembic_callers_require_exact_isolated_authority(self) -> None:
        policy = load("verify_nyayone_ci")

        self.assertEqual(policy.check_alembic_execution_contracts(), [])

        wave5 = (
            policy.ROOT / ".github/workflows/wave5-calendar-gate.yml"
        ).read_text(encoding="utf-8")
        mutations = {
            "missing opt-in": wave5.replace(
                '      NYAY19_ISOLATED_MIGRATION_EXECUTE: "1"\n',
                "",
                1,
            ),
            "hostname indirection": wave5.replace(
                "@127.0.0.1:5432/nyayone_wave5_qa",
                "@localhost:5432/nyayone_wave5_qa",
                1,
            ),
            "unclassified opt-in": wave5.replace(
                "  required:\n",
                "  required:\n    env:\n"
                '      NYAY19_ISOLATED_MIGRATION_EXECUTE: "1"\n',
                1,
            ),
            "unclassified caller": wave5.replace(
                "      - name: Require every upstream job to succeed\n"
                "        env:\n"
                "          RESULTS: ${{ toJSON(needs) }}\n"
                "        run: |\n"
                "          python - <<'PY'\n",
                "      - name: Require every upstream job to succeed\n"
                "        env:\n"
                "          RESULTS: ${{ toJSON(needs) }}\n"
                "        run: |\n"
                "          alembic upgrade head\n"
                "          python - <<'PY'\n",
                1,
            ),
        }
        with tempfile.TemporaryDirectory() as directory:
            candidate = Path(directory) / "wave5-calendar-gate.yml"
            for label, mutated in mutations.items():
                with self.subTest(label=label):
                    self.assertNotEqual(mutated, wave5)
                    candidate.write_text(mutated, encoding="utf-8")
                    failures = policy.check_workflow(candidate)
                    self.assertTrue(
                        any("NYAY-19 isolated Alembic" in item for item in failures),
                        failures,
                    )

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            scripts = root / "backend/scripts"
            scripts.mkdir(parents=True)
            (scripts / "planted_gate.py").write_text(
                "import subprocess, sys\n"
                "subprocess.run(\n"
                "    [sys.executable, '-m', 'alembic', 'upgrade', 'head'],\n"
                "    env={'APP_ENV': 'testing'},\n"
                ")\n",
                encoding="utf-8",
            )
            failures = policy.check_alembic_execution_contracts(root)
        self.assertTrue(
            any("missing exact isolated subprocess authority" in item for item in failures),
            failures,
        )

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            scripts = root / "backend/scripts"
            scripts.mkdir(parents=True)
            (scripts / "planted_gate.sh").write_text(
                '#!/usr/bin/env bash\npython -m alembic upgrade head\n',
                encoding="utf-8",
            )
            failures = policy.check_alembic_execution_contracts(root)
        self.assertTrue(
            any("unclassified Alembic shell caller" in item for item in failures),
            failures,
        )

        nyay5_orchestrator = policy.NYAY5_BROWSER_ORCHESTRATOR.read_text(
            encoding="utf-8"
        )
        nyay5_mutations = {
            "missing scratch-only authority": nyay5_orchestrator.replace(
                "    NYAY19_ISOLATED_MIGRATION_EXECUTE=1 \\\n", "", 1
            ),
            "substituted control authority": nyay5_orchestrator.replace(
                '"$ROOT/backend/scripts/nyay5_browser_gate_control.py" create \\\n'
                '  --control-url "$CONTROL_URL" --state-file "$STATE_FILE"',
                '"$ROOT/backend/scripts/nyay5_browser_gate_control.py" create \\\n'
                '  --control-url "postgresql://substitute" --state-file "$STATE_FILE"',
                1,
            ),
            "broad exported authority": nyay5_orchestrator.replace(
                "set -Eeuo pipefail\n",
                "set -Eeuo pipefail\nexport NYAY19_ISOLATED_MIGRATION_EXECUTE=1\n",
                1,
            ),
        }
        for label, mutated in nyay5_mutations.items():
            with self.subTest(label=label), tempfile.TemporaryDirectory() as directory:
                self.assertNotEqual(mutated, nyay5_orchestrator)
                root = Path(directory)
                scripts = root / "scripts"
                scripts.mkdir(parents=True)
                (scripts / "nyay5_profile_browser_gate.sh").write_text(
                    mutated, encoding="utf-8"
                )
                failures = policy.check_alembic_execution_contracts(root)
                self.assertTrue(
                    any(
                        "NYAY-5 Alembic caller lacks exact owned-scratch isolated authority"
                        in item
                        for item in failures
                    ),
                    failures,
                )

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            scripts = root / "backend/scripts"
            scripts.mkdir(parents=True)
            (scripts / "nyay19_migrate.py").write_text(
                "import os, subprocess, sys\n"
                "TARGET_REVISION = '0020_auth_retention_lifecycle'\n"
                "environment = dict(os.environ)\n"
                "subprocess.run(\n"
                "    [sys.executable, '-m', 'alembic', 'upgrade', TARGET_REVISION],\n"
                "    env=environment,\n"
                ")\n",
                encoding="utf-8",
            )
            failures = policy.check_alembic_execution_contracts(root)
        self.assertTrue(
            any("force exact approval" in item for item in failures),
            failures,
        )

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

        version_files = []
        for candidate in (source / "versions").glob("*.py"):
            match = verifier.VERSION_FILE.fullmatch(candidate.name)
            if match and int(match.group("ordinal")) > verifier.BASELINE_LAST_ORDINAL:
                version_files.append((int(match.group("ordinal")), candidate))
        version_files.sort()
        current_ordinal, current_path = version_files[-1]
        current_revision, current_error = verifier._literal_assignment(
            current_path, "revision"
        )
        prior_revision, prior_error = verifier._literal_assignment(
            current_path, "down_revision"
        )
        self.assertIsNone(current_error)
        self.assertIsNone(prior_error)
        self.assertIsInstance(current_revision, str)
        self.assertIsInstance(prior_revision, str)
        next_ordinal = current_ordinal + 1
        next_prefix = f"{next_ordinal:04d}"
        predecessor = repr(current_revision)
        with tempfile.TemporaryDirectory() as directory:
            root = copied_root(directory)
            write_forward(
                root,
                f"{next_prefix}_valid_forward.py",
                revision=repr(f"{next_prefix}_valid_forward"),
                down_revision=predecessor,
            )
            self.assertEqual(verifier.verify(root), [])

        mutants = {
            "duplicate root": {
                "filename": f"{next_prefix}_duplicate_root.py",
                "revision": repr(f"{next_prefix}_duplicate_root"),
                "down_revision": "None",
                "expected": "exactly one root",
            },
            "duplicate revision": {
                "filename": f"{next_prefix}_duplicate_revision.py",
                "revision": predecessor,
                "down_revision": predecessor,
                "expected": "duplicate revision id",
            },
            "ordinal gap": {
                "filename": f"{next_ordinal + 1:04d}_gap.py",
                "revision": repr(f"{next_ordinal + 1:04d}_gap"),
                "down_revision": predecessor,
                "expected": "unique and contiguous",
            },
            "wrong predecessor": {
                "filename": f"{next_prefix}_wrong_predecessor.py",
                "revision": repr(f"{next_prefix}_wrong_predecessor"),
                "down_revision": repr(prior_revision),
                "expected": "down_revision must be immediate predecessor",
            },
            "branch label": {
                "filename": f"{next_prefix}_branch.py",
                "revision": repr(f"{next_prefix}_branch"),
                "down_revision": predecessor,
                "branch_labels": repr("planted-branch"),
                "expected": "branch_labels must be literal None",
            },
            "dependency": {
                "filename": f"{next_prefix}_dependency.py",
                "revision": repr(f"{next_prefix}_dependency"),
                "down_revision": predecessor,
                "depends_on": predecessor,
                "expected": "depends_on must be literal None",
            },
            "multiple parents": {
                "filename": f"{next_prefix}_multiple_parents.py",
                "revision": repr(f"{next_prefix}_multiple_parents"),
                "down_revision": repr(
                    (current_revision, prior_revision)
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

    def test_policy_workflow_discovers_nyay33_contract_exactly_once(self) -> None:
        policy = load("verify_nyayone_ci")
        command = "python scripts/ci/test_nyay33_documentation_polish.py"
        workflow = policy.ROOT / ".github/workflows/nyayone-policy-gate.yml"
        original = workflow.read_text(encoding="utf-8")

        self.assertEqual(
            getattr(policy, "EXPECTED_NYAY33_POLICY_COMMAND", None), command
        )
        self.assertIn(
            command,
            policy.REQUIRED_JOB_RUNS[("nyayone-policy-gate.yml", "policy-contracts")],
        )
        self.assertEqual(original.count(command), 1)
        self.assertEqual(policy.check_workflow(workflow), [])

        mutations = {
            "missing": original.replace(
                f"      - name: Validate NYAY-33 documentation reconciliation\n"
                f"        run: {command}\n",
                "",
                1,
            ),
            "duplicate": original.replace(
                f"      - name: Validate NYAY-33 documentation reconciliation\n"
                f"        run: {command}\n",
                f"      - name: Validate NYAY-33 documentation reconciliation\n"
                f"        run: {command}\n"
                f"      - name: Duplicate NYAY-33 contract\n"
                f"        run: {command}\n",
                1,
            ),
        }
        with tempfile.TemporaryDirectory() as directory:
            for label, mutated in mutations.items():
                with self.subTest(label=label):
                    self.assertNotEqual(mutated, original)
                    candidate = Path(directory) / "nyayone-policy-gate.yml"
                    candidate.write_text(mutated, encoding="utf-8")
                    failures = policy.check_workflow(candidate)
                    self.assertTrue(
                        any(
                            "must contain the required gate command exactly once"
                            in failure
                            and command in failure
                            for failure in failures
                        ),
                        failures,
                    )

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
            "staging OTP provider downgraded to plaintext": (
                original.replace(
                    "OTP_PROVIDER_URL: https://otp-provider.example.test/send",
                    "OTP_PROVIDER_URL: http://otp-provider.example.test/send",
                    1,
                ),
                "canonical semantic contract",
            ),
            "staging OTP idempotency guarantee disabled": (
                original.replace(
                    'OTP_PROVIDER_SUPPORTS_IDEMPOTENCY: "true"',
                    'OTP_PROVIDER_SUPPORTS_IDEMPOTENCY: "false"',
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

    def test_nyay4_quarantine_workflow_is_exact_visible_and_never_silent(self) -> None:
        policy = load("verify_nyayone_ci")
        source = (
            policy.ROOT
            / ".github"
            / "workflows"
            / "ci-flaky-nyay4-cookie-reload-symmetry.yml"
        )
        original = source.read_text(encoding="utf-8")
        self.assertEqual(policy.check_nyay4_quarantine_workflow(source), [])
        reason = (
            "Timing-sensitive reload-symmetry assertion that passes locally (17/17) "
            "but exhibits nondeterministic scheduling variance in GitHub Actions "
            "runners. Quarantined 2026-08-24 after Cycle 4. Product code is correct; "
            "CI runner timing is the variable."
        )
        command_flag = "--require-quarantined-assertion"
        diagnostic_path = (
            "${{ github.workspace }}/backend/test-results/nyay4-ci-flaky/summary.json"
        )
        mutations = {
            "assertion removed": original.replace(
                "CONTRACT-COOKIE-ORIGIN-RELOAD-SYMMETRY",
                "CONTRACT-REMOVED",
            ),
            "reason removed": original.replace(reason, "Unreviewed quarantine."),
            "strict flag removed": original.replace(command_flag, "--execute"),
            "unavailable diagnostic removed": original.replace(
                "Initialize explicit not-yet-executed diagnostic",
                "Initialize unrelated output",
            ),
            "pgvector fixture removed": original.replace(
                '-c "CREATE EXTENSION IF NOT EXISTS vector;"',
                '-c "SELECT 1;"',
            ),
            "schedule removed": original.replace("  schedule:\n", "  x-schedule:\n"),
            "manual trigger removed": original.replace(
                "  workflow_dispatch:\n", "  x-workflow_dispatch:\n"
            ),
            "PR trigger removed": original.replace(
                "  pull_request:\n", "  x-pull_request:\n"
            ),
            "always upload removed": original.replace(
                "        if: ${{ always() }}",
                "        if: ${{ success() }}",
            ),
            "diagnostic path changed": original.replace(
                diagnostic_path,
                "${{ github.workspace }}/backend/test-results/empty.json",
            ),
            "missing artifact is warning": original.replace(
                "if-no-files-found: error", "if-no-files-found: warn"
            ),
            "failure suppressed": original.replace(
                command_flag,
                f"{command_flag} || true",
            ),
        }
        with tempfile.TemporaryDirectory() as directory:
            workflow = (
                Path(directory) / "ci-flaky-nyay4-cookie-reload-symmetry.yml"
            )
            for label, mutated in mutations.items():
                with self.subTest(label=label):
                    self.assertNotEqual(mutated, original)
                    workflow.write_text(mutated, encoding="utf-8")
                    self.assertTrue(
                        policy.check_nyay4_quarantine_workflow(workflow), label
                    )

    def test_nyay5_required_pipeline_cannot_skip_a_producer_or_attestation(self) -> None:
        policy = load("verify_nyayone_ci")
        source = (
            policy.ROOT
            / ".github"
            / "workflows"
            / "nyay5-profile-boundary-gate.yml"
        )
        original = source.read_text(encoding="utf-8")
        self.assertEqual(policy.check_workflow(source), [])
        db_gate = "        run: (cd backend && PYTHON=python bash scripts/db_gate.sh)"
        browser_gate = (
            "        run: bash scripts/nyay5_profile_browser_gate.sh "
            '"$GITHUB_WORKSPACE/test-results/nyay5-browser/results.json"'
        )
        source_manifest = (
            "        run: python scripts/ci/evidence_manifest.py --seal "
            '"$GITHUB_WORKSPACE/test-results/nyay5-browser"'
        )
        attestation_producer = (
            "          python scripts/ci/nyay5_acceptance_attestations.py\n"
            "          --browser \"$GITHUB_WORKSPACE/test-results/nyay5-browser/results.json\"\n"
            "          --orchestrator \"$GITHUB_WORKSPACE/test-results/nyay5-browser/orchestrator-summary.json\"\n"
            "          --postgres \"$GITHUB_WORKSPACE/test-results/nyay5-postgres/summary.json\"\n"
            "          --otp-postgres \"$GITHUB_WORKSPACE/test-results/nyay4-postgres/summary.json\"\n"
            "          --manifest-root \"$GITHUB_WORKSPACE/test-results/nyay5-browser\"\n"
            "          --output \"$GITHUB_WORKSPACE/test-results/nyay5-acceptance/attestations.json\""
        )
        acceptance_aggregate = (
            "          npm run qa:nyay5:acceptance --\n"
            "          --browser \"$GITHUB_WORKSPACE/test-results/nyay5-browser/results.json\"\n"
            "          --postgres \"$GITHUB_WORKSPACE/test-results/nyay5-postgres/summary.json\"\n"
            "          --otp-postgres \"$GITHUB_WORKSPACE/test-results/nyay4-postgres/summary.json\"\n"
            "          --attestations \"$GITHUB_WORKSPACE/test-results/nyay5-acceptance/attestations.json\"\n"
            "          --output \"$GITHUB_WORKSPACE/test-results/nyay5-acceptance/summary.json\""
        )
        require_pass = (
            "        run: python \"$GITHUB_WORKSPACE/scripts/ci/"
            "prepare_uploadable_evidence.py\" --require-pass "
            '"$RUNNER_TEMP/nyay5-uploadable"'
        )
        for expected in (
            db_gate,
            browser_gate,
            source_manifest,
            attestation_producer,
            acceptance_aggregate,
            require_pass,
        ):
            self.assertEqual(original.count(expected), 1)
        mutations = {
            "deleted database producer": original.replace(db_gate, "        run: true", 1),
            "masked database producer": original.replace(
                db_gate, db_gate + " || true", 1
            ),
            "deleted browser producer": original.replace(
                browser_gate, "        run: true", 1
            ),
            "masked browser producer": original.replace(
                browser_gate, browser_gate + " || true", 1
            ),
            "redirected browser result": original.replace(
                "test-results/nyay5-browser/results.json",
                "test-results/nyay5-browser/substitute.json",
                1,
            ),
            "deleted source manifest": original.replace(
                source_manifest, "        run: true", 1
            ),
            "deleted attestation producer": original.replace(
                attestation_producer, "          true", 1
            ),
            "masked attestation producer": original.replace(
                attestation_producer,
                attestation_producer + " || true",
                1,
            ),
            "deleted acceptance aggregate": original.replace(
                acceptance_aggregate, "          true", 1
            ),
            "masked acceptance aggregate": original.replace(
                acceptance_aggregate,
                acceptance_aggregate + " || true",
                1,
            ),
            "missing NYAY-4 producer staging": original.replace(
                "          install -m 0600 backend/test-results/nyay4-postgres/summary.json \"$GITHUB_WORKSPACE/test-results/nyay4-postgres/summary.json\"\n",
                "",
                1,
            ),
            "remote database": original.replace(
                "@127.0.0.1:5432/nyayone_nyay5_ci",
                "@database.internal:5432/nyayone_nyay5_ci",
                1,
            ),
            "missing migration authority": original.replace(
                '      NYAY19_ISOLATED_MIGRATION_EXECUTE: "1"\n', "", 1
            ),
            "deleted attestation verdict": original.replace(
                require_pass, "        run: true", 1
            ),
            "empty required needs": original.replace(
                "    needs: [profile-postgres-production-browser]",
                "    needs: []",
                1,
            ),
            "conditional producer": original.replace(
                "  profile-postgres-production-browser:\n",
                "  profile-postgres-production-browser:\n"
                "    if: ${{ github.actor == '__never_nyayone_actor__' }}\n",
                1,
            ),
        }
        with tempfile.TemporaryDirectory() as directory:
            candidate = Path(directory) / source.name
            for label, mutated in mutations.items():
                with self.subTest(label=label):
                    self.assertNotEqual(mutated, original)
                    candidate.write_text(mutated, encoding="utf-8")
                    failures = policy.check_workflow(candidate)
                    self.assertTrue(failures, label)
                    if label in {
                        "deleted database producer",
                        "masked database producer",
                        "deleted browser producer",
                        "masked browser producer",
                        "deleted source manifest",
                        "deleted attestation producer",
                        "masked attestation producer",
                    }:
                        self.assertTrue(
                            any("required gate command" in item for item in failures),
                            failures,
                        )
                    if label in {
                        "deleted acceptance aggregate",
                        "masked acceptance aggregate",
                    }:
                        self.assertTrue(
                            any(
                                "Run and require exact NYAY-5 acceptance aggregate PASS"
                                in item
                                and "exact required contract" in item
                                for item in failures
                            ),
                            failures,
                        )

    def test_nested_database_gate_cannot_drop_or_bypass_required_native_gates(self) -> None:
        policy = load("verify_nyayone_ci")
        source = policy.DB_GATE
        original = source.read_text(encoding="utf-8")
        self.assertEqual(policy.check_db_gate_contract(source), [])
        nyay16 = (
            'NYAY16_GATE_ALLOW_DATABASES=true "$PY" scripts/nyay16_postgres_gate.py \\\n'
            "  --output test-results/nyay16-postgres/summary.json"
        )
        nyay3 = (
            '"$PY" scripts/nyay3_postgres_characterization.py \\\n'
            "  --expect hardened \\\n"
            "  --output test-results/nyay3-postgres/summary.json"
        )
        nyay2 = (
            '"$PY" scripts/nyay2_postgres_authorization_gate.py \\\n'
            "  --report test-results/nyay2-postgres/summary.json"
        )
        nyay5 = (
            'NYAY5_POSTGRES_GATE=1 "$PY" scripts/nyay5_postgres_profile_gate.py \\\n'
            "  --execute \\\n"
            '  --database-url "$DATABASE_URL" \\\n'
            "  --output test-results/nyay5-postgres/summary.json"
        )
        nyay17 = (
            '"$PY" scripts/nyay17_postgres_idempotency_gate.py \\\n'
            "  --report test-results/nyay17-postgres/summary.json"
        )
        nyay4 = (
            'NYAY4_POSTGRES_GATE=1 "$PY" scripts/nyay4_postgres_otp_gate.py \\\n'
            "  --execute \\\n"
            '  --database-url "$DATABASE_URL" \\\n'
            "  --output test-results/nyay4-postgres/summary.json"
        )
        nyay19 = (
            'NYAY19_POSTGRES_GATE_EXECUTE=1 "$PY" '
            "scripts/nyay19_postgres_auth_retention_gate.py \\\n"
            "  --execute \\\n"
            '  --database-url "$DATABASE_URL" \\\n'
            "  --output test-results/nyay19-postgres/summary.json"
        )
        self.assertEqual(original.count(nyay16), 1)
        self.assertEqual(original.count(nyay3), 1)
        self.assertEqual(original.count(nyay2), 1)
        self.assertEqual(original.count(nyay5), 1)
        self.assertEqual(original.count(nyay17), 1)
        self.assertEqual(original.count(nyay4), 1)
        self.assertEqual(original.count(nyay19), 1)
        mutations = {
            "deleted NYAY-16 invocation": original.replace(nyay16, "true", 1),
            "wrong NYAY-16 script": original.replace(
                "scripts/nyay16_postgres_gate.py",
                "scripts/not-the-nyay16-gate.py",
                1,
            ),
            "missing NYAY-16 database opt-in": original.replace(
                "NYAY16_GATE_ALLOW_DATABASES=true ", "", 1
            ),
            "discarded NYAY-16 report": original.replace(
                "test-results/nyay16-postgres/summary.json", "/dev/null", 1
            ),
            "conditional NYAY-16 bypass": original.replace(
                nyay16,
                "if false; then\n" + nyay16 + "\nfi",
                1,
            ),
            "deleted NYAY-3 invocation": original.replace(nyay3, "true", 1),
            "wrong NYAY-3 script": original.replace(
                "scripts/nyay3_postgres_characterization.py",
                "scripts/not-the-nyay3-gate.py",
                1,
            ),
            "NYAY-3 red mode": original.replace(
                "--expect hardened", "--expect current-vulnerable", 1
            ),
            "discarded NYAY-3 report": original.replace(
                "test-results/nyay3-postgres/summary.json", "/dev/null", 1
            ),
            "duplicated NYAY-3 invocation": original.replace(
                nyay3, nyay3 + "\n" + nyay3, 1
            ),
            "conditional NYAY-3 bypass": original.replace(
                nyay3, "if false; then\n" + nyay3 + "\nfi", 1
            ),
            "NYAY-3 ordered before NYAY-16": original.replace(
                nyay3, "true", 1
            ).replace(nyay16, nyay3 + "\n" + nyay16, 1),
            "deleted NYAY-2 invocation": original.replace(nyay2, "true", 1),
            "duplicated NYAY-2 invocation": original.replace(
                nyay2, nyay2 + "\n" + nyay2, 1
            ),
            "wrong NYAY-2 script": original.replace(
                "scripts/nyay2_postgres_authorization_gate.py",
                "scripts/not-the-nyay2-gate.py",
                1,
            ),
            "discarded NYAY-2 output": original.replace(
                nyay2, nyay2 + " >/dev/null", 1
            ),
            "conditional NYAY-2 bypass": original.replace(
                nyay2, "if false; then\n" + nyay2 + "\nfi", 1
            ),
            "NYAY-2 ordered before NYAY-3": original.replace(
                nyay2, "true", 1
            ).replace(nyay3, nyay2 + "\n" + nyay3, 1),
            "altered NYAY-2 report": original.replace(
                "test-results/nyay2-postgres/summary.json",
                "test-results/nyay2-postgres/substitute.json",
                1,
            ),
            "NYAY-2 non-executing help mode": original.replace(
                "  --report test-results/nyay2-postgres/summary.json",
                "  --help --report test-results/nyay2-postgres/summary.json",
                1,
            ),
            "masked NYAY-2 failure": original.replace(
                nyay2, nyay2 + " || true", 1
            ),
            "deleted NYAY-5 invocation": original.replace(nyay5, "true", 1),
            "duplicated NYAY-5 invocation": original.replace(
                nyay5, nyay5 + "\n" + nyay5, 1
            ),
            "wrong NYAY-5 script": original.replace(
                "scripts/nyay5_postgres_profile_gate.py",
                "scripts/not-the-nyay5-gate.py",
                1,
            ),
            "missing NYAY-5 opt-in": original.replace(
                "NYAY5_POSTGRES_GATE=1 ", "", 1
            ),
            "missing NYAY-5 execute flag": original.replace(
                nyay5,
                nyay5.replace("  --execute \\\n", "", 1),
                1,
            ),
            "altered NYAY-5 database authority": original.replace(
                nyay5,
                nyay5.replace(
                    '  --database-url "$DATABASE_URL"',
                    '  --database-url "postgresql://substitute"',
                    1,
                ),
                1,
            ),
            "altered NYAY-5 report": original.replace(
                "test-results/nyay5-postgres/summary.json",
                "test-results/nyay5-postgres/substitute.json",
                1,
            ),
            "NYAY-5 non-executing help mode": original.replace(
                nyay5,
                nyay5.replace("  --execute \\\n", "  --execute --help \\\n", 1),
                1,
            ),
            "conditional NYAY-5 bypass": original.replace(
                nyay5, "if false; then\n" + nyay5 + "\nfi", 1
            ),
            "masked NYAY-5 failure": original.replace(
                nyay5, nyay5 + " || true", 1
            ),
            "NYAY-5 ordered before NYAY-2": original.replace(
                nyay5, "true", 1
            ).replace(nyay2, nyay5 + "\n" + nyay2, 1),
            "deleted NYAY-17 invocation": original.replace(nyay17, "true", 1),
            "duplicated NYAY-17 invocation": original.replace(
                nyay17, nyay17 + "\n" + nyay17, 1
            ),
            "wrong NYAY-17 script": original.replace(
                "scripts/nyay17_postgres_idempotency_gate.py",
                "scripts/not-the-nyay17-gate.py",
                1,
            ),
            "altered NYAY-17 report": original.replace(
                "test-results/nyay17-postgres/summary.json",
                "test-results/nyay17-postgres/substitute.json",
                1,
            ),
            "NYAY-17 non-executing help mode": original.replace(
                "  --report test-results/nyay17-postgres/summary.json",
                "  --help --report test-results/nyay17-postgres/summary.json",
                1,
            ),
            "conditional NYAY-17 bypass": original.replace(
                nyay17, "if false; then\n" + nyay17 + "\nfi", 1
            ),
            "masked NYAY-17 failure": original.replace(
                nyay17, nyay17 + " || true", 1
            ),
            "NYAY-17 ordered before NYAY-2": original.replace(
                nyay17, "true", 1
            ).replace(nyay2, nyay17 + "\n" + nyay2, 1),
            "deleted NYAY-4 invocation": original.replace(nyay4, "true", 1),
            "duplicated NYAY-4 invocation": original.replace(
                nyay4, nyay4 + "\n" + nyay4, 1
            ),
            "wrong NYAY-4 script": original.replace(
                "scripts/nyay4_postgres_otp_gate.py",
                "scripts/not-the-nyay4-gate.py",
                1,
            ),
            "missing NYAY-4 opt-in": original.replace(
                "NYAY4_POSTGRES_GATE=1 ", "", 1
            ),
            "missing NYAY-4 execute flag": original.replace(
                "  --execute \\\n", "", 1
            ),
            "altered NYAY-4 database authority": original.replace(
                '  --database-url "$DATABASE_URL"',
                '  --database-url "postgresql://substitute"',
                1,
            ),
            "altered NYAY-4 report": original.replace(
                "test-results/nyay4-postgres/summary.json",
                "test-results/nyay4-postgres/substitute.json",
                1,
            ),
            "NYAY-4 non-executing help mode": original.replace(
                "  --execute \\\n", "  --execute --help \\\n", 1
            ),
            "conditional NYAY-4 bypass": original.replace(
                nyay4, "if false; then\n" + nyay4 + "\nfi", 1
            ),
            "masked NYAY-4 failure": original.replace(
                nyay4, nyay4 + " || true", 1
            ),
            "NYAY-4 ordered before NYAY-17": original.replace(
                nyay4, "true", 1
            ).replace(nyay17, nyay4 + "\n" + nyay17, 1),
            "deleted NYAY-19 invocation": original.replace(nyay19, "true", 1),
            "duplicated NYAY-19 invocation": original.replace(
                nyay19, nyay19 + "\n" + nyay19, 1
            ),
            "wrong NYAY-19 script": original.replace(
                "scripts/nyay19_postgres_auth_retention_gate.py",
                "scripts/not-the-nyay19-gate.py",
                1,
            ),
            "missing NYAY-19 opt-in": original.replace(
                "NYAY19_POSTGRES_GATE_EXECUTE=1 ", "", 1
            ),
            "missing NYAY-19 execute flag": original.replace(
                nyay19,
                nyay19.replace("  --execute \\\n", "", 1),
                1,
            ),
            "altered NYAY-19 database authority": original.replace(
                nyay19,
                nyay19.replace(
                    '  --database-url "$DATABASE_URL"',
                    '  --database-url "postgresql://substitute"',
                    1,
                ),
                1,
            ),
            "altered NYAY-19 report": original.replace(
                "test-results/nyay19-postgres/summary.json",
                "test-results/nyay19-postgres/substitute.json",
                1,
            ),
            "NYAY-19 non-executing help mode": original.replace(
                nyay19,
                nyay19.replace("  --execute \\\n", "  --execute --help \\\n", 1),
                1,
            ),
            "conditional NYAY-19 bypass": original.replace(
                nyay19, "if false; then\n" + nyay19 + "\nfi", 1
            ),
            "masked NYAY-19 failure": original.replace(
                nyay19, nyay19 + " || true", 1
            ),
            "NYAY-19 ordered before NYAY-4": original.replace(
                nyay19, "true", 1
            ).replace(nyay4, nyay19 + "\n" + nyay4, 1),
            "NYAY-19 is not final": original + "\ntrue\n",
        }
        with tempfile.TemporaryDirectory() as directory:
            candidate = Path(directory) / "db_gate.sh"
            for label, mutated in mutations.items():
                with self.subTest(label=label):
                    self.assertNotEqual(mutated, original)
                    candidate.write_text(mutated, encoding="utf-8")
                    failures = policy.check_db_gate_contract(candidate)
                    self.assertTrue(failures, label)
                    if label == "deleted NYAY-16 invocation":
                        self.assertTrue(
                            any("invoke the exact NYAY-16" in item for item in failures),
                            failures,
                        )
                    if label == "deleted NYAY-3 invocation":
                        self.assertTrue(
                            any("invoke the exact NYAY-3" in item for item in failures),
                            failures,
                        )
                    if label == "deleted NYAY-2 invocation":
                        self.assertTrue(
                            any("invoke the exact NYAY-2" in item for item in failures),
                            failures,
                        )
                    if label == "deleted NYAY-5 invocation":
                        self.assertTrue(
                            any("invoke the exact NYAY-5" in item for item in failures),
                            failures,
                        )
                    if label == "deleted NYAY-17 invocation":
                        self.assertTrue(
                            any("invoke the exact NYAY-17" in item for item in failures),
                            failures,
                        )
                    if label == "deleted NYAY-4 invocation":
                        self.assertTrue(
                            any("invoke the exact NYAY-4" in item for item in failures),
                            failures,
                        )
                    if label == "deleted NYAY-19 invocation":
                        self.assertTrue(
                            any("invoke the exact NYAY-19" in item for item in failures),
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

    def test_wave3_requires_the_exact_nyay4_browser_gate(self) -> None:
        policy = load("verify_nyayone_ci")
        source = (
            HERE.parent.parent / ".github" / "workflows" /
            "wave3-credential-trust-gate.yml"
        )
        original = source.read_text(encoding="utf-8")
        self.assertEqual(policy.check_workflow(source), [])
        mutations = {
            "deleted gate": original.replace(
                "      - name: NYAY-4 OTP authority Chromium regression\n"
                "        working-directory: frontend\n"
                "        env:\n"
                "          NYAY4_WEB_BASE_URL: http://127.0.0.1:1170\n"
                "          NYAY4_API_BASE_URL: http://127.0.0.1:1171\n"
                "          NYAY4_OTP_CAPTURE_URL: http://127.0.0.1:1099\n"
                "        run: npm run qa:nyay4:otp-negative\n\n",
                "",
                1,
            ),
            "wrong API": original.replace(
                "NYAY4_API_BASE_URL: http://127.0.0.1:1171",
                "NYAY4_API_BASE_URL: http://127.0.0.1:9999",
                1,
            ),
            "masked failure": original.replace(
                "run: npm run qa:nyay4:otp-negative",
                "run: npm run qa:nyay4:otp-negative || true",
                1,
            ),
            "conditional gate": original.replace(
                "        run: npm run qa:nyay4:otp-negative",
                "        if: ${{ always() }}\n"
                "        run: npm run qa:nyay4:otp-negative",
                1,
            ),
        }
        with tempfile.TemporaryDirectory() as directory:
            candidate = Path(directory) / source.name
            for label, mutated in mutations.items():
                with self.subTest(label=label):
                    self.assertNotEqual(mutated, original)
                    candidate.write_text(mutated, encoding="utf-8")
                    failures = policy.check_workflow(candidate)
                    self.assertTrue(failures, label)
                    self.assertTrue(
                        any(
                            "NYAY-4 OTP authority Chromium regression" in item
                            or "canonical semantic contract" in item
                            for item in failures
                        ),
                        failures,
                    )

    def test_nyay4_transitive_jobs_require_frontend_dependencies_before_gate(self) -> None:
        policy = load("verify_nyayone_ci")
        node_failure = (
            "NYAY-4-transitive job must provision exact pinned Node 22 "
            "before its backend gate"
        )
        npm_failure = (
            "NYAY-4-transitive job must run exact npm ci from frontend "
            "before its backend gate"
        )

        wave3_path = (
            policy.ROOT / ".github/workflows/wave3-credential-trust-gate.yml"
        )
        wave3 = wave3_path.read_text(encoding="utf-8")
        self.assertEqual(policy.check_workflow(wave3_path), [])
        setup_node = (
            "      - uses: actions/setup-node@49933ea5288caeca8642d1e84afbd3f7d6820020 # v4.4.0\n"
            "        with:\n"
            '          node-version: "22"\n'
            "          cache: npm\n"
            "          cache-dependency-path: frontend/package-lock.json\n"
        )
        install_frontend = (
            "      - name: Install frontend and Chromium\n"
            "        working-directory: frontend\n"
            "        run: |\n"
            "          npm ci\n"
            "          npm exec -- playwright install --with-deps chromium\n"
        )
        gate = (
            "      - name: PostgreSQL migration and full backend gate\n"
            "        working-directory: backend\n"
            "        run: PYTHON=python bash scripts/db_gate.sh\n"
        )
        self.assertEqual(wave3.count(setup_node), 1)
        self.assertEqual(wave3.count(install_frontend), 1)
        self.assertEqual(wave3.count(gate), 1)
        without_node = wave3.replace(setup_node, "", 1)
        without_npm = wave3.replace("          npm ci\n", "", 1)
        mutations: dict[str, tuple[str, str]] = {
            "missing setup-node": (without_node, node_failure),
            "wrong Node version": (
                wave3.replace(
                    '          node-version: "22"',
                    '          node-version: "20"',
                    1,
                ),
                node_failure,
            ),
            "setup-node after gate": (
                without_node.replace(gate, gate + setup_node, 1),
                node_failure,
            ),
            "missing npm ci": (without_npm, npm_failure),
            "npm ci masked": (
                wave3.replace("          npm ci\n", "          npm ci || true\n", 1),
                npm_failure,
            ),
            "npm ci in backend": (
                wave3.replace(
                    "      - name: Install frontend and Chromium\n"
                    "        working-directory: frontend\n",
                    "      - name: Install frontend and Chromium\n"
                    "        working-directory: backend\n",
                    1,
                ),
                npm_failure,
            ),
            "npm ci after gate": (
                wave3.replace(install_frontend, "", 1).replace(
                    gate, gate + install_frontend, 1
                ),
                npm_failure,
            ),
        }
        with tempfile.TemporaryDirectory() as directory:
            candidate = Path(directory) / wave3_path.name
            for label, (mutated, expected) in mutations.items():
                with self.subTest(label=label):
                    self.assertNotEqual(mutated, wave3)
                    candidate.write_text(mutated, encoding="utf-8")
                    failures = policy.check_workflow(candidate)
                    self.assertTrue(
                        any(expected in failure for failure in failures),
                        failures,
                    )

        wave4_path = (
            policy.ROOT / ".github/workflows/wave4-private-reporting-gate.yml"
        )
        wave4 = wave4_path.read_text(encoding="utf-8")
        self.assertEqual(policy.check_workflow(wave4_path), [])
        full_suite_mutant = wave4.replace("          npm ci\n", "", 1)
        self.assertNotEqual(full_suite_mutant, wave4)
        with tempfile.TemporaryDirectory() as directory:
            candidate = Path(directory) / wave4_path.name
            candidate.write_text(full_suite_mutant, encoding="utf-8")
            failures = policy.check_workflow(candidate)
        self.assertTrue(
            any(npm_failure in failure for failure in failures), failures
        )

        wave5_path = policy.ROOT / ".github/workflows/wave5-calendar-gate.yml"
        wave5_failures = policy.check_workflow(wave5_path)
        self.assertFalse(
            any("NYAY-4-transitive job" in failure for failure in wave5_failures),
            wave5_failures,
        )

    def test_wave4_failure_diagnostic_upload_is_exact_and_fail_closed(self) -> None:
        policy = load("verify_nyayone_ci")
        workflow_path = (
            policy.ROOT / ".github/workflows/wave4-private-reporting-gate.yml"
        )
        source = workflow_path.read_text(encoding="utf-8")
        diagnostic = (
            "      - name: Upload privacy-safe S-86/S-87 failure diagnostic\n"
            "        if: ${{ failure() }}\n"
            "        uses: actions/upload-artifact@ea165f8d65b6e75b540449e92b4886f43607fa02 # v4.6.2\n"
            "        with:\n"
            "          name: wave4-reporting-failure-diagnostic\n"
            "          path: ${{ github.workspace }}/test-results/wave4-browser/results.json\n"
            "          if-no-files-found: error\n"
            "          retention-days: 14\n"
            "          include-hidden-files: false\n"
        )
        self.assertEqual(source.count(diagnostic), 1)
        mutations = {
            "missing": source.replace(diagnostic, "", 1),
            "success-only": source.replace(
                "        if: ${{ failure() }}\n",
                "        if: ${{ always() }}\n",
                1,
            ),
            "directory upload": source.replace(
                "          path: ${{ github.workspace }}/test-results/wave4-browser/results.json\n",
                "          path: ${{ github.workspace }}/test-results/wave4-browser\n",
                1,
            ),
            "missing file allowed": source.replace(
                "          if-no-files-found: error\n",
                "          if-no-files-found: warn\n",
                1,
            ),
            "hidden files included": source.replace(
                "          include-hidden-files: false\n",
                "          include-hidden-files: true\n",
                1,
            ),
        }
        with tempfile.TemporaryDirectory() as directory:
            candidate = Path(directory) / workflow_path.name
            for label, mutant in mutations.items():
                with self.subTest(label=label):
                    self.assertNotEqual(mutant, source)
                    candidate.write_text(mutant, encoding="utf-8")
                    failures = policy.check_workflow(candidate)
                    self.assertTrue(
                        any("diagnostic upload" in failure for failure in failures),
                        failures,
                    )

    def test_nyay4_failure_diagnostic_upload_is_exact_and_non_derivative(self) -> None:
        policy = load("verify_nyayone_ci")
        workflow_path = policy.ROOT / ".github/workflows/wave1-foundation-gate.yml"
        source = workflow_path.read_text(encoding="utf-8")
        producer = (
            "      - name: Wave 1 + registration DB gate (PostgreSQL 16 + pgvector)\n"
            "        run: PYTHON=python bash scripts/db_gate.sh\n"
        )
        diagnostic = (
            "      - name: Upload privacy-safe NYAY-4 failure diagnostic\n"
            "        if: ${{ failure() && hashFiles('backend/test-results/nyay4-postgres/summary.json') != '' }}\n"
            "        uses: actions/upload-artifact@ea165f8d65b6e75b540449e92b4886f43607fa02 # v4.6.2\n"
            "        with:\n"
            "          name: nyay4-postgres-failure-diagnostic\n"
            "          path: ${{ github.workspace }}/backend/test-results/nyay4-postgres/summary.json\n"
            "          if-no-files-found: error\n"
            "          retention-days: 14\n"
            "          include-hidden-files: false\n"
        )

        self.assertEqual(source.count(producer), 1)
        self.assertEqual(source.count(diagnostic), 1)
        self.assertEqual(source.count(producer + diagnostic), 1)
        mutations = {
            "always upload": diagnostic.replace(
                "failure() && hashFiles(", "always() && hashFiles(", 1
            ),
            "missing exact-file condition": diagnostic.replace(
                " && hashFiles('backend/test-results/nyay4-postgres/summary.json') != ''",
                "",
                1,
            ),
            "directory upload": diagnostic.replace(
                "backend/test-results/nyay4-postgres/summary.json",
                "backend/test-results/nyay4-postgres",
                1,
            ),
            "missing file allowed": diagnostic.replace(
                "if-no-files-found: error", "if-no-files-found: warn", 1
            ),
        }
        with tempfile.TemporaryDirectory() as directory:
            candidate = Path(directory) / workflow_path.name
            for label, mutant in mutations.items():
                with self.subTest(label=label):
                    self.assertNotEqual(mutant, diagnostic)
                    candidate.write_text(
                        source.replace(diagnostic, mutant, 1),
                        encoding="utf-8",
                    )
                    failures = policy.check_workflow(candidate)
                    self.assertTrue(
                        any("diagnostic upload" in failure for failure in failures),
                        failures,
                    )

    def test_nyay4_browser_executable_contract_rejects_seeded_mutants(self) -> None:
        policy = load("verify_nyayone_ci")
        self.assertEqual(policy.check_nyay4_browser_gate_contract(), [])
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            browser = root / "nyay4-otp-browser-negative.mjs"
            contract = root / "nyay4-otp-runner-contract.mjs"
            contract_test = root / "nyay4-otp-runner-contract.test.mjs"
            package = root / "package.json"
            browser.write_bytes(policy.NYAY4_BROWSER_GATE.read_bytes())
            contract.write_bytes(policy.NYAY4_BROWSER_CONTRACT.read_bytes())
            contract_test.write_bytes(policy.NYAY4_BROWSER_CONTRACT_TEST.read_bytes())
            package.write_bytes(policy.FRONTEND_PACKAGE.read_bytes())

            def failures() -> list[str]:
                return policy.check_nyay4_browser_gate_contract(
                    browser, contract, package, contract_test
                )

            browser.write_bytes(browser.read_bytes() + b"\n// planted no-op drift\n")
            self.assertTrue(failures())
            browser.write_bytes(policy.NYAY4_BROWSER_GATE.read_bytes())

            contract.write_text(
                contract.read_text(encoding="utf-8").replace(
                    "throw new Error('NYAY4_ASSERTION_INVENTORY_MISMATCH');",
                    "return;",
                    1,
                ),
                encoding="utf-8",
            )
            self.assertTrue(failures())
            contract.write_bytes(policy.NYAY4_BROWSER_CONTRACT.read_bytes())

            contract_test.write_bytes(
                contract_test.read_bytes() + b"\n// planted contract-test drift\n"
            )
            self.assertTrue(failures())
            contract_test.write_bytes(policy.NYAY4_BROWSER_CONTRACT_TEST.read_bytes())

            document = json.loads(package.read_text(encoding="utf-8"))
            document["scripts"]["qa:nyay4:otp-negative"] = "true"
            package.write_text(json.dumps(document), encoding="utf-8")
            self.assertTrue(failures())

            document = json.loads(policy.FRONTEND_PACKAGE.read_text(encoding="utf-8"))
            document["scripts"]["preqa:nyay4:otp-negative"] = "true"
            package.write_text(json.dumps(document), encoding="utf-8")
            self.assertTrue(failures())

    def test_wave3_requires_exact_isolated_nyay19_browser_steps(self) -> None:
        policy = load("verify_nyayone_ci")
        source = (
            HERE.parent.parent / ".github" / "workflows" /
            "wave3-credential-trust-gate.yml"
        )
        original = source.read_text(encoding="utf-8")
        self.assertEqual(policy.check_workflow(source), [])
        startup = (
            "      - name: Start NYAY-19 isolated auth lifecycle backend and frontend\n"
            "        env:\n"
            "          APP_ENV: test\n"
            "          CORS_ORIGINS: '[\"http://127.0.0.1:1180\"]'\n"
            "          OTP_DELIVERY_ENABLED: \"true\"\n"
            "          OTP_PROVIDER: http\n"
            "          OTP_PROVIDER_URL: http://127.0.0.1:1099/send\n"
            "          OTP_PROVIDER_SUPPORTS_IDEMPOTENCY: \"true\"\n"
            "          OTP_RESEND_COOLDOWN_SECONDS: \"1\"\n"
            "          OTP_FLOW_TTL_SECONDS: \"600\"\n"
            "          OTP_RECOVERY_PROOF_TTL_SECONDS: \"300\"\n"
            "          AUTH_SESSION_TTL_SECONDS: \"20\"\n"
            "          VITE_API_BASE_URL: http://127.0.0.1:1181\n"
            "        run: |\n"
            "          (cd backend && python -m uvicorn app.main:app --host 127.0.0.1 --port 1181 > \"$RUNNER_TEMP/nyay19-backend.log\" 2>&1 &)\n"
            "          (cd frontend && npm run dev -- --host 127.0.0.1 --port 1180 --strictPort > \"$RUNNER_TEMP/nyay19-frontend.log\" 2>&1 &)\n"
            "          for url in \\\n"
            "            http://127.0.0.1:1181/health \\\n"
            "            http://127.0.0.1:1180; do\n"
            "            for attempt in {1..60}; do\n"
            "              curl --fail --silent \"$url\" >/dev/null && break\n"
            "              if [[ \"$attempt\" == 60 ]]; then\n"
            "                echo \"Timed out waiting for $url\"\n"
            "                exit 1\n"
            "              fi\n"
            "              sleep 1\n"
            "            done\n"
            "          done\n\n"
        )
        browser = (
            "      - name: NYAY-19 authentication lifecycle Chromium regression\n"
            "        working-directory: frontend\n"
            "        env:\n"
            "          NYAY19_WEB_BASE_URL: http://127.0.0.1:1180\n"
            "          NYAY19_API_BASE_URL: http://127.0.0.1:1181\n"
            "          NYAY19_OTP_CAPTURE_URL: http://127.0.0.1:1099\n"
            "          NYAY19_SESSION_TTL_SECONDS: \"20\"\n"
            "          NYAY19_OTP_RESEND_COOLDOWN_SECONDS: \"1\"\n"
            "          NYAY19_OTP_FLOW_TTL_SECONDS: \"600\"\n"
            "          NYAY19_RECOVERY_PROOF_TTL_SECONDS: \"300\"\n"
            "        run: npm run qa:nyay19:auth-lifecycle\n\n"
        )
        self.assertEqual(original.count(startup), 1)
        self.assertEqual(original.count(browser), 1)
        mutations = {
            "deleted startup": original.replace(startup, "", 1),
            "duplicated startup": original.replace(startup, startup + startup, 1),
            "deleted browser gate": original.replace(browser, "", 1),
            "duplicated browser gate": original.replace(browser, browser + browser, 1),
            "wrong isolated backend port": original.replace(
                startup,
                startup.replace("--port 1181 >", "--port 9999 >", 1),
                1,
            ),
            "wrong isolated frontend port": original.replace(
                startup,
                startup.replace("--port 1180 --strictPort", "--port 9998 --strictPort", 1),
                1,
            ),
            "preview server substituted": original.replace(
                startup,
                startup.replace("npm run dev -- --host", "npm run preview -- --host", 1),
                1,
            ),
            "strict port removed": original.replace(
                startup,
                startup.replace(" --strictPort", "", 1),
                1,
            ),
            "wrong isolated CORS origin": original.replace(
                "CORS_ORIGINS: '[\"http://127.0.0.1:1180\"]'",
                "CORS_ORIGINS: '[\"http://127.0.0.1:1170\"]'",
                1,
            ),
            "wrong browser web authority": original.replace(
                "NYAY19_WEB_BASE_URL: http://127.0.0.1:1180",
                "NYAY19_WEB_BASE_URL: http://127.0.0.1:1170",
                1,
            ),
            "wrong browser API authority": original.replace(
                "NYAY19_API_BASE_URL: http://127.0.0.1:1181",
                "NYAY19_API_BASE_URL: http://127.0.0.1:1171",
                1,
            ),
            "wrong browser capture authority": original.replace(
                "NYAY19_OTP_CAPTURE_URL: http://127.0.0.1:1099",
                "NYAY19_OTP_CAPTURE_URL: http://127.0.0.1:9999",
                1,
            ),
            "deleted browser TTL binding": original.replace(
                "          NYAY19_SESSION_TTL_SECONDS: \"20\"\n",
                "",
                1,
            ),
            "duplicate browser env key": original.replace(
                "          NYAY19_WEB_BASE_URL: http://127.0.0.1:1180\n",
                "          NYAY19_WEB_BASE_URL: http://127.0.0.1:1180\n"
                "          NYAY19_WEB_BASE_URL: http://127.0.0.1:1180\n",
                1,
            ),
            "masked browser failure": original.replace(
                "run: npm run qa:nyay19:auth-lifecycle",
                "run: npm run qa:nyay19:auth-lifecycle || true",
                1,
            ),
            "conditional browser gate": original.replace(
                "        run: npm run qa:nyay19:auth-lifecycle",
                "        if: ${{ always() }}\n"
                "        run: npm run qa:nyay19:auth-lifecycle",
                1,
            ),
            "reordered startup and browser": original.replace(
                startup + browser, browser + startup, 1
            ),
            "interposed step": original.replace(
                startup + browser,
                startup + "      - run: echo interposed\n\n" + browser,
                1,
            ),
        }
        with tempfile.TemporaryDirectory() as directory:
            candidate = Path(directory) / source.name
            for label, mutated in mutations.items():
                with self.subTest(label=label):
                    self.assertNotEqual(mutated, original)
                    candidate.write_text(mutated, encoding="utf-8")
                    failures = policy.check_workflow(candidate)
                    self.assertTrue(failures, label)

    def test_nyay19_browser_executable_contract_rejects_seeded_mutants(self) -> None:
        policy = load("verify_nyayone_ci")
        self.assertEqual(policy.check_nyay19_browser_gate_contract(), [])
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            browser = root / "nyay19-auth-lifecycle-browser.mjs"
            contract = root / "nyay19-auth-lifecycle-runner-contract.mjs"
            contract_test = root / "nyay19-auth-lifecycle-runner-contract.test.mjs"
            package = root / "package.json"

            def reset() -> None:
                browser.write_bytes(policy.NYAY19_BROWSER_GATE.read_bytes())
                contract.write_bytes(policy.NYAY19_BROWSER_CONTRACT.read_bytes())
                contract_test.write_bytes(
                    policy.NYAY19_BROWSER_CONTRACT_TEST.read_bytes()
                )
                package.write_bytes(policy.FRONTEND_PACKAGE.read_bytes())

            def failures() -> list[str]:
                return policy.check_nyay19_browser_gate_contract(
                    browser, contract, package, contract_test
                )

            reset()
            browser.write_bytes(browser.read_bytes() + b"\n// planted no-op drift\n")
            self.assertTrue(failures())

            reset()
            contract.write_bytes(contract.read_bytes() + b"\n// planted no-op drift\n")
            self.assertTrue(failures())

            reset()
            contract_test.write_bytes(
                contract_test.read_bytes() + b"\n// planted no-op drift\n"
            )
            self.assertTrue(failures())

            reset()
            document = json.loads(package.read_text(encoding="utf-8"))
            document["scripts"]["qa:nyay19:auth-lifecycle"] = "true"
            package.write_text(json.dumps(document), encoding="utf-8")
            self.assertTrue(failures())

            reset()
            document = json.loads(package.read_text(encoding="utf-8"))
            del document["scripts"]["qa:nyay19:auth-lifecycle"]
            package.write_text(json.dumps(document), encoding="utf-8")
            self.assertTrue(failures())

            for hook in (
                "preqa:nyay19:auth-lifecycle",
                "postqa:nyay19:auth-lifecycle",
            ):
                with self.subTest(hook=hook):
                    reset()
                    document = json.loads(package.read_text(encoding="utf-8"))
                    document["scripts"][hook] = "true"
                    package.write_text(json.dumps(document), encoding="utf-8")
                    self.assertTrue(failures())

    def test_nyay5_executable_chain_rejects_seeded_mutants(self) -> None:
        policy = load("verify_nyayone_ci")
        self.assertEqual(policy.check_nyay5_gate_contract(), [])
        pinned = {
            "orchestrator_path": policy.NYAY5_BROWSER_ORCHESTRATOR,
            "browser_path": policy.NYAY5_BROWSER_GATE,
            "contract_path": policy.NYAY5_BROWSER_CONTRACT,
            "contract_test_path": policy.NYAY5_BROWSER_CONTRACT_TEST,
            "control_path": policy.NYAY5_BROWSER_CONTROL,
            "postgres_path": policy.NYAY5_POSTGRES_GATE,
            "aggregate_path": policy.NYAY5_ACCEPTANCE_AGGREGATE,
            "aggregate_test_path": policy.NYAY5_ACCEPTANCE_AGGREGATE_TEST,
            "attestation_path": policy.NYAY5_ACCEPTANCE_ATTESTATION_PRODUCER,
            "attestation_test_path": policy.NYAY5_ACCEPTANCE_ATTESTATION_TEST,
        }
        for argument, source in pinned.items():
            with self.subTest(argument=argument), tempfile.TemporaryDirectory() as directory:
                mutant = Path(directory) / source.name
                mutant.write_bytes(source.read_bytes() + b"\n# planted semantic drift\n")
                failures = policy.check_nyay5_gate_contract(**{argument: mutant})
                self.assertTrue(
                    any("SHA-256 differs" in item for item in failures),
                    failures,
                )

        package = json.loads(policy.FRONTEND_PACKAGE.read_text(encoding="utf-8"))
        package_mutants = {
            "substituted browser command": (
                "qa:nyay5:profile-boundary",
                "node scripts/not-the-nyay5-gate.mjs",
            ),
            "non-executing browser help": (
                "qa:nyay5:profile-boundary",
                "node scripts/nyay5-profile-browser.mjs --help",
            ),
            "substituted aggregate command": (
                "qa:nyay5:acceptance",
                "node scripts/not-the-nyay5-aggregate.mjs",
            ),
            "non-executing aggregate help": (
                "qa:nyay5:acceptance",
                "node scripts/nyay5-acceptance-aggregate.mjs --help",
            ),
        }
        for label, (script_name, command) in package_mutants.items():
            with self.subTest(label=label), tempfile.TemporaryDirectory() as directory:
                mutant = Path(directory) / "package.json"
                candidate = json.loads(json.dumps(package))
                candidate["scripts"][script_name] = command
                mutant.write_text(json.dumps(candidate), encoding="utf-8")
                failures = policy.check_nyay5_gate_contract(package_path=mutant)
                self.assertTrue(
                    any("package command differs" in item for item in failures),
                    failures,
                )

        for hook in (
            "preqa:nyay5:profile-boundary",
            "postqa:nyay5:profile-boundary",
            "preqa:nyay5:acceptance",
            "postqa:nyay5:acceptance",
        ):
            with self.subTest(hook=hook), tempfile.TemporaryDirectory() as directory:
                mutant = Path(directory) / "package.json"
                candidate = json.loads(json.dumps(package))
                candidate["scripts"][hook] = "true"
                mutant.write_text(json.dumps(candidate), encoding="utf-8")
                failures = policy.check_nyay5_gate_contract(package_path=mutant)
                self.assertTrue(
                    any("npm lifecycle wrapper" in item for item in failures),
                    failures,
                )

    def test_nyay14_evidence_gate_contract_rejects_source_and_workflow_drift(self) -> None:
        policy = load("verify_nyayone_ci")
        self.assertEqual(policy.check_nyay14_evidence_gate_contract(), [])

        for label, source in policy.NYAY14_EVIDENCE_FILES.items():
            with self.subTest(label=label), tempfile.TemporaryDirectory() as directory:
                mutant = Path(directory) / source.name
                mutant.write_bytes(source.read_bytes() + b"\n# planted NYAY-14 drift\n")
                failures = policy.check_nyay14_evidence_gate_contract(
                    {label: mutant}
                )
                self.assertTrue(
                    any("SHA-256 differs" in item for item in failures),
                    failures,
                )

        workflow = policy.WORKFLOWS / "nyayone-policy-gate.yml"
        original = workflow.read_text(encoding="utf-8")
        required_steps = (
            (
                "Validate NYAY-14 exact-head evidence gate",
                policy.EXPECTED_NYAY14_POLICY_COMMAND,
            ),
            (
                "Prove NYAY-14 evidence gate fails closed under adversarial inputs",
                policy.EXPECTED_NYAY14_SECURITY_POLICY_COMMAND,
            ),
            (
                "Enforce NYAY-27 future contact-sheet evidence",
                policy.EXPECTED_NYAY27_POLICY_COMMAND,
            ),
        )
        for name, command in required_steps:
            with self.subTest(command=command), tempfile.TemporaryDirectory() as directory:
                self.assertIn(command, original)
                mutant = Path(directory) / workflow.name
                mutant.write_text(
                    original.replace(
                        f"      - name: {name}\n        run: {command}\n",
                        "",
                        1,
                    ),
                    encoding="utf-8",
                )
                failures = policy.check_workflow(mutant)
                self.assertTrue(
                    any("required gate command" in item for item in failures),
                    failures,
                )

    def test_nyay21_history_purge_tooling_is_sealed_and_blocking(self) -> None:
        policy = load("verify_nyayone_ci")
        self.assertEqual(policy.check_nyay21_history_purge_contract(), [])

        for label, source in policy.NYAY21_HISTORY_PURGE_FILES.items():
            with self.subTest(label=label), tempfile.TemporaryDirectory() as directory:
                mutant = Path(directory) / source.name
                mutant.write_bytes(source.read_bytes() + b"\n# planted NYAY-21 drift\n")
                failures = policy.check_nyay21_history_purge_contract(
                    {label: mutant}
                )
                self.assertTrue(
                    any("NYAY-21" in item and "SHA-256 differs" in item for item in failures),
                    failures,
                )

        workflow = policy.WORKFLOWS / "nyayone-policy-gate.yml"
        original = workflow.read_text(encoding="utf-8")
        command = policy.EXPECTED_NYAY21_POLICY_COMMAND
        self.assertIn(command, original)
        with tempfile.TemporaryDirectory() as directory:
            mutant = Path(directory) / workflow.name
            mutant.write_text(
                original.replace(
                    "      - name: Validate NYAY-21 history-purge tooling\n"
                    f"        run: {command}\n",
                    "",
                    1,
                ),
                encoding="utf-8",
            )
            failures = policy.check_workflow(mutant)
        self.assertTrue(
            any("required gate command" in item for item in failures),
            failures,
        )

        path_to_go_command = policy.EXPECTED_NYAY21_PATH_TO_GO_POLICY_COMMAND
        self.assertIn(path_to_go_command, original)
        with tempfile.TemporaryDirectory() as directory:
            mutant = Path(directory) / workflow.name
            mutant.write_text(
                original.replace(
                    "      - name: Validate NYAY-21 path-to-GO seal and restoration ceremony\n"
                    f"        run: {path_to_go_command}\n",
                    "",
                    1,
                ),
                encoding="utf-8",
            )
            failures = policy.check_workflow(mutant)
        self.assertTrue(
            any("required gate command" in item for item in failures),
            failures,
        )

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


class RewrittenHistoryBaseTests(unittest.TestCase):
    def setUp(self) -> None:
        import yaml

        workflow = yaml.safe_load((HERE.parent.parent / '.github/workflows/nyayone-policy-gate.yml').read_text())
        self.steps = workflow['jobs']['policy-contracts']['steps']
        self.script = next(step['run'] for step in self.steps if step.get('name') == 'Reject whitespace and patch corruption')
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.repo = Path(self.temp.name)
        self.git('init', '-q')
        self.git('config', 'user.name', 'Synthetic CI')
        self.git('config', 'user.email', 'synthetic@example.invalid')
        self.git('config', 'commit.gpgsign', 'false')
        (self.repo / 'sample.txt').write_text('first\n')
        self.git('add', '.')
        self.git('commit', '-qm', 'root')
        self.root = self.git('rev-parse', 'HEAD')

    def git(self, *args: str) -> str:
        return subprocess.check_output(['git', *args], cwd=self.repo, text=True).strip()

    def run_check(self, base: str, event: str = 'push') -> subprocess.CompletedProcess:
        env = {**os.environ, 'BASE_SHA': base, 'GITHUB_SHA': self.git('rev-parse', 'HEAD'),
               'GITHUB_EVENT_NAME': event, 'GITHUB_ENV': str(self.repo / 'ci-env')}
        return subprocess.run(['bash', '-e', '-c', self.script], cwd=self.repo, env=env, text=True, capture_output=True)

    def next_commit(self, content: str = 'second\n') -> None:
        (self.repo / 'sample.txt').write_text(content)
        self.git('add', '.')
        self.git('commit', '-qm', 'next')

    def test_unavailable_push_base_uses_parent_and_exports_it(self) -> None:
        self.next_commit()
        result = self.run_check('f' * 40)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('BASE_SHA=' + self.root, (self.repo / 'ci-env').read_text())

    def test_zero_base_and_root_commit_use_empty_tree(self) -> None:
        result = self.run_check('0' * 40)
        self.assertEqual(result.returncode, 0, result.stderr)
        empty_tree = subprocess.check_output(
            ['git', 'hash-object', '-t', 'tree', '--stdin'],
            input='', cwd=self.repo, text=True,
        ).strip()
        self.assertEqual((self.repo / 'ci-env').read_text(), f'BASE_SHA={empty_tree}\n')

    def test_root_whitespace_is_not_hidden_by_comparing_head_to_itself(self) -> None:
        (self.repo / 'sample.txt').write_text('bad root whitespace \n')
        self.git('add', '.')
        self.git('commit', '--amend', '--no-edit', '-q')
        self.assertNotEqual(self.run_check('0' * 40).returncode, 0)

    def test_dispatch_without_base_uses_parent(self) -> None:
        self.next_commit()
        result = self.run_check('', 'workflow_dispatch')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('BASE_SHA=' + self.root, (self.repo / 'ci-env').read_text())

    def test_existing_base_retains_whitespace_rejection(self) -> None:
        self.next_commit('bad trailing whitespace \n')
        self.assertNotEqual(self.run_check(self.root).returncode, 0)

    def test_missing_pr_base_does_not_silently_narrow_review(self) -> None:
        self.next_commit()
        self.assertNotEqual(self.run_check('f' * 40, 'pull_request').returncode, 0)

    def test_migration_check_uses_same_resolved_base(self) -> None:
        migration = next(step for step in self.steps if step.get('name') == 'Enforce forward-only migration history')
        self.assertNotIn('BASE_SHA', migration.get('env', {}))
        self.assertIn('"$BASE_SHA" "$GITHUB_SHA"', migration['run'])


if __name__ == "__main__":
    unittest.main()
