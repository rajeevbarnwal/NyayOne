# Wave 2 — State Inventory (S-31–S-35)

**82 named states**, identical across Options A/B/C (one shared deterministic engine, three visual systems). **No new canonical screen IDs** — every entry is a named state/overlay inside S-31…S-35, per the frozen screen-ownership rule. Reach any state via **Reviewer → All states** or the stable URL flag `#/<screen>?state=<id>` (append `&baseline=1` to hide reviewer tooling for screenshots).

| # | State ID | Canonical screen | State | Status |
|---|---|---|---|---|
| 1 | `s31-default` | S-31 | Tutor discovery — results | Built (A·B·C) |
| 2 | `s31-filtered` | S-31 | Discovery — filtered | Built (A·B·C) |
| 3 | `s31-empty` | S-31 | Discovery — empty result | Built (A·B·C) |
| 4 | `s32-profile` | S-32 | Tutor profile | Built (A·B·C) |
| 5 | `s32-availability` | S-32 | Profile — availability (available/held/booked) | Built (A·B·C) |
| 6 | `s33-summary` | S-33 | Order summary + slot | Built (A·B·C) |
| 7 | `s33-hold` | S-33 | Active 10-min hold (live countdown) | Built (A·B·C) |
| 8 | `s33-hold-urgent` | S-33 | Hold under 2 min — non-colour urgency | Built (A·B·C) |
| 9 | `s33-card` | S-33 | Card entry (hosted-field treatment) | Built (A·B·C) |
| 10 | `s33-testhelper` | S-33 | Deterministic test-card helper | Built (A·B·C) |
| 11 | `s33-validation` | S-33 | Card form validation errors | Built (A·B·C) |
| 12 | `s33-otp` | S-33 | Payment OTP / 3-DS challenge | Built (A·B·C) |
| 13 | `s33-otp-resent` | S-33 | OTP resent (counter + expiry) | Built (A·B·C) |
| 14 | `s33-otp-wrong` | S-33 | OTP incorrect (attempts left) | Built (A·B·C) |
| 15 | `s33-otp-locked` | S-33 | OTP locked after 3 attempts | Built (A·B·C) |
| 16 | `s33-processing` | S-33 | Processing — awaiting provider | Built (A·B·C) |
| 17 | `s33-success` | S-33 | Success (server-verified event) | Built (A·B·C) |
| 18 | `s33-declined` | S-33 | Card declined | Built (A·B·C) |
| 19 | `s33-provider-down` | S-33 | Provider unavailable | Built (A·B·C) |
| 20 | `s33-cancelled` | S-33 | User cancelled payment | Built (A·B·C) |
| 21 | `s33-hold-expired` | S-33 | Hold expired — slot released | Built (A·B·C) |
| 22 | `s33-duplicate` | S-33 | Duplicate submit — idempotent replay | Built (A·B·C) |
| 23 | `s33-retry` | S-33 | Safe retry (no double charge) | Built (A·B·C) |
| 24 | `s33-back-warning` | S-33 | Back-navigation warning during hold | Built (A·B·C) |
| 25 | `s34-confirmed` | S-34 | Booking confirmed + receipt | Built (A·B·C) |
| 26 | `s34-pending` | S-34 | Pending provider verification (not confirmed) | Built (A·B·C) |
| 27 | `s34-join-early` | S-34 | Join disabled before window | Built (A·B·C) |
| 28 | `s34-join-open` | S-34 | Join window open | Built (A·B·C) |
| 29 | `s34-reminders` | S-34 | Reminder schedule | Built (A·B·C) |
| 30 | `s34-receipt` | S-34 | Receipt / reference detail | Built (A·B·C) |
| 31 | `s35-upcoming` | S-35 | Upcoming session management | Built (A·B·C) |
| 32 | `s35-policy` | S-35 | Policy preview before action | Built (A·B·C) |
| 33 | `s35-cancel-eligible` | S-35 | Cancel ≥24h — full refund | Built (A·B·C) |
| 34 | `s35-cancel-late` | S-35 | Cancel <24h — admin exception | Built (A·B·C) |
| 35 | `s35-tutor-cancelled` | S-35 | Tutor cancelled — full refund | Built (A·B·C) |
| 36 | `s35-reschedule` | S-35 | Free reschedule — slot pick | Built (A·B·C) |
| 37 | `s35-confirm-modal` | S-35 | Destructive confirmation modal | Built (A·B·C) |
| 38 | `s35-refund-requested` | S-35 | Refund requested | Built (A·B·C) |
| 39 | `s35-refund-processing` | S-35 | Refund processing | Built (A·B·C) |
| 40 | `s35-refund-succeeded` | S-35 | Refund succeeded | Built (A·B·C) |
| 41 | `s35-refund-failed` | S-35 | Refund failed — retry | Built (A·B·C) |
| 42 | `s35-refund-review` | S-35 | Refund — manual review | Built (A·B·C) |
| 43 | `s35-conflict` | S-35 | Stale action / concurrent change | Built (A·B·C) |
| 44 | `s35-already-started` | S-35 | Session already started/ended | Built (A·B·C) |
| 45 | `s35-offline` | S-35 | Offline / provider failure — safe retry | Built (A·B·C) |
| 46 | `s35-prejoin` | S-35 | Pre-join identity + device test entry | Built (A·B·C) |
| 47 | `s35-devices` | S-35 | Device check — preview + selectors | Built (A·B·C) |
| 48 | `s35-perm-cam` | S-35 | Camera permission denied | Built (A·B·C) |
| 49 | `s35-perm-mic` | S-35 | Microphone denied | Built (A·B·C) |
| 50 | `s35-perm-pending` | S-35 | Permission dismissed / pending | Built (A·B·C) |
| 51 | `s35-no-device` | S-35 | No camera/microphone found | Built (A·B·C) |
| 52 | `s35-device-busy` | S-35 | Device busy / in use | Built (A·B·C) |
| 53 | `s35-unsupported` | S-35 | Unsupported browser | Built (A·B·C) |
| 54 | `s35-insecure` | S-35 | Insecure origin | Built (A·B·C) |
| 55 | `s35-constraint` | S-35 | Media constraint failure | Built (A·B·C) |
| 56 | `s35-join-early-v` | S-35 | Join too early | Built (A·B·C) |
| 57 | `s35-pay-unverified` | S-35 | Payment not verified | Built (A·B·C) |
| 58 | `s35-token-expired` | S-35 | Join credential expired | Built (A·B·C) |
| 59 | `s35-wrong-user` | S-35 | Wrong user / cross-user access | Built (A·B·C) |
| 60 | `s35-ended` | S-35 | Session already ended | Built (A·B·C) |
| 61 | `s35-room-waiting` | S-35 | Room — waiting for tutor | Built (A·B·C) |
| 62 | `s35-room-live` | S-35 | Room — live (tutor + student) | Built (A·B·C) |
| 63 | `s35-room-muted` | S-35 | Room — participant muted | Built (A·B·C) |
| 64 | `s35-room-camoff` | S-35 | Room — camera off | Built (A·B·C) |
| 65 | `s35-autoplay` | S-35 | Audio autoplay blocked | Built (A·B·C) |
| 66 | `s35-remote-missing` | S-35 | Remote track unavailable | Built (A·B·C) |
| 67 | `s35-degraded` | S-35 | Degraded network | Built (A·B·C) |
| 68 | `s35-reconnecting` | S-35 | Reconnecting | Built (A·B·C) |
| 69 | `s35-icefail` | S-35 | ICE/TURN failure — full reconnect | Built (A·B·C) |
| 70 | `s35-tutor-left` | S-35 | Tutor left | Built (A·B·C) |
| 71 | `s35-leave-confirm` | S-35 | Leave confirmation | Built (A·B·C) |
| 72 | `s35-post` | S-35 | Post-session (tracks released) | Built (A·B·C) |
| 73 | `s35-att-pending` | S-35 | Attendance pending (after end) | Built (A·B·C) |
| 74 | `s35-att-marked` | S-35 | Attendance marked by tutor | Built (A·B·C) |
| 75 | `s35-att-confirm` | S-35 | Student confirmed attendance | Built (A·B·C) |
| 76 | `s35-att-dispute` | S-35 | Student dispute + reason | Built (A·B·C) |
| 77 | `s35-att-resolution` | S-35 | Pending admin resolution | Built (A·B·C) |
| 78 | `s35-att-resolved` | S-35 | Dispute resolved | Built (A·B·C) |
| 79 | `s35-att-errors` | S-35 | Typed attendance errors (early/dup/unauth/stale) | Built (A·B·C) |
| 80 | `s35-review-blocked` | S-35 | Review locked (no attendance) | Built (A·B·C) |
| 81 | `s35-review-open` | S-35 | Review form (1–5★, 10–1,000 chars) | Built (A·B·C) |
| 82 | `s35-review-done` | S-35 | Review submitted | Built (A·B·C) |

Notes: `s33-hold` runs the live 10-minute countdown (other s33 states pin deterministic remaining values for stable screenshots); duplicate/refusal/idempotent states mutate nothing; refund/attendance states are explicit and durable (URL-addressable, survive reload); every device/permission state has a recovery action; `s35-post` asserts all local tracks are stopped.