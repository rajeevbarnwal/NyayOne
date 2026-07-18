/**
 * Core Filing workflow E08–E12 (SAATHI-20/22/24/26/28).
 *
 * One sequential, persisted workflow that continues the E06/E07 pre-filing flow:
 *   E06/E07 approved draft version
 *     → E08 final locked filing bundle
 *     → E09 filing event
 *     → E10 diary number
 *     → E11 court/process fee ledger
 *     → E12 CNR + tracking activation
 *
 * Each stage loads the ACTUAL persisted output of the previous stage — there are
 * no hard-coded "approved/filed/diary/receipt/CNR" fixtures. Persistence uses the
 * shared KvStore; the approved-draft prerequisite comes from DraftWorkspaceService
 * (E06/E07). Pure helpers are exported for unit testing; FilingWorkflowService
 * wraps persistence + prerequisites + an append-only audit log.
 *
 * Guardrails: internal locking is not court acceptance; filing/diary/CNR are
 * user-entered or authorised-source-derived (never AI-inferred or "officially
 * validated" without an authorised source); payments are receipt-gated,
 * server-authoritative and idempotent; eCourts polling is disabled by default
 * pending LCR-009; GST/reimbursement stays conservative pending LCR-007/008.
 */
import { defaultKvStore, type KvStore } from '../../../lib/kvStore';
import { DraftWorkspaceService } from './draftWorkspace';

// --- shared helpers ----------------------------------------------------------

/** Non-reversible content fingerprint (document hash stand-in; no raw content). */
export function contentHash(input: string): string {
  let h = 2166136261 >>> 0;
  for (let i = 0; i < input.length; i += 1) {
    h ^= input.charCodeAt(i);
    h = Math.imul(h, 16777619) >>> 0;
  }
  return `sha_${h.toString(16)}`;
}

export interface TimelineEvent {
  readonly stage: 'E08' | 'E09' | 'E10' | 'E11' | 'E12';
  readonly label: string;
  readonly at: string;
}
export type FilingAuditType =
  | 'bundle_created' | 'checklist_update' | 'vetted' | 'locked' | 'edit_attempt_locked' | 'new_version' | 'unlock_replace'
  | 'filing_recorded' | 'filing_corrected' | 'milestone_reached' | 'invoice_draft' | 'invoice_approved' | 'proof_uploaded'
  | 'diary_captured' | 'diary_corrected' | 'diary_confirmed' | 'comm_approved' | 'ack_uploaded'
  | 'fee_added' | 'fee_paid' | 'fee_manual_review' | 'fee_reversed' | 'fee_refund' | 'fee_adjustment' | 'advance_allocated' | 'receipt_uploaded'
  | 'cnr_captured' | 'cnr_validated' | 'tracking_activated' | 'tracking_refresh' | 'stale_source' | 'manual_fallback' | 'identifier_fetch_attempt' | 'identifier_manual_update'
  | 'notification_queued' | 'notification_suppressed'
  | 'export_attempt' | 'failure';
export interface FilingAuditEvent {
  readonly type: FilingAuditType;
  readonly actor: string;
  readonly at: string;
  readonly ref?: string;
}
export function auditEvent(type: FilingAuditType, actor: string, at: string, ref?: string): FilingAuditEvent {
  return { type, actor, at, ref };
}

// --- actor / role authorisation (E08 finalize gate) --------------------------
//
// SAATHI-20/434/435: finalising (locking) a filing bundle is a privileged,
// authorised action. It must NOT be granted merely because a caller passed a
// non-empty actor string (the previous behaviour). Authorisation is decided on a
// TYPED role drawn from a fixed enum; only Lawyer / Senior Advocate / Firm
// Partner roles may finalise. Student / client / clerk / unknown / empty actors
// are refused and an auditable failure event is appended.
export const FILING_ACTOR_ROLES = ['lawyer', 'senior_advocate', 'firm_partner', 'associate', 'clerk', 'student', 'client', 'unknown'] as const;
export type FilingActorRole = (typeof FILING_ACTOR_ROLES)[number];
export interface FilingActor {
  readonly id: string;
  readonly role: FilingActorRole;
}
/** Roles permitted to finalise (lock) a filing bundle. */
export const FILING_FINALIZE_ROLES: readonly FilingActorRole[] = ['lawyer', 'senior_advocate', 'firm_partner'];

/**
 * Resolve an actor from either a typed FilingActor or the legacy `"role:id"`
 * actor string. Anything unrecognised, or a bare/empty string, resolves to the
 * `unknown` role — which is never authorised. The authorisation decision is made
 * on the resulting typed role, not on the raw string's presence.
 */
export function parseActor(input: FilingActor | string | null | undefined): FilingActor {
  if (input && typeof input === 'object') {
    const role = (FILING_ACTOR_ROLES as readonly string[]).includes(input.role) ? input.role : 'unknown';
    return { id: (input.id ?? '').trim(), role };
  }
  const raw = typeof input === 'string' ? input.trim() : '';
  if (!raw) return { id: '', role: 'unknown' };
  const [head, ...rest] = raw.split(':');
  const maybeRole = head.trim().toLowerCase();
  if ((FILING_ACTOR_ROLES as readonly string[]).includes(maybeRole)) {
    return { id: rest.join(':').trim() || maybeRole, role: maybeRole as FilingActorRole };
  }
  return { id: raw, role: 'unknown' }; // an un-roled string is never trusted as authorised
}
/** True only for a typed, non-empty actor holding a finalize-capable role. */
export function canFinalize(input: FilingActor | string | null | undefined): boolean {
  const actor = parseActor(input);
  return !!actor.id && FILING_FINALIZE_ROLES.includes(actor.role);
}
/** Safe, non-PII descriptor for audit records. */
export function describeActor(actor: FilingActor): string {
  return actor.id ? `${actor.role}:${actor.id}` : actor.role;
}

// --- internal-task notification stub (E08 dispatch evidence) -----------------
//
// SAATHI-20 scope: locking a bundle queues an INTERNAL task notification stub
// (evidence of dispatch intent — nothing is actually transmitted here). WhatsApp
// is never queued for dispatch unless the lawyer has explicitly configured it;
// by default a suppressed record is written instead.
export type NotificationChannel = 'internal_task' | 'whatsapp';
export type NotificationKind = 'bundle_locked' | 'diary_client_status';
export interface NotificationStub {
  readonly id: string;
  readonly channel: NotificationChannel;
  readonly kind: NotificationKind;
  readonly to: string; // team/role target — never client PII
  readonly queuedAt: string;
  readonly dispatched: boolean; // stub only: true = would dispatch, false = suppressed/pending
  readonly suppressedReason?: string;
}
export interface NotificationConfig {
  readonly whatsappEnabled: boolean;
}
export const DEFAULT_NOTIFICATION_CONFIG: NotificationConfig = { whatsappEnabled: false };
export const WHATSAPP_SUPPRESSED_REASON = 'whatsapp_not_configured';

// --- secure file upload contract (E09/E10/E11 real uploads) ------------------
//
// SAATHI-22/24/26: filing proof, diary acknowledgement and fee receipts are real
// file uploads (not typed references). We validate type/MIME/size/presence and
// persist ONLY safe metadata + an opaque storage reference — never file bytes or
// PII, and never anything in a URL query string.
export const ALLOWED_UPLOAD_MIME = ['application/pdf', 'image/png', 'image/jpeg'] as const;
export type AllowedUploadMime = (typeof ALLOWED_UPLOAD_MIME)[number];
export const ALLOWED_UPLOAD_EXT = ['pdf', 'png', 'jpg', 'jpeg'] as const;
export const MAX_UPLOAD_BYTES = 10 * 1024 * 1024; // 10 MB

export interface UploadInput {
  readonly filename: string;
  readonly mime: string;
  readonly size: number; // bytes
  readonly present: boolean; // a file was actually selected (bytes exist)
}
export interface UploadMeta {
  readonly ref: string; // opaque storage reference (no PII, no URL params)
  readonly filename: string; // display name only
  readonly mime: string;
  readonly size: number;
  readonly uploadedAt: string;
}
export type UploadReason = 'missing' | 'empty' | 'type' | 'size';
export type UploadValidation = { readonly ok: true } | { readonly ok: false; readonly reason: UploadReason };

function fileExt(name: string): string {
  const i = name.lastIndexOf('.');
  return i >= 0 ? name.slice(i + 1).toLowerCase() : '';
}
/** Validate a candidate upload against type/MIME, size and presence rules. */
export function validateUpload(
  input: UploadInput,
  allowedMime: readonly string[] = ALLOWED_UPLOAD_MIME,
  maxBytes: number = MAX_UPLOAD_BYTES,
): UploadValidation {
  if (!input || !input.present || !input.filename) return { ok: false, reason: 'missing' };
  if (input.size <= 0) return { ok: false, reason: 'empty' };
  const mimeOk = allowedMime.includes(input.mime);
  const extOk = (ALLOWED_UPLOAD_EXT as readonly string[]).includes(fileExt(input.filename));
  if (!mimeOk || !extOk) return { ok: false, reason: 'type' };
  if (input.size > maxBytes) return { ok: false, reason: 'size' };
  return { ok: true };
}
export const UPLOAD_ERROR_MESSAGES: Record<UploadReason, string> = {
  missing: 'Select a file to upload.',
  empty: 'The selected file is empty.',
  type: 'Allowed formats: PDF, PNG or JPEG.',
  size: 'File exceeds the 10 MB limit.',
};
/** Build safe persisted metadata + an opaque reference for a validated upload. */
export function makeUploadMeta(input: UploadInput, now: string, seed: string): UploadMeta {
  const ref = `upload_${contentHash(`${seed}|${input.filename}|${input.size}|${now}`)}`;
  return { ref, filename: input.filename, mime: input.mime, size: input.size, uploadedAt: now };
}

// --- E08: final filing bundle -------------------------------------------------

// Jira E08 (SAATHI-20/433/434/435): the vetting checklist must include the
// 'fee readiness' and 'client approval' dimensions alongside document checks.
// Adding them here flows to emptyChecklist, checklistComplete, bundleHash, the
// UI chips (CaseScreens maps CHECKLIST_KEYS) and audit, so the final lock cannot
// complete until every required readiness dimension is satisfied.
export const CHECKLIST_KEYS = ['pleading', 'annexures', 'pagination', 'signatures', 'affidavits', 'vakalatnama', 'metadata', 'fee_readiness', 'client_approval'] as const;
export type ChecklistKey = (typeof CHECKLIST_KEYS)[number];
export const CHECKLIST_LABELS: Record<ChecklistKey, string> = {
  pleading: 'Pleading / petition',
  annexures: 'Annexures attached',
  pagination: 'Pagination',
  signatures: 'Signatures',
  affidavits: 'Affidavits',
  vakalatnama: 'Vakalatnama / authorisation',
  metadata: 'Required metadata',
  fee_readiness: 'Fee readiness',
  client_approval: 'Client approval',
};

export interface FilingBundle {
  readonly id: string;
  readonly versionNo: number;
  readonly sourceDraftVersionId: string; // the real lawyer-approved E06/E07 version
  readonly checklist: Record<ChecklistKey, boolean>;
  readonly annexureOrder: readonly string[];
  readonly locked: boolean;
  readonly lockedBy: string | null;
  readonly lockedAt: string | null;
  readonly hash: string | null;
  readonly createdAt: string;
}

export function emptyChecklist(): Record<ChecklistKey, boolean> {
  return CHECKLIST_KEYS.reduce((acc, k) => ({ ...acc, [k]: false }), {} as Record<ChecklistKey, boolean>);
}
export function checklistComplete(b: FilingBundle): boolean {
  return CHECKLIST_KEYS.every((k) => b.checklist[k]);
}
export function bundleHash(b: FilingBundle): string {
  return contentHash(`${b.sourceDraftVersionId}|${b.versionNo}|${CHECKLIST_KEYS.map((k) => (b.checklist[k] ? 1 : 0)).join('')}|${b.annexureOrder.join(',')}`);
}
export const INTERNAL_LOCK_NOTICE = 'Locking finalises the bundle internally. It is not court acceptance or registration.';
export const AI_NON_BINDING_NOTICE = 'AI vetting suggestions are non-binding; the vetting decision is the lawyer’s.';

// --- E09: filing event --------------------------------------------------------

export type FilingMode = 'e-filing' | 'physical' | 'authorised_source';
export const FILING_MODES: readonly FilingMode[] = ['e-filing', 'physical', 'authorised_source'];
export const MILESTONE_CASE_FILED_PCT = 25;

export interface FilingCorrection { readonly at: string; readonly by: string; readonly field: string; readonly old: string; readonly newValue: string; }
export interface FilingEvent {
  readonly id: string;
  readonly bundleId: string; // the locked E08 bundle
  readonly court: string;
  readonly benchLocation: string;
  readonly filedAt: string;
  readonly mode: FilingMode;
  readonly filedBy: string;
  readonly notes: string;
  readonly proofRef: string; // secure reference; never PII in a URL
  readonly proof: UploadMeta | null; // E09: real uploaded filing-proof document metadata
  readonly corrections: readonly FilingCorrection[];
  readonly milestoneReached: boolean;
  readonly milestonePct: number;
  readonly invoiceStatus: 'draft' | 'approved';
}
export const FILING_NOT_ACCEPTANCE_NOTICE = 'Recording a filing reflects your submission only; it does not assert the court accepted or registered the case.';

// --- E10: diary number --------------------------------------------------------

export type DiarySource = 'manual' | 'authorised_source';
export interface DiaryChange { readonly at: string; readonly by: string; readonly field: string; readonly old: string; readonly newValue: string; readonly reason: string; }
export interface DiaryRecord {
  readonly number: string;
  readonly court: string;
  readonly year: string;
  readonly source: DiarySource;
  readonly receivedDate: string;
  readonly acknowledgementRef: string;
  readonly acknowledgement: UploadMeta | null; // E10: real uploaded acknowledgement document metadata
  readonly boundFilingId: string; // bound to the correct E09 filing event
  readonly officiallyValidated: boolean;
  readonly history: readonly DiaryChange[];
}
/** Format rules keyed by court; validation applies ONLY where a rule is configured. */
export const DIARY_FORMAT_RULES: Record<string, RegExp> = {
  // Example (opt-in): a configured court could require "DDDD/YYYY". Empty by default.
};
export function diaryFormatValid(court: string, value: string): boolean {
  const rule = DIARY_FORMAT_RULES[court];
  return rule ? rule.test(value) : true; // no rule configured → do not pretend to validate
}
export const DIARY_MANUAL_LABEL = 'Manually recorded — not officially validated.';

// --- E11: fee ledger ----------------------------------------------------------

export const FEE_CATEGORIES = ['court_fee', 'process_fee', 'professional_fee', 'reimbursement', 'tax', 'refund', 'adjustment'] as const;
export type FeeCategory = (typeof FEE_CATEGORIES)[number];
export const FEE_CATEGORY_LABELS: Record<FeeCategory, string> = {
  court_fee: 'Court fee', process_fee: 'Process fee', professional_fee: 'Professional fee',
  reimbursement: 'Reimbursement', tax: 'Tax', refund: 'Refund', adjustment: 'Adjustment',
};
export type FeeStatus = 'pending' | 'paid' | 'manual_review';
export interface FeeAllocation { readonly advanceId: string; readonly amount: number; }
export interface FeeLine {
  readonly id: string;
  readonly category: FeeCategory;
  readonly amount: number;
  readonly payer: string;
  readonly payee: string;
  readonly date: string;
  readonly mode: string;
  readonly status: FeeStatus;
  readonly receiptRef: string | null;
  readonly receipt: UploadMeta | null; // E11: real uploaded receipt metadata for this line
  readonly allocations: readonly FeeAllocation[];
}
export interface FeeLedger {
  readonly lines: readonly FeeLine[];
  readonly advanceBalance: number;
  readonly seenRefs: readonly string[]; // idempotency of payment events
  readonly statement: 'pending' | 'paid' | 'refunded';
}
export const GST_ENABLED = false; // pending LCR-007/LCR-008 (CA review)
export const GST_REVIEW_NOTICE = 'GST/SAC and reimbursement classification are pending CA review (LCR-007/008) and disabled by default.';

export function emptyLedger(advanceBalance = 0): FeeLedger {
  return { lines: [], advanceBalance, seenRefs: [], statement: 'pending' };
}
export function addFeeLine(ledger: FeeLedger, line: Omit<FeeLine, 'status' | 'allocations' | 'receipt'>): FeeLedger {
  const full: FeeLine = { ...line, status: 'pending', allocations: [], receipt: null };
  return { ...ledger, lines: [...ledger.lines, full] };
}
export interface FeePaymentEvent { readonly lineId: string; readonly providerRef: string; readonly serverVerified: boolean; readonly receiptRef?: string; }
/**
 * Apply a payment event to a fee line. Server-authoritative + idempotent: a line
 * becomes 'paid' ONLY when the event is server-verified AND a receipt is present;
 * an unverified event routes to manual_review; duplicate provider refs are no-ops.
 * (Mirrors the billing.applyPaymentEvent idempotency pattern.)
 */
export function applyFeePayment(ledger: FeeLedger, ev: FeePaymentEvent): { ledger: FeeLedger; deduped: boolean } {
  if (ledger.seenRefs.includes(ev.providerRef)) return { ledger, deduped: true };
  const seenRefs = [...ledger.seenRefs, ev.providerRef];
  const lines = ledger.lines.map((l) => {
    if (l.id !== ev.lineId) return l;
    if (l.status === 'paid') return l;
    const receiptRef = ev.receiptRef ?? l.receiptRef;
    if (ev.serverVerified && receiptRef) return { ...l, status: 'paid' as FeeStatus, receiptRef };
    return { ...l, status: 'manual_review' as FeeStatus, receiptRef };
  });
  return { ledger: { ...ledger, lines, seenRefs }, deduped: false };
}
/** Manual bank transfer: paid only on explicit verification AND a receipt. */
export function applyManualFeeVerification(ledger: FeeLedger, lineId: string, verified: boolean): FeeLedger {
  const lines = ledger.lines.map((l) => {
    if (l.id !== lineId) return l;
    if (verified && l.receiptRef) return { ...l, status: 'paid' as FeeStatus };
    return { ...l, status: 'manual_review' as FeeStatus };
  });
  return { ...ledger, lines };
}
/** Allocate advance to a line; prevents over-allocation and negative balance. */
export function allocateAdvance(ledger: FeeLedger, lineId: string, amount: number): FeeLedger {
  if (amount <= 0) return ledger;
  const line = ledger.lines.find((l) => l.id === lineId);
  if (!line) return ledger;
  const already = line.allocations.reduce((s, a) => s + a.amount, 0);
  if (already + amount > line.amount) return ledger; // no double/over allocation
  if (amount > ledger.advanceBalance) return ledger; // no negative balance
  const lines = ledger.lines.map((l) => (l.id === lineId ? { ...l, allocations: [...l.allocations, { advanceId: 'ADV', amount }] } : l));
  return { ...ledger, lines, advanceBalance: ledger.advanceBalance - amount };
}
export function receiptGatedPaidOk(line: FeeLine): boolean {
  return line.status !== 'paid' || !!line.receiptRef;
}

// E11 (SAATHI-26/442/444): a complete client statement showing EVERY fee line and
// its client-facing state (pending / paid / refunded), keeping the five fee
// categories distinct. `manual_review` is surfaced to the client as 'pending'
// (payment not yet confirmed); refund/adjustment categories read as 'refunded'.
export type StatementLineStatus = 'pending' | 'paid' | 'refunded';
export interface ClientStatementLine {
  readonly id: string;
  readonly category: FeeCategory;
  readonly categoryLabel: string;
  readonly amount: number;
  readonly status: StatementLineStatus;
  readonly receiptPresent: boolean;
  readonly allocatedFromAdvance: number;
}
export interface ClientStatement {
  readonly lines: readonly ClientStatementLine[];
  readonly totalsByCategory: Record<FeeCategory, number>;
  /** Gross billed across non-refund/adjustment lines. */
  readonly totalBilled: number;
  /** Receipt-gated amount actually marked paid. */
  readonly totalPaid: number;
  /** Advance applied to billed lines (reduces the client's pending shortfall). */
  readonly advanceApplied: number;
  /** Remaining shortfall the client must still pay: billed − paid − advance applied. */
  readonly totalPending: number;
  readonly totalRefunded: number;
  readonly advanceBalance: number;
}
export function statementLineStatus(line: FeeLine): StatementLineStatus {
  if (line.category === 'refund' || line.category === 'adjustment') return 'refunded';
  return line.status === 'paid' ? 'paid' : 'pending';
}
/**
 * SAATHI-26/442/444 fix: pending must account for advance allocated to a line.
 * For each billed (non-refund/adjustment) line:
 *   - paid line → contributes its amount to paid, 0 to pending;
 *   - pending line → contributes max(0, amount − allocatedFromAdvance) to pending.
 * Refund/adjustment lines are reported separately and excluded from billed/pending.
 */
export function buildClientStatement(ledger: FeeLedger): ClientStatement {
  const totalsByCategory = FEE_CATEGORIES.reduce(
    (acc, c) => ({ ...acc, [c]: 0 }),
    {} as Record<FeeCategory, number>,
  );
  let totalBilled = 0, totalPaid = 0, totalPending = 0, totalRefunded = 0, advanceApplied = 0;
  const lines = ledger.lines.map((l): ClientStatementLine => {
    const status = statementLineStatus(l);
    const allocated = l.allocations.reduce((s, a) => s + a.amount, 0);
    totalsByCategory[l.category] += l.amount;
    if (status === 'refunded') {
      totalRefunded += l.amount;
    } else {
      totalBilled += l.amount;
      advanceApplied += allocated;
      if (status === 'paid') {
        totalPaid += l.amount;
      } else {
        totalPending += Math.max(0, l.amount - allocated); // advance reduces the shortfall
      }
    }
    return {
      id: l.id,
      category: l.category,
      categoryLabel: FEE_CATEGORY_LABELS[l.category],
      amount: l.amount,
      status,
      receiptPresent: !!l.receipt || !!l.receiptRef,
      allocatedFromAdvance: allocated,
    };
  });
  return { lines, totalsByCategory, totalBilled, totalPaid, advanceApplied, totalPending, totalRefunded, advanceBalance: ledger.advanceBalance };
}

// --- E12: CNR + tracking ------------------------------------------------------

export type IdentifierSourceType = 'manual' | 'authorised';
export interface TrackingState {
  readonly cnr: string;
  readonly caseNumber: string;
  readonly source: string;
  readonly sourceType: IdentifierSourceType;
  readonly capturedAt: string;
  readonly checkedAt: string | null;
  readonly validated: boolean;
  readonly trackingEnabled: boolean;
  readonly courtVerified: boolean;
  readonly alertsConsent: boolean;
  readonly alertsEnabled: boolean;
}
export const ECOURTS_POLLING_ENABLED = false; // pending LCR-009 + authorised TOS review
export const CNR_RE = /^[A-Z]{4}\d{6,8}\d{4}$/i; // representative CNR shape; not court-universal
export function cnrFormatValid(cnr: string): boolean {
  return cnr.trim() === '' ? false : CNR_RE.test(cnr.replace(/[-\s]/g, ''));
}
export const CNR_MANUAL_NOTICE = 'Manually entered — not court-verified. Court polling is disabled pending TOS/legal review (LCR-009).';

// E12 (SAATHI-28/445/447): when automated identifier capture is unavailable or
// the captured identifier fails validation, the workflow must expose actionable
// fallback actions (retry automated fetch, then manual entry/edit). Automated
// fetch stays disabled by default pending LCR-009, so a retry returns an
// actionable manual-entry instruction rather than silently failing.
export type IdentifierFetchReason = 'polling_disabled' | 'not_found' | 'unavailable';
export interface IdentifierFetchResult {
  readonly ok: false;
  readonly reason: IdentifierFetchReason;
  readonly message: string;
}
export const IDENTIFIER_FETCH_DISABLED: IdentifierFetchResult = {
  ok: false,
  reason: 'polling_disabled',
  message: 'Automated court fetch is disabled pending TOS/legal review (LCR-009). Please enter the CNR/case number manually below.',
};
/** Retry entry point for automated capture. Disabled by default → manual fallback. */
export function attemptAutomatedIdentifierFetch(): IdentifierFetchResult {
  return IDENTIFIER_FETCH_DISABLED;
}
/** Freshness age in ms (Infinity when never checked). */
export function trackingAgeMs(t: TrackingState, now: number): number {
  return t.checkedAt ? now - Date.parse(t.checkedAt) : Infinity;
}
export function trackingStale(t: TrackingState, now: number, maxAgeMs = 24 * 60 * 60 * 1000): boolean {
  return trackingAgeMs(t, now) > maxAgeMs;
}

// --- persisted workflow record + service -------------------------------------

export interface FilingWorkflow {
  readonly caseId: string;
  readonly workspaceId: string;
  readonly bundles: readonly FilingBundle[]; // append-only E08 versions
  readonly filing: FilingEvent | null;
  readonly diary: DiaryRecord | null;
  readonly fees: FeeLedger;
  readonly tracking: TrackingState | null;
  readonly timeline: readonly TimelineEvent[];
  readonly audit: readonly FilingAuditEvent[];
  readonly notifications: readonly NotificationStub[]; // E08 dispatch-evidence stubs
  readonly notifyConfig: NotificationConfig; // WhatsApp off unless lawyer-configured
  readonly updatedAt: number;
}

const fwKey = (workspaceId: string) => `ls-filing-${workspaceId}`;

export function latestBundle(fw: FilingWorkflow): FilingBundle | null {
  return fw.bundles.length ? fw.bundles[fw.bundles.length - 1] : null;
}
export function canProceedToFiling(fw: FilingWorkflow): boolean {
  const b = latestBundle(fw);
  return !!b && b.locked && checklistComplete(b);
}

export class FilingWorkflowService {
  constructor(
    private store: KvStore = defaultKvStore(),
    private drafts: DraftWorkspaceService = new DraftWorkspaceService(store),
  ) {}

  private save(fw: FilingWorkflow): FilingWorkflow {
    const next = { ...fw, updatedAt: Date.now() };
    this.store.set(fwKey(fw.workspaceId), next);
    return next;
  }
  private log(fw: FilingWorkflow, e: FilingAuditEvent, tl?: TimelineEvent): FilingWorkflow {
    return { ...fw, audit: [...fw.audit, e], timeline: tl ? [...fw.timeline, tl] : fw.timeline };
  }

  get(workspaceId: string): FilingWorkflow | null {
    return this.store.get<FilingWorkflow>(fwKey(workspaceId));
  }
  /** Resolve the current workspace (handed over from E06/E07 via setCurrent). */
  currentWorkspaceId(): string | null {
    return this.drafts.getCurrent();
  }

  /** E08: initialise the bundle from the REAL latest lawyer-approved draft version. */
  initBundle(workspaceId: string, now: string): FilingWorkflow | null {
    const approved = this.drafts.latestApprovedVersion(workspaceId);
    if (!approved) return null; // no approved E06/E07 version → cannot finalise
    const existing = this.get(workspaceId);
    if (existing && latestBundle(existing)) return existing;
    const ws = this.drafts.get(workspaceId)!;
    const bundle: FilingBundle = {
      id: `FB-${workspaceId}-1`, versionNo: 1, sourceDraftVersionId: approved.id,
      checklist: emptyChecklist(), annexureOrder: [], locked: false, lockedBy: null, lockedAt: null, hash: null, createdAt: now,
    };
    const fw: FilingWorkflow = existing ?? {
      caseId: ws.caseId, workspaceId, bundles: [], filing: null, diary: null, fees: emptyLedger(50000), tracking: null, timeline: [], audit: [],
      notifications: [], notifyConfig: DEFAULT_NOTIFICATION_CONFIG, updatedAt: Date.now(),
    };
    return this.save(this.log({ ...fw, bundles: [bundle] }, auditEvent('bundle_created', 'lawyer', now, bundle.id)));
  }

  setChecklist(workspaceId: string, key: ChecklistKey, value: boolean, now: string, actor?: FilingActor): FilingWorkflow {
    const fw = this.require(workspaceId);
    const b = latestBundle(fw);
    if (!b || b.locked) return fw; // locked bundle is read-only
    const updated: FilingBundle = { ...b, checklist: { ...b.checklist, [key]: value } };
    const bundles = [...fw.bundles.slice(0, -1), updated];
    return this.save(this.log({ ...fw, bundles }, auditEvent('checklist_update', this.who(actor, 'lawyer'), now, `${key}=${value}`)));
  }

  /** Configure notification channels (WhatsApp off unless the lawyer opts in). */
  configureNotifications(workspaceId: string, cfg: Partial<NotificationConfig>, now: string, actor?: FilingActor): FilingWorkflow {
    const fw = this.require(workspaceId);
    const notifyConfig: NotificationConfig = { ...(fw.notifyConfig ?? DEFAULT_NOTIFICATION_CONFIG), ...cfg };
    return this.save(this.log({ ...fw, notifyConfig }, auditEvent('comm_approved', this.who(actor, 'lawyer'), now, `whatsapp=${notifyConfig.whatsappEnabled}`)));
  }

  /**
   * E08 lock: privileged human approval. Authorisation is decided on a TYPED
   * actor role — only Lawyer / Senior Advocate / Firm Partner may finalise. A
   * complete nine-dimension checklist is required. Refusals (unauthorised actor,
   * incomplete checklist, missing bundle) append an auditable `failure` event and
   * leave bundle state unchanged. A successful lock stores hash + version, appends
   * the `locked` audit, and queues the internal-task notification stub (WhatsApp
   * only if the lawyer configured it).
   */
  lockBundle(workspaceId: string, actorInput: FilingActor | string, now: string): FilingWorkflow {
    const fw = this.require(workspaceId);
    const actor = parseActor(actorInput);
    const b = latestBundle(fw);
    if (!b) {
      return this.save(this.log(fw, auditEvent('failure', describeActor(actor), now, 'lock_refused:no_bundle')));
    }
    if (b.locked) return fw; // idempotent: already finalised, not a failure
    if (!canFinalize(actor)) {
      // unauthorised actor — refuse without changing bundle state
      return this.save(this.log(fw, auditEvent('failure', describeActor(actor), now, 'lock_refused:unauthorised_actor')));
    }
    if (!checklistComplete(b)) {
      return this.save(this.log(fw, auditEvent('failure', describeActor(actor), now, 'lock_refused:incomplete_checklist')));
    }
    const locked: FilingBundle = { ...b, locked: true, lockedBy: describeActor(actor), lockedAt: now, hash: bundleHash(b) };
    const bundles = [...fw.bundles.slice(0, -1), locked];
    let next = this.log({ ...fw, bundles }, auditEvent('locked', describeActor(actor), now, locked.hash!), { stage: 'E08', label: 'Filing bundle locked', at: now });
    next = this.queueLockNotifications(next, actor, now);
    return this.save(next);
  }

  /** Queue the internal-task notification stub; WhatsApp is suppressed unless configured. */
  private queueLockNotifications(fw: FilingWorkflow, actor: FilingActor, now: string): FilingWorkflow {
    const cfg = fw.notifyConfig ?? DEFAULT_NOTIFICATION_CONFIG;
    const internal: NotificationStub = {
      id: `NT-${fw.workspaceId}-internal-${(fw.notifications?.length ?? 0) + 1}`,
      channel: 'internal_task', kind: 'bundle_locked', to: 'filing_team', queuedAt: now, dispatched: false,
    };
    let next = this.log({ ...fw, notifications: [...(fw.notifications ?? []), internal] }, auditEvent('notification_queued', describeActor(actor), now, 'internal_task:bundle_locked'));
    if (cfg.whatsappEnabled) {
      const wa: NotificationStub = {
        id: `NT-${fw.workspaceId}-whatsapp-${(next.notifications?.length ?? 0) + 1}`,
        channel: 'whatsapp', kind: 'bundle_locked', to: 'client_channel', queuedAt: now, dispatched: false,
      };
      next = this.log({ ...next, notifications: [...next.notifications, wa] }, auditEvent('notification_queued', describeActor(actor), now, 'whatsapp:bundle_locked'));
    } else {
      next = this.log(next, auditEvent('notification_suppressed', describeActor(actor), now, `whatsapp:${WHATSAPP_SUPPRESSED_REASON}`));
    }
    return next;
  }

  /** Editing after lock creates a NEW unlocked version (append-only). */
  editAfterLock(workspaceId: string, now: string, actor?: FilingActor): FilingWorkflow {
    const fw = this.require(workspaceId);
    const b = latestBundle(fw);
    if (!b || !b.locked) return fw;
    const next: FilingBundle = {
      ...b, id: `FB-${workspaceId}-${b.versionNo + 1}`, versionNo: b.versionNo + 1,
      locked: false, lockedBy: null, lockedAt: null, hash: null, createdAt: now,
    };
    const logged = this.log(fw, auditEvent('edit_attempt_locked', this.who(actor, 'lawyer'), now, b.id));
    return this.save(this.log({ ...logged, bundles: [...logged.bundles, next] }, auditEvent('new_version', this.who(actor, 'lawyer'), now, next.id)));
  }

  /** E09: record a filing event; requires a locked, complete bundle. */
  recordFiling(workspaceId: string, input: Omit<FilingEvent, 'id' | 'bundleId' | 'proof' | 'corrections' | 'milestoneReached' | 'milestonePct' | 'invoiceStatus'>, now: string, actor?: FilingActor): FilingWorkflow | null {
    const fw = this.get(workspaceId);
    if (!fw || !canProceedToFiling(fw)) return null; // prerequisite: E08 locked + complete
    const bundle = latestBundle(fw)!;
    const filing: FilingEvent = {
      ...input, id: `FE-${workspaceId}`, bundleId: bundle.id, proof: null, corrections: [],
      milestoneReached: true, milestonePct: MILESTONE_CASE_FILED_PCT, invoiceStatus: 'draft',
    };
    let next = this.log({ ...fw, filing }, auditEvent('filing_recorded', this.who(actor, input.filedBy), now, filing.id), { stage: 'E09', label: 'Filed in court', at: now });
    next = this.log(next, auditEvent('milestone_reached', 'system', now, `Case Filed ${MILESTONE_CASE_FILED_PCT}%`));
    next = this.log(next, auditEvent('invoice_draft', 'system', now));
    return this.save(next);
  }
  /**
   * E09: attach a REAL uploaded filing-proof document. Validates type/MIME/size/
   * presence; on success persists only safe metadata + opaque ref (no bytes/PII);
   * on failure appends an audit failure and returns the reason without mutating
   * the filing. Requires an existing filing event.
   */
  attachFilingProof(workspaceId: string, input: UploadInput, now: string, actor?: FilingActor): { fw: FilingWorkflow; validation: UploadValidation } {
    const fw = this.require(workspaceId);
    if (!fw.filing) return { fw, validation: { ok: false, reason: 'missing' } };
    const validation = validateUpload(input);
    if (!validation.ok) {
      return { fw: this.save(this.log(fw, auditEvent('failure', this.who(actor, 'lawyer'), now, `proof_upload_rejected:${validation.reason}`))), validation };
    }
    const proof = makeUploadMeta(input, now, `${fw.filing.id}-proof`);
    const filing: FilingEvent = { ...fw.filing, proof, proofRef: proof.ref };
    return { fw: this.save(this.log({ ...fw, filing }, auditEvent('proof_uploaded', this.who(actor, 'lawyer'), now, proof.ref))), validation };
  }
  approveFilingInvoice(workspaceId: string, approver: string, now: string): FilingWorkflow {
    const fw = this.require(workspaceId);
    if (!fw.filing) return fw;
    return this.save(this.log({ ...fw, filing: { ...fw.filing, invoiceStatus: 'approved' } }, auditEvent('invoice_approved', approver, now)));
  }
  correctFiling(workspaceId: string, field: string, newValue: string, by: string, now: string): FilingWorkflow {
    const fw = this.require(workspaceId);
    if (!fw.filing) return fw;
    const old = String((fw.filing as unknown as Record<string, unknown>)[field] ?? '');
    const filing: FilingEvent = { ...fw.filing, [field]: newValue, corrections: [...fw.filing.corrections, { at: now, by, field, old, newValue }] } as FilingEvent;
    return this.save(this.log({ ...fw, filing }, auditEvent('filing_corrected', by, now, field)));
  }

  /** E10: capture the diary number; requires an E09 filing; binds to it. */
  captureDiary(workspaceId: string, input: Omit<DiaryRecord, 'boundFilingId' | 'acknowledgement' | 'officiallyValidated' | 'history'>, now: string, actor?: FilingActor): FilingWorkflow | null {
    const fw = this.get(workspaceId);
    if (!fw || !fw.filing) return null; // prerequisite: E09 filing exists
    if (!diaryFormatValid(input.court, input.number)) return null;
    const diary: DiaryRecord = {
      ...input, boundFilingId: fw.filing.id,
      acknowledgement: null,
      officiallyValidated: input.source === 'authorised_source',
      history: [],
    };
    return this.save(this.log({ ...fw, diary }, auditEvent('diary_captured', this.who(actor, 'lawyer'), now, diary.number), { stage: 'E10', label: `Diary number ${diary.number}`, at: now }));
  }
  /**
   * E10: attach a REAL uploaded acknowledgement document to the diary record.
   * Validates type/MIME/size/presence; persists only safe metadata + opaque ref.
   * Does not alter the official-validation flag (manual capture stays
   * "not officially validated"). Requires an existing diary record.
   */
  attachDiaryAcknowledgement(workspaceId: string, input: UploadInput, now: string, actor?: FilingActor): { fw: FilingWorkflow; validation: UploadValidation } {
    const fw = this.require(workspaceId);
    if (!fw.diary) return { fw, validation: { ok: false, reason: 'missing' } };
    const validation = validateUpload(input);
    if (!validation.ok) {
      return { fw: this.save(this.log(fw, auditEvent('failure', this.who(actor, 'lawyer'), now, `ack_upload_rejected:${validation.reason}`))), validation };
    }
    const acknowledgement = makeUploadMeta(input, now, `${fw.diary.number}-ack`);
    const diary: DiaryRecord = { ...fw.diary, acknowledgement, acknowledgementRef: acknowledgement.ref };
    return { fw: this.save(this.log({ ...fw, diary }, auditEvent('ack_uploaded', this.who(actor, 'lawyer'), now, acknowledgement.ref))), validation };
  }
  /**
   * E10 (SAATHI-24/439/441): optional client status update, gated on explicit
   * lawyer approval.
   *  - Default (never called) → no notification is queued (suppressed).
   *  - Only a finalize-capable lawyer actor may approve; anyone else is refused
   *    with a `failure` audit and NOTHING is queued.
   *  - On approval, a single privacy-safe internal-task stub is queued (no PII in
   *    the id/target) with `comm_approved` + `notification_queued` audit.
   *  - Idempotent: repeated approval does not duplicate the queued item.
   * Requires a valid diary record.
   */
  approveDiaryClientStatus(workspaceId: string, actor: FilingActor | string, now: string): FilingWorkflow {
    const fw = this.require(workspaceId);
    const a = parseActor(actor);
    if (!fw.diary) {
      return this.save(this.log(fw, auditEvent('failure', describeActor(a), now, 'diary_notify_refused:no_diary')));
    }
    if (!canFinalize(a)) {
      return this.save(this.log(fw, auditEvent('failure', describeActor(a), now, 'diary_notify_refused:unauthorised_actor')));
    }
    const already = (fw.notifications ?? []).some((n) => n.kind === 'diary_client_status');
    if (already) return fw; // idempotent: no duplicate queue item
    const stub: NotificationStub = {
      id: `NT-${fw.workspaceId}-diary-${(fw.notifications?.length ?? 0) + 1}`,
      channel: 'internal_task', kind: 'diary_client_status', to: 'client_channel', queuedAt: now, dispatched: false,
    };
    let next = this.log({ ...fw, notifications: [...(fw.notifications ?? []), stub] }, auditEvent('comm_approved', describeActor(a), now, 'diary_client_status'));
    next = this.log(next, auditEvent('notification_queued', describeActor(a), now, 'internal_task:diary_client_status'));
    return this.save(next);
  }
  /** Whether a client-status notification has been approved + queued (UI helper). */
  diaryClientStatusQueued(fw: FilingWorkflow): boolean {
    return (fw.notifications ?? []).some((n) => n.kind === 'diary_client_status');
  }
  /** Correction appends to history (old value preserved), never overwrites it. */
  correctDiary(workspaceId: string, newNumber: string, reason: string, by: string, now: string): FilingWorkflow {
    const fw = this.require(workspaceId);
    if (!fw.diary) return fw;
    const change: DiaryChange = { at: now, by, field: 'number', old: fw.diary.number, newValue: newNumber, reason };
    const diary: DiaryRecord = { ...fw.diary, number: newNumber, history: [...fw.diary.history, change] };
    return this.save(this.log({ ...fw, diary }, auditEvent('diary_corrected', by, now, reason)));
  }

  /** E11: fee ledger operations (persisted). */
  addFee(workspaceId: string, line: Omit<FeeLine, 'status' | 'allocations' | 'receipt'>, now: string, actor?: FilingActor): FilingWorkflow {
    const fw = this.require(workspaceId);
    return this.save(this.log({ ...fw, fees: addFeeLine(fw.fees, line) }, auditEvent('fee_added', this.who(actor, 'billing'), now, `${line.category}:${line.id}`)));
  }
  payFee(workspaceId: string, ev: FeePaymentEvent, now: string, actor?: FilingActor): FilingWorkflow {
    const fw = this.require(workspaceId);
    const { ledger, deduped } = applyFeePayment(fw.fees, ev);
    if (deduped) return fw;
    const line = ledger.lines.find((l) => l.id === ev.lineId);
    const type: FilingAuditType = line?.status === 'paid' ? 'fee_paid' : 'fee_manual_review';
    return this.save(this.log({ ...fw, fees: ledger }, auditEvent(type, this.who(actor, 'billing'), now, ev.lineId)));
  }
  allocate(workspaceId: string, lineId: string, amount: number, now: string, actor?: FilingActor): FilingWorkflow {
    const fw = this.require(workspaceId);
    const fees = allocateAdvance(fw.fees, lineId, amount);
    if (fees === fw.fees) return fw;
    return this.save(this.log({ ...fw, fees }, auditEvent('advance_allocated', this.who(actor, 'billing'), now, `${lineId}:${amount}`)));
  }
  /**
   * E11: attach a REAL uploaded receipt to a specific fee line. Validates
   * type/MIME/size/presence; persists only safe metadata + opaque ref and sets
   * the line's receiptRef. Does NOT itself mark the line paid — paid status
   * remains server-verification + receipt gated and idempotent via payFee.
   */
  attachFeeReceipt(workspaceId: string, lineId: string, input: UploadInput, now: string, actor?: FilingActor): { fw: FilingWorkflow; validation: UploadValidation } {
    const fw = this.require(workspaceId);
    const target = fw.fees.lines.find((l) => l.id === lineId);
    if (!target) return { fw, validation: { ok: false, reason: 'missing' } };
    const validation = validateUpload(input);
    if (!validation.ok) {
      return { fw: this.save(this.log(fw, auditEvent('failure', this.who(actor, 'billing'), now, `receipt_upload_rejected:${lineId}:${validation.reason}`))), validation };
    }
    const receipt = makeUploadMeta(input, now, `${lineId}-receipt`);
    const lines = fw.fees.lines.map((l) => (l.id === lineId ? { ...l, receipt, receiptRef: receipt.ref } : l));
    return { fw: this.save(this.log({ ...fw, fees: { ...fw.fees, lines } }, auditEvent('receipt_uploaded', this.who(actor, 'billing'), now, `${lineId}:${receipt.ref}`))), validation };
  }
  /** E11: derive the complete client statement (every line + totals) for display. */
  clientStatement(workspaceId: string): ClientStatement | null {
    const fw = this.get(workspaceId);
    return fw ? buildClientStatement(fw.fees) : null;
  }

  /** E12: capture CNR; requires E09/E10 identifiers; tracking stays off until validated. */
  captureCnr(workspaceId: string, input: { cnr: string; caseNumber: string; source: string; sourceType: IdentifierSourceType }, now: string, actor?: FilingActor): FilingWorkflow | null {
    const fw = this.get(workspaceId);
    if (!fw || (!fw.filing && !fw.diary)) return null; // prerequisite: filing/diary identifiers
    const validated = cnrFormatValid(input.cnr);
    const tracking: TrackingState = {
      cnr: input.cnr, caseNumber: input.caseNumber, source: input.source, sourceType: input.sourceType,
      capturedAt: now, checkedAt: null, validated, trackingEnabled: false,
      courtVerified: input.sourceType === 'authorised', alertsConsent: false, alertsEnabled: false,
    };
    let next = this.log({ ...fw, tracking }, auditEvent('cnr_captured', this.who(actor, 'lawyer'), now, input.cnr));
    if (validated) next = this.log(next, auditEvent('cnr_validated', 'system', now));
    if (input.sourceType === 'manual') next = this.log(next, auditEvent('manual_fallback', this.who(actor, 'lawyer'), now));
    return this.save(next);
  }
  /** Activate tracking only after validation; alerts require consent; polling stays off. */
  activateTracking(workspaceId: string, alertsConsent: boolean, now: string, actor?: FilingActor): FilingWorkflow {
    const fw = this.require(workspaceId);
    if (!fw.tracking || !fw.tracking.validated) return fw;
    const tracking: TrackingState = { ...fw.tracking, trackingEnabled: true, checkedAt: now, alertsConsent, alertsEnabled: alertsConsent && ECOURTS_POLLING_ENABLED ? true : alertsConsent };
    return this.save(this.log({ ...fw, tracking }, auditEvent('tracking_activated', this.who(actor, 'lawyer'), now, `alerts=${alertsConsent}`), { stage: 'E12', label: 'Tracking activated', at: now }));
  }

  /**
   * E12 fallback: attempt an automated court fetch. Disabled by default pending
   * LCR-009, so this records an audited attempt and returns an actionable result
   * that directs the lawyer to the manual-entry fallback. It never enables
   * scraping/polling.
   */
  attemptIdentifierFetch(workspaceId: string, now: string, actor?: FilingActor): { fw: FilingWorkflow; result: IdentifierFetchResult } {
    const fw = this.require(workspaceId);
    const result = attemptAutomatedIdentifierFetch();
    return { fw: this.save(this.log(fw, auditEvent('identifier_fetch_attempt', this.who(actor, 'lawyer'), now, result.reason))), result };
  }
  /**
   * E12 fallback: manually enter/edit the CNR + case number after a failed or
   * invalid automated capture. Re-validates, preserves source/freshness metadata,
   * keeps court-verified false (manual is not court-verified) and appends audit
   * history. Requires an existing tracking record (from captureCnr).
   */
  manualUpdateIdentifier(workspaceId: string, input: { cnr: string; caseNumber: string; source?: string }, now: string, actor?: FilingActor): FilingWorkflow {
    const fw = this.require(workspaceId);
    if (!fw.tracking) return fw;
    const validated = cnrFormatValid(input.cnr);
    const tracking: TrackingState = {
      ...fw.tracking,
      cnr: input.cnr,
      caseNumber: input.caseNumber,
      source: input.source ?? 'manual entry',
      sourceType: 'manual',
      capturedAt: now,
      validated,
      courtVerified: false,
      // a failed re-entry must not leave stale tracking enabled
      trackingEnabled: fw.tracking.trackingEnabled && validated,
    };
    let next = this.log({ ...fw, tracking }, auditEvent('identifier_manual_update', this.who(actor, 'lawyer'), now, input.cnr));
    next = this.log(next, auditEvent('manual_fallback', this.who(actor, 'lawyer'), now, validated ? 'valid' : 'invalid'));
    if (validated) next = this.log(next, auditEvent('cnr_validated', 'system', now));
    return this.save(next);
  }

  /** Audit actor label: the session-bound actor when supplied, else a role fallback. */
  private who(actor: FilingActor | undefined, fallback: string): string {
    return actor ? describeActor(actor) : fallback;
  }

  private require(workspaceId: string): FilingWorkflow {
    const fw = this.get(workspaceId);
    if (!fw) throw new Error(`filing workflow not found: ${workspaceId}`);
    return fw;
  }
}
