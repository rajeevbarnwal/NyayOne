#!/usr/bin/env python3
"""Private control plane for the isolated NYAY-5 production-browser gate.

The CLI writes database credentials and synthetic denial-session tokens only to
caller-selected mode-0600 files outside uploadable evidence. Standard output is
aggregate-only. Every destructive operation revalidates a literal loopback
PostgreSQL control URL and an exact marker-owned random database name.
"""

from __future__ import annotations

import argparse
from datetime import date, datetime, timedelta, timezone
import json
import os
from pathlib import Path
import re
import uuid

from sqlalchemy import create_engine, text
from sqlalchemy.engine import URL
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import NullPool

from scripts import nyay5_postgres_profile_gate as postgres_gate


SCRATCH_PREFIX = "nyay5_profile_browser_"
DENIAL_FIXTURE_STATES = ("expired", "revoked", "deleted", "wrong_role")
M01_FIXTURE_SESSION_COUNT = 2
_SCRATCH_NAME = re.compile(rf"{re.escape(SCRATCH_PREFIX)}[0-9a-f]{{32}}\Z")


def validated_control_url(raw: str) -> URL:
    try:
        return postgres_gate._safe_local_postgres_url(raw)
    except postgres_gate.Blocked as exc:
        raise ValueError("literal loopback PostgreSQL control URL required") from exc


def valid_scratch_name(name: str) -> bool:
    return bool(_SCRATCH_NAME.fullmatch(name or ""))


def _write_private_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    flags = os.O_WRONLY | os.O_CREAT | os.O_TRUNC | getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(path, flags, 0o600)
    try:
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8", closefd=False) as handle:
            json.dump(value, handle, separators=(",", ":"), sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
    finally:
        os.close(descriptor)


def _read_private_json(path: Path) -> dict[str, object]:
    mode = path.stat().st_mode & 0o777
    if mode & 0o077:
        raise ValueError("private control file permissions rejected")
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError("private control file shape rejected")
    return value


def create_scratch(control_raw: str, state_path: Path) -> None:
    base = validated_control_url(control_raw)
    baseline = sorted(postgres_gate._scratch_database_inventory(base))
    name = f"{SCRATCH_PREFIX}{uuid.uuid4().hex}"
    if not valid_scratch_name(name):
        raise ValueError("generated scratch name rejected")
    scratch_url = postgres_gate._create_scratch(base, name)
    try:
        engine = create_engine(scratch_url, poolclass=NullPool)
        try:
            with engine.begin() as connection:
                connection.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
                if connection.scalar(
                    text("SELECT count(*) FROM pg_extension WHERE extname = 'vector'")
                ) != 1:
                    raise RuntimeError("pgvector extension unavailable")
        finally:
            engine.dispose()
        _write_private_json(
            state_path,
            {
                "baseline": baseline,
                "database_name": name,
                "database_url": scratch_url,
            },
        )
    except Exception:
        postgres_gate._drop_scratch(base, name)
        raise


def drop_scratch(control_raw: str, state_path: Path) -> bool:
    base = validated_control_url(control_raw)
    state = _read_private_json(state_path)
    name = state.get("database_name")
    baseline = state.get("baseline")
    if not isinstance(name, str) or not valid_scratch_name(name):
        raise ValueError("unowned scratch database name rejected")
    if not isinstance(baseline, list) or not all(
        isinstance(item, str) and item.startswith(postgres_gate.SCRATCH_PREFIX)
        for item in baseline
    ):
        raise ValueError("scratch baseline inventory rejected")
    postgres_gate._drop_scratch(base, name)
    final = postgres_gate._scratch_database_inventory(base)
    matched = final == set(baseline) and name not in final
    if not matched:
        raise RuntimeError("scratch database cleanup inventory mismatch")
    state_path.unlink(missing_ok=True)
    return True


def seed_denial_fixtures(database_raw: str, output_path: Path) -> None:
    url = validated_control_url(database_raw)
    if not valid_scratch_name(url.database or ""):
        raise ValueError("denial fixtures require an owned browser scratch database")
    engine = create_engine(url, poolclass=NullPool)
    factory = sessionmaker(bind=engine, class_=Session, expire_on_commit=False)
    now = datetime.now(timezone.utc)
    try:
        with engine.connect() as connection:
            revision = connection.scalar(text("SELECT version_num FROM alembic_version"))
        if revision != postgres_gate.PINNED_HEAD:
            raise ValueError("denial fixtures require the exact application head")

        from app.core.crypto import encrypt, keyed_hash
        from app.models.registration import (
            AuthSession,
            StudentProfile,
            StudentRegistration,
            User,
        )
        from app.models.wave2 import (
            TutorAvailabilitySlot,
            TutorProfile,
            TutoringSession,
        )

        fixtures: dict[str, dict[str, str]] = {}
        with factory.begin() as session:
            for index, state in enumerate(DENIAL_FIXTURE_STATES):
                role = "moderator" if state == "wrong_role" else "student"
                user = User(role=role, status="active")
                session.add(user)
                session.flush()
                if state != "wrong_role":
                    registration_id = uuid.uuid4()
                    erased = state == "deleted"
                    mobile = f"90000000{index:02d}"
                    dob = date(2000, 1, 1).isoformat()
                    registration = StudentRegistration(
                        id=registration_id,
                        user_id=user.id,
                        first_name="Synthetic",
                        middle_name=None,
                        last_name="Boundary",
                        mobile_hash=(
                            f"[erased]:{registration_id.hex}"
                            if erased else keyed_hash(mobile)
                        ),
                        mobile_ct="[erased]" if erased else encrypt(mobile),
                        dob_hash=(
                            f"[erased]:{registration_id.hex}"
                            if erased else keyed_hash(dob)
                        ),
                        dob_ct="[erased]" if erased else encrypt(dob),
                        dob_hash_state="erased" if erased else "verified",
                        key_version="v1",
                        status="deleted" if state == "deleted" else "active",
                        is_minor=False,
                        deleted_at=now if state == "deleted" else None,
                    )
                    session.add(registration)
                    session.flush()
                    if not erased:
                        session.add(StudentProfile(registration_id=registration.id))
                token = f"nyay5-browser-denial-{state}-{uuid.uuid4().hex}"
                session.add(
                    AuthSession(
                        user_id=user.id,
                        token_hash=keyed_hash(token),
                        status="revoked" if state == "revoked" else "active",
                        expires_at=(
                            now - timedelta(seconds=1)
                            if state == "expired"
                            else now + timedelta(hours=1)
                        ),
                        last_seen_at=now,
                        revoked_at=now if state == "revoked" else None,
                    )
                )
                fixtures[state] = {"token": token}

            # M-01 uses a real server-issued administrator session and two
            # independent, already-ended targets. The bearer and opaque ids
            # leave this control process only through the caller-selected 0600
            # file; stdout remains aggregate-only.
            admin = User(role="admin", status="active")
            tutor_user = User(role="lawyer", status="active")
            students = [
                User(role="student", status="active")
                for _ in range(M01_FIXTURE_SESSION_COUNT)
            ]
            session.add_all([admin, tutor_user, *students])
            session.flush()
            admin_token = f"nyay5-browser-m01-admin-{uuid.uuid4().hex}"
            session.add(
                AuthSession(
                    user_id=admin.id,
                    token_hash=keyed_hash(admin_token),
                    status="active",
                    expires_at=now + timedelta(hours=1),
                    last_seen_at=now,
                )
            )
            tutor = TutorProfile(
                user_id=tutor_user.id,
                display_name="Synthetic M-01 Boundary Tutor",
                headline="Private production-browser control fixture",
                experience_years=1,
                verified_identity=True,
                verified_credentials=True,
                status="active",
            )
            session.add(tutor)
            session.flush()
            m01_session_ids: list[str] = []
            for index, student in enumerate(students, start=1):
                start_utc = now - timedelta(hours=2 * index)
                end_utc = start_utc + timedelta(minutes=45)
                slot = TutorAvailabilitySlot(
                    tutor_id=tutor.id,
                    start_utc=start_utc,
                    end_utc=end_utc,
                    iana_timezone="Asia/Kolkata",
                    status="booked",
                )
                session.add(slot)
                session.flush()
                target = TutoringSession(
                    slot_id=slot.id,
                    tutor_id=tutor.id,
                    student_user_id=student.id,
                    start_utc=start_utc,
                    end_utc=end_utc,
                    iana_timezone="Asia/Kolkata",
                    status="confirmed",
                    version=1,
                )
                session.add(target)
                session.flush()
                m01_session_ids.append(str(target.id))
        _write_private_json(
            output_path,
            {
                "fixtures": fixtures,
                "m01": {
                    "admin_session_token": admin_token,
                    "session_ids": m01_session_ids,
                },
            },
        )
    finally:
        engine.dispose()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    create = subparsers.add_parser("create")
    create.add_argument("--control-url", required=True)
    create.add_argument("--state-file", required=True)
    drop = subparsers.add_parser("drop")
    drop.add_argument("--control-url", required=True)
    drop.add_argument("--state-file", required=True)
    seed = subparsers.add_parser("seed-denials")
    seed.add_argument("--database-url", required=True)
    seed.add_argument("--output", required=True)
    args = parser.parse_args()
    if args.command == "create":
        create_scratch(args.control_url, Path(args.state_file))
        print(json.dumps({"created": True}, sort_keys=True))
    elif args.command == "drop":
        matched = drop_scratch(args.control_url, Path(args.state_file))
        print(json.dumps({"inventory_match": matched, "removed": True}, sort_keys=True))
    else:
        seed_denial_fixtures(args.database_url, Path(args.output))
        print(
            json.dumps(
                {
                    "denial_fixtures": len(DENIAL_FIXTURE_STATES),
                    "m01_sessions": M01_FIXTURE_SESSION_COUNT,
                    "seeded": True,
                },
                sort_keys=True,
            )
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
