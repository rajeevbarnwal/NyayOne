"""Notification & reminder tests (SAATHI-340/379/380).

The safe-log-view oracle, and why it is structural
--------------------------------------------------
``test_safe_log_view_excludes_recipient_and_values`` used to end with

    assert "abc" not in str(view) and "under_review" not in str(view)

and it FLAKED in CI. ``str(view)`` sweeps in ``view["id"]``, which is a random
``uuid4().hex`` — 32 hex digits — and ``a``, ``b`` and ``c`` ARE hex digits, so
roughly one generated id in a few thousand contains the substring ``abc`` by
pure chance. CI drew ``6b4ebf82fffa4d4d80346f8abc6f7347`` and the test failed
without any redaction defect existing: the leak it reported came from the
opaque identifier, not from ``variables["application_id"]``.

That is an oracle defect, so the oracle is what changed. Nothing about
``NotificationMessage.safe_log_view`` moved, no value is masked, and no
production redaction behaviour was touched — a masking "fix" would have hidden
a real leak behind a filter while the flake stayed.

The replacement is STRUCTURAL and deterministic:

* the message id is INJECTED (no ``uuid4`` in any assertion path), and it is
  additionally EXCLUDED from the substring value scan — an opaque generated
  identifier is not a content-bearing field, and scanning it is exactly the
  false positive above. Both, not either: injection removes the randomness,
  exclusion removes the category error. The recipient scan still covers every
  field, id included, because a recipient reaching an id would be real.
* the safe view's key set is asserted EXACTLY, so a new key is a review event
  rather than an unscanned hiding place;
* every other field is scanned for the variable VALUES, recursively, so a leak
  into a nested structure cannot slip past;
* and the oracle is proven to still bite: the same assertions are re-run
  against deliberately tampered projections below.
"""
from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import pytest

from app.services.audit_service import record_audit_event
from app.services.notifications import (
    Channel,
    DeliveryStatus,
    NotificationMessage,
    NotificationService,
    ReminderRule,
    due_reminders,
)

#: The id CI actually generated when this test flaked. `abc` is inside it, and
#: `abc` is also `variables["application_id"]` — which is precisely how a blind
#: `str(view)` scan confused an identifier with a leak.
FLAKY_ID = "6b4ebf82fffa4d4d80346f8abc6f7347"

#: The APPROVED key set of the privacy-safe log projection. Adding a key to
#: `safe_log_view` must fail here first: every new field is a new place for
#: recipient or content to escape, and that is a decision to be reviewed, not
#: a change that silently widens what gets logged.
SAFE_VIEW_KEYS = {"id", "channel", "template_key", "variable_keys"}

#: Fields that are opaque generated identifiers rather than notification
#: CONTENT, and are therefore not scanned for variable values.
OPAQUE_KEYS = {"id"}


def _msg(channel=Channel.EMAIL, *, message_id: str | None = None) -> NotificationMessage:
    kwargs: dict[str, Any] = {} if message_id is None else {"id": message_id}
    return NotificationMessage(
        channel=channel,
        template_key="internship.status_changed",
        to_ref="user-ref-123",  # opaque, not a real email/phone
        variables={"application_id": "abc", "status": "under_review"},
        **kwargs,
    )


def _texts(value: Any) -> Iterator[str]:
    """Every string reachable inside ``value``, however it is nested.

    Fail-closed on purpose: a dict, a list, a tuple or an object nobody
    anticipated is descended into or stringified, so a value hidden one level
    down is still found.
    """
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for key, item in value.items():
            yield from _texts(key)
            yield from _texts(item)
    elif isinstance(value, (list, tuple, set, frozenset)):
        for item in value:
            yield from _texts(item)
    else:
        yield str(value)


def assert_privacy_safe_projection(view: dict, *, message: NotificationMessage) -> None:
    """Every property the safe log view must have, applied to ONE projection.

    Written as a function over a projection — not inline in a test — so the
    tampering tests below can hand it a deliberately leaky view and prove it
    still fails. An oracle nobody has seen fail is not an oracle.
    """
    # 1. the recipient is absent as a KEY ...
    assert "to_ref" not in view, "the recipient reference must never be logged"
    # 2. ... and the key set is exactly the approved one.
    assert set(view) == SAFE_VIEW_KEYS, (
        f"unreviewed key(s) in the safe log view: {sorted(set(view) ^ SAFE_VIEW_KEYS)}"
    )
    # 3. variable_keys carries KEYS ONLY, sorted, and nothing else.
    assert view["variable_keys"] == sorted(message.variables), "keys only"
    assert all(isinstance(key, str) for key in view["variable_keys"])

    # 4. no variable VALUE appears in any content-bearing field. The scan is
    #    over the fields themselves, never over `str(view)`, so the opaque id
    #    cannot manufacture a match out of hex digits.
    content = {key: item for key, item in view.items() if key not in OPAQUE_KEYS}
    for name, value in message.variables.items():
        for field, item in content.items():
            for text in _texts(item):
                assert value not in text, (
                    f"variable value {name}={value!r} leaked into safe view "
                    f"field {field!r} ({text!r})"
                )

    # 5. the recipient is scanned for in EVERY field, id included: unlike a
    #    variable value, an opaque recipient ref appearing in an identifier
    #    would be a genuine finding, not a hex-digit coincidence.
    for text in _texts(view):
        assert message.to_ref not in text, f"recipient leaked into {text!r}"

    # 6. and the fields that survive still say what they are supposed to say —
    #    asserted LAST, so a leak is reported as a leak and not as "this field
    #    changed", which is the more useful failure of the two.
    assert view["id"] == message.id
    assert view["channel"] == message.channel.value
    assert view["template_key"] == message.template_key


def test_noop_provider_dispatch_returns_sent() -> None:
    svc = NotificationService()
    assert svc.dispatch(_msg()) is DeliveryStatus.SENT
    assert svc.dispatch(_msg(Channel.WHATSAPP)) is DeliveryStatus.SENT


@pytest.mark.parametrize(
    "message_id",
    [
        pytest.param(FLAKY_ID, id="the-id-that-flaked-in-ci"),
        pytest.param("abcabcabcabcabcabcabcabcabcabcab", id="all-abc"),
        pytest.param("0" * 32, id="no-hex-letters-at-all"),
    ],
)
def test_safe_log_view_excludes_recipient_and_values(message_id: str) -> None:
    """Recipient absent, approved key set, keys not values — for ANY id.

    The id is injected rather than generated, so this test's verdict cannot
    depend on a draw from ``uuid4``. The first case is the exact id CI produced
    when the old assertion failed.
    """
    message = _msg(message_id=message_id)
    assert_privacy_safe_projection(message.safe_log_view(), message=message)


def test_the_old_substring_oracle_would_flake_on_this_id_and_the_new_one_does_not():
    """The flake, demonstrated rather than described.

    ``abc`` really is present in ``str(view)`` for this id — the old assertion
    would fail here — and it comes from the identifier, not from a leaked
    value. The structural oracle passes on the same projection.
    """
    message = _msg(message_id=FLAKY_ID)
    view = message.safe_log_view()

    assert "abc" in str(view)  # what the OLD oracle looked at: it would fail
    assert "abc" in view["id"]  # and this is the only place it came from
    content = {key: item for key, item in view.items() if key not in OPAQUE_KEYS}
    assert "abc" not in str(content)  # no content-bearing field carries it

    assert_privacy_safe_projection(view, message=message)


@pytest.mark.parametrize(
    "leak",
    [
        pytest.param(
            lambda view, message: view.update(
                template_key=f"{message.template_key}?id={message.variables['application_id']}"
            ),
            id="value-appended-to-template_key",
        ),
        pytest.param(
            lambda view, message: view.update(
                variable_keys=[f"{k}={v}" for k, v in sorted(message.variables.items())]
            ),
            id="values-folded-into-variable_keys",
        ),
        pytest.param(
            lambda view, message: view.update(variables=dict(message.variables)),
            id="whole-variables-dict-added-as-a-new-key",
        ),
        pytest.param(
            lambda view, message: view.update(
                context={"trace": [{"status": message.variables["status"]}]}
            ),
            id="value-buried-in-a-nested-new-key",
        ),
    ],
)
def test_the_oracle_still_fails_when_a_variable_value_is_injected(leak) -> None:
    """Point of the whole exercise: the replacement still catches a real leak.

    Production code is untouched — the tampering happens to a COPY of the
    projection, which is what an oracle actually judges.
    """
    message = _msg(message_id=FLAKY_ID)
    view = dict(message.safe_log_view())
    leak(view, message)
    with pytest.raises(AssertionError):
        assert_privacy_safe_projection(view, message=message)


def test_the_oracle_still_fails_when_the_recipient_is_injected() -> None:
    message = _msg(message_id=FLAKY_ID)
    view = dict(message.safe_log_view())
    view["to_ref"] = message.to_ref
    with pytest.raises(AssertionError, match="recipient reference must never be logged"):
        assert_privacy_safe_projection(view, message=message)


def test_the_oracle_still_fails_when_the_recipient_hides_in_another_field() -> None:
    """Not just the `to_ref` KEY: the recipient's value, under any name."""
    message = _msg(message_id=FLAKY_ID)
    view = dict(message.safe_log_view())
    view["id"] = f"{message.id}-{message.to_ref}"
    with pytest.raises(AssertionError, match="recipient leaked into"):
        assert_privacy_safe_projection(view, message=message)


def test_dispatch_emits_privacy_safe_audit(db_session) -> None:
    svc = NotificationService()
    svc.dispatch(_msg(), audit=record_audit_event, session=db_session)
    db_session.commit()
    from app.db.models.audit import AuditEvent

    ev = db_session.query(AuditEvent).filter_by(action="notification.dispatch").one()
    # audit after_state carries only the safe view (no recipient/values)
    assert ev.after_state["channel"] == "email"
    assert "to_ref" not in ev.after_state
    assert ev.after_state["status"] == "sent"


def test_due_reminders_selection() -> None:
    rules = [
        ReminderRule(channel=Channel.PUSH, offset_minutes=60),
        ReminderRule(channel=Channel.EMAIL, offset_minutes=1440),
        ReminderRule(channel=Channel.SMS, offset_minutes=15, enabled=False),
    ]
    # 30 min to event: the 60-min and 1440-min enabled rules fire; disabled SMS never.
    fired = due_reminders(rules, minutes_to_event=30)
    channels = {r.channel for r in fired}
    assert Channel.PUSH in channels and Channel.EMAIL in channels
    assert Channel.SMS not in channels
