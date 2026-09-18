import { readFileSync } from 'node:fs';
import { describe, expect, it } from 'vitest';
import { mockApplication } from './nyay66-fixtures.mjs';

function fakePage() {
  const calls = [];
  const page = {
    clock: new Proxy({}, { get: (_target, method) => {
      if (method !== 'setFixedTime') throw Error(`Unexpected clock/timer override: ${String(method)}`);
      return async value => calls.push(['date-only', value.toISOString()]);
    } }),
    route: async () => calls.push(['route']),
    waitForResponse: async () => ({ finished: async () => {} }),
    goto: async url => calls.push(['goto', url]),
    evaluate: async () => {}, waitForURL: async () => {}, waitForFunction: async () => {},
    locator: () => ({ waitFor: async () => {} }),
    getByRole: () => ({ waitFor: async () => {} }),
  };
  return { page, calls };
}

describe('NYAY-61 Date-only dashboard conformance fixture', () => {
  it.each(['S-14', 'S-07'])('fixes only %s Date before route setup/navigation, without pausing timers', async id => {
    const { page, calls } = fakePage();
    const realDate = globalThis.Date;
    await mockApplication(page, id, 'http://synthetic.invalid', []);
    expect(calls[0]).toEqual(['date-only', '2025-08-16T09:00:00.000Z']);
    expect(calls.filter(row => row[0] === 'date-only')).toHaveLength(1);
    expect(globalThis.Date).toBe(realDate);
  });
  it.each(['S-01', 'S-02', 'S-03', 'S-04', 'S-05', 'S-06', 'S-07-popup', 'S-08', 'S-09', 'S-10', 'S-10-academic', 'S-11', 'S-12', 'S-13', 'S-15', 'S-16', 'S-17'])('does not change the %s fixture clock', async id => {
    const { page, calls } = fakePage();
    await mockApplication(page, id, 'http://synthetic.invalid', []);
    expect(calls.filter(row => row[0] === 'date-only')).toEqual([]);
  });
  it('keeps the clock pin out of product sources and keeps real date/timezone derivation', () => {
    const product = readFileSync('src/features/student/dashboard/Dashboard.tsx', 'utf8');
    expect(product).toContain('const now = new Date();');
    expect(product).toContain('}).format(now);');
    expect(product).not.toMatch(/2025-08-16|setFixedTime|page\.clock|nyay66-fixtures/);
  });
});
