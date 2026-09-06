"""Public retention preserves NYAY-11 reviewer serialization and rollback.

These runtime contracts supplement the real two-connection PostgreSQL
schedule tests. No session or authority check is replaced by a synthetic pass.
"""
from __future__ import annotations

from datetime import timedelta

import pytest
from sqlalchemy import func, select

from app.core import retention
from app.models.registration import AuthSession, StudentRegistration
from app.models.student_authority import (
    AuthorityAuditEvent,
    AuthorityState,
    InstitutionalEmailProof,
    InstitutionalReviewerAssignment,
)
from app.services import student_authority
from tests.test_nyay11_runtime import ctx, email_verified  # noqa: F401


def _approved_review(ctx):
    session, now = ctx["db"], ctx["now"]
    for actor in (ctx["owner"], ctx["reviewer"]):
        email_verified(ctx, actor)
    student_authority.request_review(
        session, ctx["owner"].id, ctx["tokens"][ctx["owner"].id],
        key="erasure-order-review-request", now=now,
    )
    student_authority.assign_reviewer(
        session, ctx["admin"].id, ctx["tokens"][ctx["admin"].id],
        reviewer_id=ctx["reviewer"].id, institution="example",
        expires_at=now + timedelta(days=30), key="erasure-order-assignment", now=now,
    )
    student_authority.review(
        session, ctx["reviewer"].id, ctx["tokens"][ctx["reviewer"].id],
        registration_id=ctx["reg"].id, approve=True,
        key="erasure-order-approved-review", now=now,
    )
    session.commit()
    assert student_authority.institutional_is_current(session, ctx["reg"].id, now=now)
    return session.scalar(select(StudentRegistration).where(
        StudentRegistration.user_id == ctx["reviewer"].id,
    ))


@pytest.mark.parametrize("wrapper", ["delete_registration", "anonymise_registration"])
def test_reviewer_erasure_locks_user_before_dependent_authority(ctx, monkeypatch, wrapper):
    reg = _approved_review(ctx)
    seen = []
    original_lock = retention.login_service.lock_user_for_session_rotation
    original_erase = student_authority.erase_owner_authority

    def lock_user(session, user_id):
        row = original_lock(session, user_id)
        seen.append("user_locked")
        return row

    def erase_authority(session, user_id, *, now):
        seen.append("authority_erasure")
        return original_erase(session, user_id, now=now)

    monkeypatch.setattr(retention.login_service, "lock_user_for_session_rotation", lock_user)
    monkeypatch.setattr(student_authority, "erase_owner_authority", erase_authority)
    assert getattr(retention, wrapper)(ctx["db"], reg) is True
    ctx["db"].commit()
    assert seen == ["user_locked", "authority_erasure"]
    state = ctx["db"].get(AuthorityState, ctx["reg"].id, populate_existing=True)
    assert state.institutional_state == "REVOKED"
    assert state.reviewer_user_id is None
    assert state.reproof_institutional is True
    assert ctx["db"].get(InstitutionalEmailProof, ctx["reviewer"].id) is None
    assert ctx["db"].scalar(select(func.count()).select_from(
        InstitutionalReviewerAssignment,
    )) == 0
    event = ctx["db"].scalar(select(AuthorityAuditEvent).where(
        AuthorityAuditEvent.transition_code == "PROOF_REVOKED",
    ))
    assert (event.actor_class, event.authority_class) == ("server", "server_profile_policy")


@pytest.mark.parametrize("wrapper", ["delete_registration", "anonymise_registration"])
def test_reviewer_erasure_failure_rolls_back_auth_proofs_and_audit(ctx, monkeypatch, wrapper):
    reg = _approved_review(ctx)
    session = ctx["db"]
    reviewer_id, registration_id = ctx["reviewer"].id, reg.id
    count = session.scalar(select(func.count()).select_from(AuthorityAuditEvent))
    original_erase = student_authority.erase_owner_authority

    def fail_after_authority_erasure(session, user_id, *, now):
        original_erase(session, user_id, now=now)
        session.flush()
        raise RuntimeError("INJECTED_AUTHORITY_ERASURE_FAILURE")

    monkeypatch.setattr(student_authority, "erase_owner_authority", fail_after_authority_erasure)
    with pytest.raises(RuntimeError, match="^INJECTED_AUTHORITY_ERASURE_FAILURE$"):
        getattr(retention, wrapper)(session, reg)
    session.rollback()
    assert session.get(StudentRegistration, registration_id).status == "active"
    assert session.scalar(select(AuthSession.status).where(AuthSession.user_id == reviewer_id)) == "active"
    assert session.get(InstitutionalEmailProof, reviewer_id).state == "verified"
    assert session.scalar(select(func.count()).select_from(InstitutionalReviewerAssignment)) == 1
    assert session.scalar(select(func.count()).select_from(AuthorityAuditEvent)) == count
    state = session.get(AuthorityState, ctx["reg"].id, populate_existing=True)
    assert (state.institutional_state, state.reviewer_user_id) == ("VERIFIED", reviewer_id)
    assert student_authority.institutional_is_current(session, ctx["reg"].id, now=ctx["now"])
