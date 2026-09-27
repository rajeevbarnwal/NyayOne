// PR4 developer regression: production React + Chromium, synthetic APIs only.
// This is routing/contrast evidence, not independent QA or reference conformance.
import assert from 'node:assert/strict';
import { mkdir, writeFile } from 'node:fs/promises';
import { chromium } from 'playwright';
import axe from 'axe-core';
import { actor, projection } from './lib/nyay66-fixtures.mjs';

const origin = process.env.NYAY84_WEB_BASE ?? 'http://127.0.0.1:4488';
const output = process.env.NYAY84_OUTPUT;
if (output) await mkdir(output, { recursive: true });
const browser = await chromium.launch({ headless: true });
const results = [];
const publicScreens = new Set([1, 2, 3, 4, 5, 6, 8, 9, 20, 21, 25, 26]);
const tick = page => page.evaluate(() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve))));

async function check(name, probe, { screen = 12, desktop = false, phase = 'authenticated', incomplete = false } = {}) {
  if (process.env.NYAY84_CASE_FILTER && !name.includes(process.env.NYAY84_CASE_FILTER)) return;
  const context = await browser.newContext({ viewport: desktop ? { width: 1440, height: 1024 } : { width: 390, height: 844 }, reducedMotion: 'reduce' });
  const page = await context.newPage(); page.setDefaultTimeout(8000);
  await page.clock.setFixedTime(new Date('2025-08-16T09:00:00Z'));
  const errors = [], mutations = [], evidence = {};
  let releaseSession;
  const heldSession = new Promise(resolve => { releaseSession = resolve; });
  page.on('pageerror', error => errors.push(error.message));
  await page.route('**/*', async route => {
    const request = route.request(), url = new URL(request.url());
    if (url.origin !== origin) { errors.push('OUTBOUND_REQUEST'); return route.abort(); }
    if (!url.pathname.startsWith('/api/')) return route.continue();
    const path = url.pathname.slice('/api/v1'.length);
    const json = (body, status = 200) => route.fulfill({ status, contentType: 'application/json', body: JSON.stringify(body) });
    if (path === '/auth/student/session') {
      if (phase === 'held') await heldSession;
      if (phase === 'unavailable') return json({}, 503);
      const authenticated = !publicScreens.has(screen) && phase !== 'anonymous';
      const identity = phase === 'wrong-role'
        ? { ...actor, roles: ['moderator'], student_profile_id: null, consent_state: [] }
        : { ...actor, roles: phase === 'nonstudent-projection' ? ['lawyer'] : ['student'], is_minor: screen === 16 };
      return json({ authenticated, actor: authenticated ? identity : null });
    }
    if (request.method() !== 'GET') { mutations.push(path); return json({}, 503); }
    if (path === '/student/profile') return json(projection(incomplete ? 'S-10' : `S-${String(screen).padStart(2, '0')}`));
    if (path.endsWith('/login/channels')) return json({ channels: [{ channel: 'mobile', enabled: true }, { channel: 'email', enabled: true }] });
    if (path.endsWith('/otp/state')) return json({ status: 'pending', purpose: screen === 9 ? 'signup' : 'login', destination_masked: '••••••0340', attempts_left: 3, expires_in_seconds: 272, resend_in_seconds: 0, locked_for_seconds: 0, resend_allowed: true });
    if (path.endsWith('/email-identities')) return json({ identities: [], login_channel_enabled: true, max_identities: 5 });
    if (path === '/calendar/view-preferences') return json({ view_mode: 'week', source_types: [], from_date: null, to_date: null, timezone: 'Asia/Kolkata', version: 1, updated_at: '2026-09-09T12:00:00Z' });
    if (path === '/calendar/events') return json({ items: [], total: 0, failed_sources: [] });
    return json({}, 404);
  });
  try {
    await probe(page, releaseSession, evidence);
    assert.deepEqual(errors, []);
    assert.deepEqual(mutations, [], 'shell selection must not mutate server state');
    results.push({ name, screen, desktop, phase, pass: true, evidence });
  } catch (error) { results.push({ name, screen, desktop, phase, pass: false, message: error.message, errors, evidence }); }
  finally { releaseSession(); console.log(JSON.stringify(results.at(-1))); await context.close(); }
}
async function shellReady(page) {
  await page.locator('.ls-v34-content, .v34-screen--continuation, .ls-shell').waitFor();
  await page.evaluate(() => document.fonts.ready); await tick(page);
}
async function noLegacy(page) {
  assert.equal(await page.locator('.ls-shell, .ls-rail, .ls-bnav, .ls-topbar').count(), 0);
  assert.equal(await page.getByRole('main').count(), 1);
}
async function contrast(page) {
  await page.addScriptTag({ content: axe.source });
  return page.evaluate(async () => (await window.axe.run(document, { runOnly: ['color-contrast'] })).violations.map(v => ({ id: v.id, impact: v.impact, targets: v.nodes.map(n => n.target) })));
}

try {
  // Full shell ownership smoke: all currently screen-owned/continuation routes.
  for (let screen = 1; screen <= 26; screen++) {
    const canonical = `/s-${String(screen).padStart(2, '0')}`;
    for (const url of [canonical, `${canonical.toUpperCase()}/?qa=synthetic#section`]) {
      await check(`routing smoke ${url}`, async page => {
        await page.goto(origin + url); await shellReady(page); await noLegacy(page);
        if (screen >= 18) {
          assert.equal(await page.locator('.v34-screen--continuation').count(), 1);
          assert.equal(await page.locator('.v34-screen--continuation').getAttribute('data-v34-screen'), `S-${screen}`);
        }
      }, { screen });
    }
  }
  for (const desktop of [false, true]) {
    for (const screen of [11, 12, 17]) {
      const canonical = `/s-${screen}`;
      for (const [variant, url] of Object.entries({ canonical, uppercase: canonical.toUpperCase(), slash: canonical + '/', combined: `${canonical.toUpperCase()}///?qa=synthetic#details` })) {
        await check(`focused P16 ${screen} ${variant} ${desktop ? 'desktop' : 'mobile'}`, async (page, _release, evidence) => {
          await page.goto(origin + url); await page.locator(`[data-screen="S-${screen}"] .v321-profile__avatar`).waitFor();
          await shellReady(page);
          evidence.legacyChrome = await page.locator('.ls-shell').count();
          evidence.navigationLandmarks = await page.getByRole('navigation').count();
          evidence.contrast = await contrast(page);
          if (output && screen === 12) await page.screenshot({ path: `${output}/S-12-${variant}-${desktop ? 'desktop' : 'mobile'}.png`, animations: 'disabled' });
          await noLegacy(page);
          assert.equal(new URL(page.url()).pathname + new URL(page.url()).search + new URL(page.url()).hash, url);
          assert.deepEqual(evidence.contrast, []);
          await page.reload(); await page.locator(`[data-screen="S-${screen}"] .v321-profile__avatar`).waitFor(); await noLegacy(page);
          if (screen === 12) {
            await page.getByRole('button', { name: 'Go to Dashboard', exact: true }).click(); await page.waitForURL('**/s-14');
            await page.goBack(); await page.locator('[data-screen="S-12"]').waitFor(); await noLegacy(page);
            assert.equal(new URL(page.url()).pathname + new URL(page.url()).search + new URL(page.url()).hash, url);
          }
        }, { screen, desktop });
      }
    }
  }
  for (const phase of ['held', 'anonymous', 'unavailable', 'nonstudent-projection', 'wrong-role']) {
    for (const url of ['/s-12', '/S-12/?qa=synthetic#details']) {
      await check(`auth barrier ${phase} ${url}`, async (page, release) => {
        await page.goto(origin + url);
        if (phase === 'held') {
          await page.getByTestId('student-session-pending').waitFor();
          assert.equal(await page.locator('.ls-v34-content, .ls-shell, [data-screen="S-12"]').count(), 0);
          release(); await page.locator('[data-screen="S-12"]').waitFor(); await noLegacy(page);
        } else if (phase === 'anonymous') {
          await page.waitForURL('**/s-03'); await page.locator('[data-screen="S-03"]').waitFor();
          await noLegacy(page);
        } else {
          // A nonstudent wire projection is rejected by the existing strict
          // session decoder before the guard; it must not mount private content.
          await page.getByTestId(phase === 'wrong-role' ? 'student-route-wrong-role' : 'student-session-unavailable').waitFor();
          assert.equal(await page.locator('.ls-v34-content, .ls-shell, [data-screen="S-12"]').count(), 0);
        }
      }, { phase });
    }
  }
  for (const url of ['/s-12', '/S-12/?qa=synthetic#details']) {
    await check(`incomplete profile redirect ${url}`, async page => {
      await page.goto(origin + url); await page.waitForURL('**/s-10?section=personal');
      await page.locator('[data-screen="S-10"]').waitFor(); await noLegacy(page);
    }, { incomplete: true });
  }
  const report = { head: process.env.NYAY84_HEAD ?? 'local-uncommitted', origin, results, pass: results.filter(r => r.pass).length, fail: results.filter(r => !r.pass).length, limitations: 'Developer routing smoke and focused contrast probes; synthetic APIs, Chromium emulation. Not independent Claude QA, real backend, physical device or screen-reader speech. PNGs are diagnostic, not hosted reference conformance.' };
  if (output) await writeFile(`${output}/results.json`, JSON.stringify(report, null, 2) + '\n');
  console.log(JSON.stringify({ pass: report.pass, fail: report.fail }));
  if (report.fail) process.exitCode = 1;
} finally { await browser.close(); }
