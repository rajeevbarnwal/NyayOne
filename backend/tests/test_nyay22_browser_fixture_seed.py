"""Fail-closed contracts for the private NYAY-22 live-browser seed fixture."""

from __future__ import annotations

import json
import re
import stat

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.models.mentor_auth import (
    MentorCeremony,
    MentorInvitation,
    MentorProviderResult,
    MentorSubjectConsent,
    TutorProfileOwnershipProof,
)
from app.services.mentor_ceremony import _token_hash
from scripts.seed_nyay22_browser_fixture import (
    seed_server_owned_fixture,
    write_private_fixture,
)
from tests import dbtemplate


def test_seed_is_server_owned_and_returns_only_the_private_cookie_capability(engine):
    dbtemplate.reset_to_empty_schema(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False, class_=Session)

    fixture = seed_server_owned_fixture(factory)

    assert set(fixture) == {"schemaVersion", "ceremonyCookie"}
    assert fixture["schemaVersion"] == "nyay22-live-browser-fixture.v1"
    assert re.fullmatch(r"[0-9a-f]{64}", fixture["ceremonyCookie"])
    with factory() as db:
        ceremony = db.scalar(
            select(MentorCeremony).where(
                MentorCeremony.token_hash == _token_hash(fixture["ceremonyCookie"])
            )
        )
        assert ceremony is not None and ceremony.state == "challenge_issued"
        assert db.scalar(
            select(MentorProviderResult.state).where(
                MentorProviderResult.ceremony_id == ceremony.id
            )
        ) == "verified"
        assert db.get(TutorProfileOwnershipProof, ceremony.ownership_proof_id).state == "current"
        assert db.get(MentorInvitation, ceremony.invitation_id).state == "pending"
        invitation = db.get(MentorInvitation, ceremony.invitation_id)
        subject_consent = db.scalar(
            select(MentorSubjectConsent).where(
                MentorSubjectConsent.invitation_id == ceremony.invitation_id
            )
        )
        assert subject_consent is not None and subject_consent.status == "granted"
        assert subject_consent.granting_session_hash == invitation.initiator_session_hash


def test_private_fixture_writer_is_exclusive_mode_0600_and_root_confined(tmp_path):
    fixture = {
        "schemaVersion": "nyay22-live-browser-fixture.v1",
        "ceremonyCookie": "a" * 64,
    }
    destination = tmp_path / "fixture.json"

    write_private_fixture(destination, fixture, allowed_root=tmp_path)

    assert stat.S_IMODE(destination.stat().st_mode) == 0o600
    assert json.loads(destination.read_text(encoding="utf-8")) == fixture
    with pytest.raises(FileExistsError):
        write_private_fixture(destination, fixture, allowed_root=tmp_path)
    with pytest.raises(
        ValueError,
        match="NYAY22_BROWSER_FIXTURE_OUTPUT_OUTSIDE_RUNNER_TEMP",
    ):
        write_private_fixture(
            tmp_path.parent / "outside.json",
            fixture,
            allowed_root=tmp_path,
        )
