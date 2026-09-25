// PR2 developer regression campaign: synthetic API, real production React/Chromium.
// This is not independent Claude QA, physical-device or real-backend evidence.
import assert from 'node:assert/strict';
import { writeFileSync } from 'node:fs';
import { chromium } from 'playwright';
import axe from 'axe-core';
import { actor, projection } from './lib/nyay66-fixtures.mjs';

const origin = process.env.NYAY84_WEB_BASE ?? 'http://127.0.0.1:4485';
const browser = await chromium.launch({ headless: true });
const results = [];
const identityId = '00000000-0000-4000-8000-000000000084';
async function check(name, screen, probe, options = {}) {
  const context = await browser.newContext({ viewport: { width: 390, height: 844 }, reducedMotion: 'reduce' });
  const page = await context.newPage(); page.setDefaultTimeout(6000);
  const calls = [], errors = []; let reads = 0;
  const start = Date.now();
  const authenticated = screen === 's-17' || screen === 's-07';
  const flow = { status: 'pending', purpose: screen === 's-09' ? 'signup' : 'login', destination_masked: '••••••0340', attempts_left: 3, expires_in_seconds: 300, resend_in_seconds: 0, locked_for_seconds: 0, resend_allowed: true, ...options.flow };
  page.on('pageerror', e => errors.push(e.message));
  await page.route('**/api/**', async route => {
    const req = route.request(), path = new URL(req.url()).pathname.slice('/api/v1'.length);
    const json = (body, status = 200) => route.fulfill({ status, contentType: 'application/json', body: JSON.stringify(body) });
    if (path === '/auth/student/session') return screen === 's-01' ? json({}, 503) : json({ authenticated, actor: authenticated ? actor : null });
    if (path === '/auth/student/otp/state') return json(flow);
    if (path === '/student/profile') return json(projection(screen === 's-17' ? 'S-17' : 'S-07-popup'));
    if (path === '/auth/student/email-identities' && req.method() === 'GET') {
      reads++;
      if (options.cooldownFailure && reads > 1) return json({}, 503);
      return json({ login_channel_enabled: true, max_identities: 3, identities: [{ id: identityId, email_masked: 's•••••@example.edu', state: 'pending', is_primary: false, verification: { status: 'active', expires_in_seconds: 300, resend_in_seconds: options.cooldown ? Math.max(0, 3 - Math.floor((Date.now() - start) / 1000)) : 0, attempts_left: 3 } }] });
    }
    if (req.method() !== 'GET') {
      calls.push(path);
      await new Promise(r => setTimeout(r, 200));
      return json({ detail: { code: 'validation_error' } }, 422);
    }
    return json({}, 404);
  });
  try {
    await page.goto(`${origin}/${screen}`);
    await page.locator(`[data-screen="${screen.toUpperCase()}"]`).waitFor();
    if (screen === 's-17') await page.getByRole('button', { name: 'Manage sign-in emails', exact: true }).click();
    await probe(page, calls, () => reads);
    assert.deepEqual(errors, []);
    results.push({ name, screen, pass: true, mode: 'synthetic API / real production React + Chromium' });
  } catch (e) { results.push({ name, screen, pass: false, message: e.message, calls, errors }); }
  finally { console.log(JSON.stringify(results.at(-1))); await context.close(); }
}
const frames = p => p.evaluate(() => new Promise(r => requestAnimationFrame(() => requestAnimationFrame(r))));
const clickBurst = locator => locator.evaluate(el => { el.click(); el.click(); el.click(); });
const focusIsAlert = p => p.evaluate(() => document.activeElement?.getAttribute('role') === 'alert');

try {
  for (const screen of ['s-05', 's-09']) {
    await check('duplicate Verify is single-flight', screen, async (p, calls) => {
      await p.getByRole('textbox', { name: 'Six digit code', exact: true }).fill('123456');
      await clickBurst(p.getByRole('button', { name: 'Verify and continue', exact: true }));
      await p.getByRole('alert').waitFor(); assert.equal(calls.length, 1);
    });
    await check('duplicate Resend is single-flight', screen, async (p, calls) => {
      await clickBurst(p.getByRole('button', { name: 'Resend Code', exact: true }));
      await p.getByRole('alert').waitFor(); assert.equal(calls.length, 1);
    });
    await check('Enter submits once and repeated errors refocus/reannounce', screen, async (p, calls) => {
      const input = p.getByRole('textbox', { name: 'Six digit code', exact: true });
      await input.fill('123456');
      for (let i = 0; i < 2; i++) {
        await input.press('Enter'); await p.getByRole('alert').waitFor(); await frames(p);
        assert.equal(calls.length, i + 1); assert.equal(await focusIsAlert(p), true);
        if (!i) await p.getByRole('alert').evaluate(el => { window.__oldAlert = el; });
      }
      assert.equal(await p.getByRole('alert').evaluate(el => el !== window.__oldAlert), true, 'repeat alert must be a new announcement node');
    });
    for (const [label, flow] of [['expired', { expires_in_seconds: 0 }], ['locked', { locked_for_seconds: 60, resend_allowed: false }], ['exhausted', { attempts_left: 0, resend_allowed: false }]]) {
      await check(`Enter refuses ${label} flow`, screen, async (p, calls) => {
        const input = p.getByRole('textbox', { name: 'Six digit code', exact: true });
        await input.fill('123456'); await input.press('Enter'); await frames(p);
        assert.equal(calls.length, 0); assert.equal(await p.getByRole('button', { name: 'Verify and continue', exact: true }).isEnabled(), false);
      }, { flow });
    }
    await check('failed Resend returns meaningful focus', screen, async p => {
      const resend = p.getByRole('button', { name: 'Resend Code', exact: true });
      for (let i = 0; i < 2; i++) { await resend.focus(); await resend.press('Enter'); await p.getByRole('alert').waitFor(); await frames(p); assert.equal(await focusIsAlert(p), true); }
    });
  }
  await check('S01 failed keyboard Retry restores focus twice', 's-01', async p => {
    const retry = p.getByRole('button', { name: 'Try again', exact: true });
    for (let i = 0; i < 2; i++) { await retry.focus(); await retry.press('Enter'); await retry.waitFor(); await frames(p); assert.equal(await retry.evaluate(el => el === document.activeElement), true); }
  });
  await check('popup first/reverse Tab and cyclic order', 's-07', async p => {
    await p.getByRole('dialog').waitFor();
    const order = ['Close profile prompt', 'Complete Profile', 'Maybe Later', 'Sign out'];
    for (const name of [...order, order[0]]) { await p.keyboard.press('Tab'); assert.equal(await p.getByRole('button', { name, exact: true }).evaluate(el => el === document.activeElement), true, name); }
    for (const name of [...order].reverse()) { await p.keyboard.press('Shift+Tab'); assert.equal(await p.getByRole('button', { name, exact: true }).evaluate(el => el === document.activeElement), true, name); }
    await p.locator('#profile-completion-dialog-title').focus(); await p.keyboard.press('Shift+Tab');
    assert.equal(await p.getByRole('button', { name: 'Sign out', exact: true }).evaluate(el => el === document.activeElement), true);
  });
  await check('popup repeated failed dismissal reannounces', 's-07', async p => {
    const later = p.getByRole('button', { name: 'Maybe Later', exact: true });
    for (let i = 0; i < 2; i++) { await later.click(); await p.getByRole('alert').waitFor(); await frames(p); assert.equal(await focusIsAlert(p), true); }
  });
  await check('email duplicate Add is single-flight', 's-17', async (p, calls) => {
    await p.locator('#profile-email-identity-input').fill('synthetic@example.edu');
    await clickBurst(p.getByRole('button', { name: 'Add email', exact: true }));
    await p.getByRole('alert').waitFor(); assert.equal(calls.length, 1);
  });
  await check('email Enter + repeated invalid/error focus', 's-17', async (p, calls) => {
    const input = p.locator('#profile-email-identity-input');
    for (let i = 0; i < 2; i++) {
      await input.fill('not-an-email'); await input.press('Enter'); await p.getByRole('alert').waitFor(); await frames(p);
      assert.equal(await focusIsAlert(p), true); assert.equal(calls.length, 0);
      if (!i) await p.getByRole('alert').evaluate(el => { window.__oldAlert = el; });
    }
    assert.equal(await p.getByRole('alert').evaluate(el => el !== window.__oldAlert), true);
    await input.fill('synthetic@example.edu'); await input.press('Enter'); await p.getByRole('alert').waitFor(); await frames(p);
    assert.equal(calls.length, 1); assert.equal(await focusIsAlert(p), true);
  });
  await check('email Verify Enter is single-flight', 's-17', async (p, calls) => {
    const input = p.locator(`#profile-email-identity-code-${identityId}`); await input.fill('123456'); await input.press('Enter');
    await p.getByRole('alert').waitFor(); assert.equal(calls.length, 1); assert.equal(await focusIsAlert(p), true);
  });
  await check('email cooldown refetches authority and enables after expiry', 's-17', async (p, calls, reads) => {
    const resend = p.getByRole('button', { name: /^Resend code to/ }); await resend.waitFor(); assert.equal(await resend.isEnabled(), false);
    await p.waitForFunction(() => [...document.querySelectorAll('button')].some(b => b.textContent === 'Resend code' && !b.disabled));
    assert.ok(reads() >= 2); assert.equal(calls.length, 0);
  }, { cooldown: true });
  await check('email cooldown read failure never grants resend', 's-17', async (p, calls, reads) => {
    const resend = p.getByRole('button', { name: /^Resend code to/ }); await resend.waitFor();
    await p.waitForTimeout(3600); assert.ok(reads() >= 2); assert.equal(await resend.isEnabled(), false); assert.equal(calls.length, 0);
  }, { cooldown: true, cooldownFailure: true });
  await check('email error state automated accessibility', 's-17', async p => {
    await p.locator('#profile-email-identity-input').fill('invalid'); await p.getByRole('button', { name: 'Add email', exact: true }).click();
    await p.getByRole('alert').waitFor(); await p.addScriptTag({ content: axe.source });
    const issues = await p.evaluate(async () => (await window.axe.run()).violations.filter(v => ['serious', 'critical'].includes(v.impact)).map(v => v.id)); assert.deepEqual(issues, []);
  });
  const report = { head: process.env.NYAY84_HEAD ?? 'local-uncommitted', limitations: 'Synthetic API and desktop Chromium emulation; not independent QA, backend proof, physical keyboard or screen-reader speech.', results, pass: results.filter(r => r.pass).length, fail: results.filter(r => !r.pass).length };
  if (process.env.NYAY84_RESULTS) writeFileSync(process.env.NYAY84_RESULTS, JSON.stringify(report, null, 2)+'\n', { flag: 'wx' });
  console.log(JSON.stringify({ pass: report.pass, fail: report.fail })); if (report.fail) process.exitCode = 1;
} finally { await browser.close(); }
