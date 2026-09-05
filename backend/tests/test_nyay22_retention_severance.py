"""NYAY-22 bounded expiry and non-destructive authority-graph severance.

These contracts intentionally exercise the unshipped 0023 schema on a
disposable test database only.  They never run a migration or retention worker
against a configured/live database.
"""
from __future__ import annotations

import ast
import inspect as pyinspect
import json
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, func, inspect, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from app.api.v1.auth_mentor import router
from app.core.config import settings
from app.core.crypto import active_key_version, encrypt, keyed_hash
from app.db.session import get_session
from app.models.mentor_auth import (
    MentorAuditLink,
    MentorAuthorityStepUp,
    MentorBootstrapAttempt,
    MentorCeremony,
    MentorConsent,
    MentorEngagement,
    MentorIdempotencyRecord,
    MentorInvitation,
    MentorProviderResult,
    MentorRetentionBlockedGraph,
    MentorSession,
    MentorSubjectConsent,
    TutorProfileOwnershipProof,
)
from app.services import mentor_ceremony
from tests import dbtemplate
from tests.test_nyay22_tutor_ceremony_runtime import (
    _initiate,
    _seed_graph,
    _verify_and_exchange,
)


MENTOR_GRAPH_MODELS = (
    MentorBootstrapAttempt,
    MentorInvitation,
    TutorProfileOwnershipProof,
    MentorCeremony,
    MentorProviderResult,
    MentorSubjectConsent,
    MentorEngagement,
    MentorConsent,
    MentorSession,
    MentorAuthorityStepUp,
    MentorIdempotencyRecord,
    MentorAuditLink,
)

SEVERED_LINK_COLUMNS = {
    MentorInvitation: ("subject_registration_id", "initiator_user_id"),
    TutorProfileOwnershipProof: ("user_id", "tutor_profile_id"),
    MentorCeremony: (
        "bootstrap_attempt_id",
        "actor_user_id",
        "tutor_profile_id",
        "ownership_proof_id",
        "invitation_id",
    ),
    MentorProviderResult: ("ceremony_id",),
    MentorSubjectConsent: (
        "invitation_id",
        "subject_registration_id",
        "granted_by_user_id",
        "guardian_consent_id",
    ),
    MentorEngagement: (
        "invitation_id",
        "subject_registration_id",
        "mentor_user_id",
        "tutor_profile_id",
    ),
    MentorConsent: ("engagement_id",),
    MentorSession: (
        "ceremony_id",
        "engagement_id",
        "actor_user_id",
        "tutor_profile_id",
        "ownership_proof_id",
        "consent_id",
        "subject_consent_id",
        "successor_id",
    ),
    MentorAuthorityStepUp: (
        "ceremony_id",
        "actor_user_id",
        "mentor_session_id",
    ),
}

# Links that must exist until the graph is explicitly severed.  Guardian and
# successor links are intentionally excluded: they are optional while live but
# must still be cleared by severance (and therefore remain in the mapping
# above).
REQUIRED_PRE_SEVERANCE_LINK = {
    model: columns[0]
    for model, columns in SEVERED_LINK_COLUMNS.items()
    if model not in {MentorSubjectConsent, MentorSession}
}
REQUIRED_PRE_SEVERANCE_LINK.update(
    {
        MentorCeremony: "actor_user_id",
        MentorSubjectConsent: "invitation_id",
        MentorSession: "ceremony_id",
    }
)

LINKAGE_CONSTRAINT_NAMES = {
    model: (
        "ck_mentor_ceremonies_severed_state_has_no_authority_links"
        if model is MentorCeremony
        else f"ck_{model.__tablename__}_retention_linkage_shape"
    )
    for model in REQUIRED_PRE_SEVERANCE_LINK
}

SENSITIVE_DIGEST_COLUMNS = {
    MentorBootstrapAttempt: ("token_hash",),
    MentorInvitation: (
        "initiator_session_hash",
        "creation_idempotency_hash",
        "mentor_match_hash",
        "authority_domain_hash",
    ),
    TutorProfileOwnershipProof: ("provider_subject_hash", "evidence_digest"),
    MentorCeremony: ("token_hash", "challenge_hash"),
    MentorProviderResult: (
        "issuer_hash",
        "audience_hash",
        "nonce_hash",
        "correlation_hash",
        "provider_subject_hash",
        "evidence_digest",
    ),
    MentorSubjectConsent: ("granting_session_hash", "grant_idempotency_hash"),
    MentorEngagement: ("authority_domain_hash",),
    MentorSession: ("authority_domain_hash", "token_hash"),
    MentorAuthorityStepUp: ("token_hash", "fingerprint"),
    MentorIdempotencyRecord: (
        "scope_hash",
        "idempotency_key_hash",
        "request_fingerprint",
    ),
    MentorAuditLink: ("correlation_hash",),
}

# Closed post-severance inventory.  Anything not named here must be NULL; a new
# column therefore fails this contract until its privacy disposition is
# reviewed explicitly.  Hash fields below contain fresh row-unique tombstones,
# not stable authority digests.
PII_FREE_SURVIVING_COLUMNS = {
    MentorBootstrapAttempt: {
        "id", "token_hash", "requested_role", "purpose_code", "state",
        "expires_at", "consumed_at", "created_at", "updated_at", "deleted_at",
    },
    MentorInvitation: {
        "id", "initiator_session_hash", "creation_idempotency_hash",
        "purpose_policy_version", "mentor_match_hash", "authority_domain_hash",
        "mentor_role", "purpose_code", "consent_version",
        "acceptance_text_version", "disclosure_classes", "state", "expires_at",
        "accepted_at", "terminal_at", "created_at", "updated_at", "deleted_at",
    },
    TutorProfileOwnershipProof: {
        "id", "provider_class", "assurance_class", "policy_version",
        "provider_subject_hash", "evidence_digest", "key_version", "state",
        "issued_at", "expires_at", "revoked_at", "retention_class",
        "created_at", "updated_at", "deleted_at",
    },
    MentorCeremony: {
        "id", "token_hash", "challenge_hash", "intent", "requested_role",
        "purpose_code", "privacy_notice_version", "state", "generation",
        "recovery", "verification_policy_version", "verified_at", "expires_at",
        "terminal_at", "retention_class", "created_at", "updated_at", "deleted_at",
    },
    MentorProviderResult: {
        "id", "provider_class", "assurance_class", "policy_version",
        "issuer_hash", "audience_hash", "algorithm", "nonce_hash",
        "correlation_hash", "start_dispatched_at", "failure_count",
        "provider_subject_hash", "evidence_digest", "key_version", "state",
        "issued_at", "expires_at", "consumed_at", "retention_class",
        "created_at", "updated_at", "deleted_at",
    },
    MentorSubjectConsent: {
        "id", "granting_session_hash", "grant_idempotency_hash",
        "purpose_policy_version", "purpose_code", "version",
        "disclosure_classes", "status", "recorded_at", "expires_at",
        "revoked_at", "retention_class", "created_at", "updated_at", "deleted_at",
    },
    MentorEngagement: {
        "id", "authority_domain_hash", "purpose_code", "state", "activated_at",
        "terminal_at", "created_at", "updated_at", "deleted_at",
    },
    MentorConsent: {
        "id", "purpose_code", "version", "disclosure_classes", "status",
        "recorded_at", "revoked_at", "created_at", "updated_at", "deleted_at",
    },
    MentorSession: {
        "id", "authority_domain_hash", "token_hash", "mentor_role",
        "purpose_code", "scopes", "permitted_profile_slices", "state",
        "generation", "issued_at", "last_seen_at", "expires_at", "terminal_at",
        "retention_class", "created_at", "updated_at", "deleted_at",
    },
    MentorAuthorityStepUp: {
        "id", "token_hash", "intent", "fingerprint", "state", "issued_at",
        "expires_at", "consumed_at", "retention_class", "created_at",
        "updated_at", "deleted_at",
    },
    MentorIdempotencyRecord: {
        "id", "scope_hash", "operation", "idempotency_key_hash",
        "request_fingerprint", "state", "retention_class", "created_at", "updated_at",
    },
    MentorAuditLink: {
        "id", "audit_event_id", "correlation_hash", "retention_class",
        "expires_at", "erased_at",
    },
}


@pytest.fixture()
def retention_ctx(engine):
    dbtemplate.reset_to_empty_schema(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False, class_=Session)

    def request_session():
        db = factory()
        try:
            yield db
        finally:
            db.rollback()
            db.close()

    app = FastAPI()
    app.include_router(router, prefix="/api/v1")
    app.dependency_overrides[get_session] = request_session
    client = TestClient(app, headers={"Origin": settings.cors_origins[1]})
    try:
        yield client, factory
    finally:
        client.close()


@pytest.fixture()
def migrated_retention_ctx(alembic_db):
    """The same lifecycle over a database produced by real ``upgrade head``."""

    database = alembic_db("head", name="nyay22-retention-linkage")
    engine = create_engine(f"sqlite+pysqlite:///{database}")
    factory = sessionmaker(bind=engine, expire_on_commit=False, class_=Session)

    def request_session():
        db = factory()
        try:
            yield db
        finally:
            db.rollback()
            db.close()

    app = FastAPI()
    app.include_router(router, prefix="/api/v1")
    app.dependency_overrides[get_session] = request_session
    client = TestClient(app, headers={"Origin": settings.cors_origins[1]})
    try:
        yield client, factory, engine
    finally:
        client.close()
        engine.dispose()


def _terminal_graph(retention_ctx):
    client, factory = retention_ctx
    ids = _seed_graph(factory)
    assert _initiate(client, ids["bootstrap"]).status_code == 202
    assert _verify_and_exchange(client, factory, ids).status_code == 201
    old = datetime.now(timezone.utc) - timedelta(days=40)
    planted = "planted-identifying-free-text-must-not-survive"
    with factory() as db:
        session = db.scalar(select(MentorSession))
        invitation = db.scalar(select(MentorInvitation))
        subject_consent = db.scalar(select(MentorSubjectConsent))
        assert session is not None
        assert invitation is not None and subject_consent is not None
        db.add(
            MentorIdempotencyRecord(
                scope_hash=mentor_ceremony._scope_hash(
                    "owner-create-mentor-prerequisites",
                    f"owner-invitation:{invitation.id}",
                    {},
                ),
                operation="owner-create-mentor-prerequisites",
                idempotency_key_hash=keyed_hash(
                    "owner-prerequisite-retention-key"
                ),
                request_fingerprint=keyed_hash(
                    "owner-prerequisite-retention-request"
                ),
                state="succeeded",
                outcome_status=201,
                outcome_ct=encrypt(
                    json.dumps(
                        {
                            "invitationBinding": str(invitation.id),
                            "consentBinding": str(subject_consent.id),
                        },
                        sort_keys=True,
                    )
                ),
                key_version=active_key_version(),
                created_at=old,
                updated_at=old,
            )
        )
        db.add(
            MentorAuthorityStepUp(
                ceremony_id=session.ceremony_id,
                actor_user_id=session.actor_user_id,
                mentor_session_id=session.id,
                token_hash=keyed_hash("retention-step-up-token"),
                token_seed_ct=None,
                token_seed_key_version=None,
                intent="authority_deletion_step_up",
                fingerprint=keyed_hash("retention-step-up-fingerprint"),
                state="expired",
                issued_at=old - timedelta(minutes=10),
                expires_at=old - timedelta(minutes=5),
                consumed_at=old,
                retention_class="mentor_step_up_security",
            )
        )
        for row in db.scalars(select(MentorBootstrapAttempt)):
            row.state = "expired"
            row.consumed_at = old
            row.updated_at = old
            row.metadata_json = {"note": planted}
        for row in db.scalars(select(MentorInvitation)):
            row.state = "deleted"
            row.terminal_at = old
            row.updated_at = old
            row.metadata_json = {"note": planted}
        for row in db.scalars(select(TutorProfileOwnershipProof)):
            row.state = "deleted"
            row.revoked_at = old
            row.updated_at = old
            row.metadata_json = {"note": planted}
        for row in db.scalars(select(MentorCeremony)):
            row.state = "deleted"
            row.terminal_at = old
            row.updated_at = old
            row.metadata_json = {"note": planted}
        for row in db.scalars(select(MentorProviderResult)):
            row.state = "expired"
            row.consumed_at = old
            row.updated_at = old
            row.metadata_json = {"note": planted}
        for row in db.scalars(select(MentorSubjectConsent)):
            row.status = "deleted"
            row.revoked_at = old
            row.updated_at = old
            row.metadata_json = {"note": planted}
        for row in db.scalars(select(MentorEngagement)):
            row.state = "deleted"
            row.terminal_at = old
            row.updated_at = old
            row.metadata_json = {"note": planted}
        for row in db.scalars(select(MentorConsent)):
            row.status = "deleted"
            row.revoked_at = old
            row.updated_at = old
            row.metadata_json = {"note": planted}
        for row in db.scalars(select(MentorSession)):
            row.state = "deleted"
            row.terminal_at = old
            row.updated_at = old
            row.metadata_json = {"note": planted}
        for row in db.scalars(select(MentorAuthorityStepUp)):
            row.updated_at = old
            row.metadata_json = {"note": planted}
        for row in db.scalars(select(MentorIdempotencyRecord)):
            row.updated_at = old
        for row in db.scalars(select(MentorAuditLink)):
            row.expires_at = old
        db.commit()
    return factory, planted


def _snapshot(factory) -> dict[str, list[dict[str, object]]]:
    with factory() as db:
        return {
            model.__tablename__: [
                {
                    column.name: getattr(row, column.name)
                    for column in model.__table__.columns
                }
                for row in db.scalars(select(model).order_by(model.id))
            ]
            for model in MENTOR_GRAPH_MODELS
        }


def _assert_bidirectional_linkage_contract(
    retention_context,
    *,
    engine,
) -> None:
    """Exercise both halves of the linkage CHECKs, not just inspect DDL."""

    factory, _planted = _terminal_graph(retention_context)
    original_links: dict[type, object] = {}
    for model, column in REQUIRED_PRE_SEVERANCE_LINK.items():
        names = {
            constraint["name"]
            for constraint in inspect(engine).get_check_constraints(
                model.__tablename__
            )
        }
        assert LINKAGE_CONSTRAINT_NAMES[model] in names
        with factory() as db:
            row = db.scalar(select(model).order_by(model.id))
            assert row is not None
            original_links[model] = getattr(row, column)
            assert original_links[model] is not None
            if model is MentorCeremony:
                # The actor relation is state-appropriate only after proof
                # binding.  Exercise that conditional branch explicitly.
                row.state = "proof_verified"
                row.terminal_at = None
            setattr(row, column, None)
            with pytest.raises(IntegrityError):
                db.commit()
            db.rollback()

    with factory() as db:
        result = mentor_ceremony.run_mentor_retention(
            db,
            now=datetime.now(timezone.utc),
            batch_size=settings.mentor_retention_batch_size,
        )
    assert result["severed_graphs"] == 1

    for model, column in REQUIRED_PRE_SEVERANCE_LINK.items():
        with factory() as db:
            row = db.scalar(select(model).order_by(model.id))
            assert row is not None and row.deleted_at is not None
            assert getattr(row, column) is None
            setattr(row, column, original_links[model])
            with pytest.raises(IntegrityError):
                db.commit()
            db.rollback()


def test_live_and_severed_rows_enforce_bidirectional_linkage_contract(
    retention_ctx,
    migrated_retention_ctx,
) -> None:
    """GREEN: create-all and real-0023 schemas enforce exact link parity.

    A state-appropriate pre-severance row cannot drop a mandatory relation;
    an explicitly severed row cannot regain one.  Running this once against
    ORM-created DDL and once against a copied real ``alembic upgrade head``
    database prevents model/migration drift from weakening either direction.
    """

    client, factory = retention_ctx
    _assert_bidirectional_linkage_contract(
        (client, factory), engine=factory.kw["bind"]
    )
    migrated_client, migrated_factory, migrated_engine = migrated_retention_ctx
    _assert_bidirectional_linkage_contract(
        (migrated_client, migrated_factory), engine=migrated_engine
    )


def test_retention_shares_authority_serialization_and_never_skip_locks_graph(
    retention_ctx,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A busy graph node is waited for boundedly, never silently omitted."""

    factory, _planted = _terminal_graph(retention_ctx)
    with factory() as db:
        session = db.scalar(select(MentorSession))
        assert session is not None
        actor_id = session.actor_user_id
        authority_domain_hash = session.authority_domain_hash
    assert actor_id is not None

    row_lock_modes: list[bool] = []
    real_rows = mentor_ceremony._retention_rows

    def observe_rows(db, model, *criteria, limit, skip_locked=True):
        row_lock_modes.append(skip_locked)
        return real_rows(
            db,
            model,
            *criteria,
            limit=limit,
            skip_locked=skip_locked,
        )

    monkeypatch.setattr(mentor_ceremony, "_retention_rows", observe_rows)
    with factory() as db:
        graph = mentor_ceremony._load_authority_domain_graph(
            db, authority_domain_hash
        )
        assert graph["sessions"]
        db.rollback()
    assert row_lock_modes and set(row_lock_modes) == {False}

    authority_locks: list[uuid.UUID | None] = []
    real_authority_lock = mentor_ceremony._lock_authority_scope

    def observe_authority_lock(db, request=None, **kwargs):
        authority_locks.append(kwargs.get("actor_hint"))
        return real_authority_lock(db, request, **kwargs)

    monkeypatch.setattr(
        mentor_ceremony, "_lock_authority_scope", observe_authority_lock
    )
    with factory() as db:
        result = mentor_ceremony.run_mentor_retention(
            db,
            now=datetime.now(timezone.utc),
            batch_size=settings.mentor_retention_batch_size,
        )
    assert result["severed_graphs"] == 1
    assert actor_id in authority_locks


def test_whole_terminal_graph_is_atomically_severed_to_piifree_allowlist(
    retention_ctx,
) -> None:
    factory, planted = _terminal_graph(retention_ctx)
    before = _snapshot(factory)
    old_digests = {
        value
        for model in MENTOR_GRAPH_MODELS
        for row in before[model.__tablename__]
        for column in SENSITIVE_DIGEST_COLUMNS.get(model, ())
        if isinstance((value := row[column]), str)
    }

    with factory() as db:
        counts = mentor_ceremony.run_mentor_retention(
            db,
            now=datetime.now(timezone.utc),
            batch_size=settings.mentor_retention_batch_size,
        )
    assert counts["severed_graphs"] == 1
    assert counts["blocked_graphs"] == 0

    after = _snapshot(factory)
    new_digests: list[str] = []
    for model, columns in SEVERED_LINK_COLUMNS.items():
        for row in after[model.__tablename__]:
            assert all(row[column] is None for column in columns)
    for model in MENTOR_GRAPH_MODELS:
        for row in after[model.__tablename__]:
            assert {
                column for column, value in row.items() if value is not None
            } == PII_FREE_SURVIVING_COLUMNS[model]
            assert row.get("metadata_json") is None
            assert planted not in repr(row)
            for column in SENSITIVE_DIGEST_COLUMNS.get(model, ()):
                value = row[column]
                assert isinstance(value, str) and len(value) == 64
                new_digests.append(value)
    assert old_digests.isdisjoint(new_digests)
    assert len(new_digests) == len(set(new_digests))

    with factory() as db:
        invitation = db.scalar(select(MentorInvitation))
        proof = db.scalar(select(TutorProfileOwnershipProof))
        ceremony = db.scalar(select(MentorCeremony))
        provider = db.scalar(select(MentorProviderResult))
        subject_consent = db.scalar(select(MentorSubjectConsent))
        engagement = db.scalar(select(MentorEngagement))
        mentor_consent = db.scalar(select(MentorConsent))
        session = db.scalar(select(MentorSession))
        record = db.scalar(select(MentorIdempotencyRecord))
        links = list(db.scalars(select(MentorAuditLink)))
        assert all(
            value is not None
            for value in (
                invitation,
                proof,
                ceremony,
                provider,
                subject_consent,
                engagement,
                mentor_consent,
                session,
                record,
            )
        )
        assert invitation.disclosure_classes == []
        assert subject_consent.disclosure_classes == []
        assert mentor_consent.disclosure_classes == []
        assert session.scopes == [] and session.permitted_profile_slices == []
        assert ceremony.predecessor_token_hash is None
        assert ceremony.token_seed_ct is None
        assert ceremony.token_seed_key_version is None
        assert provider.nonce_ct is None and provider.correlation_ct is None
        assert provider.transaction_key_version is None
        assert session.token_seed_ct is None
        assert session.token_seed_key_version is None
        assert record.state == "erased"
        assert record.outcome_status is None and record.outcome_ct is None
        assert record.key_version is None
        assert links and all(
            link.link_key_ct is None
            and link.actor_link_ct is None
            and link.key_version is None
            and link.erased_at is not None
            for link in links
        )


def test_injected_mid_severance_failure_rolls_back_the_complete_graph(
    retention_ctx, monkeypatch: pytest.MonkeyPatch
) -> None:
    factory, _planted = _terminal_graph(retention_ctx)
    before = _snapshot(factory)
    real_tombstone = mentor_ceremony._retention_tombstone
    calls = 0

    def fail_midway(label: str) -> str:
        nonlocal calls
        calls += 1
        if calls == 7:
            raise RuntimeError("privacy-safe injected retention failure")
        return real_tombstone(label)

    monkeypatch.setattr(mentor_ceremony, "_retention_tombstone", fail_midway)
    with factory() as db, pytest.raises(RuntimeError):
        mentor_ceremony.run_mentor_retention(
            db,
            now=datetime.now(timezone.utc),
            batch_size=settings.mentor_retention_batch_size,
        )
    assert _snapshot(factory) == before


def test_graph_above_hard_cap_is_registered_for_nyay19_without_partial_unlink(
    retention_ctx,
) -> None:
    factory, _planted = _terminal_graph(retention_ctx)
    old = datetime.now(timezone.utc) - timedelta(days=40)
    with factory() as db:
        template = db.scalar(select(MentorSession))
        assert template is not None
        for index in range(257):
            db.add(
                MentorSession(
                    ceremony_id=template.ceremony_id,
                    engagement_id=template.engagement_id,
                    actor_user_id=template.actor_user_id,
                    tutor_profile_id=template.tutor_profile_id,
                    ownership_proof_id=template.ownership_proof_id,
                    consent_id=template.consent_id,
                    subject_consent_id=template.subject_consent_id,
                    authority_domain_hash=template.authority_domain_hash,
                    token_hash=keyed_hash(f"oversize-session-{index}"),
                    token_seed_ct=None,
                    token_seed_key_version=None,
                    mentor_role=template.mentor_role,
                    purpose_code=template.purpose_code,
                    scopes=list(template.scopes),
                    permitted_profile_slices=list(
                        template.permitted_profile_slices
                    ),
                    state="deleted",
                    generation=index + 2,
                    issued_at=old - timedelta(hours=1),
                    last_seen_at=old - timedelta(hours=1),
                    expires_at=old,
                    terminal_at=old,
                    updated_at=old,
                )
            )
        db.commit()
        linked_before = db.scalar(
            select(func.count()).select_from(MentorSession).where(
                MentorSession.actor_user_id.is_not(None)
            )
        )

    with factory() as db:
        counts = mentor_ceremony.run_mentor_retention(
            db,
            now=datetime.now(timezone.utc),
            batch_size=settings.mentor_retention_batch_size,
        )
    assert counts["severed_graphs"] == 0
    assert counts["blocked_graphs"] == 1
    with factory() as db:
        alert = db.scalar(select(MentorRetentionBlockedGraph))
        assert alert is not None
        assert alert.reason_code == "GRAPH_EXCEEDS_HARD_CAP"
        assert alert.observed_row_count > 256
        assert alert.review_queue == "nyay19_retention_review"
        assert len(alert.graph_key_hash) == 64
        assert db.scalar(
            select(func.count()).select_from(MentorSession).where(
                MentorSession.actor_user_id.is_not(None)
            )
        ) == linked_before


def test_abandoned_authority_is_materialized_before_retention_window(
    retention_ctx,
) -> None:
    client, factory = retention_ctx
    ids = _seed_graph(factory)
    assert _initiate(client, ids["bootstrap"]).status_code == 202
    now = datetime.now(timezone.utc)
    with factory() as db:
        bootstrap = db.scalar(select(MentorBootstrapAttempt))
        ceremony = db.scalar(select(MentorCeremony))
        provider = db.scalar(select(MentorProviderResult))
        invitation = db.scalar(select(MentorInvitation))
        proof = db.scalar(select(TutorProfileOwnershipProof))
        subject_consent = db.scalar(select(MentorSubjectConsent))
        assert all(
            row is not None
            for row in (
                bootstrap,
                ceremony,
                provider,
                invitation,
                proof,
                subject_consent,
            )
        )
        # Recreate an abandoned pre-navigation bootstrap alongside the other
        # elapsed authority rows; initiation has consumed the fixture's first
        # bootstrap already.
        bootstrap.state = "active"
        bootstrap.consumed_at = None
        for row in (bootstrap, ceremony, provider, invitation, proof, subject_consent):
            row.expires_at = now - timedelta(seconds=1)
        db.commit()

    with factory() as db:
        counts = mentor_ceremony.run_mentor_retention(db, now=now)
        assert counts["materialized_expirations"] == 6
    with factory() as db:
        assert db.scalar(select(MentorBootstrapAttempt)).state == "expired"
        assert db.scalar(select(MentorCeremony)).state == "expired"
        assert db.scalar(select(MentorProviderResult)).state == "expired"
        assert db.scalar(select(MentorInvitation)).state == "expired"
        assert db.scalar(select(TutorProfileOwnershipProof)).state == "expired"
        assert db.scalar(select(MentorSubjectConsent)).status == "expired"
        assert all(
            row.deleted_at is None
            for model in (
                MentorBootstrapAttempt,
                MentorCeremony,
                MentorProviderResult,
                MentorInvitation,
                TutorProfileOwnershipProof,
                MentorSubjectConsent,
            )
            for row in db.scalars(select(model))
        )


def test_domain_expired_before_cutoff_is_materialized_and_severed_same_run(
    retention_ctx,
) -> None:
    """A late worker never restarts the configured retention window at now."""

    client, factory = retention_ctx
    ids = _seed_graph(factory)
    assert _initiate(client, ids["bootstrap"]).status_code == 202
    assert _verify_and_exchange(client, factory, ids).status_code == 201
    old = datetime.now(timezone.utc) - timedelta(days=40)
    with factory() as db:
        for row in db.scalars(select(MentorBootstrapAttempt)):
            row.consumed_at = old
            row.updated_at = old
        for row in db.scalars(select(MentorInvitation)):
            row.expires_at = old
            row.accepted_at = old
            row.terminal_at = None
            row.updated_at = old
        for row in db.scalars(select(TutorProfileOwnershipProof)):
            row.issued_at = old - timedelta(minutes=1)
            row.expires_at = old
            row.revoked_at = None
            row.updated_at = old
        for row in db.scalars(select(MentorCeremony)):
            row.expires_at = old
            row.terminal_at = old
            row.updated_at = old
        for row in db.scalars(select(MentorProviderResult)):
            row.issued_at = old - timedelta(minutes=1)
            row.expires_at = old
            row.consumed_at = old
            row.updated_at = old
        for row in db.scalars(select(MentorSubjectConsent)):
            row.expires_at = old
            row.revoked_at = None
            row.updated_at = old
        for row in db.scalars(select(MentorEngagement)):
            row.terminal_at = None
            row.updated_at = old
        for row in db.scalars(select(MentorConsent)):
            row.revoked_at = None
            row.updated_at = old
        for row in db.scalars(select(MentorSession)):
            row.issued_at = old - timedelta(hours=2)
            row.expires_at = old
            row.last_seen_at = old - timedelta(minutes=31)
            row.terminal_at = None
            row.updated_at = old
        for row in db.scalars(select(MentorIdempotencyRecord)):
            row.updated_at = old
        for row in db.scalars(select(MentorAuditLink)):
            row.expires_at = old
        db.commit()

    with factory() as db:
        counts = mentor_ceremony.run_mentor_retention(
            db,
            now=datetime.now(timezone.utc),
            batch_size=settings.mentor_retention_batch_size,
        )
    assert counts["materialized_expirations"] >= 6
    assert counts["severed_graphs"] == 1
    with factory() as db:
        assert all(
            row.deleted_at is not None
            for model in MENTOR_GRAPH_MODELS
            if hasattr(model, "deleted_at")
            for row in db.scalars(select(model))
        )


def test_post_window_orphan_bootstrap_and_preproof_graph_are_fully_severed(
    retention_ctx,
) -> None:
    """Orphaned pre-authority secrets cannot evade the domain candidate scan."""

    client, factory = retention_ctx
    ids = _seed_graph(factory)
    assert _initiate(client, ids["bootstrap"]).status_code == 202
    old = datetime.now(timezone.utc) - timedelta(days=40)

    with factory() as db:
        linked_bootstrap = db.scalar(
            select(MentorBootstrapAttempt).where(
                MentorBootstrapAttempt.state == "consumed"
            )
        )
        ceremony = db.scalar(select(MentorCeremony))
        provider = db.scalar(select(MentorProviderResult))
        record = db.scalar(select(MentorIdempotencyRecord))
        invitation = db.get(MentorInvitation, ids["invitation"])
        proof = db.get(TutorProfileOwnershipProof, ids["proof"])
        subject_consent = db.scalar(select(MentorSubjectConsent))
        assert all(
            row is not None
            for row in (
                linked_bootstrap,
                ceremony,
                provider,
                record,
                invitation,
                proof,
                subject_consent,
            )
        )
        unused_bootstrap = MentorBootstrapAttempt(
            token_hash=keyed_hash("unused-orphan-bootstrap-token"),
            requested_role="tutor",
            purpose_code="student_guidance",
            state="active",
            expires_at=old - timedelta(minutes=1),
            consumed_at=None,
        )
        db.add(unused_bootstrap)
        linked_bootstrap.consumed_at = old
        linked_bootstrap.updated_at = old
        ceremony.expires_at = old
        ceremony.updated_at = old
        provider.expires_at = old
        provider.updated_at = old
        proof.expires_at = old
        record.updated_at = old
        db.commit()
        linked_bootstrap_id = linked_bootstrap.id
        unused_bootstrap_id = unused_bootstrap.id
        ceremony_id = ceremony.id
        provider_id = provider.id
        record_id = record.id
        old_bootstrap_hashes = {
            linked_bootstrap.token_hash,
            unused_bootstrap.token_hash,
        }
        old_provider_digests = {
            provider.issuer_hash,
            provider.audience_hash,
            provider.nonce_hash,
            provider.correlation_hash,
        }
        assert ceremony.actor_user_id is None
        assert ceremony.invitation_id is None

    with factory() as db:
        counts = mentor_ceremony.run_mentor_retention(
            db,
            now=datetime.now(timezone.utc),
            batch_size=settings.mentor_retention_batch_size,
        )
    assert counts["severed_graphs"] == 3
    assert counts["blocked_graphs"] == 0
    assert counts["materialized_expirations"] == 4
    assert counts["bootstraps"] == 2
    assert counts["ceremonies"] == 1
    assert counts["provider_results"] == 1
    assert counts["proofs"] == 1
    assert counts["idempotency"] == 1

    with factory() as db:
        linked_bootstrap = db.get(MentorBootstrapAttempt, linked_bootstrap_id)
        unused_bootstrap = db.get(MentorBootstrapAttempt, unused_bootstrap_id)
        ceremony = db.get(MentorCeremony, ceremony_id)
        provider = db.get(MentorProviderResult, provider_id)
        record = db.get(MentorIdempotencyRecord, record_id)
        assert all(
            row is not None
            for row in (
                linked_bootstrap,
                unused_bootstrap,
                ceremony,
                provider,
                record,
            )
        )
        assert all(
            row.deleted_at is not None
            and row.token_hash not in old_bootstrap_hashes
            for row in (linked_bootstrap, unused_bootstrap)
        )
        assert ceremony.deleted_at is not None
        assert ceremony.bootstrap_attempt_id is None
        assert ceremony.token_seed_ct is None
        assert ceremony.token_seed_key_version is None
        assert provider.deleted_at is not None
        assert provider.ceremony_id is None
        assert provider.nonce_ct is None and provider.correlation_ct is None
        assert provider.transaction_key_version is None
        assert old_provider_digests.isdisjoint(
            {
                provider.issuer_hash,
                provider.audience_hash,
                provider.nonce_hash,
                provider.correlation_hash,
            }
        )
        assert record.state == "erased"
        assert record.outcome_ct is None and record.key_version is None
        # The still-live invitation/subject consent were never connected to
        # the pre-proof ceremony and remain linked.  The independently elapsed,
        # never-used proof is severed only after its own authoritative cutoff.
        invitation = db.get(MentorInvitation, ids["invitation"])
        proof = db.get(TutorProfileOwnershipProof, ids["proof"])
        subject_consent = db.scalar(select(MentorSubjectConsent))
        assert invitation is not None and invitation.deleted_at is None
        assert invitation.subject_registration_id is not None
        assert proof is not None and proof.deleted_at is not None
        assert proof.user_id is None and proof.tutor_profile_id is None
        assert proof.provider_subject_hash != keyed_hash(
            "synthetic-provider-subject"
        )
        assert proof.evidence_digest != "a" * 64
        assert subject_consent is not None and subject_consent.deleted_at is None
        assert subject_consent.invitation_id == invitation.id


def test_referenced_current_proof_is_not_selected_as_standalone_retention(
    retention_ctx,
) -> None:
    """A live ceremony/session reference always protects the current proof."""

    client, factory = retention_ctx
    ids = _seed_graph(factory)
    assert _initiate(client, ids["bootstrap"]).status_code == 202
    assert _verify_and_exchange(client, factory, ids).status_code == 201
    with factory() as db:
        proof = db.get(TutorProfileOwnershipProof, ids["proof"])
        assert proof is not None
        before = {
            column.name: getattr(proof, column.name)
            for column in TutorProfileOwnershipProof.__table__.columns
        }

    with factory() as db:
        counts = mentor_ceremony.run_mentor_retention(
            db,
            now=datetime.now(timezone.utc),
            batch_size=settings.mentor_retention_batch_size,
        )
    assert counts["proofs"] == 0
    assert counts["severed_graphs"] == 0
    with factory() as db:
        proof = db.get(TutorProfileOwnershipProof, ids["proof"])
        assert proof is not None
        assert {
            column.name: getattr(proof, column.name)
            for column in TutorProfileOwnershipProof.__table__.columns
        } == before


def test_0023_is_schema_only_and_cannot_execute_live_retention() -> None:
    repository = Path(__file__).resolve().parents[2]
    migration = repository / (
        "backend/app/db/migrations/versions/0023_nyay22_mentor_ceremony.py"
    )
    source = migration.read_text(encoding="utf-8")
    assert "mentor_retention_blocked_graphs" in source
    for forbidden in (
        "create_engine(",
        "Session(",
        "run_mentor_retention(",
        "DATABASE_URL",
        "op.execute(",
    ):
        assert forbidden not in source
    assert "def upgrade()" in source and "def downgrade()" in source
    tree = ast.parse(source)
    assert {
        node.name for node in tree.body if isinstance(node, ast.FunctionDef)
    } >= {"upgrade", "downgrade"}


def test_every_nyay19_subject_erasure_entry_prelocks_mentor_authority() -> None:
    """Mentor actor/domain locks must precede legacy registration row locks."""

    from app.api.v1 import student_settings
    from app.core import retention

    for entrypoint in (
        retention.anonymise_registration,
        retention.delete_registration,
    ):
        source = pyinspect.getsource(entrypoint)
        assert source.index("_prelock_subject_mentor_erasure(") < source.index(
            "lock_registration_with_idempotency("
        )

    for locked in (retention._anonymise_locked, retention._delete_locked):
        source = pyinspect.getsource(locked)
        assert source.index(
            "validate_subject_mentor_erasure_boundary("
        ) < source.index("terminalize_registration_idempotency(")
        assert "_lock_authority_scope(" not in source

    privacy = pyinspect.getsource(student_settings.privacy_delete)
    assert privacy.index(
        "lock_subject_mentor_erasure_boundary("
    ) < privacy.index("lock_registration_with_idempotency(")
    assert privacy.index(
        "retire_subject_mentor_authority_for_privacy_request("
    ) < privacy.index("_create_dsr(")

    purge_security = pyinspect.getsource(retention.purge_otp_security_state)
    assert purge_security.index(
        "_prelock_subject_mentor_erasure("
    ) < purge_security.index("select(RegistrationIdempotencyRecord)")
    purge_challenge = pyinspect.getsource(retention._purge_expired_challenge)
    assert purge_challenge.index(
        "_prelock_subject_mentor_erasure("
    ) < purge_challenge.index("select(RegistrationIdempotencyRecord.id)")
