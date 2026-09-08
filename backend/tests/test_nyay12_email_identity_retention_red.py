"""NYAY-12 review S1: complete email-identity graph disposition under NYAY-19/22 rules.

RED-first contracts for anonymise, delete, mentor DEFER atomicity, remove-time
tombstones, bounded terminal retention and the interleaved verify-vs-erasure
schedule. Evidence never contains a raw address; assertions use only masks,
hashes and row states.
"""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select, text

from app.core import retention
from app.core.crypto import decrypt, keyed_hash
from app.core.email_identity import email_identity_hash
from app.core.retention import ANONYMISED, RetentionPolicy, anonymise_registration, delete_registration, purge_expired
from app.db.models.audit import AuditEvent
from app.models.email_identity import EmailIdentityMutation, EmailIdentityReconciliation, UserEmailIdentity
from app.models.registration import StudentRegistration, User
from tests.test_nyay12_email_identity_red import Ctx, _add, _add_verified, _key, _remove, _verify, EMAIL_START, ROOT

EMAIL_A = "retention.subject@example.test"
EMAIL_SHARED = "shared.collision@example.test"


@pytest.fixture()
def ctx(monkeypatch: pytest.MonkeyPatch) -> Ctx:
    return Ctx(monkeypatch)


def _registration(session, user_id):
    return session.scalar(select(StudentRegistration).where(StudentRegistration.user_id == user_id))


def _not_decryptable(row: UserEmailIdentity) -> bool:
    """A tombstone decrypts only to the retention marker, never to an address."""
    try:
        plaintext = decrypt(row.email_ct)
    except Exception:
        return True
    return plaintext == ANONYMISED


def _seed_subject_graph(ctx: Ctx):
    """Subject A: verified + pending identities, sealed ledger, a collision where A is the claimant."""
    a = ctx.client
    a_user = ctx.register_student(a, "9876543210")
    verified_id = _add_verified(ctx, a, EMAIL_A)
    pending_id = _add(a, "pending.subject@example.test").json()["identity"]["id"]
    b = ctx.new_client()
    b_user = ctx.register_student(b, "9876543211")
    _add_verified(ctx, b, EMAIL_SHARED)
    claim_id = _add(a, EMAIL_SHARED).json()["identity"]["id"]
    conflict = _verify(a, claim_id, ctx.email.sent[-1][1])
    assert conflict.status_code == 409
    return a_user, b_user, verified_id, pending_id, claim_id


# --------------------------------------------------------------------------- #
# Anonymise                                                                    #
# --------------------------------------------------------------------------- #
def test_anonymise_disposes_the_complete_email_identity_graph(ctx: Ctx):
    a_user, b_user, verified_id, pending_id, claim_id = _seed_subject_graph(ctx)
    original_hash = email_identity_hash(EMAIL_A)
    with ctx.factory() as session:
        assert session.scalar(select(EmailIdentityMutation).where(EmailIdentityMutation.user_id == a_user)) is not None
        assert anonymise_registration(session, _registration(session, a_user)) is True
        session.commit()
    with ctx.factory() as session:
        rows = session.scalars(select(UserEmailIdentity).where(UserEmailIdentity.user_id == a_user)).all()
        assert {str(r.id) for r in rows} == {verified_id, pending_id, claim_id}
        for row in rows:
            assert row.state == "removed" and row.is_primary is False and row.removed_at is not None
            assert row.deleted_at is not None
            assert _not_decryptable(row), "NYAY12_ERASURE_RETAINS_DECRYPTABLE_IDENTITY"
            assert row.email_hash != original_hash and row.email_hash != email_identity_hash(EMAIL_SHARED)
            assert row.email_hash == keyed_hash(f"nyay12:email-identity-erased:v1:{row.id}")
            assert row.verification_state == "none" and row.code_hash is None and row.provider_receipt_hash is None
            assert row.challenge_issued_at is None and row.challenge_expires_at is None and row.metadata_json is None
        # Sealed ledger outcomes (they carry masks and identity ids) are gone.
        assert session.scalar(select(EmailIdentityMutation).where(EmailIdentityMutation.user_id == a_user)) is None
        # The collision record loses the erased party's link but keeps the holder's review value.
        reconciliations = session.scalars(select(EmailIdentityReconciliation)).all()
        assert len(reconciliations) == 1
        rec = reconciliations[0]
        assert rec.claimant_user_id is None and rec.holder_user_id == b_user and rec.state == "open"
        assert rec.email_hash == email_identity_hash(EMAIL_SHARED)
        # B's verified identity is untouched (no partial or over-erasure).
        b_rows = session.scalars(select(UserEmailIdentity).where(UserEmailIdentity.user_id == b_user)).all()
        assert [r.state for r in b_rows] == ["verified"] and not _not_decryptable(b_rows[0])
        # Aggregate-only audit: no address, mask or hash in any audit row.
        for event in session.scalars(select(AuditEvent)).all():
            blob = json.dumps({c.name: getattr(event, c.name) for c in event.__table__.columns}, default=str)
            assert EMAIL_A not in blob and original_hash not in blob and "retention.subject" not in blob
        assert session.get(User, a_user).status == "deleted"
    # Login authority is gone: the erased address is a decoy and nothing is delivered.
    sent_before = len(ctx.email.sent)
    login = ctx.new_client()
    assert login.post(EMAIL_START, json={"email": EMAIL_A}).status_code == 202
    assert len(ctx.email.sent) == sent_before


def test_delete_removes_identities_ledgers_and_unlinks_reconciliations(ctx: Ctx):
    a_user, b_user, verified_id, pending_id, claim_id = _seed_subject_graph(ctx)
    with ctx.factory() as session:
        assert delete_registration(session, _registration(session, a_user)) is True
        session.commit()
    with ctx.factory() as session:
        assert session.scalar(select(UserEmailIdentity).where(UserEmailIdentity.user_id == a_user)) is None
        assert session.scalar(select(EmailIdentityMutation).where(EmailIdentityMutation.user_id == a_user)) is None
        rec = session.scalar(select(EmailIdentityReconciliation))
        assert rec.claimant_user_id is None and rec.holder_user_id == b_user
        assert session.get(User, a_user) is None
        assert session.scalar(select(UserEmailIdentity).where(UserEmailIdentity.user_id == b_user)).state == "verified"


def test_delete_after_both_parties_erased_resolves_reconciliation_with_unlinkable_hash(ctx: Ctx):
    a_user, b_user, *_ = _seed_subject_graph(ctx)
    with ctx.factory() as session:
        assert anonymise_registration(session, _registration(session, a_user)) is True
        session.commit()
    with ctx.factory() as session:
        assert anonymise_registration(session, _registration(session, b_user)) is True
        session.commit()
    with ctx.factory() as session:
        rec = session.scalar(select(EmailIdentityReconciliation))
        assert rec.holder_user_id is None and rec.claimant_user_id is None
        assert rec.state == "resolved" and rec.resolved_at is not None
        assert rec.email_hash == keyed_hash(f"nyay12:email-reconciliation-erased:v1:{rec.id}")
        assert rec.email_hash != email_identity_hash(EMAIL_SHARED)


def test_mentor_deferral_leaves_the_email_graph_untouched_atomically(ctx: Ctx, monkeypatch):
    from app.services import mentor_ceremony

    a_user, *_ = _seed_subject_graph(ctx)
    monkeypatch.setattr(mentor_ceremony, "prepare_subject_mentor_registration_erasure", lambda *args, **kwargs: "DEFER")
    with ctx.factory() as session:
        assert anonymise_registration(session, _registration(session, a_user)) is False
        session.commit()
    with ctx.factory() as session:
        rows = session.scalars(select(UserEmailIdentity).where(UserEmailIdentity.user_id == a_user)).all()
        assert sorted(r.state for r in rows) == ["pending", "pending", "verified"]
        assert all(not _not_decryptable(r) for r in rows)
        assert session.scalar(select(EmailIdentityMutation).where(EmailIdentityMutation.user_id == a_user)) is not None


def test_anonymise_after_partial_failure_leaves_no_partial_erasure(ctx: Ctx, monkeypatch):
    """A failure after the identity graph step rolls the whole transaction back."""
    a_user, *_ = _seed_subject_graph(ctx)
    original = retention._dispose_email_identity_graph

    def exploding(*args, **kwargs):
        original(*args, **kwargs)
        raise RuntimeError("synthetic post-disposition crash")

    monkeypatch.setattr(retention, "_dispose_email_identity_graph", exploding)
    with ctx.factory() as session:
        with pytest.raises(RuntimeError):
            anonymise_registration(session, _registration(session, a_user))
        session.rollback()
    with ctx.factory() as session:
        rows = session.scalars(select(UserEmailIdentity).where(UserEmailIdentity.user_id == a_user)).all()
        assert sorted(r.state for r in rows) == ["pending", "pending", "verified"]
        assert all(not _not_decryptable(r) for r in rows)
        assert session.get(User, a_user).status == "active"


# --------------------------------------------------------------------------- #
# Remove-time tombstone and bounded terminal retention                         #
# --------------------------------------------------------------------------- #
def test_owner_removal_tombstones_the_address_immediately(ctx: Ctx):
    owner = ctx.client
    ctx.register_student(owner, "9876543210")
    identity_id = _add_verified(ctx, owner, EMAIL_A)
    removed = _remove(owner, identity_id)
    assert removed.status_code == 200 and removed.json()["identity"]["email_masked"] == "r•••••@example.test"
    with ctx.factory() as session:
        row = session.get(UserEmailIdentity, uuid.UUID(identity_id))
        assert row.state == "removed" and _not_decryptable(row)
        assert row.email_hash == keyed_hash(f"nyay12:email-identity-erased:v1:{row.id}")
        assert row.deleted_at is not None
    # The address can be re-added and verified afresh by the same owner (no reservation by a tombstone).
    again = _add(owner, EMAIL_A)
    assert again.status_code == 202 and again.json()["identity"]["id"] != identity_id


def test_terminal_retention_purges_tombstones_ledgers_and_resolved_reconciliations(ctx: Ctx):
    a_user, b_user, verified_id, pending_id, claim_id = _seed_subject_graph(ctx)
    with ctx.factory() as session:
        assert anonymise_registration(session, _registration(session, a_user)) is True
        assert anonymise_registration(session, _registration(session, b_user)) is True
        session.commit()
    old = datetime.now(timezone.utc) - timedelta(days=400)
    with ctx.factory() as session:
        for row in session.scalars(select(UserEmailIdentity)).all():
            row.removed_at = old
            row.deleted_at = old
            row.updated_at = old
        for rec in session.scalars(select(EmailIdentityReconciliation)).all():
            rec.resolved_at = old
            rec.updated_at = old
        session.commit()
    policy = RetentionPolicy(
        registration_pending_days=None, registration_inactive_days=None, otp_challenge_days=None,
        recovery_session_days=None, audit_events_days=None, mode="anonymise", email_identity_terminal_days=30,
    )
    with ctx.factory() as session:
        counts = purge_expired(session, policy=policy)
        session.commit()
    assert counts["email_identity_tombstones"] == 4  # A: verified + pending + claim, B: verified
    assert counts["email_identity_reconciliations"] == 1
    with ctx.factory() as session:
        assert session.scalar(select(UserEmailIdentity)) is None
        assert session.scalar(select(EmailIdentityReconciliation)) is None
    # A fresh tombstone inside the window survives (bounded, not immediate).
    owner = ctx.new_client()
    ctx.register_student(owner, "9876543212")
    identity_id = _add_verified(ctx, owner, "fresh.subject@example.test")
    assert _remove(owner, identity_id).status_code == 200
    with ctx.factory() as session:
        counts = purge_expired(session, policy=policy)
        session.commit()
        assert counts["email_identity_tombstones"] == 0
        assert session.get(UserEmailIdentity, uuid.UUID(identity_id)).state == "removed"


def test_terminal_retention_policy_is_validated_and_defaults_bounded():
    from app.core.config import settings

    assert 1 <= settings.retention_days_email_identity_terminal <= 36_500
    assert RetentionPolicy.from_settings().email_identity_terminal_days == settings.retention_days_email_identity_terminal
    with pytest.raises(ValueError):
        retention._validated_policy(RetentionPolicy(
            registration_pending_days=None, registration_inactive_days=None, otp_challenge_days=None,
            recovery_session_days=None, audit_events_days=None, mode="anonymise", email_identity_terminal_days=0,
        ))


# --------------------------------------------------------------------------- #
# Schedules and lock order                                                     #
# --------------------------------------------------------------------------- #
def test_interleaved_verify_and_erasure_schedules_never_leave_authority(ctx: Ctx):
    # Schedule 1: erasure first, then the owner's verify replays a still-valid code.
    a = ctx.client
    a_user = ctx.register_student(a, "9876543210")
    pending = _add(a, EMAIL_A).json()["identity"]["id"]
    code = ctx.email.sent[-1][1]
    with ctx.factory() as session:
        assert anonymise_registration(session, _registration(session, a_user)) is True
        session.commit()
    late = _verify(a, pending, code)
    assert late.status_code in {401, 404}
    with ctx.factory() as session:
        row = session.get(UserEmailIdentity, uuid.UUID(pending))
        assert row.state == "removed" and _not_decryptable(row)
        assert session.scalar(select(UserEmailIdentity).where(UserEmailIdentity.state == "verified")) is None
    # Schedule 2: verify first, then erasure disposes the freshly verified identity.
    b = ctx.new_client()
    b_user = ctx.register_student(b, "9876543211")
    verified = _add_verified(ctx, b, "second.subject@example.test")
    with ctx.factory() as session:
        assert anonymise_registration(session, _registration(session, b_user)) is True
        session.commit()
    with ctx.factory() as session:
        row = session.get(UserEmailIdentity, uuid.UUID(verified))
        assert row.state == "removed" and row.is_primary is False and _not_decryptable(row)
    assert b.get(ROOT).status_code == 401


def test_service_and_retention_share_the_registration_before_user_lock_order():
    from pathlib import Path

    source = Path(retention.__file__).read_text(encoding="utf-8")
    body = source[source.index("def _anonymise_locked("):source.index("def anonymise_registration(")]
    assert body.index("erase_owner_authority(") < body.index("_dispose_email_identity_graph(") < body.index("AuditEvent(")
    delete_body = source[source.index("def _delete_locked("):source.index("def delete_registration(")]
    assert delete_body.index("erase_owner_authority(") < delete_body.index("_dispose_email_identity_graph(") < delete_body.index("session.delete(reg)")
    service_source = Path(__import__("app.services.email_identity_service", fromlist=["x"]).__file__).read_text(encoding="utf-8")
    for name in ("def add_identity(", "def verify_identity(", "def set_primary("):
        function = service_source[service_source.index(name):]
        function = function[:function.index("\ndef ")] if "\ndef " in function else function
        assert function.index("_lock_registration(") < function.index("_presented(")
