"""Transactional internal moderation service for SAATHI-274.

The queue is moderator-only; reporter identity is never joined into list/detail
projections.  Raw narrative is returned only from the assigned case detail.
Clusters require organisation + category + time-window + clean-evidence
agreement and retain source report ids.  They never publish: the database and service both force
``publication_ready=False``.
"""
from __future__ import annotations

import re
import calendar
import hashlib
import json
import uuid
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.auth import ActorContext, Role
from app.core.config import settings
from app.core.crypto import decrypt, encrypt, key_version, keyed_hash
from app.models.registration import User
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
    NotificationOutbox,
    OrganisationResponse,
    OrganisationResponseRequest,
    PublicationDecision,
    PublishedRiskLabel,
    ReporterIdentityAccessApproval,
    ReporterIdentityAccessRequest,
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
    IdentityAccessApprovalIn,
    IdentityAccessExecutionOut,
    IdentityAccessRequestIn,
    IdentityAccessRequestOut,
    RiskClusterCreate,
    RiskClusterOut,
    RiskSignalApprovalIn,
)
from app.services.audit_service import record_audit_event
from app.services.organisation_identity import (
    OrganisationIdentityIntegrityError,
    decrypt_bound_organisation,
    normalise_organisation,
)

_IDEMPOTENCY_UNSAFE = re.compile(r"[\x00-\x20<>]")
_NEUTRAL_LABELS = {
    "unpaid_mismatch": "Moderated unpaid or stipend mismatch pattern",
    "excessive_hours": "Moderated excessive-hours pattern",
    "unsafe_environment": "Moderated workplace-safety pattern",
    "harassment": "Moderated workplace-conduct pattern",
    "discrimination": "Moderated equal-treatment concern pattern",
    "misleading_work": "Moderated role-description mismatch pattern",
    "non_response": "Moderated organisation non-response pattern",
    "certificate_withheld": "Moderated certificate-delay pattern",
    "stipend_delay_exploitative": "Moderated stipend-delay pattern",
    "positive_experience": "Moderated positive-experience pattern",
}


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


def _fingerprint(payload: dict[str, object]) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _audit_role(actor: ActorContext) -> str:
    for role in (
        Role.ADMIN, Role.MODERATOR, Role.SAFETY_OFFICER, Role.LEGAL_REVIEWER,
        Role.STUDENT, Role.TUTOR, Role.LAWYER,
    ):
        if actor.has_role(role):
            return role.value
    return "authenticated"


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


def _require_safety_officer(actor: ActorContext) -> None:
    if not actor.is_authenticated:
        raise ModerationError(401, "authentication_required", "Authentication required")
    if not actor.has_role(Role.SAFETY_OFFICER):
        raise ModerationError(403, "safety_officer_role_required", "Safety officer role required")


def _identity_approver_role(actor: ActorContext) -> str:
    if not actor.is_authenticated:
        raise ModerationError(401, "authentication_required", "Authentication required")
    if actor.has_role(Role.SAFETY_OFFICER):
        return Role.SAFETY_OFFICER.value
    if actor.has_role(Role.LEGAL_REVIEWER):
        return Role.LEGAL_REVIEWER.value
    raise ModerationError(403, "identity_approval_role_required", "Identity approval role required")


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
    # One privacy-safe audit event per request: never copy report ids,
    # organisation names, categories, evidence refs or narrative into audit.
    record_audit_event(
        session,
        action="moderation_queue_viewed",
        resource_type="moderation_queue",
        actor_user_id=actor.user_id,
        actor_role=_audit_role(actor),
        after_state={"state_filter": state or "all", "result_count": len(items)},
    )
    session.commit()
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
        actor_role=_audit_role(actor),
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
    fingerprint = _fingerprint({
        "report_id": report_id,
        "actor_id": actor.user_id,
        **payload.model_dump(),
    })
    if existing is not None:
        existing_case = session.get(ModerationCase, existing.case_id)
        if existing_case is None or existing_case.report_id != report_id or existing.actor_user_id != actor.user_id \
                or existing.request_fingerprint != fingerprint:
            raise ModerationError(409, "idempotency_conflict", "Idempotency key already used")
        current = _case(session, report_id)
        return ModerationActionOut(
            id=existing.id, case_id=current.id, action=existing.action,
            reason_code=existing.reason_code, case_state=current.state,
            case_version=current.version, created_at=_as_utc(existing.created_at),
        )

    # Canonical aggregate-source lock order is report -> moderation case.
    # Publication uses the same order after locking its cluster/signal/label,
    # so a source mutation can serialize with publication without a cycle.
    report = session.scalar(select(InternshipReport).where(
        InternshipReport.id == report_id,
        InternshipReport.deleted_at.is_(None),
    ).with_for_update())
    if report is None:
        raise ModerationError(404, "moderation_case_not_found", "Moderation case not found")
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
        request_fingerprint=fingerprint,
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
        actor_role=_audit_role(actor),
        after_state={"case_state": case.state, "reason_code": payload.reason_code, "case_version": case.version},
    )
    try:
        session.commit()
    except IntegrityError:
        session.rollback()
        existing = session.scalar(select(ModerationAction).where(ModerationAction.idempotency_key == key))
        existing_case = session.get(ModerationCase, existing.case_id) if existing else None
        if (
            existing
            and existing_case
            and existing_case.report_id == report_id
            and existing.actor_user_id == actor.user_id
            and existing.request_fingerprint == fingerprint
        ):
            current = _case(session, report_id)
            return ModerationActionOut(
                id=existing.id, case_id=current.id, action=existing.action,
                reason_code=existing.reason_code, case_state=current.state,
                case_version=current.version, created_at=_as_utc(existing.created_at),
            )
        if existing is not None:
            raise ModerationError(
                409, "idempotency_conflict", "Idempotency key already used"
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
    day = min(today.day, calendar.monthrange(year, month)[1])
    return date(year, month, day)


def _utc_today() -> date:
    """Return the UTC calendar date through a patchable clock boundary."""
    return datetime.now(timezone.utc).date()


def _cluster_out(session: Session, cluster: DuplicateCluster) -> RiskClusterOut:
    signal = session.scalar(select(RiskSignal).where(RiskSignal.cluster_id == cluster.id))
    members = list(session.scalars(select(DuplicateClusterMember.report_id).where(
        DuplicateClusterMember.cluster_id == cluster.id,
        DuplicateClusterMember.deleted_at.is_(None),
    ).order_by(DuplicateClusterMember.report_id)))
    try:
        organisation_name = decrypt_bound_organisation(
            cluster.organisation_ciphertext, cluster.organisation_hash
        )
    except OrganisationIdentityIntegrityError:
        raise ModerationError(
            409,
            "cluster_organisation_integrity_conflict",
            "Risk cluster organisation identity failed integrity validation",
        )
    if (
        _NEUTRAL_LABELS.get(cluster.category) is None
        or signal.neutral_label != _NEUTRAL_LABELS[cluster.category]
    ):
        raise ModerationError(
            409,
            "cluster_label_integrity_conflict",
            "Risk cluster label failed integrity validation",
        )
    return RiskClusterOut(
        id=cluster.id,
        organisation_name=organisation_name,
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
        publication_ready=signal.publication_ready,
        public_count=(None if signal.small_count_suppressed else signal.report_count),
        neutral_label=_NEUTRAL_LABELS[cluster.category],
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
    fingerprint = _fingerprint({
        "actor_id": actor.user_id,
        "report_ids": sorted(str(value) for value in payload.report_ids),
        "category": payload.category,
    })
    existing = session.scalar(select(DuplicateCluster).where(DuplicateCluster.idempotency_key == key))
    if existing:
        if existing.actor_user_id != actor.user_id or existing.request_fingerprint != fingerprint:
            raise ModerationError(409, "idempotency_conflict", "Idempotency key already used")
        return _cluster_out(session, existing)
    reports = list(session.scalars(select(InternshipReport).where(
        InternshipReport.id.in_(payload.report_ids), InternshipReport.deleted_at.is_(None)
    ).order_by(InternshipReport.id).with_for_update()))
    if len(reports) != len(payload.report_ids):
        raise ModerationError(404, "moderation_report_not_found", "Moderation report not found")
    # A competitor can commit the same idempotency key while this transaction
    # waits for its ordered report locks. Re-read after the wait so the loser
    # returns the durable winner instead of misclassifying it as overlap.
    existing = session.scalar(select(DuplicateCluster).where(
        DuplicateCluster.idempotency_key == key
    ))
    if existing:
        if existing.actor_user_id != actor.user_id or existing.request_fingerprint != fingerprint:
            raise ModerationError(409, "idempotency_conflict", "Idempotency key already used")
        return _cluster_out(session, existing)
    # Lock every source in a deterministic report -> case order. Concurrent
    # overlapping cluster creation therefore serializes before testing the
    # partial-unique membership invariant.
    cases_by_report = {
        case.report_id: case
        for case in session.scalars(select(ModerationCase).where(
            ModerationCase.report_id.in_([report.id for report in reports]),
            ModerationCase.deleted_at.is_(None),
        ).order_by(ModerationCase.report_id, ModerationCase.id).with_for_update())
    }
    cases = [cases_by_report.get(report.id) for report in reports]
    if any(case is None or case.state != "approved_aggregate_only" for case in cases):
        raise ModerationError(409, "reports_not_aggregate_approved", "Every report must be approved for aggregate-only use")
    evidence_states = {report.id: _scan_states(session, report.id) for report in reports}
    if any(
        not states or "clean" not in states or any(state != "clean" for state in states)
        for states in evidence_states.values()
    ):
        raise ModerationError(
            409,
            "clean_evidence_signal_required",
            "Every report requires clean evidence and no unresolved scan result",
        )
    organisations = {normalise_organisation(report.organisation_name) for report in reports}
    category_sets = {report.id: set(_categories(session, report.id)) for report in reports}
    if len(organisations) != 1 or any(payload.category not in values for values in category_sets.values()):
        raise ModerationError(422, "cluster_signal_mismatch", "Organisation and category signals must agree")
    dates = [report.experience_end_date or report.experience_start_date for report in reports]
    if any(value is None for value in dates):
        raise ModerationError(422, "cluster_date_required", "Every report needs an experience date")
    cutoff = _months_ago(_utc_today(), settings.internship_risk_window_months)
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
    overlap = session.scalar(select(DuplicateClusterMember.id).join(
        DuplicateCluster,
        DuplicateCluster.id == DuplicateClusterMember.cluster_id,
    ).where(
        DuplicateClusterMember.report_id.in_(payload.report_ids),
        DuplicateClusterMember.category == payload.category,
        DuplicateClusterMember.deleted_at.is_(None),
        DuplicateCluster.deleted_at.is_(None),
    ))
    if overlap is not None:
        raise ModerationError(
            409,
            "risk_cluster_source_overlap",
            "A report is already assigned to an active cluster for this category",
        )
    organisation_name = reports[0].organisation_name
    organisation_ct = encrypt(organisation_name)
    cluster = DuplicateCluster(
        organisation_hash=keyed_hash(normalise_organisation(organisation_name), lower=True),
        organisation_ciphertext=organisation_ct,
        key_version=key_version(organisation_ct),
        category=payload.category,
        window_start=min(dates),
        window_end=max(dates),
        explanation_code="organisation_category_time_window_clean_evidence",
        state="eligible" if threshold else "suppressed",
        idempotency_key=key,
        actor_user_id=actor.user_id,
        request_fingerprint=fingerprint,
    )
    try:
        # ``flush`` can raise the same unique violation as ``commit``. Keep
        # every write in the recovery boundary so a concurrent idempotent or
        # overlapping create becomes a typed result, never an uncaught 500.
        session.add(cluster)
        session.flush()
        session.add_all([
            DuplicateClusterMember(
                cluster_id=cluster.id,
                report_id=report.id,
                category=payload.category,
            )
            for report in reports
        ])
        signal = RiskSignal(
            cluster_id=cluster.id,
            neutral_label=_NEUTRAL_LABELS[payload.category],
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
            actor_role=_audit_role(actor),
            after_state={
                "category": payload.category, "report_count": len(reports),
                "distinct_reporter_count": distinct, "threshold_met": threshold,
                "evidence_signal_met": True,
                "publication_ready": False,
            },
        )
        session.commit()
    except IntegrityError:
        session.rollback()
        existing = session.scalar(select(DuplicateCluster).where(DuplicateCluster.idempotency_key == key))
        if existing:
            if (
                existing.actor_user_id != actor.user_id
                or existing.request_fingerprint != fingerprint
            ):
                raise ModerationError(
                    409, "idempotency_conflict", "Idempotency key already used"
                )
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
    output = _cluster_out(session, cluster)
    record_audit_event(
        session,
        action="risk_cluster_viewed",
        resource_type="duplicate_cluster",
        resource_id=cluster.id,
        actor_user_id=actor.user_id,
        actor_role=_audit_role(actor),
        after_state={"state": cluster.state, "version": cluster.version},
    )
    session.commit()
    return output


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
    # Canonical governed lock order: cluster -> signal -> published label ->
    # authority user. Invitation creation also locks label -> authority user.
    # Lock the optional label even for approvals so a concurrent veto/request
    # can never invert these two rows.
    label = session.scalar(select(PublishedRiskLabel).where(
        PublishedRiskLabel.risk_signal_id == signal.id,
        PublishedRiskLabel.status.in_(("published", "corrected")),
        PublishedRiskLabel.deleted_at.is_(None),
    ).with_for_update())
    current_actor = session.scalar(select(User).where(
        User.id == actor.user_id
    ).with_for_update())
    if (
        current_actor is None
        or current_actor.status != "active"
        or current_actor.role != role
    ):
        raise ModerationError(
            403,
            "risk_approval_actor_not_active",
            "Risk approval actor is not active",
        )
    existing = session.scalar(select(RiskSignalApproval).where(
        RiskSignalApproval.risk_signal_id == signal.id,
        RiskSignalApproval.actor_user_id == actor.user_id,
    ))
    if existing:
        if existing.decision != payload.decision or existing.actor_role != role:
            raise ModerationError(409, "risk_approval_conflict", "Approval already recorded")
        return _cluster_out(session, cluster)
    approval = RiskSignalApproval(
        risk_signal_id=signal.id, actor_user_id=actor.user_id, actor_role=role,
        decision=payload.decision, reason_code=payload.reason_code,
    )
    signal_id = signal.id
    session.add(approval)
    try:
        session.flush()
    except IntegrityError:
        session.rollback()
        winner = session.scalar(select(RiskSignalApproval).where(
            RiskSignalApproval.risk_signal_id == signal_id,
            RiskSignalApproval.actor_user_id == actor.user_id,
        ))
        if winner is not None and (
            winner.actor_role == role
            and winner.decision == payload.decision
            and winner.reason_code == payload.reason_code
        ):
            durable_cluster = session.get(DuplicateCluster, cluster_id)
            if durable_cluster is not None:
                return _cluster_out(session, durable_cluster)
        raise ModerationError(
            409, "risk_approval_conflict", "Approval already recorded"
        )
    decisions = list(session.scalars(select(RiskSignalApproval).where(
        RiskSignalApproval.risk_signal_id == signal.id,
        RiskSignalApproval.deleted_at.is_(None),
    ).order_by(RiskSignalApproval.id)))
    vetoed = any(row.decision == "reject" for row in decisions)
    signal.approval_vetoed = vetoed
    signal.moderator_approved = (
        not vetoed
        and any(row.actor_role == "moderator" and row.decision == "approve" for row in decisions)
    )
    signal.safety_legal_approved = (
        not vetoed
        and any(
            row.actor_role in {"safety_officer", "legal_reviewer"}
            and row.decision == "approve"
            for row in decisions
        )
    )
    signal.version += 1
    # SAATHI-274 may compute approvals but never publish.
    signal.publication_ready = False
    if vetoed:
        if label is not None:
            now = datetime.now(timezone.utc)
            label.status = "withdrawn"
            label.last_reviewed_at = now
            label.version += 1
            requests = list(session.scalars(select(OrganisationResponseRequest).where(
                OrganisationResponseRequest.published_label_id == label.id,
                OrganisationResponseRequest.state == "pending",
                OrganisationResponseRequest.deleted_at.is_(None),
            ).order_by(OrganisationResponseRequest.id).with_for_update()))
            request_ids = [item.id for item in requests]
            for item in requests:
                item.state = "revoked"
                item.version += 1
            if request_ids:
                invitations = list(session.scalars(select(NotificationOutbox).where(
                    NotificationOutbox.aggregate_type == "organisation_response_request",
                    NotificationOutbox.aggregate_id.in_(request_ids),
                    NotificationOutbox.event_kind == "organisation_response_requested",
                    NotificationOutbox.state.in_(("pending", "processing", "failed")),
                    NotificationOutbox.deleted_at.is_(None),
                ).order_by(NotificationOutbox.id).with_for_update()))
                for invitation in invitations:
                    invitation.state = "void"
                    invitation.claimed_at = None
                    invitation.claim_token = None
                    invitation.available_at = None
                    invitation.secret_ciphertext = None
                    invitation.secret_key_version = None
                    invitation.last_error_code = "risk_signal_vetoed"
            pending_responses = list(session.scalars(select(OrganisationResponse).where(
                OrganisationResponse.published_label_id == label.id,
                OrganisationResponse.state == "moderation_pending",
                OrganisationResponse.deleted_at.is_(None),
            ).order_by(OrganisationResponse.id).with_for_update()))
            for response in pending_responses:
                response.state = "rejected"
                response.is_current = False
                response.moderated_at = now
                response.version += 1
            session.add(NotificationOutbox(
                aggregate_type="published_risk_label",
                aggregate_id=label.id,
                event_kind="risk_label_withdrawn",
                idempotency_key=f"notification:risk-veto:{approval.id}",
                payload_json={"label_id": str(label.id), "status": "withdrawn"},
                available_at=now,
            ))
            withdrawal_key = f"risk-veto-withdraw:{approval.id}"
            withdrawal_fingerprint = hashlib.sha256(
                f"{signal.id}:{label.id}:{approval.id}:withdraw".encode("utf-8")
            ).hexdigest()
            session.add(PublicationDecision(
                risk_signal_id=signal.id,
                published_label_id=label.id,
                actor_user_id=actor.user_id,
                decision="withdraw",
                reason_code="risk_signal_veto",
                idempotency_key=withdrawal_key,
                expected_version=signal.version,
                request_fingerprint=withdrawal_fingerprint,
            ))
    record_audit_event(
        session,
        action="risk_signal_approval_recorded",
        resource_type="risk_signal",
        resource_id=signal.id,
        actor_user_id=actor.user_id,
        actor_role=role,
        after_state={
            "decision": payload.decision,
            "reason_code": payload.reason_code,
            "approval_vetoed": vetoed,
            "publication_ready": False,
        },
    )
    session.commit()
    return _cluster_out(session, cluster)


def _identity_request_out(session: Session, row: ReporterIdentityAccessRequest) -> IdentityAccessRequestOut:
    approvals = session.scalar(select(func.count()).select_from(ReporterIdentityAccessApproval).where(
        ReporterIdentityAccessApproval.request_id == row.id,
        ReporterIdentityAccessApproval.decision == "approve",
        ReporterIdentityAccessApproval.deleted_at.is_(None),
    )) or 0
    return IdentityAccessRequestOut(
        id=row.id,
        report_id=row.report_id,
        state=row.state,
        approval_count=approvals,
        version=row.version,
        expires_at=_as_utc(row.expires_at),
        created_at=_as_utc(row.created_at),
    )


def request_identity_access(
    session: Session,
    actor: ActorContext,
    report_id: uuid.UUID,
    payload: IdentityAccessRequestIn,
    idempotency_key: str | None,
) -> IdentityAccessRequestOut:
    _require_safety_officer(actor)
    key = safe_idempotency(idempotency_key)
    fingerprint = _fingerprint({
        "report_id": report_id,
        "actor_id": actor.user_id,
        "reason_digest": keyed_hash(payload.reason_detail),
    })
    existing = session.scalar(select(ReporterIdentityAccessRequest).where(
        ReporterIdentityAccessRequest.idempotency_key == key
    ))
    if existing:
        if existing.request_fingerprint != fingerprint:
            raise ModerationError(409, "idempotency_conflict", "Idempotency key already used")
        return _identity_request_out(session, existing)
    report = session.scalar(select(InternshipReport.id).where(
        InternshipReport.id == report_id, InternshipReport.deleted_at.is_(None)
    ))
    vault = session.scalar(select(ReporterIdentityVault.id).where(
        ReporterIdentityVault.report_id == report_id,
        ReporterIdentityVault.deleted_at.is_(None),
    ))
    if report is None or vault is None:
        raise ModerationError(404, "moderation_report_not_found", "Moderation report not found")
    ciphertext = encrypt(payload.reason_detail)
    row = ReporterIdentityAccessRequest(
        report_id=report_id,
        safety_officer_user_id=actor.user_id,
        reason_ciphertext=ciphertext,
        reason_key_version=key_version(ciphertext),
        idempotency_key=key,
        request_fingerprint=fingerprint,
        state="pending",
        version=1,
        expires_at=datetime.now(timezone.utc) + timedelta(
            minutes=settings.internship_identity_access_ttl_minutes
        ),
    )
    try:
        # The idempotency UNIQUE can fire during flush on PostgreSQL. The
        # recovery boundary must therefore start before the first write.
        session.add(row)
        session.flush()
        record_audit_event(
            session,
            action="reporter_identity_access_requested",
            resource_type="reporter_identity_access_request",
            resource_id=row.id,
            actor_user_id=actor.user_id,
            actor_role=Role.SAFETY_OFFICER.value,
            after_state={"state": "pending", "version": 1},
        )
        session.commit()
    except IntegrityError:
        session.rollback()
        existing = session.scalar(select(ReporterIdentityAccessRequest).where(
            ReporterIdentityAccessRequest.idempotency_key == key
        ))
        if existing is None:
            raise ModerationError(
                409, "identity_access_request_conflict", "Identity access request conflicted"
            )
        if (
            existing.report_id != report_id
            or existing.safety_officer_user_id != actor.user_id
            or existing.request_fingerprint != fingerprint
        ):
            raise ModerationError(
                409, "idempotency_conflict", "Idempotency key already used"
            )
        return _identity_request_out(session, existing)
    return _identity_request_out(session, row)


def decide_identity_access(
    session: Session,
    actor: ActorContext,
    request_id: uuid.UUID,
    payload: IdentityAccessApprovalIn,
    idempotency_key: str | None,
) -> IdentityAccessRequestOut:
    role = _identity_approver_role(actor)
    key = safe_idempotency(idempotency_key)
    row = session.scalar(select(ReporterIdentityAccessRequest).where(
        ReporterIdentityAccessRequest.id == request_id,
        ReporterIdentityAccessRequest.deleted_at.is_(None),
    ).with_for_update())
    if row is None:
        raise ModerationError(404, "identity_access_request_not_found", "Identity access request not found")
    approver_user = session.scalar(select(User).where(
        User.id == actor.user_id
    ).with_for_update())
    if (
        approver_user is None
        or approver_user.status != "active"
        or approver_user.role != role
    ):
        raise ModerationError(
            403,
            "identity_access_approver_not_active",
            "Identity access approver is not active",
        )
    if row.safety_officer_user_id == actor.user_id:
        raise ModerationError(403, "requester_cannot_approve", "Requester cannot approve identity access")
    existing_key = session.scalar(select(ReporterIdentityAccessApproval).where(
        ReporterIdentityAccessApproval.idempotency_key == key
    ))
    if existing_key:
        if existing_key.request_id != row.id or existing_key.approver_user_id != actor.user_id \
                or existing_key.decision != payload.decision:
            raise ModerationError(409, "idempotency_conflict", "Idempotency key already used")
        return _identity_request_out(session, row)
    if row.version != payload.expected_version:
        raise ModerationError(409, "stale_identity_access_request", "Identity access request changed", current_version=row.version)
    if _as_utc(row.expires_at) <= datetime.now(timezone.utc):
        row.state = "expired"
        row.version += 1
        session.commit()
        raise ModerationError(
            409, "identity_access_request_expired", "Identity access request expired",
            current_version=row.version,
        )
    if row.state in {"rejected", "executed", "expired"}:
        raise ModerationError(409, "identity_access_decision_not_allowed", "Identity access decision is not allowed")
    prior = session.scalar(select(ReporterIdentityAccessApproval).where(
        ReporterIdentityAccessApproval.request_id == row.id,
        ReporterIdentityAccessApproval.approver_user_id == actor.user_id,
    ))
    if prior:
        raise ModerationError(409, "identity_access_approver_duplicate", "Approver already decided")
    approval = ReporterIdentityAccessApproval(
        request_id=row.id,
        approver_user_id=actor.user_id,
        approver_role=role,
        decision=payload.decision,
        idempotency_key=key,
    )
    session.add(approval)
    try:
        session.flush()
    except IntegrityError:
        session.rollback()
        winner = session.scalar(select(ReporterIdentityAccessApproval).where(
            ReporterIdentityAccessApproval.idempotency_key == key
        ))
        if winner is not None and (
            winner.request_id == request_id
            and winner.approver_user_id == actor.user_id
            and winner.approver_role == role
            and winner.decision == payload.decision
        ):
            durable_request = session.get(ReporterIdentityAccessRequest, request_id)
            if durable_request is not None:
                return _identity_request_out(session, durable_request)
        if winner is not None:
            raise ModerationError(
                409, "idempotency_conflict", "Idempotency key already used"
            )
        raise ModerationError(
            409,
            "identity_access_approval_conflict",
            "Identity access approval conflicted",
        )
    decisions = list(session.scalars(select(ReporterIdentityAccessApproval).where(
        ReporterIdentityAccessApproval.request_id == row.id,
        ReporterIdentityAccessApproval.deleted_at.is_(None),
    )))
    if any(item.decision == "reject" for item in decisions):
        row.state = "rejected"
    elif len({item.approver_user_id for item in decisions if item.decision == "approve"}) >= 2:
        row.state = "approved"
    row.version += 1
    record_audit_event(
        session,
        action="reporter_identity_access_decided",
        resource_type="reporter_identity_access_request",
        resource_id=row.id,
        actor_user_id=actor.user_id,
        actor_role=role,
        after_state={
            "state": row.state,
            "decision": payload.decision,
            "approval_count": len([item for item in decisions if item.decision == "approve"]),
            "version": row.version,
        },
    )
    session.commit()
    return _identity_request_out(session, row)


def execute_identity_access(
    session: Session,
    actor: ActorContext,
    request_id: uuid.UUID,
    expected_version: int,
) -> IdentityAccessExecutionOut:
    _require_safety_officer(actor)
    row = session.scalar(select(ReporterIdentityAccessRequest).where(
        ReporterIdentityAccessRequest.id == request_id,
        ReporterIdentityAccessRequest.deleted_at.is_(None),
    ).with_for_update())
    if row is None or row.safety_officer_user_id != actor.user_id:
        raise ModerationError(404, "identity_access_request_not_found", "Identity access request not found")
    requester_user = session.scalar(select(User).where(
        User.id == actor.user_id
    ).with_for_update())
    if (
        requester_user is None
        or requester_user.status != "active"
        or requester_user.role != Role.SAFETY_OFFICER.value
    ):
        raise ModerationError(
            403,
            "identity_access_requester_not_active",
            "Identity access requester is not active",
        )
    if row.version != expected_version:
        raise ModerationError(409, "stale_identity_access_request", "Identity access request changed", current_version=row.version)
    if _as_utc(row.expires_at) <= datetime.now(timezone.utc):
        row.state = "expired"
        row.version += 1
        session.commit()
        raise ModerationError(
            409, "identity_access_request_expired", "Identity access request expired",
            current_version=row.version,
        )
    decisions = list(session.scalars(select(ReporterIdentityAccessApproval).where(
        ReporterIdentityAccessApproval.request_id == row.id,
        ReporterIdentityAccessApproval.deleted_at.is_(None),
    ).with_for_update()))
    approved_ids = {
        item.approver_user_id
        for item in decisions
        if item.decision == "approve"
        and item.approver_role in {"safety_officer", "legal_reviewer"}
    }
    approver_users = {
        user.id: user
        for user in session.scalars(
            select(User).where(User.id.in_(approved_ids)).order_by(User.id).with_for_update()
        )
    }
    valid_approval_ids = {
        item.approver_user_id
        for item in decisions
        if item.approver_user_id in approver_users
        and item.decision == "approve"
        and approver_users[item.approver_user_id].status == "active"
        and approver_users[item.approver_user_id].role == item.approver_role
        and item.approver_role in {"safety_officer", "legal_reviewer"}
    }
    if row.state != "approved" or any(item.decision == "reject" for item in decisions) \
            or len(valid_approval_ids) < 2:
        raise ModerationError(409, "identity_access_not_approved", "Identity access is not approved")
    vault = session.scalar(select(ReporterIdentityVault).where(
        ReporterIdentityVault.report_id == row.report_id,
        ReporterIdentityVault.deleted_at.is_(None),
    ).with_for_update())
    if vault is None:
        raise ModerationError(404, "identity_access_request_not_found", "Identity access request not found")
    try:
        identity = decrypt(vault.reporter_ciphertext)
        identity_bound = (
            key_version(vault.reporter_ciphertext) == vault.key_version
            and keyed_hash(identity) == vault.reporter_lookup_hash
        )
    except Exception:
        identity_bound = False
        identity = ""
    if not identity_bound:
        raise ModerationError(
            409,
            "reporter_identity_integrity_conflict",
            "Reporter identity failed integrity validation",
        )
    row.state = "executed"
    row.executed_at = datetime.now(timezone.utc)
    row.version += 1
    record_audit_event(
        session,
        action="reporter_identity_access_executed",
        resource_type="reporter_identity_access_request",
        resource_id=row.id,
        actor_user_id=actor.user_id,
        actor_role=Role.SAFETY_OFFICER.value,
        after_state={"state": "executed", "approval_count": 2, "version": row.version},
    )
    session.commit()
    return IdentityAccessExecutionOut(
        request_id=row.id, state=row.state, reporter_identity=identity
    )
