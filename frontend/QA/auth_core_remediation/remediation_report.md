# Independent-QA remediation — SAATHI-2/3/4/16/18

Baseline implementation commit: **61c3361**. All work keeps the 20 tickets in **Testing**.

Note: the independent-QA artifacts under `~/Documents/LegalSaathi/QA/auth_core_independent/` are outside the connected workspace folder, so they could not be opened directly. This remediation is driven by the fully-enumerated blocker spec (A–F) and the Option B v3 prototype notes, which mirror that analysis.

## Blocker → resolution map

| # | Independent-QA blocker | Resolution | Evidence |
|---|---|---|---|
| A | P0.1 exposed only the Bar Council form — incomplete lifecycle | `/auth/lawyer` rebuilt as a full lifecycle on the workbench: entry/register → OTP sent/entry/invalid/expired/resend-cooldown/lockout → DPDP consent → BCI capture → pending/manual_review/rejected(+safe next actions)/verified → restricted workspace while unverified. Shared `otp.ts` reused (TTL/cooldown/attempts/lockout). | `authLifecycle.ts`, `AuthScreens.tsx`; `dev_P0_1_*` shots; interaction PASSes (OTP entry/invalid/lockout/refresh) |
| B | P0.2 exposed only institutional verification | `/auth/student` rebuilt: register → OTP → **explicit affirmative DPDP consent recorded** → institutional-email (preferred) / college-ID→manual_review → pending/rejected(+remediation)/verified + minor **age-gate** with guardian-consent request/pending/accepted/rejected. Reuses student identity/OTP/consent (no parallel system). | `AuthScreens.tsx`, `studentVerify.ts`, `consent.ts`; `dev_P0_2_*` shots; interaction PASSes (consent step, minor gate) |
| C | Option B v3 workbench alignment | 3-panel workbench (`Workbench.tsx` + `.wb-*` tokens): left flow rail with role/state, center action panel, right requirements checklist + timestamped verification ledger/audit + policy notes; degrades < 1024px (rail → chips, ledger → toggle); ls-theme light/dark; 44px; keyboard/focus; no overflow. Rebuilt in React, not copied HTML. | `Workbench.tsx`, `student.css`; `proto_optionB_*` vs `dev_*` shots |
| D | P0.3 was simulation-only | `/auth/security` expanded: active-session + **expiry warning**, refresh success/failure, current-device logout, **logout-all-devices**, per-device revoke, forgot-password/OTP-reset with invalid/expired/locked, successful recovery, re-auth for sensitive actions, unusual-login notice, biometric capability boundary, security audit timeline. | `session.ts` (+`expiryWarning`/`isUnusualLogin`/`revokeAllOtherDevices`), `AuthScreens.tsx`; `sessionUi.test.ts`; QA sweep |
| E | E06 kept versions only in component state | New `DraftWorkspaceService` over a `KvStore` (localStorage/in-memory) persistence boundary: stable case+workspace ids, immutable version ids, append-only history, persisted approval record, latest-approved lookup, reload restoration, export gate, post-approval edit → new unapproved version. | `draftWorkspace.ts` (+test: reload restoration, re-block after edit), `kvStore.ts`, `CaseScreens.tsx` |
| F | Hard-coded `SEED_APPROVED_VERSION = 'v1-approved'` | **Removed.** E07 resolves the real latest lawyer-approved version from the persisted workspace via `ReviewWorkspaceService`; refuses when none exists; session binds immutably to that version id; refresh retains binding; a newer E06 version marks the review stale; comments/approval stay on the original version; client approval ≠ filing approval; expiring/revocable no-PII links; consent-gated adapter notify. | `reviewWorkspace.ts` (+test), `CaseScreens.tsx`; **real browser handoff test** (15/15 incl. same-version-id, stale, comment ownership) |

## Guardrails preserved
Enrolment-status-only; no competence/outcome claims; automation can never clear verification (authorised human override + reason + audit); BCI profile display disabled by default (LCR-002); conservative minor default (restricted until guardian consent verified); explicit DPDP consent **recorded** before processing; no raw OTP/password/token persisted or logged (redacted snapshot + non-reversible fingerprint; verified by test asserting persisted snapshot excludes the code); AI draft content labelled+cited and never filing-ready without lawyer approval; client approval distinct from filing approval.

## Validation
typecheck 0 · lint 0 (0 warnings) · logic 51/51 · backend pytest 35 passed · esbuild production bundle exit 0 (native vite build bus-errors in sandbox) · browser QA 50 responsive checks (5 routes × 5 widths × light/dark) 0 failures + 15 interaction assertions 0 failures.

## Remaining limitations
- Native Vitest / Vite build bus-error in this sandbox (known); validated via esbuild+vitest-shim and an esbuild static bundle served to headless Chromium. Not counted as native passes.
- Prototype reviewer-panel state toggling is not scripted; representative states captured by driving the real app.
- LCR-002 (BCI profile display) and counsel-dependent minor rules remain disabled/conservative by default.
