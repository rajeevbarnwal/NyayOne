"""Offline contracts for owner-dispatched, artifact-only reference generation."""
from pathlib import Path
import re
import unittest
import yaml

ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = ROOT / ".github/workflows/nyay66-calibration.yml"


class CalibrationWorkflowContracts(unittest.TestCase):
    def workflow(self):
        self.assertTrue(WORKFLOW.is_file(), "manual calibration workflow missing")
        return yaml.load(WORKFLOW.read_text(), Loader=yaml.BaseLoader)

    def test_dispatch_only(self):
        workflow = self.workflow()
        self.assertEqual(set(workflow["on"]), {"workflow_dispatch"})
        self.assertEqual(workflow["on"]["workflow_dispatch"]["inputs"]["source_head"]["required"], "true")

    def test_read_only_token_and_no_persistence(self):
        workflow = self.workflow()
        self.assertEqual(workflow["permissions"], {})
        job = workflow["jobs"]["calibrate"]
        self.assertEqual(job["permissions"], {"contents": "read"})
        for step in job["steps"]:
            if str(step.get("uses", "")).startswith("actions/checkout@"):
                self.assertEqual(step["with"]["persist-credentials"], "false")
        self.assertNotIn("GH_TOKEN", WORKFLOW.read_text())
        self.assertNotIn("secrets.", WORKFLOW.read_text())

    def test_no_import_commit_or_merge(self):
        self.workflow()
        text = WORKFLOW.read_text()
        for pattern in (r"git\s+(push|commit)", r"gh\s+pr\s+merge", r"node\s+\S*import-reference", r"contents:\s*write"):
            self.assertIsNone(re.search(pattern, text))
        self.assertIn("actions/upload-artifact@", text)
        self.assertIn("if-no-files-found: error", text)

    def test_exact_head_and_runtime_pins(self):
        self.workflow()
        text = WORKFLOW.read_text()
        for required in ('^[a-f0-9]{40}$', 'github.workflow_sha', 'persist-credentials: false', '149.0.7827.55', '1.61.1', 'linux-x64', 'FONT_PIN_MISMATCH', 'REFERENCE_MANIFEST_MISMATCH', 'sha256sum -c SHA256SUMS'):
            self.assertIn(required, text)
        self.assertEqual(self.workflow()["jobs"]["calibrate"]["runs-on"], "ubuntu-24.04")

    def test_actions_immutable_and_candidates_not_checked_out_before_input_validation(self):
        steps = self.workflow()["jobs"]["calibrate"]["steps"]
        for step in steps:
            if "uses" in step:
                self.assertRegex(step["uses"], r"@[a-f0-9]{40}$")
        validation = next(i for i, step in enumerate(steps) if "^[a-f0-9]{40}$" in step.get("run", ""))
        candidate = next(i for i, step in enumerate(steps) if step.get("with", {}).get("path") == "candidate")
        self.assertLess(validation, candidate)


if __name__ == "__main__":
    unittest.main()
