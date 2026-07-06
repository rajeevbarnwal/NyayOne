"""Tests for the auth-context abstraction (SAATHI-337)."""
from __future__ import annotations

import uuid

import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

from app.core.auth import (
    ANONYMOUS,
    ActorContext,
    Role,
    VerificationStatus,
    build_actor_context,
    get_actor_context,
    require_authenticated,
    require_lawyer_features,
    require_role,
)


def test_anonymous_context() -> None:
    assert ANONYMOUS.is_authenticated is False
    assert build_actor_context(None) is ANONYMOUS
    assert build_actor_context({}) is ANONYMOUS


def test_student_context_from_claims() -> None:
    uid = str(uuid.uuid4())
    actor = build_actor_context(
        {"sub": uid, "roles": ["student"], "student_verification": "verified"}
    )
    assert actor.is_authenticated
    assert actor.has_role(Role.STUDENT)
    assert actor.is_student_verified
    assert actor.can_use_lawyer_features is False  # no lawyer role/verification


def test_lawyer_feature_lock_requires_p01_verification() -> None:
    uid = str(uuid.uuid4())
    # Lawyer role but NOT verified -> locked.
    unverified = build_actor_context({"sub": uid, "roles": ["lawyer"], "lawyer_verification": "submitted"})
    assert unverified.can_use_lawyer_features is False
    # Verified -> unlocked.
    verified = build_actor_context({"sub": uid, "roles": ["lawyer"], "lawyer_verification": "verified"})
    assert verified.can_use_lawyer_features is True


def _app() -> FastAPI:
    app = FastAPI()

    @app.get("/me")
    def me(actor: ActorContext = Depends(get_actor_context)):
        return {"auth": actor.is_authenticated}

    @app.get("/secure")
    def secure(actor: ActorContext = Depends(require_authenticated)):
        return {"ok": True}

    @app.get("/lawyer")
    def lawyer(actor: ActorContext = Depends(require_lawyer_features)):
        return {"ok": True}

    return app


def test_dependency_states() -> None:
    client = TestClient(_app())
    # anonymous
    assert client.get("/me").json() == {"auth": False}
    assert client.get("/secure").status_code == 401
    # student (authenticated, not lawyer-verified) -> secure ok, lawyer 403
    import json

    student = {"X-Actor-Claims": json.dumps({"sub": str(uuid.uuid4()), "roles": ["student"]})}
    assert client.get("/secure", headers=student).status_code == 200
    assert client.get("/lawyer", headers=student).status_code == 403
    # verified lawyer -> lawyer ok
    law = {"X-Actor-Claims": json.dumps({"sub": str(uuid.uuid4()), "roles": ["lawyer"], "lawyer_verification": "verified"})}
    assert client.get("/lawyer", headers=law).status_code == 200
