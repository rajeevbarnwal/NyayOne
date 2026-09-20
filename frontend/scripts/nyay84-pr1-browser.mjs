// PR1 synthetic transport + real React/browser navigation. Not independent QA.
import assert from 'node:assert/strict';
import { writeFileSync } from 'node:fs';
import { chromium } from 'playwright';
import axe from 'axe-core';
import { actor, projection } from './lib/nyay66-fixtures.mjs';

const origin = process.env.NYAY84_WEB_BASE ?? 'http://127.0.0.1:4484';
const browser = await chromium.launch({ headless: true });
const results = [];
const pending = purpose => ({ status: 'pending', purpose, destination_masked: '••••••0340', attempts_left: 3, expires_in_seconds: 300, resend_in_seconds: 0, locked_for_seconds: 0, resend_allowed: true });
const authenticated = purpose => ({ status: 'authenticated', purpose, destination_masked: null, attempts_left: null, expires_in_seconds: null, resend_in_seconds: null, locked_for_seconds: null, resend_allowed: false, onboarding: projection('S-07-popup') });
const deferred = () => { let resolve; const promise = new Promise(r => { resolve = r; }); return { promise, resolve }; };
const bounded = promise => Promise.race([promise, new Promise((_, reject) => { const t = setTimeout(() => reject(Error('handshake timeout')), 8000); t.unref(); })]);

async function check(kind, outcome, depart) {
  const context = await browser.newContext({ viewport: { width: 390, height: 844 }, reducedMotion: 'reduce', serviceWorkers: 'block' });
  const page = await context.newPage(); page.setDefaultTimeout(8000);
  const started = deferred(), release = deferred(), finished = deferred();
  const errors = [], unexpected = [];
  let a11y = null;
  let isAuthenticated = ['personal', 'academic', 'interests', 'logout'].includes(kind);
  let probeUnavailable = false;
  const id = kind === 'personal' ? 'S-10' : kind === 'academic' ? 'S-10-academic' : kind === 'interests' ? 'S-11' : 'S-07-popup';
  let profile = projection(id);
  const purpose = ['signup', 'register'].includes(kind) ? 'signup' : 'login';
  const endpoint = kind === 'register' ? '/auth/student/register' : kind === 'login' ? '/auth/student/login/otp/verify' : kind === 'signup' ? '/auth/student/otp/verify' : kind === 'logout' ? '/auth/student/logout' : `/student/profile/${kind}`;
  await page.addInitScript(() => {
    window.__pr1 = { paths: [], settled: 0 };
    for (const name of ['pushState', 'replaceState']) {
      const original = history[name].bind(history);
      history[name] = (...args) => { const value = original(...args); window.__pr1.paths.push(location.pathname + location.search); return value; };
    }
    const fetch = window.fetch.bind(window);
    window.fetch = async (...args) => { try { return await fetch(...args); } finally { window.__pr1.settled += 1; } };
  });
  page.on('pageerror', e => errors.push(e.message));
  await page.route('**/*', async route => {
    const req = route.request(), url = new URL(req.url());
    const json = (body, status = 200) => route.fulfill({ status, contentType: 'application/json', body: JSON.stringify(body) });
    if (url.origin !== origin) { unexpected.push('outbound'); return route.abort(); }
    if (!url.pathname.startsWith('/api/')) return route.continue();
    const path = url.pathname.slice('/api/v1'.length);
    if (path === endpoint && req.method() !== 'GET') {
      started.resolve(); await release.promise;
      try {
        if (outcome === 'failure') return await json({ detail: { code: kind === 'logout' ? 'service_unavailable' : 'invalid_input' } }, kind === 'logout' ? 503 : 422);
        if (kind === 'register') return await json({ status: 'accepted', next: 'otp', expires_in_seconds: 300, resend_after_seconds: 30 }, 202);
        if (['login', 'signup'].includes(kind)) { isAuthenticated = true; return await json(authenticated(purpose)); }
        if (kind === 'logout') {
          if (outcome === 'success') isAuthenticated = false;
          if (outcome === 'probe-unavailable') probeUnavailable = true;
          return await json({});
        }
        const body = req.postDataJSON(); const { expected_profile_version: version, ...values } = body;
        profile = projection(kind === 'personal' ? 'S-10-academic' : kind === 'academic' ? 'S-11' : 'S-12');
        profile.profile_version = version + 1;
        profile.profile[kind] = values;
        return await json(profile);
      } finally { finished.resolve(); }
    }
    if (path === '/auth/student/session') return probeUnavailable ? route.abort('connectionrefused') : json({ authenticated: isAuthenticated, actor: isAuthenticated ? actor : null });
    if (path === '/auth/student/otp/state') return json(pending(purpose));
    if (path === '/auth/student/login/channels') return json({ channels: [{ channel: 'mobile', enabled: true }, { channel: 'email', enabled: true }] });
    if (path === '/student/profile') return json(profile);
    if (path.endsWith('/email-identities')) return json({ identities: [], login_channel_enabled: true, max_identities: 3 });
    if (path === '/calendar/view-preferences') return json({ view_mode: 'week', source_types: [], from_date: null, to_date: null, timezone: 'Asia/Kolkata', version: 1, updated_at: '2026-09-20T00:00:00Z' });
    if (path === '/calendar/events') return json({ items: [], total: 0, failed_sources: [] });
    unexpected.push(`${req.method()} ${path}`); return json({}, 404);
  });
  try {
    await page.goto(origin + '/s-03');
    await page.locator('[data-screen="S-03"]').waitFor();
    const target = kind === 'register' ? '/s-08' : kind === 'login' ? '/s-05' : kind === 'signup' ? '/s-09' : kind === 'logout' ? '/s-07' : kind === 'interests' ? '/s-11' : kind === 'academic' ? '/s-10?section=academic' : '/s-10?section=personal';
    await page.evaluate(target => { history.pushState({ key: 'pr1-entry' }, '', target); dispatchEvent(new PopStateEvent('popstate')); }, target);
    if (kind === 'register') {
      for (const [field, value] of [['first','Synthetic'], ['last','Student'], ['mobile','9000000084'], ['dob','2000-01-01']]) await page.locator('#v34-' + field).fill(value);
      await page.locator('#v34-terms').check(); await page.locator('#v34-privacy').check();
      await page.getByRole('button', { name: 'Create Account', exact: true }).click();
    } else if (['login', 'signup'].includes(kind)) {
      await page.getByRole('textbox', { name: 'Six digit code', exact: true }).fill('123456');
      await page.getByRole('button', { name: /Verify.*Continue/i }).click();
    } else if (kind === 'logout') await page.getByRole('button', { name: 'Sign out', exact: true }).click();
    else {
      if (kind === 'personal') { await page.locator('#profile-personal-language').selectOption('en'); await page.locator('#profile-personal-city').fill('Synthetic City'); }
      if (kind === 'academic') { await page.locator('#profile-academic-college').selectOption({ index: 1 }); await page.locator('#profile-academic-year').selectOption({ index: 1 }); await page.locator('#profile-academic-enrolment').fill('KA/1234/2023'); }
      if (kind === 'interests') { await page.locator('#profile-interests-first-option').click(); await page.locator('#profile-interests-goal').selectOption({ index: 1 }); }
      await page.getByRole('button', { name: kind === 'interests' ? 'Finish setup' : 'Save & continue', exact: true }).click();
    }
    await bounded(started.promise);
    if (depart) { await page.goBack(); await page.waitForURL(origin + '/s-03'); await page.locator('[data-screen="S-03"]').waitFor(); }
    const count = await page.evaluate(() => window.__pr1.settled);
    const pathCount = await page.evaluate(() => window.__pr1.paths.length);
    release.resolve(); await bounded(finished.promise);
    await page.waitForFunction(count => window.__pr1.settled > count, count);
    // Wait for promise parsing, auth-probe completion and React effects, not a product delay.
    await page.waitForFunction(() => !document.querySelector('[data-testid="student-session-pending"]'));
    await page.evaluate(() => new Promise(r => requestAnimationFrame(() => requestAnimationFrame(r))));
    if (depart) {
      assert.equal(new URL(page.url()).pathname, '/s-03');
      assert.deepEqual(await page.evaluate(n => window.__pr1.paths.slice(n), pathCount), [], 'late completion must not navigate, even transiently');
      assert.equal(await page.getByRole('alert').count(), 0);
    }
    else if (outcome === 'success') {
      const destination = kind === 'register' ? '/s-09' : ['login','signup'].includes(kind) ? '/s-07' : kind === 'logout' ? '/s-03' : kind === 'personal' ? '/s-10?section=academic' : kind === 'academic' ? '/s-11' : '/s-12';
      await page.waitForURL(origin + destination);
    } else if (kind === 'logout') {
      await page.getByText('Sign out could not be confirmed.', { exact: false }).waitFor();
      assert.equal(new URL(page.url()).pathname, '/s-07');
      assert.equal(isAuthenticated, true);
    } else assert.equal(new URL(page.url()).pathname + new URL(page.url()).search, target);
    if (kind === 'logout' && !depart && outcome !== 'success') {
      await page.addScriptTag({ content: axe.source });
      const audit = await page.evaluate(() => window.axe.run());
      a11y = audit.violations.map(v => ({ id: v.id, impact: v.impact }));
      assert.deepEqual(a11y.filter(v => ['serious', 'critical'].includes(v.impact)), []);
    }
    assert.deepEqual(unexpected, []); assert.deepEqual(errors, []);
    results.push({ kind, outcome, depart, pass: true, a11y, evidence: 'synthetic API / real browser navigation' });
  } catch (e) { results.push({ kind, outcome, depart, pass: false, message: e.message, url: page.url(), errors, unexpected }); }
  finally { release.resolve(); console.log(JSON.stringify(results.at(-1))); await context.close(); }
}
try {
  for (const kind of ['register','login','signup','personal','academic','interests','logout']) {
    if (process.env.NYAY84_CASE && process.env.NYAY84_CASE !== kind) continue;
    const outcomes = kind === 'logout' ? ['success','failure','probe-authenticated','probe-unavailable'] : ['success','failure'];
    for (const outcome of outcomes) for (const depart of [false,true]) await check(kind,outcome,depart);
  }
  const report = { evidence: 'Synthetic transport; real production build/browser. Not independent QA or real backend proof.', origin, results, pass: results.filter(r => r.pass).length, fail: results.filter(r => !r.pass).length };
  if (process.env.NYAY84_RESULTS) writeFileSync(process.env.NYAY84_RESULTS, JSON.stringify(report, null, 2) + '\n', { flag: 'wx' });
  console.log(JSON.stringify({ pass: report.pass, fail: report.fail }));
  if (results.some(r => !r.pass)) process.exitCode = 1;
} finally { await browser.close(); }
