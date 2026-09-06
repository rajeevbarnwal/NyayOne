"""Runtime proofs for NYAY-11; no JSON assertion substitutes for a mutation."""
from datetime import date, datetime, timedelta, timezone
from itertools import product

import pytest


def runtime():
    from app.services import student_authority
    return student_authority


@pytest.mark.parametrize(("born", "today", "minor"), [
    (date(2008, 9, 5), date(2026, 9, 4), True),
    (date(2008, 9, 5), date(2026, 9, 5), False),
    (date(2008, 2, 29), date(2026, 2, 28), True),
    (date(2008, 2, 29), date(2026, 3, 1), False),
])
def test_age_is_server_calendar_boundary(born, today, minor):
    assert runtime().is_minor(born, today) is minor


def test_guardian_ttl_is_calendar_months_including_leap_year():
    now = datetime(2024, 2, 29, 9, tzinfo=timezone.utc)
    assert runtime().guardian_deadline(now) == datetime(2025, 2, 28, 9, tzinfo=timezone.utc)


def test_state_machine_denies_every_unknown_symbol():
    service = runtime()
    for machine, source, target, trigger, authority in [
        ("foreign", "PENDING", "VERIFIED", "assigned_review_approved", "assigned_institutional_reviewer"),
        ("guardian", "UNKNOWN", "VERIFIED", "guardian_proof_completed", "server_attested_guardian"),
        ("guardian", "REQUIRED_PENDING", "VERIFIED", "guardian_proof_completed", "student"),
        ("institutional", "PENDING", "VERIFIED", "assigned_review_approved", "student"),
    ]:
        with pytest.raises(service.AuthorityError) as exc:
            service.evaluate_transition(machine, source, target, trigger, authority)
        assert exc.value.code == "authority_denied"
        assert str(exc.value) == "authority_denied"


def test_all_61_runtime_pairs_match_independent_policy_inventory():
    from tests.test_nyay11_authority_state_machine_red import (
        GUARDIAN_ALLOWED_EDGES, GUARDIAN_STATES,
        INSTITUTIONAL_ALLOWED_EDGES, INSTITUTIONAL_STATES,
    )
    service = runtime()
    exercised = 0
    for machine, states, edges in [
        ("guardian", GUARDIAN_STATES, GUARDIAN_ALLOWED_EDGES),
        ("institutional", INSTITUTIONAL_STATES, INSTITUTIONAL_ALLOWED_EDGES),
    ]:
        for source, target in product(states, repeat=2):
            exercised += 1
            if source == target:
                assert service.evaluate_transition(machine, source, target, "exact_idempotent_replay", "server") == "STATE_STABLE"
            elif (source, target) in edges:
                triggers, authorities = edges[source, target]
                assert service.evaluate_transition(machine, source, target, triggers[0], authorities[0]) == "ALLOWED"
            else:
                with pytest.raises(service.AuthorityError):
                    service.evaluate_transition(machine, source, target, "forged", "server")
    assert exercised == 61


def test_legacy_unknown_never_silently_maps():
    service = runtime()
    with pytest.raises(service.AuthorityError) as exc:
        service.map_legacy("guardian", "VERIFIED")
    assert exc.value.code == "legacy_authority_unmapped"


def test_authority_foreign_keys_are_indexed_on_the_left_prefix():
    import sqlalchemy as sa
    from app.models import student_authority as models
    for model in (models.AuthorityState, models.GuardianInvitation, models.InstitutionalEmailProof,
                  models.InstitutionalReviewerAssignment, models.AuthorityMutationRecord, models.AuthorityNotification):
        table = model.__table__
        shapes = [tuple(index.columns.keys()) for index in table.indexes]
        shapes += [tuple(c.columns.keys()) for c in table.constraints if isinstance(c, (sa.UniqueConstraint, sa.PrimaryKeyConstraint))]
        for foreign_key in table.foreign_keys:
            assert any(shape and shape[0] == foreign_key.parent.name for shape in shapes), f"{table.name}.{foreign_key.parent.name}"


def test_machine_trigger_authority_pair_cannot_be_crossed():
    service = runtime()
    with pytest.raises(service.AuthorityError):
        service.evaluate_transition("guardian", "VERIFIED", "REQUIRED_PENDING", "proof_expired", "server_profile_policy")


@pytest.fixture()
def ctx(db_session, monkeypatch):
    from app.core.config import settings
    from app.core.crypto import encrypt, keyed_hash
    from app.models.registration import AuthSession, User
    from tests.test_nyay9_owner_scoped_profile_api import _student
    now = datetime.now(timezone.utc)
    owner, reg, profile = _student(db_session, suffix="31", first_name="Synthetic")
    guardian, guardian_reg, guardian_profile = _student(db_session, suffix="32", first_name="Synthetic")
    reviewer, reviewer_reg, reviewer_profile = _student(db_session, suffix="33", first_name="Synthetic")
    minor_dob = date(now.year - 15, 1, 1).isoformat()
    reg.dob_hash, reg.dob_ct, reg.is_minor = keyed_hash(minor_dob), encrypt(minor_dob), True
    for registration, prof, email in [(reg, profile, "owner@example.edu"), (reviewer_reg, reviewer_profile, "reviewer@example.edu")]:
        registration.institution_ref = "example"
        prof.institutional_email_hash, prof.institutional_email_ct = keyed_hash(email), encrypt(email)
    admin = User(role="admin", status="active")
    db_session.add(admin)
    db_session.flush()
    tokens = {}
    for index, user in enumerate((owner, guardian, reviewer, admin)):
        token = f"nyay11-synthetic-cookie-{index}-" + "x" * 32
        tokens[user.id] = token
        db_session.add(AuthSession(user_id=user.id, token_hash=keyed_hash(token), status="active", expires_at=now+timedelta(days=3), last_seen_at=now))
    db_session.commit()
    monkeypatch.setattr(settings, "authority_institution_domains", {"example": ["example.edu"]})
    return {"db": db_session, "owner": owner, "reg": reg, "profile": profile, "guardian": guardian, "reviewer": reviewer, "admin": admin, "tokens": tokens, "now": now}


def request(ctx, key="guardian-request-0001"):
    s = runtime()
    result = s.guardian_request(ctx["db"], ctx["owner"].id, ctx["tokens"][ctx["owner"].id], key=key, now=ctx["now"])
    ctx["db"].commit()
    return result


def consent(ctx, invitation, actor=None, key="guardian-consent-0001"):
    actor = actor or ctx["guardian"]
    result = runtime().guardian_consent(ctx["db"], actor.id, ctx["tokens"][actor.id], invitation=invitation, relationship="parent", accepted=True, key=key, now=ctx["now"])
    ctx["db"].commit()
    return result


def test_real_guardian_session_consumes_invitation_and_grants(ctx):
    invitation = request(ctx)["invitation"]
    assert consent(ctx, invitation)["guardian_state"] == "VERIFIED"
    assert runtime().guardian_is_current(ctx["db"], ctx["reg"].id, now=ctx["now"])
    assert not runtime().guardian_is_current(ctx["db"], ctx["reg"].id, now=runtime().guardian_deadline(ctx["now"]))


def test_owner_session_cannot_author_guardian_approval(ctx):
    invitation = request(ctx)["invitation"]
    with pytest.raises(runtime().AuthorityError):
        consent(ctx, invitation, actor=ctx["owner"])
    ctx["db"].rollback()
    assert not runtime().guardian_is_current(ctx["db"], ctx["reg"].id, now=ctx["now"])


def test_revocation_invalidates_pending_invitation(ctx):
    invitation = request(ctx)["invitation"]
    runtime().guardian_revoke(ctx["db"], ctx["owner"].id, ctx["tokens"][ctx["owner"].id], key="guardian-revoke-0001", now=ctx["now"])
    ctx["db"].commit()
    with pytest.raises(runtime().AuthorityError):
        consent(ctx, invitation)


def test_replay_is_exact_without_duplicate_audit_or_regrant(ctx):
    from sqlalchemy import func, select
    from app.models.student_authority import AuthorityAuditEvent
    invitation = request(ctx)["invitation"]
    original = consent(ctx, invitation)
    count = ctx["db"].scalar(select(func.count()).select_from(AuthorityAuditEvent))
    assert consent(ctx, invitation) == original
    assert ctx["db"].scalar(select(func.count()).select_from(AuthorityAuditEvent)) == count
    runtime().guardian_revoke(ctx["db"], ctx["owner"].id, ctx["tokens"][ctx["owner"].id], key="guardian-revoke-0002", now=ctx["now"])
    ctx["db"].commit()
    assert consent(ctx, invitation) == original
    assert not runtime().guardian_is_current(ctx["db"], ctx["reg"].id, now=ctx["now"])


def test_no_presented_cookie_means_no_authority(ctx):
    with pytest.raises(runtime().AuthorityError) as exc:
        runtime().guardian_request(ctx["db"], ctx["owner"].id, None, key="guardian-request-0002", now=ctx["now"])
    assert exc.value.status_code == 401


def test_profile_projection_observes_expiry_without_client_authority(ctx):
    from app.services import profile_service
    consent(ctx, request(ctx)["invitation"])
    authority = profile_service.resolve_authority(ctx["db"], ctx["owner"].id)
    assert profile_service.project(ctx["db"], authority, now=ctx["now"])["access_mode"] == "full"
    later = runtime().guardian_deadline(ctx["now"])
    assert profile_service.project(ctx["db"], authority, now=later)["access_mode"] == "limited"


def email_verified(ctx, actor):
    from app.services.otp_sender import CapturingSender
    sender = CapturingSender()
    email = "owner@example.edu" if actor.id == ctx["owner"].id else "reviewer@example.edu"
    runtime().request_email_proof(ctx["db"], actor.id, ctx["tokens"][actor.id], email=email, institution="example", sender=sender, key="email-request-0001", now=ctx["now"])
    code = sender.sent[0][1]
    result = runtime().verify_email_proof(ctx["db"], actor.id, ctx["tokens"][actor.id], code=code, key="email-verify-00001", now=ctx["now"])
    ctx["db"].commit()
    assert result == {"status": "verified"}


def test_institutional_requires_both_proofs_and_admin_assignment(ctx):
    s = runtime()
    email_verified(ctx, ctx["owner"])
    email_verified(ctx, ctx["reviewer"])
    s.request_review(ctx["db"], ctx["owner"].id, ctx["tokens"][ctx["owner"].id], key="review-request-0001", now=ctx["now"])
    ctx["db"].commit()
    with pytest.raises(s.AuthorityError):
        s.review(ctx["db"], ctx["reviewer"].id, ctx["tokens"][ctx["reviewer"].id], registration_id=ctx["reg"].id, approve=True, key="review-complete-0001", now=ctx["now"])
    ctx["db"].rollback()
    s.assign_reviewer(ctx["db"], ctx["admin"].id, ctx["tokens"][ctx["admin"].id], reviewer_id=ctx["reviewer"].id, institution="example", expires_at=ctx["now"]+timedelta(days=30), key="reviewer-assignment1", now=ctx["now"])
    ctx["db"].commit()
    result = s.review(ctx["db"], ctx["reviewer"].id, ctx["tokens"][ctx["reviewer"].id], registration_id=ctx["reg"].id, approve=True, key="review-complete-0001", now=ctx["now"])
    ctx["db"].commit()
    assert result["institutional_state"] == "VERIFIED"
    assert s.institutional_is_current(ctx["db"], ctx["reg"].id, now=ctx["now"])


def test_student_cannot_assign_reviewers(ctx):
    with pytest.raises(runtime().AuthorityError):
        runtime().assign_reviewer(ctx["db"], ctx["owner"].id, ctx["tokens"][ctx["owner"].id], reviewer_id=ctx["reviewer"].id, institution="example", expires_at=ctx["now"]+timedelta(days=30), key="reviewer-assignment1", now=ctx["now"])


def test_unknown_institution_domain_cannot_receive_proof(ctx):
    from app.services.otp_sender import CapturingSender
    sender = CapturingSender()
    with pytest.raises(runtime().AuthorityError):
        runtime().request_email_proof(ctx["db"], ctx["reviewer"].id, ctx["tokens"][ctx["reviewer"].id], email="reviewer@attacker.example", institution="example", sender=sender, key="email-request-0002", now=ctx["now"])
    assert sender.sent == []


def test_owner_erasure_clears_linkable_graph_preserves_aggregate_audit(ctx):
    from sqlalchemy import func, select
    from app.models.student_authority import AuthorityAuditEvent, AuthorityState, GuardianInvitation, AuthorityMutationRecord
    consent(ctx, request(ctx)["invitation"])
    count = ctx["db"].scalar(select(func.count()).select_from(AuthorityAuditEvent))
    runtime().erase_owner_authority(ctx["db"], ctx["owner"].id, now=ctx["now"])
    ctx["db"].commit()
    for model in (AuthorityState, GuardianInvitation, AuthorityMutationRecord):
        assert ctx["db"].scalar(select(func.count()).select_from(model)) == 0
    assert ctx["db"].scalar(select(func.count()).select_from(AuthorityAuditEvent)) == count


def test_injected_failure_rolls_back_consent_and_invitation(ctx, monkeypatch):
    from app.models.student_authority import GuardianInvitation
    from sqlalchemy import select
    s = runtime()
    invitation = request(ctx)["invitation"]
    def crash(*args, **kwargs):
        raise RuntimeError("injected_transaction_failure")
    monkeypatch.setattr(s, "_finish", crash)
    with pytest.raises(RuntimeError):
        consent(ctx, invitation)
    ctx["db"].rollback()
    assert ctx["db"].scalar(select(GuardianInvitation.state)) == "pending"
    assert not s.guardian_is_current(ctx["db"], ctx["reg"].id, now=ctx["now"])


def test_canonical_authority_projection_settles_lost_guardian(ctx):
    from app.models.student_authority import AuthorityState
    consent(ctx, request(ctx)["invitation"])
    ctx["guardian"].status = "suspended"
    ctx["db"].commit()
    result = runtime().read_authority(ctx["db"], ctx["owner"].id, ctx["tokens"][ctx["owner"].id], ctx["now"])
    assert result["access_mode"] == "limited"
    assert ctx["db"].get(AuthorityState, ctx["reg"].id).guardian_state == "REVOKED"


def test_guardian_adult_identity_change_invalidates_dependent_consent(ctx):
    from sqlalchemy import select
    from app.core.crypto import encrypt, keyed_hash
    from app.models.registration import StudentRegistration
    from app.models.student_authority import AuthorityAuditEvent
    service = runtime()
    consent(ctx, request(ctx)["invitation"])
    guardian = ctx["db"].scalar(select(StudentRegistration).where(StudentRegistration.user_id == ctx["guardian"].id))
    guardian.dob_hash, guardian.dob_ct = keyed_hash("1990-02-02"), encrypt("1990-02-02")
    ctx["db"].commit()
    assert service.guardian_is_current(ctx["db"], ctx["reg"].id, now=ctx["now"]) is False
    current = service.read_authority(ctx["db"], ctx["owner"].id, ctx["tokens"][ctx["owner"].id], ctx["now"])
    ctx["db"].commit()
    assert (current["guardian_state"], current["access_mode"], current["reverification_required"]) == ("REQUIRED_PENDING", "limited", True)
    assert ctx["db"].scalar(select(AuthorityAuditEvent.transition_code).where(AuthorityAuditEvent.transition_code == "VERIFIED_TO_REQUIRED_PENDING")) == "VERIFIED_TO_REQUIRED_PENDING"


def test_reviewer_identity_change_invalidates_dependent_review(ctx):
    from sqlalchemy import select
    from app.core.crypto import encrypt, keyed_hash
    from app.models.registration import StudentRegistration, StudentProfile
    service = runtime()
    test_institutional_requires_both_proofs_and_admin_assignment(ctx)
    reviewer = ctx["db"].scalar(select(StudentRegistration).where(StudentRegistration.user_id == ctx["reviewer"].id))
    profile = ctx["db"].scalar(select(StudentProfile).where(StudentProfile.registration_id == reviewer.id))
    profile.institutional_email_hash, profile.institutional_email_ct = keyed_hash("changed@example.edu"), encrypt("changed@example.edu")
    ctx["db"].commit()
    assert service.institutional_is_current(ctx["db"], ctx["reg"].id, now=ctx["now"]) is False
    current = service.read_authority(ctx["db"], ctx["owner"].id, ctx["tokens"][ctx["owner"].id], ctx["now"])
    assert (current["institutional_state"], current["reverification_required"]) == ("PENDING", True)
    with pytest.raises(service.AuthorityError):
        service.review(ctx["db"], ctx["reviewer"].id, ctx["tokens"][ctx["reviewer"].id], registration_id=ctx["reg"].id, approve=True, key="reproof-stale-review1", now=ctx["now"])


@pytest.mark.parametrize("cause", ["guardian_lost", "guardian_erased", "reviewer_erased"])
def test_server_proof_loss_audit_never_impersonates_guardian_or_owner(ctx, cause):
    from sqlalchemy import select
    from app.models.student_authority import AuthorityAuditEvent
    service = runtime()
    if cause == "reviewer_erased":
        test_institutional_requires_both_proofs_and_admin_assignment(ctx)
        service.erase_owner_authority(ctx["db"], ctx["reviewer"].id, now=ctx["now"])
    else:
        consent(ctx, request(ctx)["invitation"])
        if cause == "guardian_erased":
            service.erase_owner_authority(ctx["db"], ctx["guardian"].id, now=ctx["now"])
        else:
            ctx["guardian"].status = "suspended"
            ctx["db"].commit()
            service.read_authority(ctx["db"], ctx["owner"].id, ctx["tokens"][ctx["owner"].id], ctx["now"])
    ctx["db"].commit()
    events = list(ctx["db"].scalars(select(AuthorityAuditEvent).where(AuthorityAuditEvent.transition_code == "PROOF_REVOKED")))
    assert len(events) == 1
    assert (events[0].actor_class, events[0].authority_class) == ("server", "server_profile_policy")


def test_server_proof_loss_helper_cannot_revoke_a_current_proof(ctx):
    from app.models.student_authority import AuthorityState
    consent(ctx, request(ctx)["invitation"])
    row = ctx["db"].get(AuthorityState, ctx["reg"].id)
    assert runtime()._invalidate_server_proofs(ctx["db"], row, now=ctx["now"]) is False
    assert row.guardian_state == "VERIFIED"


def test_manual_revocation_audit_preserves_actual_guardian_and_owner(ctx, monkeypatch):
    from sqlalchemy import select
    from app.core.config import settings
    from app.models.student_authority import AuthorityAuditEvent
    service = runtime()
    consent(ctx, request(ctx)["invitation"])
    service.guardian_revoke(ctx["db"], ctx["guardian"].id, ctx["tokens"][ctx["guardian"].id], registration_id=ctx["reg"].id, key="manual-revoke-guardian", now=ctx["now"])
    test_institutional_requires_both_proofs_and_admin_assignment(ctx)
    monkeypatch.setattr(settings, "authority_platform_owner_id", str(ctx["admin"].id))
    service.owner_break_glass(ctx["db"], ctx["admin"].id, ctx["tokens"][ctx["admin"].id], registration_id=ctx["reg"].id, key="manual-revoke-owner", now=ctx["now"])
    ctx["db"].commit()
    events = list(ctx["db"].scalars(select(AuthorityAuditEvent).where(AuthorityAuditEvent.transition_code == "VERIFIED_TO_REVOKED")))
    assert {(event.actor_class, event.authority_class) for event in events} == {("guardian", "guardian"), ("owner", "platform_owner")}


def test_legacy_review_scope_precedes_metadata_and_replay_is_exact(ctx, monkeypatch):
    from app.api.v1 import auth_student
    from app.core.config import settings
    from app.db.session import get_session
    from app.models.student_authority import InstitutionalReviewerAssignment
    from sqlalchemy import select
    from tests import apptemplate
    service = runtime()
    ctx["reviewer"].role = "legal_reviewer"
    ctx["db"].commit()
    email_verified(ctx, ctx["owner"])
    email_verified(ctx, ctx["reviewer"])
    service.request_review(ctx["db"], ctx["owner"].id, ctx["tokens"][ctx["owner"].id], key="scoped-review-request", now=ctx["now"])
    ctx["db"].commit()
    app, client = apptemplate.mounted_app(exception_handlers=True)
    apptemplate.fresh(app, client)
    app.dependency_overrides[get_session] = lambda: ctx["db"]
    monkeypatch.setattr(auth_student, "_now", lambda: ctx["now"])
    monkeypatch.setattr(settings, "cors_origins", ["http://testserver"])
    client.cookies.set(settings.auth_session_cookie_name, ctx["tokens"][ctx["reviewer"].id])
    headers = {"Origin": "http://testserver", "Idempotency-Key": "legacy-scoped-review"}
    payload = {"registration_id": str(ctx["reg"].id), "status": "verified", "expected_profile_version": 999}
    path = "/api/v1/auth/student/verification/status"
    try:
        unassigned = client.post(path, headers=headers, json=payload)
        assert unassigned.status_code == 403
        assert "current_profile_version" not in unassigned.text
        service.assign_reviewer(ctx["db"], ctx["admin"].id, ctx["tokens"][ctx["admin"].id], reviewer_id=ctx["reviewer"].id, institution="example", expires_at=ctx["now"] + timedelta(days=1), now=ctx["now"], key="legacy-review-assign")
        assignment = ctx["db"].scalar(select(InstitutionalReviewerAssignment))
        assignment.institution = "foreign"
        ctx["db"].commit()
        foreign = client.post(path, headers=headers, json=payload)
        assert foreign.status_code == 403
        assert "current_profile_version" not in foreign.text
        assignment.institution = "example"
        ctx["db"].commit()
        stale = client.post(path, headers=headers, json=payload)
        assert stale.status_code == 409
        assert stale.json()["detail"]["current_profile_version"] == 1
        payload["expected_profile_version"] = 1
        original = client.post(path, headers=headers, json=payload)
        assert original.status_code == 200
        ctx["profile"].profile_version = 2
        ctx["profile"].city = "Synthetic"
        ctx["db"].commit()
        replay = client.post(path, headers=headers, json=payload)
        assert replay.status_code == 200
        assert replay.json() == original.json()
        payload["expected_profile_version"] = 2
        changed = client.post(path, headers=headers, json=payload)
        assert changed.status_code == 409
        assert changed.json()["detail"]["code"] == "authority_idempotency_conflict"
    finally:
        app.dependency_overrides.clear()
        client.cookies.clear()


def test_profile_reviewer_proof_uses_the_single_request_clock(ctx, monkeypatch):
    from app.services import profile_service
    test_institutional_requires_both_proofs_and_admin_assignment(ctx)
    authority = profile_service.resolve_authority(ctx["db"], ctx["owner"].id)
    observed = []
    def proof(session, registration_id, *, now):
        observed.append(now)
        return True
    monkeypatch.setattr(runtime(), "institutional_is_current", proof)
    assert profile_service.verification_has_current_reviewer_provenance(ctx["db"], authority, now=ctx["now"])
    assert observed == [ctx["now"]]


def test_review_timeout_is_wired_to_canonical_read(ctx):
    from sqlalchemy import select
    from app.models.student_authority import AuthorityNotification
    s = runtime()
    s.request_review(ctx["db"], ctx["owner"].id, ctx["tokens"][ctx["owner"].id], key="review-request-0009", now=ctx["now"]-timedelta(days=8))
    ctx["db"].commit()
    result = s.read_authority(ctx["db"], ctx["owner"].id, ctx["tokens"][ctx["owner"].id], ctx["now"])
    assert result["institutional_state"] == "PENDING"
    assert ctx["db"].scalar(select(AuthorityNotification.code)) == "review_returned_to_queue"


def test_current_proof_consumers_issue_no_for_update_queries(ctx):
    import sqlalchemy as sa
    statements = []
    def collect(orm_execute_state):
        statements.append(orm_execute_state.statement)
    sa.event.listen(ctx["db"], "do_orm_execute", collect)
    runtime().institutional_is_current(ctx["db"], ctx["reg"].id, now=ctx["now"])
    runtime().guardian_is_current(ctx["db"], ctx["reg"].id, now=ctx["now"])
    assert all(getattr(statement, "_for_update_arg", None) is None for statement in statements)


def test_timeout_notification_is_owner_observable_without_linkable_identifiers(ctx):
    service = runtime()
    service.request_review(ctx["db"], ctx["owner"].id, ctx["tokens"][ctx["owner"].id], key="review-notice-000001", now=ctx["now"] - timedelta(days=8))
    ctx["db"].commit()
    result = service.read_notifications(ctx["db"], ctx["owner"].id, ctx["tokens"][ctx["owner"].id], now=ctx["now"])
    assert result == {"notifications": [{"code": "review_returned_to_queue", "state_version": 3}]}
    assert service.read_notifications(ctx["db"], ctx["guardian"].id, ctx["tokens"][ctx["guardian"].id], now=ctx["now"]) == {"notifications": []}
    with pytest.raises(service.AuthorityError):
        service.read_notifications(ctx["db"], ctx["owner"].id, ctx["tokens"][ctx["guardian"].id], now=ctx["now"])


def test_http_strict_cookie_and_schema_boundary(ctx, monkeypatch):
    from app.api.v1 import student_authority as api
    from app.core.config import settings
    from app.db.session import get_session
    from tests import apptemplate
    app, client = apptemplate.mounted_app(exception_handlers=True)
    apptemplate.fresh(app, client)
    app.dependency_overrides[get_session] = lambda: ctx["db"]
    monkeypatch.setattr(api, "_now", lambda: ctx["now"])
    monkeypatch.setattr(settings, "cors_origins", ["http://testserver"])
    try:
        assert client.get("/api/v1/auth/student/authority").status_code == 401
        client.cookies.set(settings.auth_session_cookie_name, ctx["tokens"][ctx["owner"].id])
        headers = {"Origin": "http://testserver", "Idempotency-Key": "request-http-000001"}
        assert client.post("/api/v1/auth/student/authority/guardian/request", headers=headers, json={"guardian_state": "VERIFIED"}).status_code == 422
        result = client.post("/api/v1/auth/student/authority/guardian/request", headers=headers, json={})
        assert result.status_code == 200, result.text
        assert result.headers["cache-control"] == "private, no-store"
        assert result.json()["guardian_state"] == "REQUIRED_PENDING"
        assert set(result.json()) == {"policy_version", "guardian_state", "institutional_state", "version", "access_mode", "reverification_required", "invitation"}
        assert client.get("/api/v1/auth/student/authority?owner=foreign").status_code == 422
    finally:
        app.dependency_overrides.clear()
        client.cookies.clear()
