import { describe, expect, it } from 'vitest';
import {
  validateIntake,
  checkConflicts,
  decideConflict,
  canProceed,
  toAuditEvent,
  nameSimilarity,
  EMPTY_INTAKE,
  SAMPLE_REGISTER,
} from './intake';

describe('intake + conflict check (SAATHI-6 / E01)', () => {
  it('validates required intake fields', () => {
    expect(Object.keys(validateIntake(EMPTY_INTAKE)).length).toBeGreaterThan(0);
    expect(
      Object.keys(
        validateIntake({ clientName: 'A', opponentName: 'B', matterType: 'Civil suit', courtPreference: '', contact: 'x@y.in', source: 'ref' })
      ).length
    ).toBe(0);
  });

  it('surfaces exact and fuzzy party-name matches', () => {
    const d = { ...EMPTY_INTAKE, clientName: 'acme textiles pvt ltd', opponentName: 'Sunrise Builders & Co' };
    const m = checkConflicts(d, SAMPLE_REGISTER);
    expect(m.some((x) => x.kind === 'exact' && x.party.role === 'client')).toBe(true);
    expect(m.some((x) => x.kind === 'fuzzy' && x.against === 'Sunrise Builders')).toBe(true);
    expect(nameSimilarity('R. K. Traders', 'RK Traders')).toBeGreaterThan(0.5);
  });

  it('blocks by default and only clears via authorised override with reason', () => {
    const m = checkConflicts({ ...EMPTY_INTAKE, clientName: 'Meera Nair' }, SAMPLE_REGISTER);
    const blocked = decideConflict(m, '2026-07-08', 'adv.rao');
    expect(blocked.decision).toBe('blocked');
    expect(canProceed(blocked)).toBe(false);

    const noReason = decideConflict(m, '2026-07-08', 'adv.rao', { authorised: true, reason: '  ' });
    expect(noReason.decision).toBe('blocked');

    const ovr = decideConflict(m, '2026-07-08', 'adv.rao', { authorised: true, reason: 'Different Meera Nair, verified PAN' });
    expect(ovr.decision).toBe('overridden');
    expect(canProceed(ovr)).toBe(true);
    expect(toAuditEvent(ovr).overrideReason).toContain('verified');
  });

  it('clears when there are no matches', () => {
    const r = decideConflict([], '2026-07-08', 'adv.rao');
    expect(r.decision).toBe('clear');
    expect(canProceed(r)).toBe(true);
    expect(toAuditEvent(r).matchCount).toBe(0);
  });
});
