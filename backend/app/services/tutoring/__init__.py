"""Wave 2 tutoring domain services (SAATHI-123 / SAATHI-127 P2).

Module map (import these directly; this package intentionally imports NOTHING at
package-import time so the ``payments`` <-> ``sessions`` cycle stays resolvable):

======================  =====================================================
module                  responsibility
======================  =====================================================
``errors``              typed domain errors carrying stable machine codes
``availability``        read-only tutor discovery, slots, UTC/IANA + DST policy
``booking``             atomic slot holds, TTL enforcement, sweeper
``payments``            orders, verified webhook application, refund policy
``sessions``            session lifecycle: create / read / reschedule / cancel
``attendance``          record (after end only) / confirm / dispute / resolve
``reviews``             create / edit / delete / moderate / public aggregate
``join_credentials``    hash-only video join grants + verified room webhooks (P3)
``reminders``           7d / 1d / 3h jobs, revocation, due-job enqueue
``outbox_relay``        durable transactional outbox + post-commit dispatch
``seed``                deterministic local seed (no network, no scraping)
======================  =====================================================

Shared conventions every module in this package obeys:

* **No service commits.** A service writes rows (business + audit + outbox) in
  the CALLER's transaction and returns a result object whose ``intents`` list
  must be handed to :func:`app.services.tutoring.outbox_relay.run_delivery`
  AFTER the caller commits. Dispatch therefore cannot happen for a change that
  was rolled back.
* **Typed errors only.** Every failure is an ``errors.TutoringError`` subclass;
  no bare ``ValueError`` and no ``HTTPException`` below the API layer.
* **Money is integer paise, INR only.** No floats anywhere.
* **Instants are UTC**; the IANA zone is retained alongside for rendering.
"""
from __future__ import annotations

__all__ = [
    "attendance",
    "availability",
    "booking",
    "errors",
    "join_credentials",
    "outbox_relay",
    "payments",
    "reminders",
    "reviews",
    "seed",
    "sessions",
]
