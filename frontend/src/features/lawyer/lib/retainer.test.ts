import { describe, expect, it } from 'vitest';
import {
  isClauseAllowed,
  applyClausePolicy,
  retainerComplete,
  makeSignatureRecord,
  DEFAULT_FEE_CONFIG,
  RESTRICTED_CLAUSES,
} from './retainer';

describe('retainer fee-clause policy (SAATHI-8 / E02)', () => {
  it('blocks restricted clauses by default', () => {
    for (const c of RESTRICTED_CLAUSES) expect(isClauseAllowed(c)).toBe(false);
    expect(isClauseAllowed('fixed')).toBe(true);
    expect(isClauseAllowed('hourly')).toBe(true);
  });

  it('enables a restricted clause only via LCR-approved config', () => {
    const cfg = { lcrApproved: true, enabledRestrictedClauses: ['success'] as const, approvedBy: 'counsel' };
    expect(isClauseAllowed('success', cfg)).toBe(true);
    expect(isClauseAllowed('contingent', cfg)).toBe(false); // not in enabled list
    // Not approved → still blocked even if listed.
    expect(isClauseAllowed('success', { lcrApproved: false, enabledRestrictedClauses: ['success'] })).toBe(false);
  });

  it('splits a requested clause set into allowed/blocked', () => {
    const { allowed, blocked } = applyClausePolicy(['fixed', 'success', 'proceeds_sharing'], DEFAULT_FEE_CONFIG);
    expect(allowed).toEqual(['fixed']);
    expect(blocked.sort()).toEqual(['proceeds_sharing', 'success']);
  });

  it('completes only when signed or uploaded, and stores a signature record', () => {
    expect(retainerComplete('draft')).toBe(false);
    expect(retainerComplete('signed')).toBe(true);
    expect(retainerComplete('uploaded')).toBe(true);
    const rec = makeSignatureRecord('abc123', 'client@x.in', '2026-07-08', 'e-sign');
    expect(rec.fileHash).toBe('abc123');
    expect(rec.source).toBe('e-sign');
  });
});
