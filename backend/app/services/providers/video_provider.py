"""Video session provider seam (SAATHI-123 / SAATHI-127 P2).

Frozen product decisions this seam implements:

* Join credentials are OPAQUE, SHORT-LIVED (``settings.join_credential_ttl_seconds``)
  and bound to a *participant* + *room* + *permission* triple. They are issued
  only for authorised, paid participants — that authorisation check lives in the
  domain service; this seam merely refuses to mint a credential without all
  three bindings and a positive TTL.
* Only the ``token_hash`` (SHA-256 hex, 64 chars — exactly the column width) is
  ever suitable for persistence. The raw token is returned once, in memory, to
  be handed to the authorised participant and then forgotten. This module never
  logs it.
* Media-plane data (SDP, ICE candidates, media, device labels) must NEVER be
  persisted or logged. ``_reject_media_payload`` raises if a provider event even
  contains such a key, so a future provider change cannot silently start
  carrying signalling data into our storage.

No vendor type escapes: ``LiveKitCommunityAdapter`` builds its JWT grant with
nothing but the standard library, and callers only ever see ``VideoCredential``,
``VideoEventData`` and ``VideoProviderError``.

WEBHOOK SIGNATURE TRANSPORT IS PER-ADAPTER, NOT PER-ROUTE. Each adapter declares
the header it verifies in ``signature_header`` and pulls that header out of the
delivery itself, because the two adapters genuinely disagree:

* ``DeterministicVideoAdapter`` — hex ``HMAC-SHA256`` of the raw body in
  ``X-Video-Signature``. This is the scheme the automated business-contract suite
  signs with, and it is deliberately unchanged.
* ``LiveKitCommunityAdapter`` — a signed JWT in ``Authorization`` whose
  ``sha256`` claim is the *base64 SHA-256 of the exact raw body*, which is what a
  real LiveKit server sends (``livekit/protocol`` → ``webhook/url_notifier.go``,
  ``URLNotifier.send``).

The HTTP route therefore forwards the raw body plus the delivery's headers and
lets the resolved adapter decide which header carries authorisation.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
import uuid
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import NamedTuple, Protocol, runtime_checkable

from app.core.config import has_secret, settings

# --------------------------------------------------------------------------- #
# Typed error
# --------------------------------------------------------------------------- #


class VideoProviderError(Exception):
    """Video-boundary failure with a retry hint (see PaymentProviderError)."""

    def __init__(
        self,
        message: str,
        *,
        code: str = "PROVIDER_ERROR",
        retryable: bool = False,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.retryable = retryable


# --------------------------------------------------------------------------- #
# Permissions + value objects
# --------------------------------------------------------------------------- #

#: Canonical permission atoms. Stored as a sorted, comma-joined string that fits
#: ``video_session_grants.permissions`` (VARCHAR 64).
PERMISSION_ATOMS = ("subscribe", "publish", "publish_data", "manage")
ROLE_PERMISSIONS = {
    "student": "publish,subscribe",
    "tutor": "manage,publish,subscribe",
    "observer": "subscribe",
}


def normalise_permissions(permissions: str | tuple[str, ...] | list[str]) -> str:
    """Validate + canonicalise a permission set (sorted, comma-joined)."""
    if isinstance(permissions, str):
        atoms = [p.strip() for p in permissions.split(",") if p.strip()]
    else:
        atoms = [str(p).strip() for p in permissions if str(p).strip()]
    if not atoms:
        raise VideoProviderError(
            "at least one permission is required", code="PERMISSIONS_REQUIRED"
        )
    unknown = sorted(set(atoms) - set(PERMISSION_ATOMS))
    if unknown:
        raise VideoProviderError(
            f"unknown permission atoms: {','.join(unknown)}",
            code="PERMISSIONS_INVALID",
        )
    canonical = ",".join(sorted(set(atoms)))
    if len(canonical) > 64:  # pragma: no cover - guarded by the atom whitelist
        raise VideoProviderError(
            "permission set too long", code="PERMISSIONS_INVALID"
        )
    return canonical


class VideoCredential(NamedTuple):
    """``(raw_token, token_hash, room_ref, expires_at)`` plus its bindings.

    A NamedTuple so it unpacks exactly in the order the contract specifies while
    still being self-documenting at call sites.
    """

    raw_token: str
    token_hash: str
    room_ref: str
    expires_at: datetime
    participant_ref: str
    permissions: str

    def __repr__(self) -> str:
        # NEVER let the raw token reach a log line, a traceback or a repr.
        return (
            f"VideoCredential(room_ref={self.room_ref!r}, "
            f"participant_ref={self.participant_ref!r}, "
            f"permissions={self.permissions!r}, "
            f"expires_at={self.expires_at!r}, raw_token='[redacted]')"
        )


@dataclass(frozen=True)
class VideoEventData:
    """Provider-neutral, media-free room event."""

    provider: str
    provider_event_id: str
    event_type: str
    room_ref: str
    payload_digest: str
    participant_ref: str | None = None
    signature_verified: bool = True


VIDEO_EVENT_TYPES = (
    "room_started",
    "room_finished",
    "participant_joined",
    "participant_left",
)

#: Keys that must never cross this boundary, let alone be persisted.
_FORBIDDEN_EVENT_KEYS = frozenset(
    {
        "sdp",
        "ice",
        "ice_candidate",
        "icecandidates",
        "candidate",
        "candidates",
        "media",
        "media_track",
        "device_label",
        "devicelabel",
        "device_name",
        "track_sid_label",
        "narrative",
    }
)


def _reject_media_payload(payload: object) -> None:
    """Raise if a provider payload carries media-plane / device data."""
    if isinstance(payload, dict):
        for key, value in payload.items():
            if str(key).strip().lower().replace("-", "_") in _FORBIDDEN_EVENT_KEYS:
                raise VideoProviderError(
                    f"refusing a media-plane field ({key}) at the provider seam",
                    code="MEDIA_DATA_REFUSED",
                )
            _reject_media_payload(value)
    elif isinstance(payload, list):
        for item in payload:
            _reject_media_payload(item)


def hash_token(raw_token: str) -> str:
    """SHA-256 hex of a join token — the ONLY representation we may store."""
    return hashlib.sha256(raw_token.encode("utf-8")).hexdigest()


def _digest(raw_body: bytes) -> str:
    if isinstance(raw_body, str):  # pragma: no cover - defensive
        raw_body = raw_body.encode("utf-8")
    return hashlib.sha256(raw_body).hexdigest()


def _assert_ttl(ttl_seconds: int) -> int:
    if isinstance(ttl_seconds, bool) or not isinstance(ttl_seconds, int):
        raise VideoProviderError("ttl must be an integer", code="TTL_INVALID")
    if ttl_seconds <= 0:
        raise VideoProviderError("ttl must be positive", code="TTL_INVALID")
    if ttl_seconds > 24 * 3600:
        raise VideoProviderError(
            "join credentials must be short-lived", code="TTL_TOO_LONG"
        )
    return ttl_seconds


# --------------------------------------------------------------------------- #
# Webhook signature transports
# --------------------------------------------------------------------------- #

#: The header ``DeterministicVideoAdapter`` verifies: hex HMAC over the raw body.
DETERMINISTIC_WEBHOOK_HEADER = "X-Video-Signature"
#: The header a real LiveKit server signs with: a JWT carrying a ``sha256`` claim.
LIVEKIT_WEBHOOK_HEADER = "Authorization"
#: LiveKit's own content type for a webhook delivery. Recorded (and asserted by
#: the tests) so operators can recognise a genuine delivery; NOT used as an
#: authorisation input — a header a forger controls proves nothing.
LIVEKIT_WEBHOOK_CONTENT_TYPE = "application/webhook+json"


def _header_value(headers: Mapping[str, str] | None, name: str) -> str:
    """Case-insensitive header lookup that tolerates a plain ``dict``.

    Starlette's ``Headers`` is already case-insensitive; ``dict(request.headers)``
    is not (its keys are lower-cased). Both must work, and a delivery with no
    headers at all must read as "absent", never as an error.
    """
    if not headers:
        return ""
    getter = getattr(headers, "get", None)
    if callable(getter):
        direct = getter(name) or getter(name.lower())
        if direct:
            return str(direct)
    items = getattr(headers, "items", None)
    if callable(items):
        wanted = name.lower()
        for key, value in items():
            if str(key).lower() == wanted:
                return str(value or "")
    return ""


def _presented_signature(
    header_name: str,
    signature: str | None,
    headers: Mapping[str, str] | None,
) -> str:
    """The credential this delivery presents, from the explicit arg or the header.

    An explicit ``signature`` still wins so that in-process callers (workers,
    CLI tooling, the service-level tests) can hand a credential straight to the
    adapter without inventing an HTTP header. Anything blank falls through to the
    adapter's OWN header — which is why the route never has to know which header
    matters.
    """
    if signature is not None and str(signature).strip():
        return str(signature)
    return _header_value(headers, header_name)


def _assert_participant(participant_ref: str) -> str:
    ref = (participant_ref or "").strip()
    if not ref:
        raise VideoProviderError(
            "participant_ref is required", code="PARTICIPANT_REQUIRED"
        )
    if len(ref) > 64:
        raise VideoProviderError(
            "participant_ref too long", code="PARTICIPANT_INVALID"
        )
    if "@" in ref or any(c.isspace() for c in ref):
        # participant_ref must be an OPAQUE handle, never an email/name.
        raise VideoProviderError(
            "participant_ref must be an opaque handle",
            code="PARTICIPANT_INVALID",
        )
    return ref


# --------------------------------------------------------------------------- #
# Protocol
# --------------------------------------------------------------------------- #


@runtime_checkable
class VideoSessionProvider(Protocol):
    """The only video surface the domain services are allowed to know."""

    name: str
    #: The request header THIS adapter verifies. Declared on the adapter so the
    #: transport stays a provider detail and no route hard-codes one header for
    #: every provider.
    signature_header: str

    def ensure_room(self, session_id: uuid.UUID) -> str: ...

    def issue_credential(
        self,
        session_id: uuid.UUID,
        participant_ref: str,
        permissions: str,
        ttl_seconds: int,
        *,
        now: datetime | None = None,
    ) -> VideoCredential: ...

    def revoke_participant(self, room_ref: str, participant_ref: str) -> None: ...

    def close_room(self, room_ref: str) -> None: ...

    def verify_event(
        self,
        signature: str | None = None,
        raw_body: bytes = b"",
        *,
        headers: Mapping[str, str] | None = None,
    ) -> VideoEventData: ...


# --------------------------------------------------------------------------- #
# Deterministic adapter
# --------------------------------------------------------------------------- #

#: Fixed TEST signing key; the deterministic adapter is only selected when
#: ``settings.video_provider == "deterministic"``.
DETERMINISTIC_SIGNING_KEY = b"legalsaathi-deterministic-video-test-key"


class DeterministicVideoAdapter:
    """In-process video provider: deterministic topology, unpredictable secrets.

    Room references are a pure function of the session id (so tests and dev
    tooling can predict them), but join tokens are drawn from
    :mod:`secrets` — a *predictable* credential would be a security defect even
    in a test adapter, and the domain only ever compares hashes.
    """

    name = "deterministic"
    #: Its own transport, unchanged: hex HMAC-SHA256 of the raw body.
    signature_header = DETERMINISTIC_WEBHOOK_HEADER

    def __init__(self, signing_key: bytes = DETERMINISTIC_SIGNING_KEY) -> None:
        self._key = signing_key
        self.rooms: list[str] = []
        self.revoked: list[tuple[str, str]] = []
        self.closed: list[str] = []

    # -- test signing surface ------------------------------------------- #
    def sign(self, raw_body: bytes) -> str:
        if isinstance(raw_body, str):
            raw_body = raw_body.encode("utf-8")
        return hmac.new(self._key, raw_body, hashlib.sha256).hexdigest()

    def make_event_body(
        self,
        *,
        room_ref: str,
        event_type: str = "participant_joined",
        participant_ref: str | None = None,
        event_id: str | None = None,
    ) -> tuple[bytes, str]:
        payload = {
            "event_id": event_id or f"det_vevt_{secrets.token_hex(8)}",
            "event_type": event_type,
            "room_ref": room_ref,
            "participant_ref": participant_ref,
        }
        raw = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
        return raw, self.sign(raw)

    # -- Protocol ------------------------------------------------------- #
    def ensure_room(self, session_id: uuid.UUID) -> str:
        room_ref = "det_room_" + hashlib.sha256(str(session_id).encode()).hexdigest()[:24]
        if room_ref not in self.rooms:
            self.rooms.append(room_ref)
        return room_ref

    def issue_credential(
        self,
        session_id: uuid.UUID,
        participant_ref: str,
        permissions: str,
        ttl_seconds: int,
        *,
        now: datetime | None = None,
    ) -> VideoCredential:
        ttl = _assert_ttl(ttl_seconds)
        ref = _assert_participant(participant_ref)
        perms = normalise_permissions(permissions)
        room_ref = self.ensure_room(session_id)
        issued = now or datetime.now(timezone.utc)
        raw_token = f"join_{secrets.token_urlsafe(32)}"
        return VideoCredential(
            raw_token=raw_token,
            token_hash=hash_token(raw_token),
            room_ref=room_ref,
            expires_at=issued + timedelta(seconds=ttl),
            participant_ref=ref,
            permissions=perms,
        )

    def revoke_participant(self, room_ref: str, participant_ref: str) -> None:
        self.revoked.append((room_ref, participant_ref))

    def close_room(self, room_ref: str) -> None:
        self.closed.append(room_ref)

    def verify_event(
        self,
        signature: str | None = None,
        raw_body: bytes = b"",
        *,
        headers: Mapping[str, str] | None = None,
    ) -> VideoEventData:
        if isinstance(raw_body, str):
            raw_body = raw_body.encode("utf-8")
        presented = _presented_signature(self.signature_header, signature, headers)
        if not presented or not hmac.compare_digest(self.sign(raw_body), presented):
            raise VideoProviderError(
                "video webhook signature verification failed",
                code="SIGNATURE_INVALID",
            )
        try:
            payload = json.loads(raw_body.decode("utf-8"))
        except Exception as exc:
            raise VideoProviderError(
                f"malformed webhook body: {type(exc).__name__}",
                code="PAYLOAD_MALFORMED",
            ) from exc
        _reject_media_payload(payload)
        event_type = str(payload.get("event_type") or "")
        if event_type not in VIDEO_EVENT_TYPES:
            raise VideoProviderError(
                "unsupported event type", code="EVENT_TYPE_UNSUPPORTED"
            )
        return VideoEventData(
            provider=self.name,
            provider_event_id=str(payload.get("event_id") or ""),
            event_type=event_type,
            room_ref=str(payload.get("room_ref") or ""),
            participant_ref=payload.get("participant_ref"),
            payload_digest=_digest(raw_body),
        )


class FailingVideoAdapter:
    """Test double whose every call raises a configurable typed error."""

    name = "deterministic"
    signature_header = DETERMINISTIC_WEBHOOK_HEADER

    def __init__(self, *, retryable: bool = True, code: str = "PROVIDER_UNREACHABLE") -> None:
        self._retryable = retryable
        self._code = code

    def _boom(self):
        raise VideoProviderError(
            "video provider unavailable", code=self._code, retryable=self._retryable
        )

    def ensure_room(self, session_id: uuid.UUID) -> str:
        self._boom()

    def issue_credential(self, *args, **kwargs) -> VideoCredential:
        self._boom()

    def revoke_participant(self, room_ref: str, participant_ref: str) -> None:
        self._boom()

    def close_room(self, room_ref: str) -> None:
        self._boom()

    def verify_event(
        self,
        signature: str | None = None,
        raw_body: bytes = b"",
        *,
        headers: Mapping[str, str] | None = None,
    ) -> VideoEventData:
        self._boom()


# --------------------------------------------------------------------------- #
# LiveKit (community edition) adapter
# --------------------------------------------------------------------------- #


def _b64url(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


_B64URL_TO_STD = str.maketrans("-_", "+/")


def _b64url_decode(segment: str) -> bytes:
    """Strict base64url decode of one JWT segment.

    ``validate=True`` matters: without it base64 silently DISCARDS characters
    outside the alphabet, so a corrupted segment could decode to something
    plausible instead of failing. Padding is restored because JWT segments carry
    none.
    """
    padded = segment.translate(_B64URL_TO_STD) + "=" * (-len(segment) % 4)
    return base64.b64decode(padded, validate=True)


#: Clock-skew tolerance when checking ``exp``/``nbf`` on a LiveKit webhook token.
#: LiveKit mints them with ``SetValidFor(5 * time.Minute)``, so a few seconds of
#: slack costs nothing and refusing a 5-minute-old token still refuses a replayed
#: one. Deliberately NOT configurable: a deployment must not be able to widen it.
LIVEKIT_WEBHOOK_LEEWAY_SECONDS = 5
#: A signed JWT for a 5-minute webhook is a few hundred bytes. Anything an order
#: of magnitude larger is not a token and is refused before it is parsed.
_MAX_WEBHOOK_TOKEN_BYTES = 4096

_DEV_DEFAULT_SECRETS = frozenset(
    {"", "changeme", "change-me", "devkey", "devsecret", "secret", "livekit", "dev"}
)


class LiveKitCommunityAdapter:
    """LiveKit boundary. Config-driven, fails closed, ZERO livekit imports.

    The access token is a plain HS256 JWT over LiveKit's documented grant claim,
    constructed here with :mod:`hmac` + :mod:`base64` only. Keeping the grant
    construction inside this class is the whole point of the seam: the domain
    layer never learns that rooms are LiveKit rooms, and swapping providers
    touches no service code.

    Server-side operations (``revoke_participant`` / ``close_room``) call the
    Twirp room-service endpoints with a short-lived admin JWT; every transport
    or HTTP failure is normalised to ``VideoProviderError`` with ``retryable``
    set from the status class. The API secret is never logged.

    Webhook deliveries are verified the way LiveKit actually signs them — a JWT
    in ``Authorization`` whose ``sha256`` claim is the base64 SHA-256 of the exact
    raw body. See :meth:`_verify_webhook_token` for the algorithm and the reason
    it is hand-rolled.
    """

    name = "livekit"
    #: What a real LiveKit server signs with (see ``_verify_webhook_token``).
    signature_header = LIVEKIT_WEBHOOK_HEADER

    def __init__(
        self,
        url: str | None,
        api_key: str | None,
        api_secret: str | None,
        *,
        timeout_s: float = 10.0,
    ) -> None:
        if not url or not str(url).strip():
            raise VideoProviderError(
                "livekit url is not configured", code="PROVIDER_MISCONFIGURED"
            )
        if not api_key or api_key.strip().lower() in _DEV_DEFAULT_SECRETS:
            raise VideoProviderError(
                "livekit api key is not configured", code="PROVIDER_MISCONFIGURED"
            )
        if not api_secret or api_secret.strip().lower() in _DEV_DEFAULT_SECRETS:
            raise VideoProviderError(
                "livekit api secret is missing or a development default",
                code="PROVIDER_MISCONFIGURED",
            )
        if len(api_secret) < 16:
            raise VideoProviderError(
                "livekit api secret is too short to sign grants safely",
                code="PROVIDER_MISCONFIGURED",
            )
        # ``.strip()`` before ``.rstrip("/")``: ``Settings`` strips before it
        # validates the scheme, so an URL that satisfied the gate must not become
        # an unusable httpx target here because of surrounding whitespace.
        self._url = str(url).strip().rstrip("/")
        self._api_key = api_key
        self._api_secret = api_secret
        self._timeout_s = timeout_s

    # -- grant construction (isolated here on purpose) ------------------ #
    def _jwt(self, claims: dict) -> str:
        header = _b64url(
            json.dumps(
                {"alg": "HS256", "typ": "JWT"}, sort_keys=True, separators=(",", ":")
            ).encode("utf-8")
        )
        body = _b64url(
            json.dumps(claims, sort_keys=True, separators=(",", ":")).encode("utf-8")
        )
        signing_input = f"{header}.{body}".encode("ascii")
        sig = _b64url(
            hmac.new(self._api_secret.encode("utf-8"), signing_input, hashlib.sha256).digest()
        )
        return f"{header}.{body}.{sig}"

    @staticmethod
    def _video_grant(room_ref: str, permissions: str) -> dict:
        atoms = set(permissions.split(","))
        return {
            "room": room_ref,
            "roomJoin": True,
            "canSubscribe": "subscribe" in atoms,
            "canPublish": "publish" in atoms,
            "canPublishData": "publish_data" in atoms or "publish" in atoms,
            "roomAdmin": "manage" in atoms,
        }

    # -- Protocol ------------------------------------------------------- #
    def ensure_room(self, session_id: uuid.UUID) -> str:
        # Rooms are created lazily by LiveKit on first join; the reference is a
        # deterministic, non-identifying function of the session id.
        return "ls_" + hashlib.sha256(str(session_id).encode()).hexdigest()[:28]

    def issue_credential(
        self,
        session_id: uuid.UUID,
        participant_ref: str,
        permissions: str,
        ttl_seconds: int,
        *,
        now: datetime | None = None,
    ) -> VideoCredential:
        ttl = _assert_ttl(ttl_seconds)
        ref = _assert_participant(participant_ref)
        perms = normalise_permissions(permissions)
        room_ref = self.ensure_room(session_id)
        issued = now or datetime.now(timezone.utc)
        expires_at = issued + timedelta(seconds=ttl)
        raw_token = self._jwt(
            {
                "iss": self._api_key,
                "sub": ref,
                # Identity is the opaque participant ref - never a name/email.
                "name": ref,
                "nbf": int(issued.timestamp()) - 5,
                "exp": int(expires_at.timestamp()),
                "jti": f"{room_ref}:{ref}:{int(issued.timestamp())}",
                "video": self._video_grant(room_ref, perms),
            }
        )
        return VideoCredential(
            raw_token=raw_token,
            token_hash=hash_token(raw_token),
            room_ref=room_ref,
            expires_at=expires_at,
            participant_ref=ref,
            permissions=perms,
        )

    def revoke_participant(self, room_ref: str, participant_ref: str) -> None:
        self._twirp(
            "RemoveParticipant",
            {"room": room_ref, "identity": _assert_participant(participant_ref)},
        )

    def close_room(self, room_ref: str) -> None:
        self._twirp("DeleteRoom", {"room": room_ref})

    # -- webhook verification ------------------------------------------- #
    @staticmethod
    def _refuse() -> "VideoProviderError":
        """One indistinguishable refusal for every way a token can be wrong.

        Deliberately uniform and deliberately vague: telling a caller *which*
        check failed (bad signature vs. stale vs. body mismatch) is an oracle, and
        the operator-facing detail belongs in the runbook, not in a response a
        forger can iterate against. Non-retryable — a re-delivery of a token that
        does not verify will not verify the second time either.
        """
        return VideoProviderError(
            "video webhook signature verification failed",
            code="SIGNATURE_INVALID",
            retryable=False,
        )

    def _verify_webhook_token(self, token: str, raw_body: bytes) -> dict:
        """Verify a real LiveKit webhook credential. FAIL-CLOSED, no side effects.

        LiveKit signs a webhook with a JWT in ``Authorization`` (``livekit/protocol``
        → ``webhook/url_notifier.go``, ``URLNotifier.send``)::

            sum := sha256.Sum256(encoded)                      // the EXACT body
            b64 := base64.StdEncoding.EncodeToString(sum[:])
            at  := auth.NewAccessToken(key, secret).SetValidFor(5*time.Minute).SetSha256(b64)
            r.Header.Set("Authorization", token)

        So verification is, in order — and every failure raises the SAME
        ``SIGNATURE_INVALID`` before anything is read, parsed as an event, or
        written:

        1. a token is present at all (``Bearer`` prefix tolerated, since it costs
           nothing and some proxies add it);
        2. it is three base64url segments that decode to JSON objects;
        3. its header says ``alg: HS256`` — pinned, so ``alg: none`` and an
           RS256/HS256 confusion attempt are both refused before any HMAC;
        4. ``HMAC-SHA256(secret, "<header>.<payload>")`` equals the presented
           signature, compared with :func:`hmac.compare_digest`;
        5. ``iss`` is exactly the configured API key — a token minted with a
           *different* project's key pair is not ours;
        6. ``exp`` is present and not past, and ``nbf`` (when present) is not in
           the future, both within ``LIVEKIT_WEBHOOK_LEEWAY_SECONDS``;
        7. the ``sha256`` claim equals ``base64(SHA-256(raw_body))`` over the body
           bytes EXACTLY as received, again with :func:`hmac.compare_digest`.

        Step 7 is why the raw body has to reach this method: re-serialising the
        JSON would change the bytes (key order, separators, unicode escaping) and
        make every genuine delivery fail — or, worse, make a mutated body pass.

        Hand-rolled with :mod:`hmac` + :mod:`hashlib` because this repository has
        NO JWT dependency (``requirements.txt`` carries no pyjwt / python-jose /
        authlib) and one signed HS256 verification is not worth adding a
        transitive dependency to a fail-closed security path. The one hazard of
        hand-rolling — accepting whatever ``alg`` the token asks for — is closed
        explicitly in step 3.
        """
        candidate = (token or "").strip()
        if candidate[:7].lower() == "bearer ":
            candidate = candidate[7:].strip()
        if not candidate or len(candidate) > _MAX_WEBHOOK_TOKEN_BYTES:
            raise self._refuse()
        parts = candidate.split(".")
        if len(parts) != 3 or not all(parts):
            raise self._refuse()
        header_b64, payload_b64, signature_b64 = parts
        try:
            header = json.loads(_b64url_decode(header_b64))
            claims = json.loads(_b64url_decode(payload_b64))
            presented = _b64url_decode(signature_b64)
        except Exception as exc:  # malformed base64/JSON is just an invalid token
            raise self._refuse() from exc
        if not isinstance(header, dict) or not isinstance(claims, dict):
            raise self._refuse()
        # 3. PIN the algorithm. Never read `alg` to decide what to do.
        if str(header.get("alg") or "") != "HS256":
            raise self._refuse()
        expected_sig = hmac.new(
            self._api_secret.encode("utf-8"),
            f"{header_b64}.{payload_b64}".encode("ascii"),
            hashlib.sha256,
        ).digest()
        if not hmac.compare_digest(expected_sig, presented):
            raise self._refuse()
        # 5. issuer must be OUR api key.
        issuer = claims.get("iss")
        if not isinstance(issuer, str) or not hmac.compare_digest(
            issuer.encode("utf-8"), self._api_key.encode("utf-8")
        ):
            raise self._refuse()
        # 6. lifetime. exp is REQUIRED: a webhook token that never expires is a
        #    replayable credential, and LiveKit always sets one.
        now = int(datetime.now(timezone.utc).timestamp())
        exp = self._numeric_claim(claims, "exp", required=True)
        if now > exp + LIVEKIT_WEBHOOK_LEEWAY_SECONDS:
            raise self._refuse()
        nbf = self._numeric_claim(claims, "nbf", required=False)
        if nbf is not None and now + LIVEKIT_WEBHOOK_LEEWAY_SECONDS < nbf:
            raise self._refuse()
        # 7. the body digest, over the bytes AS RECEIVED.
        claimed_digest = claims.get("sha256")
        if not isinstance(claimed_digest, str) or not claimed_digest:
            raise self._refuse()
        body_digest = base64.b64encode(hashlib.sha256(raw_body).digest()).decode("ascii")
        if not hmac.compare_digest(body_digest, claimed_digest):
            raise self._refuse()
        return claims

    @classmethod
    def _numeric_claim(cls, claims: dict, name: str, *, required: bool) -> int | None:
        """A JWT time claim as an int. Absent-but-required, or non-numeric, refuse.

        ``bool`` is excluded on purpose (``True`` is an ``int`` in Python, and
        ``"exp": true`` must not read as the epoch second 1). Floats are accepted
        because RFC 7519 NumericDate permits them.
        """
        value = claims.get(name)
        if value is None:
            if required:
                raise cls._refuse()
            return None
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise cls._refuse()
        return int(value)

    def verify_event(
        self,
        signature: str | None = None,
        raw_body: bytes = b"",
        *,
        headers: Mapping[str, str] | None = None,
    ) -> VideoEventData:
        if isinstance(raw_body, str):
            raw_body = raw_body.encode("utf-8")
        token = _presented_signature(self.signature_header, signature, headers)
        # Verification FIRST: nothing below this line runs for an unverified body.
        self._verify_webhook_token(token, raw_body)
        try:
            body = json.loads(raw_body.decode("utf-8"))
        except Exception as exc:
            raise VideoProviderError(
                f"malformed webhook body: {type(exc).__name__}",
                code="PAYLOAD_MALFORMED",
            ) from exc
        _reject_media_payload(body)
        mapping = {
            "room_started": "room_started",
            "room_finished": "room_finished",
            "participant_joined": "participant_joined",
            "participant_left": "participant_left",
        }
        event_type = mapping.get(str(body.get("event") or ""))
        if event_type is None:
            raise VideoProviderError(
                "unsupported event type", code="EVENT_TYPE_UNSUPPORTED"
            )
        room = (body.get("room") or {}).get("name") or ""
        participant = (body.get("participant") or {}).get("identity")
        return VideoEventData(
            provider=self.name,
            provider_event_id=str(body.get("id") or ""),
            event_type=event_type,
            room_ref=str(room),
            participant_ref=participant,
            payload_digest=_digest(raw_body),
        )

    # -- transport ------------------------------------------------------ #
    def _admin_token(self) -> str:
        now = datetime.now(timezone.utc)
        return self._jwt(
            {
                "iss": self._api_key,
                "sub": self._api_key,
                "nbf": int(now.timestamp()) - 5,
                "exp": int((now + timedelta(seconds=60)).timestamp()),
                "video": {"roomAdmin": True, "roomList": True},
            }
        )

    def _twirp(self, method: str, payload: dict) -> dict:
        import httpx

        try:
            resp = httpx.post(
                f"{self._url}/twirp/livekit.RoomService/{method}",
                json=payload,
                headers={"Authorization": f"Bearer {self._admin_token()}"},
                timeout=self._timeout_s,
            )
        except Exception as exc:
            raise VideoProviderError(
                f"livekit transport failure: {type(exc).__name__}",
                code="PROVIDER_UNREACHABLE",
                retryable=True,
            ) from exc
        if resp.status_code >= 500 or resp.status_code == 429:
            raise VideoProviderError(
                f"livekit responded {resp.status_code}",
                code="PROVIDER_UNAVAILABLE",
                retryable=True,
            )
        if resp.status_code >= 400:
            raise VideoProviderError(
                f"livekit rejected the request ({resp.status_code})",
                code="PROVIDER_REJECTED",
            )
        try:
            return resp.json() or {}
        except Exception:
            return {}


# --------------------------------------------------------------------------- #
# DI selector
# --------------------------------------------------------------------------- #


def build_video_provider() -> VideoSessionProvider | None:
    """Resolve the configured video provider, or ``None`` when unusable.

    Same fail-closed contract as ``build_payment_provider`` /
    ``build_otp_sender``: ``None`` means "not configured", and callers must
    surface PROVIDER_UNAVAILABLE instead of minting a credential.
    """
    provider = (getattr(settings, "video_provider", "none") or "none").lower()
    if provider == "deterministic":
        return DeterministicVideoAdapter()
    if provider == "livekit":
        if not settings.livekit_url or not has_secret(
            settings.livekit_api_key
        ) or not has_secret(settings.livekit_api_secret):
            return None
        try:
            return LiveKitCommunityAdapter(
                settings.livekit_url,
                settings.livekit_api_key.get_secret_value(),
                settings.livekit_api_secret.get_secret_value(),
            )
        except VideoProviderError:
            return None
    return None
