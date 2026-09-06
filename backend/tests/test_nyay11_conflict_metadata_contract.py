"""Preserve the distinct canonical and compatibility review wire contracts.

The canonical authority command has no optimistic profile-version selector.
Only the compatibility command accepts that selector and may return scoped
conflict metadata. These are preservation proofs, not a new response contract.
"""
from datetime import timedelta
import inspect

import pytest

from tests.test_nyay11_runtime import ctx, email_verified  # noqa: F401


@pytest.fixture()
def review_http(ctx, monkeypatch):
    from app.api.v1 import auth_student, student_authority as api
    from app.core.config import settings
    from app.db.session import get_session
    from app.services import student_authority as service
    from tests import apptemplate

    ctx["reviewer"].role = "legal_reviewer"
    ctx["db"].commit()
    email_verified(ctx, ctx["owner"])
    email_verified(ctx, ctx["reviewer"])
    service.request_review(
        ctx["db"], ctx["owner"].id, ctx["tokens"][ctx["owner"].id],
        key="metadata-review-request", now=ctx["now"],
    )
    ctx["db"].commit()
    app, client = apptemplate.mounted_app(exception_handlers=True)
    apptemplate.fresh(app, client)
    app.dependency_overrides[get_session] = lambda: ctx["db"]
    monkeypatch.setattr(auth_student, "_now", lambda: ctx["now"])
    monkeypatch.setattr(api, "_now", lambda: ctx["now"])
    monkeypatch.setattr(settings, "cors_origins", ["http://testserver"])
    client.cookies.set(
        settings.auth_session_cookie_name, ctx["tokens"][ctx["reviewer"].id],
    )
    try:
        yield {
            "client": client,
            "ctx": ctx,
            "headers": {
                "Origin": "http://testserver",
                "Idempotency-Key": "metadata-review-command",
            },
            "legacy_path": "/api/v1/auth/student/verification/status",
            "canonical_path": "/api/v1/auth/student/authority/institutional/review",
            "legacy_payload": {
                "registration_id": str(ctx["reg"].id),
                "status": "verified",
                "expected_profile_version": 999,
            },
        }
    finally:
        app.dependency_overrides.clear()
        client.cookies.clear()


def assign_reviewer(review_http):
    from app.services import student_authority as service

    ctx = review_http["ctx"]
    service.assign_reviewer(
        ctx["db"], ctx["admin"].id, ctx["tokens"][ctx["admin"].id],
        reviewer_id=ctx["reviewer"].id, institution="example",
        expires_at=ctx["now"] + timedelta(days=1), now=ctx["now"],
        key="metadata-review-assignment",
    )
    ctx["db"].commit()


def legacy_request(review_http, payload=None):
    return review_http["client"].post(
        review_http["legacy_path"], headers=review_http["headers"],
        json=payload if payload is not None else review_http["legacy_payload"],
    )


def test_canonical_schema_cannot_supply_a_profile_version():
    from pydantic import ValidationError
    from app.api.v1.student_authority import ReviewBody
    from app.services import student_authority as service

    assert set(ReviewBody.model_fields) == {"registration_id", "approve"}
    assert ReviewBody.model_config["extra"] == "forbid"
    assert inspect.signature(service.review).parameters["expected_profile_version"].default is None
    with pytest.raises(ValidationError) as rejected:
        ReviewBody.model_validate({
            "registration_id": "00000000-0000-4000-8000-000000000001",
            "approve": True,
            "expected_profile_version": 999,
        })
    assert [(row["loc"], row["type"]) for row in rejected.value.errors()] == [
        (("expected_profile_version",), "extra_forbidden"),
    ]


def test_canonical_http_rejects_version_and_delegates_without_conflict_selector(review_http, monkeypatch):
    from app.services import student_authority as service

    assign_reviewer(review_http)
    calls = []
    original = service.review

    def observe_review(*args, **kwargs):
        bound = inspect.signature(original).bind(*args, **kwargs)
        bound.apply_defaults()
        calls.append((set(kwargs), bound.arguments["expected_profile_version"]))
        return original(*args, **kwargs)

    monkeypatch.setattr(service, "review", observe_review)
    payload = {
        "registration_id": str(review_http["ctx"]["reg"].id),
        "approve": True,
    }
    rejected = review_http["client"].post(
        review_http["canonical_path"], headers=review_http["headers"],
        json={**payload, "expected_profile_version": 999},
    )
    assert rejected.status_code == 422
    assert "current_profile_version" not in rejected.text
    assert calls == []
    result = review_http["client"].post(
        review_http["canonical_path"], headers=review_http["headers"], json=payload,
    )
    assert result.status_code == 200
    assert len(calls) == 1
    assert "expected_profile_version" not in calls[0][0]
    assert calls[0][1] is None
    assert result.json()["institutional_state"] == "VERIFIED"
    assert set(result.json()) == {
        "policy_version", "guardian_state", "institutional_state", "version",
        "access_mode", "reverification_required",
    }


def test_unassigned_compatibility_reviewer_cannot_obtain_conflict_metadata(review_http):
    denied = legacy_request(review_http)
    assert denied.status_code == 403
    assert denied.json() == {
        "detail": {"code": "authority_denied", "message": "Request failed"},
        "request_id": None,
    }
    assert "current_profile_version" not in denied.text


def test_foreign_assignment_cannot_obtain_compatibility_conflict_metadata(review_http):
    from sqlalchemy import select
    from app.models.student_authority import InstitutionalReviewerAssignment

    assign_reviewer(review_http)
    # Adversarial persisted scope fixture, as in the inherited runtime oracle:
    # a valid proof for the target institution must not make a foreign
    # administrator assignment authorize that target or disclose its version.
    assignment = review_http["ctx"]["db"].scalar(select(InstitutionalReviewerAssignment))
    assignment.institution = "foreign"
    review_http["ctx"]["db"].commit()
    denied = legacy_request(review_http)
    assert denied.status_code == 403
    assert denied.json() == {
        "detail": {"code": "authority_denied", "message": "Request failed"},
        "request_id": None,
    }
    assert "current_profile_version" not in denied.text


def test_scoped_compatibility_conflict_retains_current_profile_version(review_http):
    assign_reviewer(review_http)
    stale = legacy_request(review_http)
    assert stale.status_code == 409
    assert stale.json() == {
        "detail": {
            "code": "profile_version_conflict", "current_profile_version": 1,
            "message": "Request failed",
        },
        "request_id": None,
    }
    assert stale.headers["cache-control"] == "private, no-store"


def test_compatibility_exact_replay_precedes_current_version_but_not_payload_binding(review_http):
    assign_reviewer(review_http)
    payload = {**review_http["legacy_payload"], "expected_profile_version": 1}
    original = legacy_request(review_http, payload)
    assert original.status_code == 200
    assert original.json() == {
        "status": "verified", "profile_version": 1,
        "owner_projection_invalidated": True,
    }
    review_http["ctx"]["profile"].profile_version = 2
    review_http["ctx"]["db"].commit()
    replay = legacy_request(review_http, payload)
    assert replay.status_code == 200
    assert replay.json() == original.json()
    changed = legacy_request(review_http, {**payload, "expected_profile_version": 2})
    assert changed.status_code == 409
    assert changed.json() == {
        "detail": {"code": "authority_idempotency_conflict", "message": "Request failed"},
        "request_id": None,
    }
    assert "current_profile_version" not in changed.text
