// S-20 synthetic API / real Chromium checks. Not live-backend or conformance evidence.
import { before, after, describe, it } from 'node:test';
import assert from 'node:assert/strict';
import { chromium } from 'playwright';
import { createServer } from 'vite';
import { readFile, mkdir } from 'node:fs/promises';
import { actor } from './nyay66-fixtures.mjs';
let server, browser, origin;
before(async () => { server = await createServer({ server: { host: '127.0.0.1', port: 0 }, logLevel: 'error' }); await server.listen(); origin = `http://127.0.0.1:${server.httpServer.address().port}`; browser = await chromium.launch({ headless: true }); });
after(async () => { await browser?.close(); await server?.close(); });
const listing = { id: 'synthetic-intern', organisation_id: '00000000-0000-4000-8000-000000000001', role: 'Research intern', organisation: 'Synthetic chambers', location: 'Delhi', stipend_monthly_paise: 1200000, verification_status: 'verified', application_deadline: '2027-07-08', eligibility: 'Student', tags: [], description: 'Synthetic research', source: { name: 'Synthetic source', url: null, retrieved_at: null, verified_at: null } };
async function fixture(options = {}, width = 390) {
  const context = await browser.newContext({ viewport: { width, height: 844 }, reducedMotion: 'reduce', colorScheme: options.theme ?? 'light' });
  if (options.theme) await context.addInitScript(theme => localStorage.setItem('nyayone.theme.v1', theme), options.theme);
  const page = await context.newPage(); page.setDefaultTimeout(7000);
  const requests = []; let config = options, saved = [], release;
  await page.route('**/api/v1/**', async route => {
    const req = route.request(), url = new URL(req.url()), path = url.pathname, method = req.method(); requests.push({ path, method, params: Object.fromEntries(url.searchParams) });
    const json = (body, status = 200) => route.fulfill({ status, contentType: 'application/json', body: JSON.stringify(body) });
    if (path.endsWith('/session')) return json(config.anonymous ? { authenticated: false, actor: null } : { authenticated: true, actor });
    if (path === '/api/v1/internships') {
      if (config.catalogueError) return json({ detail: { code: 'unavailable' } }, 503);
      const pageNum = Number(url.searchParams.get('page') || 1), verified = url.searchParams.get('verified_only') === 'true';
      return json({ items: config.empty ? [] : pageNum === 2 ? [{ ...listing, id: 'page-two', role: 'Page two intern' }] : verified ? [listing] : [listing, { ...listing, id: 'unpaid', role: 'Unpaid intern', stipend_monthly_paise: null, verification_status: 'unverified' }], total: config.empty ? 0 : config.paginated ? 21 : verified ? 1 : 2, page: pageNum, page_size: 20 });
    }
    if (path.endsWith('/internships/saved')) return config.savedError ? json({ detail: { code: 'unavailable' } }, 503) : json({ items: saved });
    if (path.endsWith('/saved')) {
      if (config.hold) await new Promise(resolve => { release = resolve; });
      if (config.saveError) return json({ detail: { code: 'unavailable' } }, 503);
      if (config.malformed) return json({ saved: true, listing_id: 'wrong-listing' });
      saved = method === 'PUT' ? [listing] : [];
      return json({ saved: method === 'PUT', listing_id: path.split('/').at(-2) });
    }
    if (path.endsWith('/internships/synthetic-intern')) return json(listing);
    if (path.endsWith('/student/settings')) return json({ theme: 'light', language: 'en', notif_email: false, notif_sms: false, notif_updates: false, version: 1, privacy: [] });
    return json({ detail: { code: 'not_mocked' } }, 404);
  });
  await page.goto(origin + '/s-20');
  await page.getByRole('heading', { name: 'Browse internships.' }).waitFor();
  await page.locator(`[data-s20-state="${config.catalogueError ? 'error' : 'results'}"]`).waitFor();
  if (!config.catalogueError && !config.anonymous && !config.savedError && !config.empty) await page.getByRole('button', { name: 'Save Research intern', exact: true }).waitFor();
  return { context, page, requests, set: value => { config = value; }, release: () => release?.() };
}
async function using(options, test, width) { const f = await fixture(options, width); try { await test(f); } finally { f.release(); await f.context.close(); } }
const mutations = f => f.requests.filter(r => r.method === 'PUT' || r.method === 'DELETE');
describe('S-20 server truth and action lifecycle', { timeout: 120000 }, () => {
  for (const width of [390, 1440]) it(`Revision L heading, expanded-filter geometry and tokens at ${width}px`, () => using({}, async f => {
    await f.page.locator('.s20-filters summary').click();
    const style = await f.page.evaluate(() => {
      const h = getComputedStyle(document.querySelector('h1'));
      const label = document.querySelector('.s20-filter-body .s20-field:last-child > span');
      const tag = document.querySelector('.s20-filter-tag');
      const c = getComputedStyle(document.querySelector('.s20-verified'));
      return { tracking: h.letterSpacing, labelSize: getComputedStyle(label).fontSize,
        labelBottom: getComputedStyle(label).marginBottom,
        tagWidth: tag.getBoundingClientRect().width, fieldWidth: tag.parentElement.getBoundingClientRect().width,
        gold: c.borderTopColor, goldFill: c.backgroundColor,
        asideLine: getComputedStyle(document.querySelector('.s20-card p')).lineHeight };
    });
    assert.equal(style.tracking, width === 390 ? '-0.22px' : '-0.28px');
    assert.equal(style.labelSize, '12.5px'); assert.equal(style.labelBottom, '6px');
    assert.equal(style.tagWidth, style.fieldWidth);
    assert.equal(style.gold, 'rgb(200, 154, 58)'); assert.equal(style.goldFill, 'rgb(246, 237, 218)');
    if (width === 1440) assert.equal(style.asideLine, '19.375px');
    assert.equal(await f.page.locator('.s20-filters summary svg circle').getAttribute('r'), '9');
    assert.equal(await f.page.locator('.s20-save svg path').first().getAttribute('d'), 'M7 4h10v17l-5-3.5L7 21z');
  }, width));
  it('Revision L error card keeps its 32px icon tile and 18px retry vector', () => using({ catalogueError: true }, async f => {
    const tile = f.page.locator('.s20-empty > span').first();
    assert.equal((await tile.boundingBox()).height, 32); assert.equal((await tile.boundingBox()).width, 32);
    assert.equal(await tile.locator('svg').getAttribute('width'), '20');
    assert.equal(await tile.evaluate(el => getComputedStyle(el).backgroundColor), 'rgba(154, 43, 33, 0.12)');
    assert.equal(await f.page.locator('.s20-empty h2').evaluate(el => getComputedStyle(el).letterSpacing), '-0.17px');
    assert.equal(await f.page.getByRole('button', { name: 'Retry', exact: true }).locator('svg').getAttribute('width'), '18');
  }));
  it('local search/stipend does not query the server; verified filter does', () => using({}, async f => {
    const count = f.requests.filter(r => r.path === '/api/v1/internships').length;
    await f.page.getByLabel('Search this page').fill('absent'); await f.page.getByText('No matching listings', { exact: true }).waitFor();
    await f.page.getByLabel('Search this page').fill(''); await f.page.locator('.s20-filters summary').click();
    await f.page.getByRole('button', { name: 'Paid', exact: true }).click(); assert.equal(await f.page.locator('.s20-result').count(), 1);
    assert.equal(f.requests.filter(r => r.path === '/api/v1/internships').length, count);
    await f.page.getByRole('button', { name: 'Verified listings only' }).click();
    await f.page.waitForFunction(() => document.querySelector('[data-s20-state="results"]'));
    assert.deepEqual(f.requests.filter(r => r.path === '/api/v1/internships').at(-1).params, { page: '1', page_size: '20', verified_only: 'true' });
  }));
  it('has real server pagination, reset on verified filter', () => using({ paginated: true }, async f => {
    await f.page.getByRole('button', { name: 'Next page' }).click(); await f.page.getByText('Page two intern', { exact: true }).waitFor();
    assert.equal(f.requests.filter(r => r.path === '/api/v1/internships').at(-1).params.page, '2');
    await f.page.locator('.s20-filters summary').click(); await f.page.getByRole('button', { name: 'Verified listings only' }).click();
    await f.page.getByText('Research intern', { exact: true }).waitFor();
    assert.equal(f.requests.filter(r => r.path === '/api/v1/internships').at(-1).params.page, '1');
  }));
  it('does not pretend saved data failure means unsaved; retry restores focus', () => using({ savedError: true }, async f => {
    await f.page.getByText('Your saved list did not load.', { exact: true }).waitFor();
    const button = f.page.getByRole('button', { name: 'Save Research intern (saved state unavailable)', exact: true });
    assert.equal(await button.getAttribute('aria-pressed'), null); assert.equal(await button.isDisabled(), true);
    f.set({}); await f.page.getByRole('button', { name: 'Retry saved list' }).press('Enter');
    await f.page.getByRole('button', { name: 'Save Research intern', exact: true }).waitFor();
    await f.page.waitForFunction(() => document.activeElement?.tagName === 'H1');
  }));
  for (const outcome of ['success', 'failure', 'malformed']) for (const moveFocus of [false, true]) {
    it(`duplicate activation/Enter: ${outcome}, moved focus=${moveFocus}`, () => using({ hold: true, saveError: outcome === 'failure', malformed: outcome === 'malformed' }, async f => {
      const button = f.page.getByRole('button', { name: 'Save Research intern', exact: true }); await button.focus();
      const sent = f.page.waitForRequest(r => r.method() === 'PUT' && new URL(r.url()).pathname.endsWith('/saved'));
      await button.evaluate(el => { el.click(); el.click(); }); await sent;
      await f.page.waitForFunction(() => document.querySelector('.s20-save[aria-busy="true"]'));
      assert.equal(mutations(f).length, 1); assert.equal(await button.getAttribute('aria-pressed'), 'false');
      await button.press('Enter'); assert.equal(mutations(f).length, 1);
      if (moveFocus) await f.page.getByLabel('Search this page').focus();
      f.release();
      if (outcome === 'success') await f.page.getByRole('button', { name: 'Remove Research intern from saved', exact: true }).waitFor();
      else await f.page.getByText('Could not confirm the change. Reload your saved list before trying again.', { exact: true }).waitFor();
      await f.page.waitForTimeout(100);
      if (moveFocus) assert.equal(await f.page.evaluate(() => document.activeElement?.id), 's20-query');
      else assert.equal(await f.page.evaluate(() => document.activeElement?.getAttribute('role') === 'alert' || document.activeElement?.classList.contains('s20-save')), true);
    }));
  }
  it('PUT then DELETE reflect only server acknowledgements', () => using({}, async f => {
    await f.page.getByRole('button', { name: 'Save Research intern', exact: true }).press('Enter');
    await f.page.getByRole('button', { name: 'Remove Research intern from saved', exact: true }).press('Space');
    await f.page.getByRole('button', { name: 'Save Research intern', exact: true }).waitFor();
    assert.deepEqual(mutations(f).map(r => r.method), ['PUT', 'DELETE']);
  }));
  it('anonymous catalogue remains readable without private GETs or save mutations', () => using({ anonymous: true }, async f => {
    await f.page.getByText('Sign in to save internships', { exact: true }).waitFor();
    assert.equal(f.requests.some(r => r.path.endsWith('/internships/saved')), false);
    assert.equal(mutations(f).length, 0);
  }));
  it('network error is not an empty catalogue; retry focuses a useful destination', () => using({ catalogueError: true }, async f => {
    assert.equal(await f.page.getByText('No internships are listed right now.').count(), 0);
    f.set({}); await f.page.getByRole('button', { name: 'Retry', exact: true }).press('Enter');
    await f.page.getByText('Research intern', { exact: true }).waitFor(); await f.page.waitForFunction(() => document.activeElement?.tagName === 'H1');
  }));
  it('clearing a local no-match retains meaningful focus when its action disappears', () => using({}, async f => {
    await f.page.getByLabel('Search this page').fill('missing');
    await f.page.getByRole('button', { name: 'Clear search and filters' }).press('Enter');
    await f.page.getByText('Research intern', { exact: true }).waitFor();
    await f.page.waitForTimeout(80);
    assert.equal(await f.page.evaluate(() => document.activeElement?.tagName), 'H1');
  }));
  it('an offline save fails promptly instead of remaining paused/busy indefinitely', () => using({}, async f => {
    await f.context.setOffline(true);
    await f.page.getByRole('button', { name: 'Save Research intern', exact: true }).press('Enter');
    await f.page.getByText('Could not confirm the change. Reload your saved list before trying again.', { exact: true }).waitFor();
    assert.equal(await f.page.locator('.s20-save[aria-busy="true"]').count(), 0);
  }));
  for (const width of [390, 1440]) it(`retains readable light-phase headings under an existing dark preference at ${width}px`, () => using({ theme: 'dark' }, async f => {
    assert.equal(await f.page.locator('html').getAttribute('data-theme'), 'dark');
    await f.page.addScriptTag({ content: await readFile(new URL('../../node_modules/axe-core/axe.min.js', import.meta.url), 'utf8') });
    const contrast = await f.page.evaluate(async () => (await window.axe.run({ runOnly: ['color-contrast'] })).violations.map(v => ({ id: v.id, targets: v.nodes.map(n => n.target) })));
    assert.deepEqual(contrast, []);
    assert.equal(await f.page.locator('h1').evaluate(el => getComputedStyle(el).color), 'rgb(20, 22, 26)');
    // The same scoped heading rule must protect empty/error states, not only
    // the loaded catalogue sampled by the foundation producer.
    for (const state of [{ empty: true }, { catalogueError: true }]) {
      f.set(state); await f.page.reload(); await f.page.locator('.s20-empty h2').waitFor();
      assert.equal(await f.page.locator('.s20-empty h2').evaluate(el => getComputedStyle(el).color), 'rgb(20, 22, 26)');
    }
  }, width));
  for (const width of [320, 390, 1440]) it(`reflow and axe at ${width}px`, () => using({}, async f => {
    await f.page.locator('.s20-filters summary').click();
    await f.page.addScriptTag({ content: await readFile(new URL('../../node_modules/axe-core/axe.min.js', import.meta.url), 'utf8') });
    const a11y = await f.page.evaluate(async () => (await window.axe.run()).violations.filter(v => ['serious', 'critical'].includes(v.impact)).map(v => ({ id: v.id, targets: v.nodes.map(n => n.target) })));
    assert.deepEqual(a11y, []);
    assert.equal(await f.page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), true);
    assert.equal(await f.page.locator('main').count(), 1);
    if (process.env.NYAY92_DIAGNOSTIC_DIR) { await mkdir(process.env.NYAY92_DIAGNOSTIC_DIR, { recursive: true }); await f.page.screenshot({ path: `${process.env.NYAY92_DIAGNOSTIC_DIR}/s20-${width}.png`, fullPage: true }); }
  }, width));
});
