/**
 * Practical training / clinical-hours log logic (SAATHI-173 · S12).
 * Category validation, verification states, hours progress, and offline-draft
 * awareness (reuses the shared draft/sync state machine). Logs stay
 * student-controlled until submitted. Pure + testable; no external integrations.
 */
import { canTransition, type DraftState } from '../../../lib/draftQueue';

/** Institution-configurable categories (R1 default set). */
export type ClinicalCategory = 'legal_aid' | 'court' | 'chamber' | 'research';

export const CATEGORY_LABELS: Record<ClinicalCategory, string> = {
  legal_aid: 'Legal-aid',
  court: 'Court',
  chamber: 'Chamber',
  research: 'Research',
};
export const CATEGORY_OPTIONS = Object.keys(CATEGORY_LABELS) as ClinicalCategory[];

export function isValidCategory(v: string): v is ClinicalCategory {
  return (CATEGORY_OPTIONS as string[]).includes(v);
}

export type VerificationStatus = 'draft' | 'submitted' | 'needs_info' | 'verified' | 'rejected';

export interface LogEntry {
  readonly id: string;
  readonly date: string; // yyyy-mm-dd or display
  readonly hours: number;
  readonly activity: string;
  readonly category: ClinicalCategory;
  readonly verifier: string; // email
  readonly evidenceName?: string;
  readonly status: VerificationStatus;
}

export interface LogDraftInput {
  date: string;
  hours: string; // raw form value
  activity: string;
  category: string;
  verifier: string;
}

const EMAIL_RE = /^[^\s@]+@[^\s@]+\.[^\s@]{2,}$/;

/**
 * Validate a log entry. `forSubmit` requires a verifier email; a plain draft can
 * be saved with fewer fields (student-controlled until submitted).
 */
export function validateEntry(d: LogDraftInput, forSubmit = false): Record<string, string> {
  const e: Record<string, string> = {};
  if (!d.date) e.date = 'Enter the date.';
  const hrs = Number(d.hours);
  if (!d.hours.trim() || Number.isNaN(hrs) || hrs <= 0) e.hours = 'Enter hours as a positive number.';
  else if (hrs > 24) e.hours = 'Hours per entry cannot exceed 24.';
  if (!d.activity.trim()) e.activity = 'Describe the activity.';
  if (!isValidCategory(d.category)) e.category = 'Choose a category.';
  if (forSubmit && !EMAIL_RE.test(d.verifier.trim())) e.verifier = 'Enter the faculty verifier’s email to submit.';
  return e;
}

export const TARGET_HOURS = 120;

export function totalHours(entries: readonly LogEntry[]): number {
  return entries.reduce((s, e) => s + e.hours, 0);
}
export function hoursByCategory(entries: readonly LogEntry[]): Record<ClinicalCategory, number> {
  const acc: Record<ClinicalCategory, number> = { legal_aid: 0, court: 0, chamber: 0, research: 0 };
  for (const e of entries) acc[e.category] += e.hours;
  return acc;
}
export function progressPct(entries: readonly LogEntry[], target = TARGET_HOURS): number {
  return Math.min(100, Math.round((totalHours(entries) / target) * 100));
}

export function statusChip(s: VerificationStatus): { kind: 'ok' | 'warn' | 'risk' | 'info'; label: string } {
  switch (s) {
    case 'verified':
      return { kind: 'ok', label: 'Verified' };
    case 'submitted':
      return { kind: 'warn', label: 'Pending faculty' };
    case 'needs_info':
      return { kind: 'warn', label: 'Needs info' };
    case 'rejected':
      return { kind: 'risk', label: 'Rejected' };
    case 'draft':
    default:
      return { kind: 'info', label: 'Draft' };
  }
}

/** Offline-draft awareness reuses the shared sync-queue state machine. */
export function canSyncTransition(from: DraftState, to: DraftState): boolean {
  return canTransition(from, to);
}

export const COMPLIANCE_NOTE =
  'LegalSaathi records and organises your training hours and evidence. Your institution’s approval controls compliance — we do not certify that requirements are met.';
export const EVIDENCE_PRIVACY = 'Evidence shared only with the faculty verifier you choose';

export const SAMPLE_ENTRIES: readonly LogEntry[] = [
  { id: 'l1', date: '28 Jun', hours: 6, activity: 'DLSA legal-aid camp — Anekal taluk', category: 'legal_aid', verifier: 'prof@nls.ac.in', evidenceName: 'camp-letter.pdf', status: 'submitted' },
  { id: 'l2', date: '21 Jun', hours: 4, activity: 'City Civil Court — observation', category: 'court', verifier: 'prof@nls.ac.in', evidenceName: 'cause-list photo', status: 'verified' },
  { id: 'l3', date: '14 Jun', hours: 8, activity: 'Chambers of Sr. Adv. R. Menon', category: 'chamber', verifier: 'prof@nls.ac.in', evidenceName: 'supervisor note', status: 'verified' },
];
