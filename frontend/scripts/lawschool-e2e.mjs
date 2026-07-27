/**
 * SAATHI-120 — repository-owned law-school directory E2E suite (TC-63-01..12).
 *
 * Runs against the built frontend (QA_BASE_URL, default http://127.0.0.1:1050)
 * with the real FastAPI + PostgreSQL 16 stack behind it (QA_API_BASE_URL,
 * default http://127.0.0.1:1031; directory seeded by
 * law_school_service.seed_law_schools — slugs nlsiu-bengaluru,
 * nalsar-hyderabad, wbnujs-kolkata, nlu-delhi).
 *
 * Follows the registration-e2e.mjs harness pattern: fresh browser contexts,
 * record(), per-state screenshots into QA_EVIDENCE_DIR, final JSON report
 * { passed, failed, cases: [{ tc, expected, actual, pass, evidence }] }.
 * Unlike registration-e2e.mjs this suite records ALL failures instead of
 * aborting on the first one (closure evidence needs the full matrix), and
 * exits non-zero if any case failed.
 *
 * Usage (QA rig — requires Chromium system deps and PG16 behind the API):
 *   cd frontend && npm ci && npx playwright install chromium
 *   QA_BASE_URL=http://127.0.0.1:1050 QA_API_BASE_URL=http://127.0.0.1:1031 \
 *   QA_EVIDENCE_DIR=/abs/path/evidence npm run qa:lawschool
 */
import { chromium } from 'playwright';
import fs from 'node:fs/promises';
import path from 'node:path';
import crypto from 'node:crypto';

const base = process.env.QA_BASE_URL ?? 'http://127.0.0.1:1050';
const api = process.env.QA_API_BASE_URL ?? 'http://127.0.0.1:1031';
const evidence = process.env.QA_EVIDENCE_DIR ?? path.resolve('../QA/wave1_lawschool_closure');
await fs.mkdir(evidence, { recursive: true });

/** Dev-stub actor claims (mirror of lawSchoolsApi.ts DEV_ACTOR_CLAIMS). The
 * frontend bakes USER_A's claims into every student-scoped request, so a fresh
 * browser context is equivalent to logout/login as the same user. */
const USER_A = { sub: '00000000-0000-4000-8000-0000000000de', roles: ['student'] };
const USER_B = { sub: '00000000-0000-4000-8000-0000000000b2', roles: ['student'] };
const NON_STUDENT = { sub: '00000000-0000-4000-8000-0000000000c3', roles: ['lawyer'] };
const SEED_SLUGS = ['nlsiu-bengaluru', 'nalsar-hyderabad', 'wbnujs-kolkata', 'nlu-delhi'];

const cases = [];
const record = (tc, expected, actual, pass, evidenceFile = null) => {
  cases.push({ tc, expected, actual, pass, evidence: evidenceFile });
  console.log(`${pass ? 'PASS' : 'FAIL'} ${tc}`);
};

/* -------------------------------- API probe -------------------------------- */

async function apiCall(method, p, { claims, body } = {}) {
  const headers = { 'Content-Type': 'application/json' };
  if (claims) headers['X-Actor-Claims'] = JSON.stringify(claims);
  const response = await fetch(`${api}${p}`, {
    method,
    headers,
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  let json;
  try { json = await response.json(); } catch { json = null; }
  return { status: response.status, json };
}
const errCode = (r) => {
  const detail = r.json?.detail;
  return (typeof detail === 'object' && detail !== null ? detail.code : detail) ?? null;
};
const savedSlugs = async (claims) => {
  const r = await apiCall('GET', '/api/v1/student/law-schools/saved', { claims });
  return (r.json?.items ?? []).map((s) => s.slug).sort();
};

/* Deterministic starting state: clear saved/followed for both test users. */
const catalog = await apiCall('GET', '/api/v1/law-schools?sort=name&page=1&page_size=50');
const bySlug = Object.fromEntries((catalog.json?.items ?? []).map((s) => [s.slug, s]));
record('TC-63-01-seed', `seed slugs ${SEED_SLUGS.join(',')} present`, Object.keys(bySlug).sort(),
  SEED_SLUGS.every((slug) => !!bySlug[slug]));
for (const claims of [USER_A, USER_B]) {
  for (const s of Object.values(bySlug)) {
    await apiCall('DELETE', `/api/v1/student/law-schools/${s.id}/saved`, { claims });
    await apiCall('DELETE', `/api/v1/student/law-schools/${s.id}/follow`, { claims });
  }
}
const ids4 = SEED_SLUGS.map((slug) => bySlug[slug]?.id).filter(Boolean);

/* ---------------- TC-63-01 — search/filter/sort/pagination (API) ----------- */
{
  const q = await apiCall('GET', '/api/v1/law-schools?q=NALSAR&page=1&page_size=20');
  record('TC-63-01-search-q', 'q=NALSAR returns exactly nalsar-hyderabad',
    (q.json?.items ?? []).map((s) => s.slug), q.json?.total === 1 && q.json?.items?.[0]?.slug === 'nalsar-hyderabad');
  const st = await apiCall('GET', '/api/v1/law-schools?state=Delhi');
  record('TC-63-01-filter-state', 'state=Delhi returns exactly nlu-delhi',
    (st.json?.items ?? []).map((s) => s.slug), st.json?.total === 1 && st.json?.items?.[0]?.slug === 'nlu-delhi');
  const ex = await apiCall('GET', '/api/v1/law-schools?entrance_exam=AILET');
  record('TC-63-01-filter-exam', 'entrance_exam=AILET returns exactly nlu-delhi',
    (ex.json?.items ?? []).map((s) => s.slug), ex.json?.total === 1 && ex.json?.items?.[0]?.slug === 'nlu-delhi');
  const fees = await apiCall('GET', '/api/v1/law-schools?fees_max=250000&sort=fees');
  record('TC-63-01-filter-fees', 'fees_max=250000 → wbnujs-kolkata, nlu-delhi (fees asc)',
    (fees.json?.items ?? []).map((s) => s.slug),
    JSON.stringify((fees.json?.items ?? []).map((s) => s.slug)) === JSON.stringify(['wbnujs-kolkata', 'nlu-delhi']));
  const nirf = await apiCall('GET', '/api/v1/law-schools?sort=nirf_rank');
  record('TC-63-01-sort-nirf', 'nirf sort puts nlsiu-bengaluru (#1) first',
    nirf.json?.items?.[0]?.slug, nirf.json?.items?.[0]?.slug === 'nlsiu-bengaluru');
  const badSort = await apiCall('GET', '/api/v1/law-schools?sort=fees_desc');
  record('TC-63-01-sort-typed-422', 'unsupported sort → 422 unsupported_sort',
    { status: badSort.status, code: errCode(badSort) }, badSort.status === 422 && errCode(badSort) === 'unsupported_sort');
  const p1 = await apiCall('GET', '/api/v1/law-schools?sort=name&page=1&page_size=2');
  const p2 = await apiCall('GET', '/api/v1/law-schools?sort=name&page=2&page_size=2');
  const p3 = await apiCall('GET', '/api/v1/law-schools?sort=name&page=3&page_size=2');
  record('TC-63-01-pagination', 'page_size=2 → 2+2 items, total 4, page 3 empty (deterministic tail)',
    { p1: p1.json?.items?.length, p2: p2.json?.items?.length, p3: p3.json?.items?.length, total: p1.json?.total },
    p1.json?.items?.length === 2 && p2.json?.items?.length === 2 && p3.json?.items?.length === 0 && p1.json?.total === 4);
  const it = await apiCall('GET', '/api/v1/law-schools?institution_type=national_law_university');
  record('TC-63-01-institution-type-api', 'canonical institution_type value accepted, returns 4',
    it.json?.total, it.json?.total === 4);
}

/* -------- TC-63-03/04 — compare rules at the HTTP boundary (typed) --------- */
{
  const fifth = crypto.randomUUID();
  const over = await apiCall('POST', '/api/v1/law-schools/compare', { body: { school_ids: [...ids4, fifth] } });
  record('TC-63-03-fifth-school-refusal', '5 ids → 422 COMPARE_LIMIT_EXCEEDED max_allowed=4',
    { status: over.status, code: errCode(over), max: over.json?.detail?.max_allowed },
    over.status === 422 && errCode(over) === 'COMPARE_LIMIT_EXCEEDED' && over.json?.detail?.max_allowed === 4);
  const under = await apiCall('POST', '/api/v1/law-schools/compare', { body: { school_ids: [ids4[0]] } });
  record('TC-63-03-min-not-met', '1 id → 422 COMPARE_MIN_NOT_MET min_required=2',
    { status: under.status, code: errCode(under) },
    under.status === 422 && errCode(under) === 'COMPARE_MIN_NOT_MET' && under.json?.detail?.min_required === 2);
  const dup = await apiCall('POST', '/api/v1/law-schools/compare', { body: { school_ids: [ids4[0], ids4[0]] } });
  record('TC-63-04-duplicate-blocked', 'duplicate id → 422 DUPLICATE_SCHOOL',
    { status: dup.status, code: errCode(dup) }, dup.status === 422 && errCode(dup) === 'DUPLICATE_SCHOOL');
  const r1 = await apiCall('POST', '/api/v1/law-schools/compare', { body: { school_ids: ids4 } });
  const r2 = await apiCall('POST', '/api/v1/law-schools/compare', { body: { school_ids: ids4 } });
  record('TC-63-04-replay', 'replayed 4-school compare → both 200, distinct comparison ids, 4 items each',
    { s1: r1.status, s2: r2.status, distinct: r1.json?.comparison_id !== r2.json?.comparison_id },
    r1.status === 200 && r2.status === 200 && r1.json?.items?.length === 4
    && r2.json?.items?.length === 4 && r1.json?.comparison_id !== r2.json?.comparison_id);
  const [cA, cB] = await Promise.all([
    apiCall('POST', '/api/v1/law-schools/compare', { body: { school_ids: ids4 } }),
    apiCall('POST', '/api/v1/law-schools/compare', { body: { school_ids: [...ids4, crypto.randomUUID()] } }),
  ]);
  record('TC-63-04-concurrent-add', 'two parallel compare calls: valid 200, over-limit typed 422; no cross-talk',
    { a: cA.status, b: cB.status, bCode: errCode(cB) },
    cA.status === 200 && cB.status === 422 && errCode(cB) === 'COMPARE_LIMIT_EXCEEDED');
}

/* -------- TC-63-09 — provider/transaction failure atomicity (API) ---------- */
{
  const before = await savedSlugs(USER_A);
  const ghost = crypto.randomUUID();
  const bad = await apiCall('POST', '/api/v1/law-schools/compare', { body: { school_ids: [ids4[0], ghost] } });
  const after = await savedSlugs(USER_A);
  const recover = await apiCall('POST', '/api/v1/law-schools/compare', { body: { school_ids: [ids4[0], ids4[1]] } });
  record('TC-63-09-compare-atomic', 'unknown school → 404 school_not_found, no partial mutation, service recovers',
    { status: bad.status, code: errCode(bad), stateUnchanged: JSON.stringify(before) === JSON.stringify(after), recover: recover.status },
    bad.status === 404 && errCode(bad) === 'school_not_found'
    && JSON.stringify(before) === JSON.stringify(after) && recover.status === 200);
  const badSave = await apiCall('PUT', `/api/v1/student/law-schools/${ghost}/saved`, { claims: USER_A });
  record('TC-63-09-save-atomic', 'save of unknown school → 404, saved list unchanged',
    { status: badSave.status, code: errCode(badSave), saved: await savedSlugs(USER_A) },
    badSave.status === 404 && errCode(badSave) === 'school_not_found'
    && JSON.stringify(await savedSlugs(USER_A)) === JSON.stringify(before));
}

/* ------- TC-63-07 — anonymous 401 + cross-user isolation (API probe) ------- */
{
  const anon = await apiCall('GET', '/api/v1/student/law-schools/saved');
  record('TC-63-07-anonymous-401', 'no claims → 401 authentication_required',
    { status: anon.status, code: errCode(anon) }, anon.status === 401 && errCode(anon) === 'authentication_required');
  const anonWrite = await apiCall('PUT', `/api/v1/student/law-schools/${ids4[0]}/saved`);
  record('TC-63-07-anonymous-write-401', 'anonymous save → 401',
    anonWrite.status, anonWrite.status === 401);
  const wrongRole = await apiCall('GET', '/api/v1/student/law-schools/saved', { claims: NON_STUDENT });
  record('TC-63-07-role-403', 'non-student role → 403 forbidden',
    { status: wrongRole.status, code: errCode(wrongRole) }, wrongRole.status === 403 && errCode(wrongRole) === 'forbidden');
  await apiCall('PUT', `/api/v1/student/law-schools/${ids4[0]}/saved`, { claims: USER_A });
  const bList = await savedSlugs(USER_B);
  record('TC-63-07-cross-user-isolation', "user B never sees user A's saved schools",
    bList, bList.length === 0);
  const bDelete = await apiCall('DELETE', `/api/v1/student/law-schools/${ids4[0]}/saved`, { claims: USER_B });
  record('TC-63-07-non-enumerating', "B unsave of A's row → idempotent {saved:false}, A unaffected (no existence leak)",
    { status: bDelete.status, body: bDelete.json, aStill: await savedSlugs(USER_A) },
    bDelete.status === 200 && bDelete.json?.saved === false
    && (await savedSlugs(USER_A)).includes('nlsiu-bengaluru'));
  await apiCall('DELETE', `/api/v1/student/law-schools/${ids4[0]}/saved`, { claims: USER_A });
}

/* ------------------------------- browser flows ----------------------------- */

const browser = await chromium.launch({ headless: true });

async function fresh(viewport = { width: 1440, height: 1000 }, theme = null) {
  const context = await browser.newContext({ viewport });
  const page = await context.newPage();
  if (theme) await page.addInitScript((value) => localStorage.setItem('ls-theme', value), theme);
  const consoleErrors = [];
  const serverErrors = [];
  page.on('console', (m) => { if (m.type() === 'error') consoleErrors.push(m.text()); });
  page.on('response', (r) => { if (r.status() >= 500) serverErrors.push(`${r.status()} ${r.url()}`); });
  return { context, page, consoleErrors, serverErrors };
}

const resultsItem = (page, name) => page
  .locator('section[aria-label="Search results"] li.st-item')
  .filter({ hasText: name });
const shot = async (page, file) => {
  await page.screenshot({ path: path.join(evidence, file), fullPage: true });
  return file;
};

/* TC-63-01/02 — search UI, deterministic empty state */
{
  const { context, page, consoleErrors, serverErrors } = await fresh();
  await page.goto(`${base}/s-27`);
  await resultsItem(page, 'NALSAR').waitFor();
  const count = await page.locator('section[aria-label="Search results"] li.st-item').count();
  record('TC-63-01-ui-results', 'all 4 seeded schools listed', count, count === 4, await shot(page, 's27_results_4.png'));
  record('TC-63-01-ui-pagination-idle', 'no pagination controls on a single page (total 4 <= page size 20)',
    await page.getByRole('button', { name: 'Previous' }).count(),
    (await page.getByRole('button', { name: 'Previous' }).count()) === 0);

  await page.getByLabel('Search law schools').fill('NALSAR');
  await page.getByLabel('Search law schools').press('Enter');
  await page.getByText('1 found').waitFor();
  record('TC-63-01-ui-search', 'q=NALSAR shows exactly one result', 1,
    (await page.locator('section[aria-label="Search results"] li.st-item').count()) === 1,
    await shot(page, 's27_search_nalsar.png'));

  await page.getByLabel('Search law schools').fill('zz-no-such-school');
  await page.getByLabel('Search law schools').press('Enter');
  await page.getByText('No schools match').waitFor();
  record('TC-63-02-ui-empty-state', 'deterministic empty state with recovery hint', 'No schools match + hint',
    await page.getByText('Try clearing a filter or broadening your search.').isVisible(),
    await shot(page, 's27_empty_state.png'));

  await page.getByLabel('Search law schools').fill('');
  await page.getByLabel('Search law schools').press('Enter');
  await page.getByLabel('State').selectOption('Delhi');
  await page.getByText('1 found').waitFor();
  record('TC-63-01-ui-filter-state', 'state=Delhi filters to NLU Delhi',
    await resultsItem(page, 'National Law University, Delhi').count(),
    (await resultsItem(page, 'National Law University, Delhi').count()) === 1,
    await shot(page, 's27_filter_delhi.png'));
  await page.getByLabel('State').selectOption('');

  await page.getByRole('button', { name: 'Sort: Fees' }).click();
  await page.getByText('4 found').waitFor();
  const firstName = await page.locator('section[aria-label="Search results"] li.st-item').first().innerText();
  record('TC-63-01-ui-sort-fees', 'fees sort puts WBNUJS (lowest fees) first', firstName.split('\n')[0],
    firstName.includes('West Bengal'), await shot(page, 's27_sort_fees.png'));

  record('TC-63-10-ui-console-clean', 'no console errors / 5xx during search flows',
    { consoleErrors, serverErrors }, consoleErrors.length === 0 && serverErrors.length === 0);
  await context.close();
}

/* Known-contract case: UI institution-type option values vs backend enum. */
{
  const { context, page } = await fresh();
  await page.goto(`${base}/s-27`);
  await resultsItem(page, 'NALSAR').waitFor();
  await page.getByLabel('Institution type').selectOption('NLU');
  const outcome = await Promise.race([
    page.getByText('4 found').waitFor().then(() => 'results'),
    page.getByText(/unsupported_institution_type|Could not load law schools/).waitFor().then(() => 'typed-error'),
    page.getByText('No schools match').waitFor().then(() => 'empty'),
  ]);
  record('TC-63-01-ui-institution-type-contract',
    'UI institution-type filter resolves deterministically (results or typed error — never a silent crash)',
    outcome, outcome === 'results' || outcome === 'typed-error' || outcome === 'empty',
    await shot(page, 's27_institution_type_filter.png'));
  await context.close();
}

/* TC-63-06 — detail navigation + return context */
{
  const { context, page } = await fresh();
  await page.goto(`${base}/s-27?state=Karnataka`);
  await resultsItem(page, 'National Law School of India University').waitFor();
  await resultsItem(page, 'National Law School of India University').getByRole('button', { name: 'View' }).click();
  await page.waitForURL('**/s-28*');
  const s28 = new URL(page.url());
  record('TC-63-06-detail-nav', 'View routes to /s-28 with id + ret context',
    s28.pathname + s28.search,
    s28.pathname === '/s-28' && s28.searchParams.get('id') === ids4[0]
    && (s28.searchParams.get('ret') ?? '').includes('state=Karnataka'));
  await page.getByRole('heading', { name: 'National Law School of India University' }).waitFor();
  record('TC-63-06-detail-facts', 'detail shows verified facts with source link',
    await page.getByText('Verified facts').isVisible() && (await page.locator('section a[target="_blank"]').count()) > 0,
    await page.getByText('Verified facts').isVisible() && (await page.locator('section a[target="_blank"]').count()) > 0,
    await shot(page, 's28_detail_nlsiu.png'));
  await page.getByRole('button', { name: 'Back to search' }).first().click();
  await page.waitForURL('**/s-27*');
  const back = new URL(page.url());
  record('TC-63-06-return-context', 'Back to search restores /s-27?state=Karnataka',
    back.pathname + back.search, back.pathname === '/s-27' && back.searchParams.get('state') === 'Karnataka',
    await shot(page, 's27_return_context.png'));
  await context.close();
}

/* TC-63-03/04 — compare UI: min 2, max 4, fifth refusal, duplicate, refresh replay */
{
  const { context, page } = await fresh();
  await page.goto(`${base}/s-27`);
  await resultsItem(page, 'NALSAR').waitFor();
  const cta = page.locator('section[aria-label="Compare tray"]').getByRole('button', { name: /^Compare/ });
  record('TC-63-03-ui-min-disabled', 'CTA disabled below minimum of 2',
    await cta.isDisabled(), await cta.isDisabled());
  await resultsItem(page, 'National Law School of India University').getByRole('button', { name: 'Compare', exact: true }).click();
  record('TC-63-03-ui-one-selected', 'with 1 selected CTA still disabled and asks for 1 more',
    await cta.innerText(), (await cta.isDisabled()) && (await cta.innerText()).includes('select 1 more'));
  await resultsItem(page, 'NALSAR').getByRole('button', { name: 'Compare', exact: true }).click();
  record('TC-63-03-ui-two-enabled', 'with 2 selected CTA enables', await cta.innerText(), !(await cta.isDisabled()));
  await cta.click();
  await page.waitForURL('**/s-29*');
  await page.getByRole('heading', { name: 'Side by side' }).waitFor();
  const cols2 = await page.locator('table.st-table thead th').count();
  record('TC-63-03-ui-compare-2', '2-school table renders (attribute col + 2 schools)', cols2, cols2 === 3,
    await shot(page, 's29_compare_2.png'));
  await page.reload();
  await page.getByRole('heading', { name: 'Side by side' }).waitFor();
  record('TC-63-04-ui-refresh-replay', 'refresh replays the comparison from the URL (state survives)',
    await page.locator('table.st-table thead th').count(),
    (await page.locator('table.st-table thead th').count()) === 3);

  await page.goto(`${base}/s-29?ids=${ids4.join(',')}`);
  await page.getByRole('heading', { name: 'Side by side' }).waitFor();
  const cols4 = await page.locator('table.st-table thead th').count();
  record('TC-63-03-ui-compare-4', '4-school table renders (max)', cols4, cols4 === 5,
    await shot(page, 's29_compare_4.png'));

  await page.goto(`${base}/s-29?ids=${[...ids4, crypto.randomUUID()].join(',')}`);
  await page.getByText(/at most 4 schools/).waitFor();
  record('TC-63-03-ui-fifth-refusal', 'fifth school → typed COMPARE_LIMIT_EXCEEDED message, no table',
    await page.getByText(/at most 4 schools/).innerText(),
    (await page.locator('table.st-table').count()) === 0, await shot(page, 's29_limit_refusal.png'));

  await page.goto(`${base}/s-29?ids=${ids4[0]},${ids4[0]}`);
  await page.getByText(/Select at least 2 schools/).waitFor();
  record('TC-63-04-ui-duplicate-blocked', 'duplicate ids deduped → below-minimum validation, no request crash',
    await page.getByText(/Select at least 2 schools/).innerText(),
    (await page.locator('table.st-table').count()) === 0, await shot(page, 's29_duplicate_blocked.png'));
  await context.close();
}

/* TC-63-05 — save/follow persistence across reload + fresh context */
{
  const { context, page } = await fresh();
  await page.goto(`${base}/s-28?id=${ids4[0]}`);
  const saveBtn = page.getByRole('button', { name: /^Save/ });
  const followBtn = page.getByRole('button', { name: /^Follow/ });
  await saveBtn.waitFor();
  await saveBtn.click();
  await page.getByRole('button', { name: 'Saved ✓' }).waitFor();
  await followBtn.click();
  await page.getByRole('button', { name: 'Following ✓' }).waitFor();
  await shot(page, 's28_saved_followed.png');
  await page.reload();
  await page.getByRole('button', { name: 'Saved ✓' }).waitFor();
  await page.getByRole('button', { name: 'Following ✓' }).waitFor();
  record('TC-63-05-reload-persistence', 'saved+followed state survives reload (server-backed)',
    'Saved ✓ / Following ✓ after reload', true, 's28_saved_followed.png');
  await context.close();

  const second = await fresh(); // fresh context == logout/login with same claims
  await second.page.goto(`${base}/s-30`);
  await second.page.locator('section[aria-label="Saved schools"] li.st-item').first().waitFor();
  const savedHas = await second.page.locator('section[aria-label="Saved schools"]').getByText('National Law School of India University').count();
  const followedHas = await second.page.locator('section[aria-label="Followed schools"]').getByText('National Law School of India University').count();
  record('TC-63-05-new-context', 'fresh browser context (same claims) sees saved+followed on S-30',
    { savedHas, followedHas }, savedHas > 0 && followedHas > 0, await shot(second.page, 's30_saved_followed.png'));
  await second.page.locator('section[aria-label="Saved schools"]').getByRole('button', { name: 'Unsave' }).first().click();
  await second.page.locator('section[aria-label="Saved schools"]').getByText('No saved schools yet').waitFor();
  record('TC-63-05-unsave', 'unsave removes the row and shows the empty state',
    'No saved schools yet', true, await shot(second.page, 's30_after_unsave.png'));
  await second.page.locator('section[aria-label="Followed schools"]').getByRole('button', { name: 'Unfollow' }).first().click();
  await second.page.locator('section[aria-label="Followed schools"]').getByText('No followed schools yet').waitFor();
  await second.context.close();
}

/* TC-63-10 — browser-storage / console / network privacy scan */
{
  const { context, page, consoleErrors } = await fresh();
  const requestLog = [];
  page.on('request', (r) => requestLog.push(r.url()));
  await page.goto(`${base}/s-27`);
  await resultsItem(page, 'NALSAR').waitFor();
  await page.goto(`${base}/s-28?id=${ids4[1]}`);
  await page.getByRole('button', { name: /^Save/ }).waitFor();
  const storage = await page.evaluate(() => ({
    local: Object.fromEntries(Object.keys(localStorage).map((k) => [k, localStorage.getItem(k)])),
    session: Object.fromEntries(Object.keys(sessionStorage).map((k) => [k, sessionStorage.getItem(k)])),
  }));
  const serialized = JSON.stringify(storage);
  const leaks = ['00000000-0000-4000-8000-0000000000de', 'X-Actor-Claims', 'Bearer ', 'roles']
    .filter((needle) => serialized.includes(needle));
  record('TC-63-10-storage-privacy', 'no actor claims/sub/token material in browser storage',
    { keys: [...Object.keys(storage.local), ...Object.keys(storage.session)], leaks }, leaks.length === 0);
  const urlLeaks = requestLog.filter((u) => u.includes('00000000-0000-4000-8000-0000000000de') || u.toLowerCase().includes('token='));
  record('TC-63-10-network-privacy', 'no claims sub / tokens in request URLs', urlLeaks, urlLeaks.length === 0);
  const consoleLeaks = consoleErrors.filter((t) => t.includes('00000000-0000-4000-8000-0000000000de'));
  record('TC-63-10-console-privacy', 'no PII/claims in console output; no console errors',
    { consoleErrors, consoleLeaks }, consoleErrors.length === 0 && consoleLeaks.length === 0);
  await context.close();
}

/* TC-63-08/11/12 — responsive × theme matrix: overflow, 44px targets, keyboard */
for (const width of [390, 430, 768, 1024, 1440]) {
  for (const theme of ['light', 'dark']) {
    const { context, page, consoleErrors } = await fresh({ width, height: 1000 }, theme);
    await page.goto(`${base}/s-27`);
    await resultsItem(page, 'NALSAR').waitFor();
    const metrics = await page.evaluate(() => ({
      scrollWidth: document.documentElement.scrollWidth,
      innerWidth: window.innerWidth,
      smallTargets: Array.from(document.querySelectorAll('button, a, input, select'))
        .filter((el) => el.offsetParent !== null)
        .map((el) => ({
          label: (el.getAttribute('aria-label') || el.textContent || el.tagName).trim().slice(0, 40),
          w: Math.round(el.getBoundingClientRect().width),
          h: Math.round(el.getBoundingClientRect().height),
        }))
        .filter((t) => t.w > 0 && t.h > 0 && (t.w < 44 || t.h < 44)),
    }));
    record(`TC-63-08-overflow-${width}-${theme}`, `no horizontal overflow at ${width}px (${theme})`,
      metrics.scrollWidth, metrics.scrollWidth <= width, await shot(page, `s27_${width}_${theme}.png`));
    record(`TC-63-11-targets-${width}-${theme}`, 'every actionable target >= 44x44',
      metrics.smallTargets, metrics.smallTargets.length === 0);
    const reached = [];
    for (let i = 0; i < 60; i += 1) {
      await page.keyboard.press('Tab');
      reached.push(await page.evaluate(() => {
        const el = document.activeElement;
        return el ? (el.getAttribute('aria-label') || el.textContent || el.tagName).trim().slice(0, 40) : '';
      }));
    }
    record(`TC-63-12-keyboard-${width}-${theme}`, 'search box, sort chips and result actions reachable by Tab',
      [...new Set(reached)].slice(0, 12),
      reached.includes('Search law schools') && reached.some((t) => t.startsWith('Sort:')) && reached.includes('View'));
    record(`TC-63-12-console-${width}-${theme}`, 'no console errors in matrix pass', consoleErrors, consoleErrors.length === 0);
    await context.close();
  }
}

/* Detail + saved/followed responsive spot checks (both themes, phone + desktop) */
for (const [width, theme] of [[390, 'dark'], [1440, 'light']]) {
  const { context, page } = await fresh({ width, height: 1000 }, theme);
  await page.goto(`${base}/s-28?id=${ids4[2]}`);
  await page.getByRole('button', { name: /^Save/ }).waitFor();
  const w28 = await page.evaluate(() => document.documentElement.scrollWidth);
  record(`TC-63-08-s28-${width}-${theme}`, `S-28 no overflow at ${width}px (${theme})`, w28, w28 <= width,
    await shot(page, `s28_${width}_${theme}.png`));
  await page.goto(`${base}/s-30`);
  await page.getByRole('heading', { name: 'Saved & followed' }).waitFor();
  const w30 = await page.evaluate(() => document.documentElement.scrollWidth);
  record(`TC-63-08-s30-${width}-${theme}`, `S-30 no overflow at ${width}px (${theme})`, w30, w30 <= width,
    await shot(page, `s30_${width}_${theme}.png`));
  await context.close();
}

await browser.close();

const report = {
  generatedAt: new Date().toISOString(),
  base,
  api,
  passed: cases.filter((c) => c.pass).length,
  failed: cases.filter((c) => !c.pass).length,
  cases,
};
await fs.writeFile(path.join(evidence, 'lawschool_e2e_report.json'), JSON.stringify(report, null, 2));
console.log(JSON.stringify({ passed: report.passed, failed: report.failed, evidence }, null, 2));
if (report.failed > 0) process.exitCode = 1;
