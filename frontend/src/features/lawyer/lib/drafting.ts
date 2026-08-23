/**
 * Plaint / petition drafting logic (SAATHI-16 · Core E06).
 *
 * Pure, testable domain logic for the drafting workspace inside the Case module.
 * Draft history is APPEND-ONLY: each edit creates a new immutable version with a
 * stable id. Machine-generated (AI-assisted) content is clearly flagged and must
 * carry source citations.
 *
 * Guardrails (load-bearing):
 *  - Drafting-agent output is a DRAFT, not legal advice or final filing content.
 *  - A human (verified) lawyer must approve a version before it can be exported
 *    for filing. AI content can NEVER silently become final/filing-ready.
 *  - All versions and comments are preserved (immutable history).
 *  - The drafting agent is a local stub/adapter (no external LLM call here).
 */

export const AI_DRAFT_LABEL = 'Machine-generated draft — verify every citation and fact before relying on it.';

export interface MatterFacts {
  readonly parties: string;
  readonly reliefs: string;
  readonly jurisdiction: string;
  readonly limitationNote: string;
  readonly sections: string;
  readonly issues: string;
  readonly documentLinks: readonly string[];
}

export const EMPTY_MATTER_FACTS: MatterFacts = {
  parties: '',
  reliefs: '',
  jurisdiction: '',
  limitationNote: '',
  sections: '',
  issues: '',
  documentLinks: [],
};

export type FieldErrors = Record<string, string>;
export function validateMatterFacts(f: MatterFacts): FieldErrors {
  const e: FieldErrors = {};
  if (!f.parties.trim()) e.parties = 'Enter the parties (plaintiff / defendant).';
  if (!f.reliefs.trim()) e.reliefs = 'Enter the relief(s) sought.';
  if (!f.jurisdiction.trim()) e.jurisdiction = 'Enter the court / jurisdiction.';
  return e;
}

/** A source citation with source-version traceability (verify before reliance). */
export interface SourceCitation {
  readonly n: number;
  readonly title: string;
  readonly ref: string;
  readonly sourceVersion: string; // e.g. "as amended 2023" — supports S-55 traceability
}

export interface DraftVersion {
  readonly id: string;
  readonly versionNo: number;
  readonly authorId: string;
  readonly createdAt: string;
  readonly changeNote: string;
  readonly body: string;
  readonly aiGenerated: boolean;
  readonly citations: readonly SourceCitation[];
}

export interface NewVersionInput {
  readonly authorId: string;
  readonly createdAt: string;
  readonly changeNote: string;
  readonly body: string;
  readonly aiGenerated: boolean;
  readonly citations?: readonly SourceCitation[];
}

/** Append a new immutable version. Prior versions are never mutated or dropped. */
export function addVersion(history: readonly DraftVersion[], input: NewVersionInput): DraftVersion[] {
  const versionNo = history.length + 1;
  const version: DraftVersion = {
    id: `v${versionNo}-${input.createdAt}`,
    versionNo,
    authorId: input.authorId,
    createdAt: input.createdAt,
    changeNote: input.changeNote,
    body: input.body,
    aiGenerated: input.aiGenerated,
    citations: input.citations ? [...input.citations] : [],
  };
  return [...history, version];
}

export function latestVersion(history: readonly DraftVersion[]): DraftVersion | null {
  return history.length ? history[history.length - 1] : null;
}
export function versionById(history: readonly DraftVersion[], id: string): DraftVersion | null {
  return history.find((v) => v.id === id) ?? null;
}

export interface ApprovalRecord {
  readonly versionId: string;
  readonly approvedBy: string; // verified lawyer id
  readonly approvedAt: string;
}

/** Approve a specific version (append-only approval log). */
export function approveVersion(approvals: readonly ApprovalRecord[], versionId: string, lawyerId: string, now: string): ApprovalRecord[] {
  if (approvals.some((a) => a.versionId === versionId)) return [...approvals];
  return [...approvals, { versionId, approvedBy: lawyerId, approvedAt: now }];
}

export function isVersionApproved(approvals: readonly ApprovalRecord[], versionId: string): boolean {
  return approvals.some((a) => a.versionId === versionId);
}

/**
 * Export-for-filing is allowed ONLY when the LATEST version is approved. Adding a
 * newer version after approval re-blocks export until that version is approved —
 * so AI/edited content can never silently reach a filing-ready state.
 */
export function canExportForFiling(history: readonly DraftVersion[], approvals: readonly ApprovalRecord[]): boolean {
  const latest = latestVersion(history);
  if (!latest) return false;
  return isVersionApproved(approvals, latest.id);
}
export const isFilingReady = canExportForFiling;

/** True when the latest version is AI-generated and not yet approved. */
export function aiContentAwaitingApproval(history: readonly DraftVersion[], approvals: readonly ApprovalRecord[]): boolean {
  const latest = latestVersion(history);
  return !!latest && latest.aiGenerated && !isVersionApproved(approvals, latest.id);
}

// --- Drafting assistant (adapter boundary; local stub only) ------------------

export interface DraftingAssistant {
  /** NO network here. Produces a labelled draft body + citations from facts. */
  generate(facts: MatterFacts, template: string): { body: string; citations: SourceCitation[] };
}

export function createStubDraftingAssistant(): DraftingAssistant {
  return {
    generate(facts, template) {
      const body =
        `[${template}]\n\nIN THE COURT OF ${facts.jurisdiction || '<court>'}\n\n` +
        `Parties: ${facts.parties || '<parties>'}\n` +
        `Reliefs sought: ${facts.reliefs || '<reliefs>'}\n` +
        `Provisions: ${facts.sections || '<sections>'}\n` +
        `Issues: ${facts.issues || '<issues>'}\n` +
        `Limitation: ${facts.limitationNote || '<limitation>'}\n`;
      const citations: SourceCitation[] = [
        { n: 1, title: 'Code of Civil Procedure, 1908', ref: 'Order VII Rule 1', sourceVersion: 'as amended' },
      ];
      return { body, citations };
    },
  };
}

// --- Audit -------------------------------------------------------------------

export type DraftAuditType =
  | 'draft_created'
  | 'draft_revised'
  | 'reviewed'
  | 'approved'
  | 'rejected'
  | 'export_attempt'
  | 'export_blocked'
  | 'failure';

export interface DraftAuditEvent {
  readonly type: DraftAuditType;
  readonly versionId: string;
  readonly actor: string;
  readonly timestamp: string;
}
export function draftAuditEvent(type: DraftAuditType, versionId: string, actor: string, now: string): DraftAuditEvent {
  return { type, versionId, actor, timestamp: now };
}

export const DRAFT_TEMPLATES: readonly string[] = [
  'Plaint — civil suit (Order VII)',
  'Writ petition — Article 226',
  'Consumer complaint',
  'Application — interlocutory',
];

export const SAMPLE_MATTER_FACTS: MatterFacts = {
  parties: 'Acme Textiles Pvt Ltd (Plaintiff) v. Sunrise Builders (Defendant)',
  reliefs: 'Recovery of ₹12,00,000 with interest; costs',
  jurisdiction: 'City Civil Court, Bengaluru',
  limitationNote: 'Cause of action arose 12 Mar 2024; within limitation',
  sections: 'Order VII Rule 1 CPC; Section 34 CPC',
  issues: 'Whether the agreement dated 12 Mar 2024 was breached',
  documentLinks: ['case://NYAY-CASE-2026-014/doc/agreement'],
};
