"""The Wave 2 target-runtime GATES themselves are under test (SAATHI-123/451).

Neither gate can run here — one needs PostgreSQL 16 + pgvector, the other needs
a live LiveKit + coturn stack and two browsers. What CAN be checked, cheaply and
on every push, is that the gates keep the promises the rest of the process
depends on:

1. the honesty contract — both gates print the runtime they detected, own a
   distinct ``BLOCKED: prerequisite runtime absent`` status and exit **78**, so
   a blocked run can never be mistaken for a pass;
2. the anti-drift contract — ``infra/video/RUNBOOK.md`` § 9 and
   ``infra/video/scripts/livekit_turn_smoke.sh`` describe THE SAME steps, with
   the same ids and the same titles. A runbook that has quietly stopped
   describing the script is worse than no runbook, because it is still believed;
3. the coverage contract — the PostgreSQL gate still claims all eight assertion
   groups, CI still stands the gate up on ``pgvector/pgvector:pg16``, and the
   whole-repo ``db_gate.sh`` still calls the Wave 2 stage rather than a fork of
   it.

These are TEXT assertions on purpose. Executing either gate from the suite would
either need the absent runtime or would tempt someone to stub it, and a stubbed
target-runtime gate proves nothing at all.
"""
from __future__ import annotations

import re
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
REPO = BACKEND.parent
SMOKE = REPO / "infra" / "video" / "scripts" / "livekit_turn_smoke.sh"
DRIVER = REPO / "infra" / "video" / "scripts" / "livekit_two_browser_smoke.mjs"
APPLICATION_DRIVER = REPO / "frontend" / "scripts" / "wave2-tutoring-e2e.mjs"
APPLICATION_FIXTURE = BACKEND / "scripts" / "wave2_e2e_fixture.py"
RUNBOOK = REPO / "infra" / "video" / "RUNBOOK.md"
PG_GATE_SH = BACKEND / "scripts" / "wave2_db_gate.sh"
PG_GATE_PY = BACKEND / "scripts" / "wave2_postgres_gate.py"
DB_GATE_SH = BACKEND / "scripts" / "db_gate.sh"
CI_WORKFLOW = REPO / ".github" / "workflows" / "wave2-tutoring-db-gate.yml"

BLOCKED_SENTINEL = "BLOCKED: prerequisite runtime absent"
#: The literal line the Python probe must carry, matched verbatim so a rename to
#: something softer ("SKIPPED", "WARN") fails the build.
BLOCKED_PREFIX_CONST = 'BLOCKED_PREFIX = "BLOCKED: prerequisite runtime absent"'


def _read(path: Path) -> str:
    assert path.exists(), f"{path} is missing"
    return path.read_text(encoding="utf-8")


def _script_step_contract() -> list[tuple[str, str]]:
    """The ``STEP_CONTRACT`` array in the smoke script: [(id, title), ...]."""
    text = _read(SMOKE)
    block = re.search(r"STEP_CONTRACT=\((.*?)\n\)", text, re.S)
    assert block, "the smoke script no longer declares a STEP_CONTRACT array"
    return [
        (match.group(1), match.group(2).strip())
        for match in re.finditer(r'"(S\d+)\|([^"]+)"', block.group(1))
    ]


def _runbook_step_headings() -> list[tuple[str, str]]:
    """The ``### S<n> <title> — UNEXECUTED`` headings in RUNBOOK § 9."""
    text = _read(RUNBOOK)
    section = text.split("## 9. Environment-blocked checks", 1)
    assert len(section) == 2, "RUNBOOK § 9 heading changed; the gate contract lives there"
    return [
        (match.group(1), match.group(2).strip())
        for match in re.finditer(
            r"^### (S\d+) (.+?) — UNEXECUTED\s*$", section[1], re.M
        )
    ]


# --------------------------------------------------------------------------- #
# 1. Honesty contract
# --------------------------------------------------------------------------- #
def test_both_gate_scripts_exist_and_are_the_named_one_command_entry_points():
    for path in (SMOKE, DRIVER, PG_GATE_SH, PG_GATE_PY):
        assert path.exists(), f"{path.relative_to(REPO)} is missing"
        assert path.stat().st_size > 0


def test_postgres_gate_refuses_rather_than_reporting_a_pass_it_did_not_earn():
    shell = _read(PG_GATE_SH)
    python = _read(PG_GATE_PY)
    # 78 == EX_CONFIG: distinct from 0 (pass) and 1 (assertion failure).
    assert "BLOCKED_EXIT=78" in shell
    assert "BLOCKED_EXIT = 78" in python
    assert BLOCKED_SENTINEL in shell
    assert BLOCKED_PREFIX_CONST in python
    # It must SAY what it found before it says anything else.
    assert "runtime.db_url" in shell
    assert "runtime.server_version" in python
    # And it must never let a SQLite URL through as if it proved anything.
    assert "does not name a PostgreSQL database" in shell


def test_livekit_smoke_refuses_rather_than_reporting_a_pass_it_did_not_earn():
    text = _read(SMOKE)
    assert "BLOCKED_EXIT=78" in text
    assert BLOCKED_SENTINEL in text
    # Every missing prerequisite at once, not just the first: an operator should
    # need ONE run to learn everything they have to install.
    assert 'for item in "${MISSING[@]}"' in text
    # Fail closed: a failed step stops the run.
    assert "fail_closed()" in text
    assert "exit 1" in text
    # The driver has its own 78, because the shell gate maps it straight through.
    driver = _read(DRIVER)
    assert "const BLOCKED_EXIT = 78" in driver
    assert BLOCKED_SENTINEL in driver


def test_livekit_smoke_supports_an_isolated_in_network_real_browser_rig():
    """Colima may not expose UDP; a network-local browser must remain real proof."""
    shell = _read(SMOKE)
    driver = _read(DRIVER)

    assert 'COMPOSE_BASE+=(-f "$SMOKE_COMPOSE_OVERRIDE")' in shell
    assert 'curl -fsS "$LIVEKIT_URL/"' in shell
    assert "process.env.SMOKE_BROWSER_LIVEKIT_URL" in driver
    assert "process.env.SMOKE_BROWSER_ORIGIN" in driver
    assert "chromium.connectOverCDP(CHROMIUM_CDP_URL)" in driver
    assert "chromium.connectOverCDP(DENIED_CHROMIUM_CDP_URL)" in driver
    assert "composeArgs.push('-f', process.env.SMOKE_COMPOSE_OVERRIDE)" in driver
    assert "participant.joined.published < 2" in driver
    assert "hasGetUserMedia" in driver
    # Bare-metal Chromium is still the default; the isolated rig is an
    # operator-selected transport, never a quiet weakening of the gate.
    assert "await chromium.launch" in driver


def test_application_live_room_oracle_executes_every_declared_assertion():
    """A label mismatch must not turn a completed assertion into NOT EXECUTED."""
    text = _read(APPLICATION_DRIVER)
    assertion = "the room reports admission only after the selected media transport connects"
    assert text.count(assertion) >= 2, (
        "the live-room admission assertion must use the same stable name in "
        "newChecks() and chk.ok()"
    )


def test_geometry_contexts_explicitly_select_the_deterministic_transport():
    """Geometry belongs to the app seam; LiveKit/TURN has its own real gate."""
    text = _read(APPLICATION_DRIVER)
    stage = text.split("async function stageGeo(browser)", 1)[1].split(
        "async function stageD1", 1
    )[0]
    loop = stage.split("for (const cfg of CONFIGS)", 1)[1]
    init = loop.index("await ctx.addInitScript")
    measure = loop.index("await measure(ctx")
    assert init < measure
    assert "window.__legalsaathiVideoTransport = 'deterministic'" in loop[:measure]


def test_browser_fixture_applies_sqlite_pragma_only_to_sqlite():
    """The same declared fixture must seed both SQLite and PostgreSQL."""
    text = _read(APPLICATION_FIXTURE)
    assert 'bind.dialect.name == "sqlite"' in text
    assert text.count("if is_sqlite") >= 2
    assert 'session.execute(sa_text("PRAGMA busy_timeout = 20000"))' in text


def test_neither_gate_can_report_a_pass_without_the_runtime():
    """No code path prints PASS before the runtime check has been made."""
    shell = _read(PG_GATE_SH)
    detection = shell.index("emit_blocked \"DATABASE_URL is not set\"")
    verdict = shell.index("wave2_db_gate: PASS")
    assert detection < verdict, "the PASS verdict is reachable before runtime detection"

    smoke = _read(SMOKE)
    blocked_at = smoke.index("BLOCKED: prerequisite runtime absent")
    first_step = smoke.index('step_head S1 "container/service health"')
    assert blocked_at < first_step, "S1 runs before the prerequisite refusal"


# --------------------------------------------------------------------------- #
# 2. Anti-drift contract: the runbook IS the script
# --------------------------------------------------------------------------- #
def test_runbook_section_9_matches_the_smoke_script_step_contract():
    script = _script_step_contract()
    runbook = _runbook_step_headings()
    assert script, "the smoke script declares no steps"
    assert script == runbook, (
        "RUNBOOK § 9 and infra/video/scripts/livekit_turn_smoke.sh have drifted.\n"
        f"  script  : {script}\n"
        f"  runbook : {runbook}"
    )


def test_the_smoke_covers_every_step_the_correction_cycle_asked_for():
    titles = {title for _, title in _script_step_contract()}
    for required in (
        "container/service health",
        "server-created room",
        "short-lived participant-bound join grant",
        "two-browser join smoke",
        "camera and microphone denial",
        "reconnect",
        "token expiry and revocation",
        "webhook verification and replay rejection",
        # Named so RUNBOOK § 9's heading still contains the exact phrase
        # test_wave2_video_infra.py pins ("FORCED-TURN smoke test").
        "FORCED-TURN smoke test (the media path)",
        "provider unreachable, fail-closed",
        "no raw token, SDP or ICE persisted",
    ):
        assert required in titles, f"the smoke lost its '{required}' step"


def test_runbook_names_the_scripts_that_actually_ship():
    text = _read(RUNBOOK)
    for command in (
        "bash infra/video/scripts/livekit_turn_smoke.sh",
        "bash backend/scripts/wave2_db_gate.sh",
        "scripts/wave2_postgres_gate.py --privacy-only",
    ):
        assert command in text, f"RUNBOOK § 9 does not name `{command}`"
    # And it still says, in as many words, that none of it has been executed.
    section = text.split("## 9. Environment-blocked checks", 1)[1]
    assert "UNEXECUTED" in section
    assert "ENVIRONMENT-BLOCKED" in section


def test_the_privacy_scan_has_exactly_one_implementation():
    """S11 and assertion A7 must not be two scans that can disagree."""
    python = _read(PG_GATE_PY)
    assert python.count("def scan_raw_storage(") == 1
    assert "--privacy-only" in python
    assert "scripts/wave2_postgres_gate.py --privacy-only" in _read(SMOKE)


# --------------------------------------------------------------------------- #
# 3. Coverage contract
# --------------------------------------------------------------------------- #
def test_postgres_gate_still_claims_all_eight_assertion_groups():
    python = _read(PG_GATE_PY)
    for ident in ("A1.1", "A1.2", "A2.1", "A3.1", "A3.2", "A4.4", "A4.5", "A5.3", "A5.4", "A6.1", "A6.2", "A6.3", "A6.4", "A7.1", "A7.2", "A8.1"):
        assert f'"{ident}"' in python, f"assertion {ident} disappeared from the gate"
    # The two PostgreSQL-only partial unique indexes are named explicitly.
    assert "uq_booking_holds_one_active_per_slot" in python
    assert "uq_payment_refunds_one_succeeded_per_order" in python
    # The concurrency probes must use PROCESSES, not threads on one connection.
    assert 'mp.get_context("spawn")' in python
    assert "pg_backend_pid()" in python
    # And the gate must publish what SQLite cannot prove, rather than implying it.
    assert "SQLITE_CANNOT_PROVE" in python


def test_the_whole_repo_gate_calls_the_wave2_stage_rather_than_forking_it():
    text = _read(DB_GATE_SH)
    assert "bash scripts/wave2_db_gate.sh" in text, (
        "db_gate.sh no longer runs the Wave 2 stage; a parallel mechanism is "
        "exactly what this cycle was told not to build"
    )


def test_ci_runs_the_wave2_postgres_gate_on_push_and_pull_request():
    text = _read(CI_WORKFLOW)
    assert "pgvector/pgvector:pg16" in text, "CI must use the repo's pinned PG16 image"
    assert re.search(r"^on:\s*$", text, re.M)
    assert re.search(r"^  push:\s*$", text, re.M), "the gate must run on push"
    assert re.search(r"^  pull_request:\s*$", text, re.M), "the gate must run on PR"
    assert "bash scripts/wave2_db_gate.sh" in text
    # CI must refuse a BLOCKED result: on a runner that HAS PostgreSQL, blocked
    # means broken.
    assert "did not execute to a PASS" in text
    for path in (
        "backend/app/models/wave2.py",
        "backend/app/services/tutoring/**",
        "backend/app/db/migrations/versions/**",
        "infra/video/**",
    ):
        assert path in text, f"CI does not trigger on {path}"


def test_ci_asserts_the_media_smoke_refuses_in_an_environment_without_a_media_plane():
    text = _read(CI_WORKFLOW)
    assert "livekit_turn_smoke.sh" in text
    assert '"78"' in text, "CI must pin the BLOCKED exit code it expects"
    assert BLOCKED_SENTINEL in text
