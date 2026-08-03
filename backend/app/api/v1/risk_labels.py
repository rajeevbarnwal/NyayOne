"""Disabled-by-default HTTP boundary for SAATHI-279."""
from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from sqlalchemy.orm import Session

from app.core.auth import ActorContext, get_actor_context
from app.db.session import get_session
from app.core.rate_limit import (
    RateLimitExceeded,
    WAVE4_RESPONSE_IP,
    WAVE4_RESPONSE_TOKEN,
    check as check_rate_limit,
)
from app.core.crypto import keyed_hash
from app.schemas.risk_labels import (
    OrganisationResponseDecisionIn,
    OrganisationResponseIn,
    OrganisationResponseOut,
    OrganisationResponseRequestIn,
    OrganisationResponseRequestOut,
    PublicRiskLabelsOut,
    PublishedRiskLabelOut,
    RiskLabelCandidateListOut,
    RiskLabelPublishIn,
)
from app.services.risk_label_service import (
    RiskLabelError,
    create_response_request,
    decide_response,
    list_risk_label_candidates,
    public_labels,
    publish_risk_label as publish_risk_label_service,
    require_publication_gate,
    submit_response,
)

router = APIRouter(tags=["internship-risk-labels"])


def _raise(error: RiskLabelError) -> None:
    detail: dict[str, object] = {
        "code": error.code,
        "message": error.message,
        "retryable": error.retryable,
    }
    if error.current_version is not None:
        detail["current_version"] = error.current_version
    raise HTTPException(status_code=error.status_code, detail=detail)


@router.get("/moderation/risk-labels", response_model=RiskLabelCandidateListOut)
def moderation_risk_labels(
    session: Session = Depends(get_session),
    actor: ActorContext = Depends(get_actor_context),
) -> RiskLabelCandidateListOut:
    try:
        return list_risk_label_candidates(session, actor)
    except RiskLabelError as error:
        _raise(error)


@router.post(
    "/moderation/risk-labels/{cluster_id}/publish",
    response_model=PublishedRiskLabelOut,
)
def publish_risk_label(
    cluster_id: uuid.UUID,
    payload: RiskLabelPublishIn,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    session: Session = Depends(get_session),
    actor: ActorContext = Depends(get_actor_context),
) -> PublishedRiskLabelOut:
    try:
        return publish_risk_label_service(
            session, actor, cluster_id, payload, idempotency_key
        )
    except RiskLabelError as error:
        _raise(error)
    raise AssertionError("unreachable while governance gate is closed")


@router.post(
    "/organisation-response-requests",
    response_model=OrganisationResponseRequestOut,
    status_code=201,
)
def create_organisation_response_request(
    payload: OrganisationResponseRequestIn,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    session: Session = Depends(get_session),
    actor: ActorContext = Depends(get_actor_context),
) -> OrganisationResponseRequestOut:
    try:
        return create_response_request(session, actor, payload, idempotency_key)
    except RiskLabelError as error:
        _raise(error)
    raise AssertionError("unreachable while governance gate is closed")


@router.post(
    "/organisation-responses",
    response_model=OrganisationResponseOut,
    status_code=201,
)
def create_organisation_response(
    payload: OrganisationResponseIn,
    request: Request,
    response_token: str | None = Header(default=None, alias="X-Organisation-Response-Token"),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    session: Session = Depends(get_session),
) -> OrganisationResponseOut:
    try:
        # Fail closed before consuming a rate-limit budget while publication is
        # disabled. Independent token and IP ceilings prevent both cross-token
        # starvation behind a proxy and bypass by rotating arbitrary tokens.
        # The limiter stores only keyed hashes, never these raw identities.
        require_publication_gate()
        client_identity = request.client.host if request.client else "unknown"
        token_identity = keyed_hash(response_token or "missing-response-token")
        check_rate_limit(WAVE4_RESPONSE_IP, client_identity)
        check_rate_limit(WAVE4_RESPONSE_TOKEN, token_identity)
        return submit_response(session, response_token, payload, idempotency_key)
    except RateLimitExceeded as error:
        raise HTTPException(
            status_code=429,
            detail={
                "code": "rate_limit_exceeded",
                "message": "Too many response attempts",
                "retryable": True,
                "retry_after_seconds": error.retry_after,
            },
        ) from error
    except RiskLabelError as error:
        _raise(error)
    raise AssertionError("unreachable while governance gate is closed")


@router.post(
    "/moderation/organisation-responses/{response_id}/decide",
    response_model=OrganisationResponseOut,
)
def decide_organisation_response(
    response_id: uuid.UUID,
    payload: OrganisationResponseDecisionIn,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    session: Session = Depends(get_session),
    actor: ActorContext = Depends(get_actor_context),
) -> OrganisationResponseOut:
    try:
        return decide_response(
            session, actor, response_id, payload, idempotency_key
        )
    except RiskLabelError as error:
        _raise(error)
    raise AssertionError("unreachable while governance gate is closed")


@router.get(
    "/public/internship-risk-labels/{organisation_id}",
    response_model=PublicRiskLabelsOut,
)
def public_internship_risk_labels(
    organisation_id: uuid.UUID,
    session: Session = Depends(get_session),
) -> PublicRiskLabelsOut:
    try:
        return public_labels(session, organisation_id)
    except RiskLabelError as error:
        _raise(error)
    raise AssertionError("unreachable while governance gate is closed")
