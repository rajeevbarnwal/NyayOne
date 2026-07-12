/**
 * S18.1 — Private/Anonymous Internship Experience Report
 * (SAATHI-269 / service SAATHI-271).
 *
 * Foundation contract consumed by moderation (SAATHI-274). Privacy is the
 * first-class concern:
 *   - safest privacy default (anonymous); changing exposure needs explicit confirm,
 *   - anonymous presentation NEVER exposes author identity (views, previews, audit),
 *   - evidence is metadata-only (filename/mime/size) — file contents are never
 *     stored or logged here; unsupported type/size is rejected with a typed error,
 *   - submission is idempotent and enters `moderation_pending`,
 *   - reports are user-scoped; cross-user access is refused,
 *   - audit events carry no narrative, identity or evidence content.
 *
 * TCs: TC-269-01 draft+resume · 02 required fields · 03 safest default + confirm ·
 * 04 idempotent submit → moderation_pending · 05 evidence validation · 06 anonymity ·
 * 07 cross-user access refused.
 */
import { defaultKvStore, type KvStore } from '../../../lib/kvStore';

export type ReportCategory =
  | 'unsafe'
  | 'unpaid'
  | 'exploitative'
  | 'stipend_delay'
  | 'harassment'
  | 'misrepresented_role';

export const REPORT_CATEGORIES: readonly ReportCategory[] = [
  'unsafe', 'unpaid', 'exploitative', 'stipend_delay', 'harassment', 'misrepresented_role',
];
export const REPORT_CATEGORY_LABELS: Record<ReportCategory, string> = {
  unsafe: 'Unsafe conditions',
  unpaid: 'Unpaid / withheld pay',
  exploitative: 'Exploitative work',
  stipend_delay: 'Stipend delay',
  harassment: 'Harassment',
  misrepresented_role: 'Misrepresented role',
};

/** anonymous = identity never shown anywhere (safest); attributed = identity to moderators only. */
export type PrivacyMode = 'anonymous' | 'attributed';
export const SAFEST_PRIVACY: PrivacyMode = 'anonymous';

export type ReportStatus = 'draft' | 'moderation_pending';

export interface EvidenceMeta {
  readonly id: string;
  readonly filename: string;
  readonly mimeType: string;
  readonly sizeBytes: number;
}

export interface ReportRecord {
  readonly id: string;
  readonly authorId: string;
  readonly category: ReportCategory | null;
  readonly narrative: string;
  readonly orgRef: string;
  readonly privacyMode: PrivacyMode;
  readonly consent: boolean;
  readonly status: ReportStatus;
  readonly evidence: readonly EvidenceMeta[];
  readonly createdAt: string;
  readonly updatedAt: string;
  readonly submittedAt: string | null;
}

export type ReportAuditType = 'draft_saved' | 'privacy_changed' | 'evidence_added' | 'submitted';
export interface ReportAuditEvent {
  readonly type: ReportAuditType;
  readonly reportId: string;
  readonly at: string;
  // NOTE: deliberately no authorId, narrative, filename or evidence content here.
}

// --- typed errors -----------------------------------------------------------

export type ReportErrorCode =
  | 'not_found'
  | 'forbidden'
  | 'missing_category'
  | 'missing_narrative'
  | 'missing_consent'
  | 'confirm_required'
  | 'evidence_type'
  | 'evidence_size'
  | 'already_submitted';
export class ReportError extends Error {
  readonly code: ReportErrorCode;
  constructor(code: ReportErrorCode, message?: string) {
    super(message ?? code);
    this.name = 'ReportError';
    this.code = code;
  }
}

// --- evidence policy --------------------------------------------------------

export const ALLOWED_EVIDENCE_MIME: readonly string[] = ['image/png', 'image/jpeg', 'application/pdf'];
export const MAX_EVIDENCE_BYTES = 5 * 1024 * 1024; // 5 MB

/** Validate evidence metadata only; contents are never inspected or logged. */
export function validateEvidence(meta: EvidenceMeta): void {
  if (!ALLOWED_EVIDENCE_MIME.includes(meta.mimeType)) {
    throw new ReportError('evidence_type', `unsupported evidence type`);
  }
  if (!(meta.sizeBytes > 0) || meta.sizeBytes > MAX_EVIDENCE_BYTES) {
    throw new ReportError('evidence_size', `evidence exceeds size limit`);
  }
}

// --- validation -------------------------------------------------------------

/** Fields required before a report may be submitted (TC-269-02). */
export function submissionErrors(r: ReportRecord): ReportErrorCode[] {
  const errs: ReportErrorCode[] = [];
  if (!r.category) errs.push('missing_category');
  if (!r.narrative.trim()) errs.push('missing_narrative');
  if (!r.consent) errs.push('missing_consent');
  return errs;
}
export function canSubmit(r: ReportRecord): boolean {
  return submissionErrors(r).length === 0 && r.status === 'draft';
}

// --- privacy-safe views (TC-269-06) -----------------------------------------

export interface PublicReportView {
  readonly id: string;
  readonly category: ReportCategory | null;
  readonly orgRef: string;
  readonly status: ReportStatus;
  readonly submittedAt: string | null;
  readonly evidenceCount: number;
  // no narrative, no author, no filenames.
}

/** Moderation view: identity is included ONLY when the author chose 'attributed'. */
export interface ModerationReportView {
  readonly id: string;
  readonly category: ReportCategory | null;
  readonly narrative: string;
  readonly orgRef: string;
  readonly privacyMode: PrivacyMode;
  readonly status: ReportStatus;
  readonly authorId: string | null; // null when anonymous
  readonly evidence: readonly EvidenceMeta[];
}

export function toPublicView(r: ReportRecord): PublicReportView {
  return {
    id: r.id,
    category: r.category,
    orgRef: r.orgRef,
    status: r.status,
    submittedAt: r.submittedAt,
    evidenceCount: r.evidence.length,
  };
}

export function toModerationView(r: ReportRecord): ModerationReportView {
  return {
    id: r.id,
    category: r.category,
    narrative: r.narrative,
    orgRef: r.orgRef,
    privacyMode: r.privacyMode,
    status: r.status,
    authorId: r.privacyMode === 'attributed' ? r.authorId : null,
    evidence: r.evidence,
  };
}

// --- persistence + service --------------------------------------------------

interface ReportStoreShape {
  readonly reports: Record<string, ReportRecord>;
  readonly audit: readonly ReportAuditEvent[];
}
const key = (userId: string) => `ls-reports-${userId}`;

export interface DraftInput {
  category?: ReportCategory | null;
  narrative?: string;
  orgRef?: string;
}

export class ReportService {
  private store: KvStore;
  private userId: string;
  constructor(userId: string, store: KvStore = defaultKvStore()) {
    this.userId = userId;
    this.store = store;
  }

  private load(): ReportStoreShape {
    return this.store.get<ReportStoreShape>(key(this.userId)) ?? { reports: {}, audit: [] };
  }
  private save(s: ReportStoreShape): void {
    this.store.set(key(this.userId), s);
  }
  private audit(s: ReportStoreShape, type: ReportAuditType, reportId: string, at: string): ReportStoreShape {
    return { ...s, audit: [...s.audit, { type, reportId, at }] };
  }

  /** Create a new draft at the safest privacy default (TC-269-03). */
  createDraft(id: string, at: string, input: DraftInput = {}): ReportRecord {
    const s = this.load();
    const rec: ReportRecord = {
      id,
      authorId: this.userId,
      category: input.category ?? null,
      narrative: input.narrative ?? '',
      orgRef: input.orgRef ?? '',
      privacyMode: SAFEST_PRIVACY,
      consent: false,
      status: 'draft',
      evidence: [],
      createdAt: at,
      updatedAt: at,
      submittedAt: null,
    };
    const next = this.audit({ ...s, reports: { ...s.reports, [id]: rec } }, 'draft_saved', id, at);
    this.save(next);
    return rec;
  }

  /** Save/resume a draft without submitting (TC-269-01). Owner-only (TC-269-07). */
  saveDraft(id: string, patch: DraftInput & { consent?: boolean }, at: string): ReportRecord {
    const s = this.load();
    const rec = this.owned(s, id);
    if (rec.status !== 'draft') throw new ReportError('already_submitted');
    const updated: ReportRecord = {
      ...rec,
      category: patch.category ?? rec.category,
      narrative: patch.narrative ?? rec.narrative,
      orgRef: patch.orgRef ?? rec.orgRef,
      consent: patch.consent ?? rec.consent,
      updatedAt: at,
    };
    const next = this.audit({ ...s, reports: { ...s.reports, [id]: updated } }, 'draft_saved', id, at);
    this.save(next);
    return updated;
  }

  /** Changing exposure away from the safest default requires explicit confirm (TC-269-03). */
  setPrivacy(id: string, mode: PrivacyMode, confirm: boolean, at: string): ReportRecord {
    const s = this.load();
    const rec = this.owned(s, id);
    if (mode !== SAFEST_PRIVACY && !confirm) throw new ReportError('confirm_required');
    const updated = { ...rec, privacyMode: mode, updatedAt: at };
    const next = this.audit({ ...s, reports: { ...s.reports, [id]: updated } }, 'privacy_changed', id, at);
    this.save(next);
    return updated;
  }

  /** Attach evidence metadata; rejects bad type/size and preserves state (TC-269-05). */
  addEvidence(id: string, meta: EvidenceMeta, at: string): ReportRecord {
    const s = this.load();
    const rec = this.owned(s, id);
    validateEvidence(meta); // throws before any mutation
    const updated = { ...rec, evidence: [...rec.evidence, meta], updatedAt: at };
    const next = this.audit({ ...s, reports: { ...s.reports, [id]: updated } }, 'evidence_added', id, at);
    this.save(next);
    return updated;
  }

  /** Submit once → moderation_pending; repeated submit is idempotent (TC-269-04). */
  submit(id: string, at: string): ReportRecord {
    const s = this.load();
    const rec = this.owned(s, id);
    if (rec.status === 'moderation_pending') return rec; // idempotent no-op
    const errs = submissionErrors(rec);
    if (errs.length) throw new ReportError(errs[0]);
    const updated: ReportRecord = { ...rec, status: 'moderation_pending', submittedAt: at, updatedAt: at };
    const next = this.audit({ ...s, reports: { ...s.reports, [id]: updated } }, 'submitted', id, at);
    this.save(next);
    return updated;
  }

  /** Owner-scoped read; returns null when missing or not owned (TC-269-07). */
  get(id: string): ReportRecord | null {
    const s = this.load();
    const rec = s.reports[id];
    if (!rec || rec.authorId !== this.userId) return null;
    return rec;
  }

  listMine(): ReportRecord[] {
    const s = this.load();
    return Object.values(s.reports).filter((r) => r.authorId === this.userId);
  }

  auditLog(): readonly ReportAuditEvent[] {
    return this.load().audit;
  }

  private owned(s: ReportStoreShape, id: string): ReportRecord {
    const rec = s.reports[id];
    if (!rec) throw new ReportError('not_found');
    if (rec.authorId !== this.userId) throw new ReportError('forbidden');
    return rec;
  }
}

export const REPORT_PRIVACY_NOTE =
  'Your report defaults to anonymous. Identity is never shown publicly, and is shared with moderators only if you explicitly choose attributed. Evidence is stored as metadata; do not upload originals you need to keep private.';
export const MODERATION_PENDING_NOTE =
  'Submitted. Your report is in moderation_pending and is not publicly visible until reviewed.';
