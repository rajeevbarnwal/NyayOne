"""Wave 5 calendar HTTP, persistence, privacy and negative-boundary proof."""
from __future__ import annotations

import json
import uuid
from datetime import date, datetime, timedelta, timezone

import pytest
from sqlalchemy import create_engine, func, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

import app.models  # noqa: F401
from app.core.crypto import keyed_hash
from app.core.auth import ActorContext, Role
from app.core.config import ConfigurationError, Settings
from app.core.middleware import redact_sensitive_path
from app.db.models.audit import AuditEvent
from app.db.session import get_session
from app.models.calendar import (
    CalendarConflict,
    CalendarEvent,
    CalendarEventSource,
    CalendarExportRevocation,
    CalendarExportSubscription,
    CalendarExportToken,
    CalendarReminderPreference,
)
from app.models.credentials import Credential, CredentialReminderJob
from app.models.registration import User
from app.models.wave2 import TutorAvailabilitySlot, TutorProfile, TutoringSession
from app.schemas.calendar import EventCreate
from app.services import calendar_service
from scripts.wave5_postgres_gate import is_isolated_gate_target
from tests import apptemplate, dbtemplate


def _claims(user_id: uuid.UUID) -> dict[str, str]:
    return {"X-Actor-Claims": json.dumps({"sub": str(user_id), "roles": ["student"]})}


def test_postgres_gate_requires_loopback_qa_target_test_env_and_opt_in():
    safe = "postgresql+psycopg://user:secret@127.0.0.1:5432/legalsaathi_wave5_qa"
    assert is_isolated_gate_target(safe, "testing", True)
    assert not is_isolated_gate_target(safe, "production", True)
    assert not is_isolated_gate_target(safe, "testing", False)
    assert not is_isolated_gate_target(
        "postgresql+psycopg://user:secret@db.internal:5432/legalsaathi_wave5_qa",
        "testing",
        True,
    )
    assert not is_isolated_gate_target(
        "postgresql+psycopg://user:secret@127.0.0.1:5432/legalsaathi",
        "testing",
        True,
    )


def test_calendar_public_origin_is_loopback_only_in_local_or_test_environments():
    assert Settings(
        _env_file=None,
        app_env="development",
        calendar_public_base_url="https://127.0.0.1:1030",
    ).calendar_public_base_url == "https://127.0.0.1:1030"
    with pytest.raises(ConfigurationError, match="calendar_public_base_url"):
        Settings(
            _env_file=None,
            app_env="preview",
            calendar_public_base_url="https://localhost:1030",
        )
    configured = Settings(
        _env_file=None,
        app_env="preview",
        calendar_public_base_url="https://calendar.example.test",
    )
    assert configured.calendar_public_base_url == "https://calendar.example.test"


@pytest.fixture(scope="module")
def _mounted():
    return apptemplate.mounted_app(exception_handlers=True, raise_server_exceptions=False)


@pytest.fixture()
def ctx(_mounted):
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    dbtemplate.create_all(engine)
    SessionLocal = sessionmaker(bind=engine, expire_on_commit=False, class_=Session)

    def request_session():
        with SessionLocal() as session:
            try:
                yield session
            finally:
                session.rollback()

    app, client = _mounted
    apptemplate.fresh(app, client)
    app.dependency_overrides[get_session] = request_session
    with SessionLocal() as session:
        first = User(role="student", status="active")
        second = User(role="student", status="active")
        session.add_all([first, second])
        session.commit()
        ids = (first.id, second.id)
    yield client, SessionLocal, ids
    app.dependency_overrides.clear()
    engine.dispose()


def _event_body(
    *,
    title: str = "Moot court preparation",
    start: str = "2026-08-10T04:30:00Z",
    end: str = "2026-08-10T05:30:00Z",
    timezone_name: str = "Asia/Kolkata",
    privacy: str = "personal",
    event_kind: str = "reminder",
) -> dict[str, object]:
    return {
        "title": title,
        "starts_at": start,
        "ends_at": end,
        "timezone": timezone_name,
        "status": "scheduled",
        "privacy_classification": privacy,
        "event_kind": event_kind,
    }


def _create(client, user_id: uuid.UUID, key: str, **kwargs):
    return client.post(
        "/api/v1/calendar/events",
        json=_event_body(**kwargs),
        headers={**_claims(user_id), "Idempotency-Key": key},
    )


def _seed_tutoring(
    SessionLocal,
    owner: uuid.UUID,
    *,
    status: str = "confirmed",
    start: datetime | None = None,
) -> uuid.UUID:
    starts_at = start or datetime(2026, 8, 20, 4, 30, tzinfo=timezone.utc)
    with SessionLocal() as session:
        tutor_user = User(role="student", status="active")
        session.add(tutor_user)
        session.flush()
        tutor = TutorProfile(
            user_id=tutor_user.id,
            display_name="Calendar test tutor",
            status="active",
        )
        session.add(tutor)
        session.flush()
        slot = TutorAvailabilitySlot(
            tutor_id=tutor.id,
            start_utc=starts_at,
            end_utc=starts_at + timedelta(hours=1),
            iana_timezone="Asia/Kolkata",
            status="booked",
        )
        session.add(slot)
        session.flush()
        tutoring = TutoringSession(
            slot_id=slot.id,
            tutor_id=tutor.id,
            student_user_id=owner,
            start_utc=starts_at,
            end_utc=starts_at + timedelta(hours=1),
            iana_timezone="Asia/Kolkata",
            status=status,
        )
        session.add(tutoring)
        session.commit()
        return tutoring.id


def test_authentication_and_strict_event_boundaries(ctx):
    client, _, (user_id, _) = ctx
    assert client.get("/api/v1/calendar/events").status_code == 401
    assert _create(client, user_id, "event-title-max-0001", title="A" * 160).status_code == 201
    assert _create(client, user_id, "event-title-over-001", title="A" * 161).status_code == 422
    assert _create(client, user_id, "event-title-control1", title="Court\u0007 hearing").status_code == 422
    assert _create(
        client,
        user_id,
        "event-zero-duration",
        start="2026-08-10T10:00:00+05:30",
        end="2026-08-10T10:00:00+05:30",
    ).status_code == 422


@pytest.mark.parametrize(
    ("start", "end", "zone", "valid"),
    [
        ("2026-08-10T10:00:00+05:30", "2026-08-10T11:00:00+05:30", "Asia/Kolkata", True),
        # Production frontend wire format: canonical UTC instant plus retained
        # display timezone.
        ("2026-08-10T04:30:00Z", "2026-08-10T05:30:00Z", "Asia/Kolkata", True),
        ("2026-08-10T04:30:00+00:00", "2026-08-10T05:30:00+00:00", "UTC", True),
        # Canonical UTC is an instant; the frontend wall-clock converter owns
        # nonexistent-time rejection before producing this wire value.
        ("2026-03-29T01:30:00Z", "2026-03-29T02:30:00Z", "Europe/London", True),
        ("2026-08-10T10:00:00+04:00", "2026-08-10T11:00:00+04:00", "Asia/Kolkata", False),
        # Both fall-back folds are explicit and valid instants.
        ("2026-10-25T01:10:00+01:00", "2026-10-25T01:40:00+01:00", "Europe/London", True),
        ("2026-10-25T01:10:00+00:00", "2026-10-25T01:40:00+00:00", "Europe/London", True),
    ],
)
def test_timezone_offset_and_dst_contract(start, end, zone, valid):
    payload = _event_body(start=start, end=end, timezone_name=zone)
    if valid:
        assert EventCreate.model_validate(payload)
    else:
        with pytest.raises(ValueError):
            EventCreate.model_validate(payload)


def test_event_crud_idempotency_stale_version_and_non_enumeration(ctx):
    client, _, (owner, other) = ctx
    first = _create(client, owner, "event-crud-idem-0001")
    assert first.status_code == 201
    event = first.json()
    assert event["event_kind"] == "reminder" and "source_id" not in event
    replay = _create(client, owner, "event-crud-idem-0001")
    assert replay.status_code == 201 and replay.json()["id"] == event["id"]
    mismatch = _create(client, owner, "event-crud-idem-0001", title="Different")
    assert mismatch.status_code == 409 and mismatch.json()["detail"]["code"] == "idempotency_conflict"
    assert client.get(f"/api/v1/calendar/events/{event['id']}", headers=_claims(other)).status_code == 404

    update = {**_event_body(title="Updated study block", event_kind="study"), "expected_version": 1}
    changed = client.put(f"/api/v1/calendar/events/{event['id']}", json=update, headers=_claims(owner))
    assert changed.status_code == 200
    assert changed.json()["title"] == "Updated study block" and changed.json()["event_kind"] == "study" and changed.json()["version"] == 2
    stale = client.put(f"/api/v1/calendar/events/{event['id']}", json=update, headers=_claims(owner))
    assert stale.status_code == 409 and stale.json()["detail"]["current_version"] == 2
    assert client.delete(f"/api/v1/calendar/events/{event['id']}", headers=_claims(owner)).status_code == 204
    # Repeat and cross-user delete are indistinguishable, by explicit policy.
    assert client.delete(f"/api/v1/calendar/events/{event['id']}", headers=_claims(owner)).status_code == 404
    assert client.delete(f"/api/v1/calendar/events/{event['id']}", headers=_claims(other)).status_code == 404


def test_view_and_reminder_defaults_save_refresh_and_stale_version(ctx):
    client, SessionLocal, (owner, _) = ctx
    view = client.get("/api/v1/calendar/view-preferences", headers=_claims(owner)).json()
    assert view["version"] == 0 and len(view["source_types"]) == 7
    missing_view_version = client.put(
        "/api/v1/calendar/view-preferences",
        headers=_claims(owner),
        json={
            "view_mode": "week",
            "source_types": ["exam"],
            "timezone": "Asia/Kolkata",
        },
    )
    assert missing_view_version.status_code == 422
    saved = client.put(
        "/api/v1/calendar/view-preferences",
        headers=_claims(owner),
        json={
            "view_mode": "week",
            "source_types": ["exam", "moot"],
            "from_date": "2026-08-01",
            "to_date": "2026-08-31",
            "timezone": "Asia/Kolkata",
            "expected_version": 0,
        },
    )
    assert saved.status_code == 200 and saved.json()["version"] == 1
    stale = client.put(
        "/api/v1/calendar/view-preferences",
        headers=_claims(owner),
        json={**saved.json(), "source_types": ["exam"], "expected_version": 0},
    )
    assert stale.status_code == 409

    defaults = client.get("/api/v1/calendar/reminder-preferences", headers=_claims(owner)).json()["items"]
    assert len(defaults) == 7
    assert all(item["version"] == 0 and item["lead_minutes"] == 30 for item in defaults)
    pref = defaults[0]
    missing_reminder_version = client.put(
        "/api/v1/calendar/reminder-preferences",
        headers=_claims(owner),
        json={
            "source_type": pref["source_type"],
            "channel": "in_app",
            "enabled": False,
            "lead_minutes": 60,
            "quiet_start_min": 1260,
            "quiet_end_min": 480,
            "timezone": "Asia/Kolkata",
        },
    )
    assert missing_reminder_version.status_code == 422
    reminder_payload = {
        "source_type": pref["source_type"],
        "channel": "in_app",
        "enabled": False,
        "lead_minutes": 60,
        "quiet_start_min": 1260,
        "quiet_end_min": 480,
        "timezone": "Asia/Kolkata",
        "expected_version": 0,
    }
    updated = client.put(
        "/api/v1/calendar/reminder-preferences",
        headers=_claims(owner),
        json=reminder_payload,
    )
    assert updated.status_code == 200 and updated.json()["version"] == 1
    with SessionLocal() as session:
        audit_before_retry = session.scalar(
            select(func.count()).select_from(AuditEvent).where(
                AuditEvent.actor_user_id == owner,
                AuditEvent.action == "calendar_reminder_preference_updated",
            )
        )
    identical_retry = client.put(
        "/api/v1/calendar/reminder-preferences",
        headers=_claims(owner),
        json={**reminder_payload, "expected_version": 1},
    )
    assert identical_retry.status_code == 200 and identical_retry.json()["version"] == 1
    with SessionLocal() as session:
        audit_after_retry = session.scalar(
            select(func.count()).select_from(AuditEvent).where(
                AuditEvent.actor_user_id == owner,
                AuditEvent.action == "calendar_reminder_preference_updated",
            )
        )
    assert audit_after_retry == audit_before_retry
    stale_retry = client.put(
        "/api/v1/calendar/reminder-preferences",
        headers=_claims(owner),
        json=reminder_payload,
    )
    assert stale_retry.status_code == 409
    assert stale_retry.json()["detail"] == {
        "code": "calendar_stale_version",
        "message": "Reminder preference changed",
        "current_version": 1,
    }
    disabled_preview = client.post(
        "/api/v1/calendar/reminder-preferences/preview",
        headers=_claims(owner),
        json={"source_type": pref["source_type"], "channel": "in_app"},
    )
    assert disabled_preview.status_code == 200
    assert disabled_preview.json() == {
        "source_type": pref["source_type"],
        "channel": "in_app",
        "scheduling_eligible": False,
        "reason_code": "disabled",
        "preview": None,
        "lead_minutes": 60,
        "timezone": "Asia/Kolkata",
    }
    reenabled = client.put(
        "/api/v1/calendar/reminder-preferences",
        headers=_claims(owner),
        json={**reminder_payload, "enabled": True, "expected_version": 1},
    )
    assert reenabled.status_code == 200 and reenabled.json()["version"] == 2
    enabled_preview = client.post(
        "/api/v1/calendar/reminder-preferences/preview",
        headers=_claims(owner),
        json={"source_type": pref["source_type"], "channel": "in_app"},
    )
    assert enabled_preview.status_code == 200
    assert enabled_preview.json()["scheduling_eligible"] is True
    assert enabled_preview.json()["reason_code"] == "eligible"
    assert enabled_preview.json()["preview"] == "An upcoming LegalSaathi event has a reminder."
    assert all(
        marker not in json.dumps(enabled_preview.json())
        for marker in ("9876543210", "student@example.com", "ENROL-PRIVATE")
    )
    refreshed = client.get("/api/v1/calendar/reminder-preferences", headers=_claims(owner)).json()["items"]
    assert len(refreshed) == 7
    assert next(item for item in refreshed if item["source_type"] == pref["source_type"])["enabled"] is True


def test_half_open_conflicts_dismiss_and_preserve_status(ctx):
    client, _, (owner, _) = ctx
    a = _create(client, owner, "event-conflict-left", start="2026-08-12T10:00:00+05:30", end="2026-08-12T11:00:00+05:30").json()
    adjacent = _create(client, owner, "event-conflict-adj", start="2026-08-12T11:00:00+05:30", end="2026-08-12T12:00:00+05:30").json()
    overlap = _create(client, owner, "event-conflict-over", start="2026-08-12T10:30:00+05:30", end="2026-08-12T11:30:00+05:30").json()
    checked = client.post(
        "/api/v1/calendar/conflicts/check",
        headers=_claims(owner),
        json={"event_ids": [a["id"], adjacent["id"], overlap["id"]], "persist": True},
    )
    assert checked.status_code == 200 and checked.json()["total"] == 2
    conflict = checked.json()["items"][0]
    dismissed = client.patch(
        f"/api/v1/calendar/conflicts/{conflict['id']}",
        headers=_claims(owner),
        json={"status": "dismissed", "expected_version": conflict["version"]},
    )
    assert dismissed.status_code == 200 and dismissed.json()["status"] == "dismissed"
    recheck = client.post(
        "/api/v1/calendar/conflicts/check",
        headers=_claims(owner),
        json={"event_ids": [conflict["left_event_id"], conflict["right_event_id"]], "persist": True},
    )
    assert recheck.status_code == 200 and recheck.json()["items"][0]["status"] == "dismissed"


def test_two_real_module_adapters_materialise_tutoring_and_credential_reminder(ctx):
    client, SessionLocal, (owner, _) = ctx
    start = datetime(2026, 8, 15, 4, 30, tzinfo=timezone.utc)
    with SessionLocal() as session:
        tutor_user = User(role="student", status="active")
        session.add(tutor_user); session.flush()
        tutor = TutorProfile(user_id=tutor_user.id, display_name="Calendar test tutor", status="active")
        session.add(tutor); session.flush()
        slot = TutorAvailabilitySlot(
            tutor_id=tutor.id,
            start_utc=start,
            end_utc=start + timedelta(hours=1),
            iana_timezone="Asia/Kolkata",
            status="booked",
        )
        session.add(slot); session.flush()
        tutoring = TutoringSession(
            slot_id=slot.id,
            tutor_id=tutor.id,
            student_user_id=owner,
            start_utc=start,
            end_utc=start + timedelta(hours=1),
            iana_timezone="Asia/Kolkata",
            status="cancelled",
        )
        completed_slot = TutorAvailabilitySlot(
            tutor_id=tutor.id,
            start_utc=start + timedelta(hours=2),
            end_utc=start + timedelta(hours=3),
            iana_timezone="Asia/Kolkata",
            status="booked",
        )
        session.add(completed_slot); session.flush()
        completed_tutoring = TutoringSession(
            slot_id=completed_slot.id,
            tutor_id=tutor.id,
            student_user_id=owner,
            start_utc=start + timedelta(hours=2),
            end_utc=start + timedelta(hours=3),
            iana_timezone="Asia/Kolkata",
            status="completed",
        )
        credential = Credential(
            owner_user_id=owner,
            title="Sensitive enrolment ENR-12345",
            credential_type="certificate",
            status="verified",
            issue_date=date(2025, 8, 1),
            expiry_date=date(2026, 9, 1),
            idempotency_key="calendar-adapter-credential",
        )
        session.add_all([tutoring, completed_tutoring, credential]); session.flush()
        reminder = CredentialReminderJob(
            credential_id=credential.id,
            days_before=30,
            remind_at=start + timedelta(days=1),
            status="cancelled",
        )
        sent_reminder = CredentialReminderJob(
            credential_id=credential.id,
            days_before=7,
            remind_at=start + timedelta(days=2),
            status="sent",
        )
        session.add_all([reminder, sent_reminder])
        session.commit()
        tutoring_ids = (tutoring.id, completed_tutoring.id)
        reminder_ids = (reminder.id, sent_reminder.id)

    response = client.get("/api/v1/calendar/events", headers=_claims(owner))
    assert response.status_code == 200 and response.json()["failed_sources"] == []
    imported = [item for item in response.json()["items"] if item["event_kind"] is None]
    assert {item["source_type"] for item in imported} == {"tutoring", "reminder"}
    assert {item["status"] for item in imported if item["source_type"] == "tutoring"} == {
        "cancelled",
        "done",
    }
    assert {item["status"] for item in imported if item["source_type"] == "reminder"} == {
        "cancelled",
        "done",
    }
    assert all("source_id" not in item and item["source_url"].startswith("/s-") for item in imported)
    assert all("ENR-12345" not in item["title"] for item in imported)
    target = imported[0]
    update = {**_event_body(title="Attempted overwrite"), "expected_version": target["version"]}
    blocked = client.put(f"/api/v1/calendar/events/{target['id']}", json=update, headers=_claims(owner))
    assert blocked.status_code == 409 and blocked.json()["detail"]["code"] == "calendar_event_read_only"

    export = client.post(
        "/api/v1/calendar/exports",
        headers={**_claims(owner), "Idempotency-Key": "adapter-export-before-delete"},
        json={"timezone": "Asia/Kolkata"},
    ).json()
    feed_before = client.get(export["feed_url"])
    assert feed_before.status_code == 200
    assert feed_before.text.count("STATUS:CANCELLED") == 2
    assert feed_before.text.count("STATUS:CONFIRMED") == 2

    deleted_at = datetime.now(timezone.utc)
    with SessionLocal() as session:
        for tutoring_id in tutoring_ids:
            session.get(TutoringSession, tutoring_id).deleted_at = deleted_at
        for reminder_id in reminder_ids:
            session.get(CredentialReminderJob, reminder_id).deleted_at = deleted_at
        session.commit()
    reconciled = client.get("/api/v1/calendar/events", headers=_claims(owner))
    assert reconciled.status_code == 200 and reconciled.json()["items"] == []
    with SessionLocal() as session:
        sources = list(session.scalars(select(CalendarEventSource).where(
            CalendarEventSource.owner_user_id == owner,
            CalendarEventSource.source_type.in_(("tutoring", "reminder")),
        )))
        imported_sources = [
            source for source in sources
            if source.source_type == "tutoring" or source.source_id.startswith("credential-reminder:")
        ]
        assert len(imported_sources) == 4
        assert all(source.deleted_at is not None for source in imported_sources)
        assert all(
            session.scalar(select(CalendarEvent).where(
                CalendarEvent.event_source_id == source.id
            )).deleted_at is not None
            for source in imported_sources
        )
    feed_after = client.get(export["feed_url"])
    assert feed_after.status_code == 200
    assert "BEGIN:VEVENT" not in feed_after.text


def test_source_sync_is_flush_only_and_authenticated_refresh_commits_once(ctx):
    _, SessionLocal, (owner, _) = ctx
    _seed_tutoring(SessionLocal, owner)
    with SessionLocal() as session:
        commits: list[bool] = []
        real_commit = session.commit

        def counted_commit():
            commits.append(True)
            return real_commit()

        session.commit = counted_commit
        assert calendar_service.sync_domain_sources(session, owner) == []
        assert session.scalar(select(func.count()).select_from(CalendarEventSource)) == 1
        assert commits == []
        session.rollback()
    with SessionLocal() as session:
        assert session.scalar(select(func.count()).select_from(CalendarEventSource)) == 0

    actor = ActorContext(user_id=owner, roles=frozenset({Role.STUDENT}))
    with SessionLocal() as session:
        commits = []
        real_commit = session.commit

        def counted_refresh_commit():
            commits.append(True)
            return real_commit()

        session.commit = counted_refresh_commit
        result = calendar_service.list_events(
            session, actor, None, None, None, "Asia/Kolkata"
        )
        assert result.total == 1 and commits == [True]


def test_projection_failure_after_sync_rolls_back_materialised_rows(ctx, monkeypatch):
    client, SessionLocal, (owner, _) = ctx
    _seed_tutoring(SessionLocal, owner)

    def fail_projection(*_args, **_kwargs):
        raise calendar_service.CalendarError(
            500, "calendar_projection_failed", "Calendar projection failed"
        )

    monkeypatch.setattr(calendar_service, "_event_out", fail_projection)
    response = client.get("/api/v1/calendar/events", headers=_claims(owner))
    assert response.status_code == 500
    assert response.json()["detail"]["code"] == "calendar_projection_failed"
    with SessionLocal() as session:
        assert session.scalar(select(func.count()).select_from(CalendarEventSource)) == 0
        assert session.scalar(select(func.count()).select_from(CalendarEvent)) == 0


def test_public_feed_is_read_only_until_authenticated_refresh(ctx):
    client, SessionLocal, (owner, _) = ctx
    export = client.post(
        "/api/v1/calendar/exports",
        headers={**_claims(owner), "Idempotency-Key": "public-read-only-export"},
        json={"timezone": "Asia/Kolkata"},
    ).json()
    _seed_tutoring(SessionLocal, owner)
    with SessionLocal() as session:
        assert session.scalar(select(func.count()).select_from(CalendarEventSource)) == 0
    before_refresh = client.get(export["feed_url"])
    assert before_refresh.status_code == 200 and "Tutoring session" not in before_refresh.text
    with SessionLocal() as session:
        assert session.scalar(select(func.count()).select_from(CalendarEventSource)) == 0
    refreshed = client.get("/api/v1/calendar/events", headers=_claims(owner))
    assert refreshed.status_code == 200 and refreshed.json()["total"] == 1
    after_refresh = client.get(export["feed_url"])
    assert after_refresh.status_code == 200 and "Tutoring session" in after_refresh.text


def test_requested_source_retry_syncs_only_the_selected_adapter(ctx, monkeypatch):
    client, _, (owner, _) = ctx
    called: list[str] = []
    monkeypatch.setattr(
        calendar_service,
        "_sync_tutoring_source",
        lambda _session, _owner: called.append("tutoring"),
    )
    monkeypatch.setattr(
        calendar_service,
        "_sync_credential_reminder_source",
        lambda _session, _owner: called.append("reminder"),
    )
    response = client.get(
        "/api/v1/calendar/events?source_type=tutoring",
        headers=_claims(owner),
    )
    assert response.status_code == 200
    assert response.json()["failed_sources"] == []
    assert called == ["tutoring"]


def test_export_one_time_secret_rotation_ics_privacy_and_revocation(ctx):
    client, SessionLocal, (owner, other) = ctx
    _create(client, owner, "event-export-private", title="Call 9876543210 lawyer@example.com", privacy="restricted")
    canaries = "ENROL-2026-999 BAR/DL/1234/2020 123e4567-e89b-12d3-a456-426614174000"
    _create(client, owner, "event-export-canaries", title=canaries, privacy="personal", event_kind="other")
    first = client.post(
        "/api/v1/calendar/exports",
        headers={**_claims(owner), "Idempotency-Key": "export-idem-first"},
        json={"timezone": "Asia/Kolkata"},
    )
    assert first.status_code == 201
    first_url = first.json()["feed_url"]
    assert first_url and first.json()["token_returned_once"] is True
    assert first_url.startswith("https://")
    raw = first_url.rsplit("/", 1)[1].removesuffix(".ics")
    replay = client.post(
        "/api/v1/calendar/exports",
        headers={**_claims(owner), "Idempotency-Key": "export-idem-first"},
        json={"timezone": "Asia/Kolkata"},
    )
    assert replay.status_code == 201 and replay.json()["feed_url"] is None
    listed = client.get("/api/v1/calendar/exports", headers=_claims(owner)).json()
    assert listed["items"][0]["feed_url"] is None
    assert client.get(f"/api/v1/calendar/exports/{first.json()['id']}", headers=_claims(other)).status_code == 404

    feed = client.get(first_url)
    assert feed.status_code == 200
    assert feed.headers["cache-control"] == "private, no-store"
    assert feed.headers["referrer-policy"] == "no-referrer"
    assert "Private LegalSaathi event" in feed.text
    assert "9876543210" not in feed.text and "lawyer@example.com" not in feed.text
    assert all(canary not in feed.text for canary in ("ENROL-2026-999", "BAR/DL/1234/2020", "123e4567-e89b-12d3-a456-426614174000"))
    assert "Personal calendar event" in feed.text
    query_rejected = client.get(f"{first_url}?tracking=not-allowed")
    assert query_rejected.status_code == 404 and query_rejected.json()["detail"]["code"] == "calendar_export_not_found"
    assert all(len(line.encode("utf-8")) <= 75 for line in feed.text.split("\r\n") if line)
    assert client.get(
        "/api/v1/public/calendar-feeds/" + ("A" * 42) + ".ics"
    ).status_code == 404
    with SessionLocal() as session:
        token = session.scalar(select(CalendarExportToken))
        assert token.token_hash == keyed_hash(raw)
        assert token.key_version == "v1" and token.metadata_json is None
        assert raw not in token.token_hash
        assert raw not in json.dumps([row.after_state for row in session.scalars(select(AuditEvent)).all()])

    second = client.post(
        "/api/v1/calendar/exports",
        headers={**_claims(owner), "Idempotency-Key": "export-idem-second"},
        json={"timezone": "Asia/Kolkata"},
    )
    assert second.status_code == 201 and second.json()["feed_url"]
    assert client.get(first_url).status_code == 404
    assert client.get(second.json()["feed_url"]).status_code == 200
    assert client.delete(f"/api/v1/calendar/exports/{second.json()['id']}", headers=_claims(owner)).status_code == 200
    assert client.get(second.json()["feed_url"]).status_code == 404
    with SessionLocal() as session:
        assert len(list(session.scalars(select(CalendarExportRevocation)))) == 2
        assert session.scalar(select(CalendarExportSubscription).where(
            CalendarExportSubscription.id == uuid.UUID(first.json()["id"])
        )).active_marker is None


def test_db_rejects_reversed_conflict_pair_and_second_active_export(ctx):
    _, SessionLocal, (owner, _) = ctx
    now = datetime.now(timezone.utc)
    with SessionLocal() as session:
        source1 = CalendarEventSource(owner_user_id=owner, source_type="reminder", source_id="db-a", source_url="/s-91", last_synced_at=now)
        source2 = CalendarEventSource(owner_user_id=owner, source_type="reminder", source_id="db-b", source_url="/s-91", last_synced_at=now)
        session.add_all([source1, source2]); session.flush()
        events = [
            CalendarEvent(owner_user_id=owner, event_source_id=source.id, title="A", starts_at=now, ends_at=now + timedelta(hours=1), timezone="UTC", source_offset_minutes=0, status="scheduled", privacy_classification="personal", idempotency_key=f"db-event-{index}")
            for index, source in enumerate((source1, source2))
        ]
        session.add_all(events); session.flush()
        left, right = sorted((events[0].id, events[1].id), key=str, reverse=True)
        session.add(CalendarConflict(owner_user_id=owner, left_event_id=left, right_event_id=right, status="active", detected_at=now))
        with pytest.raises(IntegrityError):
            session.flush()
        session.rollback()

    with SessionLocal() as session:
        first = CalendarExportSubscription(owner_user_id=owner, status="active", active_marker=True, timezone="UTC", idempotency_key="db-export-first", expires_at=now + timedelta(days=1))
        second = CalendarExportSubscription(owner_user_id=owner, status="active", active_marker=True, timezone="UTC", idempotency_key="db-export-second", expires_at=now + timedelta(days=1))
        session.add_all([first, second])
        with pytest.raises(IntegrityError):
            session.flush()
        session.rollback()


def test_db_rejects_event_source_owner_mismatch(ctx):
    _, SessionLocal, (owner, other) = ctx
    now = datetime.now(timezone.utc)
    with SessionLocal() as session:
        session.execute(text("PRAGMA foreign_keys=ON"))
        source = CalendarEventSource(
            owner_user_id=owner,
            source_type="reminder",
            source_id="owner-consistency-source",
            source_url="/s-91",
            last_synced_at=now,
        )
        session.add(source); session.commit()
        session.add(CalendarEvent(
            owner_user_id=other,
            event_source_id=source.id,
            title="Mismatched owner",
            starts_at=now,
            ends_at=now + timedelta(hours=1),
            timezone="UTC",
            source_offset_minutes=0,
            status="scheduled",
            privacy_classification="personal",
            personal_event_kind="other",
            idempotency_key="owner-consistency-event",
        ))
        with pytest.raises(IntegrityError):
            session.flush()
        session.rollback()


def test_db_rejects_conflict_whose_events_do_not_share_owner(ctx):
    client, SessionLocal, (owner, other) = ctx
    owner_event = _create(client, owner, "conflict-owner-event").json()
    other_event = _create(client, other, "conflict-other-event").json()
    left, right = sorted(
        (uuid.UUID(owner_event["id"]), uuid.UUID(other_event["id"])),
        key=str,
    )
    with SessionLocal() as session:
        session.execute(text("PRAGMA foreign_keys=ON"))
        session.add(CalendarConflict(
            owner_user_id=owner,
            left_event_id=left,
            right_event_id=right,
            status="active",
            detected_at=datetime.now(timezone.utc),
        ))
        with pytest.raises(IntegrityError):
            session.flush()
        session.rollback()


def test_conflict_schema_uses_composite_owner_foreign_keys():
    event_uniques = {
        constraint.name
        for constraint in CalendarEvent.__table__.constraints
        if constraint.__class__.__name__ == "UniqueConstraint"
    }
    conflict_fks = {
        constraint.name: tuple(column.name for column in constraint.columns)
        for constraint in CalendarConflict.__table__.foreign_key_constraints
    }
    assert "uq_calendar_event_id_owner" in event_uniques
    assert conflict_fks["fk_calendar_conflict_left_event_owner"] == (
        "left_event_id",
        "owner_user_id",
    )
    assert conflict_fks["fk_calendar_conflict_right_event_owner"] == (
        "right_event_id",
        "owner_user_id",
    )


def test_user_deletion_cascades_export_capability_and_revocation(ctx):
    client, SessionLocal, (owner, _) = ctx
    with SessionLocal() as session:
        session.execute(text("PRAGMA foreign_keys=ON"))
        session.commit()
    created = client.post(
        "/api/v1/calendar/exports",
        headers={**_claims(owner), "Idempotency-Key": "export-delete-cascade"},
        json={"timezone": "Asia/Kolkata"},
    ).json()
    assert client.delete(f"/api/v1/calendar/exports/{created['id']}", headers=_claims(owner)).status_code == 200
    with SessionLocal() as session:
        session.execute(text("PRAGMA foreign_keys=ON"))
        user = session.get(User, owner)
        session.delete(user)
        session.commit()
        assert session.scalar(select(func.count()).select_from(CalendarExportSubscription)) == 0
        assert session.scalar(select(func.count()).select_from(CalendarExportToken)) == 0
        assert session.scalar(select(func.count()).select_from(CalendarExportRevocation)) == 0

def test_public_token_path_is_redacted():
    path = "/api/v1/public/calendar-feeds/not-a-real-secret.ics"
    assert redact_sensitive_path(path) == "/api/v1/public/calendar-feeds/:token"
    assert "not-a-real-secret" not in redact_sensitive_path(path)
