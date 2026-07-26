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

/* -------------------------------------------------------------------------- */
/* Evidence verification workflow + export (S12.2 / S12.3)                      */
/* -------------------------------------------------------------------------- */

export type StepState = 'done' | 'now' | 'todo';
export interface WorkflowStep {
  readonly label: string;
  readonly detail: string;
  readonly state: StepState;
}

/** 3-step verification workflow derived from the entry's status. */
export function verificationSteps(status: VerificationStatus): WorkflowStep[] {
  const loggedDone = true; // evidence attached before entering the workflow
  const verified = status === 'verified';
  const rejected = status === 'rejected' || status === 'needs_info';
  return [
    { label: 'Logged & evidence attached', detail: 'by you', state: 'done' },
    {
      label: rejected ? 'Faculty review — needs info' : 'Faculty review',
      detail: verified ? 'reviewed' : 'awaiting verifier',
      state: verified ? 'done' : loggedDone ? 'now' : 'todo',
    },
    {
      label: 'Verified & counted',
      detail: 'institution confirms compliance',
      state: verified ? 'done' : 'todo',
    },
  ];
}

export interface ExportSummary {
  readonly totalHours: number;
  readonly target: number;
  readonly entries: number;
  readonly verifiedEntries: number;
  readonly verifiedHours: number;
  readonly progressPct: number;
}

export function exportSummary(entries: readonly LogEntry[], target = TARGET_HOURS): ExportSummary {
  const verified = entries.filter((e) => e.status === 'verified');
  const total = totalHours(entries);
  return {
    totalHours: total,
    target,
    entries: entries.length,
    verifiedEntries: verified.length,
    verifiedHours: totalHours(verified),
    progressPct: Math.min(100, Math.round((total / target) * 100)),
  };
}

export type ExportFormat = 'pdf' | 'csv' | 'institution';

export interface ClinicalExportOptions {
  readonly includesEvidence: boolean;
  readonly reauthenticated: boolean;
  readonly generatedAt: string;
}

export interface ClinicalExportPayload {
  readonly format: ExportFormat;
  readonly fileName: string;
  readonly mimeType: string;
  readonly content: string;
  readonly generatedAt: string;
  readonly includesEvidence: boolean;
  readonly entryCount: number;
  readonly source: 'LegalSaathi self-maintained clinical log';
}

export interface ClinicalExportAuditEvent {
  readonly eventId: string;
  readonly action: 'clinical_hours_exported';
  readonly format: ExportFormat;
  readonly generatedAt: string;
  readonly includesEvidence: boolean;
  readonly entryCount: number;
}

function csvCell(value: string | number): string {
  const text = String(value);
  return /[",\n]/.test(text) ? `"${text.replace(/"/g, '""')}"` : text;
}

function exportRows(entries: readonly LogEntry[], includeEvidence: boolean) {
  return entries.map((entry) => ({
    date: entry.date,
    hours: entry.hours,
    activity: entry.activity,
    category: CATEGORY_LABELS[entry.category],
    status: statusChip(entry.status).label,
    ...(includeEvidence ? { evidence: entry.evidenceName ?? '' } : {}),
    // Verifier identity is deliberately excluded from every export format.
  }));
}

function pdfSafe(text: string): string {
  return text.normalize('NFKD').replace(/[^\x20-\x7E]/g, '-').replace(/([\\()])/g, '\\$1');
}

/** Small standards-valid single-page PDF generator for the browser prototype. */
function simplePdf(lines: readonly string[]): string {
  const commands = ['BT', '/F1 9 Tf', '40 800 Td'];
  for (const [index, line] of lines.slice(0, 48).entries()) {
    if (index > 0) commands.push('0 -14 Td');
    commands.push(`(${pdfSafe(line)}) Tj`);
  }
  commands.push('ET');
  const stream = commands.join('\n');
  const objects = [
    '<< /Type /Catalog /Pages 2 0 R >>',
    '<< /Type /Pages /Kids [3 0 R] /Count 1 >>',
    '<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] /Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>',
    '<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>',
    `<< /Length ${stream.length} >>\nstream\n${stream}\nendstream`,
  ];
  let pdf = '%PDF-1.4\n';
  const offsets = [0];
  for (const [index, object] of objects.entries()) {
    offsets.push(pdf.length);
    pdf += `${index + 1} 0 obj\n${object}\nendobj\n`;
  }
  const xref = pdf.length;
  pdf += `xref\n0 ${objects.length + 1}\n0000000000 65535 f \n`;
  pdf += offsets.slice(1).map((offset) => `${String(offset).padStart(10, '0')} 00000 n \n`).join('');
  pdf += `trailer\n<< /Size ${objects.length + 1} /Root 1 0 R >>\nstartxref\n${xref}\n%%EOF\n`;
  return pdf;
}

/** Build a privacy-minimised PDF/CSV/institution payload at the service boundary. */
export function buildClinicalExport(
  entries: readonly LogEntry[],
  format: ExportFormat,
  options: ClinicalExportOptions,
): ClinicalExportPayload {
  if (!canExport(options)) throw new Error('re_authentication_required');
  const rows = exportRows(entries, options.includesEvidence);
  const stamp = options.generatedAt.slice(0, 10);
  let content: string;
  let mimeType: string;
  let extension: string;

  if (format === 'csv') {
    const headers = ['date', 'hours', 'activity', 'category', 'status', ...(options.includesEvidence ? ['evidence'] : [])];
    content = [
      headers.join(','),
      ...rows.map((row) => headers.map((key) => csvCell(String(row[key as keyof typeof row] ?? ''))).join(',')),
    ].join('\n');
    mimeType = 'text/csv;charset=utf-8';
    extension = 'csv';
  } else if (format === 'pdf') {
    const lines = [
      'LegalSaathi clinical-hours report',
      `Generated: ${options.generatedAt}`,
      NON_OFFICIAL_TRANSCRIPT_WARNING,
      ...rows.map((row) => `${row.date} | ${row.hours} hrs | ${row.activity} | ${row.category} | ${row.status}${'evidence' in row ? ` | evidence: ${row.evidence}` : ''}`),
    ];
    content = simplePdf(lines);
    mimeType = 'application/pdf';
    extension = 'pdf';
  } else {
    content = JSON.stringify({
      schema: 'legalsaathi.clinical-export.v1',
      generatedAt: options.generatedAt,
      warning: NON_OFFICIAL_TRANSCRIPT_WARNING,
      summary: exportSummary(entries),
      rows,
    }, null, 2);
    mimeType = 'application/json';
    extension = 'json';
  }

  return {
    format,
    fileName: `legalsaathi-clinical-hours-${stamp}.${extension}`,
    mimeType,
    content,
    generatedAt: options.generatedAt,
    includesEvidence: options.includesEvidence,
    entryCount: entries.length,
    source: 'LegalSaathi self-maintained clinical log',
  };
}

const AUDIT_KEY = 'legalsaathi.clinical.export-audit.v1';

/** Record only export metadata; activity/evidence/verifier PII never enters audit. */
export function recordClinicalExportAudit(payload: ClinicalExportPayload): ClinicalExportAuditEvent {
  const event: ClinicalExportAuditEvent = {
    eventId: `clinical-export-${payload.generatedAt}-${payload.format}`,
    action: 'clinical_hours_exported',
    format: payload.format,
    generatedAt: payload.generatedAt,
    includesEvidence: payload.includesEvidence,
    entryCount: payload.entryCount,
  };
  if (typeof window !== 'undefined') {
    try {
      const existing = JSON.parse(window.localStorage.getItem(AUDIT_KEY) ?? '[]') as ClinicalExportAuditEvent[];
      window.localStorage.setItem(AUDIT_KEY, JSON.stringify([...existing, event]));
    } catch {
      // Storage denial must not corrupt the export already produced.
    }
  }
  return event;
}

/** Whether an export can proceed. Re-auth is required when evidence is included. */
export function canExport(g: { includesEvidence: boolean; reauthenticated: boolean }): boolean {
  return g.includesEvidence ? g.reauthenticated : true;
}

/** Mandatory export copy (PRD S12.3): this is NOT an official transcript. */
export const NON_OFFICIAL_TRANSCRIPT_WARNING =
  'This export is a self-maintained record, not an official transcript. Verified/unverified split, source and generated timestamp are included; your institution’s ruleset governs compliance.';
export const EXPORT_AUDIT_NOTE = 'Every export is audited; sensitive evidence requires re-authentication.';

export const SAMPLE_ENTRIES: readonly LogEntry[] = [
  { id: 'l1', date: '28 Jun', hours: 6, activity: 'DLSA legal-aid camp — Anekal taluk', category: 'legal_aid', verifier: 'prof@nls.ac.in', evidenceName: 'camp-letter.pdf', status: 'submitted' },
  { id: 'l2', date: '21 Jun', hours: 4, activity: 'City Civil Court — observation', category: 'court', verifier: 'prof@nls.ac.in', evidenceName: 'cause-list photo', status: 'verified' },
  { id: 'l3', date: '14 Jun', hours: 8, activity: 'Chambers of Sr. Adv. R. Menon', category: 'chamber', verifier: 'prof@nls.ac.in', evidenceName: 'supervisor note', status: 'verified' },
];
