/**
 * SAATHI-279 real HTTP/database/Chromium gate. SQLite is permitted only as
 * supplementary local coverage; release evidence must declare PostgreSQL and
 * match the nonsecret dialect recorded by the seed fixture.
 *
 * This gate deliberately runs without Playwright tracing: an S-89 invitation
 * token exists in the URL fragment for less than one render and traces would
 * be capable of retaining that transient URL. Raw tokens are supplied only by
 * the process environment, sent only in the dedicated request header, and are
 * redacted from every thrown error and evidence row.
 */
import { readFile, mkdir, writeFile, unlink, stat, readdir } from 'node:fs/promises';
import path from 'node:path';
import { randomBytes } from 'node:crypto';
import { spawn } from 'node:child_process';
import { chromium } from 'playwright';
import axe from 'axe-core';

const ENABLED_WEB = (process.env.E2E_WEB_URL ?? 'http://127.0.0.1:1260').replace(/\/$/, '');
const ENABLED_API = (process.env.E2E_API_URL ?? 'http://127.0.0.1:1261').replace(/\/$/, '');
const DISABLED_WEB = (process.env.E2E_DISABLED_WEB_URL ?? 'http://127.0.0.1:1263').replace(/\/$/, '');
const DISABLED_API = (process.env.E2E_DISABLED_API_URL ?? 'http://127.0.0.1:1262').replace(/\/$/, '');
const OUT = path.resolve(process.env.E2E_OUTPUT_DIR ?? 'test-results/wave4-risk-labels-e2e');
const FIXTURE_PATH = path.resolve(process.env.WAVE4_E2E_FIXTURE_PATH ?? '../test-results/wave4-risk-label-fixture.json');
const COOKIE = process.env.AUTH_SESSION_COOKIE_NAME ?? 'nyayone_session';
const MODERATOR_TOKEN = process.env.WAVE4_E2E_SESSION_TOKEN ?? '';
const PUBLICATION_TOKEN = process.env.WAVE4_E2E_SAFETY_SESSION_TOKEN ?? '';
const LEGAL_TOKEN = process.env.WAVE4_E2E_LEGAL_SESSION_TOKEN ?? '';
const RESPONSE_TOKEN = process.env.WAVE4_E2E_RESPONSE_TOKEN ?? '';
const EXPIRED_TOKEN = process.env.WAVE4_E2E_EXPIRED_RESPONSE_TOKEN ?? '';
const BOUNDARY_TOKEN = process.env.WAVE4_E2E_BOUNDARY_RESPONSE_TOKEN ?? '';
const DATABASE_DIALECT = (process.env.WAVE4_E2E_DATABASE_DIALECT ?? '').trim().toLowerCase();
const ACTIVE_RESPONSE_TOKEN = RESPONSE_TOKEN;
const BACKEND_DIR = path.resolve(process.env.WAVE4_E2E_BACKEND_DIR ?? '../backend');
const PYTHON = process.env.WAVE4_E2E_PYTHON ?? 'python';
const RUNNER_TEMP = process.env.RUNNER_TEMP ? path.resolve(process.env.RUNNER_TEMP) : '';
const INVITATION_CAPTURE_SCRIPT = path.resolve(
  BACKEND_DIR,
  process.env.WAVE4_E2E_INVITATION_CAPTURE_SCRIPT ?? 'scripts/relay_wave4_response_invitations_e2e.py',
);
const SOURCE_INVALIDATION_SCRIPT = path.resolve(
  BACKEND_DIR,
  process.env.WAVE4_E2E_SOURCE_INVALIDATION_SCRIPT ?? 'scripts/invalidate_wave4_risk_label_source_e2e.py',
);
// Deliberately not a credential. A legacy query navigation necessarily sends
// its query to the web origin before React can run; this canary proves the app
// rejects and scrubs that input without risking a real invitation secret.
const LEGACY_QUERY_CANARY = 'wave4-query-token-nonsecret-canary';
const TOKENS = new Set(
  [MODERATOR_TOKEN, PUBLICATION_TOKEN, LEGAL_TOKEN, RESPONSE_TOKEN, EXPIRED_TOKEN, BOUNDARY_TOKEN]
    .filter(Boolean),
);
const report = {
  startedAt: new Date().toISOString(),
  target: `isolated-loopback-real-api-${DATABASE_DIALECT || 'unspecified'}-chromium`,
  databaseDialect: DATABASE_DIALECT || 'unspecified',
  rows: [],
  failures: [],
};

function redact(value) {
  let safe = typeof value === 'string' ? value : JSON.stringify(value);
  for (const token of TOKENS) safe = safe.split(token).join('[REDACTED]');
  return safe.replace(/([?#&]token=)[^&#\s]+/gi, '$1[REDACTED]');
}

function record(name, expected, actual, pass) {
  const row = { name, expected, actual: redact(actual), pass: Boolean(pass) };
  report.rows.push(row);
  if (!row.pass) report.failures.push(`${name}: expected ${expected}; actual ${row.actual}`);
}

function assert(name, condition, expected, actual) {
  record(name, expected, actual, condition);
  if (!condition) throw new Error(`${name}: expected ${expected}; actual ${redact(actual)}`);
}

function requireIsolatedRuntime() {
  if (process.env.WAVE4_E2E_ALLOW_RUN !== 'true') {
    throw new Error('WAVE4_E2E_ALLOW_RUN=true is required');
  }
  if (process.env.WAVE4_E2E_ALLOW_SOURCE_INVALIDATION !== 'true') {
    throw new Error('WAVE4_E2E_ALLOW_SOURCE_INVALIDATION=true is required');
  }
  if (!['sqlite', 'postgresql'].includes(DATABASE_DIALECT)) {
    throw new Error('WAVE4_E2E_DATABASE_DIALECT must be sqlite or postgresql');
  }
  for (const [name, raw] of [
    ['enabled web', ENABLED_WEB], ['enabled API', ENABLED_API],
    ['disabled web', DISABLED_WEB], ['disabled API', DISABLED_API],
  ]) {
    const url = new URL(raw);
    if (url.protocol !== 'http:' || !['127.0.0.1', 'localhost'].includes(url.hostname)) {
      throw new Error(`${name} must be an isolated loopback HTTP URL`);
    }
  }
  for (const [name, token] of [
    ['moderator session', MODERATOR_TOKEN],
    ['safety publication session', PUBLICATION_TOKEN],
    ['legal review session', LEGAL_TOKEN],
    ['response invitation', RESPONSE_TOKEN],
    ['expired invitation', EXPIRED_TOKEN],
    ['boundary invitation', BOUNDARY_TOKEN],
  ]) {
    if (token.length < 32) throw new Error(`${name} token must contain at least 32 characters`);
  }
  if (!RUNNER_TEMP) throw new Error('RUNNER_TEMP is required for the transient invitation capture');
}

async function bodyOf(response) {
  return response.json().catch(() => ({}));
}

function assertPublicProjectionPayloadPrivacy(name, response, rawBody) {
  const reasonLeak = /reason(?:_|-)code|verified_factual|qa_(?:target|boundary|policy)|moderator_(?:policy|review)/i.test(rawBody);
  const tokenLeak = [...TOKENS].some((token) => rawBody.includes(token));
  assert(
    name,
    response.status() === 200 && !reasonLeak && !tokenLeak,
    'HTTP 200; no moderation reason/code or invitation/session token',
    `HTTP ${response.status()} reasonLeak=${reasonLeak} tokenLeak=${tokenLeak}`,
  );
}

async function runInvitationCapture(deliveryIdempotencyKey) {
  await mkdir(RUNNER_TEMP, { recursive: true });
  const capturePath = path.join(
    RUNNER_TEMP,
    `wave4-invitation-${process.pid}-${randomBytes(12).toString('hex')}.txt`,
  );
  const args = [INVITATION_CAPTURE_SCRIPT];
  let stdout = '';
  let stderr = '';
  const code = await new Promise((resolve, reject) => {
    const child = spawn(PYTHON, args, {
      cwd: BACKEND_DIR,
      env: {
        ...process.env,
        WAVE4_E2E_DELIVERY_OUTPUT: capturePath,
        WAVE4_E2E_DELIVERY_IDEMPOTENCY_KEY: deliveryIdempotencyKey,
      },
      stdio: ['ignore', 'pipe', 'pipe'],
    });
    child.stdout.on('data', (chunk) => { stdout += String(chunk); });
    child.stderr.on('data', (chunk) => { stderr += String(chunk); });
    child.once('error', reject);
    child.once('close', resolve);
  });
  if (code !== 0) {
    await unlink(capturePath).catch(() => undefined);
    throw new Error(`invitation capture worker exited ${code}; output suppressed for credential safety`);
  }
  let invitationUrl;
  let captureMode;
  try {
    captureMode = (await stat(capturePath)).mode & 0o777;
    const payload = JSON.parse(await readFile(capturePath, 'utf8'));
    invitationUrl = String(payload?.invitation_url ?? '').trim();
  } finally {
    await unlink(capturePath).catch(() => undefined);
  }
  const captureRemoved = await stat(capturePath).then(
    () => false,
    (error) => error?.code === 'ENOENT',
  );
  const parsed = new URL(invitationUrl);
  const token = new URLSearchParams(parsed.hash.slice(1)).get('token') ?? '';
  TOKENS.add(token);
  assert(
    'real invitation relay captures one fragment-only correction credential in transient runner memory',
    captureRemoved && captureMode === 0o600 && parsed.pathname.endsWith('/s-89') && parsed.search === '' && token.length >= 32
      && !stdout.includes(token) && !stderr.includes(token),
    'S-89 fragment token; transient file removed; no query or child-process output leak',
    JSON.stringify({
      s89Path: parsed.pathname.endsWith('/s-89'),
      queryEmpty: parsed.search === '',
      captureMode0600: captureMode === 0o600,
      captureRemoved,
      tokenLengthValid: token.length >= 32,
      stdoutLeak: stdout.includes(token),
      stderrLeak: stderr.includes(token),
    }),
  );
  return token;
}

async function invalidatePublishedSource() {
  let stdout = '';
  let stderr = '';
  const code = await new Promise((resolve, reject) => {
    const child = spawn(PYTHON, [SOURCE_INVALIDATION_SCRIPT], {
      cwd: BACKEND_DIR,
      env: process.env,
      stdio: ['ignore', 'pipe', 'pipe'],
    });
    child.stdout.on('data', (chunk) => { stdout += String(chunk); });
    child.stderr.on('data', (chunk) => { stderr += String(chunk); });
    child.once('error', reject);
    child.once('close', resolve);
  });
  if (code !== 0) {
    throw new Error(`source invalidation helper exited ${code}; output suppressed for credential safety`);
  }
  const tokenLeak = [...TOKENS].some((token) => stdout.includes(token) || stderr.includes(token));
  const payload = JSON.parse(stdout.trim());
  const result = payload?.wave4_source_invalidation_e2e;
  assert(
    'guarded target-runtime helper invalidates deterministic source evidence without credential output',
    Number(result?.updated_evidence) >= 1 && !tokenLeak,
    'at least one evidence row invalidated; no credential in child output',
    JSON.stringify({ updatedEvidence: result?.updated_evidence ?? 0, tokenLeak }),
  );
}

async function issueCorrectionInvitation(browser, fixture) {
  const correctionKey = 'wave4-correction-invitation-runtime';
  const safety = await cookieContext(browser, ENABLED_API, PUBLICATION_TOKEN);
  const request = await safety.request.post(
    `${ENABLED_API}/api/v1/organisation-response-requests`,
    {
      headers: { 'Idempotency-Key': correctionKey },
      data: {
        published_label_id: fixture.prepublished_label_id,
        representative_verification_ref: 'qa-correction-after-approved-initial-response',
        verification_method: 'qa_fixture',
        request_kind: 'correction',
      },
    },
  );
  const body = await bodyOf(request);
  assert(
    'safety actor issues correction invitation only after an approved current response exists',
    request.status() === 201 && body?.state === 'pending' && body?.published_label_id === fixture.prepublished_label_id,
    'HTTP 201 pending for the currently published fixture label',
    `HTTP ${request.status()} state=${body?.state ?? 'missing'} label_match=${body?.published_label_id === fixture.prepublished_label_id}`,
  );
  await safety.close();
  return runInvitationCapture(`notification:${correctionKey}`);
}

async function cookieContext(browser, baseUrl, token, viewport = { width: 1440, height: 900 }, theme = 'light') {
  // Playwright's API request context is not a page fetch and therefore does
  // not synthesize an Origin header. Supply the actual enabled web origin so
  // cookie-backed unsafe requests exercise the production CSRF boundary.
  const context = await browser.newContext({
    viewport,
    colorScheme: theme,
    extraHTTPHeaders: { Origin: new URL(ENABLED_WEB).origin },
  });
  const url = new URL(baseUrl);
  await context.addCookies([{
    name: COOKIE, value: token, domain: url.hostname, path: '/',
    httpOnly: true, secure: false, sameSite: 'Lax',
  }]);
  return context;
}

function attachRuntimeOracle(page, expectedHttp = []) {
  const state = { console: [], page: [], request: [], http: [], consumed: [], consumedConsole: [] };
  page.on('console', (message) => {
    if (message.type() !== 'error') return;
    const entry = {
      text: redact(message.text()),
      url: redact(message.location().url || ''),
    };
    const matched = expectedHttp.find((item) => (
      item.consoleText === message.text()
      && message.location().url.includes(item.path)
    ));
    (matched ? state.consumedConsole : state.console).push(entry);
  });
  page.on('pageerror', (error) => state.page.push(redact(String(error))));
  page.on('requestfailed', (request) => state.request.push({
    url: redact(request.url()), error: redact(request.failure()?.errorText ?? 'unknown'),
  }));
  page.on('response', (response) => {
    if (response.status() < 400) return;
    const matched = expectedHttp.find((item) => item.status === response.status() && response.url().includes(item.path));
    const entry = { url: redact(response.url()), status: response.status() };
    (matched ? state.consumed : state.http).push(entry);
  });
  return state;
}

function assertCleanRuntime(prefix, state, expectedConsumed = 0, expectedConsoleConsumed = 0) {
  const counts = `${state.console.length}/${state.page.length}/${state.request.length}/${state.http.length}`;
  const diagnostics = state.console.length || state.page.length || state.request.length || state.http.length
    ? `; diagnostics=${JSON.stringify({ console: state.console, page: state.page, request: state.request, http: state.http })}`
    : '';
  assert(
    `${prefix} zero unexpected console/page/request/HTTP errors`,
    state.console.length === 0 && state.page.length === 0 && state.request.length === 0 && state.http.length === 0,
    '0/0/0/0',
    `${counts}${diagnostics}`,
  );
  assert(`${prefix} explicit expected HTTP errors consumed`, state.consumed.length === expectedConsumed, String(expectedConsumed), String(state.consumed.length));
  assert(
    `${prefix} exact browser console side-effects consumed`,
    state.consumedConsole.length === expectedConsoleConsumed,
    String(expectedConsoleConsumed),
    String(state.consumedConsole.length),
  );
}

async function assertDisabledByDefault(browser, fixture) {
  const context = await browser.newContext();
  const apiResponse = await context.request.get(
    `${DISABLED_API}/api/v1/public/internship-risk-labels/${fixture.organisation_id}`,
  );
  const body = await bodyOf(apiResponse);
  assert(
    'production-like backend fails closed',
    apiResponse.status() === 503
      && ['risk_labels_disabled', 'risk_labels_unavailable'].includes(body?.detail?.code)
      && body?.detail?.retryable === false,
    'HTTP 503 typed non-retryable disabled error',
    `HTTP ${apiResponse.status()} ${JSON.stringify(body)}`,
  );

  const page = await context.newPage();
  const runtime = attachRuntimeOracle(page);
  let publicRequests = 0;
  page.on('request', (request) => {
    if (request.url().includes('/api/v1/public/internship-risk-labels/')) publicRequests += 1;
  });
  await page.goto(`${DISABLED_WEB}/s-88?organisation=${fixture.organisation_id}`, { waitUntil: 'networkidle' });
  await page.locator('[data-risk-label-state="disabled"]').waitFor();
  assert('disabled S-88 performs no public-label request', publicRequests === 0, '0 requests', String(publicRequests));
  await page.screenshot({ path: path.join(OUT, 's88-disabled-production-default.png'), fullPage: true });

  await page.goto(`${DISABLED_WEB}/s-89#token=${encodeURIComponent(ACTIVE_RESPONSE_TOKEN)}`, { waitUntil: 'networkidle' });
  await page.locator('[data-risk-label-state="disabled"]').waitFor();
  await page.waitForURL((url) => !url.hash.includes('token='));
  const privacy = await page.evaluate(() => ({
    urlHasToken: /token=/i.test(location.href),
    local: Object.values(localStorage), session: Object.values(sessionStorage), cookie: document.cookie,
  }));
  assert(
    'disabled S-89 still scrubs invitation and stores nothing',
    !privacy.urlHasToken && !privacy.local.some((value) => value.includes('token'))
      && !privacy.session.some((value) => value.includes('token')) && privacy.cookie === '',
    'scrubbed URL, no browser-readable secret',
    JSON.stringify(privacy),
  );
  assertCleanRuntime('disabled UI', runtime);
  await context.close();
}

async function queryTokenMisuse(browser) {
  const context = await browser.newContext({ viewport: { width: 430, height: 932 }, colorScheme: 'light' });
  await context.addInitScript((canary) => {
    globalThis.__wave4QueryTokenProbe = {
      firstScreenUrlHasCanary: null,
      invitedFormAtFirstScreen: null,
      storageCanaryWrite: false,
    };
    const originalSetItem = Storage.prototype.setItem;
    Storage.prototype.setItem = function setItem(key, value) {
      if (String(key).includes(canary) || String(value).includes(canary)) {
        globalThis.__wave4QueryTokenProbe.storageCanaryWrite = true;
      }
      return originalSetItem.call(this, key, value);
    };
    const observer = new MutationObserver(() => {
      if (globalThis.__wave4QueryTokenProbe.firstScreenUrlHasCanary !== null) return;
      if (document.querySelector('[data-screen="S-89"]')) {
        globalThis.__wave4QueryTokenProbe.firstScreenUrlHasCanary = location.href.includes(canary)
          || /[?&]token=/i.test(location.search);
        globalThis.__wave4QueryTokenProbe.invitedFormAtFirstScreen = Boolean(
          document.querySelector('[data-response-state="invited"]'),
        );
      }
    });
    observer.observe(document, { childList: true, subtree: true });
  }, LEGACY_QUERY_CANARY);
  const page = await context.newPage();
  const runtime = attachRuntimeOracle(page);
  let initialWebOriginTransmissions = 0;
  let onwardNetworkTransmissions = 0;
  let responseCalls = 0;
  let referrerLeak = false;
  page.on('request', (request) => {
    if (request.url().includes('/api/v1/organisation-responses')) responseCalls += 1;
    if ((request.headers().referer ?? '').includes(LEGACY_QUERY_CANARY)) referrerLeak = true;
    if (request.url().includes(LEGACY_QUERY_CANARY)) {
      if (request.isNavigationRequest() && request.resourceType() === 'document') initialWebOriginTransmissions += 1;
      else onwardNetworkTransmissions += 1;
    }
  });
  await page.goto(`${ENABLED_WEB}/s-89?token=${encodeURIComponent(LEGACY_QUERY_CANARY)}`, { waitUntil: 'networkidle' });
  await page.locator('[data-risk-label-state="invalid-invitation"]').waitFor();
  await page.waitForURL((url) => !/[?&]token=/i.test(url.search));
  const probe = await page.evaluate((canary) => ({
    ...globalThis.__wave4QueryTokenProbe,
    currentUrlHasCanary: location.href.includes(canary) || /[?&]token=/i.test(location.search),
    invitedFormMounted: Boolean(document.querySelector('[data-response-state="invited"]')),
    localCanary: Object.entries(localStorage).some(([key, value]) => key.includes(canary) || value.includes(canary)),
    sessionCanary: Object.entries(sessionStorage).some(([key, value]) => key.includes(canary) || value.includes(canary)),
    readableCookieHasCanary: document.cookie.includes(canary),
  }), LEGACY_QUERY_CANARY);
  record(
    'S-89 reports the unavoidable initial legacy-query transmission truthfully',
    'one non-secret canary document request to the web origin; zero onward network propagation',
    JSON.stringify({ initialWebOriginTransmissions, onwardNetworkTransmissions }),
    initialWebOriginTransmissions === 1 && onwardNetworkTransmissions === 0,
  );
  record(
    'S-89 query token is scrubbed before paint and never authorises the invited form',
    'all leak/form booleans false; zero organisation-response calls',
    JSON.stringify({
      firstScreenUrlHasCanary: probe.firstScreenUrlHasCanary,
      invitedFormAtFirstScreen: probe.invitedFormAtFirstScreen,
      currentUrlHasCanary: probe.currentUrlHasCanary,
      invitedFormMounted: probe.invitedFormMounted,
      storageCanaryWrite: probe.storageCanaryWrite,
      localCanary: probe.localCanary,
      sessionCanary: probe.sessionCanary,
      readableCookieHasCanary: probe.readableCookieHasCanary,
      referrerLeak,
      responseCalls,
    }),
    probe.firstScreenUrlHasCanary === false && probe.invitedFormAtFirstScreen === false
      && probe.currentUrlHasCanary === false && probe.invitedFormMounted === false
      && probe.storageCanaryWrite === false && probe.localCanary === false
      && probe.sessionCanary === false && probe.readableCookieHasCanary === false
      && referrerLeak === false && responseCalls === 0,
  );
  assertCleanRuntime('S-89 query-token misuse', runtime);
  await context.close();
}

async function apiNegativeMatrix(browser) {
  const context = await browser.newContext();
  const endpoint = `${ENABLED_API}/api/v1/organisation-responses`;
  const post = (token, text, key) => context.request.post(endpoint, {
    headers: { 'X-Organisation-Response-Token': token, 'Idempotency-Key': key },
    data: { response_text: text },
  });
  for (const [name, value] of [
    ['empty', ''], ['spaces only', '   '], ['2,001 Unicode code points', '😀'.repeat(2001)],
    ['reserved markup', '<private allegation>'], ['control character', `safe\u0001unsafe`],
  ]) {
    const response = await post(`unknown-${randomBytes(32).toString('hex')}`, value, `negative-${name.replaceAll(' ', '-')}`);
    const body = await bodyOf(response);
    assert(
      `real API rejects ${name} response`,
      response.status() === 422,
      'HTTP 422 before token lookup',
      `HTTP ${response.status()} ${JSON.stringify(body)}`,
    );
  }

  const unknown = await post(`unknown-${randomBytes(32).toString('hex')}`, 'A', 'negative-unknown-token');
  const unknownBody = await bodyOf(unknown);
  assert(
    'real API rejects unknown invitation without enumeration',
    unknown.status() === 404 && unknownBody?.detail?.code === 'response_token_unavailable',
    'HTTP 404 response_token_unavailable',
    `HTTP ${unknown.status()} ${JSON.stringify(unknownBody)}`,
  );

  const expired = await post(EXPIRED_TOKEN, 'A', 'negative-expired-token');
  const expiredBody = await bodyOf(expired);
  assert(
    'real API rejects expired invitation without enumeration',
    expired.status() === 404 && expiredBody?.detail?.code === 'response_token_unavailable',
    'HTTP 404 response_token_unavailable',
    `HTTP ${expired.status()} ${JSON.stringify(expiredBody)}`,
  );

  const boundaryText = '😀'.repeat(2000);
  const boundary = await post(BOUNDARY_TOKEN, boundaryText, 'boundary-2000-unicode');
  const boundaryBody = await bodyOf(boundary);
  assert(
    'real API accepts exactly 2,000 Unicode code points',
    boundary.status() === 201 && boundaryBody?.state === 'moderation_pending',
    'HTTP 201 moderation_pending',
    `HTTP ${boundary.status()} state=${boundaryBody?.state ?? 'missing'}`,
  );
  const boundaryReplay = await post(BOUNDARY_TOKEN, boundaryText, 'boundary-2000-unicode-replay');
  const boundaryReplayBody = await bodyOf(boundaryReplay);
  assert(
    '2,000-character invitation is single use',
    boundaryReplay.status() === 404 && boundaryReplayBody?.detail?.code === 'response_token_unavailable',
    'HTTP 404 response_token_unavailable',
    `HTTP ${boundaryReplay.status()} ${JSON.stringify(boundaryReplayBody)}`,
  );
  await context.close();
  return boundaryBody;
}

async function rejectPendingBoundaryResponse(browser, fixture, response) {
  const publicContext = await browser.newContext();
  const before = await publicContext.request.get(
    `${ENABLED_API}/api/v1/public/internship-risk-labels/${fixture.organisation_id}`,
  );
  const beforeBody = await bodyOf(before);
  const beforeLabel = beforeBody?.labels?.find((item) => item.id === fixture.prepublished_label_id);
  assert(
    '2,000-character response remains private while moderation is pending',
    before.status() === 200 && beforeLabel?.organisation_response?.text !== '😀'.repeat(2000),
    'public projection unchanged',
    `HTTP ${before.status()} boundary_is_public=${beforeLabel?.organisation_response?.text === '😀'.repeat(2000)}`,
  );
  const moderator = await cookieContext(browser, ENABLED_API, MODERATOR_TOKEN);
  const decision = await moderator.request.post(
    `${ENABLED_API}/api/v1/moderation/organisation-responses/${response.id}/decide`,
    {
      headers: { 'Idempotency-Key': 'wave4-boundary-response-reject' },
      data: { decision: 'reject', reason_code: 'response_policy_violation', expected_version: response.version },
    },
  );
  const decisionBody = await bodyOf(decision);
  assert(
    'moderator rejection keeps boundary response private',
    decision.status() === 200 && decisionBody?.state === 'rejected',
    'HTTP 200 rejected',
    `HTTP ${decision.status()} state=${decisionBody?.state ?? 'missing'}`,
  );
  await moderator.close();
  const after = await publicContext.request.get(
    `${ENABLED_API}/api/v1/public/internship-risk-labels/${fixture.organisation_id}`,
  );
  const afterBody = await bodyOf(after);
  const afterLabel = afterBody?.labels?.find((item) => item.id === fixture.prepublished_label_id);
  assert(
    'rejected organisation response never enters public projection',
    after.status() === 200 && afterLabel?.organisation_response?.text === beforeLabel?.organisation_response?.text,
    'public response unchanged after rejection',
    `HTTP ${after.status()} unchanged=${afterLabel?.organisation_response?.text === beforeLabel?.organisation_response?.text}`,
  );
  await publicContext.close();
}

async function publishCandidate(browser, fixture) {
  const moderator = await cookieContext(browser, ENABLED_API, MODERATOR_TOKEN);
  const candidates = await moderator.request.get(`${ENABLED_API}/api/v1/moderation/risk-labels`);
  const candidateBody = await bodyOf(candidates);
  const candidate = candidateBody?.items?.find((item) => item.cluster_id === fixture.candidate_cluster_id);
  assert(
    'moderation candidate is target-runtime ready',
    candidates.status() === 200 && candidate?.version === Number(fixture.candidate_version)
      && candidate?.threshold_met === true && candidate?.moderator_approved === true
      && candidate?.safety_legal_approved === true && candidate?.approval_vetoed === false,
    'HTTP 200, version and independent approval prerequisites true',
    `HTTP ${candidates.status()} candidate=${JSON.stringify(candidate ?? null)}`,
  );
  await moderator.close();
  const context = await cookieContext(browser, ENABLED_API, PUBLICATION_TOKEN);
  const response = await context.request.post(
    `${ENABLED_API}/api/v1/moderation/risk-labels/${fixture.candidate_cluster_id}/publish`,
    {
      headers: { 'Idempotency-Key': 'wave4-risk-label-e2e-publish' },
      data: { expected_version: Number(fixture.candidate_version), reason_code: 'qa_governed_publication', action: 'publish' },
    },
  );
  const body = await bodyOf(response);
  assert(
    'safety officer publishes eligible neutral aggregate',
    response.status() === 200 && body?.status === 'published' && body?.organisation_id === fixture.organisation_id,
    'HTTP 200 published for fixture organisation',
    `HTTP ${response.status()} status=${body?.status ?? 'missing'} code=${body?.detail?.code ?? 'missing'} organisation_match=${body?.organisation_id === fixture.organisation_id}`,
  );
  const published = { id: body?.id, version: body?.version };
  await context.close();
  return published;
}

async function activeS89KeyboardCoverage(browser) {
  const context = await browser.newContext({ viewport: { width: 430, height: 932 }, colorScheme: 'light' });
  const page = await context.newPage();
  const runtime = attachRuntimeOracle(page);
  let responseCalls = 0;
  page.on('request', (request) => {
    if (request.url().includes('/api/v1/organisation-responses')) responseCalls += 1;
  });
  await page.goto(`${ENABLED_WEB}/s-89#token=${encodeURIComponent(ACTIVE_RESPONSE_TOKEN)}`, { waitUntil: 'networkidle' });
  await page.getByRole('heading', { name: 'Provide a factual response' }).waitFor();
  await page.waitForURL((url) => !url.hash.includes('token='));
  const input = page.getByLabel('Organisation response or correction');
  await input.focus();
  const focused = await input.evaluate((node) => node === document.activeElement);
  await page.keyboard.press('Tab');
  const nextName = await page.evaluate(() => document.activeElement?.textContent?.trim());
  record(
    'S-89 seeded, non-consuming active-form keyboard coverage',
    'textarea focus then Submit for moderation; URL scrubbed; zero response calls',
    JSON.stringify({ focused, nextIsSubmit: nextName === 'Submit for moderation', urlScrubbed: !page.url().includes('token='), responseCalls }),
    focused && nextName === 'Submit for moderation' && !page.url().includes('token=') && responseCalls === 0,
  );
  await page.screenshot({ path: path.join(OUT, 's89-active-form-keyboard-430x932-light.png'), fullPage: true });
  assertCleanRuntime('S-89 seeded active-form keyboard coverage', runtime);
  await context.close();
}

async function typedSubmissionConflict(browser) {
  const endpoint = '/api/v1/organisation-responses';
  const backendMessage = 'Submission conflict';
  const context = await browser.newContext({ viewport: { width: 430, height: 932 }, colorScheme: 'light' });
  const page = await context.newPage();
  const runtime = attachRuntimeOracle(page, [{
    path: endpoint,
    status: 409,
    consoleText: 'Failed to load resource: the server responded with a status of 409 (Conflict)',
  }]);
  const attempts = [];
  let invitationIssueCalls = 0;
  page.on('request', (request) => {
    if (request.url().includes('/api/v1/organisation-response-requests')) invitationIssueCalls += 1;
  });
  await page.route(`**${endpoint}`, async (route) => {
    const request = route.request();
    const headers = await request.allHeaders();
    attempts.push({
      idempotencyKey: headers['idempotency-key'] ?? '',
      exactTokenHeader: headers['x-organisation-response-token'] === ACTIVE_RESPONSE_TOKEN,
      urlLeak: request.url().includes(ACTIVE_RESPONSE_TOKEN),
      bodyLeak: (request.postData() ?? '').includes(ACTIVE_RESPONSE_TOKEN),
      rawReasonField: /reason(?:_|-)code/i.test(request.postData() ?? ''),
    });
    await route.fulfill({
      status: 409,
      contentType: 'application/json',
      body: JSON.stringify({
        detail: {
          code: 'idempotency_conflict',
          message: backendMessage,
          retryable: false,
        },
      }),
    });
  });
  await page.goto(`${ENABLED_WEB}/s-89#token=${encodeURIComponent(ACTIVE_RESPONSE_TOKEN)}`, { waitUntil: 'networkidle' });
  await page.getByRole('heading', { name: 'Provide a factual response' }).waitFor();
  await page.waitForURL((url) => !url.hash.includes('token='));
  await page.getByLabel('Organisation response or correction').fill('A factual response for the conflict boundary.');
  await page.getByRole('button', { name: 'Submit for moderation' }).click();
  const conflict = page.locator('[data-response-error-kind="conflict"]');
  await conflict.waitFor();
  const firstCopy = await conflict.innerText();
  assert(
    'typed 409 renders neutral conflict recovery without backend text',
    /Start a fresh submission attempt/.test(firstCopy) && !firstCopy.includes(backendMessage),
    'neutral conflict copy; backend message absent',
    firstCopy,
  );
  assert(
    'typed 409 disables blind resubmission until explicit recovery',
    await page.getByRole('button', { name: 'Submit for moderation' }).isDisabled(),
    'primary submit disabled',
    `disabled=${await page.getByRole('button', { name: 'Submit for moderation' }).isDisabled()}`,
  );
  await page.getByRole('button', { name: 'Start a fresh submission attempt' }).click();
  await conflict.waitFor({ state: 'detached' });
  assert(
    'explicit conflict recovery re-enables submission',
    await page.getByRole('button', { name: 'Submit for moderation' }).isEnabled(),
    'primary submit enabled after user action',
    `enabled=${await page.getByRole('button', { name: 'Submit for moderation' }).isEnabled()}`,
  );
  await page.getByRole('button', { name: 'Submit for moderation' }).click();
  await page.locator('[data-response-error-kind="conflict"]').waitFor();
  const privacy = await page.evaluate(({ token, message }) => ({
    urlLeak: location.href.includes(token),
    localLeak: Object.values(localStorage).some((value) => value.includes(token) || value.includes(message)),
    sessionLeak: Object.values(sessionStorage).some((value) => value.includes(token) || value.includes(message)),
    domReasonLeak: document.body.innerText.includes(message),
  }), { token: ACTIVE_RESPONSE_TOKEN, message: backendMessage });
  assert(
    'explicit conflict recovery rotates only the idempotency key and keeps credentials out of request URL/body',
    attempts.length === 2 && attempts[0].idempotencyKey.length > 0
      && attempts[1].idempotencyKey.length > 0
      && attempts[0].idempotencyKey !== attempts[1].idempotencyKey
      && attempts.every((item) => item.exactTokenHeader && !item.urlLeak && !item.bodyLeak && !item.rawReasonField)
      && invitationIssueCalls === 0,
    'two distinct keys; token only in dedicated header; no raw reason field; zero new invitation calls',
    JSON.stringify({ attempts, invitationIssueCalls }),
  );
  assert(
    'typed conflict keeps token and backend message out of URL, DOM and browser storage',
    !privacy.urlLeak && !privacy.localLeak && !privacy.sessionLeak && !privacy.domReasonLeak,
    'all leak probes false',
    JSON.stringify(privacy),
  );
  await page.screenshot({ path: path.join(OUT, 's89-idempotency-conflict-430x932-light.png'), fullPage: true });
  assertCleanRuntime('S-89 typed idempotency conflict', runtime, 2, 2);
  await context.close();
}

async function staleCorrectionInvitation(browser) {
  const endpoint = '/api/v1/organisation-responses';
  const backendMessage = 'Correction or appeal target changed';
  const context = await browser.newContext({ viewport: { width: 390, height: 844 }, colorScheme: 'dark' });
  const page = await context.newPage();
  const runtime = attachRuntimeOracle(page, [{
    path: endpoint,
    status: 409,
    consoleText: 'Failed to load resource: the server responded with a status of 409 (Conflict)',
  }]);
  const requests = [];
  let invitationIssueCalls = 0;
  page.on('request', (request) => {
    if (request.url().includes('/api/v1/organisation-response-requests')) invitationIssueCalls += 1;
  });
  await page.route(`**${endpoint}`, async (route) => {
    const request = route.request();
    const headers = await request.allHeaders();
    requests.push({
      exactTokenHeader: headers['x-organisation-response-token'] === ACTIVE_RESPONSE_TOKEN,
      urlLeak: request.url().includes(ACTIVE_RESPONSE_TOKEN),
      bodyLeak: (request.postData() ?? '').includes(ACTIVE_RESPONSE_TOKEN),
      rawReasonField: /reason(?:_|-)code/i.test(request.postData() ?? ''),
    });
    await route.fulfill({
      status: 409,
      contentType: 'application/json',
      body: JSON.stringify({
        detail: {
          code: 'response_correction_target_changed',
          message: backendMessage,
          retryable: false,
        },
      }),
    });
  });
  await page.goto(`${ENABLED_WEB}/s-89#token=${encodeURIComponent(ACTIVE_RESPONSE_TOKEN)}`, { waitUntil: 'networkidle' });
  await page.getByRole('heading', { name: 'Provide a factual response' }).waitFor();
  await page.waitForURL((url) => !url.hash.includes('token='));
  await page.getByLabel('Organisation response or correction').fill('A stale correction must not be resubmitted.');
  await page.getByRole('button', { name: 'Submit for moderation' }).click();
  const invalid = page.locator('[data-risk-label-state="invalid-invitation"]');
  await invalid.waitFor();
  const copy = await invalid.innerText();
  const privacy = await page.evaluate(({ token, message }) => ({
    urlLeak: location.href.includes(token),
    localLeak: Object.values(localStorage).some((value) => value.includes(token) || value.includes(message)),
    sessionLeak: Object.values(sessionStorage).some((value) => value.includes(token) || value.includes(message)),
    domReasonLeak: document.body.innerText.includes(message),
    invitedForm: Boolean(document.querySelector('[data-response-state="invited"]')),
  }), { token: ACTIVE_RESPONSE_TOKEN, message: backendMessage });
  assert(
    'stale correction 409 invalidates token-dependent controls and exposes a neutral recovery path',
    /no longer current/.test(copy)
      && await page.getByRole('link', { name: 'Return to internships' }).isVisible()
      && !privacy.invitedForm && await page.getByRole('button', { name: 'Submit for moderation' }).count() === 0,
    'neutral stale state, back link, no form or resubmit control',
    `${copy}; ${JSON.stringify(privacy)}`,
  );
  assert(
    'stale correction request carries no token or raw reason in URL/body and renders no backend message',
    requests.length === 1 && requests[0].exactTokenHeader
      && !requests[0].urlLeak && !requests[0].bodyLeak && !requests[0].rawReasonField
      && !privacy.urlLeak && !privacy.localLeak && !privacy.sessionLeak && !privacy.domReasonLeak
      && invitationIssueCalls === 0,
    'dedicated header only; all reason/token leak probes false; zero new invitation calls',
    JSON.stringify({ requests, privacy, invitationIssueCalls }),
  );
  await page.screenshot({ path: path.join(OUT, 's89-stale-correction-390x844-dark.png'), fullPage: true });
  assertCleanRuntime('S-89 stale correction target', runtime, 1, 1);
  await context.close();
}

async function s89Lifecycle(browser, fixture) {
  const context = await browser.newContext({ viewport: { width: 430, height: 932 }, colorScheme: 'light' });
  await context.addInitScript((secret) => {
    globalThis.__wave4PrivacyProbe = { firstScreenUrlHasToken: null, storageSecretWrite: false };
    const originalSetItem = Storage.prototype.setItem;
    Storage.prototype.setItem = function setItem(key, value) {
      if (String(key).includes(secret) || String(value).includes(secret)) {
        globalThis.__wave4PrivacyProbe.storageSecretWrite = true;
      }
      return originalSetItem.call(this, key, value);
    };
    const observer = new MutationObserver(() => {
      if (globalThis.__wave4PrivacyProbe.firstScreenUrlHasToken !== null) return;
      if (document.querySelector('[data-screen="S-89"]')) {
        globalThis.__wave4PrivacyProbe.firstScreenUrlHasToken = location.href.includes(secret) || /[#?&]token=/i.test(location.href);
      }
    });
    observer.observe(document, { childList: true, subtree: true });
  }, ACTIVE_RESPONSE_TOKEN);
  const page = await context.newPage();
  const runtime = attachRuntimeOracle(page);
  const responseRequests = [];
  page.on('request', async (request) => {
    if (!request.url().endsWith('/api/v1/organisation-responses') || request.method() !== 'POST') return;
    const headers = await request.allHeaders();
    responseRequests.push({
      urlContainsSecret: request.url().includes(ACTIVE_RESPONSE_TOKEN),
      bodyContainsSecret: (request.postData() ?? '').includes(ACTIVE_RESPONSE_TOKEN),
      dedicatedHeaderExact: headers['x-organisation-response-token'] === ACTIVE_RESPONSE_TOKEN,
    });
  });
  await page.goto(`${ENABLED_WEB}/s-89#token=${encodeURIComponent(ACTIVE_RESPONSE_TOKEN)}`, { waitUntil: 'networkidle' });
  await page.getByRole('heading', { name: 'Provide a factual response' }).waitFor();
  await page.waitForURL((url) => !url.hash.includes('token='));
  const probe = await page.evaluate((secret) => ({
    ...globalThis.__wave4PrivacyProbe,
    currentUrlHasSecret: location.href.includes(secret) || /[#?&]token=/i.test(location.href),
    localSecret: Object.entries(localStorage).some(([key, value]) => key.includes(secret) || value.includes(secret)),
    sessionSecret: Object.entries(sessionStorage).some(([key, value]) => key.includes(secret) || value.includes(secret)),
    readableCookie: document.cookie,
  }), ACTIVE_RESPONSE_TOKEN);
  assert(
    'S-89 scrubs fragment before feature paint and never stores token',
    probe.firstScreenUrlHasToken === false && probe.storageSecretWrite === false
      && probe.currentUrlHasSecret === false && probe.localSecret === false
      && probe.sessionSecret === false && probe.readableCookie === '',
    'all token-leak probes false and no readable cookie',
    JSON.stringify(probe),
  );

  const input = page.getByLabel('Organisation response or correction');
  await page.getByRole('button', { name: 'Submit for moderation' }).click();
  await page.getByRole('alert').waitFor();
  assert('S-89 blocks empty input', /1–2,000/.test(await page.getByRole('alert').innerText()), 'length error', await page.getByRole('alert').innerText());
  await input.fill('   ');
  await page.getByRole('button', { name: 'Submit for moderation' }).click();
  assert('S-89 blocks spaces-only input', /1–2,000/.test(await page.getByRole('alert').innerText()), 'length error', await page.getByRole('alert').innerText());
  await input.fill('😀'.repeat(2000));
  assert(
    'S-89 counts exactly 2,000 Unicode code points as valid input',
    /2,000\s*\/\s*2,000/.test(await page.locator('#organisation-response-count').innerText()),
    '2,000 / 2,000 characters',
    await page.locator('#organisation-response-count').innerText(),
  );
  await input.fill('😀'.repeat(2001));
  await page.getByRole('button', { name: 'Submit for moderation' }).click();
  assert('S-89 blocks 2,001 Unicode code points', /1–2,000/.test(await page.getByRole('alert').innerText()), 'length error', await page.getByRole('alert').innerText());
  await input.fill('<private allegation>');
  await page.getByRole('button', { name: 'Submit for moderation' }).click();
  assert('S-89 blocks reserved markup', /control characters/.test(await page.getByRole('alert').innerText()), 'unsafe character error', await page.getByRole('alert').innerText());
  await input.evaluate((node) => {
    const setter = Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, 'value')?.set;
    setter?.call(node, `safe\u0001unsafe`);
    node.dispatchEvent(new Event('input', { bubbles: true }));
  });
  await page.getByRole('button', { name: 'Submit for moderation' }).click();
  assert('S-89 blocks ASCII control characters', /control characters/.test(await page.getByRole('alert').innerText()), 'unsafe character error', await page.getByRole('alert').innerText());
  await input.fill('A');
  const submittedResponse = page.waitForResponse((response) => response.url().endsWith('/api/v1/organisation-responses') && response.request().method() === 'POST');
  await page.getByRole('button', { name: 'Submit for moderation' }).click();
  const response = await submittedResponse;
  const body = await bodyOf(response);
  await page.locator('[data-response-state="moderation-pending"]').waitFor();
  assert(
    'S-89 accepts one Unicode code point through the real API',
    response.status() === 201 && body?.state === 'moderation_pending',
    'HTTP 201 moderation_pending',
    `HTTP ${response.status()} state=${body?.state ?? 'missing'}`,
  );
  assert(
    'S-89 token travels only in dedicated request header',
    responseRequests.length === 1 && responseRequests[0].dedicatedHeaderExact
      && !responseRequests[0].urlContainsSecret && !responseRequests[0].bodyContainsSecret,
    'one request; exact header; absent from URL/body',
    JSON.stringify(responseRequests),
  );
  await page.screenshot({ path: path.join(OUT, 's89-submitted-430x932-light.png'), fullPage: true });
  assertCleanRuntime('S-89 happy path', runtime);

  await page.reload({ waitUntil: 'networkidle' });
  await page.locator('[data-risk-label-state="invalid-invitation"]').waitFor();
  assert('direct refresh cannot resurrect in-memory invitation', true, 'invalid invitation after refresh', 'invalid invitation');

  const replay = await context.request.post(`${ENABLED_API}/api/v1/organisation-responses`, {
    headers: { 'X-Organisation-Response-Token': ACTIVE_RESPONSE_TOKEN, 'Idempotency-Key': 'wave4-response-replay' },
    data: { response_text: 'A' },
  });
  const replayBody = await bodyOf(replay);
  assert(
    'real invitation cannot be replayed',
    replay.status() === 404 && replayBody?.detail?.code === 'response_token_unavailable',
    'HTTP 404 response_token_unavailable',
    `HTTP ${replay.status()} ${JSON.stringify(replayBody)}`,
  );
  await context.close();

  const beforeApprovalContext = await browser.newContext();
  const beforeApproval = await beforeApprovalContext.request.get(
    `${ENABLED_API}/api/v1/public/internship-risk-labels/${fixture.organisation_id}`,
  );
  const beforeApprovalBody = await bodyOf(beforeApproval);
  const beforeApprovalLabel = beforeApprovalBody?.labels?.find((item) => item.id === fixture.prepublished_label_id);
  assert(
    'new organisation response remains private before moderation approval',
    beforeApproval.status() === 200 && beforeApprovalLabel?.organisation_response?.text !== 'A',
    'HTTP 200 with previous approved response unchanged',
    `HTTP ${beforeApproval.status()} response_is_new=${beforeApprovalLabel?.organisation_response?.text === 'A'}`,
  );
  await beforeApprovalContext.close();

  const moderator = await cookieContext(browser, ENABLED_API, MODERATOR_TOKEN);
  const decision = await moderator.request.post(
    `${ENABLED_API}/api/v1/moderation/organisation-responses/${body.id}/decide`,
    {
      headers: { 'Idempotency-Key': 'wave4-response-approve' },
      data: { decision: 'approve', reason_code: 'verified_initial_response', expected_version: body.version },
    },
  );
  const decisionBody = await bodyOf(decision);
  assert(
    'moderator approves organisation response',
    decision.status() === 200 && decisionBody?.state === 'approved',
    'HTTP 200 approved',
    `HTTP ${decision.status()} state=${decisionBody?.state ?? 'missing'}`,
  );
  await moderator.close();

  const publicContext = await browser.newContext({ viewport: { width: 1440, height: 900 }, colorScheme: 'light' });
  const initialProjectionApi = await publicContext.request.get(
    `${ENABLED_API}/api/v1/public/internship-risk-labels/${fixture.organisation_id}`,
  );
  const initialProjectionRaw = await initialProjectionApi.text();
  assertPublicProjectionPayloadPrivacy(
    'approved initial public payload excludes moderation reasons and credentials',
    initialProjectionApi,
    initialProjectionRaw,
  );
  const publicPage = await publicContext.newPage();
  const publicRuntime = attachRuntimeOracle(publicPage);
  await publicPage.goto(`${ENABLED_WEB}/s-88?organisation=${fixture.organisation_id}`, { waitUntil: 'networkidle' });
  const initialCard = publicPage.locator(`[data-risk-label-id="${fixture.prepublished_label_id}"][data-risk-label-status="approved"]`);
  await initialCard.waitFor();
  const projectionText = await initialCard.innerText();
  assert(
    'S-88 publishes the approved initial organisation response only after moderation',
    /Approved aggregate/.test(projectionText) && /Approved organisation response/.test(projectionText)
      && /\nA\n/.test(`\n${projectionText}\n`)
      && !/private allegation|reporter|response_token/i.test(projectionText),
    'approved aggregate and initial response, no private source detail',
    projectionText.slice(0, 600),
  );
  await publicPage.screenshot({ path: path.join(OUT, 's88-approved-initial-response-1440x900-light.png'), fullPage: true });
  assertCleanRuntime('S-88 approved initial projection', publicRuntime);
  await publicContext.close();
}

async function correctionLifecycle(browser, fixture) {
  const correctionText = 'The organisation corrected its documented internship hours and review process.';
  const correctionToken = await issueCorrectionInvitation(browser, fixture);
  const context = await browser.newContext({ viewport: { width: 430, height: 932 }, colorScheme: 'dark' });
  await context.addInitScript((secret) => {
    globalThis.__wave4CorrectionProbe = { firstScreenUrlHasToken: null, storageSecretWrite: false };
    const originalSetItem = Storage.prototype.setItem;
    Storage.prototype.setItem = function setItem(key, value) {
      if (String(key).includes(secret) || String(value).includes(secret)) {
        globalThis.__wave4CorrectionProbe.storageSecretWrite = true;
      }
      return originalSetItem.call(this, key, value);
    };
    const observer = new MutationObserver(() => {
      if (globalThis.__wave4CorrectionProbe.firstScreenUrlHasToken !== null) return;
      if (document.querySelector('[data-screen="S-89"]')) {
        globalThis.__wave4CorrectionProbe.firstScreenUrlHasToken = location.href.includes(secret) || /[#?&]token=/i.test(location.href);
      }
    });
    observer.observe(document, { childList: true, subtree: true });
  }, correctionToken);
  const page = await context.newPage();
  const runtime = attachRuntimeOracle(page);
  const requestProbe = [];
  page.on('request', async (request) => {
    if (!request.url().endsWith('/api/v1/organisation-responses') || request.method() !== 'POST') return;
    const headers = await request.allHeaders();
    requestProbe.push({
      exactHeader: headers['x-organisation-response-token'] === correctionToken,
      urlOrBodyLeak: request.url().includes(correctionToken) || (request.postData() ?? '').includes(correctionToken),
    });
  });
  await page.goto(`${ENABLED_WEB}/s-89#token=${encodeURIComponent(correctionToken)}`, { waitUntil: 'networkidle' });
  await page.getByRole('heading', { name: 'Provide a factual response' }).waitFor();
  await page.waitForURL((url) => !url.hash.includes('token='));
  const probe = await page.evaluate((secret) => ({
    ...globalThis.__wave4CorrectionProbe,
    currentUrlLeak: location.href.includes(secret) || /[#?&]token=/i.test(location.href),
    localLeak: Object.values(localStorage).some((value) => value.includes(secret)),
    sessionLeak: Object.values(sessionStorage).some((value) => value.includes(secret)),
  }), correctionToken);
  assert(
    'correction invitation is scrubbed before feature paint and never stored',
    probe.firstScreenUrlHasToken === false && !probe.storageSecretWrite
      && !probe.currentUrlLeak && !probe.localLeak && !probe.sessionLeak,
    'all token-leak probes false',
    JSON.stringify(probe),
  );
  await page.getByLabel('Organisation response or correction').fill(correctionText);
  const submitted = page.waitForResponse((response) => response.url().endsWith('/api/v1/organisation-responses') && response.request().method() === 'POST');
  await page.getByRole('button', { name: 'Submit for moderation' }).click();
  const response = await submitted;
  const body = await bodyOf(response);
  await page.locator('[data-response-state="moderation-pending"]').waitFor();
  assert(
    'S-89 correction enters moderation pending',
    response.status() === 201 && body?.state === 'moderation_pending'
      && requestProbe.length === 1 && requestProbe[0].exactHeader && !requestProbe[0].urlOrBodyLeak,
    'HTTP 201, dedicated header only',
    `HTTP ${response.status()} state=${body?.state ?? 'missing'} probe=${JSON.stringify(requestProbe)}`,
  );
  assertCleanRuntime('S-89 correction submission', runtime);
  await context.close();

  const pending = await browser.newContext();
  const pendingProjection = await pending.request.get(
    `${ENABLED_API}/api/v1/public/internship-risk-labels/${fixture.organisation_id}`,
  );
  const pendingBody = await bodyOf(pendingProjection);
  const pendingLabel = pendingBody?.labels?.find((item) => item.id === fixture.prepublished_label_id);
  assert(
    'pending correction does not replace the approved initial public response',
    pendingProjection.status() === 200 && pendingLabel?.status === 'approved'
      && pendingLabel?.organisation_response?.text === 'A',
    'initial response A remains public until correction approval',
    `HTTP ${pendingProjection.status()} status=${pendingLabel?.status ?? 'missing'} initial_remains=${pendingLabel?.organisation_response?.text === 'A'}`,
  );
  await pending.close();

  const moderator = await cookieContext(browser, ENABLED_API, MODERATOR_TOKEN);
  const decision = await moderator.request.post(
    `${ENABLED_API}/api/v1/moderation/organisation-responses/${body.id}/decide`,
    {
      headers: { 'Idempotency-Key': 'wave4-correction-approve' },
      data: { decision: 'approve', reason_code: 'verified_factual_correction', expected_version: body.version },
    },
  );
  const decisionBody = await bodyOf(decision);
  assert(
    'moderator approves correction and supersedes prior response',
    decision.status() === 200 && decisionBody?.state === 'approved',
    'HTTP 200 approved',
    `HTTP ${decision.status()} state=${decisionBody?.state ?? 'missing'}`,
  );
  await moderator.close();

  const publicContext = await browser.newContext({ viewport: { width: 1440, height: 900 }, colorScheme: 'dark' });
  const correctedProjectionApi = await publicContext.request.get(
    `${ENABLED_API}/api/v1/public/internship-risk-labels/${fixture.organisation_id}`,
  );
  const correctedProjectionRaw = await correctedProjectionApi.text();
  assertPublicProjectionPayloadPrivacy(
    'corrected public payload excludes moderation reasons and credentials',
    correctedProjectionApi,
    correctedProjectionRaw,
  );
  const pagePublic = await publicContext.newPage();
  const publicRuntime = attachRuntimeOracle(pagePublic);
  const route = `${ENABLED_WEB}/s-88?organisation=${fixture.organisation_id}`;
  await pagePublic.goto(route, { waitUntil: 'networkidle' });
  const corrected = pagePublic.locator(`[data-risk-label-id="${fixture.prepublished_label_id}"][data-risk-label-status="corrected"]`);
  await corrected.waitFor();
  const text = await corrected.innerText();
  assert(
    'S-88 renders only the approved correction after supersession',
    /Approved correction/.test(text) && /Approved organisation correction/.test(text)
      && text.includes(correctionText) && !/private allegation|reporter|response_token/i.test(text),
    'corrected badge and corrected response only',
    text.slice(0, 700),
  );
  await pagePublic.reload({ waitUntil: 'networkidle' });
  await pagePublic.locator(`[data-risk-label-id="${fixture.prepublished_label_id}"][data-risk-label-status="corrected"]`).waitFor();
  assert('direct S-88 reload restores corrected server projection', true, 'corrected state after reload', 'corrected state');
  await pagePublic.screenshot({ path: path.join(OUT, 's88-corrected-1440x900-dark.png'), fullPage: true });
  assertCleanRuntime('S-88 corrected projection and direct reload', publicRuntime);
  await publicContext.close();
}

async function retryableAndEmptyStates(browser, fixture) {
  const context = await browser.newContext({ viewport: { width: 390, height: 844 } });
  const page = await context.newPage();
  const endpoint = `/api/v1/public/internship-risk-labels/${fixture.organisation_id}`;
  let attempts = 0;
  await page.route(`**${endpoint}`, async (route) => {
    attempts += 1;
    if (attempts === 1) {
      await route.fulfill({
        status: 503, contentType: 'application/json',
        body: JSON.stringify({ detail: { code: 'risk_labels_temporarily_unavailable', message: 'Retry safely', retryable: true } }),
      });
      return;
    }
    await route.continue();
  });
  const runtime = attachRuntimeOracle(page, [{
    path: endpoint,
    status: 503,
    consoleText: 'Failed to load resource: the server responded with a status of 503 (Service Unavailable)',
  }]);
  await page.goto(`${ENABLED_WEB}/s-88?organisation=${fixture.organisation_id}`, { waitUntil: 'networkidle' });
  await page.locator('[data-risk-label-state="retryable"]').waitFor();
  await page.getByRole('button', { name: 'Retry' }).click();
  await page.locator('[data-risk-label-state="published"]').waitFor();
  assert('retryable S-88 recovers via explicit retry', attempts === 2, '2 attempts', String(attempts));
  assertCleanRuntime('retryable S-88', runtime, 1, 1);
  await context.close();

  const emptyContext = await browser.newContext({ viewport: { width: 390, height: 844 } });
  const emptyPage = await emptyContext.newPage();
  const emptyRuntime = attachRuntimeOracle(emptyPage);
  const unknownOrganisation = '00000000-0000-4000-8000-000000009999';
  await emptyPage.goto(`${ENABLED_WEB}/s-88?organisation=${unknownOrganisation}`, { waitUntil: 'networkidle' });
  await emptyPage.locator('[data-risk-label-state="insufficient"]').waitFor();
  assert('S-88 renders truthful empty/insufficient projection', true, 'insufficient state', 'insufficient state');
  await emptyPage.screenshot({ path: path.join(OUT, 's88-insufficient-390x844-light.png'), fullPage: true });
  assertCleanRuntime('empty/insufficient S-88', emptyRuntime);
  await emptyContext.close();
}

async function countSuppressionAndWithdrawal(browser, fixture, published) {
  const context = await browser.newContext({ viewport: { width: 430, height: 932 } });
  const page = await context.newPage();
  const runtime = attachRuntimeOracle(page);
  await page.goto(`${ENABLED_WEB}/s-88?organisation=${fixture.organisation_id}`, { waitUntil: 'networkidle' });
  const fixtureCard = page.locator(`[data-risk-label-id="${fixture.prepublished_label_id}"]`);
  await fixtureCard.waitFor();
  assert(
    'S-88 suppresses small public count',
    /Count withheld for privacy/.test(await fixtureCard.innerText()),
    'explicit count-withheld copy',
    (await fixtureCard.innerText()).slice(0, 400),
  );
  assertCleanRuntime('count-suppressed S-88', runtime);
  await context.close();

  const safety = await cookieContext(browser, ENABLED_API, PUBLICATION_TOKEN);
  const withdrawn = await safety.request.post(
    `${ENABLED_API}/api/v1/moderation/risk-labels/${fixture.candidate_cluster_id}/publish`,
    {
      headers: { 'Idempotency-Key': 'wave4-risk-label-e2e-withdraw' },
      data: { expected_version: Number(fixture.candidate_version), reason_code: 'administrative_withdrawal', action: 'withdraw' },
    },
  );
  const withdrawnBody = await bodyOf(withdrawn);
  assert(
    'safety officer withdraws the published candidate',
    withdrawn.status() === 200 && withdrawnBody?.status === 'withdrawn' && withdrawnBody?.id === published.id,
    'HTTP 200 withdrawn exact label',
    `HTTP ${withdrawn.status()} status=${withdrawnBody?.status ?? 'missing'} exact=${withdrawnBody?.id === published.id}`,
  );
  await safety.close();

  const publicContext = await browser.newContext();
  const projection = await publicContext.request.get(
    `${ENABLED_API}/api/v1/public/internship-risk-labels/${fixture.organisation_id}`,
  );
  const projectionBody = await bodyOf(projection);
  assert(
    'withdrawn label disappears from public projection',
    projection.status() === 200 && !projectionBody?.labels?.some((item) => item.id === published.id),
    'HTTP 200 without withdrawn label',
    `HTTP ${projection.status()} withdrawn_present=${projectionBody?.labels?.some((item) => item.id === published.id)}`,
  );
  await publicContext.close();
}

async function postPublicationSourceInvalidation(browser, fixture) {
  await invalidatePublishedSource();
  const context = await browser.newContext({ viewport: { width: 430, height: 932 }, colorScheme: 'dark' });
  const response = await context.request.get(
    `${ENABLED_API}/api/v1/public/internship-risk-labels/${fixture.organisation_id}`,
  );
  const rawBody = await response.text();
  assertPublicProjectionPayloadPrivacy(
    'post-invalidation public payload excludes moderation reasons and credentials',
    response,
    rawBody,
  );
  const body = JSON.parse(rawBody);
  assert(
    'post-publication evidence invalidation removes every label derived from the affected source chain',
    Array.isArray(body?.labels) && body.labels.length === 0,
    'HTTP 200 with zero public labels',
    `labels=${Array.isArray(body?.labels) ? body.labels.length : 'missing'}`,
  );
  const page = await context.newPage();
  const runtime = attachRuntimeOracle(page);
  await page.goto(`${ENABLED_WEB}/s-88?organisation=${fixture.organisation_id}`, { waitUntil: 'networkidle' });
  await page.locator('[data-risk-label-state="insufficient"]').waitFor();
  const pageState = await page.evaluate(() => ({
    publicCards: document.querySelectorAll('[data-risk-label-id]').length,
    correctedCopy: document.body.innerText.includes('Approved organisation correction'),
    reasonLeak: /reason(?:_|-)code|verified_factual|qa_(?:target|boundary|policy)/i.test(document.body.innerText),
  }));
  assert(
    'S-88 fails closed after a published source becomes infected',
    pageState.publicCards === 0 && !pageState.correctedCopy && !pageState.reasonLeak,
    'insufficient state; zero cards, corrected copy or moderation reasons',
    JSON.stringify(pageState),
  );
  await page.screenshot({ path: path.join(OUT, 's88-source-invalidated-430x932-dark.png'), fullPage: true });
  assertCleanRuntime('S-88 post-publication source invalidation', runtime);
  await context.close();
}

async function geometryAndA11y(browser, fixture) {
  for (const [width, height] of [[390, 844], [430, 932], [768, 1024], [1024, 768], [1440, 900]]) {
    for (const theme of ['light', 'dark']) {
      for (const screen of ['s88', 's89']) {
        const context = await browser.newContext({ viewport: { width, height }, colorScheme: theme });
        await context.addInitScript((selectedTheme) => localStorage.setItem('ls-theme', selectedTheme), theme);
        const page = await context.newPage();
        const runtime = attachRuntimeOracle(page);
        const target = screen === 's88'
          ? `${ENABLED_WEB}/s-88?organisation=${fixture.organisation_id}`
          : `${ENABLED_WEB}/s-89`;
        await page.goto(target, { waitUntil: 'networkidle' });
        await page.locator(`[data-screen="S-${screen === 's88' ? '88' : '89'}"]`).waitFor();
        if (screen === 's89') await page.locator('[data-risk-label-state="invalid-invitation"]').waitFor();
        const metrics = await page.evaluate(() => {
          const root = document.querySelector('[data-screen="S-88"], [data-screen="S-89"]');
          if (!root) throw new Error('risk-label screen root missing');
          const viewportWidth = document.documentElement.clientWidth;
          const targets = [...root.querySelectorAll('button,a,input,textarea,select,[role="button"]')];
          const tiny = targets.flatMap((node) => {
            const style = getComputedStyle(node);
            const rect = node.getBoundingClientRect();
            if (style.visibility === 'hidden' || style.display === 'none' || rect.width <= 0 || rect.height <= 0) return [];
            return rect.width < 44 || rect.height < 44
              ? [{ name: node.getAttribute('aria-label') || node.textContent?.trim() || node.id, width: rect.width, height: rect.height }]
              : [];
          });
          const outside = [...root.querySelectorAll('*')].flatMap((node) => {
            const rect = node.getBoundingClientRect();
            if (rect.width <= 0 || rect.height <= 0 || (rect.left >= -0.5 && rect.right <= viewportWidth + 0.5)) return [];
            return [{ tag: node.tagName.toLowerCase(), className: String(node.className).slice(0, 80), left: rect.left, right: rect.right }];
          }).slice(0, 12);
          const clipped = [...root.querySelectorAll('*')].flatMap((node) => {
            const rect = node.getBoundingClientRect();
            if (rect.width <= 0 || rect.height <= 0) return [];
            let parent = node.parentElement;
            while (parent && parent !== document.body) {
              const style = getComputedStyle(parent);
              if (/(hidden|clip)/.test(`${style.overflow}${style.overflowX}${style.overflowY}`)) {
                const boundary = parent.getBoundingClientRect();
                if (rect.left < boundary.left - 1 || rect.right > boundary.right + 1 || rect.top < boundary.top - 1 || rect.bottom > boundary.bottom + 1) {
                  return [{ child: node.tagName.toLowerCase(), childClass: String(node.className).slice(0, 80), parentClass: String(parent.className).slice(0, 80) }];
                }
              }
              parent = parent.parentElement;
            }
            return [];
          }).slice(0, 12);
          return {
            overflow: document.documentElement.scrollWidth - viewportWidth,
            tiny, outside, clipped,
            theme: document.documentElement.dataset.theme,
          };
        });
        record(
          `${screen.toUpperCase()} geometry ${width}x${height} ${theme}`,
          '0 overflow/outside/clipped; every target >=44px; requested theme active',
          JSON.stringify(metrics),
          metrics.overflow === 0 && metrics.tiny.length === 0 && metrics.outside.length === 0
            && metrics.clipped.length === 0 && metrics.theme === theme,
        );
        await page.addScriptTag({ content: axe.source });
        const violations = await page.evaluate(async () => {
          const root = document.querySelector('[data-screen="S-88"], [data-screen="S-89"]');
          const result = await globalThis.axe.run(root, {
            runOnly: { type: 'tag', values: ['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa', 'wcag22aa'] },
          });
          return result.violations.map((item) => ({
            id: item.id, impact: item.impact,
            targets: item.nodes.slice(0, 4).map((node) => node.target),
          }));
        });
        record(`${screen.toUpperCase()} axe ${width}x${height} ${theme}`, '0 WCAG A/AA violations', JSON.stringify(violations), violations.length === 0);
        if (screen === 's88') {
          const tooltip = page.getByRole('button', { name: 'How this signal was created' }).first();
          await tooltip.focus();
          assert(`${screen.toUpperCase()} tooltip keyboard focus ${width}x${height} ${theme}`, await tooltip.evaluate((node) => node === document.activeElement), 'tooltip trigger focused', 'focus checked');
          const tooltipPanel = page.getByRole('tooltip').first();
          assert(
            `${screen.toUpperCase()} tooltip visible on focus ${width}x${height} ${theme}`,
            await tooltipPanel.isVisible(),
            'tooltip visible',
            `visible=${await tooltipPanel.isVisible()}`,
          );
          await page.screenshot({ path: path.join(OUT, `${screen}-tooltip-${width}x${height}-${theme}.png`), fullPage: true });
          await tooltip.evaluate((node) => node.blur());
          await tooltipPanel.waitFor({ state: 'hidden' });
          assert(
            `${screen.toUpperCase()} baseline has neutral tooltip state ${width}x${height} ${theme}`,
            !(await tooltipPanel.isVisible()),
            'tooltip hidden before baseline screenshot',
            `visible=${await tooltipPanel.isVisible()}`,
          );
        }
        await page.screenshot({ path: path.join(OUT, `${screen}-${width}x${height}-${theme}.png`), fullPage: true });
        assertCleanRuntime(`${screen.toUpperCase()} ${width}x${height} ${theme}`, runtime);
        await context.close();
      }
    }
  }
}

async function zoomAndReducedMotion(browser, fixture) {
  for (const screen of ['s88', 's89']) {
    const zoomContext = await browser.newContext({ viewport: { width: 384, height: 900 }, colorScheme: 'light' });
    const zoomPage = await zoomContext.newPage();
    const route = screen === 's88'
      ? `${ENABLED_WEB}/s-88?organisation=${fixture.organisation_id}`
      : `${ENABLED_WEB}/s-89`;
    await zoomPage.goto(route, { waitUntil: 'networkidle' });
    await zoomPage.locator(`[data-screen="S-${screen === 's88' ? '88' : '89'}"]`).waitFor();
    if (screen === 's89') await zoomPage.locator('[data-risk-label-state="invalid-invitation"]').waitFor();
    const zoom = await zoomPage.evaluate(() => {
      const root = document.querySelector('[data-screen="S-88"], [data-screen="S-89"]');
      return {
        width: document.documentElement.clientWidth,
        overflow: document.documentElement.scrollWidth - document.documentElement.clientWidth,
        controls: root?.querySelectorAll('button,a,input,textarea,select').length ?? 0,
        text: root?.textContent?.trim().length ?? 0,
        invalidInvitation: Boolean(root?.querySelector('[data-risk-label-state="invalid-invitation"]')),
        invitedForm: Boolean(root?.querySelector('[data-response-state="invited"]')),
      };
    });
    const zoomPass = screen === 's88'
      ? zoom.width === 384 && zoom.overflow === 0 && zoom.controls > 0 && zoom.text > 0
      : zoom.width === 384 && zoom.overflow === 0 && zoom.controls > 0 && zoom.text > 0
        && zoom.invalidInvitation && !zoom.invitedForm;
    record(
      `${screen.toUpperCase()} 200% equivalent reflow`,
      screen === 's88'
        ? '384 CSS px, 0 horizontal overflow, published content and controls retained'
        : '384 CSS px, 0 horizontal overflow, truthful invalid-invitation content and recovery control retained, invited form absent',
      JSON.stringify(zoom),
      zoomPass,
    );
    await zoomContext.close();

    const motionContext = await browser.newContext({
      viewport: { width: 430, height: 844 }, colorScheme: 'light', reducedMotion: 'reduce',
    });
    const motionPage = await motionContext.newPage();
    await motionPage.goto(route, { waitUntil: 'networkidle' });
    await motionPage.locator(`[data-screen="S-${screen === 's88' ? '88' : '89'}"]`).waitFor();
    if (screen === 's89') await motionPage.locator('[data-risk-label-state="invalid-invitation"]').waitFor();
    const motion = await motionPage.evaluate(() => {
      const seconds = (value) => value.split(',').map((item) => {
        const unit = item.trim();
        return unit.endsWith('ms') ? Number.parseFloat(unit) / 1000 : Number.parseFloat(unit) || 0;
      });
      const root = document.querySelector('[data-screen="S-88"], [data-screen="S-89"]');
      const durations = [...(root?.querySelectorAll('*') ?? [])].flatMap((node) => {
        const style = getComputedStyle(node);
        return [...seconds(style.animationDuration), ...seconds(style.transitionDuration)];
      });
      return {
        media: matchMedia('(prefers-reduced-motion: reduce)').matches,
        maxDurationSeconds: Math.max(0, ...durations),
      };
    });
    record(
      `${screen.toUpperCase()} reduced motion`,
      'media=true and max animation/transition duration <=0.00001s',
      JSON.stringify(motion),
      motion.media && motion.maxDurationSeconds <= 0.00001,
    );
    await motionContext.close();
  }
}

requireIsolatedRuntime();
await mkdir(OUT, { recursive: true });
const fixture = JSON.parse(await readFile(FIXTURE_PATH, 'utf8'));
for (const key of ['organisation_id', 'candidate_cluster_id', 'candidate_version', 'prepublished_label_id']) {
  if (fixture[key] === undefined || fixture[key] === null) throw new Error(`fixture ${key} missing`);
}
assert(
  'database target provenance matches the seeded fixture',
  fixture.database_dialect === DATABASE_DIALECT,
  `fixture and runner both declare ${DATABASE_DIALECT}`,
  `fixture=${String(fixture.database_dialect ?? 'missing')} runner=${DATABASE_DIALECT}`,
);

const browser = await chromium.launch({ headless: true });
try {
  await assertDisabledByDefault(browser, fixture);
  await queryTokenMisuse(browser);
  const boundaryResponse = await apiNegativeMatrix(browser);
  await rejectPendingBoundaryResponse(browser, fixture, boundaryResponse);
  const published = await publishCandidate(browser, fixture);
  await activeS89KeyboardCoverage(browser);
  await typedSubmissionConflict(browser);
  await staleCorrectionInvitation(browser);
  await s89Lifecycle(browser, fixture);
  await correctionLifecycle(browser, fixture);
  await retryableAndEmptyStates(browser, fixture);
  await geometryAndA11y(browser, fixture);
  await zoomAndReducedMotion(browser, fixture);
  await countSuppressionAndWithdrawal(browser, fixture, published);
  await postPublicationSourceInvalidation(browser, fixture);
} catch (error) {
  report.failures.push(redact(String(error)));
} finally {
  await browser.close();
}
report.finishedAt = new Date().toISOString();
for (const entry of await readdir(OUT, { withFileTypes: true })) {
  if (!entry.isFile()) continue;
  const data = await readFile(path.join(OUT, entry.name));
  for (const token of TOKENS) {
    if (data.includes(Buffer.from(token))) {
      report.failures.push(`privacy oracle: raw token found in evidence file ${entry.name}`);
    }
  }
}
const sealed = `${JSON.stringify(report, null, 2)}\n`;
for (const token of TOKENS) {
  if (sealed.includes(token)) report.failures.push('privacy oracle: raw token found in evidence payload');
}
await writeFile(path.join(OUT, 'results.json'), `${JSON.stringify(report, null, 2)}\n`);
console.log(JSON.stringify({ rows: report.rows.length, failedCount: report.failures.length }, null, 2));
process.exit(report.failures.length ? 1 : 0);
