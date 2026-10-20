// Local Chromium + synthetic API regression evidence. Not hosted parity or live-backend QA.
import { before, after, it } from 'node:test';
import { setTimeout as delay } from 'node:timers/promises';
import assert from 'node:assert/strict';
import { readFile, mkdir } from 'node:fs/promises';
import { preview } from 'vite';
import { chromium } from 'playwright';
import { actor } from './lib/nyay66-fixtures.mjs';
import { S20_LISTINGS } from './lib/nyay66-s20-fixtures.mjs';
let server, browser, origin;
before(async () => { server = await preview({ preview: { host: '127.0.0.1', port: 0 }, logLevel: 'error' }); origin = `http://127.0.0.1:${server.httpServer.address().port}`; browser = await chromium.launch(); });
after(async () => { await browser?.close(); await new Promise(done => server?.httpServer.close(done)); });
const item = { ...S20_LISTINGS[0], tags: ['Research'], source: { name: 'Synthetic organisation submission', url: 'https://example.test/listing', retrieved_at: null, verified_at: null } };
async function using(run, { saved = false, width = 390, detailStatus = 200, mutationStatus = 200, savedStatus = 200, malformedMutation = false, malformedDetail = false } = {}) {
  const context = await browser.newContext({ viewport: { width, height: 844 }, locale: 'en-IN', timezoneId: 'Asia/Kolkata', reducedMotion: 'reduce' });
  const page = await context.newPage(); page.setDefaultTimeout(6000);
  const s = { saved, detailStatus, mutationStatus, savedStatus, malformedMutation, authenticated: true, mutations: [], reads: 0, holdMutation: false, holdRead: false, heldMutation: null, heldRead: null, unexpected: [] };
  await page.route('**/*', async route => {
    const req = route.request(), url = new URL(req.url()), method = req.method();
    if (url.origin !== origin && !(url.origin === 'http://localhost:1131' && url.pathname.startsWith('/api/v1/'))) { s.unexpected.push(url.origin); return route.abort(); }
    if (!url.pathname.startsWith('/api/v1/')) return route.continue();
    const reply = (body, status = 200) => route.fulfill({ status, contentType: 'application/json', body: JSON.stringify(body) });
    if (url.pathname === '/api/v1/auth/student/session') return reply(s.authenticated ? { authenticated: true, actor } : { authenticated: false, actor: null });
    if (url.pathname === '/api/v1/internships') return reply({ items: [item], total: 1, page: 1, page_size: 20 });
    if (url.pathname === `/api/v1/internships/${item.id}`) {
      if (s.detailStatus === 0) return route.abort('failed');
      return reply(s.detailStatus === 200 ? malformedDetail ? {} : item : { detail: { code: s.detailStatus === 404 ? 'internship_listing_not_found' : 'unavailable' } }, s.detailStatus);
    }
    if (url.pathname === '/api/v1/student/internships/saved') {
      if (s.savedStatus !== 200) return reply({ detail: { code: 'unavailable' } }, s.savedStatus);
      s.reads++; const snapshot = { items: s.saved ? [item] : [] };
      if (s.holdRead) { s.holdRead = false; s.heldRead = () => reply(snapshot).catch(() => undefined); return; }
      return reply(snapshot);
    }
    if (url.pathname === `/api/v1/student/internships/${item.id}/saved` && ['PUT', 'DELETE'].includes(method)) {
      s.mutations.push(method);
      const finish = () => {
        if (s.mutationStatus === 200) { s.saved = method === 'PUT'; return reply(s.malformedMutation ? {} : { listing_id: item.id, saved: s.saved }); }
        if (s.mutationStatus === 401) s.authenticated = false;
        return reply({ detail: { code: s.mutationStatus === 401 ? 'authentication_required' : 'unavailable' } }, s.mutationStatus);
      };
      if (s.holdMutation) { s.heldMutation = finish; return; }
      return finish();
    }
    s.unexpected.push(`${method} ${url.pathname}`); return route.abort();
  });
  try { await run(page, s); assert.deepEqual(s.unexpected, []); }
  catch (error) { console.error('Synthetic S-21 diagnostic', { url: page.url(), body: (await page.locator('body').innerText()).slice(0, 3000), reads: s.reads, unexpected: s.unexpected }); throw error; }
  finally { await context.close(); }
}
const detailUrl = () => `${origin}/s-21?listing=${item.id}`;
async function heldMutation(s) {
  const deadline = Date.now() + 6000;
  while (!s.heldMutation && Date.now() < deadline) await delay(10);
  assert.equal(typeof s.heldMutation, 'function', 'synthetic mutation must reach the server before release');
}
async function ready(page, saved = false) { const b = page.getByRole('button', { name: saved ? 'Saved' : 'Save listing', exact: true }); await b.waitFor(); await page.waitForFunction(() => document.querySelector('.s21-actions button')?.getAttribute('aria-disabled') === 'false'); return b; }
for (const saved of [false, true]) it(`R2-1: delayed ${saved ? 'DELETE' : 'PUT'} and pre-commit GET cannot overwrite the confirmed mark on S-20`, { timeout: 20000 }, () => using(async (page, s) => {
  await page.goto(detailUrl()); const b = await ready(page, saved); s.holdMutation = true;
  await b.evaluate(el => { el.click(); el.click(); });
  await page.waitForFunction(() => document.querySelector('[aria-busy="true"]'));
  await heldMutation(s);
  assert.equal(s.mutations.length, 1); assert.equal(s.saved, saved);
  s.holdRead = true; await page.getByRole('button', { name: 'Back to internships', exact: true }).click();
  await page.waitForFunction(() => document.querySelector('.s20-save:disabled'));
  assert.ok(s.heldMutation); assert.ok(s.heldRead);
  await s.heldMutation();
  await page.waitForFunction(want => document.querySelector('.s20-save')?.getAttribute('aria-pressed') === String(want), !saved);
  await s.heldRead();
  // Drain rendering after deliberately delivering the stale snapshot last.
  await page.evaluate(() => new Promise(r => requestAnimationFrame(() => requestAnimationFrame(r))));
  assert.equal(await page.locator('.s20-save').getAttribute('aria-pressed'), String(!saved));
  assert.equal(s.mutations.length, 1);
  await page.getByRole('button', { name: 'Saved internships', exact: true }).first().click();
  if (!saved) await page.getByText(`${item.role} — ${item.organisation}`, { exact: true }).waitFor();
  else await page.getByText('No saved internships yet', { exact: true }).waitFor();
}, { saved }));
it('save failure focuses the truthful notice; retry restores truth, never sends another mutation', { timeout: 20000 }, () => using(async (page, s) => {
  await page.goto(detailUrl()); const b = await ready(page); s.holdMutation = true;
  await b.focus(); await page.keyboard.press('Enter'); await page.waitForFunction(() => document.querySelector('[aria-busy="true"]'));
  await heldMutation(s);
  assert.equal(await page.evaluate(() => document.activeElement?.tagName), 'BUTTON');
  await s.heldMutation(); await page.getByRole('alert').waitFor();
  await page.waitForFunction(() => document.activeElement?.getAttribute('role') === 'alert');
  assert.equal(s.saved, false); assert.equal(s.mutations.length, 1);
  await page.getByRole('button', { name: 'Reload saved state' }).click(); await ready(page);
  assert.notEqual(await page.evaluate(() => document.activeElement?.tagName), 'BODY');
  assert.equal(s.mutations.length, 1);
}, { mutationStatus: 503 }));
for (const saved of [false, true]) it(`focus handoff survives a frame before the ${saved ? 'DELETE' : 'PUT'} error commit`, { timeout: 20000 }, () => using(async (page, s) => {
  await page.goto(detailUrl()); const b = await ready(page, saved); s.holdMutation = true;
  await b.focus(); await page.keyboard.press('Enter'); await heldMutation(s);
  await page.waitForFunction(() => document.querySelector('[aria-busy="true"]'));
  // Scheduler negative control, not a capture fixture: force the next frame
  // callback to run before React can commit the response-driven state update.
  // The old handoff consumes ownership here while the error notice is absent.
  await page.evaluate(() => {
    const nativeFrame = window.requestAnimationFrame;
    window.__s21EarlyFrame = null;
    window.requestAnimationFrame = callback => {
      window.requestAnimationFrame = nativeFrame;
      window.__s21EarlyFrame = {
        busy: !!document.querySelector('[aria-busy="true"]'),
        alert: !!document.querySelector('.s21-detail [role="alert"]'),
      };
      callback(performance.now());
      return 0;
    };
  });
  await s.heldMutation(); await page.getByRole('alert').waitFor();
  try {
    await page.waitForFunction(() => document.activeElement?.getAttribute('role') === 'alert', null, { polling: 25 });
  } catch (error) {
    console.error('S-21 pre-commit frame ordering', await page.evaluate(() => window.__s21EarlyFrame));
    throw error;
  }
  assert.equal(s.saved, saved);
  assert.deepEqual(s.mutations, [saved ? 'DELETE' : 'PUT']);
  assert.equal(await page.locator('.s21-actions button').first().getAttribute('aria-pressed'), null);
}, { saved, mutationStatus: 503 }));
it('does not steal focus if the user moves away during a pending save', { timeout: 20000 }, () => using(async (page, s) => {
  await page.goto(detailUrl()); const b = await ready(page); s.holdMutation = true;
  await b.click(); await page.waitForFunction(() => document.querySelector('[aria-busy="true"]'));
  await heldMutation(s);
  await page.getByRole('button', { name: 'Back to internships', exact: true }).focus();
  await s.heldMutation(); await page.getByRole('alert').waitFor();
  assert.equal(await page.evaluate(() => document.activeElement?.getAttribute('aria-label')), 'Back to internships');
}, { mutationStatus: 503 }));
it('offline rejection and repeated failed saves each focus their committed notice', { timeout: 20000 }, () => using(async (page, s) => {
  await page.goto(detailUrl()); await ready(page);
  await page.context().setOffline(true);
  await page.getByRole('button', { name: 'Save listing', exact: true }).press('Enter');
  await page.getByText('You are offline. No request was sent. Reconnect and try again.', { exact: true }).waitFor();
  await page.waitForFunction(() => document.activeElement?.getAttribute('role') === 'alert');
  assert.deepEqual(s.mutations, []);
  await page.context().setOffline(false);
  for (let attempt = 1; attempt <= 2; attempt++) {
    await (await ready(page)).press('Enter');
    await page.getByText('Could not confirm this change. Reload your saved list before trying again.', { exact: true }).waitFor();
    await page.waitForFunction(() => document.activeElement?.getAttribute('role') === 'alert');
    assert.equal(s.mutations.length, attempt);
    await page.getByRole('button', { name: 'Reload saved state' }).press('Enter'); await ready(page);
    await page.waitForFunction(() => document.activeElement?.tagName === 'H1');
  }
}, { mutationStatus: 503 }));
for (const saved of [false, true]) it(`successful ${saved ? 'DELETE' : 'PUT'} retains focus on its confirmed toggle`, { timeout: 20000 }, () => using(async (page, s) => {
  await page.goto(detailUrl()); const b = await ready(page, saved); s.holdMutation = true;
  await b.press('Enter'); await heldMutation(s);
  assert.equal(await page.getByRole('button', { name: 'Saving', exact: true }).evaluate(el => document.activeElement === el), true);
  await s.heldMutation(); const confirmed = await ready(page, !saved);
  assert.equal(await confirmed.evaluate(el => document.activeElement === el), true);
  assert.equal(s.mutations.length, 1);
}, { saved }));
it('Apply stays unavailable; return context is restricted to the approved routes', { timeout: 20000 }, () => using(async page => {
  await page.goto(detailUrl() + '&from=s25'); await ready(page);
  const apply = page.getByRole('button', { name: 'Apply', exact: true }); assert.equal(await apply.getAttribute('aria-disabled'), 'true');
  await apply.evaluate(el => el.click()); assert.equal(new URL(page.url()).pathname, '/s-21');
  await page.getByRole('button', { name: 'Back to saved internships' }).click(); assert.equal(new URL(page.url()).pathname, '/s-25');
}));
it('failed saved-list read is unavailable, never false unsaved, and reload restores server truth', { timeout: 20000 }, () => using(async (page, s) => {
  await page.goto(detailUrl()); await page.getByText('Your saved state is unavailable.', { exact: true }).waitFor();
  const button = page.locator('.s21-actions button').first();
  assert.equal(await button.getAttribute('aria-pressed'), null);
  await button.evaluate(el => { el.click(); el.click(); }); assert.equal(s.mutations.length, 0);
  s.savedStatus = 200; await page.getByRole('button', { name: 'Reload saved state' }).click(); await ready(page, true);
  assert.notEqual(await page.evaluate(() => document.activeElement?.tagName), 'BODY');
}, { saved: true, savedStatus: 503 }));
it('malformed 2xx cannot announce a successful save; reload reads the authoritative outcome', { timeout: 20000 }, () => using(async (page, s) => {
  await page.goto(detailUrl()); await (await ready(page)).click();
  await page.getByRole('alert').waitFor();
  assert.equal(await page.getByRole('status').innerText(), '');
  assert.equal(await page.locator('.s21-actions button').first().getAttribute('aria-pressed'), null);
  await page.getByRole('button', { name: 'Reload saved state' }).click(); await ready(page, true);
  assert.equal(s.mutations.length, 1);
}, { malformedMutation: true }));
it('401 transitions to truthful sign-in state and retains meaningful focus through remount', { timeout: 20000 }, () => using(async page => {
  await page.goto(detailUrl()); await (await ready(page)).click();
  await page.getByText('Sign in to save listings.', { exact: true }).waitFor();
  await page.waitForFunction(() => document.activeElement?.getAttribute('role') === 'alert');
  assert.equal(await page.locator('.s21-actions button').first().getAttribute('aria-pressed'), null);
}, { mutationStatus: 401 }));
it('missing identity and 404 do not substitute a sample; failed retry keeps meaningful focus', { timeout: 20000 }, () => using(async (page, s) => {
  await page.goto(origin + '/s-21'); await page.getByText('Listing unavailable', { exact: true }).waitFor();
  s.detailStatus = 404; await page.goto(detailUrl()); await page.getByText('This listing is no longer available.', { exact: true }).waitFor();
  s.detailStatus = 503; await page.reload(); await page.getByRole('button', { name: 'Retry', exact: true }).click();
  await page.waitForFunction(() => document.activeElement?.getAttribute('role') === 'alert');
  assert.equal(await page.getByText(item.role, { exact: true }).count(), 0);
}));
for (const width of [320, 390, 1440]) it(`layout/axe diagnostic at ${width}px`, { timeout: 20000 }, () => using(async page => {
  await page.goto(detailUrl()); await ready(page); await page.evaluate(() => document.fonts.ready);
  assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), true);
  assert.equal(await page.locator('main').count(), 1);
  await page.addScriptTag({ content: await readFile('node_modules/axe-core/axe.min.js', 'utf8') });
  const violations = await page.evaluate(async () => (await window.axe.run()).violations.filter(v => ['serious', 'critical'].includes(v.impact)).map(v => ({ id: v.id, nodes: v.nodes.map(n => n.target) })));
  assert.deepEqual(violations, []);
  assert.equal(await page.locator('.s21-actions button').evaluateAll(nodes => nodes.every(n => n.getBoundingClientRect().height >= 48)), true);
  await mkdir('/private/tmp/NYAY93-S21-initial-diagnostic', { recursive: true });
  await page.screenshot({ path: `/private/tmp/NYAY93-S21-initial-diagnostic/s21-${width}.png`, fullPage: true });
}, { width }));
for (const status of [404, 429, 500, 503]) it(`shows genuine detail HTTP ${status}, not an invented generic 500`, () => using(async page => {
  await page.goto(detailUrl()); await page.getByRole('alert').waitFor();
  assert.equal(await page.locator('.s21-detail .s20-code').innerText(), `HTTP ${status}`);
}, { detailStatus: status }));
for (const scenario of ['transport', 'malformed-2xx', 'invalid-link']) it(`does not fabricate an HTTP error status for ${scenario}`, () => using(async page => {
  await page.goto(scenario === 'invalid-link' ? origin + '/s-21' : detailUrl());
  await page.getByRole('alert').waitFor();
  assert.equal(await page.locator('.s21-detail .s20-code').count(), 0);
}, { detailStatus: scenario === 'transport' ? 0 : 200, malformedDetail: scenario === 'malformed-2xx' }));
for (const width of [390, 1440]) it(`S-21-specific chip spacing and action decoration at ${width}px`, () => using(async page => {
  await page.goto(detailUrl()); await ready(page);
  assert.equal(await page.locator('.s21-card p').first().evaluate(el => getComputedStyle(el).fontSize), '13.5px');
  assert.equal(await page.locator('.s21-card p').first().evaluate(el => getComputedStyle(el).lineHeight), '20.925px');
  assert.equal(await page.locator('.s21-source').evaluate(el => getComputedStyle(el).fontSize), '12px');
  assert.equal(await page.locator('.s21-kvs').evaluate(el => getComputedStyle(el).fontFamily.includes('NyayOne S21 Rupee')), true);
  assert.equal(await page.evaluate(() => [...document.fonts].some(face => face.family === 'NyayOne S21 Rupee' && face.weight === '700' && face.unicodeRange === 'U+20B9')), true);
  assert.equal(await page.locator('.s20-chips').evaluate(el => getComputedStyle(el).marginTop), '0px');
  assert.equal(await page.locator('.s21-tag').count(), item.tags.length);
  assert.equal(await page.locator('.s21-tag').first().evaluate(el => getComputedStyle(el).color), 'rgb(46, 58, 140)');
  assert.equal(await page.locator('.s21-tag > [aria-hidden="true"]').count(), item.tags.length);
  assert.equal(await page.locator('.s21-icon--send').count(), 2);
  assert.equal(await page.getByRole('link', { name: 'Open source listing (opens Synthetic organisation submission in a new tab)', exact: true }).count(), 1);
  assert.equal(await page.locator('.s21-actions > button').first().locator('.s21-action-indigo').count(), 1);
  await page.getByRole('button', { name: 'Save listing', exact: true }).click(); await ready(page, true);
  assert.equal(await page.locator('.s21-action-gold').evaluate(el => getComputedStyle(el).color), 'rgb(122, 92, 20)');
}, { width }));
it('failed-save risk and session warning use their own tokens without changing focus or mutation count', () => using(async (page, s) => {
  await page.goto(detailUrl()); await (await ready(page)).click(); await page.getByRole('alert').waitFor();
  assert.equal(await page.getByRole('alert').evaluate(el => getComputedStyle(el).borderLeftColor), 'rgb(154, 43, 33)');
  assert.equal(s.mutations.length, 1);
  s.mutationStatus = 401; await page.getByRole('button', { name: 'Reload saved state' }).click(); await ready(page);
  await page.getByRole('button', { name: 'Save listing', exact: true }).click();
  await page.getByText('Sign in to save listings.', { exact: true }).waitFor();
  await page.waitForFunction(() => document.activeElement?.getAttribute('role') === 'alert');
  assert.equal(await page.getByRole('alert').evaluate(el => getComputedStyle(el).borderLeftColor), 'rgb(122, 90, 16)');
  assert.equal(await page.locator('.s21-icon--lock').count(), 1);
  assert.equal(await page.locator('.s21-icon--login').count(), 1);
  assert.equal(s.mutations.length, 2);
}, { mutationStatus: 503 }));
