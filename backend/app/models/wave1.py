"""Wave 1 models (SAATHI-58 settings/DPDP + SAATHI-63 law schools).

Same conventions as the approved registration schema: UUID PKs (TimestampedBase),
timestamptz, indexed FKs with explicit ON DELETE, CHECK constraints on finite
domains, unique constraints for idempotency/user-scoping, optimistic version on
user_settings. No raw PII beyond fields already approved for display.
"""
from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean, CheckConstraint, DateTime, ForeignKey, Integer, String, UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import Uuid

from app.db.base import TimestampedBase

THEMES = ("system", "light", "dark")
PRIVACY_KINDS = ("analytics", "marketing", "share_partners")
DSR_KINDS = ("export", "delete")
DSR_STATUSES = ("pending", "processing", "complete", "failed", "cancelled")
JOB_STATUSES = ("pending", "processing", "complete", "failed")
DELETION_MODES = ("anonymise", "delete")
INSTITUTION_TYPES = ("national_law_university", "government", "private", "deemed")


def _in(col: str, allowed: tuple[str, ...], name: str) -> CheckConstraint:
    return CheckConstraint(f"{col} IN ({', '.join(repr(v) for v in allowed)})", name=name)


# --------------------------- SAATHI-58 -----------------------------------------
class UserSettings(TimestampedBase):
    __tablename__ = "user_settings"
    user_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False)
    theme: Mapped[str] = mapped_column(String(16), default="system", nullable=False)
    language: Mapped[str] = mapped_column(String(16), default="en", nullable=False)
    notif_email: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    notif_sms: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    notif_updates: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)  # optimistic concurrency
    __table_args__ = (
        UniqueConstraint("user_id", name="uq_user_settings_user_id"),
        _in("theme", THEMES, "theme"),
        CheckConstraint("version >= 1", name="version_positive"),
    )


class PrivacyPreference(TimestampedBase):
    __tablename__ = "privacy_preferences"
    user_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False)
    kind: Mapped[str] = mapped_column(String(32), nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    policy_version: Mapped[str] = mapped_column(String(40), default="dpdp-2023.v1", nullable=False)
    __table_args__ = (
        UniqueConstraint("user_id", "kind", name="uq_privacy_preferences_user_id"),
        _in("kind", PRIVACY_KINDS, "kind"),
    )


class DataSubjectRequest(TimestampedBase):
    __tablename__ = "data_subject_requests"
    user_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False)
    kind: Mapped[str] = mapped_column(String(16), nullable=False)
    opaque_id: Mapped[str] = mapped_column(String(64), nullable=False)  # client-facing, never row UUID
    status: Mapped[str] = mapped_column(String(16), default="pending", nullable=False)
    idempotency_key: Mapped[str | None] = mapped_column(String(200), nullable=True)
    reauth_verified: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    confirmation_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)  # keyed hash, never text
    __table_args__ = (
        UniqueConstraint("opaque_id", name="uq_data_subject_requests_opaque_id"),
        UniqueConstraint("idempotency_key", name="uq_data_subject_requests_idempotency_key"),
        _in("kind", DSR_KINDS, "kind"),
        _in("status", DSR_STATUSES, "status"),
    )


class ExportJob(TimestampedBase):
    __tablename__ = "export_jobs"
    request_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("data_subject_requests.id", ondelete="CASCADE"), index=True, nullable=False)
    status: Mapped[str] = mapped_column(String(16), default="pending", nullable=False)
    artifact_ref: Mapped[str | None] = mapped_column(String(200), nullable=True)  # storage boundary ref, never contents
    __table_args__ = (_in("status", JOB_STATUSES, "status"),)


class DeletionJob(TimestampedBase):
    __tablename__ = "deletion_jobs"
    request_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("data_subject_requests.id", ondelete="CASCADE"), index=True, nullable=False)
    status: Mapped[str] = mapped_column(String(16), default="pending", nullable=False)
    mode: Mapped[str] = mapped_column(String(16), default="anonymise", nullable=False)  # retention-config driven
    __table_args__ = (
        _in("status", JOB_STATUSES, "status"),
        _in("mode", DELETION_MODES, "mode"),
    )


# --------------------------- SAATHI-63 -----------------------------------------
class LawSchool(TimestampedBase):
    __tablename__ = "law_schools"
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    slug: Mapped[str] = mapped_column(String(200), nullable=False)
    state: Mapped[str] = mapped_column(String(80), index=True, nullable=False)
    institution_type: Mapped[str] = mapped_column(String(40), index=True, nullable=False)
    accreditation: Mapped[str | None] = mapped_column(String(80), nullable=True)
    entrance_exam: Mapped[str | None] = mapped_column(String(40), index=True, nullable=True)
    fees_min: Mapped[int | None] = mapped_column(Integer, nullable=True)
    fees_max: Mapped[int | None] = mapped_column(Integer, nullable=True)
    nirf_rank: Mapped[int | None] = mapped_column(Integer, nullable=True)
    __table_args__ = (
        UniqueConstraint("slug", name="uq_law_schools_slug"),
        _in("institution_type", INSTITUTION_TYPES, "institution_type"),
        CheckConstraint("fees_min IS NULL OR fees_min >= 0", name="fees_min_nonneg"),
    )


class LawSchoolSource(TimestampedBase):
    __tablename__ = "law_school_sources"
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    url: Mapped[str] = mapped_column(String(400), nullable=False)
    retrieved_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    freshness_days: Mapped[int] = mapped_column(Integer, default=180, nullable=False)


class LawSchoolProgramme(TimestampedBase):
    __tablename__ = "law_school_programmes"
    school_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("law_schools.id", ondelete="CASCADE"), index=True, nullable=False)
    degree: Mapped[str] = mapped_column(String(80), index=True, nullable=False)
    duration_years: Mapped[int] = mapped_column(Integer, nullable=False)
    __table_args__ = (CheckConstraint("duration_years > 0", name="duration_positive"),)


class LawSchoolFact(TimestampedBase):
    __tablename__ = "law_school_facts"
    school_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("law_schools.id", ondelete="CASCADE"), index=True, nullable=False)
    key: Mapped[str] = mapped_column(String(80), nullable=False)
    value: Mapped[str] = mapped_column(String(400), nullable=False)
    source_id: Mapped[uuid.UUID | None] = mapped_column(Uuid(as_uuid=True), ForeignKey("law_school_sources.id", ondelete="SET NULL"), index=True, nullable=True)
    __table_args__ = (UniqueConstraint("school_id", "key", name="uq_law_school_facts_school_id"),)


class SavedLawSchool(TimestampedBase):
    __tablename__ = "saved_law_schools"
    user_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False)
    school_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("law_schools.id", ondelete="CASCADE"), index=True, nullable=False)
    __table_args__ = (UniqueConstraint("user_id", "school_id", name="uq_saved_law_schools_user_id"),)


class LawSchoolFollow(TimestampedBase):
    __tablename__ = "law_school_follows"
    user_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False)
    school_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("law_schools.id", ondelete="CASCADE"), index=True, nullable=False)
    notify_opt_in: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    __table_args__ = (UniqueConstraint("user_id", "school_id", name="uq_law_school_follows_user_id"),)


class ComparisonSet(TimestampedBase):
    __tablename__ = "comparison_sets"
    user_id: Mapped[uuid.UUID | None] = mapped_column(Uuid(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=True)


class ComparisonItem(TimestampedBase):
    __tablename__ = "comparison_items"
    set_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("comparison_sets.id", ondelete="CASCADE"), index=True, nullable=False)
    school_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("law_schools.id", ondelete="CASCADE"), index=True, nullable=False)
    position: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    __table_args__ = (UniqueConstraint("set_id", "school_id", name="uq_comparison_items_set_id"),)
