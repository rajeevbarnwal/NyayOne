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

    def test_owner_actor_and_rerun_actor_are_both_required(self):
        condition = self.workflow()["jobs"]["calibrate"]["if"]
        self.assertEqual(condition, "${{ github.event_name == 'workflow_dispatch' && github.ref == 'refs/heads/main' && github.actor == 'rajeevbarnwal' && github.triggering_actor == 'rajeevbarnwal' }}")

    def test_owner_dispatch_and_rerun_actor_matrix(self):
        # Interpret the workflow's actual conjunction, not a duplicated predicate.
        condition = self.workflow()["jobs"]["calibrate"]["if"]
        self.assertTrue(condition.startswith("${{ ") and condition.endswith(" }}"))
        clauses = []
        for clause in condition[4:-3].split(" && "):
            match = re.fullmatch(r"github\.(event_name|ref|actor|triggering_actor) == '([^']+)'", clause)
            self.assertIsNotNone(match, "unexpected condition grammar")
            clauses.append(match.groups())
        for label, actor, triggering_actor, event, ref, expected in (
            ("owner dispatch", "rajeevbarnwal", "rajeevbarnwal", "workflow_dispatch", "refs/heads/main", True),
            ("owner rerun", "rajeevbarnwal", "rajeevbarnwal", "workflow_dispatch", "refs/heads/main", True),
            ("collaborator reruns owner run", "rajeevbarnwal", "collaborator", "workflow_dispatch", "refs/heads/main", False),
            ("owner reruns collaborator run", "collaborator", "rajeevbarnwal", "workflow_dispatch", "refs/heads/main", False),
            ("collaborator dispatch", "collaborator", "collaborator", "workflow_dispatch", "refs/heads/main", False),
            ("missing rerun actor", "rajeevbarnwal", "", "workflow_dispatch", "refs/heads/main", False),
            ("wrong event", "rajeevbarnwal", "rajeevbarnwal", "push", "refs/heads/main", False),
            ("wrong ref", "rajeevbarnwal", "rajeevbarnwal", "workflow_dispatch", "refs/heads/other", False),
        ):
            with self.subTest(case=label):
                context = dict(actor=actor, triggering_actor=triggering_actor, event_name=event, ref=ref)
                self.assertEqual(all(context[key] == value for key, value in clauses), expected)

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
