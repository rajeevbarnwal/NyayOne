/**
 * Wave 2 tutoring REAL-BROWSER driver (SAATHI-124 / SAATHI-128, matrix I1/I2/J1).
 *
 * Invoked by `scripts/wave2_tutoring_browser_gate.sh`, which has already put a
 * migrated+seeded SQLite database, a real uvicorn backend and a real production
 * frontend bundle in front of it. This file only drives Chromium and writes
 * evidence; it starts no server and owns no fixture.
 *
 * Honesty rules baked in:
 *   * every claim written to disk is either a DOM/geometry/network OBSERVATION
 *     made in this process, or is explicitly tagged `mechanism: "server_leg"`
 *     (an HTTP call this driver made as the payment/video provider, as the
 *     tutor, as a rival student or as an admin — actors a student's browser
 *     cannot be) or `mechanism: "clock_shift"` (a fixture row moved in time).
 *   * a stage that fails records the failure plus a screenshot and the run
 *     continues, so an interruption still leaves real evidence on disk.
 *   * nothing is asserted about a screen this driver did not actually load.
 *
 * Stages (E2E_STAGES, comma separated; `none` = boot only):
 *   a    S-31 discovery: filters, sort, pagination
 *   b    S-32 tutor detail + availability
 *   c    S-33 hold -> provider order -> paid webhook -> S-34 confirmation
 *   e    live-room entry with a real server-issued join credential
 *   geo  I2 live-room geometry / a11y measurement
 *   d1   S-35 reschedule outside the free window
 *   d2   S-35 <24h reschedule refusal, cancel with refund + cancel without
 *   d3   completion after scheduled end, attendance state, review gate
 *   d4   attendance confirm -> review allowed; dispute -> review blocked
 *   neg  hold expiry, slot conflict, payment failure, refused room entry
 *   rl   rate limit rendered in the browser
 *   priv J1 privacy scan over everything captured on disk
 */
import { chromium } from 'playwright';
import { createHmac, createHash } from 'node:crypto';
import { spawnSync } from 'node:child_process';
import fs from 'node:fs';
import path from 'node:path';

/* ------------------------------------------------------------------ config */

const WEB = must('E2E_WEB_URL');
const API = must('E2E_API_URL');
const OUT = must('E2E_OUT_DIR');
const FIXTURE_PATH = must('E2E_FIXTURE');
const STAGES = (process.env.E2E_STAGES || 'a').split(',').map((s) => s.trim()).filter(Boolean);
const PYTHON = process.env.E2E_PYTHON || 'python3';
const REPO_ROOT = process.env.E2E_REPO_ROOT || process.cwd();
const BACKEND_LOG = process.env.E2E_BACKEND_LOG || '';
const FEE_PAISE = Number(process.env.E2E_FEE_PAISE || '250000');

/** Compile-time constants of the deterministic adapters (not env secrets). */
const PAY_KEY = Buffer.from('legalsaathi-deterministic-payment-test-key');
const PAY_SIG_HEADER = 'X-Payment-Signature';

const STUDENT = '00000000-0000-4000-8000-0000000000de';
const RIVAL = '00000000-0000-4000-8000-0000000000b2';
const ADMIN = '00000000-0000-4000-8000-00000000ad01';

const MOBILE = { width: 390, height: 844 };

const DIRS = {
  shots: path.join(OUT, 'shots'),
  dom: path.join(OUT, 'dom'),
  net: path.join(OUT, 'net'),
  storage: path.join(OUT, 'storage'),
  traces: path.join(OUT, 'traces'),
  work: path.join(OUT, 'work'),
};
for (const d of Object.values(DIRS)) fs.mkdirSync(d, { recursive: true });

const FIXTURE = JSON.parse(fs.readFileSync(FIXTURE_PATH, 'utf8'));
const STATE_PATH = path.join(DIRS.work, 'state.json');
const RESULTS_PATH = path.join(OUT, 'journeys.json');

let STATE = fs.existsSync(STATE_PATH) ? JSON.parse(fs.readFileSync(STATE_PATH, 'utf8')) : {};
const RESULTS = fs.existsSync(RESULTS_PATH) ? JSON.parse(fs.readFileSync(RESULTS_PATH, 'utf8')) : [];

function must(name) {
  const v = process.env[name];
  if (!v) throw new Error(`${name} is required`);
  return v;
}
function saveState() {
  fs.writeFileSync(STATE_PATH, JSON.stringify(STATE, null, 2));
}
function saveResults() {
  fs.writeFileSync(RESULTS_PATH, JSON.stringify(RESULTS, null, 2));
}
function record(entry) {
  const idx = RESULTS.findIndex((r) => r.id === entry.id);
  const row = { ...entry, at: new Date().toISOString() };
  if (idx >= 0) RESULTS[idx] = row;
  else RESULTS.push(row);
  saveResults();
  const mark = row.outcome === 'pass' ? 'PASS' : row.outcome === 'defect' ? 'DEFECT' : row.outcome === 'skip' ? 'SKIP' : 'FAIL';
  console.log(`  [${mark}] ${row.id} — ${row.summary}`);
}

/* --------------------------------------------------------------- api client */

function claims(sub, roles = ['student']) {
  return JSON.stringify({ sub, roles });
}

async function api(method, urlPath, { sub = STUDENT, roles = ['student'], body, headers = {}, raw } = {}) {
  const init = { method, headers: { ...headers } };
  if (sub) init.headers['X-Actor-Claims'] = claims(sub, roles);
  if (raw !== undefined) {
    init.body = raw;
    init.headers['Content-Type'] = init.headers['Content-Type'] || 'application/json';
  } else if (body !== undefined) {
    init.body = JSON.stringify(body);
    init.headers['Content-Type'] = 'application/json';
  }
  const res = await fetch(`${API}${urlPath}`, init);
  let json = null;
  const text = await res.text();
  try {
    json = text ? JSON.parse(text) : null;
  } catch {
    json = { _unparsed: text.slice(0, 400) };
  }
  return { status: res.status, json };
}

/** The provider leg no browser can perform: a signature-verified paid event. */
async function payWebhook(orderRef, { amountPaise = FEE_PAISE, eventType = 'paid', eventId, currency = 'INR' } = {}) {
  const payload = {
    amount_paise: amountPaise,
    brand: 'TESTCARD',
    currency,
    event_id: eventId || `det_evt_${createHash('sha256').update(`${orderRef}:${eventType}:${Date.now()}`).digest('hex').slice(0, 20)}`,
    event_type: eventType,
    expiry_month: 12,
    expiry_year: 2030,
    masked_last4: '4242',
    order_ref: orderRef,
    provider: 'deterministic',
    token: 'tok_test_success',
  };
  const rawBody = JSON.stringify(payload, Object.keys(payload).sort());
  const sig = createHmac('sha256', PAY_KEY).update(Buffer.from(rawBody, 'utf8')).digest('hex');
  return api('POST', '/api/v1/payments/webhook', {
    sub: null,
    raw: rawBody,
    headers: { [PAY_SIG_HEADER]: sig },
  });
}

/* ----------------------------------------------------- fixture / db helpers */

function fixtureCmd(args) {
  const r = spawnSync(PYTHON, ['scripts/wave2_e2e_fixture.py', ...args], {
    cwd: path.join(REPO_ROOT, 'backend'),
    encoding: 'utf8',
    env: process.env,
  });
  if (r.status !== 0) throw new Error(`fixture ${args.join(' ')} failed: ${r.stderr || r.stdout}`);
  return JSON.parse(r.stdout.trim().split('\n').pop());
}

function dbPath() {
  const url = process.env.DATABASE_URL || '';
  const m = url.match(/sqlite\+pysqlite:\/\/\/(.*)$/);
  if (!m) throw new Error(`cannot read a sqlite path out of DATABASE_URL=${url}`);
  return m[1].startsWith('/') ? m[1] : path.join(REPO_ROOT, 'backend', m[1]);
}

/**
 * UUIDs are persisted dash-free by the SQLite UUID type, so every id used as a
 * bound parameter has to be normalised or the row silently does not match.
 */
const hex = (id) => String(id).replace(/-/g, '');

/** Read-only SQL against the same file the server is writing. The oracle. */
function dbQuery(sql, params = []) {
  params = params.map((p) => (typeof p === 'string' && /^[0-9a-f-]{32,36}$/i.test(p) ? hex(p) : p));
  const script = `
import json, sqlite3, sys
con = sqlite3.connect(sys.argv[1])
con.row_factory = sqlite3.Row
rows = [dict(r) for r in con.execute(sys.argv[2], json.loads(sys.argv[3]))]
print(json.dumps(rows, default=str))
`;
  const r = spawnSync(PYTHON, ['-c', script, dbPath(), sql, JSON.stringify(params)], { encoding: 'utf8' });
  if (r.status !== 0) throw new Error(`dbQuery failed: ${r.stderr}`);
  return JSON.parse(r.stdout);
}

/* ------------------------------------------------------------ page capture */

const NET = [];
const CONSOLE = [];

function attachCapture(page) {
  page.on('request', (req) => {
    let post = null;
    try {
      post = req.postData();
    } catch {
      post = null;
    }
    NET.push({
      dir: 'request',
      method: req.method(),
      url: req.url(),
      headers: req.headers(),
      postData: post ? String(post).slice(0, 4000) : null,
      at: new Date().toISOString(),
    });
  });
  page.on('response', async (res) => {
    const url = res.url();
    let bodyText = null;
    if (url.includes('/api/v1/')) {
      try {
        bodyText = (await res.text()).slice(0, 6000);
      } catch {
        bodyText = null;
      }
    }
    NET.push({ dir: 'response', status: res.status(), url, headers: res.headers(), body: bodyText, at: new Date().toISOString() });
  });
  page.on('console', (msg) => CONSOLE.push({ type: msg.type(), text: msg.text().slice(0, 600) }));
  page.on('pageerror', (err) => CONSOLE.push({ type: 'pageerror', text: String(err).slice(0, 600) }));
}

function flushNet(stage) {
  fs.writeFileSync(path.join(DIRS.net, `${stage}.json`), JSON.stringify(NET, null, 1));
  fs.writeFileSync(path.join(DIRS.net, `${stage}.console.json`), JSON.stringify(CONSOLE, null, 1));
}

/** Screenshot + DOM + storage + URL, all under one name. Returns the names. */
async function shot(page, name, { fullPage = true } = {}) {
  const file = `${name}.png`;
  await page.screenshot({ path: path.join(DIRS.shots, file), fullPage });
  fs.writeFileSync(path.join(DIRS.dom, `${name}.html`), await page.content());
  const store = await page.evaluate(() => {
    const dump = (s) => {
      const o = {};
      try {
        for (let i = 0; i < s.length; i++) o[s.key(i)] = s.getItem(s.key(i));
      } catch (e) {
        o._error = String(e);
      }
      return o;
    };
    return {
      url: location.href,
      localStorage: dump(window.localStorage),
      sessionStorage: dump(window.sessionStorage),
      cookie: document.cookie,
      title: document.title,
    };
  });
  fs.writeFileSync(path.join(DIRS.storage, `${name}.json`), JSON.stringify(store, null, 1));
  return file;
}

/* ------------------------------------------------------------- dom readers */

const BANNER = '.tt-banner';
const CODE_SEL = 'code.tt-banner__code';

async function banners(page) {
  return page.$$eval(BANNER, (els) =>
    els.map((el) => ({
      tone: (el.className.match(/tt-banner--(\w+)/) || [])[1] || null,
      role: el.getAttribute('role'),
      title: el.querySelector('.tt-banner__t')?.textContent?.trim() || null,
      detail: el.querySelector('.tt-banner__d')?.textContent?.trim() || null,
      code: el.querySelector('code.tt-banner__code')?.textContent?.trim() || null,
    })),
  );
}

async function waitForCode(page, code, timeout = 12000) {
  await page.waitForFunction(
    (want) => [...document.querySelectorAll('code.tt-banner__code')].some((c) => c.textContent.trim() === want),
    code,
    { timeout },
  );
}

async function cardNames(page) {
  return page.$$eval('article.tt-tut .tt-tut__nm', (els) => els.map((e) => e.textContent.trim()));
}

async function countLine(page) {
  return page.$$eval('p.tt-p.tt-muted', (els) => {
    const hit = els.find((e) => /Showing \d+ of \d+ mentors/.test(e.textContent));
    return hit ? hit.textContent.trim() : null;
  });
}

/** Any tutor in the packaged seed cast (extra pagination tutors have no slots). */
function seedTutorWithSlots() {
  const slot = FIXTURE.slots.find((s) => s.bucket === 'gt24h' && s.status === 'available');
  return slot ? slot.tutor_id : FIXTURE.slots[0]?.tutor_id;
}

function freeSlots(bucket = 'gt24h') {
  const used = new Set(STATE.usedSlots || []);
  return FIXTURE.slots.filter((s) => s.bucket === bucket && s.status === 'available' && !used.has(s.slot_id));
}

function takeSlot(bucket = 'gt24h') {
  const s = freeSlots(bucket)[0];
  if (!s) throw new Error(`no unused ${bucket} slot left in the fixture`);
  STATE.usedSlots = [...(STATE.usedSlots || []), s.slot_id];
  saveState();
  return s;
}

/* ------------------------------------------------------- booking primitive */

/**
 * The real S-33 booking leg, driven in the browser: mount creates the hold,
 * "Pay" creates the provider order, the PROVIDER (this driver, tagged as a
 * server leg) posts the signed `paid` event, then "Check payment and confirm"
 * is clicked and the confirmed session id is read back off the wire.
 */
async function bookInBrowser(page, slot, tag) {
  const orderRefs = [];
  const sessionIds = [];
  const onResponse = async (res) => {
    if (res.url().includes('/api/v1/payments/orders') && res.status() < 300) {
      try {
        orderRefs.push((await res.json()).provider_order_ref);
      } catch { /* body already consumed elsewhere */ }
    }
    if (res.url().match(/\/api\/v1\/tutoring\/sessions$/) && res.request().method() === 'POST' && res.status() < 300) {
      try {
        sessionIds.push((await res.json()).id);
      } catch { /* ignore */ }
    }
  };
  page.on('response', onResponse);
  try {
    await page.goto(`${WEB}/s-33?slot=${slot.slot_id}&tutor=${slot.tutor_id}`, { waitUntil: 'domcontentloaded' });
    await page.waitForSelector('div.tt-hold[role="timer"]', { timeout: 15000 });
    if (tag) await shot(page, `${tag}_hold`);

    const pay = page.locator('button.tt-btn--jade', { hasText: /securely/ });
    await pay.waitFor({ state: 'visible', timeout: 10000 });
    await pay.click();
    await page.waitForFunction(() => !!document.body.textContent.match(/Order reference|Waiting for the provider/), { timeout: 15000 });
    if (tag) await shot(page, `${tag}_order`);

    for (let i = 0; i < 40 && orderRefs.length === 0; i++) await page.waitForTimeout(100);
    const orderRef = orderRefs[orderRefs.length - 1];
    if (!orderRef) throw new Error('no provider_order_ref observed on POST /payments/orders');

    const hook = await payWebhook(orderRef);
    if (hook.status !== 200) throw new Error(`paid webhook rejected: ${hook.status} ${JSON.stringify(hook.json)}`);

    const confirm = page.locator('button.tt-btn--jade', { hasText: /Check payment and confirm/ });
    await confirm.waitFor({ state: 'visible', timeout: 10000 });
    await confirm.click();
    await page.waitForSelector('a.tt-btn--jade:has-text("View your confirmed session")', { timeout: 15000 });
    if (tag) await shot(page, `${tag}_confirmed`);

    const sessionId = sessionIds[sessionIds.length - 1] || hook.json.session_id;
    return { sessionId, orderRef, webhook: hook.json };
  } finally {
    page.off('response', onResponse);
  }
}

async function sessionRow(sessionId) {
  const rows = dbQuery('SELECT id, status, slot_id, tutor_id, student_user_id, order_id, version, start_utc, end_utc FROM tutoring_sessions WHERE id = ?', [sessionId]);
  return rows[0] || null;
}

async function apiSession(sessionId, sub = STUDENT) {
  const r = await api('GET', `/api/v1/tutoring/sessions/${sessionId}`, { sub });
  return r.json;
}

/** Move a session so its start is `hours` from now. Declared clock shift. */
async function shiftSessionTo(sessionId, hours) {
  const s = await apiSession(sessionId);
  const startMs = Date.parse(s.start_utc);
  const targetMs = Date.now() + hours * 3600 * 1000;
  const minutes = Math.round((targetMs - startMs) / 60000);
  return fixtureCmd(['shift-session', sessionId, '--minutes', String(minutes)]);
}

function tutorUserIdFor(tutorProfileId) {
  const profiles = FIXTURE.actors.tutor_profile_ids || {};
  const users = FIXTURE.actors.tutor_user_ids || {};
  for (const [key, pid] of Object.entries(profiles)) if (pid === tutorProfileId) return users[key];
  return null;
}

/* ================================================================= stages */

async function stageA(page) {
  const arts = [];
  await page.goto(`${WEB}/s-31`, { waitUntil: 'domcontentloaded' });
  await page.waitForSelector('article.tt-tut', { timeout: 20000 });
  arts.push(await shot(page, 'a1_s31_discovery_default'));
  const page1 = await cardNames(page);
  const line1 = await countLine(page);

  // sort
  await page.locator('div.tt-rails[aria-label="Sort results"] button.tt-rail', { hasText: 'Most experienced' }).click();
  await page.waitForFunction(() => location.search.includes('sort=experience_desc'), { timeout: 8000 });
  await page.waitForSelector('article.tt-tut', { timeout: 15000 });
  await page.waitForTimeout(300);
  arts.push(await shot(page, 'a2_s31_sort_experience_desc'));
  const sorted = await page.$$eval('article.tt-tut span.tt-hero', (els) => els.map((e) => parseInt(e.textContent, 10)));

  // filters
  await page.locator('details.tt-dis summary', { hasText: /^Refine/ }).click();
  await page.fill('#tt-subject', 'Legal Research');
  await page.locator('#tt-subject').blur();
  await page.waitForFunction(() => location.search.includes('subject=Legal'), { timeout: 8000 });
  await page.selectOption('#tt-minexp', '5');
  await page.waitForTimeout(600);
  arts.push(await shot(page, 'a3_s31_filter_subject_experience'));
  const filtered = await cardNames(page);
  const lineF = await countLine(page);

  const verified = page.locator('button.tt-btn', { hasText: /verified mentors only/ });
  await verified.click();
  await page.waitForFunction(() => location.search.includes('verified_only=1'), { timeout: 8000 });
  await page.waitForTimeout(500);
  arts.push(await shot(page, 'a4_s31_filter_verified_only'));
  const lineV = await countLine(page);

  // pagination on the unfiltered list
  await page.goto(`${WEB}/s-31`, { waitUntil: 'domcontentloaded' });
  await page.waitForSelector('article.tt-tut', { timeout: 15000 });
  const prevDisabled = await page.locator('button:has-text("Previous page")').isDisabled();
  const p1 = await cardNames(page);
  await page.locator('button:has-text("Next page")').click();
  await page.waitForFunction(() => location.search.includes('offset=10'), { timeout: 8000 });
  await page.waitForSelector('article.tt-tut', { timeout: 15000 });
  await page.waitForTimeout(300);
  arts.push(await shot(page, 'a5_s31_pagination_page2'));
  const p2 = await cardNames(page);
  const line2 = await countLine(page);

  const overlap = p1.filter((n) => p2.includes(n));
  const sortedDesc = sorted.every((v, i) => i === 0 || sorted[i - 1] >= v);
  const ok = page1.length > 0 && p1.length === 10 && p2.length > 0 && overlap.length === 0 && prevDisabled && sortedDesc;
  record({
    id: 'I1-a-S31-discovery',
    stage: 'a',
    matrix: 'I1',
    outcome: ok ? 'pass' : 'fail',
    summary: `S-31 in Chromium: ${line1}; page1=${p1.length} cards, page2=${p2.length} cards, overlap=${overlap.length}, Previous disabled at offset 0=${prevDisabled}, experience_desc monotonic=${sortedDesc}`,
    observed: { defaultCountLine: line1, page2CountLine: line2, filteredCountLine: lineF, verifiedCountLine: lineV, experienceYearsInSortOrder: sorted, page1: p1, page2: p2, filtered },
    artifacts: arts,
  });
}

async function stageB(page) {
  const arts = [];
  const tutorId = seedTutorWithSlots();
  await page.goto(`${WEB}/s-32?tutor=${tutorId}`, { waitUntil: 'domcontentloaded' });
  await page.waitForSelector('section.tt-phead h1', { timeout: 20000 });
  await page.waitForSelector('div.tt-slots button.tt-slotbtn', { timeout: 20000 });
  arts.push(await shot(page, 'b1_s32_detail_availability'));
  const detail = await page.evaluate(() => ({
    name: document.querySelector('section.tt-phead h1')?.textContent?.trim(),
    chips: [...document.querySelectorAll('section.tt-phead span.tt-chip')].map((c) => c.textContent.trim()),
    provenance: [...document.querySelectorAll('details.tt-dis .tt-kv')].map((k) => k.textContent.trim()).slice(0, 12),
    slots: [...document.querySelectorAll('div.tt-slots button.tt-slotbtn')].map((b) => ({
      label: b.querySelector('.tt-sl')?.textContent?.trim(),
      state: b.querySelector('.tt-chip')?.textContent?.trim(),
      disabled: b.disabled,
    })),
  }));
  await page.selectOption('#tt-tz', 'Europe/London');
  await page.waitForFunction(() => location.search.includes('tz=Europe'), { timeout: 8000 });
  await page.waitForTimeout(600);
  arts.push(await shot(page, 'b2_s32_availability_timezone_london'));
  const londonLabels = await page.$$eval('div.tt-slots button.tt-slotbtn .tt-sl', (e) => e.map((x) => x.textContent.trim()));

  const ok = !!detail.name && detail.slots.length > 0 && detail.provenance.length > 0;
  record({
    id: 'I1-b-S32-detail-availability',
    stage: 'b',
    matrix: 'I1',
    outcome: ok ? 'pass' : 'fail',
    summary: `S-32 in Chromium for ${detail.name}: ${detail.slots.length} availability buttons, ${detail.chips.length} verification/rating chips, ${detail.provenance.length} provenance rows; timezone switch relabelled slots (${londonLabels[0] || 'n/a'})`,
    observed: { tutorId, ...detail, londonLabels },
    artifacts: arts,
  });
}

async function stageC(page) {
  const arts = [];
  const slot = takeSlot('gt24h');
  const booked = await bookInBrowser(page, slot, 'c1_s33');
  arts.push('c1_s33_hold.png', 'c1_s33_order.png', 'c1_s33_confirmed.png');

  // in-product route to S-34: dock link -> S-35 list -> Open -> Receipt
  await page.locator('a.tt-btn--jade:has-text("View your confirmed session")').click();
  await page.waitForSelector('article.tt-tut', { timeout: 15000 });
  arts.push(await shot(page, 'c2_s35_list_after_booking'));
  await page.locator('article.tt-tut button.tt-btn--jade:has-text("Open")').first().click();
  await page.waitForFunction(() => location.search.includes('view=manage'), { timeout: 10000 });
  await page.waitForSelector('h1', { timeout: 10000 });
  arts.push(await shot(page, 'c3_s35_manage'));
  await page.locator('a.tt-btn:has-text("Receipt")').click();
  await page.waitForFunction(() => location.pathname === '/s-34', { timeout: 10000 });
  await page.waitForSelector('h1', { timeout: 10000 });
  arts.push(await shot(page, 'c4_s34_confirmation'));
  const s34 = await page.evaluate(() => ({
    heading: document.querySelector('h1')?.textContent?.trim(),
    seal: !!document.querySelector('span.tt-seal'),
    kv: [...document.querySelectorAll('.tt-kv')].map((k) => k.textContent.trim()),
    banners: [...document.querySelectorAll('.tt-banner__t')].map((b) => b.textContent.trim()),
  }));

  const row = await sessionRow(booked.sessionId);
  STATE.s1 = booked.sessionId;
  STATE.s1Order = booked.orderRef;
  saveState();

  const ok = !!row && ['confirmed', 'scheduled'].includes(row.status) && row.student_user_id.replace(/-/g, '') === STUDENT.replace(/-/g, '') && !!row.order_id && /booked/i.test(s34.heading || '');
  record({
    id: 'I1-c-S33-S34-book-pay-confirm',
    stage: 'c',
    matrix: 'I1',
    outcome: ok ? 'pass' : 'fail',
    summary: `booked in the browser: hold -> order ${booked.orderRef} -> signed paid webhook (server leg) -> "Check payment and confirm"; S-34 shows "${s34.heading}"; DB row ${booked.sessionId} status=${row?.status} order_id=${row?.order_id ? 'set' : 'null'} student=${row?.student_user_id}`,
    observed: { sessionId: booked.sessionId, slotId: slot.slot_id, dbRow: row, s34, webhook: booked.webhook },
    mechanism: { paidEvent: 'server_leg', note: 'the signed provider event is posted by this driver acting as the payment provider; every other step is a real click' },
    artifacts: arts,
  });
}

async function stageE(page) {
  const arts = [];
  const sessionId = STATE.s1;
  if (!sessionId) return record({ id: 'I1-e-live-room-entry', stage: 'e', matrix: 'I1', outcome: 'skip', summary: 'no confirmed session in state.json (run stage c first)', artifacts: [] });

  const creds = [];
  const onResponse = async (res) => {
    if (res.url().includes('/join-credentials')) {
      try {
        creds.push({ status: res.status(), json: await res.json() });
      } catch { /* ignore */ }
    }
  };
  page.on('response', onResponse);
  try {
    await page.goto(`${WEB}/s-35?session=${sessionId}&view=prejoin`, { waitUntil: 'domcontentloaded' });
    await page.waitForSelector('div.tt-preview', { timeout: 15000 });
    arts.push(await shot(page, 'e1_s35_prejoin'));
    const test = page.locator('button', { hasText: /Test camera and microphone/ });
    await test.click();
    await page.waitForFunction(() => /detected/.test(document.body.textContent), { timeout: 15000 });
    arts.push(await shot(page, 'e2_s35_prejoin_devices_ok'));
    const chips = await page.$$eval('span.tt-chip', (e) => e.map((x) => x.textContent.trim()).filter((t) => /detected/.test(t)));

    await page.locator('button', { hasText: /^Enter the room$/ }).click();
    await page.waitForSelector('main.tt-live', { timeout: 15000 });
    await page.waitForFunction(() => /In the room|Not admitted/.test(document.querySelector('div.tt-lh')?.textContent || ''), { timeout: 20000 });
    arts.push(await shot(page, 'e3_s35_live_room', { fullPage: false }));
    const headChip = await page.$eval('div.tt-lh span.tt-chip', (e) => e.textContent.trim());

    await page.locator('button.tt-cb[aria-label="Session, connection and privacy details"]').click();
    await page.waitForSelector('div.tt-sheet[data-open="1"]', { timeout: 8000 });
    arts.push(await shot(page, 'e4_s35_live_room_details_sheet', { fullPage: false }));
    const sheet = await page.$$eval('div.tt-sheet .tt-kv', (els) => els.map((e) => e.textContent.trim()));

    const cred = creds.find((c) => c.status === 201);
    const rawToken = cred?.json?.join_token || null;
    // in-memory leak check against the literal token; never persisted
    const leak = rawToken
      ? await page.evaluate((tok) => {
          const store = (s) => {
            const out = [];
            for (let i = 0; i < s.length; i++) out.push(`${s.key(i)}=${s.getItem(s.key(i))}`);
            return out.join('|');
          };
          return {
            dom: document.documentElement.outerHTML.includes(tok),
            local: store(localStorage).includes(tok),
            session: store(sessionStorage).includes(tok),
            cookie: document.cookie.includes(tok),
            url: location.href.includes(tok),
          };
        }, rawToken)
      : null;
    const grants = dbQuery('SELECT id, session_id, participant_ref, room_ref, permissions, revoked_at, expires_at, length(token_hash) AS hash_len FROM video_session_grants WHERE session_id = ?', [sessionId]);
    STATE.roomRef = cred?.json?.room_ref || null;
    STATE.participantRef = cred?.json?.participant_ref || null;
    saveState();

    const redacted = sheet.some((r) => /redacted/i.test(r) && /in memory only/i.test(r));
    const ok = !!cred && /In the room/.test(headChip) && grants.length > 0 && redacted && leak && !Object.values(leak).some(Boolean);
    record({
      id: 'I1-e-live-room-entry',
      stage: 'e',
      matrix: 'I1/J1',
      outcome: ok ? 'pass' : 'fail',
      summary: `live room entered with a server-issued credential: POST /join-credentials ${cred?.status}, room_ref=${cred?.json?.room_ref}, ttl=${cred?.json?.ttl_seconds}s, header chip "${headChip}", ${grants.length} grant row(s) storing only a ${grants[0]?.hash_len}-char token hash; sheet shows the credential redacted=${redacted}; raw-token leak into DOM/storage/cookie/URL=${leak ? JSON.stringify(leak) : 'n/a'}`,
      observed: { credentialStatus: cred?.status, roomRef: cred?.json?.room_ref, participantRef: cred?.json?.participant_ref, ttlSeconds: cred?.json?.ttl_seconds, permissions: cred?.json?.permissions, tokenPrefix: rawToken ? `${rawToken.slice(0, 5)}…(${rawToken.length} chars)` : null, headChip, deviceChips: chips, sheetRows: sheet, grants, rawTokenLeak: leak },
      artifacts: arts,
    });
  } finally {
    page.off('response', onResponse);
  }
}

async function stageGeo(browser) {
  const sessionId = STATE.s1;
  if (!sessionId) return record({ id: 'I2-live-room-geometry-a11y', stage: 'geo', matrix: 'I2', outcome: 'skip', summary: 'no confirmed session in state.json (run stage c first)', artifacts: [] });

  const arts = [];
  const measure = async (ctx, label, { fullPage = false } = {}) => {
    const page = await ctx.newPage();
    attachCapture(page);
    await page.goto(`${WEB}/s-35?session=${sessionId}&view=room`, { waitUntil: 'domcontentloaded' });
    await page.waitForSelector('main.tt-live', { timeout: 20000 });
    await page.waitForTimeout(1200);
    const m = await page.evaluate(() => {
      const de = document.documentElement;
      const live = document.querySelector('main.tt-live');
      const r = live?.getBoundingClientRect();
      const targets = [...document.querySelectorAll('button, a[href], select, input, [role="radio"], [role="button"]')]
        .filter((el) => {
          const b = el.getBoundingClientRect();
          const cs = getComputedStyle(el);
          return b.width > 0 && b.height > 0 && cs.visibility !== 'hidden' && cs.display !== 'none';
        })
        .map((el) => {
          const b = el.getBoundingClientRect();
          return {
            label: (el.getAttribute('aria-label') || el.textContent || '').trim().slice(0, 48),
            w: Math.round(b.width * 10) / 10,
            h: Math.round(b.height * 10) / 10,
          };
        });
      const under = targets.filter((t) => t.w < 44 || t.h < 44);
      const dvh = (() => {
        const probe = document.createElement('div');
        probe.style.cssText = 'position:fixed;top:0;left:0;height:100dvh;width:1px;pointer-events:none;opacity:0';
        document.body.appendChild(probe);
        const h = probe.getBoundingClientRect().height;
        probe.remove();
        return h;
      })();
      const insetProbe = (() => {
        const p = document.createElement('div');
        p.style.cssText = 'position:fixed;padding:env(safe-area-inset-top) env(safe-area-inset-right) env(safe-area-inset-bottom) env(safe-area-inset-left);opacity:0;pointer-events:none';
        document.body.appendChild(p);
        const cs = getComputedStyle(p);
        const v = { top: cs.paddingTop, right: cs.paddingRight, bottom: cs.paddingBottom, left: cs.paddingLeft };
        p.remove();
        return v;
      })();
      const ctrl = document.querySelector('div.tt-lctrl');
      const ctrlCs = ctrl ? getComputedStyle(ctrl) : null;
      const anim = [...document.querySelectorAll('*')]
        .map((el) => getComputedStyle(el))
        .filter((cs) => (parseFloat(cs.animationDuration) || 0) > 0 || (parseFloat(cs.transitionDuration) || 0) > 0)
        .map((cs) => ({ animation: cs.animationDuration, transition: cs.transitionDuration }));
      return {
        viewport: { w: window.innerWidth, h: window.innerHeight, dpr: window.devicePixelRatio },
        cssDvhPx: Math.round(dvh * 10) / 10,
        liveRect: r ? { w: Math.round(r.width * 10) / 10, h: Math.round(r.height * 10) / 10 } : null,
        pageScroll: { scrollHeight: de.scrollHeight, clientHeight: de.clientHeight, verticalOverflowPx: de.scrollHeight - de.clientHeight },
        horizontal: { scrollWidth: de.scrollWidth, clientWidth: de.clientWidth, horizontalOverflowPx: de.scrollWidth - de.clientWidth },
        bodyOverflow: getComputedStyle(document.body).overflow,
        roomAttr: { html: de.dataset.ttRoom || null, body: document.body.dataset.ttRoom || null },
        targets: { total: targets.length, under44: under },
        safeAreaEnvResolved: insetProbe,
        controlPadding: ctrlCs ? { bottom: ctrlCs.paddingBottom, usesEnv: /env\(/.test(ctrl.getAttribute('style') || '') } : null,
        animatedElements: anim.length,
        longestAnimationSeconds: anim.reduce((mx, a) => Math.max(mx, parseFloat(a.animation) || 0, parseFloat(a.transition) || 0), 0),
      };
    });
    // focus ring
    const focus = await page.evaluate(() => {
      const btn = document.querySelector('div.tt-lctrl button.tt-cb');
      if (!btn) return null;
      const before = getComputedStyle(btn);
      const base = { outlineWidth: before.outlineWidth, outlineStyle: before.outlineStyle, boxShadow: before.boxShadow };
      btn.focus();
      const after = getComputedStyle(btn);
      const now = { outlineWidth: after.outlineWidth, outlineStyle: after.outlineStyle, boxShadow: after.boxShadow, isFocused: document.activeElement === btn };
      return { base, focused: now, changed: base.outlineWidth !== now.outlineWidth || base.boxShadow !== now.boxShadow || base.outlineStyle !== now.outlineStyle };
    });
    await page.keyboard.press('Tab');
    const file = await shot(page, `geo_${label}`, { fullPage });
    m.focusRing = focus;
    m.colors = await page.evaluate(() => {
      const cs = getComputedStyle(document.querySelector('main.tt-live'));
      const chip = document.querySelector('div.tt-lh span.tt-chip');
      return { liveBackground: cs.backgroundColor, liveColor: cs.color, chipColor: chip ? getComputedStyle(chip).color : null, chipBackground: chip ? getComputedStyle(chip).backgroundColor : null };
    });
    m.screenshot = file;
    await page.close();
    return m;
  };

  const results = {};
  const base = await browser.newContext({ viewport: MOBILE, permissions: [], colorScheme: 'light' });
  results.mobile_light_390x844 = await measure(base, 'mobile_light_390x844');
  await base.close();

  const dark = await browser.newContext({ viewport: MOBILE, colorScheme: 'dark' });
  results.mobile_dark_390x844 = await measure(dark, 'mobile_dark_390x844');
  await dark.close();

  // 200% zoom == half the CSS viewport at 2x device scale
  const zoom = await browser.newContext({ viewport: { width: 195, height: 422 }, deviceScaleFactor: 2, colorScheme: 'light' });
  results.zoom200_195x422_dsf2 = await measure(zoom, 'zoom200_195x422_dsf2');
  await zoom.close();

  const rm = await browser.newContext({ viewport: MOBILE, reducedMotion: 'reduce', colorScheme: 'light' });
  results.reduced_motion_390x844 = await measure(rm, 'reduced_motion_390x844');
  await rm.close();

  const desk = await browser.newContext({ viewport: { width: 1280, height: 800 }, colorScheme: 'light' });
  results.desktop_light_1280x800 = await measure(desk, 'desktop_light_1280x800');
  await desk.close();

  for (const [k, v] of Object.entries(results)) arts.push(v.screenshot);
  const noPageScroll = Object.values(results).every((r) => r.pageScroll.verticalOverflowPx <= 1);
  const noHorizontal = Object.values(results).every((r) => r.horizontal.horizontalOverflowPx <= 1);
  const dvhOk = Object.values(results).every((r) => Math.abs(r.cssDvhPx - r.viewport.h) <= 1 && r.liveRect && Math.abs(r.liveRect.h - r.viewport.h) <= 1);
  const targetsOk = Object.values(results).every((r) => r.targets.under44.length === 0);
  const focusOk = Object.values(results).every((r) => r.focusRing && r.focusRing.changed);
  const reducedOk = results.reduced_motion_390x844.longestAnimationSeconds <= 0.001;

  fs.writeFileSync(path.join(OUT, 'browser_matrix.json'), JSON.stringify({
    generatedAt: new Date().toISOString(),
    matrixRow: 'I2',
    surface: `/s-35?view=room (live room), session ${sessionId}`,
    browser: STATE.browserVersion || null,
    verdicts: { noPageScroll, noHorizontalOverflow: noHorizontal, hundredDvhMatchesViewport: dvhOk, allTargetsAtLeast44px: targetsOk, visibleFocusRing: focusOk, reducedMotionHonoured: reducedOk },
    measurements: results,
  }, null, 2));
  arts.push('browser_matrix.json');

  record({
    id: 'I2-live-room-geometry-a11y',
    stage: 'geo',
    matrix: 'I2',
    outcome: noPageScroll && noHorizontal && dvhOk && targetsOk && focusOk && reducedOk ? 'pass' : 'fail',
    summary: `room measured in 5 configurations: 100dvh=${results.mobile_light_390x844.cssDvhPx}px vs viewport ${results.mobile_light_390x844.viewport.h}px, page vertical overflow ${Object.values(results).map((r) => r.pageScroll.verticalOverflowPx).join('/')}px, horizontal overflow ${Object.values(results).map((r) => r.horizontal.horizontalOverflowPx).join('/')}px, ${results.mobile_light_390x844.targets.total} targets with ${results.mobile_light_390x844.targets.under44.length} under 44px, reduced-motion longest animation ${results.reduced_motion_390x844.longestAnimationSeconds}s, focus ring changes on focus=${focusOk}`,
    observed: results,
    artifacts: arts,
  });
}

async function stageD1(page) {
  const sessionId = STATE.s1;
  if (!sessionId) return record({ id: 'I1-d1-reschedule-outside-window', stage: 'd1', matrix: 'I1', outcome: 'skip', summary: 'no session in state.json', artifacts: [] });
  const arts = [];
  await page.goto(`${WEB}/s-35?session=${sessionId}&view=policy`, { waitUntil: 'domcontentloaded' });
  await page.waitForSelector('h2', { timeout: 15000 });
  arts.push(await shot(page, 'd1_s35_policy_outside_window'));
  const policy = await banners(page);
  const kv = await page.$$eval('.tt-kv', (e) => e.map((x) => x.textContent.trim()));
  await page.locator('button', { hasText: /Reschedule/ }).first().click();
  await page.waitForFunction(() => location.search.includes('view=reschedule'), { timeout: 10000 });
  await page.waitForSelector('div.tt-slots button.tt-slotbtn', { timeout: 15000 });
  arts.push(await shot(page, 'd2_s35_reschedule_choose'));
  const before = await apiSession(sessionId);
  await page.locator('div.tt-slots button.tt-slotbtn').first().click();
  await page.locator('button', { hasText: /Confirm the new time/ }).click();
  await page.waitForFunction(() => location.search.includes('view=manage'), { timeout: 20000 });
  await page.waitForTimeout(600);
  arts.push(await shot(page, 'd3_s35_rescheduled'));
  const after = await apiSession(sessionId);
  const row = await sessionRow(sessionId);
  const ok = after.slot_id !== before.slot_id && after.version > before.version && ['rescheduled', 'confirmed'].includes(row.status);
  record({
    id: 'I1-d1-reschedule-outside-window',
    stage: 'd1',
    matrix: 'I1',
    outcome: ok ? 'pass' : 'fail',
    summary: `reschedule accepted outside the free window: slot ${before.slot_id} -> ${after.slot_id}, version ${before.version} -> ${after.version}, DB status=${row.status}; policy banner "${policy[0]?.title}"`,
    observed: { policyBanners: policy, policyKv: kv, before: { slot: before.slot_id, version: before.version, start: before.start_utc }, after: { slot: after.slot_id, version: after.version, start: after.start_utc }, dbRow: row },
    artifacts: arts,
  });
}

async function stageD2(page) {
  const arts = [];
  // S2: booked, then clock-shifted inside the window -> reschedule refused, cancel with no refund
  const slot2 = takeSlot('gt24h');
  const b2 = await bookInBrowser(page, slot2, null);
  STATE.s2 = b2.sessionId;
  saveState();
  const shift = await shiftSessionTo(b2.sessionId, 3);

  await page.goto(`${WEB}/s-35?session=${b2.sessionId}&view=policy`, { waitUntil: 'domcontentloaded' });
  await page.waitForSelector('h2', { timeout: 15000 });
  arts.push(await shot(page, 'd4_s35_policy_inside_window'));
  const insideBanners = await banners(page);
  await page.locator('button', { hasText: /reschedule/i }).first().click();
  await page.waitForFunction(() => location.search.includes('view=reschedule'), { timeout: 10000 });
  await page.waitForSelector('div.tt-slots button.tt-slotbtn', { timeout: 15000 });
  await page.locator('div.tt-slots button.tt-slotbtn').first().click();
  await page.locator('button', { hasText: /Confirm the new time/ }).click();
  let refusalCode = null;
  try {
    await waitForCode(page, 'RESCHEDULE_WINDOW_CLOSED', 15000);
    refusalCode = 'RESCHEDULE_WINDOW_CLOSED';
  } catch {
    refusalCode = (await banners(page)).map((b) => b.code).filter(Boolean).join(',') || null;
  }
  arts.push(await shot(page, 'd5_s35_reschedule_window_closed'));
  const refusal = await banners(page);

  // cancel inside the window -> NO_AUTO_REFUND
  await page.goto(`${WEB}/s-35?session=${b2.sessionId}&view=manage`, { waitUntil: 'domcontentloaded' });
  await page.waitForSelector('h1', { timeout: 15000 });
  await page.locator('button', { hasText: /Cancel this session/ }).click();
  await page.waitForSelector('div.tt-modal[role="dialog"]', { timeout: 8000 });
  arts.push(await shot(page, 'd6_s35_cancel_modal_inside_window'));
  await page.locator('div.tt-modal button', { hasText: /Yes, cancel/ }).click();
  await page.waitForFunction(() => /Cancelled with/.test(document.body.textContent), { timeout: 20000 });
  arts.push(await shot(page, 'd7_s35_cancel_no_auto_refund'));
  const noRefund = await banners(page);
  const s2row = await sessionRow(b2.sessionId);
  const s2refunds = dbQuery('SELECT c.id AS id, c.refund_decision AS decision, c.cancelled_by_role AS cancelled_by_role, c.audited AS audited, c.hours_before_start AS hours_before_start, (SELECT r.amount_paise FROM payment_refunds r JOIN tutoring_sessions s ON s.order_id = r.order_id WHERE s.id = c.session_id ORDER BY r.created_at DESC LIMIT 1) AS amount_paise FROM session_cancellations c WHERE c.session_id = ?', [b2.sessionId]);

  // S3: booked and cancelled outside the window -> FULL_REFUND
  const slot3 = takeSlot('gt24h');
  const b3 = await bookInBrowser(page, slot3, null);
  STATE.s3 = b3.sessionId;
  saveState();
  await page.goto(`${WEB}/s-35?session=${b3.sessionId}&view=manage`, { waitUntil: 'domcontentloaded' });
  await page.waitForSelector('h1', { timeout: 15000 });
  await page.locator('button', { hasText: /Cancel this session/ }).click();
  await page.waitForSelector('div.tt-modal[role="dialog"]', { timeout: 8000 });
  await page.locator('div.tt-modal button', { hasText: /Yes, cancel/ }).click();
  await page.waitForFunction(() => /Cancelled with/.test(document.body.textContent), { timeout: 20000 });
  arts.push(await shot(page, 'd8_s35_cancel_full_refund'));
  const fullRefund = await banners(page);
  const amount = await page.$eval('div.tt-amt .tt-amt__big', (e) => e.textContent.trim()).catch(() => null);
  const prog = await page.$eval('div.tt-prog', (e) => e.getAttribute('aria-label')).catch(() => null);
  const s3refunds = dbQuery('SELECT c.id AS id, c.refund_decision AS decision, c.cancelled_by_role AS cancelled_by_role, c.audited AS audited, c.hours_before_start AS hours_before_start, (SELECT r.amount_paise FROM payment_refunds r JOIN tutoring_sessions s ON s.order_id = r.order_id WHERE s.id = c.session_id ORDER BY r.created_at DESC LIMIT 1) AS amount_paise FROM session_cancellations c WHERE c.session_id = ?', [b3.sessionId]);
  const s3row = await sessionRow(b3.sessionId);

  const ok = refusalCode === 'RESCHEDULE_WINDOW_CLOSED'
    && s2refunds[0]?.decision === 'no_auto_refund' && s2row.status === 'cancelled'
    && s3refunds[0]?.decision === 'full_refund' && s3row.status === 'cancelled';
  record({
    id: 'I1-d2-policy-cancel-refund',
    stage: 'd2',
    matrix: 'I1',
    outcome: ok ? 'pass' : 'fail',
    summary: `inside-window reschedule refused in the browser with code ${refusalCode}; cancel inside window -> "${noRefund.find((b) => /Cancelled/.test(b.title || ''))?.title}" (DB decision=${s2refunds[0]?.decision} amount=${s2refunds[0]?.amount_paise} h_before=${s2refunds[0]?.hours_before_start}); cancel outside window -> "${fullRefund.find((b) => /Cancelled/.test(b.title || ''))?.title}" amount shown ${amount} (DB decision=${s3refunds[0]?.decision} amount=${s3refunds[0]?.amount_paise} h_before=${s3refunds[0]?.hours_before_start} by=${s3refunds[0]?.cancelled_by_role})`,
    observed: { s2: b2.sessionId, s3: b3.sessionId, clockShift: shift, insideBanners, refusal, noRefund, fullRefund, refundAmountShown: amount, refundProgress: prog, s2refunds, s3refunds, s2row, s3row },
    mechanism: { clockShift: 'clock_shift', note: 'S2 was moved to 3h from now on its own row; no wall-clock time elapsed' },
    artifacts: arts,
  });
}

async function stageD3(page) {
  const sessionId = STATE.s1;
  if (!sessionId) return record({ id: 'I1-d3-completion-attendance', stage: 'd3', matrix: 'I1', outcome: 'skip', summary: 'no session in state.json', artifacts: [] });
  const arts = [];
  const s = await apiSession(sessionId);

  // 1. completion refused before the scheduled end (real server refusal, browser-rendered)
  await page.goto(`${WEB}/s-35?session=${sessionId}&view=attendance`, { waitUntil: 'domcontentloaded' });
  await page.waitForSelector('.tt-banner', { timeout: 15000 });
  arts.push(await shot(page, 'd9_s35_attendance_before_end'));
  const beforeEnd = await banners(page);
  const early = await api('POST', `/api/v1/tutoring/sessions/${sessionId}/complete`, { sub: STUDENT, roles: ['tutor'] });

  // 2. move the session past its end (declared clock shift) and try completion IN THE BROWSER
  const shift = await shiftSessionTo(sessionId, -1.6);
  await page.goto(`${WEB}/s-35?session=${sessionId}&view=manage`, { waitUntil: 'domcontentloaded' });
  await page.waitForSelector('h1', { timeout: 15000 });
  const completeBtn = page.locator('button', { hasText: /Record completion/ });
  const hasCompleteBtn = await completeBtn.count();
  let studentComplete = null;
  if (hasCompleteBtn) {
    await completeBtn.click();
    await page.waitForTimeout(1500);
    arts.push(await shot(page, 'd10_s35_student_completion_refused'));
    studentComplete = await banners(page);
  }

  // 3. the real recorder is the tutor: server leg with tutor claims
  const tutorUserId = tutorUserIdFor(s.tutor_id);
  const done = await api('POST', `/api/v1/tutoring/sessions/${sessionId}/complete`, { sub: tutorUserId, roles: ['tutor'] });

  await page.goto(`${WEB}/s-35?session=${sessionId}&view=attendance`, { waitUntil: 'domcontentloaded' });
  await page.waitForSelector('.tt-banner', { timeout: 15000 });
  await page.waitForTimeout(500);
  arts.push(await shot(page, 'd11_s35_attendance_after_completion'));
  const afterBanners = await banners(page);
  const dock = await page.$$eval('div.tt-dock button, .tt-dock button', (e) => e.map((x) => x.textContent.trim()));

  await page.goto(`${WEB}/s-35?session=${sessionId}&view=review`, { waitUntil: 'domcontentloaded' });
  await page.waitForSelector('.tt-banner', { timeout: 15000 });
  arts.push(await shot(page, 'd12_s35_review_blocked'));
  const reviewBanners = await banners(page);
  const serverReview = await api('POST', `/api/v1/tutoring/sessions/${sessionId}/review`, { sub: STUDENT, body: { rating: 5 } });

  const att = dbQuery('SELECT id, state, version, recorded_by_role FROM session_attendance WHERE session_id = ?', [sessionId]);
  const confirmOffered = dock.some((d) => /Confirm attendance/.test(d));
  const feState = afterBanners.map((b) => b.code).find((c) => c && c.startsWith('ATTENDANCE_'));

  record({
    id: 'I1-d3-completion-attendance',
    stage: 'd3',
    matrix: 'I1',
    outcome: confirmOffered ? 'pass' : 'defect',
    summary: `completion refused before end with ${early.status} ${early.json?.detail?.code}; after a clock shift the browser's own "Record completion" button returned ${studentComplete ? studentComplete.map((b) => b.code).filter(Boolean).join(',') : 'no button rendered'}; tutor server leg recorded attendance (${done.status}, state=${done.json?.state}); DB state=${att[0]?.state} version=${att[0]?.version}; browser attendance banner code=${feState}; "Confirm attendance" offered=${confirmOffered}; review gate code=${reviewBanners.map((b) => b.code).filter(Boolean).join(',')}; server review refusal=${serverReview.status} ${serverReview.json?.detail?.code}`,
    observed: { earlyComplete: early, clockShift: shift, studentCompleteBanners: studentComplete, tutorComplete: done, attendanceBannersBeforeEnd: beforeEnd, attendanceBannersAfter: afterBanners, dockButtons: dock, reviewBanners, serverReviewRefusal: serverReview, dbAttendance: att },
    mechanism: { completion: 'server_leg', clockShift: 'clock_shift', note: 'the student surface may not record completion (RECORDER_ROLES = tutor, admin); the tutor call is an HTTP leg by this driver' },
    artifacts: arts,
  });
  STATE.s1Completed = true;
  saveState();
}

async function stageD4(page) {
  const sessionId = STATE.s1;
  if (!sessionId) return record({ id: 'I1-d4-attendance-confirm-review', stage: 'd4', matrix: 'I1', outcome: 'skip', summary: 'no session in state.json', artifacts: [] });
  const arts = [];
  await page.goto(`${WEB}/s-35?session=${sessionId}&view=attendance`, { waitUntil: 'domcontentloaded' });
  await page.waitForSelector('.tt-banner', { timeout: 15000 });
  arts.push(await shot(page, 'd13_s35_attendance_recorded'));
  const confirm = page.locator('button', { hasText: /^Confirm attendance$/ });
  if (!(await confirm.count())) {
    return record({ id: 'I1-d4-attendance-confirm-review', stage: 'd4', matrix: 'I1', outcome: 'defect', summary: 'no "Confirm attendance" control rendered for the server state; the attendance leg is unreachable from the student surface', observed: { banners: await banners(page) }, artifacts: arts });
  }
  await confirm.click();
  await page.waitForFunction(() => /You confirmed attendance/.test(document.body.textContent), { timeout: 20000 });
  arts.push(await shot(page, 'd14_s35_attendance_confirmed'));
  const attConfirmed = dbQuery('SELECT state, version, confirmed_at FROM session_attendance WHERE session_id = ?', [sessionId]);

  // review validation, then a real submit
  await page.locator('button', { hasText: /Leave a review/ }).click();
  await page.waitForFunction(() => location.search.includes('view=review'), { timeout: 10000 });
  await page.waitForSelector('div.tt-stars', { timeout: 10000 });
  arts.push(await shot(page, 'd15_s35_review_open'));
  await page.locator('label.tt-star').nth(4).click();
  await page.fill('#tt-review-body', 'too short');
  await page.waitForTimeout(300);
  arts.push(await shot(page, 'd16_s35_review_validation_short_body'));
  const validation = await page.evaluate(() => {
    const ta = document.querySelector('#tt-review-body');
    const submit = [...document.querySelectorAll('button')].find((b) => /Submit review/.test(b.textContent));
    return {
      ariaInvalid: ta?.getAttribute('aria-invalid'),
      counter: document.querySelector('#tt-review-count')?.textContent?.trim(),
      why: document.querySelector('#tt-review-why')?.textContent?.trim(),
      submitDisabled: submit ? submit.disabled : null,
    };
  });
  await page.fill('#tt-review-body', 'The mentor was well prepared and the session ran exactly as described.');
  await page.waitForTimeout(300);
  const submit = page.locator('button', { hasText: /Submit review/ });
  await submit.click();
  await page.waitForFunction(() => /your review was submitted/i.test(document.body.textContent), { timeout: 20000 });
  arts.push(await shot(page, 'd17_s35_review_submitted'));
  const reviews = dbQuery('SELECT v.id AS id, v.session_id AS session_id, v.rating AS rating, m.state AS moderation_state, v.published AS published, length(v.body) AS body_len FROM tutor_reviews v LEFT JOIN review_moderation m ON m.review_id = v.id WHERE v.session_id = ?', [sessionId]);

  // dispute path on S4 -> review blocked again
  let disputed = null;
  try {
    const slot4 = takeSlot('gt24h');
    const b4 = await bookInBrowser(page, slot4, null);
    STATE.s4 = b4.sessionId;
    saveState();
    await shiftSessionTo(b4.sessionId, -1.6);
    const s4 = await apiSession(b4.sessionId);
    await api('POST', `/api/v1/tutoring/sessions/${b4.sessionId}/complete`, { sub: tutorUserIdFor(s4.tutor_id), roles: ['tutor'] });
    await page.goto(`${WEB}/s-35?session=${b4.sessionId}&view=attendance`, { waitUntil: 'domcontentloaded' });
    await page.waitForSelector('.tt-banner', { timeout: 15000 });
    await page.locator('button', { hasText: /Dispute this/ }).click();
    await page.waitForSelector('div.tt-modal[role="dialog"]', { timeout: 8000 });
    await page.selectOption('#tt-reason', 'session_cut_short');
    arts.push(await shot(page, 'd18_s35_attendance_dispute_modal'));
    await page.locator('div.tt-modal button', { hasText: /Submit the dispute/ }).click();
    await page.waitForFunction(() => /dispute is open/i.test(document.body.textContent), { timeout: 20000 });
    arts.push(await shot(page, 'd19_s35_attendance_disputed'));
    await page.goto(`${WEB}/s-35?session=${b4.sessionId}&view=review`, { waitUntil: 'domcontentloaded' });
    await page.waitForSelector('.tt-banner', { timeout: 15000 });
    arts.push(await shot(page, 'd20_s35_review_blocked_while_disputed'));
    const blocked = await banners(page);
    const serverBlocked = await api('POST', `/api/v1/tutoring/sessions/${b4.sessionId}/review`, { sub: STUDENT, body: { rating: 4 } });
    disputed = { sessionId: b4.sessionId, banners: blocked, serverRefusal: serverBlocked, db: dbQuery('SELECT state, version FROM session_attendance WHERE session_id = ?', [b4.sessionId]) };
  } catch (err) {
    disputed = { error: String(err).slice(0, 400) };
  }

  const ok = attConfirmed[0]?.state === 'confirmed' && reviews.length === 1 && validation.submitDisabled === true && disputed?.serverRefusal?.json?.detail?.code === 'REVIEW_BLOCKED';
  record({
    id: 'I1-d4-attendance-confirm-review',
    stage: 'd4',
    matrix: 'I1',
    outcome: ok ? 'pass' : 'fail',
    summary: `attendance confirmed by a real click (DB state=${attConfirmed[0]?.state} v${attConfirmed[0]?.version}); review validation with a 9-char body: aria-invalid=${validation.ariaInvalid} submit disabled=${validation.submitDisabled} ("${validation.why}"); review submitted -> DB row rating=${reviews[0]?.rating} moderation=${reviews[0]?.moderation_state} published=${reviews[0]?.published}; dispute on a second session left review blocked (browser code ${disputed?.banners?.map((b) => b.code).filter(Boolean).join(',')}, server ${disputed?.serverRefusal?.status} ${disputed?.serverRefusal?.json?.detail?.code})`,
    observed: { attendance: attConfirmed, validation, reviews, disputed },
    artifacts: arts,
  });
}

async function stageNeg(page) {
  const arts = [];
  const findings = {};

  // 1. hold expiry (clock shift on the hold row, then a real click)
  try {
    const slot = takeSlot('gt24h');
    const holds = [];
    const onRes = async (res) => {
      if (res.url().includes('/booking-holds') && res.request().method() === 'POST') {
        try { holds.push(await res.json()); } catch { /* ignore */ }
      }
    };
    page.on('response', onRes);
    await page.goto(`${WEB}/s-33?slot=${slot.slot_id}&tutor=${slot.tutor_id}`, { waitUntil: 'domcontentloaded' });
    await page.waitForSelector('div.tt-hold[role="timer"]', { timeout: 15000 });
    for (let i = 0; i < 30 && holds.length === 0; i++) await page.waitForTimeout(100);
    page.off('response', onRes);
    const holdId = holds[0]?.id;
    const shift = fixtureCmd(['expire-hold', holdId]);
    await page.locator('button.tt-btn--jade', { hasText: /securely/ }).click();
    await page.waitForSelector(CODE_SEL, { timeout: 15000 });
    arts.push(await shot(page, 'n1_s33_hold_expired'));
    findings.holdExpiry = { holdId, clockShift: shift, banners: await banners(page) };
  } catch (err) {
    findings.holdExpiry = { error: String(err).slice(0, 300) };
  }

  // 2. slot conflict: a rival student holds the slot first (server leg), then the browser tries it
  try {
    const slot = takeSlot('gt24h');
    const rival = await api('POST', '/api/v1/tutoring/booking-holds', {
      sub: RIVAL,
      body: { slot_id: slot.slot_id, idempotency_key: `rival-${Date.now()}` },
    });
    await page.goto(`${WEB}/s-33?slot=${slot.slot_id}&tutor=${slot.tutor_id}`, { waitUntil: 'domcontentloaded' });
    await page.waitForSelector(CODE_SEL, { timeout: 15000 });
    arts.push(await shot(page, 'n2_s33_slot_conflict'));
    findings.slotConflict = { rivalHold: rival.status, banners: await banners(page) };
  } catch (err) {
    findings.slotConflict = { error: String(err).slice(0, 300) };
  }

  // 3. payment failure: the provider declines, then the student clicks confirm
  try {
    const slot = takeSlot('gt24h');
    const orderRefs = [];
    const onRes = async (res) => {
      if (res.url().includes('/payments/orders') && res.status() < 300) {
        try { orderRefs.push((await res.json()).provider_order_ref); } catch { /* ignore */ }
      }
    };
    page.on('response', onRes);
    await page.goto(`${WEB}/s-33?slot=${slot.slot_id}&tutor=${slot.tutor_id}`, { waitUntil: 'domcontentloaded' });
    await page.waitForSelector('div.tt-hold[role="timer"]', { timeout: 15000 });
    await page.locator('button.tt-btn--jade', { hasText: /securely/ }).click();
    await page.waitForFunction(() => /Order reference|Waiting for the provider/.test(document.body.textContent), { timeout: 15000 });
    for (let i = 0; i < 30 && orderRefs.length === 0; i++) await page.waitForTimeout(100);
    page.off('response', onRes);
    const declined = await payWebhook(orderRefs[0], { eventType: 'failed' });
    await page.locator('button.tt-btn--jade', { hasText: /Check payment and confirm/ }).click();
    await page.waitForSelector(CODE_SEL, { timeout: 15000 });
    arts.push(await shot(page, 'n3_s33_payment_unverified'));
    findings.paymentFailure = { orderRef: orderRefs[0], declineWebhook: declined, banners: await banners(page) };
  } catch (err) {
    findings.paymentFailure = { error: String(err).slice(0, 300) };
  }

  // 4. refused room entry: a session this student does not own
  try {
    const other = dbQuery("SELECT id FROM tutoring_sessions WHERE student_user_id != ? ORDER BY created_at DESC LIMIT 1", [STUDENT]);
    let target = other[0]?.id;
    if (!target) {
      // make one as the rival student, end to end, over HTTP (server leg)
      const slot = takeSlot('gt24h');
      const hold = await api('POST', '/api/v1/tutoring/booking-holds', { sub: RIVAL, body: { slot_id: slot.slot_id, idempotency_key: `rival-book-${Date.now()}` } });
      const order = await api('POST', '/api/v1/payments/orders', { sub: RIVAL, body: { hold_id: hold.json.id, amount_paise: FEE_PAISE, idempotency_key: `rival-order-${Date.now()}` } });
      const hook = await payWebhook(order.json.provider_order_ref);
      target = hook.json?.session_id;
    }
    await page.goto(`${WEB}/s-35?session=${target}&view=room`, { waitUntil: 'domcontentloaded' });
    await page.waitForSelector('div.tt-rbanner[role="alert"], .tt-banner--err', { timeout: 20000 });
    arts.push(await shot(page, 'n4_s35_room_entry_refused', { fullPage: false }));
    const refusal = await page.evaluate(() => {
      const rb = document.querySelector('div.tt-rbanner');
      return rb ? { title: rb.querySelector('.tt-banner__t')?.textContent?.trim(), detail: rb.querySelector('.tt-banner__d')?.textContent?.trim() } : null;
    });
    findings.roomEntryRefused = { targetSession: target, refusal, banners: await banners(page) };
  } catch (err) {
    findings.roomEntryRefused = { error: String(err).slice(0, 300) };
  }

  // 5. cancelled session cannot be joined
  try {
    if (STATE.s3) {
      await page.goto(`${WEB}/s-35?session=${STATE.s3}&view=room`, { waitUntil: 'domcontentloaded' });
      await page.waitForSelector('div.tt-rbanner[role="alert"], .tt-banner--err', { timeout: 20000 });
      arts.push(await shot(page, 'n5_s35_room_cancelled_session', { fullPage: false }));
      findings.roomCancelled = await page.evaluate(() => {
        const rb = document.querySelector('div.tt-rbanner');
        return rb ? { title: rb.querySelector('.tt-banner__t')?.textContent?.trim(), detail: rb.querySelector('.tt-banner__d')?.textContent?.trim() } : null;
      });
    }
  } catch (err) {
    findings.roomCancelled = { error: String(err).slice(0, 300) };
  }

  const codes = {
    holdExpiry: findings.holdExpiry?.banners?.map((b) => b.code).filter(Boolean).join(',') || null,
    slotConflict: findings.slotConflict?.banners?.map((b) => b.code).filter(Boolean).join(',') || null,
    paymentFailure: findings.paymentFailure?.banners?.map((b) => b.code).filter(Boolean).join(',') || null,
    roomEntryRefused: findings.roomEntryRefused?.refusal?.title || null,
    roomCancelled: findings.roomCancelled?.title || null,
  };
  const ok = codes.holdExpiry && codes.slotConflict && codes.paymentFailure && codes.roomEntryRefused;
  record({
    id: 'I1-neg-negative-states',
    stage: 'neg',
    matrix: 'I1',
    outcome: ok ? 'pass' : 'fail',
    summary: `negative states rendered in Chromium — hold expiry: ${codes.holdExpiry}; slot conflict: ${codes.slotConflict}; payment failure: ${codes.paymentFailure}; room entry for someone else's session: ${codes.roomEntryRefused}; room entry for a cancelled session: ${codes.roomCancelled}`,
    observed: findings,
    mechanism: { holdExpiry: 'clock_shift', rivalHold: 'server_leg', declinedPayment: 'server_leg' },
    artifacts: arts,
  });
}

async function stageRl(page) {
  const arts = [];
  let code = null;
  let hits = 0;
  for (let i = 0; i < 30 && !code; i++) {
    await page.goto(`${WEB}/s-31?q=rate${i}`, { waitUntil: 'domcontentloaded' });
    await page.waitForSelector('.tt-banner, article.tt-tut', { timeout: 15000 });
    hits += 1;
    const b = await banners(page);
    const found = b.map((x) => x.code).find((c) => c === 'rate_limit_exceeded');
    if (found) code = found;
  }
  arts.push(await shot(page, 'n6_s31_rate_limited'));
  const b = await banners(page);
  record({
    id: 'I1-neg-rate-limit',
    stage: 'rl',
    matrix: 'I1',
    outcome: code ? 'pass' : 'fail',
    summary: `rate limit rendered in the browser after ${hits} search navigations: code=${code}, banner "${b.find((x) => x.code === 'rate_limit_exceeded')?.title}" detail "${b.find((x) => x.code === 'rate_limit_exceeded')?.detail}"`,
    observed: { navigations: hits, banners: b, limitSetting: process.env.RATE_LIMIT_TUTOR_SEARCH_PER_MIN || null },
    artifacts: arts,
  });
}

/**
 * Defect capture. Runs the two S-35 list tabs side by side so the screenshots
 * themselves prove where the fault is: the same student, the same data, one tab
 * that sends a status the server does not have and one that sends none.
 * `--defect-label` distinguishes the before-fix and after-fix captures.
 */
async function stageBug(page) {
  const label = process.env.E2E_DEFECT_LABEL || 'before_fix';
  const arts = [];
  const responses = [];
  const onRes = async (res) => {
    if (res.url().includes('/api/v1/tutoring/sessions?')) {
      let body = null;
      try { body = (await res.text()).slice(0, 500); } catch { /* ignore */ }
      responses.push({ status: res.status(), url: res.url(), body });
    }
  };
  page.on('response', onRes);
  await page.goto(`${WEB}/s-35`, { waitUntil: 'domcontentloaded' });
  await page.waitForSelector('.tt-banner, article.tt-tut', { timeout: 15000 });
  await page.waitForTimeout(800);
  arts.push(await shot(page, `bug1_s35_list_upcoming_tab_${label}`));
  const upcoming = { banners: await banners(page), cards: await page.locator('article.tt-tut').count(), requests: [...responses] };

  responses.length = 0;
  await page.locator('div.tt-rails button.tt-rail', { hasText: 'Everything' }).click();
  await page.waitForTimeout(1200);
  arts.push(await shot(page, `bug2_s35_list_everything_tab_${label}`));
  const everything = { banners: await banners(page), cards: await page.locator('article.tt-tut').count(), requests: [...responses] };
  page.off('response', onRes);

  const broken = upcoming.cards === 0 && upcoming.requests.some((r) => r.status === 422);
  record({
    id: `DEFECT-s35-list-upcoming-tab-${label}`,
    stage: 'bug',
    matrix: 'I1',
    outcome: broken ? 'defect' : 'pass',
    summary: `S-35 "Upcoming" tab: ${upcoming.cards} session card(s), request(s) ${upcoming.requests.map((r) => `${r.status} ${r.url.split('?')[1]}`).join(' | ')}, banner "${upcoming.banners.map((b) => b.title).join(' / ')}"; "Everything" tab on the same data: ${everything.cards} card(s), request(s) ${everything.requests.map((r) => `${r.status} ${r.url.split('?')[1] || '(no filter)'}`).join(' | ')}`,
    observed: { label, upcoming, everything },
    artifacts: arts,
  });
}

/* ------------------------------------------------------------- J1 privacy */

const CANARIES = [
  { id: 'pan_visa_like', re: /\b4[0-9]{12}(?:[0-9]{3})?\b/g, what: 'a 13/16-digit Visa-shaped primary account number' },
  { id: 'pan_test_4242', re: /4242[ -]?4242[ -]?4242[ -]?4242/g, what: 'the canonical test PAN' },
  { id: 'cvv_field', re: /\b(cvv|cvc|card_?verification)\b\s*[:=]?\s*"?\d{3,4}"?/gi, what: 'a CVV/CVC value' },
  { id: 'otp_field', re: /\b(otp|one[_-]?time[_-]?password|2fa_code)\b\s*[:=]\s*"?\d{4,8}"?/gi, what: 'a payment OTP' },
  { id: 'raw_join_token', re: /join_[A-Za-z0-9_-]{20,}/g, what: 'a RAW server-issued join credential' },
  { id: 'payment_provider_secret', re: /legalsaathi-deterministic-payment-test-key/g, what: 'the payment provider signing key' },
  { id: 'video_provider_secret', re: /legalsaathi-deterministic-video-test-key/g, what: 'the video provider signing key' },
  { id: 'razorpay_secret', re: /rzp_(live|test)_[A-Za-z0-9]{6,}/g, what: 'a Razorpay key id' },
  { id: 'sdp_offer', re: /(^|["'\s>])v=0[\r\n]/g, what: 'an SDP session description' },
  { id: 'sdp_media_line', re: /\bm=(audio|video)\s+\d+/g, what: 'an SDP media line' },
  { id: 'ice_candidate', re: /\bcandidate:\d+\s+\d+\s+(udp|tcp)/gi, what: 'an ICE candidate' },
  { id: 'ice_srflx_relay', re: /\b(typ\s+(srflx|relay|host)|turn:|stun:)/gi, what: 'ICE/TURN/STUN plumbing' },
  { id: 'device_label_fake', re: /Fake (Audio|Video) (Input|Output)|fake_device_\d+|default - /g, what: 'a media DEVICE LABEL' },
  { id: 'device_label_field', re: /"(device_?label|deviceLabel|label)"\s*:\s*"[^"]{3,}"/g, what: 'a device label field' },
  { id: 'payment_token', re: /\btok_[A-Za-z0-9_]{3,60}\b/g, what: 'a provider payment token' },
];

function scanText(text, surface, source) {
  const hits = [];
  for (const c of CANARIES) {
    c.re.lastIndex = 0;
    const m = text.match(c.re);
    if (m && m.length) {
      hits.push({
        canary: c.id,
        what: c.what,
        occurrences: m.length,
        sample: String(m[0]).slice(0, 24).replace(/[0-9](?=[0-9]{3})/g, '*'),
        surface,
        source,
      });
    }
  }
  return hits;
}

async function stagePriv() {
  const surfaces = [];
  const hits = [];
  const scanDir = (dir, kind) => {
    if (!fs.existsSync(dir)) return;
    for (const f of fs.readdirSync(dir).sort()) {
      const p = path.join(dir, f);
      if (!fs.statSync(p).isFile()) continue;
      const text = fs.readFileSync(p, 'utf8');
      surfaces.push({ kind, file: path.relative(OUT, p), bytes: text.length });
      hits.push(...scanText(text, f, kind));
    }
  };
  scanDir(DIRS.dom, 'captured_dom');
  scanDir(DIRS.net, 'network_traffic');
  scanDir(DIRS.storage, 'storage_cookies_url');

  // URL bar: every URL the driver actually visited, from the storage dumps
  const urls = [];
  for (const f of fs.readdirSync(DIRS.storage)) {
    try {
      const s = JSON.parse(fs.readFileSync(path.join(DIRS.storage, f), 'utf8'));
      urls.push(s.url);
    } catch { /* ignore */ }
  }
  hits.push(...scanText(urls.join('\n'), 'url_bar', 'url_bar'));

  // storage/cookie emptiness is itself the assertion
  const storageState = [];
  for (const f of fs.readdirSync(DIRS.storage)) {
    const s = JSON.parse(fs.readFileSync(path.join(DIRS.storage, f), 'utf8'));
    storageState.push({
      capture: f.replace(/\.json$/, ''),
      localStorageKeys: Object.keys(s.localStorage || {}),
      sessionStorageKeys: Object.keys(s.sessionStorage || {}),
      cookie: s.cookie || '',
    });
  }

  let backendLog = { path: BACKEND_LOG, bytes: 0, hits: [] };
  if (BACKEND_LOG && fs.existsSync(BACKEND_LOG)) {
    const text = fs.readFileSync(BACKEND_LOG, 'utf8');
    backendLog = { path: BACKEND_LOG, bytes: text.length, hits: scanText(text, 'backend_uvicorn.log', 'backend_log') };
    surfaces.push({ kind: 'backend_log', file: path.relative(OUT, BACKEND_LOG), bytes: text.length });
  }
  hits.push(...backendLog.hits);

  const nonEmptyStorage = storageState.filter((s) => s.localStorageKeys.length || s.sessionStorageKeys.length || s.cookie);
  const report = {
    generatedAt: new Date().toISOString(),
    matrixRow: 'J1',
    method: 'every artifact this driver captured from the running browser (DOM snapshots, full request/response log including POST bodies and headers, localStorage/sessionStorage/cookies/URL per capture) plus the backend uvicorn log, scanned with the canary set below',
    canaries: CANARIES.map((c) => ({ id: c.id, pattern: String(c.re), what: c.what })),
    surfacesScanned: surfaces,
    surfaceCount: surfaces.length,
    totalBytesScanned: surfaces.reduce((a, s) => a + s.bytes, 0),
    findings: hits,
    findingCount: hits.length,
    storageState,
    storageAndCookiesEmptyEverywhere: nonEmptyStorage.length === 0,
    nonEmptyStorageCaptures: nonEmptyStorage,
    urlsVisited: [...new Set(urls)],
    verdict: hits.length === 0 && nonEmptyStorage.length === 0 ? 'clean' : 'findings_present',
  };
  fs.writeFileSync(path.join(OUT, 'privacy_scan.json'), JSON.stringify(report, null, 2));
  record({
    id: 'J1-privacy-canary-scan',
    stage: 'priv',
    matrix: 'J1',
    outcome: report.verdict === 'clean' ? 'pass' : 'fail',
    summary: `${CANARIES.length} canaries over ${surfaces.length} captured surfaces (${report.totalBytesScanned} bytes: DOM, network incl. POST bodies + headers, storage/cookies/URL, backend log) — ${hits.length} finding(s); localStorage/sessionStorage/cookies empty in all ${storageState.length} captures = ${report.storageAndCookiesEmptyEverywhere}`,
    observed: { findings: hits, storageCaptures: storageState.length, backendLogBytes: backendLog.bytes },
    artifacts: ['privacy_scan.json'],
  });
}

/* ==================================================================== main */

async function main() {
  if (STAGES.length === 1 && STAGES[0] === 'none') {
    console.log('stages=none — servers verified, no browser work requested');
    return 0;
  }
  const browser = await chromium.launch({
    args: [
      '--no-sandbox',
      '--disable-dev-shm-usage',
      '--use-fake-ui-for-media-stream',
      '--use-fake-device-for-media-stream',
      '--autoplay-policy=no-user-gesture-required',
    ],
  });
  STATE.browserVersion = browser.version();
  saveState();
  console.log(`chromium ${browser.version()} launched · stages=${STAGES.join(',')}`);

  const needsPage = STAGES.some((s) => s !== 'geo' && s !== 'priv');
  let ctx = null;
  let page = null;
  if (needsPage) {
    ctx = await browser.newContext({ viewport: MOBILE, colorScheme: 'light', permissions: ['camera', 'microphone'] });
    await ctx.tracing.start({ screenshots: true, snapshots: true, sources: false });
    page = await ctx.newPage();
    attachCapture(page);
  }

  let failures = 0;
  for (const stage of STAGES) {
    console.log(`\n--- stage ${stage}`);
    try {
      if (stage === 'a') await stageA(page);
      else if (stage === 'b') await stageB(page);
      else if (stage === 'c') await stageC(page);
      else if (stage === 'e') await stageE(page);
      else if (stage === 'geo') await stageGeo(browser);
      else if (stage === 'd1') await stageD1(page);
      else if (stage === 'd2') await stageD2(page);
      else if (stage === 'd3') await stageD3(page);
      else if (stage === 'd4') await stageD4(page);
      else if (stage === 'neg') await stageNeg(page);
      else if (stage === 'rl') await stageRl(page);
      else if (stage === 'bug') await stageBug(page);
      else if (stage === 'priv') await stagePriv();
      else console.log(`  (unknown stage ${stage}, skipped)`);
    } catch (err) {
      failures += 1;
      const name = `error_${stage}`;
      let artifacts = [];
      try {
        if (page) artifacts = [await shot(page, name)];
      } catch { /* ignore */ }
      record({
        id: `stage-${stage}-ERROR`,
        stage,
        outcome: 'fail',
        summary: `stage threw: ${String(err).slice(0, 400)}`,
        observed: { stack: String(err.stack || '').slice(0, 2000), banners: page ? await banners(page).catch(() => null) : null },
        artifacts,
      });
    }
  }

  if (ctx) {
    await ctx.tracing.stop({ path: path.join(DIRS.traces, `trace_${STAGES.join('-')}.zip`) });
    await ctx.close();
  }
  flushNet(STAGES.join('-'));
  await browser.close();

  const bad = RESULTS.filter((r) => r.outcome === 'fail').length;
  console.log(`\nresults: ${RESULTS.length} recorded · fail=${bad} · defect=${RESULTS.filter((r) => r.outcome === 'defect').length}`);
  return failures || bad ? 1 : 0;
}

main().then((rc) => process.exit(rc)).catch((err) => {
  console.error(err);
  process.exit(2);
});
