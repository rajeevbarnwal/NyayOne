"""Internal moderator-only HTTP boundary for SAATHI-274."""
from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Response
from sqlalchemy.orm import Session

from app.api.openapi_headers import required_idempotency_header
from app.core.auth import ActorContext, get_actor_context
from app.db.session import get_session
from app.schemas.moderation import (
    ModerationActionIn,
    ModerationActionOut,
    ModerationCaseOut,
    ModerationQueueOut,
    IdentityAccessApprovalIn,
    IdentityAccessExecutionOut,
    IdentityAccessRequestIn,
    IdentityAccessRequestOut,
    RiskClusterCreate,
    RiskClusterOut,
    RiskSignalApprovalIn,
)
from app.services.moderation_service import (
    ModerationError,
    act_on_case,
    approve_cluster,
    create_cluster,
    get_case,
    get_cluster,
    list_cases,
    request_identity_access,
    decide_identity_access,
    execute_identity_access,
)

router = APIRouter(prefix="/moderation", tags=["internship-report-moderation"])


def _raise(error: ModerationError) -> None:
    detail: dict[str, object] = {"code": error.code, "message": error.message}
    if error.field:
        detail["field"] = error.field
    if error.current_version is not None:
        detail["current_version"] = error.current_version
    raise HTTPException(status_code=error.status_code, detail=detail)


@router.get("/internship-reports", response_model=ModerationQueueOut)
def moderation_queue(
    state: str | None = Query(default=None),
    session: Session = Depends(get_session),
    actor: ActorContext = Depends(get_actor_context),
) -> ModerationQueueOut:
    try:
        return list_cases(session, actor, state)
    except ModerationError as error:
        _raise(error)


@router.get("/internship-reports/{report_id}", response_model=ModerationCaseOut)
def moderation_case(
    report_id: uuid.UUID,
    session: Session = Depends(get_session),
    actor: ActorContext = Depends(get_actor_context),
) -> ModerationCaseOut:
    try:
        return get_case(session, actor, report_id)
    except ModerationError as error:
        _raise(error)


@router.post("/internship-reports/{report_id}/actions", response_model=ModerationActionOut, openapi_extra=required_idempotency_header())
def moderation_action(
    report_id: uuid.UUID,
    payload: ModerationActionIn,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key", include_in_schema=False),
    session: Session = Depends(get_session),
    actor: ActorContext = Depends(get_actor_context),
) -> ModerationActionOut:
    try:
        return act_on_case(session, actor, report_id, payload, idempotency_key)
    except ModerationError as error:
        _raise(error)


@router.post("/risk-clusters", response_model=RiskClusterOut, status_code=201, openapi_extra=required_idempotency_header())
def risk_cluster_create(
    payload: RiskClusterCreate,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key", include_in_schema=False),
    session: Session = Depends(get_session),
    actor: ActorContext = Depends(get_actor_context),
) -> RiskClusterOut:
    try:
        return create_cluster(session, actor, payload, idempotency_key)
    except ModerationError as error:
        _raise(error)


@router.get("/risk-clusters/{cluster_id}", response_model=RiskClusterOut)
def risk_cluster_get(
    cluster_id: uuid.UUID,
    session: Session = Depends(get_session),
    actor: ActorContext = Depends(get_actor_context),
) -> RiskClusterOut:
    try:
        return get_cluster(session, actor, cluster_id)
    except ModerationError as error:
        _raise(error)


@router.post("/risk-clusters/{cluster_id}/approvals", response_model=RiskClusterOut)
def risk_cluster_approval(
    cluster_id: uuid.UUID,
    payload: RiskSignalApprovalIn,
    session: Session = Depends(get_session),
    actor: ActorContext = Depends(get_actor_context),
) -> RiskClusterOut:
    try:
        return approve_cluster(session, actor, cluster_id, payload)
    except ModerationError as error:
        _raise(error)


@router.post(
    "/internship-reports/{report_id}/identity-access-requests",
    response_model=IdentityAccessRequestOut,
    status_code=201,
    openapi_extra=required_idempotency_header(),
)
def identity_access_request_create(
    report_id: uuid.UUID,
    payload: IdentityAccessRequestIn,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key", include_in_schema=False),
    session: Session = Depends(get_session),
    actor: ActorContext = Depends(get_actor_context),
) -> IdentityAccessRequestOut:
    try:
        return request_identity_access(session, actor, report_id, payload, idempotency_key)
    except ModerationError as error:
        _raise(error)


@router.post(
    "/identity-access-requests/{request_id}/approvals",
    response_model=IdentityAccessRequestOut,
    openapi_extra=required_idempotency_header(),
)
def identity_access_request_approval(
    request_id: uuid.UUID,
    payload: IdentityAccessApprovalIn,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key", include_in_schema=False),
    session: Session = Depends(get_session),
    actor: ActorContext = Depends(get_actor_context),
) -> IdentityAccessRequestOut:
    try:
        return decide_identity_access(session, actor, request_id, payload, idempotency_key)
    except ModerationError as error:
        _raise(error)


@router.post(
    "/identity-access-requests/{request_id}/execute",
    response_model=IdentityAccessExecutionOut,
)
def identity_access_request_execute(
    request_id: uuid.UUID,
    response: Response,
    expected_version: int = Query(ge=1),
    session: Session = Depends(get_session),
    actor: ActorContext = Depends(get_actor_context),
) -> IdentityAccessExecutionOut:
    response.headers["Cache-Control"] = "no-store"
    try:
        return execute_identity_access(session, actor, request_id, expected_version)
    except ModerationError as error:
        _raise(error)
