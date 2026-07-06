import { describe, expect, it } from 'vitest';
import { TOTAL_SCREENS, screenRoutes } from './screenRegistry';

describe('canonical screen registry (v3.2 S-01..S-99)', () => {
  it('registers exactly 99 screens', () => {
    expect(screenRoutes).toHaveLength(TOTAL_SCREENS);
  });

  it('spans S-01 through S-99 with unique paths', () => {
    expect(screenRoutes[0].id).toBe('S-01');
    expect(screenRoutes[TOTAL_SCREENS - 1].id).toBe('S-99');
    const paths = new Set(screenRoutes.map((r) => r.path));
    expect(paths.size).toBe(TOTAL_SCREENS);
  });

  it('derives lowercase route paths', () => {
    expect(screenRoutes[0].path).toBe('/s-01');
  });
});
