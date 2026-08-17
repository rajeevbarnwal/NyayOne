/**
 * Wave 5 S-90–S-93 deterministic UI-contract harness.
 * This intentionally mocks the HTTP boundary and proves only frontend rendering,
 * accessibility, responsiveness and browser-secret handling. It is NOT API,
 * PostgreSQL, migration, concurrency or end-to-end release evidence; the real
 * target-runtime gate must run separately against the migrated backend.
 */
import { mkdir, writeFile } from 'node:fs/promises';
import path from 'node:path';
import { chromium } from 'playwright';
import axe from 'axe-core';

const WEB = (process.env.E2E_WEB_URL ?? 'http://127.0.0.1:1130').replace(/\/$/, '');
const OUT = path.resolve(process.env.E2E_OUTPUT_DIR ?? 'test-results/wave5-calendar-e2e');
const WIDTHS = [390, 430, 768, 1024, 1440];
const THEMES = ['light', 'dark'];
const STATES = [
  ['s90-month', '/s-90'],
  ['s91-add', '/s-91'],
  ['s92-conflicts', '/s-92'],
  ['s93-reminders', '/s-93?tab=reminders'],
  ['s93-export', '/s-93?tab=export'],
];
const SECRET = 'wave5-private-feed-secret-canary';
const report = { evidenceClass: 'deterministic-mocked-ui-only', releaseGate: false, startedAt: new Date().toISOString(), web: WEB, rows: [], failures: [] };

function record(name, expected, actual, pass) {
  const row = { name, expected, actual, pass: Boolean(pass) };
  report.rows.push(row);
  if (!row.pass) report.failures.push(`${name}: expected ${expected}; actual ${actual}`);
}

const event = (id, title, sourceType, startHour, sourceUrl) => ({
  id, source_type: sourceType, source_id: `${sourceType}-${id}`, title,
  starts_at: `2026-08-03T${String(startHour).padStart(2, '0')}:00:00Z`,
  ends_at: `2026-08-03T${String(startHour + 1).padStart(2, '0')}:00:00Z`,
  timezone: 'Asia/Kolkata', status: 'scheduled', privacy_classification: 'personal',
  event_kind: sourceType === 'reminder' ? 'reminder' : null,
  source_url: sourceUrl, version: 1,
  created_at: '2026-08-02T00:00:00Z', updated_at: '2026-08-02T00:00:00Z',
});
const events = [
  event('00000000-0000-4000-8000-000000000901', 'CLAT mock test', 'exam', 10, '/s-55'),
  event('00000000-0000-4000-8000-000000000902', 'Tutoring session', 'tutoring', 10, '/s-35'),
];
const preview = (item) => ({
  id: item.id, source_type: item.source_type, title: item.title, starts_at: item.starts_at,
  ends_at: item.ends_at, timezone: item.timezone, status: item.status, source_url: item.source_url,
});

function json(route, body, status = 200) {
  return route.fulfill({ status, contentType: 'application/json', body: JSON.stringify(body) });
}

async function installApi(page) {
  await page.route('**/api/v1/**', async (route) => {
    const request = route.request();
    const url = new URL(request.url());
    const pathname = url.pathname;
    if (pathname.endsWith('/auth/student/session')) return json(route, {
      authenticated: true,
      actor: { sub: '00000000-0000-4000-8000-0000000000de', roles: ['student'], student_profile_id: 'profile-1', student_verification: 'verified', is_minor: false, consent_state: [] },
    });
    if (pathname.endsWith('/calendar/view-preferences')) return json(route, {
      view_mode: 'month', source_types: ['exam', 'tutoring'], from_date: null, to_date: null,
      timezone: 'Asia/Kolkata', version: 1, updated_at: '2026-08-02T00:00:00Z',
    });
    if (pathname.endsWith('/calendar/events') && request.method() === 'GET') return json(route, { items: events, total: events.length, failed_sources: [] });
    if (pathname.endsWith('/calendar/conflicts/check')) return json(route, {
      items: [{ id: '00000000-0000-4000-8000-000000000920', left_event_id: events[0].id, right_event_id: events[1].id,
        left: preview(events[0]), right: preview(events[1]), status: 'active', detected_at: '2026-08-02T00:00:00Z', version: 1 }], total: 1,
    });
    if (/\/calendar\/conflicts\/[^/]+$/.test(pathname) && request.method() === 'PATCH') {
      const input = request.postDataJSON();
      return json(route, { id: pathname.split('/').pop(), left_event_id: events[0].id, right_event_id: events[1].id,
        left: preview(events[0]), right: preview(events[1]), status: input.status, detected_at: '2026-08-02T00:00:00Z', version: 2 });
    }
    if (pathname.endsWith('/calendar/reminder-preferences')) return json(route, request.method() === 'GET' ? { items: [{
      id: '00000000-0000-4000-8000-000000000930', source_type: 'exam', channel: 'in_app', enabled: true,
      lead_minutes: 30, quiet_start_min: 1320, quiet_end_min: 420, timezone: 'Asia/Kolkata', version: 1, updated_at: '2026-08-02T00:00:00Z',
    }] } : { id: '00000000-0000-4000-8000-000000000930', source_type: 'exam', channel: 'in_app', enabled: true,
      lead_minutes: 30, quiet_start_min: 1320, quiet_end_min: 420, timezone: 'Asia/Kolkata', version: 2, updated_at: '2026-08-02T00:00:00Z' });
    if (pathname.endsWith('/calendar/exports') && request.method() === 'GET') return json(route, { items: [{
      id: '00000000-0000-4000-8000-000000000940', status: 'expired', timezone: 'Asia/Kolkata',
      expires_at: '2026-08-01T00:00:00Z', revoked_at: null, feed_url: null, token_returned_once: false, version: 1,
    }], total: 1 });
    if (pathname.endsWith('/calendar/exports') && request.method() === 'POST') return json(route, {
      id: '00000000-0000-4000-8000-000000000941', status: 'active', timezone: 'Asia/Kolkata',
      expires_at: '2026-08-09T00:00:00Z', revoked_at: null,
      feed_url: `https://calendar.local/api/v1/public/calendar-feeds/${SECRET}.ics`, token_returned_once: true, version: 1,
    }, 201);
    return json(route, { detail: { code: 'unexpected_mock_route', message: `${request.method()} ${pathname}` } }, 500);
  });
}

async function scan(page, state, width, theme) {
  const prefix = `${state}-${width}-${theme}`;
  const ready = page.locator('[data-wave5-ready]');
  await ready.waitFor({ state: 'visible' });
  await page.waitForFunction(() => document.querySelector('[data-wave5-ready]')?.getAttribute('data-wave5-ready') !== 'loading');
  await page.evaluate(async () => {
    if (document.fonts) await document.fonts.ready;
    await new Promise((resolve) => requestAnimationFrame(() => requestAnimationFrame(resolve)));
  });
  const readyValue = await ready.getAttribute('data-wave5-ready');
  record(`${prefix} explicit readiness`, 'ready', readyValue, readyValue === 'ready');
  const geometry = await page.locator('main.calv').evaluate((node) => ({
    scrollWidth: node.scrollWidth, clientWidth: node.clientWidth,
    small: [...node.querySelectorAll('button:not([disabled]), a[href], input:not([type=checkbox]):not([disabled]), select:not([disabled])')]
      .filter((element) => {
        const rect = element.getBoundingClientRect();
        return rect.width > 0 && rect.height > 0 && (rect.width < 44 || rect.height < 44);
      }).map((element) => ({ label: element.getAttribute('aria-label') || element.textContent?.trim() || element.tagName, rect: element.getBoundingClientRect().toJSON() })),
  }));
  record(`${prefix} horizontal overflow`, '0 px', `${geometry.scrollWidth - geometry.clientWidth} px`, geometry.scrollWidth <= geometry.clientWidth + 1);
  record(`${prefix} interactive targets`, 'all at least 44px', JSON.stringify(geometry.small), geometry.small.length === 0);
  const axeResult = await page.evaluate(axe.source).then(() => page.evaluate(async () => globalThis.axe.run('main.calv', { runOnly: { type: 'tag', values: ['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa', 'wcag22aa'] } })));
  record(`${prefix} axe A/AA`, '0 violations', JSON.stringify(axeResult.violations.map((item) => ({ id: item.id, targets: item.nodes.map((node) => node.target) }))), axeResult.violations.length === 0);
  await page.screenshot({ path: path.join(OUT, `${prefix}.png`), fullPage: true });
}

await mkdir(OUT, { recursive: true });
console.warn('UI HARNESS ONLY: mocked API responses are not target-runtime release evidence.');
const browser = await chromium.launch({ headless: true });
try {
  for (const [state, route] of STATES) for (const width of WIDTHS) for (const theme of THEMES) {
    const context = await browser.newContext({ viewport: { width, height: width <= 430 ? 844 : 900 }, colorScheme: theme, permissions: ['clipboard-read', 'clipboard-write'] });
    const page = await context.newPage();
    const consoleErrors = [];
    const pageErrors = [];
    const failedRequests = [];
    page.on('console', (message) => { if (message.type() === 'error') consoleErrors.push(message.text()); });
    page.on('pageerror', (error) => pageErrors.push(String(error)));
    page.on('requestfailed', (request) => failedRequests.push(`${request.method()} ${request.url()}: ${request.failure()?.errorText}`));
    await installApi(page);
    await page.goto(`${WEB}${route}`, { waitUntil: 'domcontentloaded' });
    await scan(page, state, width, theme);
    record(`${state}-${width}-${theme} runtime`, '0 console/page/network errors', JSON.stringify({ consoleErrors, pageErrors, failedRequests }), consoleErrors.length + pageErrors.length + failedRequests.length === 0);
    await context.close();
  }

  const context = await browser.newContext({ viewport: { width: 430, height: 844 }, permissions: ['clipboard-read', 'clipboard-write'] });
  const page = await context.newPage();
  await installApi(page);
  await page.goto(`${WEB}/s-93?tab=export`, { waitUntil: 'domcontentloaded' });
  await page.waitForSelector('[data-wave5-ready="ready"]');
  await page.getByRole('button', { name: 'Create private feed' }).click();
  await page.getByText('One-time secret ready').waitFor();
  const bodyBeforeCopy = await page.locator('body').innerText();
  const storesBeforeCopy = await page.evaluate(() => JSON.stringify({ local: { ...localStorage }, session: { ...sessionStorage } }));
  record('export secret never rendered', 'secret absent', bodyBeforeCopy.includes(SECRET) ? 'present' : 'absent', !bodyBeforeCopy.includes(SECRET));
  record('export secret never stored', 'secret absent', storesBeforeCopy.includes(SECRET) ? 'present' : 'absent', !storesBeforeCopy.includes(SECRET));
  await page.getByRole('button', { name: 'Copy private feed URL' }).click();
  await page.getByText('one-time URL has been cleared', { exact: false }).waitFor();
  record('export one-time control clears after copy', 'control absent', String(await page.getByRole('button', { name: 'Copy private feed URL' }).count()), await page.getByRole('button', { name: 'Copy private feed URL' }).count() === 0);
  await context.close();
} finally {
  await browser.close();
}

report.finishedAt = new Date().toISOString();
report.total = report.rows.length;
report.passed = report.rows.filter((row) => row.pass).length;
report.failed = report.failures.length;
await writeFile(path.join(OUT, 'wave5-calendar-e2e.json'), JSON.stringify(report, null, 2));
console.log(JSON.stringify({ total: report.total, passed: report.passed, failed: report.failed }, null, 2));
if (report.failures.length) {
  console.error(report.failures.join('\n'));
  process.exit(1);
}
