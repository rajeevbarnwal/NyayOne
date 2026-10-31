// Synthetic developer regressions against the production build; not hosted conformance or independent QA.
import { before, after, it } from 'node:test';
import assert from 'node:assert/strict';
import { readFile, mkdir } from 'node:fs/promises';
import { setTimeout as delay } from 'node:timers/promises';
import { preview } from 'vite';
import { chromium } from 'playwright';
let server, browser, origin;
before(async () => { server = await preview({ preview: { host: '127.0.0.1', port: 0 }, logLevel: 'error' }); origin = `http://127.0.0.1:${server.httpServer.address().port}`; browser = await chromium.launch(); });
after(async () => { await browser?.close(); await new Promise(done => server?.httpServer.close(done)); });
const schools = Array.from({ length: 5 }, (_, i) => ({ id: `school-${i + 1}`, slug: `school-${i + 1}`, name: `Synthetic Law School ${i + 1}`, state: 'Delhi', institution_type: 'government', accreditation: 'BCI approved', entrance_exam: 'CLAT', fees_min: 150000, fees_max: 300000, nirf_rank: i === 0 ? null : i }));
async function using(run, options = {}) {
  const context = await browser.newContext({ viewport: { width: options.width ?? 390, height: options.width >= 900 ? 1024 : 844 }, reducedMotion: 'reduce' });
  const page = await context.newPage(); page.setDefaultTimeout(5000);
  const s = { status: 200, items: schools, total: 25, max: 4, malformed: false, hold: false, held: [], reads: [], unexpected: [], ...options };
  await page.route('**/*', async route => {
    const request = route.request(), url = new URL(request.url());
    if (url.origin !== origin && !(url.origin === 'http://localhost:1131' && url.pathname.startsWith('/api/v1/'))) { s.unexpected.push(url.origin); return route.abort(); }
    if (!url.pathname.startsWith('/api/v1/')) return route.continue();
    const reply = (body, status = 200) => route.fulfill({ status, contentType: 'application/json', body: JSON.stringify(body) }).catch(() => undefined);
    if (url.pathname === '/api/v1/auth/student/session') return reply({ authenticated: false, actor: null });
    if (url.pathname === '/api/v1/law-schools' && request.method() === 'GET') {
      const params = Object.fromEntries(url.searchParams); s.reads.push(params);
      const status = s.status, body = s.malformed ? {} : status === 200 ? { items: s.items, total: s.total, page: Number(params.page), page_size: Number(params.page_size), compare_max: s.max } : { detail: { code: status === 422 ? 'unsupported_sort' : 'unavailable' } };
      if (s.hold) { s.hold = false; s.held.push(() => reply(body, status)); return; } return reply(body, status);
    }
    s.unexpected.push(`${request.method()} ${url.pathname}`); return route.abort();
  });
  try { await run(page, s); assert.deepEqual(s.unexpected, []); }
  catch (error) { console.error({ url: page.url(), body: (await page.locator('body').innerText()).slice(0, 1600), requests: s.reads, unexpected: s.unexpected }); throw error; }
  finally { await context.close(); }
}
const root = page => page.locator('.s27-search');
const cards = page => root(page).locator('article');
const compareAction = page => root(page).getByRole('region', { name: 'Comparison', exact: true }).getByRole('button', { name: 'Compare', exact: true });
const retry = page => page.getByRole('button', { name: 'Retry', exact: true });
async function held(s, n = 1) { const until = Date.now() + 5000; while (s.held.length < n && Date.now() < until) await delay(10); assert.equal(s.held.length, n); }
it('Revision L public search reads only the summary endpoint, with no invented account counts or rankings', () => using(async (page, s) => {
  await page.goto(origin + '/s-27'); await page.getByRole('heading', { name: 'Find a law school.', exact: true }).waitFor(); await cards(page).first().waitFor();
  assert.equal(s.reads.length, 1); assert.equal(await cards(page).count(), 5);
  assert.equal(await page.locator('main').count(), 1); assert.equal(await page.locator('.ls-shell').count(), 0);
  assert.doesNotMatch(await root(page).innerText(), /2 saved|2 following|recommended|best match|verified/i);
}));
it('mobile related destinations follow the heading before search, including Compare only when selection is eligible', () => using(async page => {
  await page.goto(origin + '/s-27'); await cards(page).first().waitFor();
  const related = page.getByRole('navigation', { name: 'Related', exact: true });
  await related.getByRole('link', { name: 'Saved and followed', exact: true }).waitFor();
  const box = await related.boundingBox(), search = await page.getByRole('searchbox').boundingBox(), heading = await page.getByRole('heading', { level: 1 }).boundingBox();
  assert.ok(box.y > heading.y + heading.height && box.y + box.height < search.y);
  assert.equal(await related.getByRole('button', { name: 'Compare', exact: true }).count(), 0);
  for (let i = 1; i <= 2; i++) await page.getByRole('button', { name: `Add Synthetic Law School ${i} to comparison`, exact: true }).click();
  assert.equal(await related.getByRole('button', { name: 'Compare', exact: true }).count(), 1);
}));
it('loading is not zero results; malformed success is an error, not an empty list', () => using(async (page, s) => {
  await page.goto(origin + '/s-27'); await held(s); await page.getByRole('status', { name: 'Loading law schools' }).waitFor();
  assert.equal(await page.getByText('No schools match.', { exact: true }).count(), 0);
  await s.held[0](); await root(page).getByRole('alert').waitFor();
  assert.doesNotMatch(await root(page).innerText(), /HTTP 200|No schools match/);
}, { hold: true, malformed: true }));
it('search, filters and all three sorts use server parameters, reset pagination and restore URL state on Back', () => using(async (page, s) => {
  await page.goto(origin + '/s-27?page=2'); await cards(page).first().waitFor();
  const input = page.getByRole('searchbox', { name: 'Search law schools' });
  const searchReply = page.waitForResponse(response => new URL(response.url()).searchParams.get('q') === 'Delhi');
  await input.fill('Delhi'); await input.press('Enter'); await searchReply;
  await page.waitForURL('**q=Delhi*'); await cards(page).first().waitFor(); assert.equal(s.reads.at(-1).q, 'Delhi'); assert.equal(s.reads.at(-1).page, '1');
  await page.getByText('Filters', { exact: true }).click();
  for (const [label, key, value] of [['State', 'state', 'Delhi'], ['Institution type', 'institution_type', 'government'], ['Degree', 'degree', 'LLM'], ['Accreditation', 'accreditation', 'BCI approved'], ['Entrance exam', 'entrance_exam', 'CLAT'], ['Max fees (₹ per year)', 'fees_max', '300000'], ['Order', 'sort', 'fees'], ['Order', 'sort', 'nirf_rank'], ['Order', 'sort', 'name']]) {
    const reply = page.waitForResponse(response => new URL(response.url()).pathname === '/api/v1/law-schools' && new URL(response.url()).searchParams.get(key) === value);
    await page.getByLabel(label, { exact: true }).selectOption(value); await reply; await cards(page).first().waitFor();
    await page.waitForFunction(([k, v]) => new URLSearchParams(location.search).get(k) === v, [key, value]);
    assert.equal(s.reads.at(-1)[key], value); assert.equal(s.reads.at(-1).page, '1');
  }
  await page.goBack(); await page.waitForFunction(() => document.querySelector('#s27-sort')?.value === 'nirf_rank');
  assert.equal(await input.inputValue(), 'Delhi');
}));
it('page controls retain focus while pending, then move to the results summary without stealing later focus', () => using(async (page, s) => {
  await page.goto(origin + '/s-27'); await cards(page).first().waitFor(); const next = page.getByRole('button', { name: 'Next page', exact: true });
  s.hold = true; await next.press('Enter'); await held(s); assert.equal(await next.evaluate(el => el === document.activeElement), true);
  await next.evaluate(el => { el.click(); el.click(); }); assert.equal(s.reads.length, 2);
  await s.held[0](); await page.waitForFunction(() => document.activeElement?.id === 's27-results-summary');
  s.hold = true; await page.getByRole('button', { name: 'Previous page', exact: true }).press('Enter'); await held(s, 2);
  await page.getByRole('searchbox').focus(); await s.held[1](); await cards(page).first().waitFor();
  assert.equal(await page.getByRole('searchbox').evaluate(el => el === document.activeElement), true);
}));
for (const status of [422, 429, 503]) it(`genuine HTTP ${status} is surfaced and failed Retry/Reset retains meaningful focus`, () => using(async (page, s) => {
  await page.goto(origin + '/s-27?sort=unsupported'); await root(page).getByRole('alert').waitFor();
  assert.equal(s.reads[0].sort, 'unsupported'); assert.match(await root(page).innerText(), new RegExp(`HTTP ${status}`));
  await page.waitForFunction(() => document.activeElement?.getAttribute('role') === 'alert');
  const action = status === 422 ? page.getByRole('button', { name: 'Reset filters', exact: true }) : retry(page);
  s.hold = true; await action.press('Enter'); await held(s); assert.notEqual(await page.evaluate(() => document.activeElement?.tagName), 'BODY');
  await s.held[0](); await page.waitForFunction(() => document.activeElement?.getAttribute('role') === 'alert');
}, { status }));
it('retry is duplicate-locked, remains focused, and a later success does not steal focus', () => using(async (page, s) => {
  await page.goto(origin + '/s-27'); await retry(page).waitFor(); s.hold = true; s.status = 200;
  await retry(page).focus(); await retry(page).evaluate(el => { el.click(); el.click(); el.click(); }); await held(s);
  assert.equal(s.reads.length, 2); assert.equal(await retry(page).evaluate(el => el === document.activeElement), true);
  await page.getByRole('searchbox').focus(); await s.held[0](); await cards(page).first().waitFor();
  assert.equal(await page.getByRole('searchbox').evaluate(el => el === document.activeElement), true);
}, { status: 503 }));
it('compare is local, deduplicated, bounded by server compare_max and unavailable until two selected', () => using(async (page, s) => {
  await page.goto(origin + '/s-27'); await cards(page).first().waitFor();
  for (let i = 1; i <= 2; i++) await page.getByRole('button', { name: `Add Synthetic Law School ${i} to comparison`, exact: true }).click();
  const compare = compareAction(page); assert.equal(await compare.isEnabled(), true);
  assert.equal(await page.getByRole('button', { name: 'Add Synthetic Law School 3 to comparison' }).getAttribute('aria-disabled'), 'true');
  await page.getByRole('button', { name: 'Remove Synthetic Law School 1 from comparison', exact: true }).click();
  assert.equal(await compare.getAttribute('aria-disabled'), 'true'); assert.equal(s.reads.length, 1);
}, { max: 2 }));
it('empty page preserves server total and offers page recovery', () => using(async page => {
  await page.goto(origin + '/s-27?page=3'); await page.getByRole('heading', { name: 'No schools on this page.', exact: true }).waitFor();
  assert.match(await root(page).innerText(), /25 schools/); assert.equal(await page.getByRole('button', { name: 'Previous page' }).getAttribute('aria-disabled'), 'false');
}, { items: [], total: 25 }));
it('rapid search changes discard an older held response and never filter a server page locally', () => using(async (page, s) => {
  await page.goto(origin + '/s-27'); await cards(page).first().waitFor();
  s.hold = true; s.items = [{ ...schools[0], name: 'Older response' }]; s.total = 1;
  const input = page.getByRole('searchbox'); await input.fill('Older'); await input.press('Enter'); await held(s);
  s.items = [{ ...schools[1], name: 'Server-selected result' }];
  const response = page.waitForResponse(r => new URL(r.url()).searchParams.get('q') === 'Newer');
  await input.fill('Newer'); await input.press('Enter'); await response;
  await page.getByRole('link', { name: /Server-selected result/ }).waitFor(); await s.held[0]();
  assert.equal(await cards(page).count(), 1); assert.equal(await page.getByRole('link', { name: /Older response/ }).count(), 0);
  assert.equal(await input.inputValue(), 'Newer'); assert.equal(await input.evaluate(el => el === document.activeElement), true);
}));
it('offline Retry makes no request, repeated failure is announced, and reconnect succeeds', () => using(async (page, s) => {
  await page.goto(origin + '/s-27'); await retry(page).waitFor(); const before = s.reads.length;
  await page.context().setOffline(true);
  for (let i = 0; i < 2; i++) { await retry(page).press('Enter'); await page.waitForFunction(() => document.activeElement?.getAttribute('role') === 'alert'); }
  assert.equal(s.reads.length, before); assert.match(await root(page).innerText(), /No request was sent/);
  s.status = 200; await page.context().setOffline(false); await retry(page).press('Enter'); await cards(page).first().waitFor();
  await page.waitForFunction(() => document.activeElement?.id === 's27-results-summary');
}, { status: 503 }));
it('initial offline state sends no directory request and makes no empty claim', () => using(async (page, s) => {
  await page.addInitScript(() => Object.defineProperty(navigator, 'onLine', { configurable: true, get: () => false }));
  await page.goto(origin + '/s-27'); await page.getByRole('heading', { name: 'You are offline.', exact: true }).waitFor();
  assert.equal(s.reads.length, 0); assert.equal(await page.getByText('No schools match.', { exact: true }).count(), 0);
}));
it('compare route carries only the chosen IDs and exact return context; detail Back restores filters', () => using(async (page, s) => {
  let compared;
  await page.route('**/api/v1/law-schools/compare', route => {
    compared = route.request().postDataJSON();
    return route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ items: schools.slice(0, 2).map(item => ({ ...item, programmes: [], facts: [] })), compare_max: s.max }) });
  });
  await page.route('**/api/v1/law-schools/school-1', route => route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ ...schools[0], programmes: [], facts: [], saved: false, followed: false }) }));
  await page.goto(origin + '/s-27?state=Delhi&sort=fees'); await cards(page).first().waitFor();
  await page.getByRole('link', { name: /Synthetic Law School 1/ }).click(); await page.waitForURL('**/s-28*');
  assert.equal(new URL(page.url()).searchParams.get('ret'), 'state=Delhi&sort=fees');
  await page.goBack(); await cards(page).first().waitFor();
  for (let i = 1; i <= 2; i++) await page.getByRole('button', { name: `Add Synthetic Law School ${i} to comparison`, exact: true }).click();
  const compareReply = page.waitForResponse(r => new URL(r.url()).pathname === '/api/v1/law-schools/compare');
  await compareAction(page).click(); await page.waitForURL('**/s-29*'); await compareReply;
  assert.deepEqual(compared.school_ids, ['school-1', 'school-2']);
  assert.equal(new URL(page.url()).searchParams.get('ret'), 'state=Delhi&sort=fees');
}));
it('compare limit changes fail closed without silently deleting the existing selection', () => using(async (page, s) => {
  await page.goto(origin + '/s-27'); await cards(page).first().waitFor();
  for (let i = 1; i <= 3; i++) await page.getByRole('button', { name: `Add Synthetic Law School ${i} to comparison`, exact: true }).click();
  s.max = 2; await page.getByRole('searchbox').fill('law'); await page.getByRole('searchbox').press('Enter');
  await page.getByText('3 of 2 selected', { exact: true }).first().waitFor();
  assert.equal(await compareAction(page).getAttribute('aria-disabled'), 'true');
  await page.getByRole('button', { name: 'Remove Synthetic Law School 3 from comparison', exact: true }).click();
  assert.equal(await compareAction(page).getAttribute('aria-disabled'), 'false');
}));
it('forward and reverse keyboard navigation retain semantic search, filters, result and compare controls', () => using(async page => {
  await page.goto(origin + '/s-27'); await cards(page).first().waitFor(); const input = page.getByRole('searchbox'); await input.focus();
  await page.keyboard.press('Tab'); assert.equal(await page.evaluate(() => document.activeElement?.tagName), 'SUMMARY');
  await page.keyboard.press('Shift+Tab'); assert.equal(await input.evaluate(el => el === document.activeElement), true);
  await page.keyboard.press('Tab'); await page.keyboard.press('Tab'); assert.equal(await page.evaluate(() => document.activeElement?.tagName), 'A');
  await page.keyboard.press('Tab'); assert.equal(await page.getByRole('button', { name: 'Add Synthetic Law School 1 to comparison', exact: true }).evaluate(el => el === document.activeElement), true);
}));
for (const width of [320, 390, 1440]) it(`${width}px: no overflow, 48px controls, one main and zero serious/critical axe`, () => using(async page => {
  await page.goto(origin + '/s-27'); await cards(page).first().waitFor(); await page.getByText('Filters', { exact: true }).click();
  assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth), false);
  const undersized = await root(page).locator('button,input,select,summary,a').evaluateAll(nodes => nodes.filter(n => n.getClientRects().length && n.getBoundingClientRect().height < 47.9).map(n => n.outerHTML)); assert.deepEqual(undersized, []);
  await page.addScriptTag({ content: await readFile('node_modules/axe-core/axe.min.js', 'utf8') });
  const result = await page.evaluate(async () => window.axe.run(document.querySelector('.s27-search')));
  assert.deepEqual(result.violations.filter(v => ['serious', 'critical'].includes(v.impact)).map(v => ({ id: v.id, nodes: v.nodes.map(n => n.target) })), []);
}, { width }));
// Presentation regressions from the first hosted S-27 comparison. The response
// statuses, keyboard/focus behavior and server-query assertions above stay intact.
for (const width of [390, 1440]) {
  it(`${width}px Revision L correction: labels use 12px ink2 and a 5px control gap`, () => using(async page => {
    await page.goto(origin + '/s-27'); await cards(page).first().waitFor(); await page.evaluate(() => document.fonts.ready);
    await page.getByText('Filters', { exact: true }).click();
    for (const selector of ['.s27-search-label', '.s27-field>label']) {
      const labels = await root(page).locator(selector).evaluateAll(nodes => nodes.map(label => {
        const style = getComputedStyle(label), box = label.getBoundingClientRect(), control = label.nextElementSibling.getBoundingClientRect();
        return { fontSize: style.fontSize, color: style.color, gap: control.top - box.bottom };
      }));
      for (const label of labels) assert.deepEqual(label, { fontSize: '12px', color: 'rgb(62, 66, 84)', gap: 5 });
    }
  }, { width }));
  it(`${width}px Revision L correction: invalid-filter notice stays compact and focused with genuine HTTP 422`, () => using(async (page, s) => {
    await page.goto(origin + '/s-27?sort=unsupported'); const alert = root(page).getByRole('alert'); await alert.waitFor();
    await page.waitForFunction(() => document.activeElement?.getAttribute('role') === 'alert');
    const style = await alert.evaluate(el => {
      const s = getComputedStyle(el), heading = getComputedStyle(el.querySelector('h2'));
      return { direction: s.flexDirection, align: s.textAlign, padding: s.padding, borderStyle: s.borderStyle, left: s.borderLeftWidth, radius: s.borderRadius, font: heading.fontSize, line: heading.lineHeight };
    });
    assert.deepEqual(style, { direction: 'row', align: 'start', padding: '9px 12px', borderStyle: 'solid', left: '4px', radius: '12px', font: '12.5px', line: '18.75px' });
    assert.equal(await alert.locator(':scope>svg').getAttribute('width'), '18');
    assert.match(await alert.innerText(), /HTTP 422 · unsupported_sort/);
    const action = alert.getByRole('button', { name: 'Reset filters', exact: true });
    assert.equal(await action.evaluate(el => getComputedStyle(el).backgroundColor), 'rgb(255, 255, 255)');
    assert.equal(await action.locator('svg').getAttribute('width'), '18');
    assert.ok((await action.boundingBox()).height >= 48);
    s.status = 200; await action.press('Enter'); await cards(page).first().waitFor();
    assert.equal(s.reads.at(-1).sort, 'name');
  }, { width, status: 422 }));
  it(`${width}px Revision L correction: no-results Clear filters is filled with a decorative filter icon`, () => using(async page => {
    await page.goto(origin + '/s-27?q=nothing'); const empty = root(page).locator('.s20-empty'); await empty.waitFor();
    const action = empty.getByRole('button', { name: 'Clear filters', exact: true });
    assert.equal(await action.evaluate(el => getComputedStyle(el).backgroundColor), 'rgb(46, 58, 140)');
    assert.equal(await action.evaluate(el => getComputedStyle(el).color), 'rgb(255, 255, 255)');
    assert.equal(await action.locator('svg').count(), 1);
    assert.equal(await action.locator('svg').getAttribute('width'), '18');
    assert.equal(await action.locator('svg').getAttribute('aria-hidden'), 'true');
    assert.equal(await empty.locator('.s20-state-icon').evaluate(el => getComputedStyle(el).color), 'rgb(46, 58, 140)');
    assert.ok((await action.boundingBox()).height >= 48);
  }, { width, items: [], total: 0 }));
  it(`${width}px Revision L correction: error focus keeps 16px corners and a visible focus ring`, () => using(async page => {
    await page.goto(origin + '/s-27'); const alert = root(page).getByRole('alert'); await alert.waitFor();
    await page.waitForFunction(() => document.activeElement?.getAttribute('role') === 'alert');
    const style = await alert.evaluate(el => { const s = getComputedStyle(el); return { radius: s.borderRadius, outline: s.outlineStyle, width: parseFloat(s.outlineWidth) }; });
    assert.equal(style.radius, '16px'); assert.equal(style.outline, 'solid'); assert.ok(style.width >= 2);
  }, { width, status: 500 }));
}
if (process.env.S27_DIAGNOSTIC_DIR) for (const width of [390, 1440]) it(`developer diagnostic only: ${width}px`, () => using(async page => {
  const dir = process.env.S27_DIAGNOSTIC_DIR; await mkdir(dir, { recursive: true });
  await page.goto(origin + '/s-27'); await cards(page).first().waitFor(); await page.evaluate(() => document.fonts.ready);
  await page.screenshot({ path: `${dir}/${width}-results.png`, fullPage: true });
  await page.getByText('Filters', { exact: true }).click(); await page.screenshot({ path: `${dir}/${width}-filters.png`, fullPage: true });
  await page.getByText('Filters', { exact: true }).click();
  for (let i = 1; i <= 2; i++) await page.getByRole('button', { name: `Add Synthetic Law School ${i} to comparison`, exact: true }).click();
  await page.screenshot({ path: `${dir}/${width}-compare.png`, fullPage: true });
}, { width, total: 5 }));
