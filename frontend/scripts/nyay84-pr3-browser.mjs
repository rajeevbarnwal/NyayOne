// PR3 developer regression: synthetic API, production React, real Chromium.
// Explicitly enable label-in-name; axe's default rules do not cover it.
// This does not substitute for independent Claude QA or screen-reader testing.
import assert from 'node:assert/strict';
import { mkdir, writeFile } from 'node:fs/promises';
import { chromium } from 'playwright';
import axe from 'axe-core';
import { actor, projection } from './lib/nyay66-fixtures.mjs';

const origin = process.env.NYAY84_WEB_BASE ?? 'http://127.0.0.1:4487';
const output = process.env.NYAY84_OUTPUT;
if (output) await mkdir(output, { recursive: true });
const browser = await chromium.launch({ headless: true });
const results = [];
const pendingId = '00000000-0000-4000-8000-000000000031';
const verifiedId = '00000000-0000-4000-8000-000000000032';
const identities = [
  { id: pendingId, email_masked: 'p•••••@example.test', state: 'pending', is_primary: false, verification: { status: 'active', expires_in_seconds: 300, resend_in_seconds: 0, attempts_left: 3 } },
  { id: verifiedId, email_masked: 'v•••••@example.test', state: 'verified', is_primary: false, verification: { status: 'none', expires_in_seconds: null, resend_in_seconds: null, attempts_left: null } },
];
const rules = ['label-content-name-mismatch', 'landmark-complementary-is-top-level', 'landmark-one-main', 'landmark-main-is-top-level'];
const frames = p => p.evaluate(() => new Promise(r => requestAnimationFrame(() => requestAnimationFrame(r))));
async function audit(p, selected = rules) {
  await p.addScriptTag({ content: axe.source });
  return p.evaluate(async ruleIds => (await window.axe.run(document, { runOnly: { type: 'rule', values: ruleIds } })).violations.map(v => ({ id: v.id, nodes: v.nodes.map(n => n.target) })), selected);
}
async function named(locator, text) {
  assert.equal(await locator.getAttribute('aria-label'), text);
  // The browser-computed accessibility tree must expose the same name.
  assert.ok((await locator.ariaSnapshot()).includes(text), `computed name omits ${text}`);
}
async function check(name, screen, probe, options = {}) {
  const viewport = options.desktop ? { width: 1440, height: 1024 } : { width: 390, height: 844 };
  const context = await browser.newContext({ viewport, reducedMotion: 'reduce', locale: 'en-IN', timezoneId: 'Asia/Kolkata' });
  const page = await context.newPage(); page.setDefaultTimeout(8000);
  const calls = [], errors = [];
  page.on('pageerror', e => errors.push(e.message));
  await page.clock.setFixedTime(new Date('2025-08-16T09:00:00.000Z'));
  await page.route('**/api/**', async route => {
    const req = route.request(), path = new URL(req.url()).pathname.slice('/api/v1'.length);
    const json = (body, status = 200) => route.fulfill({ status, contentType: 'application/json', body: JSON.stringify(body) });
    if (path === '/auth/student/session') return json({ authenticated: screen !== 'S-06', actor: screen === 'S-06' ? null : { ...actor, is_minor: screen === 'S-16' } });
    if (path === '/student/profile') {
      if (options.profileFailure) return json({}, 503);
      const value = projection(screen === 'S-07' ? 'S-14' : screen);
      if (options.identity) Object.assign(value.profile.personal, options.identity);
      return json(value);
    }
    if (path === '/auth/student/otp/state') return json({ status: 'unavailable', purpose: null, destination_masked: null, attempts_left: null, expires_in_seconds: null, resend_in_seconds: null, locked_for_seconds: null, resend_allowed: false });
    if (path === '/auth/student/email-identities' && req.method() === 'GET') return json({ identities, login_channel_enabled: true, max_identities: 3 });
    if (path === '/calendar/view-preferences') return json({ view_mode: 'week', source_types: [], from_date: null, to_date: null, timezone: 'Asia/Kolkata', version: 1, updated_at: '2026-09-09T12:00:00Z' });
    if (path === '/calendar/events') return json({ items: [], total: 0, failed_sources: [] });
    if (req.method() !== 'GET') { calls.push(path); return json({ detail: { code: 'validation_error' } }, 422); }
    return json({}, 404);
  });
  try {
    await page.goto(`${origin}/${screen.toLowerCase()}`);
    await page.locator(`[data-screen="${screen === 'S-07' ? 'S-14' : screen}"]`).waitFor();
    await probe(page, calls);
    assert.deepEqual(errors, []);
    results.push({ name, screen, viewport, pass: true });
  } catch (error) { results.push({ name, screen, viewport, pass: false, message: error.message, errors }); }
  finally { console.log(JSON.stringify(results.at(-1))); await context.close(); }
}
async function capture(p, name) {
  await p.evaluate(async () => { await document.fonts.ready; await Promise.all([...document.images].map(img => img.decode())); });
  await frames(p);
  if (output) await p.screenshot({ path: `${output}/${name}.png`, animations: 'disabled' });
}
try {
  for (const desktop of [false, true]) {
    const size = desktop ? 'desktop' : 'mobile390';
    for (const screen of ['S-07', 'S-10', 'S-11', 'S-12', 'S-13', 'S-14', 'S-15', 'S-16', 'S-17']) {
      await check(`${size} shared avatar visible label, computed name and keyboard route`, screen, async p => {
        const avatar = p.locator('.v321-profile__avatar');
        await p.waitForFunction(() => document.querySelector('.v321-profile__avatar')?.textContent === 'SS');
        await capture(p, `${screen}-${size}`);
        await named(avatar, 'SS · Your Profile · Synthetic Student');
        await avatar.focus(); await avatar.press(desktop ? 'Enter' : 'Space'); await p.waitForURL('**/s-17');
        await p.locator('[data-screen="S-17"]').waitFor();
        assert.deepEqual(await audit(p), []);
      }, { desktop });
    }
    await check(`${size} S06 brand retains readable content without nested landmark`, 'S-06', async p => {
      await p.getByRole('button', { name: 'Send recovery code', exact: true }).waitFor();
      await capture(p, `S-06-${size}`);
      assert.equal(await p.getByRole('main').count(), 1);
      assert.equal(await p.locator('main aside, main [role="complementary"]').count(), 0);
      assert.equal(await p.locator('div.s06-r2__brand').count(), 1);
      assert.ok(await p.locator('.s06-r2__brand').innerText());
      assert.deepEqual(await audit(p), []);
      // Negative control: reproducing the old semantic nesting must be detected.
      await p.locator('.s06-r2__brand').evaluate(el => el.setAttribute('role', 'complementary'));
      assert.ok((await audit(p)).some(v => v.id === 'landmark-complementary-is-top-level'));
    }, { desktop });
  }
  for (const [first_name, middle_name, last_name] of [['अनन्या', 'कुमारी', 'नायर'], ['李', null, '王'], ['Élodie', null, 'Åström'], ['𠮷', null, '野'], ['A\u0301\u0302'.normalize('NFC'), null, 'Ng']]) {
    await check('Accepted Unicode identity keeps displayed initials in computed name', 'S-17', async p => {
      const avatar = p.locator('.v321-profile__avatar');
      await p.locator('.v321-profile-summary__identity').waitFor();
      const visible = await avatar.innerText();
      const fullName = [first_name, middle_name, last_name].filter(Boolean).join(' ').trim();
      await named(avatar, `${visible} · Your Profile${fullName ? ` · ${fullName}` : ''}`);
      assert.deepEqual(await audit(p, ['label-content-name-mismatch']), []);
    }, { identity: { first_name, middle_name, last_name } });
  }
  await check('Unavailable identity has truthful P fallback and working keyboard route', 'S-17', async p => {
    const avatar = p.locator('.v321-profile__avatar');
    await named(avatar, 'P · Your Profile'); assert.equal(await avatar.innerText(), 'P');
    await avatar.focus(); await avatar.press('Enter'); assert.equal(new URL(p.url()).pathname, '/s-17');
  }, { profileFailure: true });
  await check('Privacy Centre visible name and Enter route; original mismatch is detected', 'S-17', async p => {
    const privacy = p.locator('.v321-profile-summary__privacy button');
    await named(privacy, 'Privacy Centre');
    assert.deepEqual(await audit(p, ['label-content-name-mismatch']), []);
    const avatar = p.locator('.v321-profile__avatar');
    await avatar.evaluate(el => el.setAttribute('aria-label', 'Your Profile · Synthetic Student'));
    assert.ok((await audit(p, ['label-content-name-mismatch'])).some(v => v.id === 'label-content-name-mismatch'));
    await avatar.evaluate(el => el.setAttribute('aria-label', 'SS · Your Profile · Synthetic Student'));
    await privacy.evaluate(el => el.setAttribute('aria-label', 'Privacy & settings'));
    assert.ok((await audit(p, ['label-content-name-mismatch'])).some(v => v.id === 'label-content-name-mismatch'));
    await privacy.evaluate(el => el.setAttribute('aria-label', 'Privacy Centre'));
    await privacy.focus(); await privacy.press('Enter'); await p.waitForURL('**/s-19');
  });
  await check('Email disclosure and actions match visible labels; keyboard activation preserves authority', 'S-17', async (p, calls) => {
    const disclosure = p.getByTestId('profile-email-identity-disclosure');
    await named(disclosure, 'Manage sign-in emails');
    await disclosure.focus(); await disclosure.press('Enter');
    await named(disclosure, 'Hide sign-in emails');
    assert.equal(await disclosure.getAttribute('aria-expanded'), 'true');
    const panel = p.getByTestId('profile-email-identities'); await panel.waitFor();
    const add = panel.locator(':scope > .st-actions > button'); await named(add, 'Add email');
    const primary = p.getByRole('button', { name: 'Make primary sign-in email v•••••@example.test', exact: true });
    await primary.waitFor();
    assert.equal(await p.getByRole('button', { name: 'Verify email p•••••@example.test', exact: true }).isEnabled(), false);
    assert.deepEqual(await audit(p, ['label-content-name-mismatch']), []);
    // Both previously misleading labels are detectable with the explicit rule.
    await disclosure.evaluate(el => el.setAttribute('aria-label', 'Manage sign-in emails'));
    await add.evaluate(el => el.setAttribute('aria-label', 'Add sign-in email'));
    const negatives = await audit(p, ['label-content-name-mismatch']);
    assert.ok(negatives.some(v => v.nodes.length >= 2));
    await disclosure.evaluate(el => el.setAttribute('aria-label', 'Hide sign-in emails'));
    await add.evaluate(el => el.setAttribute('aria-label', 'Add email'));
    await primary.focus(); await primary.press('Enter'); await p.getByRole('alert').waitFor();
    assert.equal(calls.length, 1); assert.ok(calls[0].endsWith(`/${verifiedId}/primary`));
    await disclosure.focus(); await disclosure.press('Space'); await named(disclosure, 'Manage sign-in emails');
    assert.equal(await disclosure.getAttribute('aria-expanded'), 'false');
    await disclosure.press('Enter'); await named(disclosure, 'Hide sign-in emails');
  });
  const report = { head: process.env.NYAY84_HEAD ?? 'local-uncommitted', limitations: 'Developer synthetic API/Chromium emulation. Not independent QA, real backend, physical device or screen-reader speech. Explicit label-in-name and landmark checks include negative controls.', results, pass: results.filter(r => r.pass).length, fail: results.filter(r => !r.pass).length };
  if (output) await writeFile(`${output}/results.json`, JSON.stringify(report, null, 2) + '\n');
  console.log(JSON.stringify({ pass: report.pass, fail: report.fail })); if (report.fail) process.exitCode = 1;
} finally { await browser.close(); }
