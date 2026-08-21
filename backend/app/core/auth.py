"""Auth-context abstraction and RBAC hooks (SAATHI-337).

Reuses the EXISTING identity service assumptions (P0.2 student auth, P0.1 lawyer
verification) — this module does not create a second identity system. It defines
the current-user/session contract and FastAPI dependency stubs that domain
routers will depend on. Real token verification is wired when the IdP integration
lands; until then `build_actor_context` reads a verified claims dict.

Key rule: S21 lawyer features stay LOCKED until P0.1 lawyer verification passes.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from urllib.parse import urlsplit

from fastapi import Depends, Header, HTTPException, Request, status
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.session import get_session


class Role(str, Enum):
    STUDENT = "student"
    TUTOR = "tutor"
    LAWYER = "lawyer"
    ADMIN = "admin"
    MODERATOR = "moderator"
    SAFETY_OFFICER = "safety_officer"
    LEGAL_REVIEWER = "legal_reviewer"


class VerificationStatus(str, Enum):
    DRAFT = "draft"
    SUBMITTED = "submitted"
    NEEDS_INFO = "needs_info"
    VERIFIED = "verified"
    REJECTED = "rejected"


@dataclass(frozen=True)
class ActorContext:
    """Per-request identity/authorization snapshot."""

    user_id: uuid.UUID | None = None
    roles: frozenset[Role] = field(default_factory=frozenset)
    student_profile_id: uuid.UUID | None = None
    lawyer_profile_id: uuid.UUID | None = None
    student_verification: VerificationStatus = VerificationStatus.DRAFT
    lawyer_verification: VerificationStatus = VerificationStatus.DRAFT
    is_minor: bool = False
    consent_state: frozenset[str] = field(default_factory=frozenset)

    # --- derived checks ---
    @property
    def is_authenticated(self) -> bool:
        return self.user_id is not None

    def has_role(self, role: Role) -> bool:
        return role in self.roles

    @property
    def is_student_verified(self) -> bool:
        return self.student_verification is VerificationStatus.VERIFIED

    @property
    def can_use_lawyer_features(self) -> bool:
        """S21 gate: lawyer features require role + P0.1 verification passed."""
        return Role.LAWYER in self.roles and self.lawyer_verification is VerificationStatus.VERIFIED

    def has_consent(self, kind: str) -> bool:
        return kind in self.consent_state


ANONYMOUS = ActorContext()

_COOKIE_MUTATING_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})


def _canonical_http_origin(value: str | None) -> str | None:
    """Return a comparison-safe HTTP(S) origin, never a URL prefix."""

    raw = (value or "").strip()
    if not raw or raw in {"null", "*"}:
        return None
    try:
        parsed = urlsplit(raw)
        port = parsed.port
    except ValueError:
        return None
    scheme = parsed.scheme.casefold()
    host = (parsed.hostname or "").casefold()
    if (
        scheme not in {"http", "https"}
        or not host
        or parsed.username is not None
        or parsed.password is not None
        or parsed.path != ""
        or parsed.query
        or parsed.fragment
    ):
        return None
    authority_host = f"[{host}]" if ":" in host else host
    if port is None or (scheme, port) in {("http", 80), ("https", 443)}:
        authority = authority_host
    else:
        authority = f"{authority_host}:{port}"
    return f"{scheme}://{authority}"


def require_trusted_cookie_origin(request: Request) -> None:
    """Reject cross-origin mutation whenever browser session authority exists.

    Public registration/OTP requests and test-only header actors do not depend
    on ambient browser credentials, so they remain compatible. Safe reads also
    remain available without an Origin header.
    """

    if request.method.upper() not in _COOKIE_MUTATING_METHODS:
        return
    if not (
        request.cookies.get(settings.auth_session_cookie_name)
        or request.cookies.get(settings.otp_flow_cookie_name)
    ):
        return

    require_trusted_mutation_origin(request)


def require_trusted_mutation_origin(request: Request) -> None:
    """Require exactly one allow-listed Origin for a cookie authority mutation."""

    if request.method.upper() not in _COOKIE_MUTATING_METHODS:
        return

    origin_headers = request.headers.getlist("origin")
    if not origin_headers or not origin_headers[0].strip():
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"code": "csrf_origin_required"},
        )
    if len(origin_headers) != 1:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"code": "csrf_origin_untrusted"},
        )
    origin_header = origin_headers[0]
    supplied = _canonical_http_origin(origin_header)
    trusted = {
        origin
        for configured in settings.cors_origins
        if (origin := _canonical_http_origin(configured)) is not None
    }
    if supplied is None or supplied not in trusted:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"code": "csrf_origin_untrusted"},
        )


def build_actor_context(claims: dict | None) -> ActorContext:
    """Map verified IdP claims (from P0.1/P0.2) into an ActorContext.

    `claims` is the already-verified token payload supplied by the identity
    layer. None → anonymous. This is intentionally pure/testable.
    """
    if not claims:
        return ANONYMOUS
    roles = frozenset(Role(r) for r in claims.get("roles", []) if r in Role._value2member_map_)

    def _uuid(v):
        return uuid.UUID(v) if v else None

    def _vs(v):
        return VerificationStatus(v) if v in VerificationStatus._value2member_map_ else VerificationStatus.DRAFT

    return ActorContext(
        user_id=_uuid(claims.get("sub")),
        roles=roles,
        student_profile_id=_uuid(claims.get("student_profile_id")),
        lawyer_profile_id=_uuid(claims.get("lawyer_profile_id")),
        student_verification=_vs(claims.get("student_verification")),
        lawyer_verification=_vs(claims.get("lawyer_verification")),
        is_minor=bool(claims.get("is_minor", False)),
        consent_state=frozenset(claims.get("consent_state", [])),
    )


# --- FastAPI identity dependency ---------------------------------------------
def get_actor_context(
    request: Request,
    session: Session = Depends(get_session),
    x_actor_claims: str | None = Header(default=None),
) -> ActorContext:
    """Resolve the server-authoritative student cookie, then dev test claims.

    The opaque cookie is hashed and resolved through ``auth_sessions``. The
    legacy ``X-Actor-Claims`` seam remains available only in development/test
    so the existing deterministic domain suites do not become an authentication
    integration test; production/staging can never trust that header.
    """
    from app.services import login_service

    cookie = request.cookies.get(settings.auth_session_cookie_name)
    if cookie:
        claims = login_service.session_claims(
            session,
            cookie,
            datetime.now(timezone.utc),
            touch=False,
        )
        if claims is None:
            return ANONYMOUS
        require_trusted_cookie_origin(request)
        return build_actor_context(claims)

    environment = (settings.app_env or "").strip().lower()
    if environment not in {"development", "dev", "test", "testing"}:
        return ANONYMOUS
    if not x_actor_claims:
        return ANONYMOUS
    import json

    try:
        return build_actor_context(json.loads(x_actor_claims))
    except Exception:
        return ANONYMOUS


def require_authenticated(actor: ActorContext = Depends(get_actor_context)) -> ActorContext:
    if not actor.is_authenticated:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Authentication required")
    return actor


def require_role(role: Role):
    def _dep(actor: ActorContext = Depends(require_authenticated)) -> ActorContext:
        if not actor.has_role(role):
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=f"Requires role: {role.value}")
        return actor

    return _dep


def require_lawyer_features(actor: ActorContext = Depends(require_authenticated)) -> ActorContext:
    """S21 lock: block lawyer capability until P0.1 verification succeeds."""
    if not actor.can_use_lawyer_features:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Lawyer features locked until P0.1 lawyer verification is complete",
        )
    return actor
