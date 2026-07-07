import { describe, expect, it } from 'vitest';
import { traceability, TRACE_COUNT, getTrace } from './traceability';
import { screenRoutes } from './screenRegistry';

describe('S-01..S-99 traceability metadata (SAATHI-344)', () => {
  it('has complete metadata for all 99 screens', () => {
    expect(TRACE_COUNT).toBe(99);
    for (let i = 1; i <= 99; i++) {
      const id = `S-${String(i).padStart(2, '0')}`;
      const t = traceability[id];
      expect(t, `${id} missing`).toBeTruthy();
      for (const f of ['id', 'epic', 'story', 'release', 'persona'] as const) {
        expect(t[f], `${id}.${f} empty`).toBeTruthy();
      }
    }
  });

  it('every canonical route has traceability metadata', () => {
    for (const r of screenRoutes) {
      expect(getTrace(r.id), `no trace for ${r.id}`).toBeTruthy();
    }
  });

  it('every release looks like a valid tranche (R…)', () => {
    for (const t of Object.values(traceability)) expect(t.release).toMatch(/^R\d/);
  });
});
