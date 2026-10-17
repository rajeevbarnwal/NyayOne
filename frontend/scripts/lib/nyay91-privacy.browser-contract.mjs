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
  const requests = []; let response = {}, release, flow = idle, lostSession = false, observePatch, observeHold;
  const held = new Promise(resolve => { observeHold = resolve; });
  const hold = () => new Promise(resolve => { release = resolve; observeHold(); });
  const patchObserved = new Promise(resolve => { observePatch = resolve; });
  await page.route('**/api/v1/**', async route => {
    const req = route.request(), path = new URL(req.url()).pathname, method = req.method();
    requests.push({ path, method, body: req.postData() ? req.postDataJSON() : null });
    const json = (body, status = 200) => route.fulfill({ status, contentType: 'application/json', body: JSON.stringify(body) });
    if (path.endsWith('/session')) return json(lostSession ? { authenticated: false, actor: null } : { authenticated: true, actor });
    if (path.endsWith('/login/channels')) return json({ channels: [{ channel: 'mobile', enabled: true }, { channel: 'email', enabled: true }] });
    if (path.endsWith('/otp/state')) {
      if (response.holdOtp) await hold();
      return response.otpError ? json({ detail: { code: 'unavailable' } }, 503) : json(flow);
    }
    if (path.endsWith('/student/settings')) {
      if (method === 'PATCH') {
        observePatch();
        if (response.hold) await hold();
        if (response.status) return json({ detail: { code: response.code } }, response.status);
        if (response.malformed) return json({ ...settings, version: settings.version });
        for (const c of req.postDataJSON().privacy) settings.privacy.find(p => p.kind === c.kind).enabled = c.enabled;
        settings.version++;
      }
      return json(settings);
    }
    if (path.endsWith('/privacy/export')) {
      if (response.holdExport) await hold();
      return response.exportError ? json({ detail: { code: 'unavailable' } }, 503) : json({ request_id: 'a'.repeat(32), status: response.exportStatus || 'pending' }, 202);
    }
    if (path.includes('/privacy/requests/')) {
      if (response.holdCheck) await hold();
      return response.checkError ? json({ detail: { code: 'not_found' } }, response.checkError) : json({ request_id: 'a'.repeat(32), kind: 'export', status: response.exportStatus || 'processing', created_at: '2026-10-17T10:00:00Z' });
    }
    if (path.endsWith('/recovery/start')) { flow = pending; return json(flow, 202); }
    if (path.endsWith('/recovery/verify')) {
      if (response.recoveryFailed) {
        flow = response.recoveryProjection ?? idle;
        return json({ detail: { code: 'recovery_failed', ...(response.omitProjection ? {} : { otp_state: flow }) } }, 401);
      }
      if (response.verifyRejected) return json({ detail: { code: 'otp_invalid', otp_state: pending } }, 400);
      flow = verified; return json(flow);
    }
    if (path.endsWith('/privacy/delete')) {
      if (response.deleteStatus) return json({ detail: { code: response.deleteCode } }, response.deleteStatus);
      lostSession = true; flow = idle; return json({ request_id: 'b'.repeat(32), status: 'pending' }, 202);
    }
    return json({ detail: { code: 'unmatched_api' } }, 404);
  });
  await page.goto(origin + '/s-19'); await page.locator('[data-privacy-state="loaded"]').waitFor();
  return { context, page, requests, settings, patchObserved, held, set: value => { response = value; }, setFlow: value => { flow = value; }, release: () => release?.() };
}
async function using(test) { const f = await fixture(); try { await test(f); } finally { f.release(); await f.context.close(); } }
const patches = f => f.requests.filter(r => r.method === 'PATCH');
describe('S-19 real browser / synthetic server', { timeout: 180000 }, () => {
  it('QA-F1 keeps consent retry focus meaningful while held and after confirmation', () => using(async f => {
    f.set({ status: 503 }); await f.page.getByRole('switch', { name: 'Usage analytics' }).click();
    await f.page.locator('[data-privacy-state="network"]').waitFor();
    f.set({ hold: true }); await f.page.getByRole('button', { name: 'Try again', exact: true }).press('Enter');
    await f.page.locator('[data-privacy-state="saving"]').waitFor();
    await f.held;
    assert.notEqual(await f.page.evaluate(() => document.activeElement.tagName), 'BODY');
    f.release(); await f.page.locator('[data-privacy-state="saved"]').waitFor();
    await f.page.waitForFunction(() => document.activeElement?.getAttribute('role') === 'switch');
    assert.equal(await f.page.evaluate(() => document.activeElement.getAttribute('aria-labelledby')), 'S-19-analytics-label');
  }));
  for (const mode of ['pending', 'processing', 'complete', 'failed', 'cancelled', 'request-failed', 'not-found', 'check-failed']) {
    it(`QA-F1 restores export Dismiss focus from ${mode}`, () => using(async f => {
      f.set(mode === 'request-failed' ? { exportError: true } : { exportStatus: ['not-found', 'check-failed'].includes(mode) ? 'pending' : mode });
      await f.page.getByRole('button', { name: 'Request a copy of my data', exact: true }).click();
      await f.page.getByRole('button', { name: 'Dismiss', exact: true }).waitFor();
      if (['not-found', 'check-failed'].includes(mode)) {
        f.set({ checkError: mode === 'not-found' ? 404 : 503 });
        await f.page.getByRole('button', { name: 'Check status', exact: true }).click();
        await f.page.getByText(mode === 'not-found' ? 'That request was not found.' : 'Status check failed.', { exact: true }).waitFor();
      }
      await f.page.getByRole('button', { name: 'Dismiss', exact: true }).press('Enter');
      await f.page.waitForFunction(() => document.activeElement?.textContent === 'Request a copy of my data');
    }));
  }
  for (const mode of ['pending', 'failed', 'request-failed', 'not-found']) {
    it(`QA-F1 keeps ${mode} export retry/check focus during a hold and after settlement`, () => using(async f => {
      f.set(mode === 'request-failed' ? { exportError: true } : { exportStatus: mode === 'not-found' ? 'pending' : mode });
      await f.page.getByRole('button', { name: 'Request a copy of my data', exact: true }).click();
      await f.page.getByRole('button', { name: 'Dismiss', exact: true }).waitFor();
      if (mode === 'not-found') {
        f.set({ checkError: 404 }); await f.page.getByRole('button', { name: 'Check status', exact: true }).click();
        await f.page.getByText('That request was not found.', { exact: true }).waitFor();
      }
      f.set({ [mode === 'pending' ? 'holdCheck' : 'holdExport']: true, exportStatus: 'complete' });
      await f.page.getByRole('button', { name: mode === 'pending' ? 'Check status' : 'Request again', exact: true }).press('Enter');
      await f.held;
      await f.page.waitForFunction(() => document.querySelector('.v321-privacy__data button:disabled'));
      assert.notEqual(await f.page.evaluate(() => document.activeElement.tagName), 'BODY');
      f.release(); await f.page.getByText('Your export is complete.', { exact: true }).waitFor();
      await f.page.waitForFunction(() => document.activeElement?.getAttribute('role') === 'status');
    }));
  }
  it('QA-F1 recovery retry holds meaningful focus and restores the mobile input', () => using(async f => {
    f.set({ otpError: true }); await f.page.getByRole('button', { name: 'Delete my account', exact: true }).click();
    await f.page.getByText('Re-authentication state is unavailable.', { exact: true }).waitFor();
    f.set({ holdOtp: true }); await f.page.getByRole('button', { name: 'Try again', exact: true }).press('Enter');
    await f.held;
    assert.notEqual(await f.page.evaluate(() => document.activeElement.tagName), 'BODY');
    f.release(); await f.page.getByText('Re-authentication state is unavailable.', { exact: true }).waitFor({ state: 'hidden' });
    await f.page.waitForFunction(() => document.activeElement?.id === 'S-19-mobile');
  }));
  it('QA-F1 re-focuses identical recovery failures without inventing authority', () => using(async f => {
    f.set({ otpError: true }); await f.page.getByRole('button', { name: 'Delete my account', exact: true }).click();
    await f.page.getByText('Re-authentication state is unavailable.', { exact: true }).waitFor();
    for (let attempt = 0; attempt < 2; attempt++) {
      await f.page.getByRole('button', { name: 'Try again', exact: true }).press('Enter');
      await f.page.waitForFunction(() => document.activeElement?.getAttribute('role') === 'alert');
    }
    assert.equal(f.requests.some(r => r.method === 'POST'), false);
  }));
  it('QA-F1 does not steal focus if the user moves away while a retry is held', () => using(async f => {
    f.set({ status: 503 }); await f.page.getByRole('switch', { name: 'Usage analytics' }).click();
    await f.page.locator('[data-privacy-state="network"]').waitFor();
    f.set({ hold: true, status: 503 }); await f.page.getByRole('button', { name: 'Try again', exact: true }).press('Enter');
    await f.held;
    await f.page.locator('.v321-privacy__back').focus();
    f.release(); await f.page.locator('[data-privacy-state="network"]').waitFor();
    assert.equal(await f.page.evaluate(() => document.activeElement.textContent), 'Profile');
  }));
  for (const projection of ['unavailable', 'expired', 'locked', 'omitted', 'pending']) {
    it(`QA-F2 handles uniform 401 recovery_failed with ${projection} authority`, () => using(async f => {
      await f.page.getByRole('button', { name: 'Delete my account', exact: true }).click();
      await f.page.getByLabel('Registered mobile number').fill('9876500340');
      await f.page.getByRole('button', { name: 'Send code', exact: true }).click();
      await f.page.getByLabel('Six-digit code').fill('123456');
      f.set({ recoveryFailed: true, omitProjection: projection === 'omitted', recoveryProjection: projection === 'pending' ? pending : projection === 'expired' ? { ...pending, expires_in_seconds: 0 } : projection === 'locked' ? { ...pending, locked_for_seconds: 60 } : idle });
      await f.page.getByRole('button', { name: 'Verify code', exact: true }).click();
      if (projection === 'pending') {
        await f.page.getByText('That code did not match.', { exact: true }).waitFor();
        assert.equal(await f.page.getByRole('button', { name: 'Verify code', exact: true }).isEnabled(), true);
      } else {
        await f.page.getByRole('button', { name: 'Start again', exact: true }).waitFor();
        assert.equal(await f.page.getByRole('button', { name: 'Verify code', exact: true }).count(), 0);
        assert.equal(await f.page.getByText('That code did not match.', { exact: true }).count(), 0);
        if (projection === 'unavailable') assert.match(await f.page.locator('main').innerText(), /code can no longer be verified/i);
        await f.page.getByRole('button', { name: 'Start again', exact: true }).press('Enter');
        await f.page.getByLabel('Registered mobile number').waitFor();
      }
      assert.equal(f.requests.filter(r => r.path.endsWith('/recovery/verify')).length, 1);
      assert.equal(f.requests.filter(r => r.path.endsWith('/privacy/delete')).length, 0);
    }));
  }
  it('QA-F3 preserves reauth_required across auth remount without connection-error wording', () => using(async f => {
    f.set({ deleteStatus: 401, deleteCode: 'reauth_required' });
    await f.page.getByRole('button', { name: 'Delete my account', exact: true }).click();
    await f.page.getByLabel('Registered mobile number').fill('9876500340');
    await f.page.getByRole('button', { name: 'Send code', exact: true }).click();
    await f.page.getByLabel('Six-digit code').fill('123456');
    await f.page.getByRole('button', { name: 'Verify code', exact: true }).click();
    await f.page.getByLabel('Type DELETE to continue').fill('DELETE');
    const remountRead = f.page.waitForResponse(response => response.url().endsWith('/otp/state'));
    await f.page.getByRole('button', { name: 'Request account deletion', exact: true }).click();
    await f.page.getByText('The server did not confirm re-authentication.', { exact: true }).waitFor();
    await remountRead;
    await f.page.evaluate(() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve))));
    assert.doesNotMatch(await f.page.locator('main').innerText(), /Check your connection/);
    assert.equal(await f.page.getByText('Identity confirmed.', { exact: true }).count(), 0, 'denied deletion proof must not retain a contradictory success banner');
    await f.page.getByRole('button', { name: 'Start again', exact: true }).press('Enter');
    await f.page.getByLabel('Registered mobile number').waitFor();
    assert.equal(f.requests.filter(r => r.path.endsWith('/privacy/delete')).length, 1);
    assert.equal(f.requests.some(r => r.path.endsWith('/recovery/complete')), false);
  }));
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
    const stackGap = width >= 900 ? '14px' : '13px';
    for (const selector of ['.v321-privacy__deletion', '.v321-privacy__form']) {
      assert.equal(await f.page.locator(selector).evaluate(el => getComputedStyle(el).gap), stackGap,
        'frozen source uses a 14px desktop stack, not the 13px mobile stack');
    }
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
  for (const width of [390, 1440]) it(`keeps the rejected-code error in the frozen 5px field-help spacing at ${width}px`, () => using(async f => {
    await f.page.setViewportSize({ width, height: 1024 });
    f.set({ verifyRejected: true });
    await f.page.getByRole('button', { name: 'Delete my account', exact: true }).click();
    await f.page.getByLabel('Registered mobile number').fill('9876500340');
    await f.page.getByRole('button', { name: 'Send code', exact: true }).click();
    await f.page.getByLabel('Six-digit code').fill('123456');
    await f.page.getByRole('button', { name: 'Verify code', exact: true }).click();
    await f.page.getByText('That code did not match.', { exact: true }).waitFor();
    const field = await f.page.locator('.v321-privacy__field').boundingBox();
    const error = await f.page.locator('.v321-privacy__field-error').boundingBox();
    assert.equal(error.y - field.y - field.height, 5, 'inline error belongs to the field, not the outer form stack');
    assert.equal(await f.page.getByLabel('Six-digit code').inputValue(), '123456');
    assert.equal(await f.page.getByRole('button', { name: 'Verify code', exact: true }).isEnabled(), true);
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
  for (const [status, code, title] of [
    [409, 'concurrent_state_changed', 'Something changed on your account while this was processing.'],
    [422, 'invalid_confirmation', 'Type DELETE in capital letters.'],
    [503, 'unavailable', 'Could not submit the deletion request.'],
  ]) it(`preserves the specific ${status} deletion notice across the real auth-transition remount`, () => using(async f => {
    f.set({ deleteStatus: status, deleteCode: code });
    await f.page.getByRole('button', { name: 'Delete my account', exact: true }).click();
    await f.page.getByLabel('Registered mobile number').fill('9876500340');
    await f.page.getByRole('button', { name: 'Send code', exact: true }).click();
    await f.page.getByLabel('Six-digit code').fill('123456');
    await f.page.getByRole('button', { name: 'Verify code', exact: true }).click();
    await f.page.getByLabel('Type DELETE to continue').fill('DELETE');
    await f.page.getByRole('button', { name: 'Request account deletion', exact: true }).click();
    await f.page.getByText(title, { exact: true }).waitFor();
    assert.equal(new URL(f.page.url()).pathname, '/s-19');
    assert.equal(await f.page.getByText('DELETION REQUEST ACCEPTED', { exact: true }).count(), 0);
    assert.equal(await f.page.getByLabel('Type DELETE to continue').inputValue(), '');
    assert.equal(await f.page.getByRole('button', { name: 'Request account deletion', exact: true }).isDisabled(), true);
    const deletionIndex = f.requests.findIndex(r => r.path.endsWith('/privacy/delete'));
    const subsequent = f.requests.slice(deletionIndex + 1);
    assert.equal(subsequent.some(r => r.path.endsWith('/session') && r.method === 'GET'), true, 'auth transition still reconciles server authority');
    assert.equal(subsequent.some(r => r.path.endsWith('/otp/state') && r.method === 'GET'), true, 'remounted route re-reads recovery authority');
    assert.equal(f.requests.filter(r => r.path.endsWith('/privacy/delete')).length, 1, 'no automatic deletion retry');
    assert.equal(f.requests.some(r => r.path.endsWith('/recovery/complete')), false);
    if (status === 409) assert.equal(await f.page.getByText('Could not submit the deletion request.', { exact: true }).count(), 0);
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
