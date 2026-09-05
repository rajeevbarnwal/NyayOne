"""Fail-closed NYAY-19 registration erasure integration for mentor graphs.

These contracts deliberately exercise the public NYAY-19 retention entrypoint,
not a test-only deletion shortcut.  Registration mutation is authorized only
by the one-shot approval minted after a complete, cutoff-bound mentor graph was
atomically severed and proved to have zero remaining joins.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from fastapi import HTTPException, Request, Response
from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

from app.core import retention
from app.models.mentor_auth import (
    MentorEngagement,
    MentorInvitation,
    MentorRetentionBlockedGraph,
    MentorSession,
    MentorSubjectConsent,
)
from app.models.registration import StudentRegistration
from app.services import mentor_ceremony
from scripts import nyay22_postgres_mentor_gate as native
from tests import dbtemplate


@pytest.fixture()
def erasure_ctx(engine):
    dbtemplate.reset_to_empty_schema(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False, class_=Session)
    return native._app(factory), factory


def _registration_snapshot(factory, registration_id):
    with factory() as db:
        row = db.get(StudentRegistration, registration_id)
        if row is None:
            return None
        return tuple(
            (column.name, repr(getattr(row, column.name)))
            for column in StudentRegistration.__table__.columns
        )


def _require_guarded_issuer() -> None:
    assert hasattr(
        mentor_ceremony, "prepare_subject_mentor_registration_erasure"
    ), "cutoff-bound subject erasure approval issuer is missing"


def test_privacy_delete_over_cap_does_not_consume_recovery_proof(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The alert-only path executes before the one-shot OTP proof consumer."""

    from types import SimpleNamespace

    from app.api.v1 import student_settings

    registration = SimpleNamespace(id=object())
    boundary = object()

    class FakeSession:
        commits = 0
        rollbacks = 0

        def commit(self) -> None:
            self.commits += 1

        def rollback(self) -> None:
            self.rollbacks += 1

    session = FakeSession()
    consumed = 0

    monkeypatch.setattr(
        student_settings,
        "_registration_for",
        lambda _session, _actor: registration,
    )
    monkeypatch.setattr(
        mentor_ceremony,
        "lock_subject_mentor_erasure_boundary",
        lambda _session, _registration_id: boundary,
    )
    monkeypatch.setattr(
        student_settings.registration_service,
        "lock_registration_with_idempotency",
        lambda _session, _registration_id: (registration, None),
    )
    monkeypatch.setattr(
        mentor_ceremony,
        "preflight_subject_mentor_authority_for_privacy_request",
        lambda *_args, **_kwargs: False,
    )

    def consume(*_args, **_kwargs) -> None:
        nonlocal consumed
        consumed += 1

    monkeypatch.setattr(
        student_settings.otp_flow_service, "consume_recovery_proof", consume
    )

    with pytest.raises(HTTPException) as caught:
        student_settings.privacy_delete(
            student_settings.DeleteRequestIn(confirmation="DELETE"),
            Request({"type": "http", "headers": []}),
            Response(),
            actor=SimpleNamespace(),
            _=None,
            session=session,
            idempotency_key=None,
        )
    assert caught.value.status_code == 409
    assert caught.value.detail == {"code": "concurrent_state_changed"}
    assert session.commits == 1 and session.rollbacks == 0
    assert consumed == 0


@pytest.mark.parametrize("mode", ("anonymise", "delete"))
def test_terminal_beyond_cutoff_graph_severs_before_registration_anonymise(
    erasure_ctx, monkeypatch: pytest.MonkeyPatch, mode: str
) -> None:
    """A <=256 closed graph must reach zero joins before owner PII mutates."""

    _require_guarded_issuer()
    app, factory = erasure_ctx
    context = native._terminal_authority_graph(app, factory)
    registration_id = context["external_ids"][1]
    monkeypatch.setattr(mentor_ceremony, "_now", lambda: context["current"])

    with factory() as db:
        registration = db.get(StudentRegistration, registration_id)
        assert registration is not None
        if mode == "anonymise":
            retention.anonymise_registration(db, registration)
        else:
            retention.delete_registration(db, registration)
        db.commit()

    assert native._retention_graph_is_fully_severed(factory, context)
    with factory() as db:
        registration = db.get(StudentRegistration, registration_id)
        if mode == "anonymise":
            assert registration is not None
            assert registration.status == "deleted"
        else:
            assert registration is None


def test_mid_severance_failure_rolls_back_graph_and_registration(
    erasure_ctx, monkeypatch: pytest.MonkeyPatch
) -> None:
    """No tombstone failure may leave a severed subset or changed subject."""

    _require_guarded_issuer()
    app, factory = erasure_ctx
    context = native._terminal_authority_graph(app, factory)
    registration_id = context["external_ids"][1]
    graph_before = native._retention_snapshot(factory, context)
    registration_before = _registration_snapshot(factory, registration_id)
    real_tombstone = mentor_ceremony._retention_tombstone
    calls = 0

    def fail_mid_graph(label: str) -> str:
        nonlocal calls
        calls += 1
        if calls == 7:
            raise RuntimeError("privacy-safe injected erasure failure")
        return real_tombstone(label)

    monkeypatch.setattr(mentor_ceremony, "_now", lambda: context["current"])
    monkeypatch.setattr(mentor_ceremony, "_retention_tombstone", fail_mid_graph)
    with factory() as db:
        registration = db.get(StudentRegistration, registration_id)
        assert registration is not None
        with pytest.raises(RuntimeError, match="privacy-safe injected"):
            retention.anonymise_registration(db, registration)
            db.flush()
        db.rollback()

    assert native._retention_snapshot(factory, context) == graph_before
    assert _registration_snapshot(factory, registration_id) == registration_before


def test_live_or_young_graph_and_registration_are_both_deferred_bit_identically(
    erasure_ctx, monkeypatch: pytest.MonkeyPatch
) -> None:
    """No graph mutation occurs before every node is terminal and old enough."""

    _require_guarded_issuer()
    app, factory = erasure_ctx
    client, seeded = native._ready_session(app, factory, "young-subject-erasure")
    with factory() as db:
        live = db.scalar(
            select(MentorSession).where(
                MentorSession.actor_user_id == seeded["mentor"]
            )
        )
        assert live is not None
        domain = live.authority_domain_hash
        graph = mentor_ceremony._load_authority_domain_graph(db, domain)
        context = {
            "ids": {name: [row.id for row in rows] for name, rows in graph.items()}
        }
    graph_before = native._retention_snapshot(factory, context)
    registration_before = _registration_snapshot(factory, seeded["registration"])
    boundary_now = datetime.now(timezone.utc)
    monkeypatch.setattr(mentor_ceremony, "_now", lambda: boundary_now)

    with factory() as db:
        registration = db.get(StudentRegistration, seeded["registration"])
        assert registration is not None
        retention.anonymise_registration(db, registration)
        db.commit()

    assert _registration_snapshot(factory, seeded["registration"]) == registration_before
    assert native._retention_snapshot(factory, context) == graph_before
    still_live = client.get("/api/v1/auth/mentor/session")
    client.close()
    assert still_live.status_code == 200


def test_global_multi_domain_oversize_blocks_without_partial_mutation(
    erasure_ctx, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A subject graph >256 across domains is registered, never partly erased."""

    _require_guarded_issuer()
    app, factory = erasure_ctx
    first = native._terminal_authority_graph(app, factory, oversize_sessions=120)
    second = native._terminal_authority_graph(app, factory, oversize_sessions=120)
    registration_id = first["external_ids"][1]
    registration_before = _registration_snapshot(factory, registration_id)
    with factory() as db:
        for row in db.scalars(
            select(MentorInvitation).where(
                MentorInvitation.id.in_(second["ids"]["invitations"])
            )
        ):
            row.subject_registration_id = registration_id
        for row in db.scalars(
            select(MentorSubjectConsent).where(
                MentorSubjectConsent.id.in_(second["ids"]["subject_consents"])
            )
        ):
            row.subject_registration_id = registration_id
        for row in db.scalars(
            select(MentorEngagement).where(
                MentorEngagement.id.in_(second["ids"]["engagements"])
            )
        ):
            row.subject_registration_id = registration_id
        db.commit()

    first_before = native._retention_snapshot(factory, first)
    second_before = native._retention_snapshot(factory, second)
    current = max(first["current"], second["current"])
    monkeypatch.setattr(mentor_ceremony, "_now", lambda: current)
    with factory() as db:
        registration = db.get(StudentRegistration, registration_id)
        assert registration is not None
        retention.anonymise_registration(db, registration)
        db.commit()

    assert native._retention_snapshot(factory, first) == first_before
    assert native._retention_snapshot(factory, second) == second_before
    assert _registration_snapshot(factory, registration_id) == registration_before
    with factory() as db:
        alerts = list(db.scalars(select(MentorRetentionBlockedGraph)))
        assert len(alerts) == 1
        assert alerts[0].reason_code == "GRAPH_EXCEEDS_HARD_CAP"
        assert alerts[0].observed_row_count > 256
        assert alerts[0].review_queue == "nyay19_retention_review"
        assert db.scalar(
            select(func.count()).select_from(MentorSession).where(
                MentorSession.id.in_(
                    first["ids"]["sessions"] + second["ids"]["sessions"]
                ),
                MentorSession.deleted_at.is_(None),
            )
        ) == len(first["ids"]["sessions"] + second["ids"]["sessions"])

    # A retry against the exact same blocked graph updates one durable review
    # register row.  Observation time is not part of the graph identity.
    monkeypatch.setattr(
        mentor_ceremony,
        "_now",
        lambda: current + timedelta(microseconds=1),
    )
    with factory() as db:
        registration = db.get(StudentRegistration, registration_id)
        assert registration is not None
        retention.anonymise_registration(db, registration)
        db.commit()
    with factory() as db:
        alerts = list(db.scalars(select(MentorRetentionBlockedGraph)))
        assert len(alerts) == 1
        assert alerts[0].occurrence_count == 2


def test_elapsed_live_oversize_retention_blocks_before_materialization(
    erasure_ctx,
) -> None:
    """The 256-row cap is evaluated before an elapsed row is mutated."""

    app, factory = erasure_ctx
    context = native._terminal_authority_graph(
        app,
        factory,
        # One canonical session + 256 extras = 257 rows in this table alone,
        # strictly above the global 256-row hard cap without overflowing the
        # loader's 257-row cap-detection inventory.
        oversize_sessions=256,
        live_expired_session=True,
    )
    before = native._retention_snapshot(factory, context)
    with factory() as db:
        counts = mentor_ceremony.run_mentor_retention(
            db,
            now=context["current"],
            batch_size=min(
                256, mentor_ceremony.settings.mentor_retention_batch_size
            ),
        )

    assert counts["materialized_expirations"] == 0
    assert counts["severed_graphs"] == 0
    assert counts["blocked_graphs"] == 1
    assert native._retention_snapshot(factory, context) == before
    with factory() as db:
        alert = db.scalar(select(MentorRetentionBlockedGraph))
        assert alert is not None
        assert alert.reason_code == "GRAPH_EXCEEDS_HARD_CAP"
        assert alert.review_queue == "nyay19_retention_review"
