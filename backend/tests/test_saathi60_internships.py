"""SAATHI-60 internship catalogue, saved persistence, and privacy proof."""
from __future__ import annotations

import json
import os
import threading
import uuid

import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

import app.models  # noqa: F401
from app.db.models.audit import AuditEvent
from app.db.session import get_session
from app.models.internships import InternshipListing, SavedInternship
from app.models.registration import User
from app.services import internship_service
from tests import apptemplate, dbtemplate


def _claims(user_id: uuid.UUID, roles: tuple[str, ...] = ("student",)) -> dict[str, str]:
    return {
        "X-Actor-Claims": json.dumps(
            {"sub": str(user_id), "roles": list(roles)}, separators=(",", ":")
        )
    }


@pytest.fixture(scope="module")
def _mounted():
    return apptemplate.mounted_app()


@pytest.fixture()
def ctx(_mounted):
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    dbtemplate.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False, class_=Session)

    def request_session():
        session = factory()
        try:
            yield session
        except Exception:
            session.rollback()
            raise
        else:
            session.rollback()
        finally:
            session.close()

    app, client = _mounted
    apptemplate.fresh(app, client)
    app.dependency_overrides[get_session] = request_session
    with factory() as session:
        internship_service.seed_internship_catalogue(session)
        student_a = User(role="student", status="active")
        student_b = User(role="student", status="active")
        lawyer = User(role="lawyer", status="active")
        session.add_all([student_a, student_b, lawyer])
        session.commit()
        identities = (student_a.id, student_b.id, lawyer.id)
    yield client, factory, identities
    engine.dispose()


def test_public_catalogue_has_deterministic_structured_provenance(ctx):
    client, _, _ = ctx
    response = client.get("/api/v1/internships")
    assert response.status_code == 200
    payload = response.json()
    assert payload["total"] == 3
    assert payload["page"] == 1 and payload["page_size"] == 20
    assert [item["id"] for item in payload["items"]] == ["cam", "menon", "vidhi"]

    cam, menon, vidhi = payload["items"]
    assert [item["role"] for item in (cam, menon, vidhi)] == [
        "Summer Associate, disputes",
        "Judicial research assistant",
        "Research fellowship, policy",
    ]
    assert cam["application_deadline"] == "2027-07-09"
    assert cam["stipend_monthly_paise"] == 4_000_000
    assert cam["verification_status"] == "verified"
    assert cam["source"]["name"] == "Cyril Amarchand Mangaldas careers"
    assert cam["source"]["url"].startswith("https://")
    assert cam["source"]["retrieved_at"] and cam["source"]["verified_at"]
    for sample in (menon, vidhi):
        assert sample["verification_status"] == "unverified"
        assert sample["source"]["verified_at"] is None
    assert vidhi["stipend_monthly_paise"] is None


def test_verified_only_returns_exactly_cam(ctx):
    client, _, _ = ctx
    response = client.get("/api/v1/internships", params={"verified_only": "true"})
    assert response.status_code == 200
    assert response.json()["total"] == 1
    assert [item["id"] for item in response.json()["items"]] == ["cam"]


def test_detail_slug_boundaries_unknown_and_inactive(ctx):
    client, factory, _ = ctx
    detail = client.get("/api/v1/internships/menon")
    assert detail.status_code == 200
    assert detail.json()["organisation"] == "Chambers of Sr. Adv. R. Menon"
    assert client.get("/api/v1/internships/unknown").status_code == 404
    for malformed in ("A", "x" * 65, "cam_1"):
        assert client.get(f"/api/v1/internships/{malformed}").status_code == 422
    # HTTP clients normalise dot segments before route matching; rejection is
    # still fail-closed even though validation therefore occurs at the router.
    assert client.get("/api/v1/internships/../cam").status_code in (404, 422)

    with factory() as session:
        vidhi = session.scalar(
            select(InternshipListing).where(InternshipListing.slug == "vidhi")
        )
        assert vidhi is not None
        vidhi.active = False
        session.commit()
    assert client.get("/api/v1/internships/vidhi").status_code == 404
    assert [item["id"] for item in client.get("/api/v1/internships").json()["items"]] == [
        "cam",
        "menon",
    ]


def test_saved_routes_require_student_authentication(ctx):
    client, _, (_, _, lawyer_id) = ctx
    assert client.get("/api/v1/student/internships/saved").status_code == 401
    assert (
        client.put(
            "/api/v1/student/internships/cam/saved",
            headers=_claims(lawyer_id, ("lawyer",)),
        ).status_code
        == 403
    )


def test_save_replay_cross_user_isolation_and_private_audit(ctx):
    client, factory, (student_a, student_b, _) = ctx
    first = client.put(
        "/api/v1/student/internships/menon/saved", headers=_claims(student_a)
    )
    replay = client.put(
        "/api/v1/student/internships/menon/saved", headers=_claims(student_a)
    )
    assert first.status_code == replay.status_code == 200
    assert first.json() == replay.json() == {"saved": True, "listing_id": "menon"}
    assert [
        item["id"]
        for item in client.get(
            "/api/v1/student/internships/saved", headers=_claims(student_a)
        ).json()["items"]
    ] == ["menon"]
    assert client.get(
        "/api/v1/student/internships/saved", headers=_claims(student_b)
    ).json()["items"] == []

    with factory() as session:
        assert session.scalar(select(func.count()).select_from(SavedInternship)) == 1
        events = list(
            session.scalars(
                select(AuditEvent).where(AuditEvent.action == "internship.saved")
            ).all()
        )
        assert len(events) == 1
        assert events[0].actor_user_id == student_a
        assert events[0].after_state == {"listing_id": "menon", "saved": True}
        serialized = json.dumps(events[0].after_state).lower()
        assert not any(
            forbidden in serialized
            for forbidden in ("mobile", "otp", "session", "token", "email")
        )


def test_unsave_is_idempotent_and_audited_only_once(ctx):
    client, factory, (student_a, _, _) = ctx
    client.put("/api/v1/student/internships/cam/saved", headers=_claims(student_a))
    first = client.delete(
        "/api/v1/student/internships/cam/saved", headers=_claims(student_a)
    )
    replay = client.delete(
        "/api/v1/student/internships/cam/saved", headers=_claims(student_a)
    )
    assert first.json() == replay.json() == {"saved": False, "listing_id": "cam"}
    with factory() as session:
        assert session.scalar(
            select(func.count())
            .select_from(SavedInternship)
            .where(SavedInternship.user_id == student_a)
        ) == 0
        assert session.scalar(
            select(func.count())
            .select_from(AuditEvent)
            .where(AuditEvent.action == "internship.unsaved")
        ) == 1


def test_unknown_save_never_mutates(ctx):
    client, factory, (student_a, _, _) = ctx
    response = client.put(
        "/api/v1/student/internships/missing/saved", headers=_claims(student_a)
    )
    assert response.status_code == 404
    with factory() as session:
        assert session.scalar(select(func.count()).select_from(SavedInternship)) == 0
        assert session.scalar(
            select(func.count())
            .select_from(AuditEvent)
            .where(AuditEvent.action.like("internship.%"))
        ) == 0


def test_commit_failure_rolls_back_save_and_audit(ctx, monkeypatch):
    _, factory, (student_a, _, _) = ctx
    session = factory()
    listing = internship_service.listing_or_none(session, "cam")
    assert listing is not None

    def fail_commit() -> None:
        raise RuntimeError("injected commit failure")

    monkeypatch.setattr(session, "commit", fail_commit)
    with pytest.raises(RuntimeError, match="injected commit failure"):
        internship_service.save_listing(
            session, user_id=student_a, listing=listing
        )
    session.rollback()
    session.close()
    with factory() as verification:
        assert verification.scalar(select(func.count()).select_from(SavedInternship)) == 0
        assert verification.scalar(
            select(func.count())
            .select_from(AuditEvent)
            .where(AuditEvent.action == "internship.saved")
        ) == 0


def test_parallel_save_is_one_row_and_one_audit_on_postgresql():
    """Optional target-runtime proof; requires an explicitly isolated QA DB."""
    url = os.getenv("SAATHI60_POSTGRES_TEST_URL")
    if not url:
        pytest.skip("SAATHI60_POSTGRES_TEST_URL is not configured")
    database = (make_url(url).database or "").lower()
    assert "saathi60" in database and "qa" in database, database
    engine = create_engine(url, pool_size=4, max_overflow=0)
    factory = sessionmaker(bind=engine, expire_on_commit=False, class_=Session)
    user_id = uuid.uuid4()
    with factory() as session:
        internship_service.seed_internship_catalogue(session)
        session.add(User(id=user_id, role="student", status="active"))
        session.commit()

    barrier = threading.Barrier(2)
    outcomes: list[bool] = []
    failures: list[BaseException] = []

    def worker() -> None:
        try:
            with factory() as session:
                listing = internship_service.listing_or_none(session, "cam")
                assert listing is not None
                barrier.wait(timeout=10)
                outcomes.append(
                    internship_service.save_listing(
                        session, user_id=user_id, listing=listing
                    )
                )
        except BaseException as exc:  # captured for assertion in main thread
            failures.append(exc)

    threads = [threading.Thread(target=worker) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=20)
    assert failures == []
    assert sorted(outcomes) == [False, True]
    with factory() as session:
        assert session.scalar(
            select(func.count())
            .select_from(SavedInternship)
            .where(SavedInternship.user_id == user_id)
        ) == 1
        assert session.scalar(
            select(func.count())
            .select_from(AuditEvent)
            .where(
                AuditEvent.actor_user_id == user_id,
                AuditEvent.action == "internship.saved",
            )
        ) == 1
        user = session.get(User, user_id)
        assert user is not None
        session.delete(user)
        session.commit()
    engine.dispose()
