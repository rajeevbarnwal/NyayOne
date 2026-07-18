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
  | 'filing_recorded' | 'filing_corrected' | 'milestone_reached' | 'invoice_draft' | 'invoice_approved'
  | 'diary_captured' | 'diary_corrected' | 'diary_confirmed' | 'comm_approved'
  | 'fee_added' | 'fee_paid' | 'fee_manual_review' | 'fee_reversed' | 'fee_refund' | 'fee_adjustment' | 'advance_allocated'
  | 'cnr_captured' | 'cnr_validated' | 'tracking_activated' | 'tracking_refresh' | 'stale_source' | 'manual_fallback'
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
export function addFeeLine(ledger: FeeLedger, line: Omit<FeeLine, 'status' | 'allocations'>): FeeLedger {
  const full: FeeLine = { ...line, status: 'pending', allocations: [] };
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
      caseId: ws.caseId, workspaceId, bundles: [], filing: null, diary: null, fees: emptyLedger(50000), tracking: null, timeline: [], audit: [], updatedAt: Date.now(),
    };
    return this.save(this.log({ ...fw, bundles: [bundle] }, auditEvent('bundle_created', 'lawyer', now, bundle.id)));
  }

  setChecklist(workspaceId: string, key: ChecklistKey, value: boolean, now: string): FilingWorkflow {
    const fw = this.require(workspaceId);
    const b = latestBundle(fw);
    if (!b || b.locked) return fw; // locked bundle is read-only
    const updated: FilingBundle = { ...b, checklist: { ...b.checklist, [key]: value } };
    const bundles = [...fw.bundles.slice(0, -1), updated];
    return this.save(this.log({ ...fw, bundles }, auditEvent('checklist_update', 'lawyer', now, `${key}=${value}`)));
  }

  /** E08 lock: human approval; requires a complete checklist; stores hash + version. */
  lockBundle(workspaceId: string, lawyerId: string, now: string): FilingWorkflow {
    const fw = this.require(workspaceId);
    const b = latestBundle(fw);
    if (!b || b.locked || !checklistComplete(b)) return fw;
    const locked: FilingBundle = { ...b, locked: true, lockedBy: lawyerId, lockedAt: now, hash: bundleHash(b) };
    const bundles = [...fw.bundles.slice(0, -1), locked];
    return this.save(this.log({ ...fw, bundles }, auditEvent('locked', lawyerId, now, locked.hash!), { stage: 'E08', label: 'Filing bundle locked', at: now }));
  }

  /** Editing after lock creates a NEW unlocked version (append-only). */
  editAfterLock(workspaceId: string, now: string): FilingWorkflow {
    const fw = this.require(workspaceId);
    const b = latestBundle(fw);
    if (!b || !b.locked) return fw;
    const next: FilingBundle = {
      ...b, id: `FB-${workspaceId}-${b.versionNo + 1}`, versionNo: b.versionNo + 1,
      locked: false, lockedBy: null, lockedAt: null, hash: null, createdAt: now,
    };
    const logged = this.log(fw, auditEvent('edit_attempt_locked', 'lawyer', now, b.id));
    return this.save(this.log({ ...logged, bundles: [...logged.bundles, next] }, auditEvent('new_version', 'lawyer', now, next.id)));
  }

  /** E09: record a filing event; requires a locked, complete bundle. */
  recordFiling(workspaceId: string, input: Omit<FilingEvent, 'id' | 'bundleId' | 'corrections' | 'milestoneReached' | 'milestonePct' | 'invoiceStatus'>, now: string): FilingWorkflow | null {
    const fw = this.get(workspaceId);
    if (!fw || !canProceedToFiling(fw)) return null; // prerequisite: E08 locked + complete
    const bundle = latestBundle(fw)!;
    const filing: FilingEvent = {
      ...input, id: `FE-${workspaceId}`, bundleId: bundle.id, corrections: [],
      milestoneReached: true, milestonePct: MILESTONE_CASE_FILED_PCT, invoiceStatus: 'draft',
    };
    let next = this.log({ ...fw, filing }, auditEvent('filing_recorded', input.filedBy, now, filing.id), { stage: 'E09', label: 'Filed in court', at: now });
    next = this.log(next, auditEvent('milestone_reached', 'system', now, `Case Filed ${MILESTONE_CASE_FILED_PCT}%`));
    next = this.log(next, auditEvent('invoice_draft', 'system', now));
    return this.save(next);
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
  captureDiary(workspaceId: string, input: Omit<DiaryRecord, 'boundFilingId' | 'officiallyValidated' | 'history'>, now: string): FilingWorkflow | null {
    const fw = this.get(workspaceId);
    if (!fw || !fw.filing) return null; // prerequisite: E09 filing exists
    if (!diaryFormatValid(input.court, input.number)) return null;
    const diary: DiaryRecord = {
      ...input, boundFilingId: fw.filing.id,
      officiallyValidated: input.source === 'authorised_source',
      history: [],
    };
    return this.save(this.log({ ...fw, diary }, auditEvent('diary_captured', 'lawyer', now, diary.number), { stage: 'E10', label: `Diary number ${diary.number}`, at: now }));
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
  addFee(workspaceId: string, line: Omit<FeeLine, 'status' | 'allocations'>, now: string): FilingWorkflow {
    const fw = this.require(workspaceId);
    return this.save(this.log({ ...fw, fees: addFeeLine(fw.fees, line) }, auditEvent('fee_added', 'billing', now, `${line.category}:${line.id}`)));
  }
  payFee(workspaceId: string, ev: FeePaymentEvent, now: string): FilingWorkflow {
    const fw = this.require(workspaceId);
    const { ledger, deduped } = applyFeePayment(fw.fees, ev);
    if (deduped) return fw;
    const line = ledger.lines.find((l) => l.id === ev.lineId);
    const type: FilingAuditType = line?.status === 'paid' ? 'fee_paid' : 'fee_manual_review';
    return this.save(this.log({ ...fw, fees: ledger }, auditEvent(type, 'billing', now, ev.lineId)));
  }
  allocate(workspaceId: string, lineId: string, amount: number, now: string): FilingWorkflow {
    const fw = this.require(workspaceId);
    const fees = allocateAdvance(fw.fees, lineId, amount);
    if (fees === fw.fees) return fw;
    return this.save(this.log({ ...fw, fees }, auditEvent('advance_allocated', 'billing', now, `${lineId}:${amount}`)));
  }

  /** E12: capture CNR; requires E09/E10 identifiers; tracking stays off until validated. */
  captureCnr(workspaceId: string, input: { cnr: string; caseNumber: string; source: string; sourceType: IdentifierSourceType }, now: string): FilingWorkflow | null {
    const fw = this.get(workspaceId);
    if (!fw || (!fw.filing && !fw.diary)) return null; // prerequisite: filing/diary identifiers
    const validated = cnrFormatValid(input.cnr);
    const tracking: TrackingState = {
      cnr: input.cnr, caseNumber: input.caseNumber, source: input.source, sourceType: input.sourceType,
      capturedAt: now, checkedAt: null, validated, trackingEnabled: false,
      courtVerified: input.sourceType === 'authorised', alertsConsent: false, alertsEnabled: false,
    };
    let next = this.log({ ...fw, tracking }, auditEvent('cnr_captured', 'lawyer', now, input.cnr));
    if (validated) next = this.log(next, auditEvent('cnr_validated', 'system', now));
    if (input.sourceType === 'manual') next = this.log(next, auditEvent('manual_fallback', 'lawyer', now));
    return this.save(next);
  }
  /** Activate tracking only after validation; alerts require consent; polling stays off. */
  activateTracking(workspaceId: string, alertsConsent: boolean, now: string): FilingWorkflow {
    const fw = this.require(workspaceId);
    if (!fw.tracking || !fw.tracking.validated) return fw;
    const tracking: TrackingState = { ...fw.tracking, trackingEnabled: true, checkedAt: now, alertsConsent, alertsEnabled: alertsConsent && ECOURTS_POLLING_ENABLED ? true : alertsConsent };
    return this.save(this.log({ ...fw, tracking }, auditEvent('tracking_activated', 'lawyer', now, `alerts=${alertsConsent}`), { stage: 'E12', label: 'Tracking activated', at: now }));
  }

  private require(workspaceId: string): FilingWorkflow {
    const fw = this.get(workspaceId);
    if (!fw) throw new Error(`filing workflow not found: ${workspaceId}`);
    return fw;
  }
}
