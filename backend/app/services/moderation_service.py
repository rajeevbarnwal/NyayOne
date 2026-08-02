"""Transactional internal moderation service for SAATHI-274.

The queue is moderator-only; reporter identity is never joined into list/detail
projections.  Raw narrative is returned only from the assigned case detail.
Clusters require organisation + category + time-window agreement and retain
source report ids.  They never publish: the database and service both force
``publication_ready=False``.
"""
from __future__ import annotations

import re
import uuid
from dataclasses import dataclass
from datetime import date, datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.auth import ActorContext, Role
from app.core.config import settings
from app.core.crypto import decrypt, encrypt, key_version, keyed_hash
from app.models.wave4 import (
    DuplicateCluster,
    DuplicateClusterMember,
    InternshipReport,
    InternshipReportCategory,
    InternshipReportEvidence,
    ModerationAction,
    ModerationAssignment,
    ModerationCase,
    ModerationHandoff,
    ModerationNotificationOutbox,
    ReporterIdentityVault,
    RiskSignal,
    RiskSignalApproval,
)
from app.schemas.moderation import (
    ModerationActionIn,
    ModerationActionOut,
    ModerationCaseOut,
    ModerationQueueItemOut,
    ModerationQueueOut,
    RiskClusterCreate,
    RiskClusterOut,
    RiskSignalApprovalIn,
)
from app.services.audit_service import record_audit_event

_IDEMPOTENCY_UNSAFE = re.compile(r"[\x00-\x20<>]")


@dataclass(frozen=True)
class ModerationError(Exception):
    status_code: int
    code: str
    message: str
    field: str | None = None
    current_version: int | None = None


def _as_utc(value: datetime) -> datetime:
    """Normalise SQLite's naive reload to the PostgreSQL UTC wire contract."""
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


def safe_idempotency(value: str | None) -> str:
    cleaned = (value or "").strip()
    if not 8 <= len(cleaned) <= 200 or _IDEMPOTENCY_UNSAFE.search(cleaned):
        raise ModerationError(422, "invalid_idempotency_key", "A safe Idempotency-Key is required", "Idempotency-Key")
    return cleaned


def require_moderator(actor: ActorContext) -> None:
    if not actor.is_authenticated:
        raise ModerationError(401, "authentication_required", "Authentication required")
    if not (actor.has_role(Role.MODERATOR) or actor.has_role(Role.ADMIN)):
        raise ModerationError(403, "moderator_role_required", "Moderator role required")


def require_approval_role(actor: ActorContext) -> str:
    if not actor.is_authenticated:
        raise ModerationError(401, "authentication_required", "Authentication required")
    for role in (Role.MODERATOR, Role.SAFETY_OFFICER, Role.LEGAL_REVIEWER):
        if actor.has_role(role):
            return role.value
    raise ModerationError(403, "risk_approval_role_required", "Risk approval role required")


def _case(session: Session, report_id: uuid.UUID, *, lock: bool = False) -> ModerationCase:
    stmt = select(ModerationCase).where(
        ModerationCase.report_id == report_id, ModerationCase.deleted_at.is_(None)
    )
    if lock:
        stmt = stmt.with_for_update()
    row = session.scalar(stmt)
    if row is None:
        raise ModerationError(404, "moderation_case_not_found", "Moderation case not found")
    return row


def _case_by_report(session: Session, report_id: uuid.UUID) -> ModerationCase | None:
    return session.scalar(select(ModerationCase).where(
        ModerationCase.report_id == report_id, ModerationCase.deleted_at.is_(None)
    ))


def _categories(session: Session, report_id: uuid.UUID) -> list[str]:
    return list(session.scalars(select(InternshipReportCategory.category).where(
        InternshipReportCategory.report_id == report_id,
        InternshipReportCategory.deleted_at.is_(None),
    ).order_by(InternshipReportCategory.category)))


def _scan_states(session: Session, report_id: uuid.UUID) -> list[str]:
    return list(session.scalars(select(InternshipReportEvidence.scan_state).where(
        InternshipReportEvidence.report_id == report_id,
        InternshipReportEvidence.deleted_at.is_(None),
    ).order_by(InternshipReportEvidence.created_at, InternshipReportEvidence.id)))


def _queue_out(session: Session, case: ModerationCase, actor_id: uuid.UUID) -> ModerationQueueItemOut:
    report = session.get(InternshipReport, case.report_id)
    if report is None:
        raise ModerationError(404, "moderation_case_not_found", "Moderation case not found")
    scans = _scan_states(session, report.id)
    return ModerationQueueItemOut(
        case_id=case.id,
        report_id=report.id,
        organisation_name=report.organisation_name,
        categories=_categories(session, report.id),
        experience_start_date=report.experience_start_date,
        experience_end_date=report.experience_end_date,
        evidence_clean=sum(value == "clean" for value in scans),
        evidence_total=len(scans),
        state=case.state,
        assigned_to_me=case.assigned_moderator_user_id == actor_id,
        version=case.version,
        submitted_at=report.submitted_at,
    )


def list_cases(session: Session, actor: ActorContext, state: str | None = None) -> ModerationQueueOut:
    require_moderator(actor)
    stmt = select(ModerationCase).where(ModerationCase.deleted_at.is_(None))
    if state:
        if state not in {"pending", "under_review", "approved_aggregate_only", "rejected", "needs_information"}:
            raise ModerationError(422, "unsupported_moderation_state", "Unsupported moderation state", "state")
        stmt = stmt.where(ModerationCase.state == state)
    rows = list(session.scalars(stmt.order_by(ModerationCase.created_at, ModerationCase.id)))
    items = [_queue_out(session, row, actor.user_id) for row in rows]
    # Viewing the queue is deliberately not audited per row: that would create
    # an unbounded access log. Detail views and all mutations are audited.
    return ModerationQueueOut(items=items, total=len(items))


def get_case(session: Session, actor: ActorContext, report_id: uuid.UUID) -> ModerationCaseOut:
    require_moderator(actor)
    case = _case(session, report_id)
    # Once claimed, ordinary moderators cannot inspect another moderator's case.
    if case.assigned_moderator_user_id not in {None, actor.user_id} and not actor.has_role(Role.ADMIN):
        raise ModerationError(404, "moderation_case_not_found", "Moderation case not found")
    queue = _queue_out(session, case, actor.user_id)
    report = session.get(InternshipReport, case.report_id)
    record_audit_event(
        session,
        action="moderation_case_viewed",
        resource_type="moderation_case",
        resource_id=case.id,
        actor_user_id=actor.user_id,
        actor_role="moderator",
        after_state={"case_state": case.state, "case_version": case.version},
    )
    session.commit()
    return ModerationCaseOut(
        **queue.model_dump(),
        listing_application_ref=report.listing_application_ref,
        narrative=report.narrative,
        privacy_mode=report.privacy_mode,
        support_guidance_required=report.support_guidance_required,
        scan_states=_scan_states(session, report.id),
    )


def act_on_case(
    session: Session,
    actor: ActorContext,
    report_id: uuid.UUID,
    payload: ModerationActionIn,
    idempotency_key: str | None,
) -> ModerationActionOut:
    require_moderator(actor)
    key = safe_idempotency(idempotency_key)
    existing = session.scalar(select(ModerationAction).where(ModerationAction.idempotency_key == key))
    if existing is not None:
        existing_case = session.get(ModerationCase, existing.case_id)
        if existing_case is None or existing_case.report_id != report_id or existing.actor_user_id != actor.user_id:
            raise ModerationError(409, "idempotency_conflict", "Idempotency key already used")
        current = _case(session, report_id)
        return ModerationActionOut(
            id=existing.id, case_id=current.id, action=existing.action,
            reason_code=existing.reason_code, case_state=current.state,
            case_version=current.version, created_at=_as_utc(existing.created_at),
        )

    case = _case(session, report_id, lock=True)
    if case.version != payload.expected_version:
        raise ModerationError(409, "stale_moderation_case", "Case changed in another session", current_version=case.version)
    now = datetime.now(timezone.utc)
    if payload.action == "claim":
        if case.state != "pending" or case.assigned_moderator_user_id is not None:
            raise ModerationError(409, "moderation_case_already_claimed", "Case is already claimed")
        case.state = "under_review"
        case.assigned_moderator_user_id = actor.user_id
        case.claimed_at = now
        session.add(ModerationAssignment(
            case_id=case.id, moderator_user_id=actor.user_id, active=True, assigned_at=now
        ))
        handoff_state = "assigned"
    else:
        if case.state != "under_review" or case.assigned_moderator_user_id != actor.user_id:
            raise ModerationError(409, "moderation_action_not_allowed", "Claim the case before taking this action")
        case.state, handoff_state = {
            "needs_information": ("needs_information", "needs_information"),
            "approve_aggregate_only": ("approved_aggregate_only", "approved"),
            "reject": ("rejected", "rejected"),
        }[payload.action]
        assignment = session.scalar(select(ModerationAssignment).where(
            ModerationAssignment.case_id == case.id,
            ModerationAssignment.moderator_user_id == actor.user_id,
            ModerationAssignment.active.is_(True),
        ).with_for_update())
        if assignment:
            assignment.active = False
            assignment.released_at = now
    case.version += 1
    handoff = session.scalar(select(ModerationHandoff).where(ModerationHandoff.report_id == case.report_id).with_for_update())
    if handoff:
        handoff.state = handoff_state
        handoff.assigned_moderator_user_id = actor.user_id
        handoff.version += 1
    report = session.get(InternshipReport, case.report_id)
    if payload.action == "needs_information":
        report.status = "needs_information"
    elif payload.action == "approve_aggregate_only":
        report.status = "approved"
    elif payload.action == "reject":
        report.status = "rejected"

    ciphertext = encrypt(payload.reason_detail)
    action = ModerationAction(
        case_id=case.id,
        actor_user_id=actor.user_id,
        action=payload.action,
        reason_code=payload.reason_code,
        reason_ciphertext=ciphertext,
        reason_key_version=key_version(ciphertext),
        idempotency_key=key,
        case_version=case.version,
    )
    session.add(action)
    if payload.action != "claim":
        session.add(ModerationNotificationOutbox(
            case_id=case.id,
            report_id=case.report_id,
            event_kind=("report_information_requested" if payload.action == "needs_information" else "moderation_decision_recorded"),
            idempotency_key=f"moderation-notification:{key}",
            payload_json={"case_state": case.state, "report_status": report.status},
        ))
    record_audit_event(
        session,
        action=f"moderation_{payload.action}",
        resource_type="moderation_case",
        resource_id=case.id,
        actor_user_id=actor.user_id,
        actor_role="moderator",
        after_state={"case_state": case.state, "reason_code": payload.reason_code, "case_version": case.version},
    )
    try:
        session.commit()
    except IntegrityError:
        session.rollback()
        existing = session.scalar(select(ModerationAction).where(ModerationAction.idempotency_key == key))
        existing_case = session.get(ModerationCase, existing.case_id) if existing else None
        if existing and existing_case and existing_case.report_id == report_id and existing.actor_user_id == actor.user_id:
            current = _case(session, report_id)
            return ModerationActionOut(
                id=existing.id, case_id=current.id, action=existing.action,
                reason_code=existing.reason_code, case_state=current.state,
                case_version=current.version, created_at=_as_utc(existing.created_at),
            )
        raise ModerationError(409, "moderation_action_conflict", "Moderation action conflicted")
    return ModerationActionOut(
        id=action.id, case_id=case.id, action=action.action, reason_code=action.reason_code,
        case_state=case.state, case_version=case.version, created_at=_as_utc(action.created_at),
    )


def _months_ago(today: date, months: int) -> date:
    absolute = today.year * 12 + today.month - 1 - months
    year, month0 = divmod(absolute, 12)
    month = month0 + 1
    # All comparison dates are first-of-month; no end-of-month ambiguity.
    return date(year, month, 1)


def _cluster_out(session: Session, cluster: DuplicateCluster) -> RiskClusterOut:
    signal = session.scalar(select(RiskSignal).where(RiskSignal.cluster_id == cluster.id))
    members = list(session.scalars(select(DuplicateClusterMember.report_id).where(
        DuplicateClusterMember.cluster_id == cluster.id,
        DuplicateClusterMember.deleted_at.is_(None),
    ).order_by(DuplicateClusterMember.report_id)))
    return RiskClusterOut(
        id=cluster.id,
        organisation_name=decrypt(cluster.organisation_ciphertext),
        category=cluster.category,
        explanation_code=cluster.explanation_code,
        state=cluster.state,
        member_report_ids=members,
        report_count=signal.report_count,
        distinct_reporter_count=signal.distinct_reporter_count,
        threshold_met=signal.threshold_met,
        small_count_suppressed=signal.small_count_suppressed,
        moderator_approved=signal.moderator_approved,
        safety_legal_approved=signal.safety_legal_approved,
        publication_ready=False,
        public_count=(None if signal.small_count_suppressed else signal.report_count),
        neutral_label=signal.neutral_label,
        version=signal.version,
    )


def create_cluster(
    session: Session,
    actor: ActorContext,
    payload: RiskClusterCreate,
    idempotency_key: str | None,
) -> RiskClusterOut:
    require_moderator(actor)
    key = safe_idempotency(idempotency_key)
    existing = session.scalar(select(DuplicateCluster).where(DuplicateCluster.idempotency_key == key))
    if existing:
        return _cluster_out(session, existing)
    reports = list(session.scalars(select(InternshipReport).where(
        InternshipReport.id.in_(payload.report_ids), InternshipReport.deleted_at.is_(None)
    )))
    if len(reports) != len(payload.report_ids):
        raise ModerationError(404, "moderation_report_not_found", "Moderation report not found")
    cases = [_case_by_report(session, report.id) for report in reports]
    if any(case is None or case.state != "approved_aggregate_only" for case in cases):
        raise ModerationError(409, "reports_not_aggregate_approved", "Every report must be approved for aggregate-only use")
    organisations = {" ".join(report.organisation_name.casefold().split()) for report in reports}
    category_sets = {report.id: set(_categories(session, report.id)) for report in reports}
    if len(organisations) != 1 or any(payload.category not in values for values in category_sets.values()):
        raise ModerationError(422, "cluster_signal_mismatch", "Organisation and category signals must agree")
    dates = [report.experience_end_date or report.experience_start_date for report in reports]
    if any(value is None for value in dates):
        raise ModerationError(422, "cluster_date_required", "Every report needs an experience date")
    cutoff = _months_ago(date.today(), settings.internship_risk_window_months)
    if any(value < cutoff for value in dates):
        raise ModerationError(422, "cluster_outside_time_window", "Reports must be inside the rolling time window")
    reporter_hashes = {
        session.scalar(select(ReporterIdentityVault.reporter_lookup_hash).where(ReporterIdentityVault.report_id == report.id))
        for report in reports
    }
    if None in reporter_hashes:
        raise ModerationError(409, "cluster_identity_boundary_missing", "Reporter identity boundary is incomplete")
    distinct = len(reporter_hashes)
    threshold = distinct >= settings.internship_risk_min_distinct_reporters
    suppressed = distinct < settings.internship_risk_public_count_suppression
    organisation_name = reports[0].organisation_name
    organisation_ct = encrypt(organisation_name)
    cluster = DuplicateCluster(
        organisation_hash=keyed_hash(" ".join(organisation_name.casefold().split()), lower=True),
        organisation_ciphertext=organisation_ct,
        key_version=key_version(organisation_ct),
        category=payload.category,
        window_start=min(dates),
        window_end=max(dates),
        explanation_code="organisation_category_time_window",
        state="eligible" if threshold else "suppressed",
        idempotency_key=key,
    )
    session.add(cluster)
    session.flush()
    session.add_all([DuplicateClusterMember(cluster_id=cluster.id, report_id=report.id) for report in reports])
    signal = RiskSignal(
        cluster_id=cluster.id,
        neutral_label=f"Moderated {payload.category.replace('_', ' ')} pattern",
        report_count=len(reports),
        distinct_reporter_count=distinct,
        threshold_met=threshold,
        small_count_suppressed=suppressed,
        publication_ready=False,
    )
    session.add(signal)
    record_audit_event(
        session,
        action="moderation_cluster_created",
        resource_type="duplicate_cluster",
        resource_id=cluster.id,
        actor_user_id=actor.user_id,
        actor_role="moderator",
        after_state={
            "category": payload.category, "report_count": len(reports),
            "distinct_reporter_count": distinct, "threshold_met": threshold,
            "publication_ready": False,
        },
    )
    try:
        session.commit()
    except IntegrityError:
        session.rollback()
        existing = session.scalar(select(DuplicateCluster).where(DuplicateCluster.idempotency_key == key))
        if existing:
            return _cluster_out(session, existing)
        raise ModerationError(409, "risk_cluster_conflict", "Risk cluster conflicted")
    return _cluster_out(session, cluster)


def get_cluster(session: Session, actor: ActorContext, cluster_id: uuid.UUID) -> RiskClusterOut:
    require_moderator(actor)
    cluster = session.scalar(select(DuplicateCluster).where(
        DuplicateCluster.id == cluster_id, DuplicateCluster.deleted_at.is_(None)
    ))
    if cluster is None:
        raise ModerationError(404, "risk_cluster_not_found", "Risk cluster not found")
    return _cluster_out(session, cluster)


def approve_cluster(
    session: Session,
    actor: ActorContext,
    cluster_id: uuid.UUID,
    payload: RiskSignalApprovalIn,
) -> RiskClusterOut:
    role = require_approval_role(actor)
    cluster = session.scalar(select(DuplicateCluster).where(
        DuplicateCluster.id == cluster_id, DuplicateCluster.deleted_at.is_(None)
    ).with_for_update())
    if cluster is None:
        raise ModerationError(404, "risk_cluster_not_found", "Risk cluster not found")
    signal = session.scalar(select(RiskSignal).where(RiskSignal.cluster_id == cluster.id).with_for_update())
    if not signal.threshold_met:
        raise ModerationError(409, "risk_threshold_not_met", "Risk threshold is not met")
    existing = session.scalar(select(RiskSignalApproval).where(
        RiskSignalApproval.risk_signal_id == signal.id,
        RiskSignalApproval.actor_user_id == actor.user_id,
    ))
    if existing:
        if existing.decision != payload.decision or existing.actor_role != role:
            raise ModerationError(409, "risk_approval_conflict", "Approval already recorded")
        return _cluster_out(session, cluster)
    session.add(RiskSignalApproval(
        risk_signal_id=signal.id, actor_user_id=actor.user_id, actor_role=role,
        decision=payload.decision, reason_code=payload.reason_code,
    ))
    if payload.decision == "approve":
        if role == "moderator":
            signal.moderator_approved = True
        else:
            signal.safety_legal_approved = True
    signal.version += 1
    # SAATHI-274 may compute approvals but never publish.
    signal.publication_ready = False
    record_audit_event(
        session,
        action="risk_signal_approval_recorded",
        resource_type="risk_signal",
        resource_id=signal.id,
        actor_user_id=actor.user_id,
        actor_role=role,
        after_state={"decision": payload.decision, "reason_code": payload.reason_code, "publication_ready": False},
    )
    session.commit()
    return _cluster_out(session, cluster)
