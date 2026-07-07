import { describe, expect, it } from 'vitest';
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
  type LogDraftInput,
} from './clinical';

const good: LogDraftInput = { date: '2026-07-04', hours: '6', activity: 'DLSA camp', category: 'legal_aid', verifier: 'prof@nls.ac.in' };

describe('clinical log validation + progress (SAATHI-173)', () => {
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
});
