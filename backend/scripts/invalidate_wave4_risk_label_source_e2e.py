"""Invalidate one deterministic Wave 4 source for the browser release gate.

This is not a product administration surface. It is a fail-closed, isolated
target-runtime fixture used after publication to prove that S-88 revalidates
its live source chain. No credential or report content is printed.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

from sqlalchemy import select

BACKEND = Path(__file__).resolve().parent.parent
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from app.models.wave4 import InternshipReportEvidence
from scripts.seed_wave4_moderation_e2e import assert_isolated_target
from scripts.seed_wave4_risk_labels_e2e import RISK_REPORT_IDS


def invalidate_source(session) -> dict[str, object]:
    source_report_id = RISK_REPORT_IDS[0]
    rows = list(session.scalars(select(InternshipReportEvidence).where(
        InternshipReportEvidence.report_id == source_report_id,
        InternshipReportEvidence.deleted_at.is_(None),
    ).order_by(InternshipReportEvidence.id).with_for_update()))
    if not rows:
        raise RuntimeError("deterministic source evidence is unavailable")
    for row in rows:
        row.scan_state = "infected"
        row.scanner_result_code = "qa_source_invalidation"
    session.commit()
    return {
        "updated_evidence": len(rows),
    }


def main() -> int:
    try:
        assert_isolated_target(
            os.getenv("DATABASE_URL", ""),
            opt_in_env="WAVE4_E2E_ALLOW_SOURCE_INVALIDATION",
        )
        from app.db.session import get_sessionmaker

        with get_sessionmaker()() as session:
            result = invalidate_source(session)
    except Exception:
        print("ERROR: Wave 4 source invalidation fixture was unavailable", file=sys.stderr)
        return 2
    print(json.dumps({"wave4_source_invalidation_e2e": result}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
