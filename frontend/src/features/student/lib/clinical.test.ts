import { describe, expect, it } from 'vitest';
import { readFileSync } from 'node:fs';
import {
  validateEntry,
  isValidCategory,
  totalHours,
  hoursByCategory,
  progressPct,
  statusChip,
  canSyncTransition,
  CATEGORY_OPTIONS,
  SAMPLE_ENTRIES,
  buildClinicalExport,
  recordClinicalExportAudit,
  type LogDraftInput,
} from './clinical';

const clinicalSource = readFileSync(new URL('./clinical.ts', import.meta.url), 'utf8');

const good: LogDraftInput = { date: '2026-07-04', hours: '6', activity: 'DLSA camp', category: 'legal_aid', verifier: 'prof@nls.ac.in' };

describe('clinical log validation + progress (SAATHI-173)', () => {
  it('never persists export audit workflow state in browser storage', () => {
    expect(clinicalSource).not.toMatch(/(?:localStorage|sessionStorage)\.(?:getItem|setItem)/u);
  });

  it('validates categories', () => {
    expect(isValidCategory('legal_aid')).toBe(true);
    expect(isValidCategory('random')).toBe(false);
    expect(CATEGORY_OPTIONS).toContain('court');
  });
  it('validates entry fields; verifier only required for submit', () => {
    expect(Object.keys(validateEntry(good)).length).toBe(0);
    expect(validateEntry({ ...good, hours: '0' }).hours).toBeTruthy();
    expect(validateEntry({ ...good, hours: '30' }).hours).toBeTruthy();
    expect(validateEntry({ ...good, category: 'x' }).category).toBeTruthy();
    expect(validateEntry({ ...good, verifier: 'nope' }, true).verifier).toBeTruthy();
    expect(validateEntry({ ...good, verifier: 'nope' }, false).verifier).toBeUndefined();
  });
  it('computes hours totals, per-category and progress', () => {
    expect(totalHours(SAMPLE_ENTRIES)).toBe(18);
    expect(hoursByCategory(SAMPLE_ENTRIES).legal_aid).toBe(6);
    expect(progressPct(SAMPLE_ENTRIES, 120)).toBe(15);
  });
  it('maps verification status to chips and reuses sync state machine', () => {
    expect(statusChip('verified').kind).toBe('ok');
    expect(statusChip('submitted').label).toBe('Pending faculty');
    expect(canSyncTransition('local_draft', 'queued')).toBe(true);
    expect(canSyncTransition('local_draft', 'synced')).toBe(false);
  });

  it('builds privacy-safe CSV/PDF payloads and an auditable export event', () => {
    const generatedAt = '2026-07-18T10:00:00.000Z';
    const csv = buildClinicalExport(SAMPLE_ENTRIES, 'csv', {
      includesEvidence: false,
      reauthenticated: false,
      generatedAt,
    });
    expect(csv.mimeType).toContain('text/csv');
    expect(csv.content).toContain('date,hours,activity,category,status');
    expect(csv.content).not.toContain('prof@nls.ac.in');
    expect(csv.content).not.toContain('camp-letter.pdf');

    const pdf = buildClinicalExport(SAMPLE_ENTRIES, 'pdf', {
      includesEvidence: true,
      reauthenticated: true,
      generatedAt,
    });
    expect(pdf.content.startsWith('%PDF-1.4')).toBe(true);
    expect(pdf.content).toContain('xref');
    expect(pdf.content.endsWith('%%EOF\n')).toBe(true);
    expect(pdf.content).not.toContain('prof@nls.ac.in');
    const audit = recordClinicalExportAudit(pdf);
    expect(audit).toMatchObject({ action: 'clinical_hours_exported', format: 'pdf', entryCount: 3 });
  });

  it('blocks evidence exports until re-authentication', () => {
    expect(() => buildClinicalExport(SAMPLE_ENTRIES, 'csv', {
      includesEvidence: true,
      reauthenticated: false,
      generatedAt: '2026-07-18T10:00:00.000Z',
    })).toThrow('re_authentication_required');
  });
});
