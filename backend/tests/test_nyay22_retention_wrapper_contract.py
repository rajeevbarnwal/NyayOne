"""Public NYAY-19/22 retention wrappers expose their completion outcome.

The locked retention helpers return ``False`` when the mentor authority graph
must be deferred and ``True`` only after the requested erasure completes.  The
public wrappers must preserve that signal so callers cannot silently treat a
deferred graph as completed.
"""
from __future__ import annotations

import inspect
from types import SimpleNamespace

import pytest

from app.core import retention


@pytest.mark.parametrize(
    ("wrapper_name", "locked_name"),
    (
        ("anonymise_registration", "_anonymise_locked"),
        ("delete_registration", "_delete_locked"),
    ),
)
@pytest.mark.parametrize("locked_outcome", (False, True))
def test_public_retention_wrapper_propagates_locked_outcome(
    monkeypatch: pytest.MonkeyPatch,
    wrapper_name: str,
    locked_name: str,
    locked_outcome: bool,
) -> None:
    registration = SimpleNamespace(id="registration-id")
    locked_registration = object()
    idempotency_record = object()
    mentor_boundary = object()
    calls: list[tuple[object, ...]] = []

    monkeypatch.setattr(
        retention,
        "_prelock_subject_mentor_erasure",
        lambda session, registration_id: mentor_boundary,
    )
    monkeypatch.setattr(
        retention.registration_service,
        "lock_registration_with_idempotency",
        lambda session, registration_id: (locked_registration, idempotency_record),
    )

    def locked_helper(*args: object) -> bool:
        calls.append(args)
        return locked_outcome

    monkeypatch.setattr(retention, locked_name, locked_helper)
    session = object()

    result = getattr(retention, wrapper_name)(session, registration)

    assert result is locked_outcome
    assert calls == [
        (session, locked_registration, idempotency_record, mentor_boundary)
    ]


@pytest.mark.parametrize(
    ("wrapper_name", "locked_name"),
    (
        ("anonymise_registration", "_anonymise_locked"),
        ("delete_registration", "_delete_locked"),
    ),
)
def test_public_retention_wrapper_reports_missing_registration_as_incomplete(
    monkeypatch: pytest.MonkeyPatch,
    wrapper_name: str,
    locked_name: str,
) -> None:
    registration = SimpleNamespace(id="registration-id")
    monkeypatch.setattr(
        retention,
        "_prelock_subject_mentor_erasure",
        lambda session, registration_id: object(),
    )
    monkeypatch.setattr(
        retention.registration_service,
        "lock_registration_with_idempotency",
        lambda session, registration_id: (None, None),
    )

    def unexpected_call(*_args: object) -> bool:
        raise AssertionError("locked helper called without a locked registration")

    monkeypatch.setattr(retention, locked_name, unexpected_call)

    assert getattr(retention, wrapper_name)(object(), registration) is False


def test_public_retention_wrappers_publish_an_explicit_boolean_contract() -> None:
    for wrapper in (
        retention.anonymise_registration,
        retention.delete_registration,
    ):
        signature = inspect.signature(wrapper)
        assert signature.return_annotation in {bool, "bool"}
        documentation = inspect.getdoc(wrapper) or ""
        assert "True" in documentation
        assert "False" in documentation
