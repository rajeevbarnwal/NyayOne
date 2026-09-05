"""Wave 5 calendar HTTP, persistence, privacy and negative-boundary proof."""
from __future__ import annotations

import json
import re
import uuid
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

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
    CalendarViewPreference,
)
from app.models.credentials import Credential, CredentialReminderJob
from app.models.registration import User
from app.models.wave2 import TutorAvailabilitySlot, TutorProfile, TutoringSession
from app.schemas.calendar import EventCreate
from app.services import calendar_service
from scripts.wave5_postgres_gate import is_isolated_gate_target, privacy_canary_hits
from tests import apptemplate, dbtemplate

NON_DEV_DATABASE_URL = (
    "postgresql+psycopg://nyayone_runtime:nondev-test-only@db.invalid/nyayone"
)
NONLOCAL_OTP_CONFIG = {
    "otp_delivery_enabled": True,
    "otp_provider": "http",
    "otp_provider_url": "https://otp-provider.example.invalid/send",
    "otp_provider_token": "wave5-calendar-config-token",
    "otp_provider_supports_idempotency": True,
}
NONLOCAL_MENTOR_CONFIG = {
    "mentor_terminal_retention_seconds": 2_592_000,
    "mentor_audit_link_retention_seconds": 2_592_000,
    "mentor_retention_mode": "bounded_crypto_erasure",
}
CI_CANONICAL_CORS_ORIGIN = "https://ci.nyayone.example"


def _claims(user_id: uuid.UUID) -> dict[str, str]:
    return {"X-Actor-Claims": json.dumps({"sub": str(user_id), "roles": ["student"]})}


def test_postgres_gate_requires_loopback_qa_target_test_env_and_opt_in():
    safe = "postgresql+psycopg://user:secret@127.0.0.1:5432/nyayone_wave5_qa"
    assert is_isolated_gate_target(safe, "testing", True)
    assert not is_isolated_gate_target(safe, "production", True)
    assert not is_isolated_gate_target(safe, "testing", False)
    assert not is_isolated_gate_target(
        "postgresql+psycopg://user:secret@db.internal:5432/nyayone_wave5_qa",
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
            database_url=NON_DEV_DATABASE_URL,
            calendar_public_base_url="https://localhost:1030",
            **NONLOCAL_OTP_CONFIG,
            **NONLOCAL_MENTOR_CONFIG,
        )
    configured = Settings(
        _env_file=None,
        app_env="preview",
        database_url=NON_DEV_DATABASE_URL,
        calendar_public_base_url="https://calendar.example.test",
        **NONLOCAL_OTP_CONFIG,
        **NONLOCAL_MENTOR_CONFIG,
    )
    assert configured.calendar_public_base_url == "https://calendar.example.test"


# --------------------------------------------------------------------------- #
# D1 — staging CI jobs must state an explicit non-loopback calendar origin.
#
# `APP_ENV: staging` is not a local/test environment, so the loopback default
# is refused on purpose.  A staging CI job that omits CALENDAR_PUBLIC_BASE_URL
# therefore cannot even construct Settings.  These tests pin both halves: the
# refusal must stay (fail-closed), and the exact origin the workflows declare
# must be accepted.
# --------------------------------------------------------------------------- #
CI_STAGING_CALENDAR_ORIGIN = "https://calendar.example.test"
_STAGING_WORKFLOWS = (
    "wave1-foundation-gate.yml",
    "wave3-credential-trust-gate.yml",
)


def _staging_settings(**overrides: object) -> Settings:
    # `staging` also activates the Wave 4 scanner contract; select the same real
    # seam the workflows select so this test isolates the Wave 5 origin rule.
    overrides.setdefault("database_url", NON_DEV_DATABASE_URL)
    return Settings(
        _env_file=None,
        app_env="staging",
        internship_report_scanner_provider="clamav",
        cors_origins=[CI_CANONICAL_CORS_ORIGIN],
        **NONLOCAL_OTP_CONFIG,
        **NONLOCAL_MENTOR_CONFIG,
        **overrides,
    )


def _job_env_blocks(document: str) -> list[dict[str, str]]:
    """Return every ``env:`` mapping in a workflow, keyed by indentation.

    Deliberately dependency-free: the backend runtime does not declare a YAML
    parser, and the assertion only needs flat scalar key/value pairs.
    """
    lines = document.splitlines()
    blocks: list[dict[str, str]] = []
    for index, line in enumerate(lines):
        if line.strip() != "env:":
            continue
        indent = len(line) - len(line.lstrip())
        block: dict[str, str] = {}
        for candidate in lines[index + 1 :]:
            if not candidate.strip():
                continue
            candidate_indent = len(candidate) - len(candidate.lstrip())
            if candidate_indent <= indent:
                break
            if candidate.lstrip().startswith("#"):
                continue
            key, separator, value = candidate.strip().partition(":")
            if separator:
                block[key.strip()] = value.strip()
        blocks.append(block)
    return blocks


def test_staging_rejects_loopback_calendar_origin_and_accepts_the_ci_origin(monkeypatch):
    # This test runs inside the very staging jobs being validated, where the
    # workflow-level variable is already present. Remove it for the explicit
    # "unset uses the refused loopback default" case; explicit constructor
    # values below remain authoritative and monkeypatch restores the process
    # environment after the test.
    monkeypatch.delenv("CALENDAR_PUBLIC_BASE_URL", raising=False)
    for loopback in ("https://localhost:1030", "https://127.0.0.1:1030", "https://[::1]:1030"):
        with pytest.raises(ConfigurationError, match="calendar_public_base_url"):
            _staging_settings(calendar_public_base_url=loopback)
    # The default is a loopback origin, so an unset variable must also refuse.
    with pytest.raises(ConfigurationError, match="calendar_public_base_url"):
        _staging_settings()
    accepted = _staging_settings(calendar_public_base_url=CI_STAGING_CALENDAR_ORIGIN)
    assert accepted.calendar_public_base_url == CI_STAGING_CALENDAR_ORIGIN
    # Production stays fail-closed on the same rule; nothing here relaxes it.
    with pytest.raises(ConfigurationError, match="calendar_public_base_url"):
        Settings(
            _env_file=None,
            app_env="production",
            database_url=NON_DEV_DATABASE_URL,
            internship_report_scanner_provider="clamav",
            cors_origins=[CI_CANONICAL_CORS_ORIGIN],
            calendar_public_base_url="https://127.0.0.1:1030",
            **NONLOCAL_OTP_CONFIG,
            **NONLOCAL_MENTOR_CONFIG,
        )


def test_staging_ci_workflows_declare_the_explicit_calendar_origin():
    root = Path(__file__).resolve().parents[2] / ".github" / "workflows"
    for name in _STAGING_WORKFLOWS:
        document = (root / name).read_text(encoding="utf-8")
        staging_blocks = [
            block for block in _job_env_blocks(document) if block.get("APP_ENV") == "staging"
        ]
        assert staging_blocks, f"{name} no longer declares a staging job environment"
        for block in staging_blocks:
            assert block.get("CALENDAR_PUBLIC_BASE_URL") == CI_STAGING_CALENDAR_ORIGIN, name
            # The declared value must be one Settings actually accepts.
            assert (
                _staging_settings(
                    calendar_public_base_url=block["CALENDAR_PUBLIC_BASE_URL"]
                ).calendar_public_base_url
                == CI_STAGING_CALENDAR_ORIGIN
            )


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


def _calendar_counts(SessionLocal, owner: uuid.UUID) -> dict[str, int]:
    """Mutation ledger used by the explicit N-* negative assertions."""
    models = {
        "sources": CalendarEventSource,
        "events": CalendarEvent,
        "views": CalendarViewPreference,
        "reminders": CalendarReminderPreference,
        "conflicts": CalendarConflict,
        "exports": CalendarExportSubscription,
        "tokens": CalendarExportToken,
        "revocations": CalendarExportRevocation,
    }
    with SessionLocal() as session:
        counts = {
            label: int(session.scalar(select(func.count()).select_from(model).where(
                getattr(model, "owner_user_id", None) == owner
            )) or 0)
            if hasattr(model, "owner_user_id")
            else int(session.scalar(select(func.count()).select_from(model)) or 0)
            for label, model in models.items()
        }
        counts["audit"] = int(session.scalar(
            select(func.count()).select_from(AuditEvent).where(AuditEvent.actor_user_id == owner)
        ) or 0)
        return counts


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
    assert enabled_preview.json()["preview"] == "An upcoming NyayOne event has a reminder."
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
    assert "Private NyayOne event" in feed.text
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


@pytest.mark.parametrize("title", ["", "   \t\n"])
def test_negative_n01_empty_or_whitespace_title_is_422_and_atomic(ctx, title):
    client, SessionLocal, (owner, _) = ctx
    before = _calendar_counts(SessionLocal, owner)
    response = _create(client, owner, "n01-empty-title", title=title)
    assert response.status_code == 422
    assert _calendar_counts(SessionLocal, owner) == before


def test_negative_n03_controls_rejected_unicode_html_is_safe_text(ctx):
    client, SessionLocal, (owner, _) = ctx
    before = _calendar_counts(SessionLocal, owner)
    rejected = _create(
        client,
        owner,
        "n03-control-title",
        title="Hearing\u0000<script>alert(1)</script>",
    )
    assert rejected.status_code == 422
    assert _calendar_counts(SessionLocal, owner) == before

    permitted = "Moot ⚖️ — <script>alert('never executable')</script>; comma, slash\\"
    accepted = _create(client, owner, "n03-safe-unicode", title=permitted)
    assert accepted.status_code == 201 and accepted.json()["title"] == permitted
    export = client.post(
        "/api/v1/calendar/exports",
        headers={**_claims(owner), "Idempotency-Key": "n03-safe-export"},
        json={"timezone": "Asia/Kolkata"},
    ).json()
    feed = client.get(export["feed_url"])
    assert feed.status_code == 200
    # Public ICS is allowlist-based; user HTML/Unicode is never projected.
    assert permitted not in feed.text and "<script>" not in feed.text


@pytest.mark.parametrize(
    "mutation",
    [
        {"starts_at": None},
        {"ends_at": None},
        {"starts_at": "not-a-date"},
        {"ends_at": "not-a-date"},
        {"timezone": "Mars/Olympus_Mons"},
        {"timezone": ""},
    ],
)
def test_negative_n04_missing_invalid_instants_or_timezone_are_422_without_mutation(ctx, mutation):
    client, SessionLocal, (owner, _) = ctx
    payload = _event_body()
    payload.update(mutation)
    before = _calendar_counts(SessionLocal, owner)
    response = client.post(
        "/api/v1/calendar/events",
        json=payload,
        headers={**_claims(owner), "Idempotency-Key": "n04-invalid-wire"},
    )
    assert response.status_code == 422
    assert _calendar_counts(SessionLocal, owner) == before


@pytest.mark.parametrize(
    ("start", "end"),
    [
        ("2026-08-10T05:30:00Z", "2026-08-10T04:30:00Z"),
        ("2026-08-10T04:30:00Z", "2026-08-10T04:30:00Z"),
    ],
)
def test_negative_n05_reversed_and_zero_duration_are_422_and_atomic(ctx, start, end):
    client, SessionLocal, (owner, _) = ctx
    before = _calendar_counts(SessionLocal, owner)
    response = _create(client, owner, "n05-invalid-interval", start=start, end=end)
    assert response.status_code == 422
    assert _calendar_counts(SessionLocal, owner) == before


def test_negative_n06_iana_and_dst_policy_is_explicit_and_never_silently_shifted(ctx):
    client, SessionLocal, (owner, _) = ctx
    valid = _create(
        client,
        owner,
        "n06-valid-iana",
        start="2026-08-10T10:00:00+05:30",
        end="2026-08-10T11:00:00+05:30",
    )
    assert valid.status_code == 201
    assert valid.json()["starts_at"] == "2026-08-10T04:30:00Z"
    count_after_valid = _calendar_counts(SessionLocal, owner)

    invalid_zone = _create(client, owner, "n06-invalid-zone", timezone_name="GMT+5:30")
    nonexistent_local_offset = _create(
        client,
        owner,
        "n06-nonexistent-local",
        start="2026-03-29T01:30:00+01:00",
        end="2026-03-29T02:30:00+01:00",
        timezone_name="Europe/London",
    )
    assert invalid_zone.status_code == nonexistent_local_offset.status_code == 422
    assert _calendar_counts(SessionLocal, owner) == count_after_valid

    # Both fall-back folds are explicit instants and must remain distinct.
    fold_one = EventCreate.model_validate(_event_body(
        start="2026-10-25T01:10:00+01:00",
        end="2026-10-25T01:40:00+01:00",
        timezone_name="Europe/London",
    ))
    fold_two = EventCreate.model_validate(_event_body(
        start="2026-10-25T01:10:00+00:00",
        end="2026-10-25T01:40:00+00:00",
        timezone_name="Europe/London",
    ))
    assert fold_one.starts_at != fold_two.starts_at


def test_negative_n08_overlap_matrix_is_stable_owner_scoped_and_half_open(ctx):
    client, _, (owner, other) = ctx
    fixtures = [
        ("base", "2026-08-12T10:00:00.000Z", "2026-08-12T11:00:00.000Z"),
        ("one-ms", "2026-08-12T10:59:59.999Z", "2026-08-12T12:00:00.000Z"),
        ("duplicate", "2026-08-12T10:00:00.000Z", "2026-08-12T11:00:00.000Z"),
        ("contained", "2026-08-12T10:15:00.000Z", "2026-08-12T10:45:00.000Z"),
        ("adjacent", "2026-08-12T11:00:00.000Z", "2026-08-12T12:00:00.000Z"),
    ]
    ids = []
    for label, start, end in fixtures:
        response = _create(client, owner, f"n08-{label}-event", start=start, end=end)
        assert response.status_code == 201
        ids.append(response.json()["id"])
    foreign = _create(client, other, "n08-foreign-event").json()["id"]

    first = client.post(
        "/api/v1/calendar/conflicts/check",
        headers=_claims(owner),
        json={"event_ids": ids, "persist": False},
    )
    second = client.post(
        "/api/v1/calendar/conflicts/check",
        headers=_claims(owner),
        json={"event_ids": list(reversed(ids)), "persist": False},
    )
    assert first.status_code == second.status_code == 200
    pairs_one = [(row["left_event_id"], row["right_event_id"]) for row in first.json()["items"]]
    pairs_two = [(row["left_event_id"], row["right_event_id"]) for row in second.json()["items"]]
    assert pairs_one == pairs_two
    assert all(left < right for left, right in pairs_one)
    assert not any(set(pair) == {ids[0], ids[-1]} for pair in pairs_one)  # base/adjacent boundary
    hidden = client.post(
        "/api/v1/calendar/conflicts/check",
        headers=_claims(owner),
        json={"event_ids": [ids[0], foreign], "persist": False},
    )
    assert hidden.status_code == 404
    assert hidden.json()["detail"] == {
        "code": "calendar_event_not_found",
        "message": "Calendar event not found",
    }


def test_negative_n09_supported_date_extremes_persist_and_out_of_range_is_typed(ctx):
    client, SessionLocal, (owner, _) = ctx
    for label, start, end in (
        ("old", "1900-01-01T00:00:00Z", "1900-01-01T01:00:00Z"),
        ("future", "2100-12-31T22:00:00Z", "2100-12-31T23:00:00Z"),
    ):
        response = _create(client, owner, f"n09-{label}-date", start=start, end=end)
        assert response.status_code == 201
    before_bad = _calendar_counts(SessionLocal, owner)
    rejected = _create(
        client,
        owner,
        "n09-out-of-range",
        start="10000-01-01T00:00:00Z",
        end="10000-01-01T01:00:00Z",
    )
    assert rejected.status_code == 422
    assert _calendar_counts(SessionLocal, owner) == before_bad


def test_negative_n10_source_tuple_dedupes_but_same_id_across_types_is_distinct(ctx):
    _, SessionLocal, (owner, _) = ctx
    now = datetime(2026, 8, 20, 4, 30, tzinfo=timezone.utc)
    with SessionLocal() as session:
        for source_type, title in (
            ("tutoring", "First tutoring title"),
            ("tutoring", "Updated tutoring title"),
            ("reminder", "Credential renewal reminder"),
        ):
            calendar_service._upsert_imported_event(
                session,
                owner_id=owner,
                source_type=source_type,
                source_id="shared-source-id",
                source_url="/s-35" if source_type == "tutoring" else "/s-82",
                title=title,
                starts_at=now,
                ends_at=now + timedelta(hours=1),
                timezone_name="Asia/Kolkata",
                status="scheduled",
            )
        session.commit()
        sources = list(session.scalars(select(CalendarEventSource).where(
            CalendarEventSource.owner_user_id == owner,
            CalendarEventSource.source_id == "shared-source-id",
        )))
        events = list(session.scalars(select(CalendarEvent).where(CalendarEvent.owner_user_id == owner)))
    assert len(sources) == len(events) == 2
    assert {source.source_type for source in sources} == {"tutoring", "reminder"}
    assert {event.title for event in events} == {
        "Updated tutoring title",
        "Credential renewal reminder",
    }


def test_negative_n12_wrong_role_is_403_without_mutation(ctx):
    client, SessionLocal, (owner, _) = ctx
    headers = {"X-Actor-Claims": json.dumps({"sub": str(owner), "roles": ["lawyer"]})}
    before = _calendar_counts(SessionLocal, owner)
    response = client.post(
        "/api/v1/calendar/events",
        headers={**headers, "Idempotency-Key": "n12-wrong-role"},
        json=_event_body(),
    )
    assert response.status_code == 403
    assert response.json()["detail"]["code"] == "forbidden"
    assert _calendar_counts(SessionLocal, owner) == before


def test_negative_n13_cross_user_resources_are_non_enumerating_and_immutable(ctx):
    client, SessionLocal, (owner, other) = ctx
    event = _create(client, owner, "n13-owned-event").json()
    export = client.post(
        "/api/v1/calendar/exports",
        headers={**_claims(owner), "Idempotency-Key": "n13-owned-export"},
        json={"timezone": "Asia/Kolkata"},
    ).json()
    before = _calendar_counts(SessionLocal, owner)
    update = {**_event_body(title="Cross-user overwrite"), "expected_version": 1}
    responses = [
        client.get(f"/api/v1/calendar/events/{event['id']}", headers=_claims(other)),
        client.put(f"/api/v1/calendar/events/{event['id']}", headers=_claims(other), json=update),
        client.delete(f"/api/v1/calendar/events/{event['id']}", headers=_claims(other)),
        client.get(f"/api/v1/calendar/exports/{export['id']}", headers=_claims(other)),
        client.delete(f"/api/v1/calendar/exports/{export['id']}", headers=_claims(other)),
    ]
    assert all(response.status_code == 404 for response in responses)
    assert len({json.dumps(response.json(), sort_keys=True) for response in responses[:3]}) == 1
    assert _calendar_counts(SessionLocal, owner) == before


def test_negative_n14_forged_claims_header_is_rejected_outside_test(monkeypatch, ctx):
    from app.core.config import settings

    client, SessionLocal, (owner, _) = ctx
    before = _calendar_counts(SessionLocal, owner)
    monkeypatch.setattr(settings, "app_env", "production")
    response = _create(client, owner, "n14-forged-production-header")
    assert response.status_code == 401
    assert response.json()["detail"]["code"] == "authentication_required"
    assert _calendar_counts(SessionLocal, owner) == before


def test_negative_n15_unknown_and_cross_user_identifiers_have_identical_contract(ctx):
    client, _, (owner, other) = ctx
    event = _create(client, other, "n15-other-event").json()
    unknown = str(uuid.uuid4())
    foreign_response = client.get(f"/api/v1/calendar/events/{event['id']}", headers=_claims(owner))
    unknown_response = client.get(f"/api/v1/calendar/events/{unknown}", headers=_claims(owner))
    assert foreign_response.status_code == unknown_response.status_code == 404
    assert foreign_response.content == unknown_response.content
    assert foreign_response.headers["content-type"] == unknown_response.headers["content-type"]


def test_negative_n16_missing_reminder_payload_is_rejected_without_partial_overwrite(ctx):
    client, SessionLocal, (owner, _) = ctx
    before = client.get("/api/v1/calendar/reminder-preferences", headers=_claims(owner)).json()
    before_counts = _calendar_counts(SessionLocal, owner)
    for payload in ({}, {"source_type": "exam"}, {"enabled": False}):
        response = client.put(
            "/api/v1/calendar/reminder-preferences",
            headers=_claims(owner),
            json=payload,
        )
        assert response.status_code == 422
    assert client.get("/api/v1/calendar/reminder-preferences", headers=_claims(owner)).json() == before
    assert _calendar_counts(SessionLocal, owner) == before_counts


@pytest.mark.parametrize("lead", [-1, 1, 9, 11, 29, 31, 61, 121, 1439, 1441])
def test_negative_n17_noncanonical_reminder_lead_is_422_and_atomic(ctx, lead):
    client, SessionLocal, (owner, _) = ctx
    before = _calendar_counts(SessionLocal, owner)
    response = client.put(
        "/api/v1/calendar/reminder-preferences",
        headers=_claims(owner),
        json={
            "source_type": "exam",
            "channel": "in_app",
            "enabled": True,
            "lead_minutes": lead,
            "quiet_start_min": 0,
            "quiet_end_min": 1439,
            "timezone": "Asia/Kolkata",
            "expected_version": 0,
        },
    )
    assert response.status_code == 422
    assert _calendar_counts(SessionLocal, owner) == before


@pytest.mark.parametrize(
    ("field", "value", "accepted"),
    [
        ("quiet_start_min", -1, False),
        ("quiet_start_min", 0, True),
        ("quiet_end_min", 1439, True),
        ("quiet_end_min", 1440, False),
        ("source_type", "unknown", False),
        ("channel", "sms", False),
        ("timezone", "Invalid/Timezone", False),
    ],
)
def test_negative_n18_quiet_source_channel_timezone_boundaries(ctx, field, value, accepted):
    client, _, (owner, _) = ctx
    payload = {
        "source_type": "exam",
        "channel": "in_app",
        "enabled": True,
        "lead_minutes": 30,
        "quiet_start_min": 0,
        "quiet_end_min": 1439,
        "timezone": "Asia/Kolkata",
        "expected_version": 0,
    }
    payload[field] = value
    response = client.put(
        "/api/v1/calendar/reminder-preferences",
        headers=_claims(owner),
        json=payload,
    )
    assert response.status_code == (200 if accepted else 422)


def test_negative_n20_commit_failure_rolls_back_reminder_and_retry_is_exactly_once(ctx, monkeypatch):
    client, SessionLocal, (owner, _) = ctx
    payload = {
        "source_type": "exam",
        "channel": "in_app",
        "enabled": False,
        "lead_minutes": 60,
        "quiet_start_min": 0,
        "quiet_end_min": 1439,
        "timezone": "Asia/Kolkata",
        "expected_version": 0,
    }
    real_commit = Session.commit
    attempts = {"count": 0}

    def fail_first_commit(session):
        attempts["count"] += 1
        if attempts["count"] == 1:
            raise RuntimeError("n20 injected commit failure")
        return real_commit(session)

    monkeypatch.setattr(Session, "commit", fail_first_commit)
    failed = client.put(
        "/api/v1/calendar/reminder-preferences",
        headers=_claims(owner),
        json=payload,
    )
    assert failed.status_code == 500
    assert _calendar_counts(SessionLocal, owner)["reminders"] == 0
    assert _calendar_counts(SessionLocal, owner)["audit"] == 0
    retry = client.put(
        "/api/v1/calendar/reminder-preferences",
        headers=_claims(owner),
        json=payload,
    )
    assert retry.status_code == 200 and retry.json()["version"] == 1
    counts = _calendar_counts(SessionLocal, owner)
    assert counts["reminders"] == counts["audit"] == 1


def test_negative_n22_export_idempotency_mismatch_is_typed_and_atomic(ctx):
    client, SessionLocal, (owner, _) = ctx
    first = client.post(
        "/api/v1/calendar/exports",
        headers={**_claims(owner), "Idempotency-Key": "n22-export-idempotency"},
        json={"timezone": "Asia/Kolkata"},
    )
    assert first.status_code == 201
    before = _calendar_counts(SessionLocal, owner)
    mismatch = client.post(
        "/api/v1/calendar/exports",
        headers={**_claims(owner), "Idempotency-Key": "n22-export-idempotency"},
        json={"timezone": "Europe/London"},
    )
    assert mismatch.status_code == 409
    assert mismatch.json()["detail"]["code"] == "idempotency_conflict"
    assert _calendar_counts(SessionLocal, owner) == before


@pytest.mark.parametrize(
    "candidate",
    [
        "A" * 42,
        "not+url/safe+base64" + "A" * 30,
        "क" * 43,
        "%2e%2e%2f" + "A" * 43,
        "A" * 161,
    ],
)
def test_negative_n24_malformed_short_unicode_or_traversal_token_is_safe_404(ctx, candidate):
    client, SessionLocal, (owner, _) = ctx
    before = _calendar_counts(SessionLocal, owner)
    response = client.get(f"/api/v1/public/calendar-feeds/{candidate}.ics")
    assert response.status_code == 404
    assert candidate not in response.text
    assert "traceback" not in response.text.casefold()
    assert _calendar_counts(SessionLocal, owner) == before


def test_negative_n25_unknown_expired_revoked_rotated_and_valid_capabilities(ctx):
    client, SessionLocal, (owner, _) = ctx

    def create(key: str) -> tuple[dict[str, object], str]:
        response = client.post(
            "/api/v1/calendar/exports",
            headers={**_claims(owner), "Idempotency-Key": key},
            json={"timezone": "Asia/Kolkata"},
        )
        assert response.status_code == 201 and response.json()["feed_url"]
        return response.json(), response.json()["feed_url"]

    first, first_url = create("n25-first-export")
    assert client.get(first_url).status_code == 200
    _, second_url = create("n25-second-export")
    rotated = client.get(first_url)
    assert client.get(second_url).status_code == 200
    second_id = client.get("/api/v1/calendar/exports", headers=_claims(owner)).json()["items"][0]["id"]
    assert client.delete(f"/api/v1/calendar/exports/{second_id}", headers=_claims(owner)).status_code == 200
    revoked = client.get(second_url)

    third, third_url = create("n25-third-export")
    with SessionLocal() as session:
        subscription = session.get(CalendarExportSubscription, uuid.UUID(third["id"]))
        token = session.scalar(select(CalendarExportToken).where(
            CalendarExportToken.subscription_id == subscription.id
        ))
        expired_at = datetime.now(timezone.utc) - timedelta(seconds=1)
        subscription.expires_at = expired_at
        token.expires_at = expired_at
        session.commit()
    expired = client.get(third_url)
    unknown = client.get("/api/v1/public/calendar-feeds/" + ("Z" * 43) + ".ics")
    assert rotated.status_code == revoked.status_code == expired.status_code == unknown.status_code == 404
    assert rotated.content == revoked.content == expired.content == unknown.content
    assert first["id"] != third["id"]


def test_negative_n26_capability_expiry_boundary_is_exclusive(ctx, monkeypatch):
    client, SessionLocal, (owner, _) = ctx
    created = client.post(
        "/api/v1/calendar/exports",
        headers={**_claims(owner), "Idempotency-Key": "n26-expiry-boundary"},
        json={"timezone": "Asia/Kolkata"},
    ).json()
    raw = created["feed_url"].rsplit("/", 1)[-1].removesuffix(".ics")
    fixed_now = datetime(2026, 8, 2, 12, 0, 0, tzinfo=timezone.utc)
    monkeypatch.setattr(calendar_service, "_now", lambda: fixed_now)

    def set_expiry(value: datetime) -> None:
        with SessionLocal() as session:
            subscription = session.get(CalendarExportSubscription, uuid.UUID(created["id"]))
            token = session.scalar(select(CalendarExportToken).where(
                CalendarExportToken.subscription_id == subscription.id
            ))
            subscription.status = "active"
            subscription.active_marker = True
            subscription.expires_at = value
            token.revoked_at = None
            token.expires_at = value
            session.commit()

    set_expiry(fixed_now - timedelta(milliseconds=1))
    assert client.get(created["feed_url"]).status_code == 404
    set_expiry(fixed_now)
    assert client.get(created["feed_url"]).status_code == 404
    set_expiry(fixed_now + timedelta(milliseconds=1))
    assert client.get(created["feed_url"]).status_code == 200
    with SessionLocal() as session:
        assert session.scalar(select(CalendarExportToken).where(
            CalendarExportToken.token_hash == keyed_hash(raw)
        )) is not None


def test_negative_n27_fail_closed_scanner_detects_raw_capability_on_every_surface():
    raw = "n27_RAW_CAPABILITY_CANARY_DO_NOT_SEAL_0123456789"
    surfaces = {
        "exception": {"detail": raw},
        "log": f"request failed {raw}",
        "audit": {"after_state": {"token": raw}},
        "evidence": {"request_url": f"https://example.test/feed/{raw}.ics"},
    }
    assert privacy_canary_hits(surfaces, {raw}) == sorted(surfaces)
    assert privacy_canary_hits(
        {name: "[redacted]" for name in surfaces},
        {raw},
    ) == []


def test_negative_n29_query_and_non_designated_capability_urls_are_rejected(ctx):
    client, _, (owner, _) = ctx
    created = client.post(
        "/api/v1/calendar/exports",
        headers={**_claims(owner), "Idempotency-Key": "n29-designated-route"},
        json={"timezone": "Asia/Kolkata"},
    ).json()
    raw = created["feed_url"].rsplit("/", 1)[-1].removesuffix(".ics")
    query = client.get(f"{created['feed_url']}?utm_source=forbidden")
    alternatives = [
        client.get(f"/api/v1/calendar-feeds/{raw}.ics"),
        client.get(f"/api/v1/calendar/exports/{raw}.ics"),
        client.get(f"/api/v1/public/calendar-feeds/{raw}"),
    ]
    assert query.status_code == 404
    assert query.json()["detail"]["code"] == "calendar_export_not_found"
    assert all(response.status_code in {404, 422} for response in alternatives)
    assert all(not response.is_redirect for response in [query, *alternatives])
    assert all(raw not in response.text for response in [query, *alternatives])


def test_negative_n30_release_exposes_ics_only_and_no_oauth_or_provider_routes(_mounted):
    app, client = _mounted
    calendar_paths = {path for path in app.openapi()["paths"] if "calendar" in path}
    assert "/api/v1/public/calendar-feeds/{raw_token}.ics" in calendar_paths
    assert all(
        marker not in path.casefold()
        for path in calendar_paths
        for marker in ("oauth", "google", "outlook", "provider-token", "webhook")
    )
    for path in (
        "/api/v1/calendar/oauth/google",
        "/api/v1/calendar/oauth/outlook",
        "/api/v1/calendar/sync/provider",
    ):
        response = client.post(path)
        assert response.status_code == 404


def _unfold_ics_lines(content: str) -> list[str]:
    unfolded: list[str] = []
    for line in content.split("\r\n"):
        if not line:
            continue
        if line.startswith(" "):
            assert unfolded, "continuation line requires a preceding content line"
            unfolded[-1] += line[1:]
        else:
            unfolded.append(line)
    return unfolded


def _unescape_ics_text(value: str) -> str:
    return re.sub(r"\\([\\n;,])", lambda match: "\n" if match.group(1) == "n" else match.group(1), value)


def test_negative_n31_ics_text_escaping_round_trips_through_test_decoder():
    original = "Comma, semicolon; slash\\ newline\nUnicode ⚖️"
    escaped = calendar_service._ics_escape(original)
    assert escaped == "Comma\\, semicolon\\; slash\\\\ newline\\nUnicode ⚖️"
    assert _unescape_ics_text(escaped) == original


def test_negative_n32_utf8_property_folding_is_75_octets_and_round_trips():
    original = "SUMMARY:" + ("न्याय⚖️," * 30) + ";end\\"
    folded = calendar_service._fold_ics(original)
    assert len(folded) > 1
    assert all(len(line.encode("utf-8")) <= 75 for line in folded)
    assert all(line.startswith(" ") for line in folded[1:])
    parsed = _unfold_ics_lines("\r\n".join(folded) + "\r\n")
    assert parsed == [original]


def test_negative_n35_empty_calendar_is_valid_crlf_vcalendar(ctx):
    client, _, (owner, _) = ctx
    created = client.post(
        "/api/v1/calendar/exports",
        headers={**_claims(owner), "Idempotency-Key": "n35-empty-calendar"},
        json={"timezone": "UTC"},
    ).json()
    feed = client.get(created["feed_url"])
    assert feed.status_code == 200
    assert feed.text.startswith("BEGIN:VCALENDAR\r\n")
    assert feed.text.endswith("END:VCALENDAR\r\n")
    assert "BEGIN:VEVENT" not in feed.text
    assert _unfold_ics_lines(feed.text)[0:2] == [
        "BEGIN:VCALENDAR",
        "PRODID:-//NyayOne//Private Calendar Feed//EN",
    ]


def test_negative_n36_replay_dedupes_vevent_and_uid_is_stable_nonreversible(ctx):
    client, _, (owner, _) = ctx
    first = _create(client, owner, "n36-idempotent-event", event_kind="study").json()
    replay = _create(client, owner, "n36-idempotent-event", event_kind="study").json()
    assert first["id"] == replay["id"]
    created = client.post(
        "/api/v1/calendar/exports",
        headers={**_claims(owner), "Idempotency-Key": "n36-export"},
        json={"timezone": "Asia/Kolkata"},
    ).json()
    first_feed = client.get(created["feed_url"]).text
    second_feed = client.get(created["feed_url"]).text
    assert first_feed.count("BEGIN:VEVENT") == second_feed.count("BEGIN:VEVENT") == 1
    first_uid = next(line.removeprefix("UID:") for line in _unfold_ics_lines(first_feed) if line.startswith("UID:"))
    second_uid = next(line.removeprefix("UID:") for line in _unfold_ics_lines(second_feed) if line.startswith("UID:"))
    assert first_uid == second_uid == f"{keyed_hash(first['id'])}@calendar.nyayone.local"
    assert first["id"] not in first_uid


@pytest.mark.parametrize("failpoint", ["before_flush", "after_flush", "before_commit"])
def test_negative_n45_n46_event_failpoints_rollback_and_retry_once(ctx, monkeypatch, failpoint):
    client, SessionLocal, (owner, _) = ctx
    key = f"n45-{failpoint}-event"
    before = _calendar_counts(SessionLocal, owner)
    with monkeypatch.context() as patch:
        if failpoint == "before_flush":
            real_flush = Session.flush
            state = {"raised": False}

            def fail_first_flush(session, *args, **kwargs):
                if not state["raised"]:
                    state["raised"] = True
                    raise RuntimeError("n45 before flush")
                return real_flush(session, *args, **kwargs)

            patch.setattr(Session, "flush", fail_first_flush)
        elif failpoint == "after_flush":
            patch.setattr(
                calendar_service,
                "record_audit_event",
                lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("n45 after flush")),
            )
        else:
            real_commit = Session.commit
            state = {"raised": False}

            def fail_first_commit(session):
                if not state["raised"]:
                    state["raised"] = True
                    raise RuntimeError("n45 before commit")
                return real_commit(session)

            patch.setattr(Session, "commit", fail_first_commit)
        failed = _create(client, owner, key)
        assert failed.status_code == 500

    assert _calendar_counts(SessionLocal, owner) == before
    retry = _create(client, owner, key)
    assert retry.status_code == 201
    replay = _create(client, owner, key)
    assert replay.status_code == 201 and replay.json()["id"] == retry.json()["id"]
    counts = _calendar_counts(SessionLocal, owner)
    assert counts["events"] == before["events"] + 1
    assert counts["sources"] == before["sources"] + 1
    assert counts["audit"] == before["audit"] + 1


def test_negative_n48_privacy_scanner_self_test_and_clean_runtime_surfaces(ctx):
    client, SessionLocal, (owner, _) = ctx
    created = client.post(
        "/api/v1/calendar/exports",
        headers={**_claims(owner), "Idempotency-Key": "n48-export"},
        json={"timezone": "Asia/Kolkata"},
    ).json()
    raw = created["feed_url"].rsplit("/", 1)[-1].removesuffix(".ics")
    forbidden = {
        raw,
        "9876543210",
        "student-private@example.test",
        "ENROL-N48-PRIVATE",
        "private-note-n48",
    }
    with SessionLocal() as session:
        db_surface = {
            "token_hashes": list(session.scalars(select(CalendarExportToken.token_hash))),
            "subscriptions": [
                {"id": str(row.id), "status": row.status, "timezone": row.timezone}
                for row in session.scalars(select(CalendarExportSubscription))
            ],
        }
        audit_surface = [
            {"action": row.action, "before": row.before_state, "after": row.after_state}
            for row in session.scalars(select(AuditEvent))
        ]
    clean_surfaces = {
        "database": db_surface,
        "audit": audit_surface,
        "log": redact_sensitive_path(f"/api/v1/public/calendar-feeds/{raw}.ics"),
        "url": "/api/v1/public/calendar-feeds/:token",
        "storage": {},
        "console": [],
        "error": client.get("/api/v1/public/calendar-feeds/" + ("X" * 43) + ".ics").json(),
    }
    assert privacy_canary_hits(clean_surfaces, forbidden) == []

    # The exact same scanner must fail every named surface when seeded.
    planted = {label: {"planted": next(iter(forbidden))} for label in clean_surfaces}
    assert privacy_canary_hits(planted, forbidden) == sorted(planted)
