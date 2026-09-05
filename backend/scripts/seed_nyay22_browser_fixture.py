#!/usr/bin/env python3
"""Seed one private, server-owned NYAY-22 live-browser authority fixture.

CI/test-only: the raw ceremony capability is written exactly once to a
mode-0600 file below RUNNER_TEMP. It is never printed or copied to evidence.
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import re
import stat
import sys
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from sqlalchemy import make_url, select
from sqlalchemy.orm import Session, sessionmaker


BACKEND = Path(__file__).resolve().parents[1]
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from app.core.config import settings  # noqa: E402
from app.core.crypto import encrypt, keyed_hash  # noqa: E402
from app.db.session import get_sessionmaker  # noqa: E402
from app.models.mentor_auth import (  # noqa: E402
    MentorBootstrapAttempt,
    MentorCeremony,
    MentorInvitation,
    MentorProviderResult,
    MentorSubjectConsent,
    TutorProfileOwnershipProof,
)
from app.models.registration import (  # noqa: E402
    StudentProfile,
    StudentRegistration,
    User,
)
from app.models.wave2 import TutorProfile  # noqa: E402
from app.services import mentor_ceremony  # noqa: E402


SCHEMA_VERSION = "nyay22-live-browser-fixture.v1"
OPT_IN_ENV = "NYAY22_BROWSER_FIXTURE_SEED"
_PRIVATE_KEY = bytes.fromhex("22" * 32)
_DATABASE_MARKERS = {"ci", "gate", "qa", "scratch", "test", "testing"}


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _provider_signature(payload: dict[str, Any]) -> str:
    encoded = json.dumps(
        payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True
    ).encode("utf-8")
    return base64.b64encode(
        Ed25519PrivateKey.from_private_bytes(_PRIVATE_KEY).sign(encoded)
    ).decode("ascii")


def seed_server_owned_fixture(
    factory: sessionmaker[Session],
) -> dict[str, str]:
    """Create the minimum authoritative graph needed for verify/exchange."""

    now = _utcnow()
    provider_subject = f"nyay22-live-browser-{uuid.uuid4().hex}"
    authority_domain = f"nyay22-live-authority-{uuid.uuid4().hex}"
    ceremony_id = uuid.uuid4()
    raw_ceremony, seed_ct, seed_version = mentor_ceremony._new_seeded_token(
        "ceremony", ceremony_id
    )
    owner_session_hash = keyed_hash(f"owner-session-{uuid.uuid4().hex}")

    with factory() as db:
        student = User(role="student", status="active")
        mentor = User(role="lawyer", status="active")
        db.add_all([student, mentor])
        db.flush()
        registration = StudentRegistration(
            user_id=student.id,
            first_name="Synthetic",
            middle_name=None,
            last_name="Fixture",
            mobile_hash=keyed_hash(f"browser-mobile-{uuid.uuid4().hex}"),
            mobile_ct=encrypt("9000000022"),
            dob_hash=keyed_hash(f"browser-dob-{uuid.uuid4().hex}"),
            dob_ct=encrypt("2000-01-01"),
            dob_hash_state="verified",
            key_version="v1",
            status="active",
            is_minor=False,
        )
        db.add(registration)
        db.flush()
        db.add(StudentProfile(registration_id=registration.id, profile_version=1))
        tutor = TutorProfile(
            user_id=mentor.id,
            display_name="Synthetic Mentor",
            status="active",
            verified_identity=True,
            verified_credentials=True,
        )
        db.add(tutor)
        db.flush()
        proof = TutorProfileOwnershipProof(
            user_id=mentor.id,
            tutor_profile_id=tutor.id,
            provider_class="nyayone_reviewed_identity",
            assurance_class="high",
            policy_version="mentor-proof.v1",
            provider_subject_hash=keyed_hash(provider_subject),
            evidence_digest="a" * 64,
            key_version="v1",
            state="current",
            issued_at=now,
            expires_at=now + timedelta(hours=1),
        )
        invitation = MentorInvitation(
            subject_registration_id=registration.id,
            initiator_user_id=student.id,
            initiator_session_hash=owner_session_hash,
            creation_idempotency_hash=keyed_hash(f"invitation-{uuid.uuid4().hex}"),
            purpose_policy_version="mentor-purpose-policy.v1",
            mentor_match_hash=keyed_hash(provider_subject),
            authority_domain_hash=keyed_hash(authority_domain),
            mentor_role="tutor",
            purpose_code="student_guidance",
            consent_version="mentor-consent.v1",
            acceptance_text_version="mentor-acceptance.v1",
            disclosure_classes=["display_identity", "preferred_language", "city"],
            state="pending",
            expires_at=now + timedelta(hours=1),
        )
        db.add_all([proof, invitation])
        db.flush()
        subject_consent = MentorSubjectConsent(
            invitation_id=invitation.id,
            subject_registration_id=registration.id,
            granted_by_user_id=student.id,
            granting_session_hash=owner_session_hash,
            grant_idempotency_hash=keyed_hash(f"subject-consent-{uuid.uuid4().hex}"),
            purpose_policy_version="mentor-purpose-policy.v1",
            guardian_consent_id=None,
            purpose_code="student_guidance",
            version="mentor-consent.v1",
            disclosure_classes=["display_identity", "preferred_language", "city"],
            status="granted",
            recorded_at=now,
            expires_at=now + timedelta(hours=1),
        )
        bootstrap = MentorBootstrapAttempt(
            token_hash=keyed_hash(f"consumed-bootstrap-{uuid.uuid4().hex}"),
            requested_role="tutor",
            purpose_code="student_guidance",
            state="consumed",
            expires_at=now + timedelta(minutes=10),
            consumed_at=now,
        )
        db.add(bootstrap)
        db.flush()
        ceremony = MentorCeremony(
            id=ceremony_id,
            bootstrap_attempt_id=bootstrap.id,
            token_hash=mentor_ceremony._token_hash(raw_ceremony),
            token_seed_ct=seed_ct,
            token_seed_key_version=seed_version,
            challenge_hash=keyed_hash(f"challenge-{uuid.uuid4().hex}"),
            intent="mentor_session",
            requested_role="tutor",
            purpose_code="student_guidance",
            privacy_notice_version="mentor-privacy.v1",
            state="challenge_issued",
            generation=1,
            actor_user_id=mentor.id,
            tutor_profile_id=tutor.id,
            ownership_proof_id=proof.id,
            invitation_id=invitation.id,
            expires_at=now + timedelta(minutes=10),
        )
        db.add_all([subject_consent, ceremony])
        db.flush()
        mentor_ceremony._add_provider_transaction(
            db,
            ceremony=ceremony,
            requested_role="tutor",
            raw_nonce=mentor_ceremony._random_token(),
            raw_correlation=mentor_ceremony._random_token(),
        )
        db.commit()

        transaction = mentor_ceremony.claim_provider_start(
            db, ceremony_id=ceremony.id
        )
        provider = db.scalar(
            select(MentorProviderResult).where(
                MentorProviderResult.ceremony_id == ceremony.id
            )
        )
        if provider is None:
            raise RuntimeError("NYAY22_BROWSER_FIXTURE_PROVIDER_MISSING")
        settled_at = _utcnow()
        deadline = provider.expires_at
        if deadline.tzinfo is None:
            deadline = deadline.replace(tzinfo=timezone.utc)
        payload: dict[str, Any] = {
            **transaction,
            "providerSubject": provider_subject,
            "accountBindingClass": "provider_account",
            "userPresenceApproved": True,
            "evidenceDigest": "a" * 64,
            "issuedAt": settled_at.isoformat(),
            "expiresAt": min(settled_at + timedelta(seconds=20), deadline).isoformat(),
        }
        mentor_ceremony.settle_provider_result(
            db,
            ceremony_id=ceremony.id,
            payload=payload,
            signature_b64=_provider_signature(payload),
        )

    return {"schemaVersion": SCHEMA_VERSION, "ceremonyCookie": raw_ceremony}


def write_private_fixture(
    destination: Path,
    fixture: dict[str, str],
    *,
    allowed_root: Path,
) -> None:
    root = allowed_root.resolve(strict=True)
    target = destination.resolve(strict=False)
    try:
        target.relative_to(root)
    except ValueError as exc:
        raise ValueError("NYAY22_BROWSER_FIXTURE_OUTPUT_OUTSIDE_RUNNER_TEMP") from exc
    if target == root or target.parent == target:
        raise ValueError("NYAY22_BROWSER_FIXTURE_OUTPUT_INVALID")
    if set(fixture) != {"schemaVersion", "ceremonyCookie"} or (
        fixture.get("schemaVersion") != SCHEMA_VERSION
        or re.fullmatch(r"[0-9a-f]{64}", fixture.get("ceremonyCookie", "")) is None
    ):
        raise ValueError("NYAY22_BROWSER_FIXTURE_PAYLOAD_INVALID")
    target.parent.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(
        target,
        os.O_WRONLY | os.O_CREAT | os.O_EXCL,
        stat.S_IRUSR | stat.S_IWUSR,
    )
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            json.dump(fixture, stream, sort_keys=True, separators=(",", ":"))
            stream.write("\n")
    except Exception:
        target.unlink(missing_ok=True)
        raise


def _safe_live_database() -> None:
    if os.environ.get(OPT_IN_ENV) != "1" or settings.app_env not in {
        "test",
        "testing",
    }:
        raise RuntimeError("NYAY22_BROWSER_FIXTURE_SEED_NOT_AUTHORIZED")
    try:
        parsed = make_url(settings.database_url)
        host = parsed.host or ""
    except Exception as exc:
        raise RuntimeError("NYAY22_BROWSER_FIXTURE_DATABASE_INVALID") from exc
    database = (parsed.database or "").casefold()
    tokens = set(re.split(r"[^a-z0-9]+", database))
    if (
        parsed.get_backend_name() != "postgresql"
        or host not in {"127.0.0.1", "::1"}
        or parsed.query
        or not (tokens & _DATABASE_MARKERS)
    ):
        raise RuntimeError("NYAY22_BROWSER_FIXTURE_DATABASE_NOT_ISOLATED")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True, type=Path)
    arguments = parser.parse_args()
    try:
        _safe_live_database()
        runner_temp = os.environ.get("RUNNER_TEMP", "").strip()
        if not runner_temp:
            raise RuntimeError("NYAY22_BROWSER_FIXTURE_RUNNER_TEMP_REQUIRED")
        fixture = seed_server_owned_fixture(get_sessionmaker())
        write_private_fixture(
            arguments.output, fixture, allowed_root=Path(runner_temp)
        )
    except Exception:
        print(
            '{"code":"NYAY22_BROWSER_FIXTURE_SEED_FAILED","status":"BLOCKED"}',
            file=sys.stderr,
        )
        return 78
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
