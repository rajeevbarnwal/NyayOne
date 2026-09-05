"""Bounded NYAY-11 expiry/review-queue settlement; schedule with retention jobs."""
from datetime import datetime, timezone

from sqlalchemy import select

from app.db.session import get_sessionmaker
from app.models.student_authority import AuthorityState
from app.services.student_authority import _registration, settle_state


def run_once(session, *, now, batch_size=256):
    if type(batch_size) is not int or not 1 <= batch_size <= 256:
        raise ValueError("authority_batch_invalid")
    ids = list(session.scalars(select(AuthorityState.registration_id).where(
        (AuthorityState.guardian_expires_at <= now)
        | (AuthorityState.institutional_expires_at <= now)
        | (AuthorityState.review_due_at <= now)
    ).order_by(AuthorityState.registration_id).limit(batch_size)))
    changed = 0
    for registration_id in ids:
        reg = _registration(session, registration_id=registration_id)
        row = session.get(AuthorityState, registration_id)
        previous = row.version
        settle_state(session, reg, row, now)
        changed += int(row.version != previous)
    return {"examined": len(ids), "changed": changed}


def main():
    with get_sessionmaker()() as session, session.begin():
        counts = run_once(session, now=datetime.now(timezone.utc))
    print(f"authority examined={counts['examined']} changed={counts['changed']}")


if __name__ == "__main__":
    main()
