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
  const requests = []; let config = options, saved = [], release, released = false;
  const heldReads = new Map();
  await page.route('**/api/v1/**', async route => {
    const req = route.request(), url = new URL(req.url()), path = url.pathname, method = req.method(); requests.push({ path, method, params: Object.fromEntries(url.searchParams) });
    const json = (body, status = 200) => route.fulfill({ status, contentType: 'application/json', body: JSON.stringify(body) });
    if (path.endsWith('/session')) return json(config.anonymous ? { authenticated: false, actor: null } : { authenticated: true, actor });
    if (path === '/api/v1/internships') {
      if (config.holdCatalogue) await new Promise(resolve => heldReads.set('catalogue', resolve));
      if (config.catalogueError) return json({ detail: { code: 'unavailable' } }, 503);
      const pageNum = Number(url.searchParams.get('page') || 1), verified = url.searchParams.get('verified_only') === 'true';
      return json({ items: config.empty ? [] : pageNum === 2 ? [{ ...listing, id: 'page-two', role: 'Page two intern' }] : verified ? [listing] : [listing, { ...listing, id: 'unpaid', role: 'Unpaid intern', stipend_monthly_paise: null, verification_status: 'unverified' }], total: config.empty ? 0 : config.paginated ? 21 : verified ? 1 : 2, page: pageNum, page_size: 20 });
    }
    if (path.endsWith('/internships/saved')) {
      if (config.holdSaved) await new Promise(resolve => heldReads.set('saved', resolve));
      return config.savedError ? json({ detail: { code: 'unavailable' } }, 503) : json({ items: saved });
    }
    if (path.endsWith('/saved')) {
      if (config.hold && !released) await new Promise(resolve => { release = resolve; });
      if (config.expireSession) { config = { ...config, anonymous: true }; return json({ detail: { code: 'authentication_required' } }, 401); }
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
  return { context, page, requests, set: value => { config = value; }, releaseRead: key => heldReads.get(key)?.(), release: () => { released = true; release?.(); for (const resolve of heldReads.values()) resolve(); } };
}
async function using(options, test, width) { const f = await fixture(options, width); try { await test(f); } finally { f.release(); await f.context.close(); } }
const mutations = f => f.requests.filter(r => r.method === 'PUT' || r.method === 'DELETE');
describe('S-20 server truth and action lifecycle', { timeout: 120000 }, () => {
  it('QA-1 observes an S-21 save and S-25 removal immediately on return, without stale marks', () => using({}, async f => {
    await f.page.getByRole('button', { name: 'Research intern Synthetic chambers' }).click();
    await f.page.getByRole('button', { name: 'Save', exact: true }).click();
    await f.page.getByRole('button', { name: 'Saved', exact: true }).waitFor();
    await f.page.getByRole('button', { name: 'Back to listings', exact: true }).click();
    await f.page.getByRole('button', { name: 'Remove Research intern from saved', exact: true }).waitFor();
    assert.equal(await f.page.getByRole('button', { name: 'Remove Research intern from saved', exact: true }).getAttribute('aria-pressed'), 'true');
    await f.page.getByRole('button', { name: 'Saved internships', exact: true }).first().click();
    await f.page.getByRole('button', { name: 'Remove', exact: true }).click();
    await f.page.getByRole('button', { name: 'Browse internships', exact: true }).click();
    await f.page.getByRole('button', { name: 'Save Research intern', exact: true }).waitFor();
    assert.equal(await f.page.getByRole('button', { name: 'Save Research intern', exact: true }).getAttribute('aria-pressed'), 'false');
    assert.deepEqual(mutations(f).map(r => r.method), ['PUT', 'DELETE']);
  }));
  for (const direction of ['Next page', 'Previous page']) for (const fail of [false, true]) {
    it(`QA-2 pagination focus is meaningful pending and settled: ${direction}, failure=${fail}`, () => using({ paginated: true }, async f => {
      if (direction === 'Previous page') {
        await f.page.getByRole('button', { name: 'Next page', exact: true }).click();
        await f.page.getByText('Page two intern', { exact: true }).waitFor();
        // The return page must be fetched rather than served from a fresh cache.
        await f.page.clock.setFixedTime(Date.now() + 31000);
      }
      f.set({ paginated: true, holdCatalogue: true, catalogueError: fail });
      const sent = f.page.waitForRequest(r => new URL(r.url()).pathname === '/api/v1/internships');
      await f.page.getByRole('button', { name: direction, exact: true }).press('Enter'); await sent;
      await f.page.waitForTimeout(60);
      assert.notEqual(await f.page.evaluate(() => document.activeElement?.tagName), 'BODY', 'pending page fetch must retain a useful focus anchor');
      f.releaseRead('catalogue');
      await f.page.locator(`[data-s20-state="${fail ? 'error' : 'results'}"]`).waitFor();
      await f.page.waitForTimeout(60);
      assert.equal(await f.page.evaluate(() => document.activeElement?.matches('.s20-title, .s20-pager button, .s20-empty[role="alert"], h1')), true);
    }));
  }
  for (const kind of ['catalogue', 'saved']) for (const fail of [false, true]) for (const move of [false, true]) {
    it(`QA-3 retry focus is retained pending/settled without stealing: ${kind}, failure=${fail}, moved=${move}`, () => using(kind === 'catalogue' ? { catalogueError: true } : { savedError: true }, async f => {
      f.set(kind === 'catalogue' ? { holdCatalogue: true, catalogueError: fail } : { holdSaved: true, savedError: fail });
      const path = kind === 'catalogue' ? '/api/v1/internships' : '/api/v1/student/internships/saved';
      const sent = f.page.waitForRequest(r => new URL(r.url()).pathname === path);
      await f.page.getByRole('button', { name: kind === 'catalogue' ? 'Retry' : 'Retry saved list', exact: true }).press('Enter'); await sent;
      await f.page.waitForTimeout(60);
      assert.notEqual(await f.page.evaluate(() => document.activeElement?.tagName), 'BODY', 'pending retry must not drop focus');
      if (move) await f.page.locator('.s20-filters summary').focus();
      f.releaseRead(kind); await f.page.waitForTimeout(150);
      if (move) assert.equal(await f.page.evaluate(() => document.activeElement?.matches('.s20-filters summary')), true);
      else assert.equal(await f.page.evaluate(() => document.activeElement?.matches('h1, [role="alert"], .s20-btn')), true);
    }));
  }
  for (const move of [false, true]) it(`QA-3 session-expiry remount preserves action focus without stealing, moved=${move}`, () => using({ hold: true, expireSession: true }, async f => {
    const sent = f.page.waitForRequest(r => r.method() === 'PUT');
    await f.page.getByRole('button', { name: 'Save Research intern', exact: true }).press('Enter'); await sent;
    if (move) await f.page.getByRole('button', { name: 'Your Profile', exact: true }).focus();
    f.release(); await f.page.getByText('Sign in to save internships', { exact: true }).waitFor();
    await f.page.waitForTimeout(120);
    assert.notEqual(await f.page.evaluate(() => document.activeElement?.tagName), 'BODY');
    assert.equal(await f.page.evaluate(() => document.activeElement?.matches('h1, .s20-note, .s20-note button, .s20-avatar')), true);
  }));
  it('QA-4 distinguishes an uncertain mutation from a saved-list load failure', () => using({ saveError: true }, async f => {
    await f.page.getByRole('button', { name: 'Save Research intern', exact: true }).click();
    await f.page.locator('.s20-save-error').waitFor();
    assert.equal(await f.page.getByText('Your saved list did not load.', { exact: true }).count(), 0);
    assert.match(await f.page.locator('.s20-note').innerText(), /saved state needs confirmation/i);
    assert.equal(await f.page.getByRole('button', { name: 'Retry saved list', exact: true }).count(), 1);
  }));
  it('QA-4 offline preflight says no request was sent and leaves confirmed state retryable', () => using({}, async f => {
    await f.context.setOffline(true);
    await f.page.getByRole('button', { name: 'Save Research intern', exact: true }).press('Enter');
    await f.page.locator('.s20-save-error').waitFor();
    assert.match(await f.page.locator('.s20-save-error').innerText(), /No request was sent/);
    assert.doesNotMatch(await f.page.locator('.s20-save-error').innerText(), /Reload your saved list/);
    assert.equal(mutations(f).length, 0);
    await f.context.setOffline(false);
    await f.page.getByRole('button', { name: 'Save Research intern', exact: true }).press('Enter');
    await f.page.getByRole('button', { name: 'Remove Research intern from saved', exact: true }).waitFor();
    assert.equal(mutations(f).length, 1);
  }));
  it('QA-5 a page-local no-match shows the server total and preserves pagination', () => using({ paginated: true }, async f => {
    await f.page.getByLabel('Search this page').fill('Page two intern');
    await f.page.getByRole('heading', { name: 'No matching listings on this page', exact: true }).waitFor();
    assert.match(await f.page.locator('.s20-empty').innerText(), /21 total listings/);
    await f.page.getByRole('button', { name: 'Next page', exact: true }).click();
    await f.page.getByText('Page two intern', { exact: true }).waitFor();
    assert.match(await f.page.locator('.s20-count').innerText(), /21 total listings/);
    assert.equal(await f.page.getByLabel('Search this page').inputValue(), 'Page two intern');
  }));
  for (const width of [390, 1440]) it(`rupee uses the frozen custom glyph only inside S-20 metadata at ${width}px`, () => using({}, async f => {
    await f.page.evaluate(async () => { await document.fonts.ready; });
    const cdp = await f.context.newCDPSession(f.page);
    await cdp.send('DOM.enable'); await cdp.send('CSS.enable');
    async function fonts(selector) {
      const { root } = await cdp.send('DOM.getDocument');
      const { nodeId } = await cdp.send('DOM.querySelector', { nodeId: root.nodeId, selector });
      return (await cdp.send('CSS.getPlatformFontsForNode', { nodeId })).fonts;
    }
    const stipend = await fonts('.s20-meta p');
    assert.ok(stipend.length > 0);
    assert.ok(stipend.every(font => font.isCustomFont), 'stipend must not fall back to the system rupee glyph');
    await f.page.evaluate(async () => {
      const probe = document.createElement('p'); probe.id = 's20-font-negative-control'; probe.textContent = '₹';
      probe.style.cssText = "position:fixed;top:0;left:0;font:12.5px 'Public Sans',system-ui,sans-serif";
      document.body.append(probe);
      await new Promise(done => requestAnimationFrame(() => requestAnimationFrame(done)));
    });
    const outside = await fonts('#s20-font-negative-control');
    assert.ok(outside.some(font => !font.isCustomFont), `the S-20 alias must not replace the global/other-screen fallback: ${JSON.stringify(outside)}`);
    await f.page.locator('#s20-font-negative-control').evaluate(el => el.remove());
    assert.equal(await f.page.locator('.s20-meta p').first().textContent(), 'Delhi · ₹12,000 per month');
    await cdp.detach();
  }, width));
  for (const width of [932, 1024, 1440]) for (const theme of ['light', 'dark']) it(`header navigation retains 48px targets without moving text at ${width}px/${theme}`, () => using({ theme }, async f => {
    const geometry = await f.page.locator('.s20-header nav').evaluate(nav => [...nav.children].map(el => {
      const range = document.createRange(); range.selectNodeContents(el);
      const text = range.getBoundingClientRect(), box = el.getBoundingClientRect();
      return { tag: el.tagName, name: el.textContent, x: box.x, right: box.right, width: box.width, height: box.height, textX: text.x, textRight: text.right };
    }));
    for (const item of geometry.filter(item => item.tag === 'BUTTON')) {
      assert.ok(item.width >= 48 && item.height >= 48, `${item.name} target must be at least 48px: ${JSON.stringify(item)}`);
    }
    for (let i = 1; i < geometry.length; i++) {
      assert.ok(geometry[i].x > geometry[i - 1].right, 'adjacent header targets must not overlap');
      assert.ok(Math.abs(geometry[i].textX - geometry[i - 1].textRight - 26) <= 1, 'Revision L 26px text spacing must be retained');
    }
  }, width));
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
  it('renders known stipend metadata as one text run and unknown stipend in the frozen italic style', () => using({}, async f => {
    const meta = await f.page.locator('.s20-result').evaluateAll(cards => cards.map(card => {
      const line = card.querySelector('.s20-meta p'), unknown = line.querySelector('i');
      return { text: line.textContent, nodes: line.childNodes.length, style: unknown && getComputedStyle(unknown).fontStyle, synthesis: unknown && getComputedStyle(unknown).fontSynthesis, color: unknown && getComputedStyle(unknown).color };
    }));
    assert.equal(meta[0].text, 'Delhi · ₹12,000 per month'); assert.equal(meta[0].nodes, 1);
    assert.equal(meta[1].text, 'Delhi · Stipend not stated'); assert.equal(meta[1].style, 'italic'); assert.equal(meta[1].color, 'rgb(62, 66, 84)');
    assert.match(meta[1].synthesis, /style/, 'the frozen italic must render, not be suppressed by global font-synthesis:none');
  }));
  it('retains the frozen empty marker slot and label span for unverified chips', () => using({}, async f => {
    const chip = f.page.locator('.s20-chip:not(.s20-verified)');
    assert.equal(await chip.locator(':scope > span').count(), 2);
    assert.equal(await chip.locator('.s20-chip-dot').getAttribute('aria-hidden'), 'true');
    assert.equal((await chip.locator('.s20-chip-dot').boundingBox()).width, 0);
    assert.equal(await chip.locator('span').last().evaluate(el => getComputedStyle(el).whiteSpace), 'nowrap');
  }));
  it('preserves frozen warning and save-error primitives without changing truthful copy', () => using({ saveError: true }, async f => {
    await f.page.getByRole('button', { name: 'Save Research intern', exact: true }).click();
    await f.page.locator('.s20-save-error').waitFor();
    const style = await f.page.locator('.s20-save-error').evaluate(el => ({ weight: getComputedStyle(el).fontWeight, line: getComputedStyle(el).lineHeight, gap: getComputedStyle(el).gap, color: getComputedStyle(el).color }));
    assert.equal(style.weight, '600'); assert.equal(style.line, '17.5px'); assert.equal(style.gap, '7px'); assert.equal(style.color, 'rgb(154, 43, 33)');
    assert.equal(await f.page.locator('.s20-save-error svg path').getAttribute('d'), 'M6 6l12 12M18 6 6 18');
    assert.equal(await f.page.locator('.s20-note > svg').evaluate(el => getComputedStyle(el).color), 'rgb(62, 66, 84)');
    assert.match(await f.page.locator('.s20-save-error').innerText(), /Could not confirm the change/);
  }));
  it('local search/stipend does not query the server; verified filter does', () => using({}, async f => {
    const count = f.requests.filter(r => r.path === '/api/v1/internships').length;
    await f.page.getByLabel('Search this page').fill('absent'); await f.page.getByText('No matching listings on this page', { exact: true }).waitFor();
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
    await f.page.getByText('You are offline. No request was sent. Reconnect and try again.', { exact: true }).waitFor();
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
