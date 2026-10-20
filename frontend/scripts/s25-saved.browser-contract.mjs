// Local synthetic Chromium regression evidence; not hosted parity or independent QA.
import { before, after, it } from 'node:test';
import assert from 'node:assert/strict';
import { readFile, mkdtemp } from 'node:fs/promises';
import { setTimeout as delay } from 'node:timers/promises';
import { preview } from 'vite';
import { chromium } from 'playwright';
import { actor } from './lib/nyay66-fixtures.mjs';
import { S20_LISTINGS } from './lib/nyay66-s20-fixtures.mjs';
let server, browser, origin;
const diagnosticDir = await mkdtemp('/private/tmp/NYAY94-S25-browser-');
const items = S20_LISTINGS.slice(0, 2);
before(async () => { server = await preview({ preview: { host: '127.0.0.1', port: 0 }, logLevel: 'error' }); origin = `http://127.0.0.1:${server.httpServer.address().port}`; browser = await chromium.launch(); });
after(async () => { await browser?.close(); await new Promise(done => server?.httpServer.close(done)); console.log('Synthetic diagnostics:', diagnosticDir); });
async function using(run, options = {}) {
  const context = await browser.newContext({ viewport: { width: options.width ?? 390, height: 844 }, locale: 'en-IN', timezoneId: 'Asia/Kolkata', reducedMotion: 'reduce' });
  const page = await context.newPage(); page.setDefaultTimeout(6000);
  const s = { saved: [...items], status: 200, mutationStatus: 200, authenticated: true, holdRead: false, holdMutation: false, heldRead: null, heldMutation: null, reads: 0, mutations: [], commitError: false, malformed: false, unexpected: [], ...options };
  await page.route('**/*', async route => {
    const req = route.request(), url = new URL(req.url()), method = req.method();
    if (url.origin !== origin && !(url.origin === 'http://localhost:1131' && url.pathname.startsWith('/api/v1/'))) { s.unexpected.push(url.origin); return route.abort(); }
    if (!url.pathname.startsWith('/api/v1/')) return route.continue();
    const reply = (body, status = 200) => route.fulfill({ status, contentType: 'application/json', body: JSON.stringify(body) }).catch(() => undefined);
    if (url.pathname === '/api/v1/auth/student/session') return reply(s.authenticated ? { authenticated: true, actor } : { authenticated: false, actor: null });
    if (url.pathname === '/api/v1/internships') return reply({ items, total: items.length, page: 1, page_size: 20 });
    if (url.pathname === '/api/v1/student/internships/saved') {
      s.reads++; const snapshot = s.malformed ? {} : { items: [...s.saved] }, status = s.status;
      const finish = () => {
        if (status === 401) s.authenticated = false;
        return reply(status === 200 ? snapshot : { detail: { code: status === 401 ? 'authentication_required' : 'unavailable' } }, status);
      };
      if (s.holdRead) { s.holdRead = false; s.heldRead = finish; return; } return finish();
    }
    const listing = items.find(i => url.pathname === `/api/v1/internships/${i.id}`);
    if (listing) return reply(listing);
    const mutationItem = items.find(i => url.pathname === `/api/v1/student/internships/${i.id}/saved`);
    if (mutationItem && ['PUT', 'DELETE'].includes(method)) {
      s.mutations.push({ method, id: mutationItem.id });
      const finish = () => {
        if (s.mutationStatus === 200 || s.commitError) s.saved = s.saved.filter(i => i.id !== mutationItem.id);
        if (s.mutationStatus === 401) s.authenticated = false;
        return reply(s.mutationStatus === 200 ? { listing_id: mutationItem.id, saved: false } : { detail: { code: s.mutationStatus === 401 ? 'authentication_required' : 'unavailable' } }, s.mutationStatus);
      };
      if (s.holdMutation) { s.heldMutation = finish; return; } return finish();
    }
    s.unexpected.push(`${method} ${url.pathname}`); return route.abort();
  });
  try { await run(page, s); assert.deepEqual(s.unexpected, []); }
  catch (error) { console.error('S-25 synthetic diagnostic', { url: page.url(), body: (await page.locator('body').innerText()).slice(0, 2500), unexpected: s.unexpected }); throw error; }
  finally { await context.close(); }
}
const remove = (page, item = items[0]) => page.getByRole('button', { name: `Remove ${item.role} from saved`, exact: true });
async function waitReady(page) { await remove(page).waitFor(); await page.waitForFunction(() => document.querySelector('[data-remove-id]')?.getAttribute('aria-disabled') === 'false'); }
async function ready(page) { await page.goto(origin + '/s-25'); await waitReady(page); }
async function waitHeld(s, key = 'heldMutation') { const until = Date.now() + 6000; while (!s[key] && Date.now() < until) await delay(10); assert.equal(typeof s[key], 'function'); }
it('server-confirmed DELETE only, duplicate lock, focus follows the next saved item', () => using(async (page, s) => {
  await ready(page); s.holdMutation = true;
  await remove(page).focus(); await remove(page).evaluate(el => { el.click(); el.click(); });
  await waitHeld(s);
  assert.deepEqual(s.mutations, [{ method: 'DELETE', id: items[0].id }]);
  assert.equal(await page.locator('.s25-saved article').count(), 2);
  assert.equal(await remove(page).evaluate(el => document.activeElement === el), true);
  await s.heldMutation(); await remove(page, items[1]).waitFor();
  await page.waitForFunction(() => document.querySelectorAll('.s25-saved article').length === 1);
  await page.waitForFunction(() => document.activeElement?.getAttribute('data-remove-id') !== null);
  assert.equal(await remove(page, items[1]).evaluate(el => document.activeElement === el), true);
}));
it('last confirmed removal yields a genuine empty list and meaningful focus', () => using(async page => {
  await ready(page); await remove(page).press('Enter');
  await page.getByRole('heading', { name: 'No saved internships yet.' }).waitFor();
  await page.waitForFunction(() => document.activeElement?.tagName === 'H1');
}, { saved: [items[0]] }));
for (const status of [503, 409, 404]) it(`HTTP ${status} remove is uncertain, focus restored, reload determines truth`, () => using(async (page, s) => {
  await ready(page); await remove(page).press('Enter');
  await page.getByText('Could not confirm removal. Reload your saved list.', { exact: true }).waitFor();
  await page.waitForFunction(() => document.activeElement?.getAttribute('role') === 'alert');
  assert.equal(await remove(page).getAttribute('aria-pressed'), null);
  assert.equal(await remove(page).getAttribute('aria-disabled'), 'true');
  assert.equal(s.mutations.length, 1);
  await page.getByRole('button', { name: 'Reload saved list' }).press('Enter');
  await page.waitForFunction(() => document.querySelector('[data-remove-id]')?.getAttribute('aria-disabled') === 'false');
  assert.equal(await remove(page).getAttribute('aria-pressed'), 'true');
  assert.equal(s.mutations.length, 1);
}, { mutationStatus: status }));
it('a committed DELETE with a lost response cannot resurrect a stale S-21 saved snapshot', { timeout: 20000 }, () => using(async (page, s) => {
  await ready(page); s.holdMutation = true;
  await remove(page).click(); await waitHeld(s);
  s.holdRead = true;
  await page.locator('.s25-saved article').first().getByRole('button', { name: `${items[0].role} ${items[0].organisation}`, exact: true }).click();
  await waitHeld(s, 'heldRead'); await s.heldMutation(); await s.heldRead();
  await page.getByRole('button', { name: 'Save listing', exact: true }).waitFor();
  assert.equal(s.mutations.length, 1);
}, { mutationStatus: 503, commitError: true }));
it('confirmed removal invalidates the S-20 saved marks', () => using(async page => {
  await page.goto(origin + '/s-20');
  await page.waitForFunction(() => document.querySelector('.s20-save')?.getAttribute('aria-pressed') === 'true');
  await page.getByRole('button', { name: 'Saved internships', exact: true }).first().click();
  await waitReady(page);
  await remove(page).press('Enter');
  await page.waitForFunction(() => document.querySelectorAll('.s25-saved article').length === 1);
  await page.getByRole('button', { name: 'Browse internships', exact: true }).first().click();
  await page.waitForFunction(() => document.querySelector('.s20-save')?.getAttribute('aria-pressed') === 'false');
}));
it('error retry stays focusable while pending and focuses the error or loaded heading', () => using(async (page, s) => {
  await page.goto(origin + '/s-25'); await page.getByRole('alert').waitFor();
  s.holdRead = true; await page.getByRole('button', { name: 'Retry', exact: true }).press('Enter'); await waitHeld(s, 'heldRead');
  assert.notEqual(await page.evaluate(() => document.activeElement?.tagName), 'BODY');
  await s.heldRead(); await page.waitForFunction(() => document.activeElement?.getAttribute('role') === 'alert');
  s.status = 200;
  await page.getByRole('button', { name: 'Retry', exact: true }).press('Enter');
  await remove(page).waitFor(); await page.waitForFunction(() => document.activeElement?.tagName === 'H1');
}, { status: 503 }));
it('pending failure never steals focus after the user chooses another control', () => using(async (page, s) => {
  await ready(page); s.holdMutation = true; await remove(page).press('Enter'); await waitHeld(s);
  const browse = page.getByRole('button', { name: 'Browse internships', exact: true }).first();
  await browse.focus(); await s.heldMutation(); await page.getByRole('alert').waitFor();
  assert.equal(await browse.evaluate(el => document.activeElement === el), true);
}, { mutationStatus: 503 }));
it('session expiry hides account data and restores focus through the remount', () => using(async page => {
  await ready(page); await remove(page).press('Enter');
  await page.getByText('Sign in to view saved internships', { exact: true }).waitFor();
  await page.waitForFunction(() => document.activeElement?.getAttribute('role') === 'alert');
  assert.equal(await page.locator('.s25-saved article').count(), 0);
}, { mutationStatus: 401 }));
it('malformed successful GET is not mistaken for an empty saved list', () => using(async page => {
  await page.goto(origin + '/s-25'); await page.getByRole('alert').waitFor();
  assert.equal(await page.getByText('No saved internships yet.', { exact: true }).count(), 0);
  assert.equal(await page.locator('.s20-code').count(), 0);
}, { malformed: true }));
for (const width of [320, 390, 1440]) it(`Revision L composition, 48px controls, reflow and axe at ${width}px`, () => using(async page => {
  await ready(page); await page.evaluate(() => document.fonts.ready);
  assert.equal(await page.locator('main').count(), 1);
  assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), true);
  assert.equal(await page.locator('.s25-saved article button').evaluateAll(nodes => nodes.every(n => n.getBoundingClientRect().height >= 48)), true);
  await page.addScriptTag({ content: await readFile('node_modules/axe-core/axe.min.js', 'utf8') });
  assert.deepEqual(await page.evaluate(async () => (await window.axe.run()).violations.filter(v => ['serious', 'critical'].includes(v.impact)).map(v => v.id)), []);
  await page.screenshot({ path: `${diagnosticDir}/s25-${width}.png`, fullPage: true });
}, { width }));
