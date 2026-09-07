"""NYAY-42 rollout contracts: selection is observation, never execution evidence."""
import copy
import unittest

try:
    import nyay42_optimization as gate
except ImportError:
    gate = None


class OptimizationTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(gate, "NYAY42_IMPLEMENTATION_ABSENT")

    def plan(self, paths=None, **kw):
        return gate.select_campaign(paths if paths is not None else ["README.md"],
                                    base="a" * 40, head="b" * 40,
                                    event=kw.get("event", "pull_request"),
                                    history_complete=kw.get("history_complete", True))

    def test_document_only_plan_is_observe_only(self):
        p = self.plan()
        self.assertEqual(p["candidateProducers"], [])
        self.assertEqual(p["executeProducers"], list(gate.PRODUCERS))
        self.assertIs(p["mergeAuthorized"], False)
        self.assertEqual(p["mode"], "observe-only")

    def test_shared_authority_changes_select_full(self):
        for path in ["backend/app/auth.py", "frontend/src/App.tsx", "scripts/ci/scan_evidence.py",
                     ".github/workflows/registration-db-gate.yml", "backend/alembic/versions/new.py",
                     "docs/architecture/ceremony.md", "frontend/package-lock.json"]:
            with self.subTest(path=path):
                self.assertEqual(self.plan([path])["candidateProducers"], list(gate.PRODUCERS))

    def test_unknown_and_incomplete_history_select_full(self):
        for p in [self.plan(["new-surface/file"]), self.plan(history_complete=False), self.plan([])]:
            self.assertEqual(p["candidateProducers"], list(gate.PRODUCERS))

    def test_main_and_nightly_always_full(self):
        for event in ["push", "schedule", "workflow_dispatch"]:
            self.assertEqual(self.plan(event=event)["candidateProducers"], list(gate.PRODUCERS))

    def test_invalid_input_has_canonical_safe_diagnostic(self):
        for path in ["../secret", "/private/name", "a\nprivate", "clean%2585row"]:
            with self.assertRaisesRegex(ValueError, "^NYAY42_INPUT_INVALID$"):
                self.plan([path])
        with self.assertRaisesRegex(ValueError, "^NYAY42_INPUT_INVALID$"):
            gate.select_campaign(["README.md"], base="no", head="b"*40,
                                 event="pull_request", history_complete=True)

    def test_seal_changes_with_exact_head_and_diff(self):
        a = self.plan()
        b = self.plan(["README.md", "LICENSE"])
        self.assertNotEqual(a["selectionSha256"], b["selectionSha256"])
        self.assertNotIn("paths", a)
        self.assertEqual(a, self.plan())

    def test_existing_required_contexts_are_not_redefined(self):
        self.assertEqual(len(gate.REQUIRED_CONTEXTS), 7)
        self.assertEqual(self.plan()["requiredContexts"], list(gate.REQUIRED_CONTEXTS))

    def test_fallback_is_bounded_and_never_changes_a_rerun_route(self):
        p = gate.fallback_plan(offline_seconds=601, already_dispatched=False,
                               reviewed_head="b"*40, remote_head="b"*40)
        self.assertEqual(p["action"], "HOSTED_DISPATCH_REQUIRED")
        self.assertIs(p["execute"], False)
        for seconds, sent in [(600, False), (601, True)]:
            self.assertEqual(gate.fallback_plan(offline_seconds=seconds,
                             already_dispatched=sent, reviewed_head="b"*40,
                             remote_head="b"*40)["action"], "WAIT")

    def test_head_change_invalidates_fallback(self):
        p = gate.fallback_plan(offline_seconds=601, already_dispatched=False,
                              reviewed_head="b"*40, remote_head="c"*40)
        self.assertEqual(p["action"], "HEAD_CHANGED")
        self.assertIs(p["execute"], False)

    def test_boolean_counts_rejected(self):
        with self.assertRaisesRegex(ValueError, "NYAY42_INPUT_INVALID"):
            gate.fallback_plan(offline_seconds=True, already_dispatched=False,
                               reviewed_head="b"*40, remote_head="b"*40)

    def test_measurement_cannot_start_before_migration(self):
        self.assertEqual(gate.measure([], migration_at=None, observed_until=1209600,
                                     baseline_week_minutes=1000,
                                     baseline_campaign_minutes=100)["verdict"], "NOT_STARTED")

    def rows(self):
        return [{"jobId":str(i), "attempt":1, "startedAt":i*86400,
                 "seconds":60, "hosted":True, "campaign":"pr-1",
                 "conclusion":"failure" if i == 0 else "success"} for i in range(14)]

    def test_fourteen_days_and_both_metrics_required(self):
        p = gate.measure(self.rows(), migration_at=0, observed_until=1209600,
                         baseline_week_minutes=1000, baseline_campaign_minutes=100)
        self.assertEqual(p["verdict"], "TARGET_MET")
        self.assertEqual(p["hostedMinutes"], 14)
        self.assertEqual(p["weeklyHostedMinutes"], [7, 7])

    def test_partial_window_is_not_pass(self):
        self.assertEqual(gate.measure(self.rows()[:7], migration_at=0, observed_until=604800,
                         baseline_week_minutes=1000, baseline_campaign_minutes=100)["verdict"], "IN_PROGRESS")

    def test_duplicates_missing_data_and_zero_counts_fail_closed(self):
        for rows in [[], self.rows()+[self.rows()[0]], [{"jobId":"1"}]]:
            with self.subTest(rows=len(rows)), self.assertRaisesRegex(ValueError, "NYAY42_INPUT_INVALID"):
                gate.measure(rows, migration_at=0, observed_until=1209600,
                             baseline_week_minutes=1000, baseline_campaign_minutes=100)

    def test_failures_reruns_and_nightlies_are_counted(self):
        rows=self.rows()
        extra=copy.deepcopy(rows[0]); extra.update(attempt=2, seconds=61, campaign="unmerged")
        rows.append(extra)
        p=gate.measure(rows, migration_at=0, observed_until=1209600,
                       baseline_week_minutes=1000, baseline_campaign_minutes=100)
        self.assertEqual(p["hostedMinutes"], 16)
        self.assertEqual(p["billedUsage"], "UNVERIFIED")

    def test_one_failed_metric_is_not_target_met(self):
        p=gate.measure(self.rows(), migration_at=0, observed_until=1209600,
                       baseline_week_minutes=1000, baseline_campaign_minutes=10)
        self.assertEqual(p["verdict"], "NOT_MET")

    def test_self_hosted_only_merged_campaigns_are_in_denominator(self):
        rows = self.rows()
        for row in rows:
            row.update(hosted=False, campaign="pr-2")
        rows.append(dict(self.rows()[0], jobId="100", campaign="pr-1", seconds=600))
        result = gate.measure(rows, migration_at=0, observed_until=1209600,
                              baseline_week_minutes=1000, baseline_campaign_minutes=100)
        self.assertEqual(result["meanCampaignMinutes"], 5)
        self.assertIs(result["programVerified"], False)

    def test_entirely_self_hosted_window_is_measurable_but_not_certified(self):
        rows = self.rows()
        for row in rows:
            row["hosted"] = False
        result = gate.measure(rows, migration_at=0, observed_until=1209600,
                              baseline_week_minutes=1000, baseline_campaign_minutes=100)
        self.assertEqual(result["hostedMinutes"], 0)
        self.assertEqual(result["meanCampaignMinutes"], 0)
        self.assertEqual(result["localMinutes"], 14)
        self.assertIs(result["programVerified"], False)

    def test_workflow_observer_is_nonrequired_and_sealed(self):
        from pathlib import Path
        import tempfile
        import verify_nyayone_ci as policy
        path=Path(__file__).resolve().parents[2]/".github/workflows/nyay42-optimization-observe.yml"
        self.assertTrue(path.exists(), "NYAY42_OBSERVER_WORKFLOW_ABSENT")
        self.assertIn(path.name, policy.CANONICAL_WORKFLOW_FILES)
        source=path.read_text()
        self.assertIn("python scripts/ci/test_nyay42_optimization.py", source)
        self.assertIn("contents: read", source)
        self.assertNotIn("self-hosted", source)
        self.assertNotIn("  required:", source)
        self.assertEqual(policy.check_workflow(path), [])
        with tempfile.TemporaryDirectory() as directory:
            mutated=Path(directory)/path.name
            mutated.write_text(source.replace("contents: read", "contents: write"))
            self.assertTrue(policy.check_workflow(mutated))

    def test_main_evidence_is_never_cancelled_by_pr(self):
        from pathlib import Path
        import re
        workflows=Path(__file__).resolve().parents[2]/".github/workflows"
        literal_groups=set()
        for path in workflows.glob("*.yml"):
            source=path.read_text()
            self.assertIn("cancel-in-progress: ${{ github.event_name == 'pull_request' }}", source)
            group=re.search(r"^  group: (.+)$", source, re.MULTILINE).group(1)
            self.assertIn("${{ github.event.pull_request.number || github.ref }}", group)
            # A unique literal workflow prefix is as isolated as github.workflow.
            if "${{ github.workflow }}" not in group:
                self.assertNotIn(group, literal_groups)
                literal_groups.add(group)
                self.assertTrue(group.startswith("nyayone-ci-flaky-nyay4-"))


if __name__ == "__main__":
    unittest.main()
