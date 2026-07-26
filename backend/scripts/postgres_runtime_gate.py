"""PostgreSQL-only runtime gate for lockout concurrency and audit immutability."""
from __future__ import annotations

import argparse
import json
import threading
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError

from app.db.models.audit import AuditEvent
from app.db.session import get_engine, get_sessionmaker
from app.models.registration import OtpChallenge
from app.schemas.registration import StudentRegisterRequest
from app.services import otp_outbox, otp_service
from app.services.otp_sender import CapturingSender
from app.services.registration_service import register_student


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    engine = get_engine()
    if engine.dialect.name != "postgresql":
        raise SystemExit("postgres_runtime_gate requires PostgreSQL")
    factory = get_sessionmaker()
    sender = CapturingSender()
    now = datetime.now(timezone.utc)
    with factory() as session:
        created = register_student(
            session,
            StudentRegisterRequest(
                first_name="Concurrency",
                last_name="Probe",
                mobile="9666666666",
                dob="2000-01-01",
                consent={"accepted": True, "policy_version": "qa"},
            ),
            idempotency_key="qa-postgres-concurrency",
            now=now,
        )
        session.commit()
        assert created.delivery is not None
        otp_outbox.run_delivery(
            session, created.delivery, sender, raise_on_failure=True
        )
        registration_id = created.registration.id

    barrier = threading.Barrier(3)
    outcomes: list[str] = []
    failures: list[str] = []
    lock = threading.Lock()

    def attempt() -> None:
        try:
            barrier.wait(timeout=5)
            with factory() as session:
                try:
                    otp_service.verify(
                        session,
                        registration_id,
                        "invalid",
                        now,
                        purpose="signup",
                    )
                except otp_service.OtpError as exc:
                    with lock:
                        outcomes.append(exc.code)
        except Exception as exc:  # pragma: no cover - emitted in gate evidence
            with lock:
                failures.append(f"{type(exc).__name__}:{exc}")

    threads = [threading.Thread(target=attempt) for _ in range(3)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=10)

    with factory() as session:
        challenge = session.scalar(
            select(OtpChallenge).where(
                OtpChallenge.registration_id == registration_id,
                OtpChallenge.consumed_at.is_(None),
            )
        )
        audit_id = session.scalar(
            select(AuditEvent.id).where(AuditEvent.resource_id == registration_id)
        )
        attempts = challenge.attempts if challenge else None
        locked = bool(challenge and challenge.locked_until)

    trigger_blocked = False
    try:
        with engine.begin() as connection:
            connection.execute(
                text("UPDATE audit_events SET action='tampered' WHERE id=:id"),
                {"id": audit_id},
            )
    except DBAPIError:
        trigger_blocked = True

    report = {
        "dialect": engine.dialect.name,
        "concurrent_outcomes": sorted(outcomes),
        "thread_failures": failures,
        "persisted_attempts": attempts,
        "locked_until_present": locked,
        "audit_update_blocked_by_database_trigger": trigger_blocked,
    }
    payload = json.dumps(report, indent=2)
    print(payload)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(payload + "\n", encoding="utf-8")
    if (
        failures
        or len(outcomes) != 3
        or attempts != 3
        or not locked
        or not trigger_blocked
    ):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
