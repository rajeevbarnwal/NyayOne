"""Fail-closed source contract for the isolated NYAY-5 browser orchestrator."""

from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
ORCHESTRATOR = ROOT / "scripts/nyay5_profile_browser_gate.sh"


def test_orchestrator_provisions_exact_real_stack_and_always_cleans_scratch() -> None:
    source = ORCHESTRATOR.read_text(encoding="utf-8")
    required = (
        "set -Eeuo pipefail",
        "trap cleanup EXIT",
        '"$ROOT/backend/scripts/nyay5_browser_gate_control.py" create \\\n',
        '"$ROOT/backend/scripts/nyay5_browser_gate_control.py" seed-denials \\\n',
        '"$ROOT/backend/scripts/nyay5_browser_gate_control.py" drop \\\n',
        "NYAY19_ISOLATED_MIGRATION_EXECUTE=1",
        "-m alembic upgrade head",
        "otp_capture_server.py",
        "uvicorn app.main:app",
        "VITE_API_BASE_URL=",
        "npm run build",
        'NYAY18_PREVIEW_ROOT="$ROOT/frontend/dist"',
        'NYAY18_PREVIEW_PORT="$WEB_PORT"',
        "exec node scripts/nyay18-preview-server.mjs",
        "qa:nyay5:profile-boundary",
        "NYAY5_DENIAL_FIXTURE_PATH",
        "NYAY5_SCREENSHOT_DIR",
        "orchestrator-summary.json",
    )
    for item in required:
        assert item in source
    assert source.count('NYAY5_API_BASE_URL="http://localhost:$API_PORT" \\\n') == 1
    assert "vite preview" not in source
    assert "set -x" not in source
    assert "--no-access-log" in source


def test_orchestrator_expands_only_the_isolated_browser_issue_budget() -> None:
    source = ORCHESTRATOR.read_text(encoding="utf-8")
    api_service = source[source.index("  exec env ") : source.index(") >\"$API_LOG\"")]

    expected = (
        "    OTP_ISSUE_IDENTITY_LIMIT=100 \\\n",
        "    OTP_ISSUE_IP_LIMIT=1000 \\\n",
        "    OTP_ISSUE_GLOBAL_LIMIT=100000 \\\n",
    )
    for setting in expected:
        assert api_service.count(setting) == 1
        assert source.count(setting) == 1

    # This gate is not the OTP abuse-budget oracle. Keep every resend and
    # verification budget at the application defaults while the disposable
    # browser stack gets enough issuance capacity for its full fixture wave.
    assert "OTP_RESEND_IDENTITY_LIMIT=" not in source
    assert "OTP_RESEND_IP_LIMIT=" not in source
    assert "OTP_RESEND_GLOBAL_LIMIT=" not in source
    assert "OTP_VERIFY_IDENTITY_LIMIT=" not in source
    assert "OTP_VERIFY_IP_LIMIT=" not in source
    assert "OTP_VERIFY_GLOBAL_LIMIT=" not in source


def test_orchestrator_summary_is_aggregate_only_and_fail_closed() -> None:
    source = ORCHESTRATOR.read_text(encoding="utf-8")
    summary_source = source[source.index("write_summary()") : source.index("cleanup()")]
    for forbidden in ("database_name", "database_url", '"url"', '"token"'):
        assert forbidden not in summary_source
    for required in (
        '"nyay5-profile-browser-orchestrator-v1"',
        '"executed"',
        '"status"',
        '"services"',
        '"serviceLogsCaptured"',
        '"scratchCleanup"',
        '"browserExitCode"',
    ):
        assert required in summary_source
    assert "status = 'PASS'" not in source


def test_orchestrator_attests_exact_private_service_log_inventory_before_deletion() -> None:
    source = ORCHESTRATOR.read_text(encoding="utf-8")

    assert "SERVICE_LOGS_CAPTURED=false" in source
    assert 'for service_log in "$API_LOG" "$OTP_LOG" "$PREVIEW_LOG" "$BUILD_LOG"' in source
    assert '[[ -f "$service_log" && ! -L "$service_log" ]]' in source
    assert "SERVICE_LOGS_CAPTURED=true" in source
    assert 'NYAY5_SUMMARY_SERVICE_LOGS="$SERVICE_LOGS_CAPTURED"' in source
    assert 'boolean("NYAY5_SUMMARY_SERVICE_LOGS")' in source
    assert '"$SERVICE_LOGS_CAPTURED" == true' in source


def test_real_chromium_census_regression_is_mandatory_before_product_producer() -> None:
    source = ORCHESTRATOR.read_text(encoding="utf-8")
    command = (
        '(\n  cd "$ROOT/frontend"\n'
        '  node --test scripts/lib/nyay5-visual-census-race.browser-contract.mjs\n'
        ') >"$OUTPUT_DIR/census-contract-results.tap" 2>&1\n'
    )
    assert source.count(command) == 1
    assert source.index(command) < source.index("npm run qa:nyay5:profile-boundary")
    assert source.index(command) < source.index("set +e\n(\n  cd")
    test_source = (
        ROOT / "frontend/scripts/lib/nyay5-visual-census-race.browser-contract.mjs"
    ).read_text(encoding="utf-8")
    assert "ts.createSourceFile" in test_source
    assert "chromium.launch({ headless: true })" in test_source
    assert "recordVisualContract" in test_source
    assert "getClientRects().length" in test_source
    assert "it.skip" not in test_source
    assert "test.skip" not in test_source
