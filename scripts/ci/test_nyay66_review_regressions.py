"""Seven Copilot regression contracts; synthetic data, no authenticated calls."""
import importlib.util
import json
from pathlib import Path
import subprocess
import tempfile
import unittest

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
        self.temp.cleanup()

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


# Inherited methods provide helpers, not a second run of the seven RED cases.
for _name in list(ReviewRegressions.__dict__):
    if _name.startswith("test_"):
        setattr(IntegrityAdversarial, _name, None)


if __name__ == "__main__":
    unittest.main()
