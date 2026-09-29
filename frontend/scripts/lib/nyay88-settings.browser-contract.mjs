// S-18 synthetic browser regressions. No live backend or conformance claim.
import { after as afterAll, before as beforeAll, describe, it } from 'node:test';
import assert from 'node:assert/strict';
import { chromium } from 'playwright';
import { createServer } from 'vite';
import { actor } from './nyay66-fixtures.mjs';
import { mkdir, readFile } from 'node:fs/promises';
import { resolve } from 'node:path';
import { createRequire } from 'node:module';

const require = createRequire(import.meta.url);
let server, browser, origin;
beforeAll(async () => {
  server = await createServer({ server: { host: '127.0.0.1', port: 0, strictPort: false }, logLevel: 'error' });
  await server.listen();
  origin = `http://127.0.0.1:${server.httpServer.address().port}`;
  browser = await chromium.launch({ headless: true });
});
afterAll(async () => { await browser?.close(); await server?.close(); });

async function fixture() {
  const context = await browser.newContext({ viewport: { width: 390, height: 844 }, reducedMotion: 'reduce' });
  const page = await context.newPage();
  const settings = { theme: 'system', language: 'en', notif_email: true, notif_sms: false, notif_updates: false, version: 7, privacy: [] };
  const calls = []; let response = { status: 200 }, release;
  await page.route('**/api/v1/**', async route => {
    const path = new URL(route.request().url()).pathname;
    const json = (body, status = 200) => route.fulfill({ status, contentType: 'application/json', body: JSON.stringify(body) });
    if (path.endsWith('/auth/student/session')) return json({ authenticated: true, actor });
    if (path.endsWith('/student/settings')) {
      if (route.request().method() === 'PATCH') {
        const body = route.request().postDataJSON(); calls.push(body);
        if (response.hold) await new Promise(resolve => { release = resolve; });
        if (response.status !== 200) return json({ detail: { code: response.code, field: response.field } }, response.status);
        for (const key of Object.keys(body)) if (key !== 'expected_version') settings[key] = body[key];
        settings.version++;
      }
      return json(settings);
    }
    return json({ detail: { code: 'unmatched_test_api' } }, 404);
  });
  await page.goto(origin + '/s-18');
  await page.locator('[data-settings-state="loaded"]').waitFor();
  return { page, context, settings, calls, setResponse: value => { response = value; }, release: () => release?.() };
}

async function waitForCall(calls, count) {
  for (let attempt = 0; attempt < 100 && calls.length < count; attempt++) await new Promise(resolve => setTimeout(resolve, 25));
  assert.equal(calls.length, count);
}

describe('S-18 real Chromium / synthetic API', { timeout: 120000 }, () => {
  it('keeps persistence pending, rejects same-tick duplicate clicks, and uses the returned version next time', async () => {
    const f = await fixture();
    try {
      f.setResponse({ status: 200, hold: true });
      await f.page.getByRole('switch', { name: 'SMS notifications' }).evaluate(el => { el.click(); el.click(); });
      await waitForCall(f.calls, 1);
      assert.deepEqual(f.calls[0], { notif_sms: true, expected_version: 7 });
      assert.equal(await f.page.getByText('Saved to your account.', { exact: true }).count(), 0);
      await f.page.locator('[data-settings-state="saving"]').waitFor();
      f.release();
      await f.page.locator('[data-settings-state="saved"]').waitFor();
      f.setResponse({ status: 200 });
      await f.page.getByRole('switch', { name: 'Email notifications' }).click();
      await f.page.locator('[data-settings-state="saved"]').waitFor();
      assert.deepEqual(f.calls[1], { notif_email: false, expected_version: 8 });
    } finally { f.release(); await f.context.close(); }
  });
  it('rolls back a failure, focuses the error, and retries only when requested', async () => {
    const f = await fixture();
    try {
      f.setResponse({ status: 503, code: 'unavailable' });
      await f.page.getByRole('switch', { name: 'SMS notifications' }).click();
      await f.page.locator('[data-settings-state="network"]').waitFor();
      assert.equal(await f.page.getByRole('switch', { name: 'SMS notifications' }).getAttribute('aria-checked'), 'false');
      assert.equal(await f.page.evaluate(() => document.activeElement?.getAttribute('role')), 'alert');
      assert.equal(f.calls.length, 1);
      f.setResponse({ status: 200 });
      await f.page.getByRole('button', { name: 'Try again' }).click();
      await f.page.locator('[data-settings-state="saved"]').waitFor();
      assert.deepEqual(f.calls[1], f.calls[0]);
    } finally { await f.context.close(); }
  });
  it('requires conflict reload and the latest version, never silently retries an overwrite', async () => {
    const f = await fixture();
    try {
      f.setResponse({ status: 409, code: 'settings_version_conflict' });
      await f.page.getByRole('switch', { name: 'SMS notifications' }).click();
      await f.page.locator('[data-settings-state="conflict"]').waitFor();
      await f.page.getByRole('switch', { name: 'Email notifications' }).evaluate(el => el.click());
      assert.equal(f.calls.length, 1);
      f.settings.version = 20;
      f.settings.notif_email = false;
      await f.page.getByRole('button', { name: 'Reload settings' }).click();
      await f.page.locator('[data-settings-state="loaded"]').waitFor();
      f.setResponse({ status: 200 });
      await f.page.getByRole('switch', { name: 'SMS notifications' }).click();
      await f.page.locator('[data-settings-state="saved"]').waitFor();
      assert.equal(f.calls[1].expected_version, 20);
      assert.equal(await f.page.getByRole('switch', { name: 'Email notifications' }).getAttribute('aria-checked'), 'false');
    } finally { await f.context.close(); }
  });
  for (const [status, state] of [[401, 'session'], [403, 'forbidden'], [422, 'invalid']]) it(`discloses HTTP ${status} as ${state}`, async () => {
    const f = await fixture();
    try {
      f.setResponse({ status, code: 'synthetic_rejection', field: 'notifSms' });
      await f.page.getByRole('switch', { name: 'SMS notifications' }).click();
      await f.page.locator(`[data-settings-state="${state}"]`).waitFor();
      assert.equal(await f.page.getByText('Saved to your account.', { exact: true }).count(), 0);
    } finally { await f.context.close(); }
  });
  it('stores Dark only after confirmation; Hindi stays unavailable; keyboard controls remain usable', async () => {
    const f = await fixture();
    try {
      await f.page.getByText('Appearance and language', { exact: true }).click();
      await f.page.getByRole('button', { name: 'Dark', exact: true }).press('Enter');
      await f.page.locator('[data-settings-state="saved"]').waitFor();
      assert.deepEqual(f.calls[0], { theme: 'dark', expected_version: 7 });
      assert.equal(await f.page.evaluate(() => getComputedStyle(document.querySelector('.v321-settings')).backgroundColor), 'rgb(239, 237, 246)');
      await f.page.getByRole('button', { name: /हिन्दी/ }).evaluate(el => el.click());
      assert.equal(f.calls.length, 1);
    } finally { await f.context.close(); }
  });
  it('settles a pending write after a query/hash change without freezing or releasing the lock early', async () => {
    const f = await fixture();
    try {
      f.setResponse({ status: 200, hold: true });
      await f.page.getByRole('switch', { name: 'SMS notifications' }).click();
      await waitForCall(f.calls, 1);
      await f.page.evaluate(() => { history.pushState({}, '', '/s-18?view=settings#preferences'); dispatchEvent(new PopStateEvent('popstate')); });
      await f.page.getByRole('switch', { name: 'Email notifications' }).evaluate(el => el.click());
      assert.equal(f.calls.length, 1);
      f.release();
      await f.page.locator('[data-settings-state="loaded"]').waitFor();
      f.setResponse({ status: 200 });
      await f.page.getByRole('switch', { name: 'Email notifications' }).click();
      await f.page.locator('[data-settings-state="saved"]').waitFor();
      assert.equal(f.calls.length, 2);
    } finally { f.release(); await f.context.close(); }
  });
  for (const width of [320, 390, 1440]) it(`has 48px targets, one main, no serious/critical axe issues or overflow at ${width}px`, async () => {
    const f = await fixture();
    try {
      await f.page.setViewportSize({ width, height: width > 900 ? 1024 : 844 });
      await f.page.getByText('Appearance and language', { exact: true }).click();
      const layout = await f.page.evaluate(() => ({ overflow: document.documentElement.scrollWidth > innerWidth, main: document.querySelectorAll('main').length,
        small: [...document.querySelectorAll('.v321-settings button,.v321-settings summary')].filter(el => el.getClientRects().length && (el.getBoundingClientRect().height < 48 || el.getBoundingClientRect().width < 48)).map(el => el.textContent) }));
      assert.deepEqual(layout, { overflow: false, main: 1, small: [] });
      await f.page.addScriptTag({ content: await readFile(require.resolve('axe-core/axe.min.js'), 'utf8') });
      const violations = await f.page.evaluate(async () => (await window.axe.run()).violations.filter(v => ['serious', 'critical'].includes(v.impact)).map(v => v.id));
      assert.deepEqual(violations, []);
      if (process.env.NYAY88_DIAGNOSTIC_DIR) {
        await mkdir(process.env.NYAY88_DIAGNOSTIC_DIR, { recursive: true });
        await f.page.screenshot({ path: resolve(process.env.NYAY88_DIAGNOSTIC_DIR, `S-18-expanded-${width}.png`), fullPage: true });
        await f.page.getByText('Appearance and language', { exact: true }).click();
        await f.page.screenshot({ path: resolve(process.env.NYAY88_DIAGNOSTIC_DIR, `S-18-loaded-${width}.png`), fullPage: true });
      }
    } finally { await f.context.close(); }
  });
});
