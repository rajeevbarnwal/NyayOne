"""Seven Copilot regression contracts; synthetic data, no authenticated calls."""
import importlib.util
import ast
import errno
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]


class ReviewRegressions(unittest.TestCase):
    def trust(self):
        path = ROOT / "scripts/ci/nyay66_trust.py"
        self.assertTrue(path.is_file(), "trusted, candidate-independent validator missing")
        spec = importlib.util.spec_from_file_location("nyay66_trust", path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    def test_01_push_and_dispatch_require_comparison_base(self):
        trust = self.trust()
        self.assertEqual(trust.comparison_base("push", {"before": "a" * 40}, "b" * 40), "a" * 40)
        for event in ({"before": "0" * 40}, {}):
            with self.assertRaisesRegex(ValueError, "COMPARISON_BASE_REQUIRED"):
                trust.comparison_base("push", event, "b" * 40)
        self.assertEqual(trust.comparison_base("workflow_dispatch", {}, "b" * 40), "b" * 40)
        with self.assertRaisesRegex(ValueError, "ENFORCEMENT_REGRESSION"):
            trust.progression(["S-03"], [])

    def test_02_token_reader_never_executes_candidate_code(self):
        workflow = (ROOT / ".github/workflows/nyay66-conformance.yml").read_text()
        self.assertNotIn("run: node scripts/nyay66-read-approvals.mjs", workflow)
        self.assertIn("pull_request_target:", workflow)
        self.assertIn("git show \"$TRUST_BASE:scripts/ci/nyay66_trust.py\"", workflow)
        self.assertIn("permissions: {}", workflow)
        self.assertIn("--read-only", workflow)

    def test_03_evaluator_changes_require_exact_owner_comment(self):
        trust = self.trust()
        old = {"frontend/scripts/nyay66-live.mjs": "a" * 64}
        new = {**old, "frontend/scripts/nyay66-live.mjs": "b" * 64}
        digest = trust.bundle_digest(new, {})
        approval = {"pr": 37, "commentId": 123, "bundleSha256": digest}
        with self.assertRaisesRegex(ValueError, "INTEGRITY_APPROVAL_REQUIRED"):
            trust.approve_change(old, new, {}, {}, approval, [])
        comment = {"id": 123, "approvalPr": 37, "user": {"login": "rajeevbarnwal"}, "body": f"NYAY66-INTEGRITY {digest}"}
        self.assertTrue(trust.approve_change(old, new, {}, {}, approval, [comment]))
        for changed in ({**comment, "id": 124}, {**comment, "approvalPr": 38}, {**comment, "user": {"login": "other"}}):
            with self.assertRaises(ValueError):
                trust.approve_change(old, new, {}, {}, approval, [changed])

    def test_04_coherent_reference_replacement_is_not_self_approval(self):
        trust = self.trust()
        old = {"frontend/test-baselines/nyay66/cache/a.png": "a" * 64}
        new = {key: "b" * 64 for key in old}
        settings = {"cache": "cache", "manifestSha256": "c" * 64}
        with self.assertRaisesRegex(ValueError, "INTEGRITY_APPROVAL_REQUIRED"):
            trust.approve_change(old, new, {}, settings, {"pr": 37, "commentId": 1, "bundleSha256": trust.bundle_digest(new, settings)}, [])

    def test_05_tolerance_metadata_is_bound_to_approved_numeric_values(self):
        trust = self.trust()
        settings = {"tolerances": trust.TOLERANCES, "ownerToleranceApproval": "NYAY-66:15382"}
        self.assertTrue(trust.validate_tolerances(settings))
        for delta in ({"tolerances": {**trust.TOLERANCES, "pixelRatio": 0.5}}, {"ownerToleranceApproval": "unapproved"}):
            with self.assertRaisesRegex(ValueError, "TOLERANCE_APPROVAL_MISMATCH"):
                trust.validate_tolerances({**settings, **delta})

    def test_06_cross_origin_api_is_aborted_not_mocked(self):
        self.assertIn("--env VITE_API_BASE_URL=", (ROOT / ".github/workflows/nyay66-conformance.yml").read_text())
        script = """
import {mockApplication} from './frontend/scripts/lib/nyay66-fixtures.mjs';
let handler; const errors=[];
const page={route:async(_,fn)=>{handler=fn;throw Error('captured')}};
try{await mockApplication(page,'S-03','http://127.0.0.1:4321',errors)}catch{}
for(const url of ['https://example.invalid/api/v1/login/channels','https://example.invalid/static.js']){
let action='';await handler({request:()=>({url:()=>url,method:()=> 'GET'}),abort:()=>{action='abort'},fulfill:()=>{action='fulfill'},continue:()=>{action='continue'}});
if(action!=='abort')throw Error('cross-origin API was fulfilled');}
if(errors.length!==2||errors.some(x=>x!=='OUTBOUND_REQUEST'))throw Error('missing classification');
"""
        result = subprocess.run(["node", "--input-type=module", "-e", script], cwd=ROOT, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_07_import_rejects_sample_hash_not_matching_png(self):
        # Full real calibration inventory, modified only in one report hash.
        script = """
import {validateReferenceFiles} from './frontend/scripts/lib/nyay66-reference.mjs';
import {createHash} from 'node:crypto';
const bytes=Buffer.from('synthetic PNG bytes'), hash=createHash('sha256').update(bytes).digest('hex');
const row={view:'s03',viewport:'mobile390',sampleHashes:['a'.repeat(64)]};
try{await validateReferenceFiles({rows:[row]},`${hash}  s03-mobile390-0.png`,async()=>bytes);throw Error('accepted')}catch(e){if(e.message!=='REFERENCE_SAMPLE_HASH_MISMATCH')throw e}
"""
        result = subprocess.run(["node", "--input-type=module", "-e", script], cwd=ROOT, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)


class IntegrityAdversarial(ReviewRegressions):
    # Reuse helpers without repeating the seven base cases in discovery.
    def setUp(self):
        self.module = self.trust()
        self.temp = tempfile.TemporaryDirectory(prefix="nyay66-trust-contract-")
        self.repo = Path(self.temp.name)
        self.run_git("init", "-q")
        self.run_git("config", "user.name", "Synthetic Contract")
        self.run_git("config", "user.email", "contract@example.invalid")
        self.write("frontend/scripts/nyay66-live.mjs", "// approved evaluator\n")
        self.write("frontend/test-baselines/nyay66/cache/sample.png", "synthetic sample")
        self.config = {"schema": 1, "tolerances": self.module.TOLERANCES, "ownerToleranceApproval": "NYAY-66:15382", "enforced": ["S-03"], "exceptions": []}
        self.write(self.module.POLICY, json.dumps(self.config))
        self.base = self.commit()

    def tearDown(self):
        # A late fixture file can race the final rmdir. Rewalk this same owned
        # TemporaryDirectory only; never ignore persistent or unrelated errors.
        for attempt in range(3):
            try:
                self.temp.cleanup()
                return
            except OSError as error:
                if error.errno != errno.ENOTEMPTY or attempt == 2:
                    raise

    def run_git(self, *args):
        return subprocess.check_output(["git", "-C", str(self.repo), *args], stderr=subprocess.PIPE).decode().strip()

    def write(self, path, content):
        destination = self.repo / path
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(content)

    def commit(self):
        self.run_git("add", ".")
        self.run_git("commit", "-qm", "synthetic contract snapshot")
        return self.run_git("rev-parse", "HEAD")

    def approve(self):
        head = self.run_git("rev-parse", "HEAD")
        digest = self.module.bundle_digest(self.module.inventory(self.repo, head), self.module.settings(self.config))
        self.config["integrityApproval"] = {"pr": 37, "commentId": 99, "bundleSha256": digest}
        self.write(self.module.POLICY, json.dumps(self.config))
        head = self.commit()
        comment = {"id": 99, "approvalPr": 37, "user": {"login": "rajeevbarnwal"}, "body": f"NYAY66-INTEGRITY {digest}"}
        return head, [comment]

    def test_08_real_git_change_cannot_reuse_prior_approval(self):
        head, comments = self.approve()
        self.assertEqual(self.module.validate(self.repo, self.base, head, comments)["head"], head)
        self.write("frontend/scripts/nyay66-live.mjs", "process.exit(0)\n")
        changed = self.commit()
        with self.assertRaisesRegex(ValueError, "INTEGRITY_APPROVAL_REQUIRED"):
            self.module.validate(self.repo, head, changed, comments)

    def test_09_manifest_replacement_and_new_evaluator_import_are_bound(self):
        head, comments = self.approve()
        self.write("frontend/test-baselines/nyay66/cache/manifest.json", '{"replacement":true}')
        self.write("frontend/scripts/lib/nyay66-new-import.mjs", "export const bypass=true")
        with self.assertRaises(ValueError):
            self.module.validate(self.repo, head, self.commit(), comments)

    def test_10_symlink_gate_file_refused(self):
        path = self.repo / "frontend/scripts/lib/nyay66-link.mjs"
        path.parent.mkdir(parents=True)
        path.symlink_to("../../unapproved.mjs")
        with self.assertRaisesRegex(ValueError, "UNSAFE_GATE_FILE"):
            self.module.inventory(self.repo, self.commit())

    def test_11_candidate_build_configuration_not_exported(self):
        self.write("frontend/vite.config.ts", "throw Error('must not run on host')")
        self.write("frontend/.npmrc", "script-shell=unapproved-shell")
        self.commit()
        head, comments = self.approve()
        self.module.validate(self.repo, self.base, head, comments)
        destination = self.repo / "export"
        self.module.export_bundle(self.repo, head, destination)
        self.assertFalse((destination / "frontend/vite.config.ts").exists())
        self.assertFalse((destination / "frontend/.npmrc").exists())
        self.assertTrue((destination / "frontend/scripts/nyay66-live.mjs").is_file())

    def test_12_removed_screen_fails_even_with_valid_approval(self):
        head, comments = self.approve()
        self.config["enforced"] = []
        self.write(self.module.POLICY, json.dumps(self.config))
        with self.assertRaisesRegex(ValueError, "ENFORCEMENT_REGRESSION"):
            self.module.validate(self.repo, head, self.commit(), comments)

    def test_13_edited_deleted_or_wrong_comment_fails(self):
        head, comments = self.approve()
        for altered in ([], [{**comments[0], "body": "approved generally"}], [{**comments[0], "id": True}]):
            with self.assertRaisesRegex(ValueError, "INTEGRITY_APPROVAL_REQUIRED"):
                self.module.validate(self.repo, self.base, head, altered)

    def test_14_unrelated_screen_changes_do_not_require_new_bundle_approval(self):
        head, comments = self.approve()
        self.write("frontend/src/screens/S03.tsx", "// synthetic product change")
        changed = self.commit()
        self.assertEqual(self.module.validate(self.repo, head, changed, comments)["head"], changed)

    def test_15_zero_or_missing_base_is_never_empty_progression(self):
        head, comments = self.approve()
        for base in ("0" * 40, "a" * 40):
            with self.assertRaises((ValueError, subprocess.CalledProcessError)):
                self.module.validate(self.repo, base, head, comments)

    def source_contract(self):
        contract = self.repo / "contracts/unicode-legal-name-v1.json"
        contract.parent.mkdir()
        contract.write_bytes(b'{"synthetic":"legal name \\u0915"}\n')
        return contract, self.commit(), self.repo / "materialized-contract.json"

    def export_source_in_subprocess(self, head, destination):
        # A regression that opens a FIFO must fail on timeout, never hang CI.
        script = """
import importlib.util, sys
spec = importlib.util.spec_from_file_location('trusted_reader', sys.argv[1])
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
module.export_source_contract(sys.argv[2], sys.argv[3], sys.argv[4])
"""
        return subprocess.run([sys.executable, "-c", script, str(ROOT / "scripts/ci/nyay66_trust.py"), str(self.repo), head, str(destination)], capture_output=True, text=True, timeout=5)

    def test_21_source_contract_materializes_exact_git_blob_in_fresh_file(self):
        contract, head, destination = self.source_contract()
        expected = contract.read_bytes()
        contract.write_bytes(b'{"uncommitted":"must not be mounted"}\n')
        self.module.export_source_contract(self.repo, head, destination)
        self.assertEqual(destination.read_bytes(), expected)
        self.assertFalse(destination.is_symlink())
        self.assertTrue(destination.is_file())
        self.assertEqual(destination.stat().st_mode & 0o777, 0o600)
        self.assertNotEqual(destination.stat().st_ino, contract.stat().st_ino)
        with self.assertRaises(FileExistsError):
            self.module.export_source_contract(self.repo, head, destination)
        self.assertEqual(destination.read_bytes(), expected)

    def test_22_source_contract_rejects_git_symlink_tree_and_gitlink(self):
        contract, head, destination = self.source_contract()
        blob = self.run_git("rev-parse", f"{head}:contracts/unicode-legal-name-v1.json")
        for mode, object_id in (("120000", blob), ("160000", self.base)):
            with self.subTest(mode=mode):
                self.run_git("update-index", "--cacheinfo", f"{mode},{object_id},contracts/unicode-legal-name-v1.json")
                tree = self.run_git("write-tree")
                revision = self.run_git("commit-tree", tree, "-m", "synthetic unsafe Git mode")
                with self.assertRaisesRegex(ValueError, "UNSAFE_SOURCE_CONTRACT_GIT_ENTRY"):
                    self.module.export_source_contract(self.repo, revision, destination)
                self.assertFalse(destination.exists())
        self.run_git("read-tree", head)
        contract.unlink()
        contract.mkdir()
        (contract / "nested.json").write_text("{}")
        revision = self.commit()
        with self.assertRaisesRegex(ValueError, "UNSAFE_SOURCE_CONTRACT_GIT_ENTRY"):
            self.module.export_source_contract(self.repo, revision, destination)
        self.assertFalse(destination.exists())

    def test_23_source_contract_rejects_checkout_symlink_directory_and_fifo(self):
        contract, head, destination = self.source_contract()
        outside = self.repo / "synthetic-private-file.json"
        outside.write_text('{"synthetic":"must remain untouched"}')
        for kind in ("symlink", "directory", "fifo"):
            with self.subTest(kind=kind):
                contract.unlink()
                if kind == "symlink":
                    contract.symlink_to(outside)
                elif kind == "directory":
                    contract.mkdir()
                else:
                    os.mkfifo(contract)
                try:
                    result = self.export_source_in_subprocess(head, destination)
                    self.assertNotEqual(result.returncode, 0)
                    self.assertIn("UNSAFE_SOURCE_CONTRACT_PATH", result.stderr)
                    self.assertFalse(destination.exists())
                finally:
                    if kind == "directory":
                        contract.rmdir()
                    else:
                        contract.unlink()
                    contract.write_text("{}")
        self.assertEqual(outside.read_text(), '{"synthetic":"must remain untouched"}')

    def test_24_source_contract_rejects_symlinked_checkout_parent(self):
        contract, head, destination = self.source_contract()
        contract.parent.rename(self.repo / "actual-contracts")
        (self.repo / "contracts").symlink_to(self.repo / "actual-contracts", target_is_directory=True)
        result = self.export_source_in_subprocess(head, destination)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("UNSAFE_SOURCE_CONTRACT_PATH", result.stderr)
        self.assertFalse(destination.exists())

    def test_25_source_contract_rejects_missing_blob_and_destination_symlink(self):
        contract, head, destination = self.source_contract()
        with self.assertRaisesRegex(ValueError, "UNSAFE_SOURCE_CONTRACT_GIT_ENTRY"):
            self.module.export_source_contract(self.repo, self.base, destination)
        destination.symlink_to(contract)
        expected = contract.read_bytes()
        with self.assertRaises(FileExistsError):
            self.module.export_source_contract(self.repo, head, destination)
        self.assertEqual(contract.read_bytes(), expected)

    def test_26_source_contract_cli_requires_matching_head_authorization(self):
        contract, _, destination = self.source_contract()
        head, comments = self.approve()
        authorization = self.module.validate(self.repo, self.base, head, comments)
        path = self.repo / "synthetic-authorization.json"
        path.write_text(json.dumps({**authorization, "head": "f" * 40}))
        command = [sys.executable, str(ROOT / "scripts/ci/nyay66_trust.py"), "--repo", str(self.repo), "--base", self.base, "--head", head, "--authorization", str(path), "--export-source-contract", str(destination)]
        rejected = subprocess.run(command, capture_output=True, text=True, timeout=5)
        self.assertNotEqual(rejected.returncode, 0)
        self.assertIn("AUTHORIZATION_HEAD_MISMATCH", rejected.stderr)
        self.assertFalse(destination.exists())
        path.write_text(json.dumps(authorization))
        accepted = subprocess.run(command, capture_output=True, text=True, timeout=5)
        self.assertEqual(accepted.returncode, 0, accepted.stderr)
        self.assertEqual(destination.read_bytes(), contract.read_bytes())


class ConformanceEligibilityRegression(unittest.TestCase):
    def eligible(self, event_name, *, fork=False, ref="refs/heads/main", number=42,
                 base="a" * 40, actor="contributor", repository="rajeevbarnwal/NyayOne"):
        workflow = (ROOT / ".github/workflows/nyay66-conformance.yml").read_text()
        expression = workflow.split("  conformance-live:\n", 1)[1].split("    if: >-\n", 1)[1].split("    runs-on:", 1)[0]
        expression = " ".join(expression.split()).replace("&&", " and ").replace("||", " or ")
        github = {"event_name": event_name, "ref": ref, "actor": actor, "repository": repository, "event": {}}
        if event_name in {"pull_request", "pull_request_target"}:
            github["event"]["pull_request"] = {"number": number, "base": {"sha": base}, "head": {"repo": {"full_name": "other/fork" if fork else repository}}}

        # Interpret only the boolean workflow gate; never execute workflow text.
        def evaluate(node):
            if isinstance(node, ast.Constant):
                return node.value
            if isinstance(node, ast.Name) and node.id == "github":
                return github
            if isinstance(node, ast.Attribute):
                return evaluate(node.value).get(node.attr, {})
            if isinstance(node, ast.BoolOp):
                values = (evaluate(value) for value in node.values)
                return all(values) if isinstance(node.op, ast.And) else any(values)
            if isinstance(node, ast.Compare) and len(node.ops) == 1:
                left, right = evaluate(node.left), evaluate(node.comparators[0])
                if isinstance(node.ops[0], ast.Eq):
                    return left == right
                if isinstance(node.ops[0], ast.NotEq):
                    return left != right
            self.fail(f"Unsupported workflow gate syntax: {ast.dump(node)}")

        return bool(evaluate(ast.parse(expression, mode="eval").body))

    def test_same_repository_target_prs_and_main_pushes_are_eligible(self):
        self.assertTrue(self.eligible("pull_request_target"))
        self.assertTrue(self.eligible("push"))

    def test_forks_never_run_the_mount_job_including_bootstrap_target_events(self):
        for event in ("pull_request", "pull_request_target"):
            for number, base in ((42, "a" * 40), (37, "10c38bed2c50e9c7ccd66c0aead516593b3d9660")):
                with self.subTest(event=event, number=number):
                    self.assertFalse(self.eligible(event, fork=True, number=number, base=base))

    def test_dispatch_other_refs_and_other_events_are_ineligible(self):
        for actor in ("contributor", "rajeevbarnwal"):
            with self.subTest(actor=actor):
                self.assertFalse(self.eligible("workflow_dispatch", actor=actor))
        for ref in ("refs/heads/feature", "refs/tags/main", "refs/pull/42/merge"):
            with self.subTest(ref=ref):
                self.assertFalse(self.eligible("push", ref=ref))
        for event in ("schedule", "workflow_run", "issue_comment"):
            with self.subTest(event=event):
                self.assertFalse(self.eligible(event))

    def test_retired_bootstrap_keeps_exact_pr_and_base_requirements(self):
        bootstrap = "10c38bed2c50e9c7ccd66c0aead516593b3d9660"
        self.assertTrue(self.eligible("pull_request", number=37, base=bootstrap))
        self.assertFalse(self.eligible("pull_request", number=38, base=bootstrap))
        self.assertFalse(self.eligible("pull_request", number=37, base="a" * 40))


class DisposableGitCleanupRegression(unittest.TestCase):
    def fixture(self, temp):
        fixture = IntegrityAdversarial()
        fixture.temp = temp
        return fixture

    def test_late_file_at_root_removal_is_deleted(self):
        # Deterministically reproduce ENOTEMPTY without a timing-dependent writer.
        with tempfile.TemporaryDirectory(prefix="nyay66-cleanup-regression-") as parent:
            temp = tempfile.TemporaryDirectory(dir=parent)
            repo = Path(temp.name)
            (repo / ".git").mkdir()
            (repo / ".git" / "config").write_text("synthetic fixture")
            rmdir = os.rmdir
            injected = []

            def late_file(path, *args, **kwargs):
                if str(path) == temp.name and not injected:
                    (repo / "late-fixture.lock").write_text("synthetic late file")
                    injected.append(True)
                return rmdir(path, *args, **kwargs)

            with mock.patch("os.rmdir", side_effect=late_file):
                self.fixture(temp).tearDown()
            self.assertEqual(injected, [True])
            self.assertFalse(repo.exists(), "teardown must remove the late file and root")

    def test_persistent_nonempty_refuses_after_three_attempts(self):
        failure = OSError(errno.ENOTEMPTY, "persistent fixture writer")
        temp = mock.Mock()
        temp.cleanup.side_effect = failure
        with self.assertRaises(OSError) as raised:
            self.fixture(temp).tearDown()
        self.assertIs(raised.exception, failure)
        self.assertEqual(temp.cleanup.call_count, 3)

    def test_unrelated_cleanup_errors_are_not_suppressed_or_retried(self):
        for code in (errno.EACCES, errno.EIO):
            with self.subTest(errno=code):
                failure = OSError(code, "unrelated cleanup failure")
                temp = mock.Mock()
                temp.cleanup.side_effect = failure
                with self.assertRaises(OSError) as raised:
                    self.fixture(temp).tearDown()
                self.assertIs(raised.exception, failure)
                temp.cleanup.assert_called_once_with()

    def test_readonly_git_file_and_external_symlink_are_safe(self):
        with tempfile.TemporaryDirectory(prefix="nyay66-cleanup-regression-") as parent:
            outside = Path(parent) / "outside.txt"
            outside.write_text("must remain untouched")
            temp = tempfile.TemporaryDirectory(dir=parent)
            repo = Path(temp.name)
            readonly = repo / "packed-refs"
            readonly.write_text("synthetic refs")
            readonly.chmod(0o400)
            (repo / "external-link").symlink_to(outside)
            self.fixture(temp).tearDown()
            self.assertFalse(repo.exists())
            self.assertEqual(outside.read_text(), "must remain untouched")
            # Idempotence uses TemporaryDirectory's missing-root handling.
            self.fixture(temp).tearDown()


class ContainerCopyRegression(unittest.TestCase):
    def build_step(self):
        workflow = (ROOT / ".github/workflows/nyay66-conformance.yml").read_text()
        return workflow.split("      - name: Build candidate in a credential-free disposable container\n", 1)[1].split("      - name:", 1)[0]

    def test_18_dependencies_keep_node_modules_package_resolution_layout(self):
        build = self.build_step()
        self.assertIn("cp -a --no-preserve=ownership /dependencies node_modules", build)
        self.assertNotIn("ln -s /dependencies node_modules", build)
        self.assertIn("dst=/dependencies,readonly", build)

    def test_19_imported_json_contract_is_available_read_only(self):
        build = self.build_step()
        contract = "contracts/unicode-legal-name-v1.json"
        # This suite also runs inside the trusted evaluator export, which must
        # not contain candidate product files. Validate the workflow's read-only
        # mapping here; the complete container rehearsal validates the import.
        self.assertIn(f'src="$RUNNER_TEMP/nyay66-source-contract.json",dst=/tmp/{contract},readonly', build)
        self.assertNotIn(f'src="$GITHUB_WORKSPACE/{contract}"', build)
        self.assertNotIn(f'dst=/tmp/{contract},rw', build)

    def test_source_contract_is_materialized_by_trusted_reader_after_authorization(self):
        workflow = (ROOT / ".github/workflows/nyay66-conformance.yml").read_text()
        export = workflow.split("      - name: Save only public verified approval data\n", 1)[1].split("      - uses:", 1)[0]
        self.assertIn('python "$RUNNER_TEMP/nyay66-trusted.py" --repo "$GITHUB_WORKSPACE"', export)
        self.assertIn('--head "$CANDIDATE_HEAD"', export)
        self.assertIn('--authorization "$RUNNER_TEMP/nyay66-authorization.json"', export)
        self.assertIn('--export-source-contract "$RUNNER_TEMP/nyay66-source-contract.json"', export)

    def test_source_contract_handoff_supports_the_previous_base_reader(self):
        workflow = (ROOT / ".github/workflows/nyay66-conformance.yml").read_text()
        export = workflow.split("      - name: Save only public verified approval data\n", 1)[1].split("      - uses:", 1)[0]
        calls = export.split('python "')[1:]
        self.assertEqual(len(calls), 2, "base reader must approve/export before the approved reader handles the new option")
        old_reader, approved_reader = calls
        self.assertTrue(old_reader.startswith('$RUNNER_TEMP/nyay66-trusted.py"'))
        self.assertIn('--export "$RUNNER_TEMP/nyay66-trusted"', old_reader)
        self.assertNotIn("--export-source-contract", old_reader)
        self.assertTrue(approved_reader.startswith('$RUNNER_TEMP/nyay66-trusted/scripts/ci/nyay66_trust.py"'))
        self.assertIn('--export-source-contract "$RUNNER_TEMP/nyay66-source-contract.json"', approved_reader)
        for call in calls:
            self.assertIn('--repo "$GITHUB_WORKSPACE"', call)
            self.assertIn('--base "$NYAY66_BASE" --head "$CANDIDATE_HEAD"', call)
            self.assertIn('--authorization "$RUNNER_TEMP/nyay66-authorization.json"', call)
        self.assertNotIn('python "$GITHUB_WORKSPACE/', workflow)
        self.assertNotIn("GH_TOKEN", export)
        self.assertNotIn("github.token", export)

    def test_20_vite_temp_is_in_private_writable_scratch_not_host_dependencies(self):
        build = self.build_step()
        self.assertIn("--tmpfs /tmp:rw,exec,size=6g", build)
        self.assertIn("cd /tmp/app; cp -a --no-preserve=ownership /dependencies node_modules; npm run build", build)
        self.assertIn("dst=/input,readonly", build)
        self.assertIn("dst=/dependencies,readonly", build)
        self.assertIn("--cap-drop ALL", build)
        self.assertNotIn("chmod", build)
        self.assertNotIn("GH_TOKEN", build)
        self.assertNotIn("--env-file", build)

    def test_17_container_build_uses_runner_uid_for_output_directory(self):
        workflow = (ROOT / ".github/workflows/nyay66-conformance.yml").read_text()
        build = workflow.split("      - name: Build candidate in a credential-free disposable container\n", 1)[1].split("      - name:", 1)[0]
        self.assertIn('--user "$(id -u):$(id -g)"', build)
        self.assertNotIn("chmod 777", build)
        self.assertNotIn("--cap-add", build)

    def test_16_capability_free_copy_does_not_preserve_host_ownership(self):
        workflow = (ROOT / ".github/workflows/nyay66-conformance.yml").read_text()
        build = workflow.split("      - name: Build candidate in a credential-free disposable container\n", 1)[1].split("      - name:", 1)[0]
        # Both boundaries retain bytes/modes/symlinks, but never attempt chown.
        self.assertIn("cp -a --no-preserve=ownership /input /tmp/app", build)
        self.assertIn("cp -a --no-preserve=ownership dist/. /output/", build)
        self.assertIn("--cap-drop ALL", build)
        self.assertIn("--read-only", build)
        self.assertIn("--security-opt no-new-privileges", build)
        self.assertNotIn("--cap-add", build)
        self.assertNotIn("--privileged", build)
        self.assertIn("Candidate build emitted a symlink", build)


# Inherited methods provide helpers, not a second run of the seven RED cases.
for _name in list(ReviewRegressions.__dict__):
    if _name.startswith("test_"):
        setattr(IntegrityAdversarial, _name, None)


class ComponentBuildPlumbingRegression(unittest.TestCase):
    def hook(self):
        workflow = (ROOT / ".github/workflows/nyay66-conformance.yml").read_text()
        line = next(line for line in workflow.splitlines() if "sh -eu -c '" in line)
        return line.split("npm run build;", 1)[1].split("cp -a --no-preserve=ownership dist/.", 1)[0]

    def execute_hook(self, present, status=0):
        with tempfile.TemporaryDirectory(prefix="nyay66-component-hook-") as directory:
            root = Path(directory)
            if present:
                (root / "scripts").mkdir()
                (root / "scripts/nyay66-s01-component-build.mjs").write_text("// synthetic fixture builder\n")
            shell = 'node() { printf "BUILD:%s\\n" "$1"; return ' + str(status) + '; }; ' + self.hook()
            return subprocess.run(["sh", "-eu", "-c", shell], cwd=root, text=True, capture_output=True)

    def test_present_component_builder_runs_after_production_build(self):
        result = self.execute_hook(True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, "BUILD:scripts/nyay66-s01-component-build.mjs\n")

    def test_absent_component_builder_does_not_fabricate_component_evidence(self):
        result = self.execute_hook(False)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, "")
        self.assertNotIn("touch", self.hook())

    def test_component_builder_failure_stops_before_output_copy(self):
        result = self.execute_hook(True, status=17)
        self.assertEqual(result.returncode, 17, result.stderr)

    def test_component_hook_keeps_existing_container_isolation(self):
        workflow = (ROOT / ".github/workflows/nyay66-conformance.yml").read_text()
        build = workflow.split("      - name: Build candidate in a credential-free disposable container", 1)[1].split("      - name:", 1)[0]
        for rail in ("--read-only", "--cap-drop ALL", "--security-opt no-new-privileges", '--user "$(id -u):$(id -g)"', "dst=/input,readonly", "dst=/dependencies,readonly"):
            self.assertIn(rail, build)
        self.assertNotIn("GH_TOKEN", build)
        self.assertNotIn("github.token", build)
        self.assertEqual(workflow.count("node scripts/nyay66-s01-component-build.mjs"), 1)


if __name__ == "__main__":
    unittest.main()
