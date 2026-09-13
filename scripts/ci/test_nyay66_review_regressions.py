"""Seven Copilot regression contracts; synthetic data, no authenticated calls."""
import importlib.util
import errno
import json
import os
from pathlib import Path
import subprocess
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
        self.assertIn(f'src="$GITHUB_WORKSPACE/{contract}",dst=/tmp/{contract},readonly', build)
        self.assertNotIn(f'dst=/tmp/{contract},rw', build)

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


if __name__ == "__main__":
    unittest.main()
