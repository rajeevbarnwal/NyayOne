"""SQLAlchemy models. Import model modules here so their tables register on
Base.metadata (foundation stage: audit only; domain models added post-approval)."""
from app.db.models.audit import AuditEvent

__all__ = ["AuditEvent"]
