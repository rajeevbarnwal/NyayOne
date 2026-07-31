import { describe, expect, it } from 'vitest';
import { studentScreens, IMPLEMENTED_SCREEN_IDS } from './screens';
import { screenRoutes } from '../../app/screenRegistry';

describe('student screen registry (SAATHI-52/53/55/57/58)', () => {
  it('implements the canonical IDs delivered so far including S17 credential trust', () => {
    const expected = [
      // S-01..S-26 + S-27..S-30 law schools (SAATHI-63)
      // + S-31..S-35 Wave 2 tutoring (SAATHI-65 owns S-31..S-34, SAATHI-66 owns S-35)
      ...Array.from({ length: 35 }, (_, i) => `S-${String(i + 1).padStart(2, '0')}`),
      'S-50', 'S-51', 'S-52', 'S-53', 'S-54',
      'S-55', 'S-56', 'S-57', 'S-58', 'S-59', 'S-60',
      'S-61', 'S-62', 'S-63', 'S-64', 'S-65',
      'S-82', 'S-83', 'S-84', 'S-85',
      'S-90', 'S-91', // S19.1 cross-module calendar (SAATHI-286)
      'S-94', 'S-95', // Terms & Conditions and Privacy Policy docs
    ];
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
