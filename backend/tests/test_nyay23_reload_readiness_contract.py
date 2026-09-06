"""NYAY-23 executable readiness specification; no producer implementation here.

Native TestClient/PG readiness adapts NYAY-26/37's arm -> response settlement
discipline. It is not a browser/font gate and cannot replace the strict native
40-per-class p95 oracle. Synthetic schedules prove ordering, not Linux timing.
Run standalone with unittest; no database, network or application import.
"""
from __future__ import annotations

import ast
import importlib.util
import itertools
import json
from functools import cache
from pathlib import Path
import random
import unittest

ROOT = Path(__file__).resolve().parents[2]
GATE_PATH = ROOT / "backend/scripts/nyay4_postgres_otp_gate.py"
SEAM_PATH = ROOT / "backend/scripts/nyay23_cookie_readiness.py"
SOURCE = GATE_PATH.read_text()
TREE = ast.parse(SOURCE)
ORIGIN = "https://testserver"
START = "/api/v1/auth/student/login/otp/start"
STATE = "/api/v1/auth/student/otp/state"


def function(name):
    return next(n for n in TREE.body if isinstance(n, ast.FunctionDef) and n.name == name)


def segment(name):
    return ast.get_source_segment(SOURCE, function(name))


def response(kind="state", **overrides):
    # Only synthetic data. Real adapters must derive authority from actual
    # committed PG rows/canonical HTTP state, never pass a hardcoded True.
    body = dict(status="pending", purpose="login", destination_masked="masked",
                attempts_left=5, expires_in_seconds=120, resend_in_seconds=30,
                locked_for_seconds=None, resend_allowed=False)
    values = dict(url=ORIGIN + (START if kind == "start" else STATE),
                  method="POST" if kind == "start" else "GET",
                  status_code=202 if kind == "start" else 200,
                  body=body, body_settled=True, redirected=False)
    values.update(overrides)
    return values


class NativeSettlementContracts(unittest.TestCase):
    @cache
    def seam(self):
        self.assertTrue(SEAM_PATH.is_file(), "NYAY23_NATIVE_SETTLEMENT_SEAM_MISSING")
        spec = importlib.util.spec_from_file_location("nyay23_readiness_contract_target", SEAM_PATH)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        self.assertTrue(hasattr(module, "CookieReadiness"), "NYAY23_OBSERVER_MISSING")
        self.assertTrue(hasattr(module, "CanonicalReadinessError"), "NYAY23_TYPED_ERROR_MISSING")
        return module

    def observer(self, flow_class="known"):
        m = self.seam()
        return m, m.CookieReadiness.arm(origin=ORIGIN, flow_class=flow_class,
                                       client_scope="one-timing-client")

    def deliver(self, observer, event):
        if event in {"start", "state"}:
            observer.observe_response(event, response(event))
        else:
            observer.observe_authority(event, proven=True,
                                       client_scope="one-timing-client")

    def ready(self, observer, exclude=()):
        for event in ("start", "commit", "delivery", "cookie", "state"):
            if event not in exclude:
                self.deliver(observer, event)

    def test_01_armed_observer_is_not_authority(self):
        m, o = self.observer()
        with self.assertRaises(m.CanonicalReadinessError):
            o.require_ready()
        self.ready(o)
        self.assertIs(o.require_ready()["ready"], True)

    def test_02_exact_url_no_query_foreign_origin_or_redirect(self):
        m = self.seam()
        for changes in ({"url": ORIGIN + STATE + "?secret=synthetic"},
                        {"url": "https://foreign.invalid" + STATE},
                        {"url": ORIGIN + STATE + "/extra"},
                        {"redirected": True}, {"method": "POST"}):
            with self.subTest(changes=tuple(changes)):
                _, o = self.observer()
                self.ready(o, exclude={"state"})
                with self.assertRaises(m.CanonicalReadinessError):
                    o.observe_response("state", response(**changes))
                    o.require_ready()

    def test_03_non_200_and_unavailable_state_never_prove_pending(self):
        m = self.seam()
        for changes in ({"status_code": 401}, {"status_code": 500},
                        {"body": {"status": "unavailable", "purpose": None}},
                        {"body": {"status": "pending", "purpose": "recovery"}}):
            _, o = self.observer()
            self.ready(o, exclude={"state"})
            with self.assertRaises(m.CanonicalReadinessError):
                o.observe_response("state", response(**changes))
                o.require_ready()

    def test_04_headers_without_body_settlement_cannot_release_sample(self):
        m, o = self.observer()
        self.ready(o, exclude={"state"})
        with self.assertRaises(m.CanonicalReadinessError):
            o.observe_response("state", response(body_settled=False))
            o.require_ready()

    def test_05_commit_delivery_cookie_each_independently_required(self):
        m = self.seam()
        for missing in ("commit", "delivery", "cookie"):
            _, o = self.observer()
            self.ready(o, exclude={missing})
            with self.assertRaises(m.CanonicalReadinessError):
                o.require_ready()
            self.deliver(o, missing)
            self.assertIs(o.require_ready()["ready"], True)

    def test_06_foreign_client_and_truthy_proofs_rejected(self):
        m = self.seam()
        for proof, scope in [(1, "one-timing-client"), ("true", "one-timing-client"),
                             (False, "one-timing-client"), (True, "foreign-client")]:
            _, o = self.observer()
            self.ready(o, exclude={"commit"})
            with self.assertRaises(m.CanonicalReadinessError):
                o.observe_authority("commit", proven=proof, client_scope=scope)
                o.require_ready()

    def test_07_deadline_is_denial_and_late_events_cannot_resurrect(self):
        m, o = self.observer()
        o.expire()
        with self.assertRaises(m.CanonicalReadinessError):
            self.ready(o)
            o.require_ready()

    def test_08_seeded_variance_all_event_orders_retry_free(self):
        m = self.seam()
        schedules = list(itertools.permutations(("start", "commit", "delivery", "cookie", "state")))
        random.Random(23).shuffle(schedules)
        for order in schedules:
            _, o = self.observer()
            # Legacy sample-on-headers is demonstrably too early; the gate
            # must not release for ANY strict subset, regardless of schedule.
            for event in order[:-1]:
                self.deliver(o, event)
                with self.assertRaises(m.CanonicalReadinessError):
                    o.require_ready()
            self.deliver(o, order[-1])
            settled = o.require_ready()
            self.assertIs(settled["ready"], True)
            self.assertEqual(settled["attempts"], 1)

    def test_09_privacy_safe_diagnostics_do_not_echo_response_payloads(self):
        m, o = self.observer()
        planted = "synthetic-secret-cookie-and-otp"
        with self.assertRaises(m.CanonicalReadinessError) as caught:
            o.observe_response("state", response(url=ORIGIN + STATE + "?token=" + planted,
                                                 body={"token": planted}))
            o.require_ready()
        self.assertRegex(str(caught.exception), r"^CANONICAL_[A-Z_]+$")
        diagnostic = caught.exception.diagnostic
        self.assertLessEqual(set(diagnostic), {"stage", "kind", "status", "errorClass"})
        self.assertNotIn(planted, json.dumps(diagnostic))
        self.assertNotIn(ORIGIN, json.dumps(diagnostic))

    def test_10_known_and_decoy_readiness_are_independent(self):
        m, known = self.observer("known")
        _, decoy = self.observer("decoy")
        self.ready(known)
        self.assertIs(known.require_ready()["ready"], True)
        with self.assertRaises(m.CanonicalReadinessError):
            decoy.require_ready()
        self.ready(decoy)
        self.assertIs(decoy.require_ready()["ready"], True)


class ProducerIntegrationContracts(unittest.TestCase):
    def test_11_one_timing_transport_for_both_classes(self):
        node = function("_run_cookie_projection_probe")
        calls = [n for n in ast.walk(node) if isinstance(n, ast.Call)
                 and isinstance(n.func, ast.Name) and n.func.id == "TestClient"]
        self.assertEqual(len(calls), 1, "NYAY23_CROSS_PORTAL_TIMING_CONFOUND")

    def test_12_observers_armed_before_initial_start(self):
        body = segment("_run_cookie_projection_probe")
        self.assertIn("CookieReadiness.arm(", body, "NYAY23_ARM_BEFORE_REQUEST_MISSING")
        self.assertLess(body.index("CookieReadiness.arm("), body.index("_cookie_start_sample("))

    def test_13_authority_settled_before_timing_and_reload(self):
        body = segment("_run_cookie_projection_probe")
        self.assertIn(".require_ready(", body, "NYAY23_SETTLEMENT_BEFORE_SAMPLING_MISSING")
        self.assertLess(body.index(".require_ready("), body.index("for first_class, second_class"))
        self.assertIn("observe_authority(", body, "NYAY23_COMMITTED_SERVER_PROOF_MISSING")
        self.assertIn("observe_response(", body, "NYAY23_CANONICAL_HTTP_PROOF_MISSING")

    def test_14_seeded_variance_proof_is_executed_by_native_producer(self):
        body = segment("_run_cookie_projection_probe")
        self.assertIn("run_seeded_cookie_readiness_variance(attempts=1)", body,
                      "NYAY23_NATIVE_RETRY_FREE_VARIANCE_PROOF_MISSING")


class InheritedPreservationContracts(unittest.TestCase):
    def timing(self):
        module = ast.Module(body=[function("_timing_ratio_observation")], type_ignores=[])
        namespace = {"COOKIE_TIMING_SAMPLE_ORDER": tuple(range(40))}
        exec(compile(module, str(GATE_PATH), "exec"), namespace)
        return namespace["_timing_ratio_observation"]

    def test_15_strict_two_x_p95_boundary_still_fails_above_bound(self):
        timing = self.timing()
        self.assertIs(timing([100]*40, [200]*40)["timing_ratio_within_bound"], True)
        self.assertIs(timing([100]*40, [201]*40)["timing_ratio_within_bound"], False)

    def test_16_sample_inventory_strict_types_and_tail_sensitivity_preserved(self):
        timing = self.timing()
        for values in ([100]*39, [100]*41, [True]*40, [0]*40):
            with self.assertRaises(ValueError):
                timing(values, [100]*40)
        self.assertIs(timing([100]*40, [100]*37+[500]*3)["timing_ratio_within_bound"], False)

    def test_17_quarantine_still_executes_and_diagnostics_always_upload(self):
        workflow = (ROOT / ".github/workflows/ci-flaky-nyay4-cookie-reload-symmetry.yml").read_text()
        for required in ("workflow_dispatch:", "schedule:", "ubuntu-24.04", "pgvector/pgvector@sha256:",
                         "--require-quarantined-assertion", "if: ${{ always() }}", "if-no-files-found: error"):
            self.assertIn(required, workflow)
        assignments = {}
        for node in TREE.body:
            if isinstance(node, ast.Assign) and isinstance(node.targets[0], ast.Name):
                try:
                    assignments[node.targets[0].id] = ast.literal_eval(node.value)
                except (ValueError, TypeError):
                    pass
        self.assertEqual(len(assignments["ALL_ASSERTION_IDS"]), 17)
        self.assertEqual(len(assignments["REQUIRED_MUTANT_IDS"]), 27)
        self.assertEqual(assignments["QUARANTINED_ASSERTION_IDS"],
                         ("CONTRACT-COOKIE-ORIGIN-RELOAD-SYMMETRY",))

    def test_18_no_sleep_or_retry_is_current_native_readiness(self):
        body = segment("_run_cookie_projection_probe")
        for forbidden in ("sleep(", "waitForTimeout(", "networkidle", "tenacity", "retry("):
            self.assertNotIn(forbidden, body)
        self.assertIn("_timing_ratio_observation(known_durations, decoy_durations)", body)

    def test_19_nyay26_37_canonical_observer_reference_is_available(self):
        browser = (ROOT / "frontend/scripts/lib/browser-response-readiness.mjs").read_text()
        for symbol in ("armCanonicalReadiness", "settleCanonicalReadiness", "response.finished()",
                       "url.search === ''", "CANONICAL_RESPONSE_STATUS_INVALID"):
            self.assertIn(symbol, browser)
        capture = (ROOT / "backend/tests/test_nyay37_capture_readiness.py").read_text()
        self.assertIn("await_delivery", capture)


if __name__ == "__main__":
    unittest.main(verbosity=2)
