// Synthetic, local production-build regression probes; not hosted parity or independent QA.
import { before, after, it } from 'node:test';
import assert from 'node:assert/strict';
import { readFile, mkdir } from 'node:fs/promises';
import { setTimeout as delay } from 'node:timers/promises';
import { preview } from 'vite';
import { chromium } from 'playwright';
import { actor } from './lib/nyay66-fixtures.mjs';
import { S20_LISTINGS } from './lib/nyay66-s20-fixtures.mjs';
let server, browser, origin;
before(async () => { server = await preview({ preview: { host: '127.0.0.1', port: 0 }, logLevel: 'error' }); origin = `http://127.0.0.1:${server.httpServer.address().port}`; browser = await chromium.launch(); });
after(async () => { await browser?.close(); await new Promise(done => server?.httpServer.close(done)); });
async function using(run, options = {}) {
  const context = await browser.newContext({ viewport: { width: options.width ?? 390, height: 844 }, locale: 'en-IN', timezoneId: 'Asia/Kolkata', reducedMotion: 'reduce' });
  const page = await context.newPage(); page.setDefaultTimeout(5000);
  const s = { saved: [], status: 200, malformed: false, authenticated: true, sessionStatus: 200, actor, holdRead: false, heldRead: null, reads: 0, unexpected: [], ...options };
  await page.route('**/*', async route => {
    const req = route.request(), url = new URL(req.url());
    if (url.origin !== origin && !(url.origin === 'http://localhost:1131' && url.pathname.startsWith('/api/v1/'))) { s.unexpected.push(url.origin); return route.abort(); }
    if (!url.pathname.startsWith('/api/v1/')) return route.continue();
    const reply = (body, status = 200) => route.fulfill({ status, contentType: 'application/json', body: JSON.stringify(body) }).catch(() => undefined);
    if (url.pathname === '/api/v1/auth/student/session') return reply(s.authenticated ? { authenticated: true, actor: s.actor } : { authenticated: false, actor: null }, s.sessionStatus);
    if (url.pathname === '/api/v1/internships') return reply({ items: S20_LISTINGS, total: S20_LISTINGS.length, page: 1, page_size: 20 });
    if (url.pathname === '/api/v1/student/internships/saved' && req.method() === 'GET') {
      s.reads++; const snapshot = s.malformed ? {} : { items: [...s.saved] }, status = s.status;
      const finish = () => { if (status === 401) s.authenticated = false; return reply(status === 200 ? snapshot : { detail: { code: status === 401 ? 'authentication_required' : 'unavailable' } }, status); };
      if (s.holdRead) { s.holdRead = false; s.heldRead = finish; return; } return finish();
    }
    s.unexpected.push(`${req.method()} ${url.pathname}`); return route.abort();
  });
  try { await run(page, s); assert.deepEqual(s.unexpected, []); }
  catch (error) { console.error({ url: page.url(), body: (await page.locator('body').innerText()).slice(0, 1800), unexpected: s.unexpected }); throw error; }
  finally { await context.close(); }
}
async function held(s) { const until = Date.now() + 5000; while (!s.heldRead && Date.now() < until) await delay(10); assert.equal(typeof s.heldRead, 'function'); }
const root = page => page.locator('.s26-recovery');
const retry = page => page.getByRole('button', { name: 'Retry', exact: true });
const diagnosticDir = process.env.S26_DIAGNOSTIC_DIR;
it('pending saved GET makes no empty claim; empty response offers browse only', () => using(async (page, s) => {
  await page.goto(origin + '/s-26'); await held(s);
  await page.getByRole('status', { name: 'Loading saved internships' }).waitFor();
  assert.equal(await page.getByText('No saved internships yet.').count(), 0);
  await s.heldRead(); await page.getByRole('heading', { name: 'No saved internships yet.' }).waitFor();
  await page.getByRole('button', { name: 'Browse internships', exact: true }).click();
  await page.waitForURL('**/s-20');
}, { holdRead: true }));
it('nonempty count uses server truth and opens S-25 without a mutation', () => using(async page => {
  await page.goto(origin + '/s-26'); await page.getByRole('heading', { name: 'You have 2 saved internships.' }).waitFor();
  await page.getByRole('button', { name: 'Open saved internships' }).click();
  await page.waitForURL('**/s-25'); await page.locator('.s25-saved article').first().waitFor();
  assert.equal(await page.locator('.s25-saved article').count(), 2);
}, { saved: S20_LISTINGS.slice(0, 2) }));
for (const status of [403, 404, 409, 429, 500, 503]) it(`HTTP ${status} is not empty or a fabricated 500`, () => using(async page => {
  await page.goto(origin + '/s-26'); await root(page).getByRole('alert').waitFor();
  assert.equal(await root(page).getByText(`HTTP ${status}`, { exact: true }).count(), 1);
  assert.equal(await page.getByText('No saved internships yet.').count(), 0);
}, { status }));
it('malformed 200 fails closed without displaying HTTP 200 or zero saved', () => using(async page => {
  await page.goto(origin + '/s-26'); await root(page).getByRole('alert').waitFor();
  assert.equal(await root(page).getByText('HTTP 200').count(), 0);
  assert.equal(await page.getByText('No saved internships yet.').count(), 0);
}, { malformed: true }));
it('initial error and repeated failed retries focus the alert; pending Retry remains focusable and locked', () => using(async (page, s) => {
  await page.goto(origin + '/s-26'); await root(page).getByRole('alert').waitFor();
  await page.waitForFunction(() => document.activeElement?.getAttribute('role') === 'alert');
  for (let n = 0; n < 2; n++) {
    s.heldRead = null; s.holdRead = true; const before = s.reads;
    await retry(page).focus(); await retry(page).evaluate(el => { el.click(); el.click(); el.click(); }); await held(s);
    assert.equal(s.reads, before + 1); assert.equal(await retry(page).evaluate(el => el === document.activeElement), true);
    assert.equal(await retry(page).getAttribute('aria-disabled'), 'true');
    await s.heldRead(); await page.waitForFunction(() => document.activeElement?.getAttribute('role') === 'alert');
  }
  s.status = 200; await retry(page).press('Enter'); await page.getByRole('heading', { name: 'No saved internships yet.' }).waitFor();
  await page.waitForFunction(() => document.activeElement?.tagName === 'H1');
}, { status: 503 }));
it('completion does not steal focus after the user moves elsewhere', () => using(async (page, s) => {
  await page.goto(origin + '/s-26'); await retry(page).waitFor(); s.holdRead = true;
  await retry(page).press('Enter'); await held(s); const profile = page.getByRole('button', { name: 'Your Profile', exact: true }); await profile.focus();
  await s.heldRead(); await page.waitForFunction(() => document.querySelector('.s26-recovery button[aria-disabled]')?.getAttribute('aria-disabled') === 'false');
  assert.equal(await profile.evaluate(el => document.activeElement === el), true);
}, { status: 503 }));
it('offline retries send no request and repeated attempts still return meaningful focus', () => using(async (page, s) => {
  await page.goto(origin + '/s-26'); await retry(page).waitFor(); const before = s.reads; await page.context().setOffline(true);
  for (let n = 0; n < 2; n++) { await retry(page).press('Enter'); await page.waitForFunction(() => document.activeElement?.getAttribute('role') === 'alert'); }
  assert.equal(s.reads, before); assert.match(await root(page).innerText(), /No request was sent/);
  assert.equal(await root(page).getByText('HTTP 500').count(), 0);
}, { status: 503 }));
it('401 during Retry clears account claims and hands focus through the auth remount', () => using(async (page, s) => {
  await page.goto(origin + '/s-26'); await retry(page).waitFor(); s.status = 401; await retry(page).press('Enter');
  await page.getByText('Sign in to view saved internships', { exact: true }).waitFor();
  await page.waitForFunction(() => document.activeElement?.getAttribute('role') === 'alert');
  assert.equal(await page.getByText('No saved internships yet.').count(), 0);
}, { status: 503 }));
it('failed session authority never sends saved-list GET or claims empty', () => using(async (page, s) => {
  await page.goto(origin + '/s-26'); await root(page).getByRole('alert').waitFor();
  assert.equal(s.reads, 0); assert.equal(await page.getByText('No saved internships yet.').count(), 0);
}, { sessionStatus: 503 }));
it('a late read after leaving S-26 does not redirect or restore stale recovery UI', () => using(async (page, s) => {
  await page.goto(origin + '/s-26'); await held(s);
  await page.evaluate(() => { history.pushState({}, '', '/s-20'); dispatchEvent(new PopStateEvent('popstate')); });
  await page.waitForURL('**/s-20'); await s.heldRead();
  await page.getByRole('heading', { name: 'Browse internships.' }).waitFor();
  assert.equal(await root(page).count(), 0); assert.equal(new URL(page.url()).pathname, '/s-20');
}, { holdRead: true }));
it('forward/reverse keyboard order is logical and decorative/legal content is inert', () => using(async page => {
  await page.goto(origin + '/s-26'); await page.getByRole('heading', { name: 'No saved internships yet.' }).waitFor();
  const profile = page.getByRole('button', { name: 'Your Profile' }); const browse = page.getByRole('button', { name: 'Browse internships', exact: true });
  await profile.focus(); await page.keyboard.press('Tab'); assert.equal(await browse.evaluate(el => el === document.activeElement), true);
  await page.keyboard.press('Shift+Tab'); assert.equal(await profile.evaluate(el => el === document.activeElement), true);
  assert.equal(await root(page).locator('footer button,footer a,[aria-hidden=true][tabindex="0"]').count(), 0);
}));
it('shared saved-query invalidation on S-25 removal is visible on back navigation', () => using(async (page, s) => {
  await page.goto(origin + '/s-26'); await page.getByRole('heading', { name: 'You have 2 saved internships.' }).waitFor();
  await page.getByRole('button', { name: 'Open saved internships' }).click(); await page.locator('.s25-saved article').first().waitFor();
  await page.route('**/api/v1/student/internships/*/saved', route => { const id = route.request().url().split('/').at(-2); s.saved = s.saved.filter(i => i.id !== id); return route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ listing_id: id, saved: false }) }); });
  await page.getByRole('button', { name: `Remove ${s.saved[0].role} from saved`, exact: true }).click();
  await page.waitForFunction(() => document.querySelectorAll('.s25-saved article').length === 1);
  await page.goBack(); await page.getByRole('heading', { name: 'You have 1 saved internship.' }).waitFor();
}, { saved: S20_LISTINGS.slice(0, 2) }));
for (const width of [320, 390, 1440]) it(`single shell, 48px targets, reflow and serious/critical axe at ${width}px`, () => using(async page => {
  await page.goto(origin + '/S-26/?test=1#state'); await page.getByRole('heading', { name: 'No saved internships yet.' }).waitFor();
  assert.equal(await page.locator('main').count(), 1); assert.equal(await page.locator('h1').count(), 1);
  assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), true);
  const targets = await root(page).getByRole('button').evaluateAll(nodes => nodes.map(el => el.getBoundingClientRect()).filter(r => r.width && r.height));
  assert.ok(targets.every(r => r.width >= 48 && r.height >= 48));
  await page.addScriptTag({ content: await readFile(new URL('../node_modules/axe-core/axe.min.js', import.meta.url), 'utf8') });
  const audit = await page.evaluate(async () => window.axe.run(document.querySelector('.s26-recovery')));
  assert.deepEqual(audit.violations.filter(v => ['serious', 'critical'].includes(v.impact)).map(v => v.id), []);
}, { width }));
for (const width of [390, 1440]) for (const state of ['loading', 'empty', 'error', 'nonempty']) it(`S-26 ${state} ${width}px synthetic diagnostic and axe`, () => using(async (page, s) => {
  await page.goto(origin + '/s-26');
  if (state === 'loading') { await held(s); await page.getByRole('status', { name: 'Loading saved internships' }).waitFor(); }
  else if (state === 'error') await root(page).getByRole('alert').waitFor();
  else await page.getByRole('heading', { name: state === 'empty' ? 'No saved internships yet.' : 'You have 2 saved internships.' }).waitFor();
  await page.evaluate(() => document.fonts.ready);
  await page.addScriptTag({ content: await readFile(new URL('../node_modules/axe-core/axe.min.js', import.meta.url), 'utf8') });
  const audit = await page.evaluate(async () => window.axe.run(document.querySelector('.s26-recovery')));
  assert.deepEqual(audit.violations.filter(v => ['serious', 'critical'].includes(v.impact)).map(v => v.id), []);
  if (diagnosticDir) { await mkdir(diagnosticDir, { recursive: true }); await page.screenshot({ path: `${diagnosticDir}/s26-${state}-${width}.png`, fullPage: true }); }
}, { width, holdRead: state === 'loading', saved: state === 'nonempty' ? S20_LISTINGS.slice(0, 2) : [], status: state === 'error' ? 503 : 200 }));
