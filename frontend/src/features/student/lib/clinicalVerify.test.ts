import { describe, expect, it } from 'vitest';
import {
  verificationSteps,
  exportSummary,
  canExport,
  SAMPLE_ENTRIES,
  NON_OFFICIAL_TRANSCRIPT_WARNING,
} from './clinical';

describe('clinical verification workflow + export (SAATHI-178/183)', () => {
  it('derives the 3-step workflow from status', () => {
    const pending = verificationSteps('submitted');
    expect(pending[0].state).toBe('done');
    expect(pending[1].state).toBe('now');
    expect(pending[2].state).toBe('todo');
    const verified = verificationSteps('verified');
    expect(verified[1].state).toBe('done');
    expect(verified[2].state).toBe('done');
  });
  it('summarises export progress with verified split', () => {
    const s = exportSummary(SAMPLE_ENTRIES, 120);
    expect(s.totalHours).toBe(18);
    expect(s.entries).toBe(3);
    expect(s.verifiedEntries).toBe(2); // two SAMPLE_ENTRIES are verified
    expect(s.verifiedHours).toBe(12);
    expect(s.progressPct).toBe(15);
  });
  it('requires re-auth to export when evidence is included', () => {
    expect(canExport({ includesEvidence: false, reauthenticated: false })).toBe(true);
    expect(canExport({ includesEvidence: true, reauthenticated: false })).toBe(false);
    expect(canExport({ includesEvidence: true, reauthenticated: true })).toBe(true);
  });
  it('carries the non-official-transcript warning', () => {
    expect(NON_OFFICIAL_TRANSCRIPT_WARNING.toLowerCase()).toContain('not an official transcript');
  });
});
