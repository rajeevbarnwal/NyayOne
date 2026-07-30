"""Join credentials + video room webhook (matrix E1 / E2).

WHY THIS MODULE EXISTS. P2 shipped the video PROVIDER seam
(``app.services.providers.video_provider``) and the ``video_session_grants``
table, and it declared ``GRANT_EXPIRED`` / ``GRANT_REVOKED`` in
``tutoring.errors`` — but no service ever bound them together, so rows E1 and E2
of the frozen matrix had no domain owner. Putting that logic in the API layer
would have broken the package rule that business rules live in services (and
would have made it untestable without HTTP), so it lives here alongside the rest
of the tutoring domain and obeys the same conventions: typed errors only, no
commits, UTC instants, ids/codes in audit payloads.

The two frozen rules this module exists to enforce:

* **only a hash is persisted.** :class:`~app.models.wave2.VideoSessionGrant` has
  no raw-token column; the raw token is returned in the ISSUING call's result
  object (so the API can put it in one response body) and is never written to a
  row, an audit payload, an outbox payload or a log line.
* **a credential is superseded, expired or revoked — never replayable.** Every
  successful issue REVOKES the participant's previous live grants, so the token
  handed out earlier stops validating the moment a new one is minted. That, plus
  the TTL and the explicit revocation paths, is what makes
  :func:`validate` able to answer GRANT_EXPIRED / GRANT_REVOKED honestly.

Webhook contract (E2), which mirrors ``payments.handle_event``:

1. resolve the provider (fail closed),
2. **verify the signature** — on failure raise ``VIDEO_UNVERIFIED`` having
   touched NOTHING,
3. resolve the session from the room reference via an existing grant (room
   references are provider-derived and not reversible, so a room nobody was ever
   granted access to is simply ``NOT_FOUND``),
4. reject an already-applied ``provider_event_id`` (``DUPLICATE_EVENT``),
5. apply the effect, which for ``participant_left`` / ``room_finished`` is
   REVOCATION, and record one ``session_status_history`` row.

Step 5 never changes ``tutoring_sessions.status``: completion is
attendance-driven (matrix D4, tutor/admin, after the scheduled end) and a video
provider must not be able to complete or cancel a booking. The history row is
written with ``from_status == to_status == <current status>`` precisely so the
room trail is auditable WITHOUT asserting a state change that did not happen.
"""
from __future__ import annotations

import hashlib
import uuid
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

import sqlalchemy as sa
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.wave2 import (
    PaymentOrder,
    SessionStatusHistory,
    TutoringSession,
    VideoSessionGrant,
)
from app.services.audit_service import record_audit_event
from app.services.providers.video_provider import (
    ROLE_PERMISSIONS,
    VideoCredential,
    VideoEventData,
    VideoProviderError,
    VideoSessionProvider,
    build_video_provider,
    hash_token,
)
from app.services.tutoring import sessions as sessions_service
from app.services.tutoring.errors import (
    DuplicateEvent,
    Forbidden,
    GrantExpired,
    GrantRevoked,
    NotFound,
    PaymentUnverified,
    ProviderUnavailable,
    SessionStateInvalid,
    ValidationError,
    VideoUnverified,
)

#: Only a session PARTICIPANT may hold a join credential. An admin is not a
#: participant: giving support staff a publishing credential to a live tutoring
#: room by default would be a privacy decision nobody has taken.
PARTICIPANT_ROLES = ("student", "tutor")

#: Room events this module knows how to apply. A provider that sends anything
#: else has already been rejected by ``verify_event``.
REVOKE_ON_EVENT = {
    "participant_left": "participant",
    "room_finished": "session",
}

#: ``session_status_history.reason`` is VARCHAR(200) and operator-visible.
_MAX_EVENT_ID = 120


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _aware(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


def _resolve_provider(
    provider: VideoSessionProvider | None,
) -> VideoSessionProvider:
    """Fail closed: an unconfigured provider is PROVIDER_UNAVAILABLE, not a guess."""
    resolved = provider or build_video_provider()
    if resolved is None:
        raise ProviderUnavailable("video provider is not configured", retryable=False)
    return resolved


def participant_ref(session_id: uuid.UUID, user_id: uuid.UUID) -> str:
    """Opaque, stable per-(session, user) handle. Never an email/phone/name.

    A hash rather than the user id itself: the reference travels to a third-party
    video provider and appears in its dashboards and logs, so it must not be a
    key into our identity system.
    """
    material = f"tutoring-participant:{session_id}:{user_id}".encode("utf-8")
    return hashlib.sha256(material).hexdigest()[:32]


def ttl_seconds() -> int:
    value = int(settings.join_credential_ttl_seconds)
    if value <= 0:  # pragma: no cover - Settings refuses to build with <= 0
        raise ValidationError(
            "join_credential_ttl_seconds must be positive",
            field="join_credential_ttl_seconds",
        )
    return value


# --------------------------------------------------------------------------- #
# Issue (matrix E1)
# --------------------------------------------------------------------------- #


@dataclass
class GrantIssued:
    """One minted credential. ``raw_token`` exists ONLY in this object."""

    grant: VideoSessionGrant
    raw_token: str
    room_ref: str
    permissions: str
    issued_at: datetime
    expires_at: datetime
    ttl_seconds: int
    superseded: int = 0

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return (
            f"GrantIssued(grant_id={self.grant.id!r}, room_ref={self.room_ref!r}, "
            f"expires_at={self.expires_at!r}, raw_token='[redacted]')"
        )


def live_grants(
    session: Session,
    session_id: uuid.UUID,
    *,
    ref: str | None = None,
    now: datetime | None = None,
) -> tuple[VideoSessionGrant, ...]:
    """Grants for a session that are neither revoked nor expired."""
    now = now or utcnow()
    filters = [
        VideoSessionGrant.session_id == session_id,
        VideoSessionGrant.revoked_at.is_(None),
        VideoSessionGrant.expires_at > now,
    ]
    if ref is not None:
        filters.append(VideoSessionGrant.participant_ref == ref)
    return tuple(
        session.scalars(
            sa.select(VideoSessionGrant)
            .where(*filters)
            .order_by(
                VideoSessionGrant.issued_at.desc(), VideoSessionGrant.id.asc()
            )
        ).all()
    )


def revoke(
    session: Session,
    session_id: uuid.UUID,
    *,
    reason: str,
    ref: str | None = None,
    now: datetime | None = None,
) -> int:
    """Revoke every un-revoked grant for a session (or one participant).

    Idempotent: an already-revoked grant is left exactly as it was, so the
    returned count is "how many this call actually revoked". Does not commit.
    """
    now = now or utcnow()
    filters = [
        VideoSessionGrant.session_id == session_id,
        VideoSessionGrant.revoked_at.is_(None),
    ]
    if ref is not None:
        filters.append(VideoSessionGrant.participant_ref == ref)
    result = session.execute(
        sa.update(VideoSessionGrant).where(*filters).values(revoked_at=now, updated_at=now)
    )
    count = int(result.rowcount or 0)
    if count:
        record_audit_event(
            session,
            action="tutoring.video.credential_revoked",
            resource_type="video_session_grant",
            resource_id=session_id,
            actor_role="system",
            after_state={
                "session_id": str(session_id),
                "participant_ref": ref,
                "revoked_count": count,
                "reason": reason,
            },
        )
    session.flush()
    return count


def _paid_order(session: Session, sess: TutoringSession) -> PaymentOrder:
    order = session.get(PaymentOrder, sess.order_id) if sess.order_id else None
    if order is None or order.status != "paid":
        raise PaymentUnverified(
            "a join credential requires a captured payment",
            session_id=str(sess.id),
            status=(order.status if order else None),
        )
    return order


def issue(
    session: Session,
    session_id: uuid.UUID,
    *,
    actor_user_id: uuid.UUID,
    actor_role: str,
    provider: VideoSessionProvider | None = None,
    ttl: int | None = None,
    now: datetime | None = None,
) -> GrantIssued:
    """Mint a join credential for an authorised, PAID participant. No commit.

    Refuses (typed, no partial write) when the caller is not a participant of
    this session (``NOT_FOUND`` — never an enumeration oracle), when the session
    is not live, when the booking was never captured (``PAYMENT_UNVERIFIED``) or
    when the provider is unusable (``PROVIDER_UNAVAILABLE``, never a 500).
    """
    now = now or utcnow()
    if actor_role not in PARTICIPANT_ROLES:
        raise Forbidden(
            "join credentials are issued to session participants only",
            actor_role=actor_role,
        )
    # Non-enumerating ownership: another user's session is NOT_FOUND.
    sess = sessions_service.get_session(
        session, session_id, user_id=actor_user_id, role=actor_role
    )
    if sess.status not in sessions_service.LIVE_STATUSES:
        raise SessionStateInvalid(
            "a join credential requires a live session", status=sess.status
        )
    # Even the tutor's credential is gated on capture: an unpaid booking is not
    # a booking, and the room must not exist for it.
    _paid_order(session, sess)
    resolved = _resolve_provider(provider)
    ref = participant_ref(sess.id, actor_user_id)
    permissions = ROLE_PERMISSIONS[actor_role]
    seconds = int(ttl if ttl is not None else ttl_seconds())

    # A new credential SUPERSEDES the previous one, which is what stops an
    # earlier token from being replayed after a reconnect.
    superseded = revoke(session, sess.id, ref=ref, reason="superseded", now=now)

    try:
        credential: VideoCredential = resolved.issue_credential(
            sess.id, ref, permissions, seconds, now=now
        )
    except VideoProviderError as exc:
        raise ProviderUnavailable(
            f"video provider could not issue a credential ({exc.code})",
            retryable=exc.retryable,
            provider_code=exc.code,
        ) from exc

    # uq_video_session_grants_session_participant is (session, participant,
    # issued_at), so a reconnect inside the same microsecond — or a test that
    # injects the same ``now`` twice — would collide. Nudge the instant forward
    # past the newest existing grant instead of failing a legitimate reissue.
    issued_at = now
    newest = session.scalar(
        sa.select(sa.func.max(VideoSessionGrant.issued_at)).where(
            VideoSessionGrant.session_id == sess.id,
            VideoSessionGrant.participant_ref == credential.participant_ref,
        )
    )
    newest = _aware(newest)
    if newest is not None and newest >= issued_at:
        issued_at = newest + timedelta(microseconds=1)
    expires_at = _aware(credential.expires_at) or (now + timedelta(seconds=seconds))
    if expires_at <= issued_at:  # pragma: no cover - guards the DB CHECK
        raise ProviderUnavailable(
            "video provider returned an already-expired credential",
            retryable=False,
        )
    grant = VideoSessionGrant(
        session_id=sess.id,
        participant_ref=credential.participant_ref,
        room_ref=credential.room_ref,
        permissions=credential.permissions,
        # The ONLY representation of the token that touches storage.
        token_hash=credential.token_hash,
        issued_at=issued_at,
        expires_at=expires_at,
    )
    session.add(grant)
    try:
        session.flush()
    except IntegrityError:  # pragma: no cover - the nudge above prevents this
        session.rollback()
        raise ProviderUnavailable(
            "join credential could not be recorded; retry", retryable=True
        ) from None

    record_audit_event(
        session,
        action="tutoring.video.credential_issued",
        resource_type="video_session_grant",
        resource_id=grant.id,
        actor_user_id=actor_user_id,
        actor_role=actor_role,
        after_state={
            # Ids, codes and instants only. No token, no token hash, no name.
            "session_id": str(sess.id),
            "participant_ref": credential.participant_ref,
            "room_ref": credential.room_ref,
            "permissions": credential.permissions,
            "expires_at": expires_at.isoformat(),
            "ttl_seconds": seconds,
            "superseded": superseded,
        },
    )
    session.flush()
    return GrantIssued(
        grant=grant,
        raw_token=credential.raw_token,
        room_ref=credential.room_ref,
        permissions=credential.permissions,
        issued_at=issued_at,
        expires_at=expires_at,
        ttl_seconds=seconds,
        superseded=superseded,
    )


def validate(
    session: Session,
    *,
    raw_token: str,
    now: datetime | None = None,
) -> VideoSessionGrant:
    """Resolve a raw join token to its grant, or raise the typed reason it fails.

    The lookup is by HASH: this function is the reason the raw token never needs
    to be stored. ``NOT_FOUND`` covers "never issued" and "not a token at all"
    with one shape, so it cannot be used to probe which tokens exist.
    """
    now = now or utcnow()
    token = (raw_token or "").strip()
    if not token:
        raise NotFound("join credential not found", resource="video_session_grant")
    grant = session.scalars(
        sa.select(VideoSessionGrant).where(
            VideoSessionGrant.token_hash == hash_token(token)
        )
    ).first()
    if grant is None:
        raise NotFound("join credential not found", resource="video_session_grant")
    if grant.revoked_at is not None:
        raise GrantRevoked(
            "join credential has been revoked", grant_id=str(grant.id)
        )
    expires_at = _aware(grant.expires_at)
    if expires_at is not None and expires_at <= now:
        raise GrantExpired("join credential has expired", grant_id=str(grant.id))
    return grant


# --------------------------------------------------------------------------- #
# Webhook (matrix E2)
# --------------------------------------------------------------------------- #


@dataclass
class VideoEventOutcome:
    """What applying one verified room event did."""

    tutoring_session: TutoringSession
    event_type: str
    provider_event_id: str
    room_ref: str
    revoked: int = 0
    participant_ref: str | None = None


def _event_reason(event_type: str, provider_event_id: str) -> str:
    """The de-duplication key, stored in ``session_status_history.reason``.

    Codes only (an opaque provider event id is a code), and short enough that
    the VARCHAR(200) column never truncates it into a collision.
    """
    return f"video:{event_type}:{provider_event_id}"


def handle_event(
    session: Session,
    *,
    signature: str | None = None,
    raw_body: bytes,
    headers: Mapping[str, str] | None = None,
    provider: VideoSessionProvider | None = None,
    now: datetime | None = None,
) -> VideoEventOutcome:
    """Verify, de-duplicate and apply one provider room event. No commit.

    ``signature`` and ``headers`` are two ways to present the SAME thing: the
    credential the delivery carries. HTTP callers forward ``headers`` verbatim and
    let the resolved adapter read the header IT signs (deterministic:
    ``X-Video-Signature``; LiveKit: ``Authorization``) — deciding that here, or in
    the route, would hard-code one provider's transport for all of them. In-process
    callers may still pass ``signature`` directly.
    """
    now = now or utcnow()
    resolved = _resolve_provider(provider)

    # 2. signature FIRST — nothing is read or written before this succeeds.
    try:
        data: VideoEventData = resolved.verify_event(
            signature, raw_body, headers=headers
        )
    except VideoProviderError as exc:
        if exc.retryable:
            raise ProviderUnavailable(
                f"video provider could not verify the event ({exc.code})",
                retryable=True,
                provider_code=exc.code,
            ) from exc
        raise VideoUnverified(
            "video event signature verification failed", provider_code=exc.code
        ) from exc
    if not data.signature_verified:  # pragma: no cover - adapters raise instead
        raise VideoUnverified("video event was not verified")
    event_id = (data.provider_event_id or "").strip()
    if not event_id or len(event_id) > _MAX_EVENT_ID:
        raise VideoUnverified(
            "video event carries no usable event id", provider_code="EVENT_ID_INVALID"
        )
    room_ref = (data.room_ref or "").strip()
    if not room_ref:
        raise VideoUnverified(
            "video event carries no room reference", provider_code="ROOM_REF_INVALID"
        )

    # 3. resolve the session from the room. Room references are provider-derived
    #    and not reversible, so the only honest mapping is "a grant was issued
    #    for this room". A room nobody holds a grant for is NOT_FOUND.
    grant_row = session.scalars(
        sa.select(VideoSessionGrant)
        .where(VideoSessionGrant.room_ref == room_ref)
        .order_by(VideoSessionGrant.issued_at.asc(), VideoSessionGrant.id.asc())
    ).first()
    if grant_row is None:
        raise NotFound("video room not found", resource="video_session_grant")
    sess = session.get(TutoringSession, grant_row.session_id)
    if sess is None or sess.deleted_at is not None:  # pragma: no cover - FK CASCADE
        raise NotFound("session not found", resource="tutoring_session")

    # 4. replay protection: the same delivery is applied at most once.
    reason = _event_reason(data.event_type, event_id)
    duplicate = session.scalars(
        sa.select(SessionStatusHistory).where(
            SessionStatusHistory.session_id == sess.id,
            SessionStatusHistory.reason == reason,
        )
    ).first()
    if duplicate is not None:
        raise DuplicateEvent(
            "video event has already been applied",
            provider_event_id=event_id,
            session_id=str(sess.id),
        )

    ref = (data.participant_ref or "").strip() or None

    # 5a. a join must present a LIVE grant. An expired/revoked/superseded
    #     (i.e. replayed) participant is refused with the typed reason, and
    #     because the caller rolls back, an identical redelivery is refused
    #     identically rather than becoming a duplicate.
    if data.event_type == "participant_joined":
        if ref is None:
            raise VideoUnverified(
                "a join event must name its participant",
                provider_code="PARTICIPANT_REQUIRED",
            )
        matching = session.scalars(
            sa.select(VideoSessionGrant)
            .where(
                VideoSessionGrant.session_id == sess.id,
                VideoSessionGrant.participant_ref == ref,
            )
            .order_by(VideoSessionGrant.issued_at.desc(), VideoSessionGrant.id.asc())
        ).first()
        if matching is None:
            raise NotFound(
                "join credential not found", resource="video_session_grant"
            )
        if matching.revoked_at is not None:
            raise GrantRevoked(
                "join credential has been revoked", grant_id=str(matching.id)
            )
        expires_at = _aware(matching.expires_at)
        if expires_at is not None and expires_at <= now:
            raise GrantExpired(
                "join credential has expired", grant_id=str(matching.id)
            )

    # 5b. revocation effects. No provider call-back: reacting to the provider's
    #     own event by calling the provider would be a redundant round trip that
    #     could only add a new failure mode to an otherwise local, idempotent
    #     write.
    revoked = 0
    scope = REVOKE_ON_EVENT.get(data.event_type)
    if scope == "participant" and ref is not None:
        revoked = revoke(session, sess.id, ref=ref, reason="participant_left", now=now)
    elif scope == "session":
        revoked = revoke(session, sess.id, reason="room_finished", now=now)

    # 5c. the auditable trail row. NOT a status change - see the module docstring.
    sessions_service._history(
        session,
        session_id=sess.id,
        from_status=sess.status,
        to_status=sess.status,
        actor_role="system",
        now=now,
        reason=reason,
    )
    record_audit_event(
        session,
        action="tutoring.video.event_applied",
        resource_type="tutoring_session",
        resource_id=sess.id,
        actor_role="system",
        after_state={
            "event_type": data.event_type,
            "provider_event_id": event_id,
            "room_ref": room_ref,
            "participant_ref": ref,
            "grants_revoked": revoked,
            "session_status": sess.status,
        },
    )
    session.flush()
    return VideoEventOutcome(
        tutoring_session=sess,
        event_type=data.event_type,
        provider_event_id=event_id,
        room_ref=room_ref,
        revoked=revoked,
        participant_ref=ref,
    )
