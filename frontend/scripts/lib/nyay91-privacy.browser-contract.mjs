// S-19 synthetic API / real Chromium regression checks. Not independent QA,
// live-backend proof, or hosted visual conformance.
import { before, after, describe, it } from 'node:test';
import assert from 'node:assert/strict';
import { chromium } from 'playwright';
import { createServer } from 'vite';
import { readFile, mkdir } from 'node:fs/promises';
import { join } from 'node:path';
import { actor } from './nyay66-fixtures.mjs';
let server, browser, origin;
before(async () => {
  server = await createServer({ server: { host: '127.0.0.1', port: 0 }, logLevel: 'error' });
  await server.listen(); origin = `http://127.0.0.1:${server.httpServer.address().port}`;
  browser = await chromium.launch({ headless: true });
});
after(async () => { await browser?.close(); await server?.close(); });
const idle = { status: 'unavailable', purpose: null, destination_masked: null, attempts_left: null, expires_in_seconds: null, resend_in_seconds: null, locked_for_seconds: null, resend_allowed: false };
const pending = { ...idle, status: 'pending', purpose: 'recovery', destination_masked: '••••••0340', attempts_left: 3, expires_in_seconds: 300, resend_in_seconds: 30, locked_for_seconds: 0 };
const verified = { ...idle, status: 'verified', purpose: 'recovery' };
async function fixture() {
  const context = await browser.newContext({ viewport: { width: 390, height: 844 }, reducedMotion: 'reduce' });
  const page = await context.newPage(); page.setDefaultTimeout(5000);
  const settings = { theme: 'system', language: 'en', notif_email: true, notif_sms: false, notif_updates: false, version: 7, privacy: ['analytics', 'marketing', 'share_partners'].map(kind => ({ kind, enabled: false })) };
  const requests = []; let response = {}, release, flow = idle, lostSession = false, observePatch;
  const patchObserved = new Promise(resolve => { observePatch = resolve; });
  await page.route('**/api/v1/**', async route => {
    const req = route.request(), path = new URL(req.url()).pathname, method = req.method();
    requests.push({ path, method, body: req.postData() ? req.postDataJSON() : null });
    const json = (body, status = 200) => route.fulfill({ status, contentType: 'application/json', body: JSON.stringify(body) });
    if (path.endsWith('/session')) return json(lostSession ? { authenticated: false, actor: null } : { authenticated: true, actor });
    if (path.endsWith('/login/channels')) return json({ channels: [{ channel: 'mobile', enabled: true }, { channel: 'email', enabled: true }] });
    if (path.endsWith('/otp/state')) return response.otpError ? json({ detail: { code: 'unavailable' } }, 503) : json(flow);
    if (path.endsWith('/student/settings')) {
      if (method === 'PATCH') {
        observePatch();
        if (response.hold) await new Promise(resolve => { release = resolve; });
        if (response.status) return json({ detail: { code: response.code } }, response.status);
        if (response.malformed) return json({ ...settings, version: settings.version });
        for (const c of req.postDataJSON().privacy) settings.privacy.find(p => p.kind === c.kind).enabled = c.enabled;
        settings.version++;
      }
      return json(settings);
    }
    if (path.endsWith('/privacy/export')) return json({ request_id: 'a'.repeat(32), status: response.exportStatus || 'pending' }, 202);
    if (path.includes('/privacy/requests/')) return response.checkError ? json({ detail: { code: 'not_found' } }, response.checkError) : json({ request_id: 'a'.repeat(32), kind: 'export', status: response.exportStatus || 'processing', created_at: '2026-10-17T10:00:00Z' });
    if (path.endsWith('/recovery/start')) { flow = pending; return json(flow, 202); }
    if (path.endsWith('/recovery/verify')) { flow = verified; return json(flow); }
    if (path.endsWith('/privacy/delete')) { lostSession = true; flow = idle; return json({ request_id: 'b'.repeat(32), status: 'pending' }, 202); }
    return json({ detail: { code: 'unmatched_api' } }, 404);
  });
  await page.goto(origin + '/s-19'); await page.locator('[data-privacy-state="loaded"]').waitFor();
  return { context, page, requests, settings, patchObserved, set: value => { response = value; }, setFlow: value => { flow = value; }, release: () => release?.() };
}
async function using(test) { const f = await fixture(); try { await test(f); } finally { f.release(); await f.context.close(); } }
const patches = f => f.requests.filter(r => r.method === 'PATCH');
describe('S-19 real browser / synthetic server', { timeout: 60000 }, () => {
  for (const width of [390, 1440]) it(`matches the frozen S-19 focused-heading and action-gap geometry at ${width}px`, () => using(async f => {
    await f.page.setViewportSize({ width, height: 1024 });
    await f.page.evaluate(() => document.fonts.ready);
    await f.page.getByRole('button', { name: 'Delete my account', exact: true }).click();
    const heading = f.page.locator('#S-19-delete-heading');
    const layout = await heading.evaluate(el => {
      const css = getComputedStyle(el), box = el.getBoundingClientRect();
      return { size: css.fontSize, display: css.display, gap: css.gap, height: box.height };
    });
    assert.deepEqual(layout, { size: '19px', display: 'flex', gap: '9px', height: 32 });
    const send = await f.page.getByRole('button', { name: 'Send code', exact: true }).boundingBox();
    const cancel = await f.page.getByRole('button', { name: 'Back to privacy', exact: true }).boundingBox();
    assert.equal(cancel.y - send.y - send.height, 8, 'deletion action gap');
    assert.equal(await f.page.getByLabel('Registered mobile number').evaluate(el => getComputedStyle(el.labels[0]).fontSize), '12px');
    await f.page.getByLabel('Registered mobile number').fill('9876500340');
    await f.page.getByRole('button', { name: 'Send code', exact: true }).click();
    const code = f.page.getByLabel('Six-digit code');
    await code.waitFor();
    assert.deepEqual(await code.evaluate(el => { const c = getComputedStyle(el); return [c.width, c.fontWeight, c.letterSpacing, c.paddingLeft]; }), ['322px', '500', '8px', '16px']);
  }));
  it('holds duplicate toggles and shows no success before server confirmation', () => using(async f => {
    f.set({ hold: true });
    await f.page.getByRole('switch', { name: 'Usage analytics' }).evaluate(el => { el.click(); el.click(); });
    await f.page.locator('[data-privacy-state="saving"]').waitFor();
    await f.patchObserved;
    assert.equal(patches(f).length, 1);
    assert.deepEqual(patches(f)[0].body, { privacy: [{ kind: 'analytics', enabled: true }], expected_version: 7 });
    assert.equal(await f.page.getByText('Saved to your account.').count(), 0);
    f.release(); await f.page.locator('[data-privacy-state="saved"]').waitFor();
    f.set({}); await f.page.getByRole('switch', { name: 'Marketing messages' }).click();
    await f.page.waitForFunction(() => document.querySelector('[data-privacy-state]')?.dataset.privacyState === 'saved');
    assert.equal(patches(f)[1].body.expected_version, 8);
  }));
  it('rolls back rejection and reload-gates conflicts without auto-overwriting', () => using(async f => {
    f.set({ status: 409, code: 'settings_version_conflict' });
    await f.page.getByRole('switch', { name: 'Usage analytics' }).click();
    await f.page.locator('[data-privacy-state="conflict"]').waitFor();
    assert.equal(await f.page.getByRole('switch', { name: 'Usage analytics' }).getAttribute('aria-checked'), 'false');
    const gets = f.requests.filter(r => r.path.endsWith('/student/settings') && r.method === 'GET').length;
    await f.page.getByRole('switch', { name: 'Marketing messages' }).evaluate(el => el.click());
    assert.equal(patches(f).length, 1); assert.equal(gets, 1);
    f.settings.version = 10; f.set({}); await f.page.getByRole('button', { name: 'Reload', exact: true }).click();
    await f.page.locator('[data-privacy-state="loaded"]').waitFor();
    assert.equal(await f.page.evaluate(() => document.activeElement?.getAttribute('role')), 'switch');
    await f.page.getByRole('switch', { name: 'Usage analytics' }).click();
    await f.page.locator('[data-privacy-state="saved"]').waitFor(); assert.equal(patches(f)[1].body.expected_version, 10);
  }));
  it('does not accept a malformed or unadvanced 2xx as persisted consent', () => using(async f => {
    f.set({ malformed: true }); await f.page.getByRole('switch', { name: 'Usage analytics' }).click();
    await f.page.locator('[data-privacy-state="network"]').waitFor();
    assert.equal(await f.page.getByText('Saved to your account.').count(), 0);
    assert.equal(await f.page.getByRole('switch', { name: 'Usage analytics' }).getAttribute('aria-checked'), 'false');
  }));
  it('releases the busy UI after query/hash navigation only when the held save settles', () => using(async f => {
    f.set({ hold: true }); await f.page.getByRole('switch', { name: 'Usage analytics' }).click();
    await f.page.locator('[data-privacy-state="saving"]').waitFor();
    await f.page.evaluate(() => { history.pushState({}, '', '/s-19?test=1#privacy'); dispatchEvent(new PopStateEvent('popstate')); });
    assert.equal(await f.page.getByRole('switch', { name: 'Marketing messages' }).getAttribute('aria-disabled'), 'true');
    f.release(); await f.page.locator('[data-privacy-state="loaded"]').waitFor();
    assert.equal(await f.page.getByRole('switch', { name: 'Usage analytics' }).getAttribute('aria-checked'), 'true');
    assert.equal(patches(f).length, 1);
  }));
  it('renders complete/cancelled export truth without a delivery or cancellation endpoint', () => using(async f => {
    f.set({ exportStatus: 'complete' }); await f.page.getByRole('button', { name: 'Request a copy of my data' }).click();
    await f.page.getByText('Your export is complete.', { exact: true }).waitFor();
    assert.match(await f.page.locator('main').innerText(), /no download or delivery step/);
    await f.page.getByRole('button', { name: 'Dismiss', exact: true }).click();
    f.set({ exportStatus: 'cancelled' }); await f.page.getByRole('button', { name: 'Request a copy of my data' }).click();
    await f.page.getByText('The export request was cancelled.').waitFor();
    assert.equal(await f.page.getByRole('button', { name: 'Cancel export' }).count(), 0);
  }));
  it('retains last confirmed export status when a status read fails', () => using(async f => {
    f.set({ exportStatus: 'processing' }); await f.page.getByRole('button', { name: 'Request a copy of my data' }).click();
    await f.page.getByText('Your export is being prepared.').waitFor();
    f.set({ checkError: 503 }); await f.page.getByRole('button', { name: 'Check status' }).click();
    await f.page.getByText('Status check failed.').waitFor();
    assert.match(await f.page.locator('main').innerText(), /last confirmed status: processing/);
  }));
  it('uses focused replacement steps and recovery → verify → exact DELETE, never recovery/complete', () => using(async f => {
    await f.page.getByRole('button', { name: 'Delete my account', exact: true }).click();
    await f.page.getByLabel('Registered mobile number').waitFor();
    assert.equal(await f.page.getByRole('switch').count(), 0);
    assert.equal(await f.page.evaluate(() => document.activeElement?.tagName), 'H1');
    await f.page.getByLabel('Registered mobile number').fill('9876500340');
    await f.page.getByRole('button', { name: 'Send code', exact: true }).click();
    await f.page.getByLabel('Six-digit code').fill('123-456');
    assert.equal(await f.page.getByLabel('Six-digit code').inputValue(), '123456');
    await f.page.getByLabel('Six-digit code').press('Enter');
    await f.page.getByLabel('Type DELETE to continue').fill('delete');
    assert.equal(await f.page.getByRole('button', { name: 'Request account deletion', exact: true }).isDisabled(), true);
    await f.page.getByLabel('Type DELETE to continue').fill('DELETE');
    await f.page.getByRole('button', { name: 'Request account deletion', exact: true }).click();
    await f.page.waitForURL('**/s-03');
    assert.deepEqual(f.requests.filter(r => r.method === 'POST').map(r => [r.path, r.body]), [
      ['/api/v1/auth/student/recovery/start', { mobile: '9876500340' }],
      ['/api/v1/auth/student/recovery/verify', { code: '123456' }],
      ['/api/v1/student/privacy/delete', { confirmation: 'DELETE' }],
    ]);
  }));
  it('restores a useful control after leaving the deletion steps', () => using(async f => {
    await f.page.getByRole('button', { name: 'Delete my account', exact: true }).click();
    await f.page.getByRole('button', { name: 'Back to privacy', exact: true }).click();
    assert.equal(await f.page.evaluate(() => document.activeElement?.textContent), 'Delete my account');
  }));
  it('fails closed on unavailable recovery authority and recovers only after a fresh read', () => using(async f => {
    f.setFlow(verified); f.set({ otpError: true });
    await f.page.getByRole('button', { name: 'Delete my account', exact: true }).click();
    await f.page.getByText('Re-authentication state is unavailable.').waitFor();
    await f.page.getByLabel('Registered mobile number').fill('9876500340');
    assert.equal(await f.page.getByRole('button', { name: 'Send code', exact: true }).isDisabled(), true);
    assert.equal(await f.page.getByLabel('Type DELETE to continue').count(), 0);
    assert.equal(f.requests.filter(r => r.method === 'POST').length, 0);
    f.set({});
    await f.page.getByLabel('Type DELETE to continue').waitFor({ timeout: 10000 });
    assert.equal(await f.page.getByRole('button', { name: 'Request account deletion', exact: true }).isDisabled(), true);
  }));
  for (const width of [320, 390, 1440]) it(`has no overflow, serious/critical axe issues, or undersized controls at ${width}px`, () => using(async f => {
    await f.page.setViewportSize({ width, height: 1024 });
    await f.page.addScriptTag({ content: await readFile('node_modules/axe-core/axe.min.js', 'utf8') });
    for (const mode of ['overview', 'deletion']) {
      if (mode === 'deletion') await f.page.getByRole('button', { name: 'Delete my account', exact: true }).click();
      const actual = await f.page.evaluate(async () => ({
        overflow: document.documentElement.scrollWidth - innerWidth,
        small: [...document.querySelectorAll('[data-screen="S-19"] button, [data-screen="S-19"] input')].filter(el => { const b = el.getBoundingClientRect(); return b.width && b.height && (b.width < 48 || b.height < 48); }).map(el => el.textContent),
        violations: (await window.axe.run()).violations.filter(v => ['serious', 'critical'].includes(v.impact)).map(v => ({ id: v.id, nodes: v.nodes.map(n => n.target) })),
      }));
      assert.equal(actual.overflow, 0, mode);
      assert.deepEqual(actual.small, [], mode);
      assert.deepEqual(actual.violations, [], mode);
      if (process.env.NYAY91_DIAGNOSTIC_DIR) {
        await mkdir(process.env.NYAY91_DIAGNOSTIC_DIR, { recursive: true });
        await f.page.screenshot({ path: join(process.env.NYAY91_DIAGNOSTIC_DIR, `s19-${mode}-${width}-local-diagnostic.png`), fullPage: true });
      }
    }
  }));
});
