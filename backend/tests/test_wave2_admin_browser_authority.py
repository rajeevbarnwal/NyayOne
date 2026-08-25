"""Wave 2 M-01 must use only a server-authoritative administrator session.

Sprint 1 deliberately has no tutor/lawyer browser ceremony.  The inherited
browser gate therefore proves the authorised completion path with an isolated
administrator ``auth_sessions`` row and the corresponding HttpOnly cookie.  A
browser-readable snapshot or ``X-Actor-Claims`` would recreate the authority
gap this gate exists to catch.
"""
from __future__ import annotations

from pathlib import Path


BACKEND = Path(__file__).resolve().parents[1]
REPO = BACKEND.parent
DRIVER = REPO / "frontend" / "scripts" / "wave2-tutoring-e2e.mjs"
FIXTURE = BACKEND / "scripts" / "wave2_e2e_fixture.py"
ORCHESTRATOR = REPO / "scripts" / "wave2_tutoring_browser_gate.sh"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_fixture_seeds_a_hashed_active_admin_session_without_emitting_the_bearer():
    source = _read(FIXTURE)

    assert 'os.getenv("WAVE2_E2E_ADMIN_SESSION_TOKEN", "")' in source
    assert '_ensure_user(session, ADMIN_ACTOR_ID, "admin")' in source
    assert "keyed_hash(admin_session_token)" in source
    assert "AuthSession(" in source
    assert '"admin_session": "seeded_hashed_only"' in source
    assert '"admin_session_token":' not in source
    assert "raw_session_token" not in source


def test_orchestrator_keeps_the_bearer_out_of_evidence_and_passes_it_by_environment():
    source = _read(ORCHESTRATOR)

    assert 'ADMIN_SESSION_TOKEN_FILE="$DB_DIR/admin-session-token"' in source
    assert 'chmod 600 "$ADMIN_SESSION_TOKEN_FILE"' in source
    assert 'WAVE2_E2E_ADMIN_SESSION_TOKEN="$ADMIN_SESSION_TOKEN"' in source
    assert source.count('WAVE2_E2E_ADMIN_SESSION_TOKEN="$ADMIN_SESSION_TOKEN"') >= 1
    assert 'E2E_ADMIN_SESSION_TOKEN="$ADMIN_SESSION_TOKEN"' in source
    # The private bearer belongs beside the isolated DB, never under --out.
    assert 'ADMIN_SESSION_TOKEN_FILE="$WORK/' not in source
    assert "raw administrator session token" not in source.lower()


def test_m01_browser_leg_uses_an_httponly_cookie_and_no_client_authority():
    source = _read(DRIVER)
    start = source.index("/* --------------------------------------------------- administrator (M-01) surface */")
    end = source.index("/** Every completion control", start)
    block = source[start:end]

    assert "async function adminContext(browser)" in block
    assert "await ctx.addCookies([{" in block
    assert "name: 'nyayone_session'" in block
    assert "value: ADMIN_SESSION_TOKEN" in block
    assert "path: '/'" in block
    assert "httpOnly: true" in block
    assert "sameSite: 'Lax'" in block
    assert "async function recordCompletionAsAdmin(" in block
    assert "role: 'admin'" in block
    assert "localStorage" not in block
    assert "sessionStorage" not in block
    assert "addInitScript" not in block
    assert "X-Actor-Claims" not in block


def test_d3_requires_the_admin_browser_leg_and_no_tutor_browser_fallback():
    source = _read(DRIVER)
    start = source.index("async function stageD3(")
    end = source.index("async function stageD4(", start)
    block = source[start:end]

    assert "recordCompletionAsAdmin(browser, sessionId" in block
    assert "completion is recorded by the ADMINISTRATOR on the authorised M-01 surface" in block
    assert "recordCompletionAsMentor" not in block
    assert "roles: ['tutor']" not in block
    assert "mentorLeg" not in block
    assert "owningTutorId" not in block
    assert "performedInBrowser === true" in block
    assert "att[0]?.recorded_by_role === 'admin'" in block


def test_fixture_seeds_a_genuine_student_registration_and_hashed_session():
    source = _read(FIXTURE)

    assert 'os.getenv("WAVE2_E2E_STUDENT_SESSION_TOKEN", "")' in source
    assert "def _ensure_student_registration_and_session(" in source
    assert "StudentRegistration(" in source
    assert "StudentProfile(registration_id=registration.id)" in source
    assert "Consent(" in source
    assert 'purpose="registration"' in source
    assert "mobile_ct = encrypt(" in source
    assert "dob_ct = encrypt(" in source
    assert "keyed_hash(student_session_token)" in source
    assert '"browser_student_session": "seeded_hashed_only"' in source
    assert '"student_session_token":' not in source


def test_orchestrator_keeps_the_student_bearer_private_and_environment_only():
    source = _read(ORCHESTRATOR)

    assert 'STUDENT_SESSION_TOKEN_FILE="$DB_DIR/student-session-token"' in source
    assert 'chmod 600 "$STUDENT_SESSION_TOKEN_FILE"' in source
    assert 'WAVE2_E2E_STUDENT_SESSION_TOKEN="$STUDENT_SESSION_TOKEN"' in source
    assert 'E2E_STUDENT_SESSION_TOKEN="$STUDENT_SESSION_TOKEN"' in source
    assert '[[ "$STUDENT_SESSION_TOKEN" != "$ADMIN_SESSION_TOKEN" ]]' in source
    assert 'STUDENT_SESSION_TOKEN_FILE="$WORK/' not in source


def test_every_student_browser_context_uses_the_canonical_httponly_cookie():
    source = _read(DRIVER)
    start = source.index("async function studentContext(browser")
    end = source.index("/* --------------------------------------------------- administrator (M-01) surface */")
    block = source[start:end]

    assert "const STUDENT_SESSION_TOKEN = must('E2E_STUDENT_SESSION_TOKEN')" in source
    assert "await ctx.addCookies([{" in block
    assert "name: 'nyayone_session'" in block
    assert "value: STUDENT_SESSION_TOKEN" in block
    assert "path: '/'" in block
    assert "httpOnly: true" in block
    assert "sameSite: 'Lax'" in block
    assert "X-Actor-Claims" not in block
    assert "/api/v1/auth/student/session" in block
    assert "body?.actor?.sub !== STUDENT" in block
    assert "body?.actor?.consent_state?.join(',') !== 'registration'" in block
    assert source.count("await studentContext(browser") >= 6
    # The only raw context constructors are the two cookie-installing helpers:
    # one student boundary and the separate administrator boundary.
    assert source.count("browser.newContext(") == 2


def test_privacy_allowlist_names_only_the_admin_authenticated_surface():
    source = _read(DRIVER)

    assert "STORAGE_ALLOWLIST.mentor" not in source
    assert "authenticatedMentorSurfaceOnly" not in source
    assert "authenticated mentor surface" not in source
    assert "authenticatedAdminSurfaceOnly: STORAGE_ALLOWLIST.admin.map" in source
    assert source.count("STORAGE_ALLOWLIST.admin.map") == 2
    assert "authenticated administrator surface" in source
