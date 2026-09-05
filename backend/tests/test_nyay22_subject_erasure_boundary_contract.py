"""Adversarial source contracts for the NYAY-19/NYAY-22 erasure seam.

These checks complement the real SQLite and PostgreSQL lifecycle proofs.  They
pin the structural properties that are otherwise easy to regress while
refactoring the shared registration-retention path.
"""
from __future__ import annotations

import ast
from pathlib import Path


BACKEND = Path(__file__).resolve().parents[1]
MENTOR_SERVICE = BACKEND / "app" / "services" / "mentor_ceremony.py"
RETENTION = BACKEND / "app" / "core" / "retention.py"


def _function_source(path: Path, name: str) -> str:
    source = path.read_text(encoding="utf-8")
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == name:
            return ast.get_source_segment(source, node) or ""
    raise AssertionError(f"required function is absent: {name}")


def test_erasure_boundary_is_same_session_same_transaction_and_one_shot() -> None:
    source = MENTOR_SERVICE.read_text(encoding="utf-8")
    lock = _function_source(MENTOR_SERVICE, "lock_subject_mentor_erasure_boundary")
    consume = _function_source(
        MENTOR_SERVICE, "consume_subject_mentor_erasure_approval"
    )

    assert "db.get_transaction()" in lock
    assert "db.info" in lock
    assert "registration_updated_at" in source
    assert "inventory_digest" in source
    assert "policy_digest" in source
    assert "zero_link_digest" in source
    assert "db.get_transaction()" in consume
    assert "db.info" in consume
    assert "consumed" in consume


def test_registration_erasure_requires_cutoff_bound_zero_link_approval() -> None:
    prepare = _function_source(
        MENTOR_SERVICE, "prepare_subject_mentor_registration_erasure"
    )
    retention = RETENTION.read_text(encoding="utf-8")

    assert "mentor_terminal_retention_seconds" in prepare
    assert "mentor_audit_link_retention_seconds" in prepare
    assert "_graph_is_cutoff_eligible" in prepare
    assert "_assert_subject_graph_severed" in prepare
    assert "consume_subject_mentor_erasure_approval" in retention
    assert retention.index("prepare_subject_mentor_registration_erasure") < retention.index(
        "terminalize_registration_idempotency"
    )


def test_subject_graph_cap_is_global_and_defers_with_nyay19_alert() -> None:
    prepare = _function_source(
        MENTOR_SERVICE, "prepare_subject_mentor_registration_erasure"
    )

    assert "SUBJECT_GRAPH_HARD_CAP = 256" in MENTOR_SERVICE.read_text(
        encoding="utf-8"
    )
    assert "total_rows" in prepare
    assert "GRAPH_EXCEEDS_HARD_CAP" in prepare
    assert "_record_blocked_retention_graph" in prepare
    assert '"DEFER"' in prepare
    assert "_sever_authority_graph" in prepare


def test_privacy_delete_checks_graph_cap_before_consuming_recovery_authority() -> None:
    """A blocked graph must not burn the caller's one-shot OTP recovery proof."""

    from app.api.v1 import student_settings

    privacy = _function_source(
        Path(student_settings.__file__).resolve(), "privacy_delete"
    )
    assert "preflight_subject_mentor_authority_for_privacy_request" in privacy
    assert privacy.index(
        "preflight_subject_mentor_authority_for_privacy_request"
    ) < privacy.index("consume_recovery_proof")
    assert privacy.index("consume_recovery_proof") < privacy.index(
        "retire_subject_mentor_authority_for_privacy_request"
    )


def test_owner_cookie_resolution_never_locks_auth_child_before_user() -> None:
    helper = _function_source(MENTOR_SERVICE, "_active_student_session")

    assert "select(AuthSession.id, AuthSession.user_id)" in helper
    assert "select(User)" in helper
    assert helper.index("select(User)") < helper.index("select(AuthSession)")
    assert ".order_by(AuthSession.id)" in helper
    assert "row.revoked_at = row.expires_at" in helper
