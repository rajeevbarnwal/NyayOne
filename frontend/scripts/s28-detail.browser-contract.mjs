// Developer Chromium + synthetic API probes, not hosted conformance or independent QA.
import { before, after, it } from 'node:test';
import assert from 'node:assert/strict';
import { readFile, mkdir } from 'node:fs/promises';
import { setTimeout as delay } from 'node:timers/promises';
import { preview } from 'vite';
import { chromium } from 'playwright';
import { actor } from './lib/nyay66-fixtures.mjs';
let server, browser, origin;
before(async () => { server = await preview({ preview: { host: '127.0.0.1', port: 0 }, logLevel: 'error' }); origin = `http://127.0.0.1:${server.httpServer.address().port}`; browser = await chromium.launch(); });
after(async () => { await browser?.close(); await new Promise(done => server?.httpServer.close(done)); });
const school = { id: 'school-1', name: 'Synthetic Law School', slug: 'school-1', state: 'Delhi', institution_type: 'government', accreditation: 'BCI approved', entrance_exam: 'CLAT', fees_min: 150000, fees_max: 300000, nirf_rank: null, programmes: [{ degree: 'LLB', duration_years: 3 }], facts: [{ key: 'hostel', value: 'Available', source_name: 'Institution publication', source_url: 'https://example.test/facts', retrieved_at: '2026-07-01T00:00:00Z' }], saved: false, followed: false };
async function using(run, options = {}) {
 const context = await browser.newContext({ viewport: { width: options.width ?? 390, height: 844 }, reducedMotion: 'reduce' });
 const page = await context.newPage(); page.setDefaultTimeout(5000);
 const s = { authenticated: true, item: structuredClone(school), status: 200, writeStatus: 200, malformed: false, hold: false, held: [], reads: 0, writes: [], unexpected: [], ...options };
 await page.route('**/*', async route => {
  const req = route.request(), url = new URL(req.url()), method = req.method();
  if (url.origin !== origin && !(url.origin === 'http://localhost:1131' && url.pathname.startsWith('/api/v1/'))) { s.unexpected.push(url.origin); return route.abort(); }
  if (!url.pathname.startsWith('/api/v1/')) return route.continue();
  const reply = (body, status = 200) => route.fulfill({ status, contentType: 'application/json', body: JSON.stringify(body) }).catch(() => {});
  if (url.pathname === '/api/v1/auth/student/session') return reply(s.authenticated ? { authenticated: true, actor } : { authenticated: false, actor: null });
  if (url.pathname === '/api/v1/law-schools/school-1') {
   s.reads++; const body = structuredClone(s.item), status = s.status;
   const finish = () => reply(status === 200 ? body : { detail: { code: status === 404 ? 'school_not_found' : 'unavailable' } }, status);
   if (s.holdRead) { s.holdRead = false; s.held.push(finish); return; } return finish();
  }
  if (/\/student\/law-schools\/school-1\/(saved|follow)$/.test(url.pathname)) {
   const follow = url.pathname.endsWith('/follow'); s.writes.push({ method, follow, body: req.postDataJSON() });
   const finish = () => {
    if (s.writeStatus !== 200) { if (s.writeStatus === 401) s.authenticated = false; return reply({ detail: { code: s.writeStatus === 401 ? 'authentication_required' : 'unavailable' } }, s.writeStatus); }
    const on = method === 'PUT'; if (follow) s.item.followed = on; else s.item.saved = on;
    return reply(s.malformed ? {} : follow ? { followed: on, notify_opt_in: on && req.postDataJSON().notify_opt_in } : { saved: on });
   }; if (s.hold) { s.hold = false; s.held.push(finish); return; } return finish();
  }
  if (url.pathname === '/api/v1/student/law-schools/saved') {
   const body = { items: s.item.saved ? [structuredClone(s.item)] : [] };
   if(s.holdList){s.holdList=false;s.heldList=()=>reply(body);return;}return reply(body);
  }
  if (url.pathname === '/api/v1/student/law-schools/followed') return reply({ items: s.item.followed ? [{ ...s.item, notify_opt_in: false }] : [] });
  s.unexpected.push(method + ' ' + url.pathname); return route.abort();
 });
 try { await run(page, s); assert.deepEqual(s.unexpected, []); }
 catch(error) { console.error({ url: page.url(), text: (await page.locator('body').innerText()).slice(0, 1800), writes: s.writes, unexpected: s.unexpected }); throw error; }
 finally { await context.close(); }
}
const url = () => origin + '/s-28?id=school-1';
const save = page => page.getByRole('button', { name: 'Save', exact: true });
async function ready(page) { await page.getByRole('heading', { name: 'Synthetic Law School.', exact: true }).waitFor(); }
async function held(s) { const until = Date.now() + 5000; while (!s.held.length && Date.now() < until) await delay(10); assert.ok(s.held.length); }
it('Revision L detail shows truthful source attribution and a single main; back context is local', () => using(async page => {
 await page.goto(url() + '&ret=state%3DDelhi'); await ready(page);
 assert.equal(await page.locator('main').count(), 1); assert.equal(await page.locator('.ls-shell').count(), 0);
 assert.match(await page.locator('main').innerText(), /Published facts/i); assert.doesNotMatch(await page.locator('main').innerText(), /verified|sample|certified/i);
 const source = page.getByRole('link', { name: /Institution publication/ }); assert.equal(await source.getAttribute('href'), 'https://example.test/facts');
 assert.match(await page.locator('main').innerText(), /retrieved 1 Jul 2026/);
 assert.equal(await page.getByRole('link', { name: 'Find a law school', exact: true }).getAttribute('href'), '/s-27?state=Delhi');
}));
it('Save is server-confirmed, duplicate locked and remains focused; Unsave sends DELETE', () => using(async (page,s) => {
 await page.goto(url()); await ready(page); s.hold = true; const button = save(page); await button.focus(); await button.evaluate(el => { el.click(); el.click(); }); await held(s);
 assert.equal(s.writes.length, 1); assert.equal(await page.getByRole('button', { name: 'Saving', exact: true }).getAttribute('aria-pressed'), 'false'); assert.equal(await page.evaluate(() => document.activeElement?.tagName), 'BUTTON');
 await s.held.shift()(); await page.getByRole('button', { name: 'Saved', exact: true }).waitFor();
 await page.getByRole('button', { name: 'Saved', exact: true }).press('Enter'); await save(page).waitFor(); assert.deepEqual(s.writes.map(w => w.method), ['PUT','DELETE']);
}));
it('Follow defaults to no notification opt-in; checkbox persists separately after confirmation', () => using(async (page,s) => {
 await page.goto(url()); await ready(page); await page.getByRole('button', { name: 'Follow', exact: true }).press('Enter');
 const checkbox = page.getByRole('checkbox', { name: 'Notify me about updates to this school', exact: true }); await checkbox.waitFor(); assert.equal(await checkbox.isChecked(), false);
 assert.deepEqual(s.writes[0].body, { notify_opt_in: false }); s.hold = true; await checkbox.press('Space'); await held(s); assert.equal(await checkbox.isChecked(), false);
 await s.held.shift()(); await page.waitForFunction(() => document.querySelector('#s28-notify')?.checked === true);
 assert.deepEqual(s.writes[1].body, { notify_opt_in: true });
 await page.getByRole('button', { name: 'Following', exact: true }).click(); await page.getByRole('button', { name: 'Follow', exact: true }).waitFor();
 assert.equal(s.writes[2].method, 'DELETE');
}));
it('existing follow does not invent its unavailable notification preference', () => using(async (page,s) => {
 await page.goto(url()); await ready(page); assert.match(await page.locator('main').innerText(), /notification preference is not available/i);
 assert.equal(s.writes.length, 0); assert.equal(await page.getByRole('checkbox').count(), 0);
 await page.getByRole('button', { name: 'Keep notifications off', exact: true }).click(); await page.getByRole('checkbox').waitFor();
 assert.deepEqual(s.writes[0].body, { notify_opt_in: false });
}, { item: { ...school, followed: true } }));
for (const writeStatus of [403, 429, 503]) it(`failed ${writeStatus} mutation focuses notice and requires read before another mutation`, () => using(async (page,s) => {
 await page.goto(url()); await ready(page); await save(page).press('Enter'); await page.getByRole('alert').waitFor();
 await page.waitForFunction(() => document.activeElement?.getAttribute('role') === 'alert'); assert.equal(s.item.saved, false);
 assert.equal(await save(page).getAttribute('aria-disabled'), 'true');
 s.holdRead = true; const retry = page.getByRole('button', { name: 'Reload school', exact: true }); await retry.press('Enter'); await held(s);
 assert.notEqual(await page.evaluate(() => document.activeElement?.tagName), 'BODY'); await s.held.shift()(); await page.waitForFunction(() => document.querySelector('[data-s28-save]')?.getAttribute('aria-disabled') === 'false');
 assert.equal(s.writes.length, 1);
}, { writeStatus }));
it('late error does not steal user focus; malformed mutation never claims success', () => using(async (page,s) => {
 await page.goto(url()); await ready(page); s.hold = true; await save(page).press('Enter'); await held(s);
 const back = page.getByRole('link', { name: 'Find a law school', exact: true }); await back.focus(); await s.held.shift()(); await page.getByRole('alert').waitFor();
 assert.equal(await back.evaluate(el => el === document.activeElement), true); assert.equal(await page.getByRole('button', { name: 'Saved', exact: true }).count(), 0);
}, { malformed: true }));
it('session-expired mutation cannot keep private marks and exposes sign-in without a request loop', () => using(async (page,s) => {
 await page.goto(url()); await ready(page); await save(page).press('Enter'); await page.getByRole('link', { name: 'Sign in', exact: true }).waitFor();
 assert.equal(s.writes.length, 1); assert.equal(await page.getByRole('button', { name: 'Saved', exact: true }).count(), 0);
}, { writeStatus: 401 }));
for (const status of [404, 503]) it(`initial HTTP ${status} and retry keep meaningful focus without fabricated status`, () => using(async (page,s) => {
 await page.goto(url()); await page.getByRole('alert').waitFor(); await page.waitForFunction(() => document.activeElement?.getAttribute('role') === 'alert');
 assert.match(await page.locator('main').innerText(), new RegExp(`HTTP ${status}`));
 if (status === 503) { s.holdRead = true; await page.getByRole('button', { name: 'Retry', exact: true }).press('Enter'); await held(s); assert.notEqual(await page.evaluate(() => document.activeElement?.tagName), 'BODY'); await s.held.shift()(); await page.waitForFunction(() => document.activeElement?.getAttribute('role') === 'alert'); }
}, { status }));
it('anonymous readable detail has no enabled mutation or guessed private state', () => using(async (page,s) => {
 await page.goto(url()); await ready(page); await page.getByRole('link', { name: 'Sign in', exact: true }).waitFor(); assert.equal(await save(page).getAttribute('aria-disabled'), 'true'); assert.equal(s.writes.length, 0);
}, { authenticated: false }));
for (const width of [320,390,1440]) it(`${width}px reflow, 48px controls and serious/critical axe`, () => using(async page => {
 await page.goto(url()); await ready(page); assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), true);
 for (const button of await page.locator('.s28-detail button:visible,.s28-detail a:visible').all()) { const box = await button.boundingBox(); assert.ok(box.height >= 48, `target ${await button.innerText()} height=${box.height}`); }
 await page.addScriptTag({ content: await readFile('node_modules/axe-core/axe.min.js','utf8') });
 const failures = await page.evaluate(async () => (await window.axe.run(document, { runOnly: { type: 'tag', values: ['wcag2a','wcag2aa','wcag21aa'] } })).violations.filter(v=>['serious','critical'].includes(v.impact)));
 assert.deepEqual(failures.map(f=>({id:f.id,nodes:f.nodes.map(n=>n.target)})),[]);
 if(process.env.S28_DIAGNOSTICS){await mkdir(process.env.S28_DIAGNOSTICS,{recursive:true});await page.screenshot({path:`${process.env.S28_DIAGNOSTICS}/s28-${width}.png`,fullPage:true});}
}, { width }));

it('a delayed S-28 removal settles S-30 after navigation and rejects an older list snapshot', () => using(async(page,s)=>{
 await page.goto(origin+'/s-30'); const saved=page.getByRole('region',{name:'Saved schools',exact:true});
 await saved.getByRole('button',{name:'View',exact:true}).click(); await ready(page);
 s.hold=true; await page.getByRole('button',{name:'Saved',exact:true}).press('Enter'); await held(s);
 // Expire the legacy list's documented 30-second cache in this test only.
 await page.clock.setFixedTime(new Date(Date.now()+31000));
 s.holdList=true; await page.goBack(); await saved.waitFor();
 const until=Date.now()+5000;while(!s.heldList&&Date.now()<until)await delay(10);assert.ok(s.heldList);
 await s.held.shift()(); await saved.getByRole('button',{name:'Browse schools',exact:true}).waitFor();
 await s.heldList(); await page.evaluate(()=>new Promise(r=>requestAnimationFrame(()=>requestAnimationFrame(r))));
 assert.equal(await saved.getByRole('button',{name:'View',exact:true}).count(),0);assert.equal(s.writes.length,1);
}, {item:{...school,saved:true}}));
it('query/hash navigation during a held save keeps the lock and recovers on server acknowledgment', () => using(async(page,s)=>{
 await page.goto(url());await ready(page);s.hold=true;await save(page).press('Enter');await held(s);
 await page.evaluate(()=>{history.pushState({},'',location.href+'#facts');dispatchEvent(new PopStateEvent('popstate'));});
 await page.waitForFunction(()=>document.querySelector('[data-s28-save]')?.getAttribute('aria-disabled')==='true');
 await page.locator('[data-s28-save]').evaluate(el=>el.click());assert.equal(s.writes.length,1);
 await s.held.shift()();await page.getByRole('button',{name:'Saved',exact:true}).waitFor();
 await page.waitForFunction(()=>document.querySelector('[data-s28-save]')?.getAttribute('aria-disabled')==='false');
}));
