# Core Filing E08–E12 — proposed canonical prototypes (v1)

**Status: PROPOSED — not approved.** These are reference screens submitted for Product/Design
approval. Functional QA on the implemented screens has passed; the mandatory visual-regression
gate remains **blocked** until this reference set is explicitly approved by the user / Product /
Design. Creating this artifact does **not** approve it.

Stories: SAATHI-20 (E08), SAATHI-22 (E09), SAATHI-24 (E10), SAATHI-26 (E11), SAATHI-28 (E12).
Implementation commit: `10124f3`. Design system: Option J v3.2 “Chambers Intelligence Studio”.

---

## 1. How to review

Open `index.html` for the cover + device-frame gallery (desktop 1440 · tablet 768 · mobile 390,
side by side, with a light/dark toggle that persists to `ls-theme` like the app). Each story’s full
screen file stacks every canonical state and is itself fully responsive, so resizing the browser is
an equivalent way to inspect the three breakpoints.

The token set and component classes in `chambers.css` are lifted verbatim from the shipped app
(`frontend/src/styles/{tokens,global,student}.css`) and the primitives in
`frontend/src/components/ui/primitives.tsx` / `frontend/src/features/student/components.tsx`, so the
reference renders match the build rather than a parallel visual language.

## 2. Design read (direction, dials, intent)

- **Direction:** Clean Chambers (light-default) with the single Chambers-green accent
  (`--accent #1f4a37` light / `#6cb493` dark). Dark is a pure token swap. One direction, not blended.
- **Dials:** Density calm-to-medium; Motion still (reduced-motion honoured); Variance safe — this is a
  canonical reference that must match the implemented workflow, not a reinvention.
- **Screen intent (one job, one primary action each):** E08 lock the vetted bundle · E09 record the
  filing · E10 capture the diary number · E11 record court/process fee · E12 capture CNR + activate tracking.

Typography: Newsreader (serif) for titles, Hanken Grotesk for UI/body, JetBrains Mono for
data/metadata and eyebrows — the shipped stack. Hero/section titles use `.st-h1` (Newsreader 1.75rem/500).
Status is never colour-only: every `.status` pairs a glyph (`✓ ! ✕ i`) + text label.

## 3. Files

| File | Purpose |
|---|---|
| `index.html` | Cover, approval-gate banner, route map, device-frame gallery, theme broadcaster |
| `chambers.css` | Shared tokens + component classes (verbatim from the app) |
| `shell.js` | Theme toggle → `ls-theme` persistence; accepts theme broadcast from the gallery |
| `screens/e08_finalize.html` | E08 — all 8 states |
| `screens/e09_filing.html` | E09 — all 5 states |
| `screens/e10_diary.html` | E10 — all 5 states |
| `screens/e11_fees.html` | E11 — all 6 states |
| `screens/e12_tracking.html` | E12 — all 6 states |
| `README.md` | This document (inventory, rationale, a11y checklist, traceability) |
| `state_inventory.json` | Machine-readable screen/state inventory |
| `traceability_matrix.json` | Machine-readable AC → state map |
| `qa/prototype_qa_report.json` | Playwright prototype-QA results |
| `qa/*.png` | Desktop + mobile captures, light + dark |

## 4. Screen / state inventory

Each state renders at 1440 / 768 / 390 in both light and dark.

**E08 — Vet & lock final filing version** (`/case/finalize`, SAATHI-20)
1. `E08-S1` Missing approved-draft prerequisite (blocked)
2. `E08-S2` Loading approved bundle
3. `E08-S3` Vetting checklist incomplete (lock disabled + validation)
4. `E08-S4` Ready to lock (all items complete)
5. `E08-S5` Locked / read-only bundle (hash + audit footnote)
6. `E08-S6` Edit after lock → new version + version/hash history
7. `E08-S8` Error (hash/persist failure) with retry

**E09 — Record court filing** (`/case/filing`, SAATHI-22)
1. `E09-S1` Missing locked bundle (E08) — blocked
2. `E09-S2` Filing form (court/date/mode/proof/notes) + “recording ≠ court acceptance” notice
3. `E09-S3` Recorded filing · Case Filed 25% milestone · invoice draft
4. `E09-S4` Milestone invoice approved
5. `E09-S5` Validation — required proof missing

**E10 — Capture diary number** (`/case/diary`, SAATHI-24)
1. `E10-S1` Missing recorded filing (E09) — blocked
2. `E10-S2` Diary capture — manual vs authorised source
3. `E10-S3` Manually-recorded result + header/timeline + append-only correction history
4. `E10-S4` Authorised-source result (validated label)
5. `E10-S5` Client status notification — consent + lawyer approval

**E11 — Court & process fee** (`/case/fees`, SAATHI-26)
1. `E11-S1` Missing recorded filing (E09) — blocked
2. `E11-S2` Add fee line + GST/SAC disabled pending review (LCR-007/008)
3. `E11-S3` Typed ledger — court fee ≠ process fee · paid / pending / manual-review
4. `E11-S4` Receipt-required validation (cannot mark paid)
5. `E11-S5` Advance allocation (no double / negative balance)
6. `E11-S6` Refund / adjustment / reversal lines

**E12 — CNR & activate tracking** (`/case/tracking`, SAATHI-28)
1. `E12-S1` Missing filing/diary identifiers — blocked
2. `E12-S2` Capture CNR / case number — manual vs authorised source
3. `E12-S3` Invalid identifier format (recordable; tracking stays off)
4. `E12-S4` Manual capture — source + freshness · tracking disabled · eCourts TOS-off
5. `E12-S5` Tracking active (authorised, validated, consent on)
6. `E12-S6` Stale source (freshness warning + manual fallback)

## 5. Design rationale

The Core lawyer module previously had no v3.2 design of its own, which is exactly why the
visual-regression gate was blocked. Rather than invent a new look, this set treats the shipped
Option J tokens and student-module primitives as the design authority and applies them to the
filing workflow: chambers rail + command bar on desktop, bottom nav on mobile, `st-panel` cards on
an 8-pt grid, one primary action per screen, and a single accent.

Legal-credibility is load-bearing here, so the compliance posture is visible in the UI, not buried:
the internal-lock-≠-court-acceptance, filing-≠-acceptance, manually-recorded, GST-pending
(LCR-007/008) and eCourts-polling-off (LCR-009) notices all render as `ui-notice` bands, and every
manual or unverified value carries a warn/`i` badge instead of an unqualified “verified” claim.
Money uses ₹ + `en-IN` grouping and tabular mono figures. Court fee and process fee are always
distinct ledger categories, never merged. Prerequisite gating is shown as a first-class blocked
state on every dependent screen so the sequential E06→E12 flow reads clearly.

## 6. Accessibility checklist

- [x] Light + dark both delivered via token swap; WCAG AA target contrast in both.
- [x] Desktop + tablet + mobile layouts for every screen (rail → bottom nav at ≤768).
- [x] Tap targets ≥ 44px (`.btn/.tap/.st-chip/.st-toggle/.st-input/select` all `min-height:var(--tap-min)`).
- [x] Visible focus ring on every focusable control (`:focus-visible` 2px `--focus`).
- [x] State never colour-only — glyph + label on all `.status`, `ui-validation`, `ui-notice`.
- [x] Real, specific copy — no lorem ipsum; notices quote the shipped guardrail strings.
- [x] Tabular mono numerals for identifiers, hashes, amounts, timestamps.
- [x] Empty / loading / error / validation / blocked-prerequisite states present.
- [x] `aria-invalid` + `aria-describedby` on invalid fields; `role="alert"` on validation/error; `aria-busy` on loading.
- [x] `aria-pressed` on toggles/chips; `aria-disabled` mirrors `disabled` on gated actions.
- [x] Safe-area insets honoured (topbar/bottom-nav use `env(safe-area-inset-*)`); no horizontal overflow at any width.
- [x] `prefers-reduced-motion` respected globally.

## 7. Acceptance-criteria traceability

Full matrix in `traceability_matrix.json`. Summary:

| Story | Acceptance criterion | Prototype state(s) |
|---|---|---|
| E08 | Vetting checklist (draft, annexures, fee readiness, client approval) | E08-S3, E08-S4 |
| E08 | Final bundle stored with hash + version ID | E08-S5, E08-S6 |
| E08 | Case advances only after checklist completion | E08-S1, E08-S3, E08-S5 |
| E09 | Filing entry captures court, date, mode, proof, notes | E09-S2 |
| E09 | Timeline shows File-in-Court stage complete | E09-S3 |
| E09 | Milestone engine checks Case Filed 25% trigger (+ approval-gated invoice) | E09-S3, E09-S4 |
| E10 | Diary number appears in case header and timeline | E10-S3, E10-S4 |
| E10 | User can attach court receipt / acknowledgement | E10-S2 |
| E10 | Change history preserves old and new values | E10-S3 |
| E11 | Ledger distinguishes professional / court / process / reimbursement / tax | E11-S2, E11-S3 |
| E11 | Receipt upload linked to the fee line item | E11-S3, E11-S4 |
| E11 | Client statement reflects paid / pending / refunded | E11-S3, E11-S5, E11-S6 |
| E12 | Case header shows CNR with source + last-updated timestamp | E12-S4, E12-S5 |
| E12 | Court-data polling enabled only after identifier validation | E12-S4, E12-S5 |
| E12 | Errors show fallback / manual update route | E12-S3, E12-S6 |

## 8. Not yet done (owned by approval)

The final developed-vs-prototype visual-regression comparison (the <2% diff gate) is **not** run
here — it runs only after this reference is approved. Until then all 20 issues stay in **Testing**.
