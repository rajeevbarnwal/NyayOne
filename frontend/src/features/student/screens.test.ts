import { describe, expect, it } from 'vitest';
import { studentScreens, IMPLEMENTED_SCREEN_IDS } from './screens';
import { screenRoutes } from '../../app/screenRegistry';

describe('student screen registry (SAATHI-52/53/55/57/58)', () => {
  it('implements canonical IDs S-01 through S-19', () => {
    const expected = Array.from({ length: 19 }, (_, i) => `S-${String(i + 1).padStart(2, '0')}`);
    expect(IMPLEMENTED_SCREEN_IDS.sort()).toEqual(expected.sort());
  });

  it('maps every implemented ID to a real component', () => {
    for (const id of IMPLEMENTED_SCREEN_IDS) {
      expect(typeof studentScreens[id]).toBe('function');
    }
  });

  it('only maps IDs that exist in the canonical S-01..S-99 route registry', () => {
    const routeIds = new Set(screenRoutes.map((r) => r.id));
    for (const id of IMPLEMENTED_SCREEN_IDS) {
      expect(routeIds.has(id)).toBe(true);
    }
  });
});
