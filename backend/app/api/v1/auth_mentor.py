"""Server-authoritative tutor/lawyer mentor ceremony endpoints (NYAY-22)."""

from __future__ import annotations

import re
import ipaddress
import copy
import json
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Annotated, Any
from urllib.parse import urlsplit

from fastapi import APIRouter, Depends, FastAPI, Header, HTTPException, Request, Response, Security
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.routing import APIRoute
from fastapi.security import APIKeyCookie, APIKeyHeader
import fastapi.openapi.utils as fastapi_openapi_utils
from pydantic import Field, TypeAdapter, ValidationError
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.session import get_session
from app.schemas.mentor_ceremony import (
    MentorAcceptanceProjection,
    MentorAuthorityDeletionOutcome,
    MentorAuthorityDeletionRequest,
    MentorAuthorityStepUpProjection,
    MentorCeremonyChallenge,
    MentorCeremonyInitiateRequest,
    MentorExchangeRequest,
    MentorFailure,
    MentorIdentityProofRequest,
    MentorLifecycleOutcome,
    MentorLifecycleRequest,
    MentorLoggedOutOutcome,
    MentorRecoveryRequest,
    MentorRevokedOutcome,
    MentorSessionProjection,
    MentorSessionExchangeRequest,
    MentorAuthorityStepUpExchangeRequest,
    MentorSessionRecoveryRequest,
    MentorAuthorityDeletionStepUpRequest,
)
from app.services import mentor_ceremony


_NO_STORE_HEADERS = {"Cache-Control": "private, no-store", "Vary": "Cookie"}
_IDEMPOTENCY_PATTERN = r"^[A-Za-z0-9._~-]{16,200}$"
_MAX_MENTOR_BODY_BYTES = 16 * 1024

_TRUSTED_ORIGIN_SCHEME = APIKeyHeader(name="Origin", scheme_name="TrustedOrigin", auto_error=False)
_BOOTSTRAP_SCHEME = APIKeyCookie(name="nyayone_mentor_bootstrap", scheme_name="MentorBootstrapCookie", auto_error=False)
_CEREMONY_SCHEME = APIKeyCookie(name="nyayone_mentor_ceremony", scheme_name="MentorCeremonyCookie", auto_error=False)
_SESSION_SCHEME = APIKeyCookie(name="nyayone_mentor_session", scheme_name="MentorSessionCookie", auto_error=False)
_STEP_UP_SCHEME = APIKeyCookie(name="nyayone_mentor_authority_step_up", scheme_name="MentorAuthorityStepUpCookie", auto_error=False)

_SEALED_OPENAPI = json.loads(
    (Path(__file__).resolve().parents[2] / "schemas/nyay22_mentor_contract.openapi.json")
    .read_text(encoding="utf-8")
)

_SEALED_FAILURE_SCHEMAS: dict[str, dict[str, Any]] = {
    "ContractVersion": {
        "type": "string", "pattern": "^[a-z0-9][a-z0-9._-]{0,63}$",
        "minLength": 1, "maxLength": 64,
    },
    "MentorPurposeCode": {
        "type": "string",
        "enum": ["student_guidance", "legal_education", "document_review", "case_discussion"],
        "description": "Server-recognized purpose class. It is not an owner/student selector and cannot expand persisted consent.",
    },
    "MentorDisclosureClass": {
        "type": "string",
        "enum": ["display_identity", "preferred_language", "city", "education_context", "interests", "goals"],
    },
    "MentorAcceptanceProjection": {
        "oneOf": [
            {"$ref": "#/components/schemas/MentorPurposeAcceptanceProjection"},
            {"$ref": "#/components/schemas/MentorDeletionStepUpAcceptanceProjection"},
        ],
        "discriminator": {
            "propertyName": "intent",
            "mapping": {
                "mentor_session": "#/components/schemas/MentorPurposeAcceptanceProjection",
                "authority_deletion_step_up": "#/components/schemas/MentorDeletionStepUpAcceptanceProjection",
            },
        },
    },
    "MentorExchangeRequest": {
        "oneOf": [
            {"$ref": "#/components/schemas/MentorSessionExchangeRequest"},
            {"$ref": "#/components/schemas/MentorAuthorityStepUpExchangeRequest"},
        ],
        "discriminator": {
            "propertyName": "intent",
            "mapping": {
                "mentor_session": "#/components/schemas/MentorSessionExchangeRequest",
                "authority_deletion_step_up": "#/components/schemas/MentorAuthorityStepUpExchangeRequest",
            },
        },
    },
    "MentorRecoveryRequest": {
        "oneOf": [
            {"$ref": "#/components/schemas/MentorSessionRecoveryRequest"},
            {"$ref": "#/components/schemas/MentorAuthorityDeletionStepUpRequest"},
        ],
        "discriminator": {
            "propertyName": "intent",
            "mapping": {
                "mentor_session": "#/components/schemas/MentorSessionRecoveryRequest",
                "authority_deletion_step_up": "#/components/schemas/MentorAuthorityDeletionStepUpRequest",
            },
        },
    },
    "MentorLifecycleOutcome": {
        "oneOf": [
            {"$ref": "#/components/schemas/MentorRevokedOutcome"},
            {"$ref": "#/components/schemas/MentorLoggedOutOutcome"},
            {"$ref": "#/components/schemas/MentorAuthorityDeletionOutcome"},
        ],
        "discriminator": {
            "propertyName": "action",
            "mapping": {
                "revoked": "#/components/schemas/MentorRevokedOutcome",
                "logged_out": "#/components/schemas/MentorLoggedOutOutcome",
                "authority_deletion_scheduled": "#/components/schemas/MentorAuthorityDeletionOutcome",
            },
        },
    },
    "MentorBadRequestFailure": {
        "allOf": [
            {"$ref": "#/components/schemas/MentorFailure"},
            {"type": "object", "required": ["detail"], "properties": {"detail": {"type": "object", "required": ["code"], "properties": {"code": {"enum": ["INVALID_REQUEST", "INVALID_IDEMPOTENCY_KEY", "ORIGIN_REJECTED"]}}}}},
        ]
    },
    "MentorAuthenticationFailure": {"allOf": [{"$ref": "#/components/schemas/MentorFailure"}, {"type": "object", "properties": {"detail": {"type": "object", "properties": {"code": {"enum": ["AUTHENTICATION_REQUIRED"]}}}}}]},
    "MentorForbiddenFailure": {"allOf": [{"$ref": "#/components/schemas/MentorFailure"}, {"type": "object", "properties": {"detail": {"type": "object", "properties": {"code": {"enum": ["AUTHORIZATION_DENIED", "STEP_UP_REQUIRED"]}}}}}]},
    "MentorNotFoundFailure": {"allOf": [{"$ref": "#/components/schemas/MentorFailure"}, {"type": "object", "properties": {"detail": {"type": "object", "properties": {"code": {"const": "RESOURCE_UNAVAILABLE"}}}}}]},
    "MentorConflictFailure": {"allOf": [{"$ref": "#/components/schemas/MentorFailure"}, {"type": "object", "properties": {"detail": {"type": "object", "properties": {"code": {"enum": ["IDEMPOTENCY_CONFLICT", "CONCURRENT_STATE_CHANGED", "CEREMONY_REPLAYED", "SESSION_CONFLICT", "SESSION_STALE"]}}}}}]},
    "MentorCeremonyGoneFailure": {"allOf": [{"$ref": "#/components/schemas/MentorFailure"}, {"type": "object", "properties": {"detail": {"type": "object", "properties": {"code": {"const": "AUTHORITY_TERMINAL"}}}}}]},
    "MentorSessionGoneFailure": {"allOf": [{"$ref": "#/components/schemas/MentorFailure"}, {"type": "object", "properties": {"detail": {"type": "object", "properties": {"code": {"enum": ["SESSION_EXPIRED", "AUTHORITY_TERMINAL"]}}}}}]},
    "MentorAuthorityGoneFailure": {"allOf": [{"$ref": "#/components/schemas/MentorFailure"}, {"type": "object", "properties": {"detail": {"type": "object", "properties": {"code": {"enum": ["SESSION_EXPIRED", "STEP_UP_EXPIRED", "AUTHORITY_TERMINAL"]}}}}}]},
    "MentorRateLimitFailure": {"allOf": [{"$ref": "#/components/schemas/MentorFailure"}, {"type": "object", "properties": {"detail": {"type": "object", "properties": {"code": {"const": "RATE_LIMITED"}}}}}]},
    "MentorProviderUnavailableFailure": {"allOf": [{"$ref": "#/components/schemas/MentorFailure"}, {"type": "object", "properties": {"detail": {"type": "object", "properties": {"code": {"const": "PROVIDER_UNAVAILABLE"}}}}}]},
}

_SEALED_RESPONSE_COMPONENTS: dict[str, dict[str, Any]] = {
    "BadRequest": {"description": "Malformed, over-broad, non-canonical, duplicate-header, or invalid idempotency request. No authoritative state changes.", "content": {"application/json": {"schema": {"$ref": "#/components/schemas/MentorBadRequestFailure"}}}},
    "AuthenticationRequired": {"description": "The required server-owned binding is absent or invalid. No existence fact is disclosed.", "content": {"application/json": {"schema": {"$ref": "#/components/schemas/MentorAuthenticationFailure"}}}},
    "Forbidden": {"description": "Generic authorization or consent/policy denial.", "content": {"application/json": {"schema": {"$ref": "#/components/schemas/MentorForbiddenFailure"}}}},
    "NotFound": {"description": "Non-enumerating unavailable result.", "content": {"application/json": {"schema": {"$ref": "#/components/schemas/MentorNotFoundFailure"}}}},
    "Conflict": {"description": "Replay, concurrency, stale generation, or incompatible authority conflict.", "content": {"application/json": {"schema": {"$ref": "#/components/schemas/MentorConflictFailure"}}}},
    "CeremonyGone": {"description": "The ceremony authority is terminal.", "content": {"application/json": {"schema": {"$ref": "#/components/schemas/MentorCeremonyGoneFailure"}}}},
    "SessionGone": {"description": "The mentor session authority is terminal.", "content": {"application/json": {"schema": {"$ref": "#/components/schemas/MentorSessionGoneFailure"}}}},
    "AuthorityGone": {"description": "The mentor authority or step-up is terminal.", "content": {"application/json": {"schema": {"$ref": "#/components/schemas/MentorAuthorityGoneFailure"}}}},
    "TooManyRequests": {"description": "A bounded server-side rate budget is exhausted.", "content": {"application/json": {"schema": {"$ref": "#/components/schemas/MentorRateLimitFailure"}}}},
    "ProviderUnavailable": {"description": "The identity-provider backchannel is unavailable within its deadline.", "content": {"application/json": {"schema": {"$ref": "#/components/schemas/MentorProviderUnavailableFailure"}}}},
}

_STATUS_COMPONENT = {
    "400": "BadRequest", "401": "AuthenticationRequired", "403": "Forbidden",
    "404": "NotFound", "409": "Conflict", "429": "TooManyRequests",
    "503": "ProviderUnavailable",
}


def _document_security_schemes(
    _origin: str | None = Security(_TRUSTED_ORIGIN_SCHEME),
    _bootstrap: str | None = Security(_BOOTSTRAP_SCHEME),
    _ceremony: str | None = Security(_CEREMONY_SCHEME),
    _session: str | None = Security(_SESSION_SCHEME),
    _step_up: str | None = Security(_STEP_UP_SCHEME),
) -> None:
    """Register contract schemes; runtime authority remains service-owned."""


def _install_mentor_openapi_normalizer() -> None:
    """Remove FastAPI's unreachable auto-422 from mentor operations only.

    ``MentorContractRoute`` maps every validation failure to the sealed 400
    envelope.  Advertising FastAPI's default 422 would therefore be both
    unreachable and a contract drift.  The wrapper is idempotent and leaves
    every non-mentor route untouched.
    """

    current = fastapi_openapi_utils.get_openapi_path
    if getattr(current, "_nyay22_exact_responses", False):
        return

    def exact_path(*args: Any, **kwargs: Any):
        rendered = current(*args, **kwargs)
        route = kwargs.get("route") or (args[0] if args else None)
        if rendered and str(getattr(route, "path", "")).startswith("/api/v1/auth/mentor/"):
            path_item = rendered[0]
            for operation in path_item.values():
                if isinstance(operation, dict):
                    responses = operation.get("responses")
                    if isinstance(responses, dict):
                        responses.pop("422", None)
                        for status, response in tuple(responses.items()):
                            if status in _STATUS_COMPONENT:
                                responses[status] = {
                                    "$ref": (
                                        "#/components/responses/"
                                        f"{_STATUS_COMPONENT[status]}"
                                    )
                                }
                            elif status == "410":
                                route_path = str(getattr(route, "path", ""))
                                if route_path.endswith("/authority"):
                                    component = "AuthorityGone"
                                elif "/session" in route_path:
                                    component = "SessionGone"
                                else:
                                    component = "CeremonyGone"
                                responses[status] = {
                                    "$ref": f"#/components/responses/{component}"
                                }
                    declared_security = getattr(route, "openapi_extra", {}).get(
                        "security"
                    )
                    if declared_security is not None:
                        # Router dependencies exist only to register component
                        # definitions.  They are not independent authorization
                        # alternatives; the sealed operation combinations win.
                        operation["security"] = declared_security
        return rendered

    exact_path._nyay22_exact_responses = True  # type: ignore[attr-defined]
    fastapi_openapi_utils.get_openapi_path = exact_path


_install_mentor_openapi_normalizer()


def _install_mentor_component_normalizer() -> None:
    """Publish the sealed typed mentor response registry in generated OpenAPI.

    FastAPI security dependencies register the five concrete schemes.  This
    wrapper adds only the design-sealed aliases and reusable response objects;
    it never broadens runtime authorization or any non-mentor operation.
    """

    current = FastAPI.openapi
    if getattr(current, "_nyay22_exact_components", False):
        return

    def exact_openapi(app: FastAPI) -> dict[str, Any]:
        schema = current(app)
        paths = schema.get("paths", {})
        if not any(
            str(path).startswith("/api/v1/auth/mentor/") for path in paths
        ):
            return schema
        # The NYAY-29/33 document is copied byte-for-byte into the runtime
        # package and contract-tested against its design source.  Replacing
        # only this namespace prevents FastAPI defaults (notably implicit 422
        # responses or dependency-generated OR alternatives) from weakening
        # the strict public wire contract while leaving every other API alone.
        for path, sealed_path in _SEALED_OPENAPI["paths"].items():
            if path in paths:
                paths[path] = copy.deepcopy(sealed_path)
        components = schema.setdefault("components", {})
        sealed_components = _SEALED_OPENAPI["components"]
        for section in ("securitySchemes", "parameters", "headers", "responses"):
            target = components.setdefault(section, {})
            target.update(copy.deepcopy(sealed_components[section]))
        schemas = components.setdefault("schemas", {})
        schemas.update(copy.deepcopy(sealed_components["schemas"]))
        return schema

    exact_openapi._nyay22_exact_components = True  # type: ignore[attr-defined]
    FastAPI.openapi = exact_openapi


_install_mentor_component_normalizer()

OriginHeader = Annotated[str, Header(alias="Origin", min_length=1, max_length=255)]
IdempotencyHeader = Annotated[
    str,
    Header(
        alias="Idempotency-Key",
        min_length=16,
        max_length=200,
        pattern=_IDEMPOTENCY_PATTERN,
    ),
]

_BODY_ADAPTERS: tuple[tuple[str, str, TypeAdapter[Any]], ...] = (
    ("POST", "/ceremony/initiate", TypeAdapter(MentorCeremonyInitiateRequest)),
    ("POST", "/ceremony/verify", TypeAdapter(MentorIdentityProofRequest)),
    (
        "POST",
        "/ceremony/exchange",
        TypeAdapter(
            Annotated[
                MentorSessionExchangeRequest | MentorAuthorityStepUpExchangeRequest,
                Field(discriminator="intent"),
            ]
        ),
    ),
    ("POST", "/session/rotate", TypeAdapter(MentorLifecycleRequest)),
    ("POST", "/session/revoke", TypeAdapter(MentorLifecycleRequest)),
    ("POST", "/session/logout", TypeAdapter(MentorLifecycleRequest)),
    (
        "POST",
        "/ceremony/recover",
        TypeAdapter(
            Annotated[
                MentorSessionRecoveryRequest | MentorAuthorityDeletionStepUpRequest,
                Field(discriminator="intent"),
            ]
        ),
    ),
    ("DELETE", "/authority", TypeAdapter(MentorAuthorityDeletionRequest)),
)


def _failure_response(
    *,
    status_code: int,
    code: str,
    retryable: bool = False,
    field: str | None = None,
    retry_after_seconds: int | None = None,
) -> JSONResponse:
    """Create the one non-enumerating, PII-safe public failure envelope."""

    detail: dict[str, object] = {
        "code": code,
        "message": "Request failed",
        "retryable": retryable,
    }
    if field in {"Idempotency-Key", "Origin", "request"}:
        detail["field"] = field
    if retry_after_seconds is not None:
        detail["retryAfterSeconds"] = retry_after_seconds
    return JSONResponse(
        status_code=status_code,
        content={"detail": detail},
        headers=_NO_STORE_HEADERS,
    )


def _mentor_origin_is_trusted(raw_origin: str) -> bool:
    """Apply the ceremony's HTTPS-only / numeric-loopback-only origin policy."""

    try:
        parsed = urlsplit(raw_origin)
        hostname = parsed.hostname
        port = parsed.port
    except (TypeError, ValueError):
        return False
    if (
        not hostname
        or parsed.scheme not in {"http", "https"}
        or parsed.username is not None
        or parsed.password is not None
        or parsed.path
        or parsed.query
        or parsed.fragment
    ):
        return False
    default_port = 80 if parsed.scheme == "http" else 443
    # ``urlsplit().hostname`` deliberately removes IPv6 brackets.  Put them
    # back when constructing the canonical origin; an unbracketed
    # ``http://::1:port`` string is not a URL and can never equal the exact
    # configured numeric-loopback development origin.
    try:
        parsed_address = ipaddress.ip_address(hostname)
    except ValueError:
        canonical_host = hostname
    else:
        canonical_host = (
            f"[{parsed_address.compressed}]"
            if parsed_address.version == 6
            else parsed_address.compressed
        )
    authority = (
        canonical_host
        if port in {None, default_port}
        else f"{canonical_host}:{port}"
    )
    canonical = f"{parsed.scheme}://{authority}"
    # ``urlsplit`` discards empty query/fragment delimiters.  Exact raw
    # reconstruction keeps ``https://host?`` and similar non-canonical
    # spellings outside the trusted-origin set.
    if raw_origin != canonical:
        return False
    configured = set(settings.cors_origins)
    environment = (settings.app_env or "").strip().casefold()
    if environment in {"production", "prod", "staging", "stage"}:
        return parsed.scheme == "https" and canonical in configured
    if parsed.scheme == "http":
        try:
            address = ipaddress.ip_address(hostname)
        except ValueError:
            return False
        if not address.is_loopback:
            return False
    return canonical in configured


def require_mentor_trusted_origin(request: Request) -> None:
    values = request.headers.getlist("origin")
    if len(values) != 1 or not _mentor_origin_is_trusted(values[0]):
        raise HTTPException(
            status_code=400,
            detail={"code": "ORIGIN_REJECTED"},
            headers=_NO_STORE_HEADERS,
        )


class MentorContractRoute(APIRoute):
    """Map request parsing failures to the sealed typed HTTP 400 contract.

    FastAPI's generic 422 payload contains field-level validation details.  At
    this boundary those details can reveal a client-supplied identifier.  The
    route wrapper deliberately emits only a stable code and bounded field
    class, even when the application is mounted without global handlers.
    """

    def get_route_handler(self) -> Callable[[Request], Awaitable[Response]]:
        original = super().get_route_handler()

        async def bounded_body(request: Request) -> bytes | None:
            """Read at most the sealed mentor request-body ceiling.

            The cumulative stream bound is authoritative; Content-Length is
            only an early rejection hint because a peer may omit or lie about
            it.  The buffered bytes are restored on the Request for FastAPI's
            normal parser after the independent contract check.
            """

            lengths = request.headers.getlist("content-length")
            if len(lengths) > 1:
                return None
            if lengths:
                try:
                    declared = int(lengths[0], 10)
                except (TypeError, ValueError):
                    return None
                if declared < 0 or declared > _MAX_MENTOR_BODY_BYTES:
                    return None
            received = 0
            chunks: list[bytes] = []
            try:
                async for chunk in request.stream():
                    received += len(chunk)
                    if received > _MAX_MENTOR_BODY_BYTES:
                        return None
                    chunks.append(chunk)
            except Exception:
                return None
            body = b"".join(chunks)
            request._body = body  # Starlette's documented body-cache shape.
            return body

        async def canonical_handler(request: Request) -> Response:
            if request.query_params:
                return _failure_response(
                    status_code=400,
                    code="INVALID_REQUEST",
                    field="request",
                )
            if request.method.upper() != "GET":
                origin_values = request.headers.getlist("origin")
                if len(origin_values) != 1 or not origin_values[0].strip():
                    return _failure_response(
                        status_code=400,
                        code="ORIGIN_REJECTED",
                        field="Origin",
                    )
                try:
                    require_mentor_trusted_origin(request)
                except HTTPException:
                    return _failure_response(
                        status_code=400,
                        code="ORIGIN_REJECTED",
                        field="Origin",
                    )

                idempotency_values = request.headers.getlist("idempotency-key")
                if (
                    len(idempotency_values) != 1
                    or re.fullmatch(_IDEMPOTENCY_PATTERN, idempotency_values[0]) is None
                ):
                    return _failure_response(
                        status_code=400,
                        code="INVALID_IDEMPOTENCY_KEY",
                        field="Idempotency-Key",
                    )

                adapter = next(
                    (
                        candidate
                        for method, suffix, candidate in _BODY_ADAPTERS
                        if method == request.method.upper()
                        and request.url.path.endswith(f"/auth/mentor{suffix}")
                    ),
                    None,
                )
                if adapter is not None:
                    raw_body = await bounded_body(request)
                    if raw_body is None:
                        return _failure_response(
                            status_code=400,
                            code="INVALID_REQUEST",
                            field="request",
                        )
                    try:
                        adapter.validate_python(json.loads(raw_body))
                    except (ValidationError, ValueError):
                        return _failure_response(
                            status_code=400,
                            code="INVALID_REQUEST",
                            field="request",
                        )

            try:
                return await original(request)
            except RequestValidationError as exc:
                locations = [tuple(error.get("loc", ())) for error in exc.errors()]
                if any("idempotency-key" in location for location in locations):
                    return _failure_response(
                        status_code=400,
                        code="INVALID_IDEMPOTENCY_KEY",
                        field="Idempotency-Key",
                    )
                if any("origin" in location for location in locations):
                    return _failure_response(
                        status_code=400,
                        code="ORIGIN_REJECTED",
                        field="Origin",
                    )
                return _failure_response(
                    status_code=400,
                    code="INVALID_REQUEST",
                    field="request",
                )
            except HTTPException as exc:
                detail = exc.detail if isinstance(exc.detail, dict) else {}
                if str(detail.get("code", "")).startswith("csrf_origin_"):
                    return _failure_response(
                        status_code=400,
                        code="ORIGIN_REJECTED",
                        field="Origin",
                    )
                allowed_codes = set(
                    _SEALED_OPENAPI["components"]["schemas"]["MentorFailure"]
                    ["properties"]["detail"]["properties"]["code"]["enum"]
                )
                code = detail.get("code")
                if not isinstance(code, str) or code not in allowed_codes:
                    return _failure_response(
                        status_code=409,
                        code="CONCURRENT_STATE_CHANGED",
                        retryable=True,
                    )
                field = detail.get("field")
                retry_after = detail.get("retryAfterSeconds")
                failure = _failure_response(
                    status_code=exc.status_code,
                    code=code,
                    retryable=detail.get("retryable") is True,
                    field=(field if isinstance(field, str) else None),
                    retry_after_seconds=(
                        retry_after if type(retry_after) is int else None
                    ),
                )
                set_cookie = (exc.headers or {}).get("Set-Cookie")
                if set_cookie:
                    failure.headers.append("Set-Cookie", set_cookie)
                return failure
            except Exception:
                # The request-session dependency rolls back every uncommitted
                # write in its generator finalizer.  Never let a driver,
                # deadlock, crypto, or response-validation exception escape
                # into an unsealed framework 500 body/header shape.
                return _failure_response(
                    status_code=409,
                    code="CONCURRENT_STATE_CHANGED",
                    retryable=True,
                )

        return canonical_handler


router = APIRouter(
    prefix="/auth/mentor",
    tags=["Mentor ceremony"],
    route_class=MentorContractRoute,
    dependencies=[Depends(_document_security_schemes)],
)


@router.get("/entry", include_in_schema=False)
def mentor_public_entry(
    request: Request,
    response: Response,
    db: Session = Depends(get_session),
) -> dict[str, object]:
    """Issue only the non-authorizing bootstrap binding for the public shell."""

    try:
        return mentor_ceremony.issue_bootstrap(
            db=db,
            request=request,
            response=response,
        )
    except mentor_ceremony.MentorCeremonyError as exc:
        raise _recorded_service_failure(
            db=db, request=request, operation="entry", exc=exc
        ) from exc


def _service_failure(exc: mentor_ceremony.MentorCeremonyError) -> HTTPException:
    detail: dict[str, object] = {
        "code": exc.code,
        "message": "Request failed",
        "retryable": exc.retryable,
    }
    if exc.field in {"Idempotency-Key", "Origin", "request"}:
        detail["field"] = exc.field
    if exc.retry_after_seconds is not None:
        detail["retryAfterSeconds"] = exc.retry_after_seconds
    headers = dict(_NO_STORE_HEADERS)
    if exc.clear_cookie is not None:
        key, path, same_site = exc.clear_cookie
        clearing = Response()
        mentor_ceremony._clear_cookie(
            clearing,
            key=key,
            path=path,
            same_site=same_site,
        )
        headers["Set-Cookie"] = clearing.headers["set-cookie"]
    return HTTPException(
        status_code=exc.status_code,
        detail=detail,
        headers=headers,
    )


def _recorded_service_failure(
    *,
    db: Session,
    request: Request,
    operation: str,
    exc: mentor_ceremony.MentorCeremonyError,
) -> HTTPException:
    """Discard partial state, durably budget the denial, and map it safely."""

    # The sealed exchange/recovery contracts expose one terminal 410 code.
    # Keep internal session/step-up expiry distinctions inside the service,
    # but never emit a response shape outside those operation contracts.
    if operation in {"exchange", "recover"} and exc.status_code == 410:
        exc = mentor_ceremony.MentorCeremonyError(
            410,
            "AUTHORITY_TERMINAL",
            clear_cookie=exc.clear_cookie,
        )

    bounded = mentor_ceremony.persist_denied_attempt(
        db,
        request=request,
        operation=operation,
        failure=exc,
    )
    return _service_failure(bounded)


def _error_responses(*statuses: int) -> dict[int, dict[str, Any]]:
    return {
        status: {
            "model": MentorFailure,
            "description": "Typed non-enumerating mentor-authority failure.",
        }
        for status in statuses
    }


_CEREMONY_SECURITY = [
    {"TrustedOrigin": [], "MentorBootstrapCookie": []},
    {"TrustedOrigin": [], "MentorCeremonyCookie": []},
]
_VERIFY_SECURITY = [
    {"TrustedOrigin": [], "MentorCeremonyCookie": []},
    {
        "TrustedOrigin": [],
        "MentorCeremonyCookie": [],
        "MentorSessionCookie": [],
    },
]
_RECOVERY_SECURITY = [
    {"TrustedOrigin": [], "MentorBootstrapCookie": []},
    {"TrustedOrigin": [], "MentorCeremonyCookie": []},
    {
        "TrustedOrigin": [],
        "MentorCeremonyCookie": [],
        "MentorSessionCookie": [],
    },
    {
        "TrustedOrigin": [],
        "MentorBootstrapCookie": [],
        "MentorSessionCookie": [],
    },
]
_EXCHANGE_SECURITY = [
    {"TrustedOrigin": [], "MentorCeremonyCookie": []},
    {"TrustedOrigin": [], "MentorSessionCookie": []},
    {
        "TrustedOrigin": [],
        "MentorCeremonyCookie": [],
        "MentorSessionCookie": [],
    },
    {
        "TrustedOrigin": [],
        "MentorSessionCookie": [],
        "MentorAuthorityStepUpCookie": [],
    },
]
_SESSION_SECURITY = [{"MentorSessionCookie": []}]
_SESSION_MUTATION_SECURITY = [{"TrustedOrigin": [], "MentorSessionCookie": []}]
_AUTHORITY_DELETE_SECURITY = [
    {
        "TrustedOrigin": [],
        "MentorSessionCookie": [],
        "MentorAuthorityStepUpCookie": [],
    }
]


@router.post(
    "/ceremony/initiate",
    operation_id="initiateTutorCeremony",
    status_code=202,
    response_model=MentorCeremonyChallenge,
    responses=_error_responses(400, 401, 403, 404, 409, 410, 429, 503),
    openapi_extra={"security": _CEREMONY_SECURITY},
)
def initiate_mentor_ceremony(
    body: MentorCeremonyInitiateRequest,
    request: Request,
    response: Response,
    origin: OriginHeader,
    idempotency_key: IdempotencyHeader,
    db: Session = Depends(get_session),
    _: None = Depends(require_mentor_trusted_origin),
) -> MentorCeremonyChallenge:
    del origin
    try:
        return mentor_ceremony.initiate(
            db=db,
            request=request,
            response=response,
            idempotency_key=idempotency_key,
            body=body,
        )
    except mentor_ceremony.MentorCeremonyError as exc:
        raise _recorded_service_failure(
            db=db, request=request, operation="initiate", exc=exc
        ) from exc


@router.post(
    "/ceremony/verify",
    operation_id="verifyTutorIdentity",
    response_model=MentorAcceptanceProjection,
    responses=_error_responses(400, 401, 403, 404, 409, 410, 429, 503),
    openapi_extra={"security": _VERIFY_SECURITY},
)
def verify_mentor_identity(
    body: MentorIdentityProofRequest,
    request: Request,
    response: Response,
    origin: OriginHeader,
    idempotency_key: IdempotencyHeader,
    db: Session = Depends(get_session),
    _: None = Depends(require_mentor_trusted_origin),
) -> MentorAcceptanceProjection:
    del origin
    try:
        return mentor_ceremony.verify(
            db=db,
            request=request,
            response=response,
            idempotency_key=idempotency_key,
            body=body,
        )
    except mentor_ceremony.MentorCeremonyError as exc:
        raise _recorded_service_failure(
            db=db, request=request, operation="verify", exc=exc
        ) from exc


@router.post(
    "/ceremony/exchange",
    operation_id="exchangeTutorCeremony",
    status_code=201,
    response_model=MentorSessionProjection,
    responses={
        200: {
            "model": MentorAuthorityStepUpProjection,
            "description": "Single-use mentor-authority deletion step-up issued.",
        },
        **_error_responses(400, 401, 403, 404, 409, 410, 429, 503),
    },
    openapi_extra={"security": _EXCHANGE_SECURITY},
)
def exchange_mentor_ceremony(
    body: MentorExchangeRequest,
    request: Request,
    response: Response,
    origin: OriginHeader,
    idempotency_key: IdempotencyHeader,
    db: Session = Depends(get_session),
    _: None = Depends(require_mentor_trusted_origin),
) -> MentorSessionProjection | MentorAuthorityStepUpProjection:
    del origin
    try:
        result = mentor_ceremony.exchange(
            db=db,
            request=request,
            response=response,
            idempotency_key=idempotency_key,
            body=body,
        )
        if result.get("schemaVersion") == "mentor-authority-step-up.v1":
            validated = MentorAuthorityStepUpProjection.model_validate(result)
            rendered = JSONResponse(
                status_code=200,
                content=validated.model_dump(mode="json", by_alias=True),
            )
            for key, value in response.headers.items():
                if key.lower() != "set-cookie":
                    rendered.headers[key] = value
            # A dict conversion collapses multiple Set-Cookie lines and can
            # silently drop the successor step-up on an exact replay.  Preserve
            # every cookie transition byte-for-byte.
            rendered.raw_headers.extend(
                (key, value)
                for key, value in response.raw_headers
                if key.lower() == b"set-cookie"
            )
            return rendered
        return result
    except mentor_ceremony.MentorCeremonyError as exc:
        raise _recorded_service_failure(
            db=db, request=request, operation="exchange", exc=exc
        ) from exc


@router.get(
    "/session",
    operation_id="getTutorSession",
    response_model=MentorSessionProjection,
    responses=_error_responses(400, 401, 403, 404, 409, 410, 429),
    openapi_extra={"security": _SESSION_SECURITY},
)
def get_mentor_session(
    request: Request,
    response: Response,
    db: Session = Depends(get_session),
) -> MentorSessionProjection:
    try:
        return mentor_ceremony.read_session(db=db, request=request, response=response)
    except mentor_ceremony.MentorCeremonyError as exc:
        raise _recorded_service_failure(
            db=db, request=request, operation="read-session", exc=exc
        ) from exc


def _run_session_mutation(
    operation: Callable[..., MentorSessionProjection | MentorLifecycleOutcome],
    *,
    db: Session,
    request: Request,
    response: Response,
    idempotency_key: str,
    body: MentorLifecycleRequest,
) -> MentorSessionProjection | MentorLifecycleOutcome:
    try:
        return operation(
            db=db,
            request=request,
            response=response,
            idempotency_key=idempotency_key,
            body=body,
        )
    except mentor_ceremony.MentorCeremonyError as exc:
        raise _recorded_service_failure(
            db=db,
            request=request,
            operation=getattr(operation, "__name__", "session-mutation"),
            exc=exc,
        ) from exc


@router.post(
    "/session/rotate",
    operation_id="rotateTutorSession",
    response_model=MentorSessionProjection,
    responses=_error_responses(400, 401, 403, 404, 409, 410, 429),
    openapi_extra={"security": _SESSION_MUTATION_SECURITY},
)
def rotate_mentor_session(
    body: MentorLifecycleRequest,
    request: Request,
    response: Response,
    origin: OriginHeader,
    idempotency_key: IdempotencyHeader,
    db: Session = Depends(get_session),
    _: None = Depends(require_mentor_trusted_origin),
) -> MentorSessionProjection:
    del origin
    return _run_session_mutation(
        mentor_ceremony.rotate,
        db=db,
        request=request,
        response=response,
        idempotency_key=idempotency_key,
        body=body,
    )


@router.post(
    "/session/revoke",
    operation_id="revokeTutorSession",
    response_model=MentorRevokedOutcome,
    responses=_error_responses(400, 401, 403, 404, 409, 410, 429),
    openapi_extra={"security": _SESSION_MUTATION_SECURITY},
)
def revoke_mentor_session(
    body: MentorLifecycleRequest,
    request: Request,
    response: Response,
    origin: OriginHeader,
    idempotency_key: IdempotencyHeader,
    db: Session = Depends(get_session),
    _: None = Depends(require_mentor_trusted_origin),
) -> MentorRevokedOutcome:
    del origin
    return _run_session_mutation(
        mentor_ceremony.revoke,
        db=db,
        request=request,
        response=response,
        idempotency_key=idempotency_key,
        body=body,
    )


@router.post(
    "/session/logout",
    operation_id="logoutTutorSession",
    response_model=MentorLoggedOutOutcome,
    responses=_error_responses(400, 401, 403, 404, 409, 410, 429),
    openapi_extra={"security": _SESSION_MUTATION_SECURITY},
)
def logout_mentor_session(
    body: MentorLifecycleRequest,
    request: Request,
    response: Response,
    origin: OriginHeader,
    idempotency_key: IdempotencyHeader,
    db: Session = Depends(get_session),
    _: None = Depends(require_mentor_trusted_origin),
) -> MentorLoggedOutOutcome:
    del origin
    return _run_session_mutation(
        mentor_ceremony.logout,
        db=db,
        request=request,
        response=response,
        idempotency_key=idempotency_key,
        body=body,
    )


@router.post(
    "/ceremony/recover",
    operation_id="recoverTutorCeremony",
    status_code=202,
    response_model=MentorCeremonyChallenge,
    responses=_error_responses(400, 401, 403, 404, 409, 410, 429, 503),
    openapi_extra={"security": _RECOVERY_SECURITY},
)
def recover_mentor_ceremony(
    body: MentorRecoveryRequest,
    request: Request,
    response: Response,
    origin: OriginHeader,
    idempotency_key: IdempotencyHeader,
    db: Session = Depends(get_session),
    _: None = Depends(require_mentor_trusted_origin),
) -> MentorCeremonyChallenge:
    del origin
    try:
        return mentor_ceremony.recover(
            db=db,
            request=request,
            response=response,
            idempotency_key=idempotency_key,
            body=body,
        )
    except mentor_ceremony.MentorCeremonyError as exc:
        raise _recorded_service_failure(
            db=db, request=request, operation="recover", exc=exc
        ) from exc


@router.delete(
    "/authority",
    operation_id="deleteTutorAuthority",
    status_code=202,
    response_model=MentorAuthorityDeletionOutcome,
    responses=_error_responses(400, 401, 403, 404, 409, 410, 429),
    openapi_extra={"security": _AUTHORITY_DELETE_SECURITY},
)
def delete_mentor_authority(
    body: MentorAuthorityDeletionRequest,
    request: Request,
    response: Response,
    origin: OriginHeader,
    idempotency_key: IdempotencyHeader,
    db: Session = Depends(get_session),
    _: None = Depends(require_mentor_trusted_origin),
) -> MentorAuthorityDeletionOutcome:
    del origin
    try:
        return mentor_ceremony.delete_authority(
            db=db,
            request=request,
            response=response,
            idempotency_key=idempotency_key,
            body=body,
        )
    except mentor_ceremony.MentorCeremonyError as exc:
        raise _recorded_service_failure(
            db=db, request=request, operation="delete-authority", exc=exc
        ) from exc
