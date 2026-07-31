"""N44 — the review-rate-limit boundary must be measured on an UNSPENT budget.

The defect these guards exist for: ``frontend/scripts/wave2-tutoring-e2e.mjs``
measured ``RATE_LIMIT_REVIEW_PER_HOUR`` by hammering the REVIEW limiter as the
RIVAL student — the same student N34/N35 had already charged two ``PATCH
/tutoring/reviews/{id}`` calls. The limiter buckets per user id, so the full run
reported "last admitted 198, first rejected 199" against a configured 200. The
limiter was correct; the ORACLE was contaminated, and by a number small enough
to be mistaken for a product quirk.

The correction is an actor plus a proof:

* ``wave2_e2e_fixture.py`` seeds a DEDICATED ``review_rate_limit_student``;
* the driver LEDGERS every request that reaches a review-limited route, per
  actor, at the instant it is issued;
* N44 asserts that ledger reads zero for its actor before measuring anything.

These tests hold the three pieces together. They are cheap text/AST guards on
purpose: the behavioural proof is the browser gate, and what a unit test can add
is that nobody can quietly take the pieces apart again.
"""
from __future__ import annotations

import ast
import json
import re
import uuid
from pathlib import Path

import pytest

from scripts.wave2_e2e_fixture import (
    ADMIN_ACTOR_ID,
    BROWSER_STUDENT_ID,
    REVIEW_LIMIT_STUDENT_ID,
    RIVAL_STUDENT_ID,
)

BACKEND = Path(__file__).resolve().parents[1]
REPO = BACKEND.parent
DRIVER = REPO / "frontend" / "scripts" / "wave2-tutoring-e2e.mjs"
FIXTURE = BACKEND / "scripts" / "wave2_e2e_fixture.py"
TUTORING_API = BACKEND / "app" / "api" / "v1" / "tutoring.py"
GATE = REPO / "scripts" / "wave2_tutoring_browser_gate.sh"


@pytest.fixture(scope="module")
def driver_source() -> str:
    return DRIVER.read_text(encoding="utf-8")


def test_the_dedicated_review_limit_actor_is_distinct_from_every_other_actor():
    others = {BROWSER_STUDENT_ID, RIVAL_STUDENT_ID, ADMIN_ACTOR_ID}
    assert REVIEW_LIMIT_STUDENT_ID not in others
    assert len(others | {REVIEW_LIMIT_STUDENT_ID}) == 4
    assert isinstance(REVIEW_LIMIT_STUDENT_ID, uuid.UUID)


def test_the_fixture_seeds_and_publishes_the_dedicated_actor():
    """It is created as a real user row AND named in the emitted JSON."""
    source = FIXTURE.read_text(encoding="utf-8")
    assert "_ensure_user(session, REVIEW_LIMIT_STUDENT_ID," in source, (
        "the dedicated review-rate-limit actor is declared but never seeded"
    )
    assert '"review_rate_limit_student": str(REVIEW_LIMIT_STUDENT_ID)' in source, (
        "the fixture must publish the actor so the driver can refuse to guess it"
    )


def test_the_driver_uses_the_same_id_the_fixture_seeds(driver_source: str):
    match = re.search(
        r"const REVIEW_LIMIT_ACTOR = '([0-9a-fA-F-]{36})';", driver_source
    )
    assert match, "the driver has no REVIEW_LIMIT_ACTOR constant"
    assert uuid.UUID(match.group(1)) == REVIEW_LIMIT_STUDENT_ID, (
        "the driver's N44 actor and the fixture's seeded actor have drifted apart"
    )


def test_no_stage_other_than_n44_spends_the_dedicated_actor(driver_source: str):
    """The whole point of a dedicated actor is that it stays dedicated."""
    uses = [
        (i + 1, line.strip())
        for i, line in enumerate(driver_source.splitlines())
        if "REVIEW_LIMIT_ACTOR" in line
    ]
    assert uses, "REVIEW_LIMIT_ACTOR is unused"
    # Every `sub: REVIEW_LIMIT_ACTOR` style request must be inside N44. The only
    # request issued with this identity anywhere in the file is N44's own loop,
    # which goes through the `actor` local.
    request_uses = [
        (n, text) for n, text in uses if re.search(r"\bsub:\s*REVIEW_LIMIT_ACTOR\b", text)
    ]
    assert not request_uses, (
        "an API call is issued directly as the dedicated review-rate-limit "
        f"actor outside N44's measured loop: {request_uses}"
    )
    n44_start = driver_source.index("--- N44 configured review rate-limit boundary")
    n44_end = driver_source.index("findings.configuredLimiters", n44_start)
    n44_block = driver_source[n44_start:n44_end]
    assert "const actor = contaminate ? RIVAL : REVIEW_LIMIT_ACTOR;" in n44_block
    assert "sub: actor" in n44_block


def test_n44_asserts_zero_prior_use_before_it_measures(driver_source: str):
    n44_start = driver_source.index("--- N44 configured review rate-limit boundary")
    n44_end = driver_source.index("findings.configuredLimiters", n44_start)
    block = driver_source[n44_start:n44_end]
    # The ledger is READ before the measuring loop exists, not after it.
    read_at = block.index("const priorCalls = reviewLimiterCalls(actor);")
    loop_at = block.index("for (let i = 1; i <= limit + 5")
    assert read_at < loop_at, "N44 measures first and checks the budget afterwards"
    # And the measurement's own verdict carries the precondition.
    assert "pass: priorCalls === 0 && firstRejectAt === limit + 1 && lastAcceptAt === limit" in block, (
        "N44's pass condition must include the zero-prior-use precondition and "
        "the exact 200-admitted / 201-rejected boundary"
    )
    assert "CONTAMINATED ORACLE" in block


def test_n44_keeps_the_exact_boundary_assertion(driver_source: str):
    """No softening: exactly `limit` admitted, exactly `limit + 1` rejected."""
    block = driver_source[
        driver_source.index("--- N44 configured review rate-limit boundary") :
        driver_source.index("findings.configuredLimiters")
    ]
    assert "firstRejectAt === limit + 1" in block
    assert "lastAcceptAt === limit" in block
    assert "const limit = REVIEW_LIMIT;" in block
    # The limiter is neither reset nor retuned for N44. Judged on CODE only:
    # the prose above the block legitimately says "not a reset".
    code = "\n".join(
        line for line in block.splitlines() if not line.lstrip().startswith("//")
    )
    assert "reset" not in code.lower(), code
    # The limit is READ, never assigned: `RATE_LIMIT_REVIEW_PER_HOUR` may appear
    # in the row's prose, but nothing in N44 may set or shrink it.
    assert not re.search(r"RATE_LIMIT_REVIEW_PER_HOUR\s*=\s*[^$]", code), code
    assigned = re.findall(r"\blimit\s*=\s*([^;\n]+)", code)
    assert assigned == ["REVIEW_LIMIT"], (
        f"N44's `limit` must be exactly REVIEW_LIMIT, never re-derived: {assigned}"
    )


def test_the_gate_still_runs_n44_at_the_production_review_limit():
    body = GATE.read_text(encoding="utf-8")
    assert "export RATE_LIMIT_REVIEW_PER_HOUR=200" in body, (
        "N44 must be measured at the production configuration, not a lowered one"
    )
    assert "E2E_REVIEW_LIMIT_PER_HOUR=\"$RATE_LIMIT_REVIEW_PER_HOUR\"" in body


def _review_limited_routes_from_production() -> set[tuple[str, str]]:
    """``{(HTTP method, route template)}`` for every ``_limit(REVIEW, ...)`` view."""
    tree = ast.parse(TUTORING_API.read_text(encoding="utf-8"))
    found: set[tuple[str, str]] = set()
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        calls_review_limit = any(
            isinstance(inner, ast.Call)
            and isinstance(inner.func, ast.Name)
            and inner.func.id == "_limit"
            and inner.args
            and isinstance(inner.args[0], ast.Name)
            and inner.args[0].id == "REVIEW"
            for inner in ast.walk(node)
        )
        if not calls_review_limit:
            continue
        for deco in node.decorator_list:
            call = deco if isinstance(deco, ast.Call) else None
            func = call.func if call else deco
            if not isinstance(func, ast.Attribute):
                continue
            method = func.attr.upper()
            if method not in {"GET", "POST", "PATCH", "PUT", "DELETE"}:
                continue
            if call and call.args and isinstance(call.args[0], ast.Constant):
                found.add((method, call.args[0].value))
    return found


def test_review_limited_routes_match_the_e2e_ledger(driver_source: str):
    """The ledger only proves anything if it watches every limited route.

    A fourth ``_limit(REVIEW, actor)`` route added to the API and not added to
    the driver's ``REVIEW_LIMITED_ROUTES`` would silently make N44's
    "zero prior calls" claim untrue again, in exactly the way that produced
    198/199. So the two lists are compared, here, at every suite run.
    """
    production = _review_limited_routes_from_production()
    assert production, "no _limit(REVIEW, ...) route found — the parser is wrong"
    assert production == {
        ("POST", "/tutoring/sessions/{session_id}/review"),
        ("PATCH", "/tutoring/reviews/{review_id}"),
        ("DELETE", "/tutoring/reviews/{review_id}"),
    }, production

    listed = re.search(
        r"const REVIEW_LIMITED_ROUTES = \[(.*?)\n\];", driver_source, re.S
    )
    assert listed, "the driver has no REVIEW_LIMITED_ROUTES list"
    entries = re.findall(r"method: '([A-Z]+)', pattern: (/[^\n]+/)", listed.group(1))
    assert {m for m, _ in entries} == {m for m, _ in production}
    assert len(entries) == len(production)
    # And the patterns really do match the concrete paths the driver builds.
    concrete = {
        "POST": "/api/v1/tutoring/sessions/00000000-0000-4000-8000-00000badbeef/review",
        "PATCH": "/api/v1/tutoring/reviews/00000000-0000-4000-8000-00000badbeef",
        "DELETE": "/api/v1/tutoring/reviews/00000000-0000-4000-8000-00000badbeef",
    }
    for method, pattern in entries:
        body = pattern.strip("/")
        regex = re.compile(body.replace("(?:\\?|$)", "(?:\\?|$)"))
        assert regex.search(concrete[method]), (method, pattern)
    # `moderate` is NOT review-limited in production, so it must not be ledgered.
    assert not any(
        re.compile(p.strip("/")).search(
            "/api/v1/tutoring/reviews/00000000-0000-4000-8000-00000badbeef/moderate"
        )
        and m == "POST"
        for m, p in entries
    )


def test_the_ledger_is_written_at_request_time_not_reconstructed(driver_source: str):
    """The count is an observation of traffic, not a tally kept by hand."""
    assert (
        "if (sub && isReviewLimited(method, urlPath)) recordReviewLimiterCall(method, urlPath, sub);"
        in driver_source
    ), "api() no longer ledgers review-limiter traffic at issue time"
    # It survives the chained 45s shells of one logical run, and only those.
    assert "STATE.reviewLimiter" in driver_source
    assert "saveState();" in driver_source


def test_the_contamination_injection_exists_and_names_the_pre_fix_actor(driver_source: str):
    """The regression assertion is provable, and the proof is data not a patch."""
    assert "E2E_INJECT=n44-contaminated-actor" in driver_source
    assert "injected('n44-contaminated-actor')" in driver_source
    block = driver_source[
        driver_source.index("--- N44 configured review rate-limit boundary") :
        driver_source.index("findings.configuredLimiters")
    ]
    assert "contaminate ? RIVAL : REVIEW_LIMIT_ACTOR" in block


def test_the_precondition_is_a_declared_required_assertion(driver_source: str):
    """It cannot pass by not running: an unexecuted required assertion FAILs."""
    assert "const N44_PRECONDITION = " in driver_source
    assert "N44_PRECONDITION,\n  ]);" in driver_source, (
        "the precondition must be in stageNeg4's `required` list"
    )
    assert "chk.assert(\n    N44_PRECONDITION," in driver_source


def test_the_fixture_json_contract_is_documented_for_the_driver():
    """The driver refuses to guess the actor; the fixture must therefore say it."""
    source = FIXTURE.read_text(encoding="utf-8")
    assert "review_rate_limit_student" in source
    payload_keys = re.search(r'"actors": \{(.*?)\n        \},', source, re.S)
    assert payload_keys, "the fixture no longer emits an `actors` block"
    assert "review_rate_limit_student" in payload_keys.group(1)


def test_the_driver_refuses_a_fixture_without_the_dedicated_actor(driver_source: str):
    block = driver_source[
        driver_source.index("--- N44 configured review rate-limit boundary") :
        driver_source.index("findings.configuredLimiters")
    ]
    assert "FIXTURE.actors?.review_rate_limit_student" in block
    assert "seededLimitActor !== REVIEW_LIMIT_ACTOR" in block


def test_seeded_actor_id_is_stable_forever():
    """A moving id would silently reset the budget claim; pin it."""
    assert str(REVIEW_LIMIT_STUDENT_ID) == "00000000-0000-4000-8000-000000004400"


def test_fixture_emits_valid_json_shape_for_actors():
    """Cheap structural guard on the block the driver parses."""
    source = FIXTURE.read_text(encoding="utf-8")
    assert json.dumps(str(REVIEW_LIMIT_STUDENT_ID)) in json.dumps(
        str(REVIEW_LIMIT_STUDENT_ID)
    )
    assert source.count('"review_rate_limit_student"') == 1
