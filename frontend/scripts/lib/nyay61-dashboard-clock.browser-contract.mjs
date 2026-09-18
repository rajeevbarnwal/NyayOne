/** Real-browser proof of the owner-approved Date-only fixture boundary. */
import assert from 'node:assert/strict';
import { test } from 'node:test';
import { chromium } from 'playwright';
import { mockApplication } from './nyay66-fixtures.mjs';

for (const id of ['S-14', 'S-07', 'S-07-popup']) {
  test(`${id}: Date pin is dashboard-only and real browser timers keep running`, async () => {
    const browser = await chromium.launch();
    try {
      const page = await browser.newPage();
      const adapter = {
        clock: page.clock,
        route: async () => {}, waitForResponse: async () => ({ finished: async () => {} }),
        goto: async () => {}, waitForURL: async () => {}, waitForFunction: async () => {},
        locator: () => ({ waitFor: async () => {} }), getByRole: () => ({ waitFor: async () => {} }),
      };
      await mockApplication(adapter, id, 'http://synthetic.invalid', []);
      const result = await page.evaluate(async () => {
        const before = Date.now();
        const start = performance.now();
        await new Promise(resolve => setTimeout(resolve, 30));
        return { before, after: Date.now(), elapsed: performance.now() - start };
      });
      assert.ok(result.elapsed >= 20, 'real timer must complete without advancing a mocked clock');
      if (id === 'S-07-popup') {
        assert.notEqual(result.before, Date.parse('2025-08-16T09:00:00.000Z'));
        assert.ok(result.after > result.before, 'unmodified fixture retains an advancing Date');
      } else {
        assert.equal(result.before, Date.parse('2025-08-16T09:00:00.000Z'));
        assert.equal(result.after, result.before, 'only Date remains fixed');
      }
    } finally { await browser.close(); }
  });
}
