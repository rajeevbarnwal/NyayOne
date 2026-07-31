"""LiveKit webhook signature transport, end to end (SAATHI-451 defect fix).

WHAT THIS FILE PROVES. That ``LiveKitCommunityAdapter`` verifies a delivery
shaped exactly the way a real LiveKit server shapes one, and refuses every
near-miss. The ``Authorization`` JWT is built HERE, from the upstream algorithm,
with no help from the adapter — ``_livekit_authorization`` is an independent
re-implementation of ``livekit/protocol`` → ``webhook/url_notifier.go``,
``URLNotifier.send``::

    encoded, _ := protojson.Marshal(event)              // the body, as bytes
    sum := sha256.Sum256(encoded)
    b64 := base64.StdEncoding.EncodeToString(sum[:])    // STD base64, padded
    at  := auth.NewAccessToken(apiKey, apiSecret).
             SetValidFor(5 * time.Minute).
             SetSha256(b64)
    token, _ := at.ToJWT()                              // HS256, iss = apiKey
    r.Header.Set("Authorization", token)
    r.Header.Set("content-type", "application/webhook+json")

If the adapter and this file ever disagree, one of them is wrong about LiveKit —
which is the point: a verifier tested only against its own signer proves nothing.

WHAT THIS FILE CANNOT PROVE. No real LiveKit server has delivered a webhook in
this environment. Nothing here starts an SFU, joins a room or moves a packet.
The bytes are constructed from the upstream source; the CLAIM is
"transport-compatible with what that source sends", not "observed in production".
``infra/video/RUNBOOK.md`` § 9 keeps the live check listed as UNEXECUTED.

WHY IT LIVES AT THE HTTP BOUNDARY. The defect was a *wiring* defect as much as a
crypto one: the route used to read one hard-coded header and hand it to whichever
adapter was configured. So the positive case drives the real route, through the
real service, and asserts the real E2 effects (a ``video:...`` history row,
event-driven revocation, duplicate refusal) rather than calling the adapter
directly.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time
import uuid

import pytest
from pydantic import SecretStr
from sqlalchemy import func, select

import tests.wave2_helpers as W
from app.core import rate_limit
from app.core.config import settings
from app.models.wave2 import SessionStatusHistory, TutoringSession, VideoSessionGrant
from app.services.providers.video_provider import (
    DETERMINISTIC_WEBHOOK_HEADER,
    LIVEKIT_WEBHOOK_CONTENT_TYPE,
    LIVEKIT_WEBHOOK_HEADER,
    DeterministicVideoAdapter,
    LiveKitCommunityAdapter,
    VideoProviderError,
)

T0 = W.T0

#: Obviously-fake credentials. The KEY is an identifier; the SECRET is long
#: enough for the adapter's own >= 16 char rule and is not a real credential.
API_KEY = "APIwave2WebhookTest"
API_SECRET = "0f1e2d3c4b5a69788796a5b4c3d2e1f0"
OTHER_SECRET = "ffffffffffffffff0000000000000000"
LIVEKIT_URL = "http://livekit.invalid:7880"


# --------------------------------------------------------------------------- #
# An independent implementation of LiveKit's webhook signing
# --------------------------------------------------------------------------- #


def _b64url(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def _body_sha256_b64(raw_body: bytes) -> str:
    """``base64.StdEncoding.EncodeToString(sha256.Sum256(body))`` — padded STD."""
    return base64.b64encode(hashlib.sha256(raw_body).digest()).decode("ascii")


def _livekit_authorization(
    raw_body: bytes,
    *,
    secret: str = API_SECRET,
    api_key: str = API_KEY,
    valid_for: int = 300,
    issued_at: float | None = None,
    nbf_offset: int = 0,
    alg: str = "HS256",
    sha256_override: object = ...,
    drop_claims: tuple[str, ...] = (),
    extra_claims: dict | None = None,
) -> str:
    """Build the header value a real LiveKit server would send.

    Every knob exists to express ONE tampering case in a test; the defaults are
    the genuine article.
    """
    now = int(issued_at if issued_at is not None else time.time())
    claims: dict = {
        "iss": api_key,
        "nbf": now + nbf_offset,
        "exp": now + valid_for,
        "sha256": _body_sha256_b64(raw_body),
        "video": {"roomList": True},
    }
    if sha256_override is not ...:
        claims["sha256"] = sha256_override
    if extra_claims:
        claims.update(extra_claims)
    for name in drop_claims:
        claims.pop(name, None)
    header = _b64url(
        json.dumps({"alg": alg, "typ": "JWT"}, separators=(",", ":")).encode("utf-8")
    )
    payload = _b64url(json.dumps(claims, separators=(",", ":")).encode("utf-8"))
    signing_input = f"{header}.{payload}".encode("ascii")
    if alg == "none":
        return f"{header}.{payload}."
    signature = hmac.new(secret.encode("utf-8"), signing_input, hashlib.sha256).digest()
    return f"{header}.{payload}.{_b64url(signature)}"


def _sign_segments(header_b64: str, payload_b64: str, *, secret: str = API_SECRET) -> str:
    """Sign ARBITRARY segments correctly.

    Needed to prove the structural checks on their own: a token whose HMAC is
    valid but whose header/payload is not a JSON object must still be refused, and
    that is only testable if the signature is genuinely right.
    """
    signature = hmac.new(
        secret.encode("utf-8"),
        f"{header_b64}.{payload_b64}".encode("ascii"),
        hashlib.sha256,
    ).digest()
    return f"{header_b64}.{payload_b64}.{_b64url(signature)}"


def _genuine_payload_segment(raw_body: bytes) -> str:
    return _livekit_authorization(raw_body).split(".")[1]


def _livekit_body(
    room_ref: str,
    *,
    event: str = "participant_joined",
    participant_ref: str | None = None,
    event_id: str | None = None,
) -> bytes:
    """A LiveKit ``WebhookEvent``, serialised the way protojson would.

    Returned as BYTES and never re-serialised: the ``sha256`` claim is taken over
    these exact bytes, so any round-trip through ``json.loads``/``json.dumps``
    would (correctly) invalidate the signature.
    """
    payload: dict = {
        "event": event,
        "id": event_id or f"EV_{uuid.uuid4().hex[:12]}",
        "createdAt": str(int(T0.timestamp())),
        "room": {"sid": "RM_test", "name": room_ref},
    }
    if participant_ref is not None:
        payload["participant"] = {"sid": "PA_test", "identity": participant_ref}
    return json.dumps(payload).encode("utf-8")


def _adapter(*, secret: str = API_SECRET, api_key: str = API_KEY):
    return LiveKitCommunityAdapter(LIVEKIT_URL, api_key, secret)


# --------------------------------------------------------------------------- #
# Fixtures: the real app, with the LIVEKIT adapter selected
# --------------------------------------------------------------------------- #


@pytest.fixture(scope="module")
def rig():
    rig = W.ApiRig()
    yield rig
    rig.close()


@pytest.fixture()
def ctx(monkeypatch, rig):
    """A booked session with ``video_provider='livekit'`` actually in force.

    ``build_video_provider()`` is left alone: pointing the real selector at
    obviously-fake credentials is what makes this an end-to-end test of the
    configured path rather than of an injected double. The provider transport
    seam is stubbed because this file owns webhook signature semantics, not SFU
    availability. Separate provider-down and live-runtime tests prove that the
    production reachability probe fails closed.
    """
    context = rig.context(monkeypatch, now=T0)
    monkeypatch.setattr(settings, "video_provider", "livekit")
    monkeypatch.setattr(settings, "livekit_url", LIVEKIT_URL)
    monkeypatch.setattr(settings, "livekit_api_key", SecretStr(API_KEY))
    monkeypatch.setattr(settings, "livekit_api_secret", SecretStr(API_SECRET))
    monkeypatch.setattr(
        LiveKitCommunityAdapter,
        "_twirp",
        lambda _self, _method, _payload: {"rooms": []},
    )
    yield context
    rate_limit.reset()


def _booked(ctx):
    with ctx.SessionLocal() as s:
        booked = W.book_session(s, ctx.world, now=ctx.clock.at)
        return booked.tutoring_session.id


def _issue(ctx, session_id):
    r = ctx.post(f"/api/v1/tutoring/sessions/{session_id}/join-credentials")
    assert r.status_code == 201, r.text
    return r.json()


def _deliver(ctx, raw: bytes, authorization: str | None, **extra_headers):
    """POST a delivery the way LiveKit would: raw body, JWT in ``Authorization``."""
    headers = {"content-type": LIVEKIT_WEBHOOK_CONTENT_TYPE, **extra_headers}
    if authorization is not None:
        headers[LIVEKIT_WEBHOOK_HEADER] = authorization
    return ctx.client.post("/api/v1/video/webhook", content=raw, headers=headers)


def _video_history(ctx, session_id=None):
    with ctx.fresh() as s:
        rows = s.scalars(select(SessionStatusHistory)).all()
        return [
            row.reason
            for row in rows
            if str(row.reason or "").startswith("video:")
            and (session_id is None or row.session_id == session_id)
        ]


def _grant_count(ctx):
    with ctx.fresh() as s:
        return s.scalar(select(func.count()).select_from(VideoSessionGrant))


# --------------------------------------------------------------------------- #
# The genuine article is ACCEPTED and drives E2
# --------------------------------------------------------------------------- #


def test_the_livekit_adapter_is_what_the_route_actually_resolves(ctx):
    """Guards the fixture: if this ever returns the deterministic adapter, the
    'end to end' claim below would be vacuous."""
    from app.services.providers.video_provider import build_video_provider

    resolved = build_video_provider()
    assert isinstance(resolved, LiveKitCommunityAdapter)
    assert resolved.signature_header == LIVEKIT_WEBHOOK_HEADER == "Authorization"
    # The two adapters must NOT have been collapsed onto one header.
    assert DeterministicVideoAdapter.signature_header == DETERMINISTIC_WEBHOOK_HEADER
    assert DeterministicVideoAdapter.signature_header != LIVEKIT_WEBHOOK_HEADER


def test_a_genuine_livekit_delivery_is_verified_and_recorded(ctx):
    session_id = _booked(ctx)
    grant = _issue(ctx, session_id)
    # A LiveKit room reference, produced by the LiveKit adapter.
    assert grant["room_ref"].startswith("ls_")

    raw = _livekit_body(grant["room_ref"], participant_ref=grant["participant_ref"])
    r = _deliver(ctx, raw, _livekit_authorization(raw))
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["session_id"] == str(session_id)
    assert body["event_type"] == "participant_joined"
    assert body["participant_ref"] == grant["participant_ref"]
    # A join is recorded but must never move the session's status (matrix D4).
    assert body["session_status"] == "confirmed"
    assert body["grants_revoked"] == 0
    with ctx.fresh() as s:
        assert s.get(TutoringSession, session_id).status == "confirmed"
    assert any(h.startswith("video:participant_joined:") for h in _video_history(ctx))


def test_a_genuine_departure_revokes_the_participants_grant(ctx):
    """The E2 effect that the transport defect was costing us entirely."""
    session_id = _booked(ctx)
    grant = _issue(ctx, session_id)
    raw = _livekit_body(
        grant["room_ref"],
        event="participant_left",
        participant_ref=grant["participant_ref"],
    )
    r = _deliver(ctx, raw, _livekit_authorization(raw))
    assert r.status_code == 200, r.text
    assert r.json()["grants_revoked"] == 1
    with ctx.fresh() as s:
        row = s.scalars(select(VideoSessionGrant)).one()
        assert row.revoked_at is not None


def test_room_finished_revokes_every_grant_for_the_session(ctx):
    session_id = _booked(ctx)
    grant = _issue(ctx, session_id)
    raw = _livekit_body(grant["room_ref"], event="room_finished")
    r = _deliver(ctx, raw, _livekit_authorization(raw))
    assert r.status_code == 200, r.text
    assert r.json()["grants_revoked"] >= 1
    with ctx.fresh() as s:
        assert all(g.revoked_at is not None for g in s.scalars(select(VideoSessionGrant)))


def test_a_body_with_unicode_and_awkward_separators_still_verifies(ctx):
    """The digest is over the bytes AS RECEIVED, so byte-exactness is the contract.

    A body with non-ASCII text, unusual separators and non-sorted keys would be
    re-serialised differently by any implementation that hashed a parsed object
    instead of the raw bytes — and would then fail. It must not.
    """
    session_id = _booked(ctx)
    grant = _issue(ctx, session_id)
    raw = (
        '{ "event" : "participant_joined" ,\n'
        '  "id": "EV_नमस्ते_1" ,\n'
        f'  "room": {{ "name": "{grant["room_ref"]}" }} ,\n'
        f'  "participant": {{ "identity": "{grant["participant_ref"]}" }} }}'
    ).encode("utf-8")
    r = _deliver(ctx, raw, _livekit_authorization(raw))
    assert r.status_code == 200, r.text
    assert r.json()["event_type"] == "participant_joined"


def test_a_bearer_prefixed_authorization_is_tolerated(ctx):
    """Some proxies add ``Bearer ``; LiveKit does not. Both must verify."""
    session_id = _booked(ctx)
    grant = _issue(ctx, session_id)
    raw = _livekit_body(grant["room_ref"], participant_ref=grant["participant_ref"])
    r = _deliver(ctx, raw, "Bearer " + _livekit_authorization(raw))
    assert r.status_code == 200, r.text


# --------------------------------------------------------------------------- #
# Every rejection: fail-closed, non-retryable, nothing read, nothing written
# --------------------------------------------------------------------------- #


def _mutate_one_byte(raw: bytes) -> bytes:
    """Flip exactly one byte of the body, keeping it valid JSON of the same length."""
    index = raw.index(b"EV_") + 3
    replacement = b"0" if raw[index : index + 1] != b"0" else b"1"
    return raw[:index] + replacement + raw[index + 1 :]


#: name -> (authorization builder, body mutator). ``None`` authorization means the
#: header is absent from the request entirely.
REJECTIONS = {
    "authorization_header_absent": (lambda raw: None, None),
    "authorization_header_empty": (lambda raw: "", None),
    "authorization_header_whitespace": (lambda raw: "   ", None),
    "not_a_jwt_at_all": (lambda raw: "deadbeef", None),
    "hex_hmac_of_the_body": (
        # The OLD scheme. It must not be accepted by the LiveKit adapter: two
        # transports coexisting on one adapter is two chances to get it wrong.
        lambda raw: hmac.new(
            API_SECRET.encode(), raw, hashlib.sha256
        ).hexdigest(),
        None,
    ),
    "malformed_jwt_two_segments": (
        lambda raw: ".".join(_livekit_authorization(raw).split(".")[:2]),
        None,
    ),
    "malformed_jwt_four_segments": (
        lambda raw: _livekit_authorization(raw) + ".extra",
        None,
    ),
    "malformed_jwt_empty_segment": (
        lambda raw: "." + ".".join(_livekit_authorization(raw).split(".")[1:]),
        None,
    ),
    "malformed_jwt_non_base64": (
        lambda raw: "!!!.???.***",
        None,
    ),
    # Correctly SIGNED but structurally wrong: proves the shape checks stand on
    # their own rather than being incidentally covered by the HMAC.
    "signed_but_payload_is_not_an_object": (
        lambda raw: _sign_segments(
            _b64url(b'{"alg":"HS256","typ":"JWT"}'), _b64url(b'"a string"')
        ),
        None,
    ),
    "signed_but_header_is_not_an_object": (
        lambda raw: _sign_segments(_b64url(b'"HS256"'), _genuine_payload_segment(raw)),
        None,
    ),
    "signed_but_alg_absent_from_header": (
        lambda raw: _sign_segments(
            _b64url(b'{"typ":"JWT"}'), _genuine_payload_segment(raw)
        ),
        None,
    ),
    "signed_with_the_wrong_secret": (
        lambda raw: _livekit_authorization(raw, secret=OTHER_SECRET),
        None,
    ),
    "signature_truncated": (
        lambda raw: _livekit_authorization(raw)[:-4],
        None,
    ),
    "alg_none_unsigned": (
        lambda raw: _livekit_authorization(raw, alg="none"),
        None,
    ),
    "alg_swapped_to_hs512": (
        lambda raw: _livekit_authorization(raw, alg="HS512"),
        None,
    ),
    "expired": (
        lambda raw: _livekit_authorization(raw, valid_for=300, issued_at=time.time() - 3600),
        None,
    ),
    "expired_just_outside_the_leeway": (
        lambda raw: _livekit_authorization(raw, valid_for=0, issued_at=time.time() - 60),
        None,
    ),
    "not_yet_valid": (
        lambda raw: _livekit_authorization(raw, issued_at=time.time() + 3600),
        None,
    ),
    "exp_claim_absent": (
        lambda raw: _livekit_authorization(raw, drop_claims=("exp",)),
        None,
    ),
    "exp_claim_not_numeric": (
        lambda raw: _livekit_authorization(raw, extra_claims={"exp": "soon"}),
        None,
    ),
    "wrong_issuer": (
        lambda raw: _livekit_authorization(raw, api_key="APIsomeoneElsesProject"),
        None,
    ),
    "issuer_absent": (
        lambda raw: _livekit_authorization(raw, drop_claims=("iss",)),
        None,
    ),
    "sha256_claim_absent": (
        lambda raw: _livekit_authorization(raw, drop_claims=("sha256",)),
        None,
    ),
    "sha256_claim_empty": (
        lambda raw: _livekit_authorization(raw, sha256_override=""),
        None,
    ),
    "sha256_claim_not_a_string": (
        lambda raw: _livekit_authorization(raw, sha256_override=0),
        None,
    ),
    "sha256_claim_is_hex_not_base64": (
        lambda raw: _livekit_authorization(
            raw, sha256_override=hashlib.sha256(raw).hexdigest()
        ),
        None,
    ),
    "sha256_claim_over_a_different_body": (
        lambda raw: _livekit_authorization(raw, sha256_override=_body_sha256_b64(b"{}")),
        None,
    ),
    "body_mutated_by_one_byte_after_signing": (
        _livekit_authorization,
        _mutate_one_byte,
    ),
    "body_replaced_with_an_empty_object": (
        _livekit_authorization,
        lambda raw: b"{}",
    ),
    "body_padded_with_one_trailing_newline": (
        _livekit_authorization,
        lambda raw: raw + b"\n",
    ),
}


@pytest.mark.parametrize("case", sorted(REJECTIONS))
def test_every_bad_livekit_delivery_is_refused_and_writes_nothing(ctx, case):
    """400 ``VIDEO_UNVERIFIED``, and the database is untouched.

    ``VIDEO_UNVERIFIED`` is the NON-retryable mapping (``ProviderUnavailable``,
    the retryable one, is reserved for a provider that could not be reached), so
    asserting the code asserts the retry posture too: LiveKit is told the
    delivery is permanently unacceptable rather than invited to redeliver.
    """
    build_auth, mutate = REJECTIONS[case]
    session_id = _booked(ctx)
    grant = _issue(ctx, session_id)
    grants_before = _grant_count(ctx)

    raw = _livekit_body(grant["room_ref"], participant_ref=grant["participant_ref"])
    authorization = build_auth(raw)
    delivered = mutate(raw) if mutate else raw

    r = _deliver(ctx, delivered, authorization)
    assert r.status_code == 400, (case, r.status_code, r.text)
    assert r.json()["detail"]["code"] == "VIDEO_UNVERIFIED", case
    # Nothing was read as an event and nothing was written.
    assert _video_history(ctx) == [], case
    assert _grant_count(ctx) == grants_before, case
    with ctx.fresh() as s:
        assert s.get(TutoringSession, session_id).status == "confirmed"
        assert all(g.revoked_at is None for g in s.scalars(select(VideoSessionGrant)))


def test_the_rejection_response_is_not_an_oracle(ctx):
    """Every refusal looks the same, so a forger learns nothing from iterating."""
    session_id = _booked(ctx)
    grant = _issue(ctx, session_id)
    raw = _livekit_body(grant["room_ref"], participant_ref=grant["participant_ref"])
    seen = set()
    for case in ("signed_with_the_wrong_secret", "expired", "wrong_issuer"):
        build_auth, _mutator = REJECTIONS[case]
        r = _deliver(ctx, raw, build_auth(raw))
        seen.add(json.dumps(r.json(), sort_keys=True))
    body_mismatch = _deliver(ctx, _mutate_one_byte(raw), _livekit_authorization(raw))
    seen.add(json.dumps(body_mismatch.json(), sort_keys=True))
    assert len(seen) == 1, seen
    # And no message names the secret, the key, or which check failed.
    only = seen.pop()
    for leak in (API_SECRET, OTHER_SECRET, "sha256", "exp", "iss"):
        assert leak not in only


def test_a_replayed_genuine_delivery_is_still_a_duplicate(ctx):
    """Verification is necessary, not sufficient: replay protection is separate.

    The SAME bytes with the SAME (still valid) token verify twice — so if event
    application were not idempotent, a captured delivery could be replayed until
    the token expired. The second attempt is ``DUPLICATE_EVENT`` and adds no row.
    """
    session_id = _booked(ctx)
    grant = _issue(ctx, session_id)
    raw = _livekit_body(grant["room_ref"], participant_ref=grant["participant_ref"])
    authorization = _livekit_authorization(raw)

    first = _deliver(ctx, raw, authorization)
    assert first.status_code == 200, first.text
    history_after_first = _video_history(ctx)
    assert len(history_after_first) == 1

    replay = _deliver(ctx, raw, authorization)
    assert replay.status_code == 409, replay.text
    assert replay.json()["detail"]["code"] == "DUPLICATE_EVENT"
    assert _video_history(ctx) == history_after_first


def test_a_verified_event_for_an_unknown_room_is_not_found_and_writes_nothing(ctx):
    """A perfectly signed event about a room nobody holds a grant for."""
    session_id = _booked(ctx)
    _issue(ctx, session_id)
    raw = _livekit_body("ls_" + "0" * 28, participant_ref="p_unknown")
    r = _deliver(ctx, raw, _livekit_authorization(raw))
    assert r.status_code == 404
    assert r.json()["detail"]["code"] == "NOT_FOUND"
    assert _video_history(ctx) == []


def test_media_plane_fields_are_still_refused_on_a_verified_delivery(ctx):
    """Signature verification must not become a licence to persist media data."""
    session_id = _booked(ctx)
    grant = _issue(ctx, session_id)
    raw = json.dumps(
        {
            "event": "participant_joined",
            "id": "EV_media",
            "room": {"name": grant["room_ref"]},
            "participant": {
                "identity": grant["participant_ref"],
                "sdp": "v=0 o=- 0 0 IN IP4 0.0.0.0",
            },
        }
    ).encode("utf-8")
    r = _deliver(ctx, raw, _livekit_authorization(raw))
    assert r.status_code == 400
    assert r.json()["detail"]["code"] == "VIDEO_UNVERIFIED"
    assert _video_history(ctx) == []


# --------------------------------------------------------------------------- #
# Adapter-level properties that do not need a database
# --------------------------------------------------------------------------- #


def test_the_adapter_refuses_a_delivery_carrying_only_the_other_adapters_header():
    """Header confusion: the deterministic scheme is not a LiveKit credential."""
    adapter = _adapter()
    raw = _livekit_body("ls_room")
    headers = {
        DETERMINISTIC_WEBHOOK_HEADER: DeterministicVideoAdapter().sign(raw),
        "content-type": LIVEKIT_WEBHOOK_CONTENT_TYPE,
    }
    with pytest.raises(VideoProviderError) as excinfo:
        adapter.verify_event(raw_body=raw, headers=headers)
    assert excinfo.value.code == "SIGNATURE_INVALID"
    assert not excinfo.value.retryable


def test_the_adapter_reads_the_header_case_insensitively():
    """``dict(request.headers)`` lower-cases keys; a raw ``dict`` does not."""
    adapter = _adapter()
    raw = _livekit_body("ls_room")
    token = _livekit_authorization(raw)
    for name in ("Authorization", "authorization", "AUTHORIZATION"):
        data = adapter.verify_event(raw_body=raw, headers={name: token})
        assert data.provider == "livekit"
        assert data.signature_verified is True


def test_a_token_valid_for_another_project_key_pair_is_refused():
    """Both halves must match: right secret + wrong key, and vice versa."""
    raw = _livekit_body("ls_room")
    right = _adapter()
    # Correct secret, but the token claims a different project's key.
    with pytest.raises(VideoProviderError) as wrong_key:
        right.verify_event(
            _livekit_authorization(raw, api_key="APIotherProject"), raw
        )
    assert wrong_key.value.code == "SIGNATURE_INVALID"
    # Correct key, but signed with a different project's secret.
    with pytest.raises(VideoProviderError) as wrong_secret:
        right.verify_event(_livekit_authorization(raw, secret=OTHER_SECRET), raw)
    assert wrong_secret.value.code == "SIGNATURE_INVALID"
    # An adapter holding the OTHER pair accepts the other token, so the fixtures
    # differ only in the credential and not in some accident of shape.
    other = _adapter(secret=OTHER_SECRET)
    assert other.verify_event(_livekit_authorization(raw, secret=OTHER_SECRET), raw)


def test_an_absurdly_large_authorization_header_is_refused_before_parsing():
    adapter = _adapter()
    raw = _livekit_body("ls_room")
    token = _livekit_authorization(raw)
    with pytest.raises(VideoProviderError) as excinfo:
        adapter.verify_event(token + "A" * 8192, raw)
    assert excinfo.value.code == "SIGNATURE_INVALID"


def test_an_unsupported_event_type_is_refused_even_when_signed():
    adapter = _adapter()
    raw = _livekit_body("ls_room", event="track_published")
    with pytest.raises(VideoProviderError) as excinfo:
        adapter.verify_event(_livekit_authorization(raw), raw)
    assert excinfo.value.code == "EVENT_TYPE_UNSUPPORTED"


def test_a_verified_event_maps_to_the_neutral_shape_with_a_body_digest():
    adapter = _adapter()
    raw = _livekit_body("ls_room", participant_ref="p_abc", event_id="EV_neutral")
    data = adapter.verify_event(_livekit_authorization(raw), raw)
    assert data.provider == "livekit"
    assert data.provider_event_id == "EV_neutral"
    assert data.event_type == "participant_joined"
    assert data.room_ref == "ls_room"
    assert data.participant_ref == "p_abc"
    # The digest recorded for audit is the hex SHA-256 of the RAW body.
    assert data.payload_digest == hashlib.sha256(raw).hexdigest()


# --------------------------------------------------------------------------- #
# The deterministic adapter's own scheme is UNCHANGED
# --------------------------------------------------------------------------- #


def test_the_deterministic_scheme_still_verifies_and_still_rejects():
    """Mandatory for the automated/business-contract suite; must not have moved."""
    adapter = DeterministicVideoAdapter()
    raw, signature = adapter.make_event_body(room_ref="det_room_x")
    # Explicit signature (worker/CLI style)...
    assert adapter.verify_event(signature, raw).room_ref == "det_room_x"
    # ...and via its OWN header (HTTP style), which is not LiveKit's.
    assert adapter.verify_event(
        raw_body=raw, headers={DETERMINISTIC_WEBHOOK_HEADER: signature}
    ).room_ref == "det_room_x"
    assert adapter.signature_header == "X-Video-Signature"

    # ``one_char_off`` must actually differ: the signature is random per body, so
    # "replace the last character with '0'" would silently be a no-op ~1/16 of the
    # time and make this test flaky rather than strict.
    one_char_off = signature[:-1] + ("1" if signature[-1] == "0" else "0")
    assert one_char_off != signature
    for bad in ("", "   ", "deadbeef", "0" * 64, one_char_off):
        with pytest.raises(VideoProviderError) as excinfo:
            adapter.verify_event(bad, raw)
        assert excinfo.value.code == "SIGNATURE_INVALID"
        assert not excinfo.value.retryable
    # A LiveKit-shaped JWT is not a deterministic credential either.
    with pytest.raises(VideoProviderError) as excinfo:
        adapter.verify_event(
            raw_body=raw,
            headers={LIVEKIT_WEBHOOK_HEADER: _livekit_authorization(raw)},
        )
    assert excinfo.value.code == "SIGNATURE_INVALID"
    # Body tampering is caught by this scheme too.
    with pytest.raises(VideoProviderError) as excinfo:
        adapter.verify_event(signature, raw + b" ")
    assert excinfo.value.code == "SIGNATURE_INVALID"


def test_the_deterministic_route_path_is_untouched(monkeypatch, rig):
    """The default deployment still verifies over ``X-Video-Signature``."""
    ctx = rig.context(monkeypatch, now=T0)
    monkeypatch.setattr(settings, "video_provider", "deterministic")
    session_id = _booked(ctx)
    grant = _issue(ctx, session_id)
    raw, signature = DeterministicVideoAdapter().make_event_body(
        room_ref=grant["room_ref"], participant_ref=grant["participant_ref"]
    )
    good = ctx.client.post(
        "/api/v1/video/webhook",
        content=raw,
        headers={DETERMINISTIC_WEBHOOK_HEADER: signature},
    )
    assert good.status_code == 200, good.text
    bad = ctx.client.post(
        "/api/v1/video/webhook",
        content=raw,
        headers={DETERMINISTIC_WEBHOOK_HEADER: "0" * 64},
    )
    assert bad.status_code == 400
    assert bad.json()["detail"]["code"] == "VIDEO_UNVERIFIED"
    rate_limit.reset()
