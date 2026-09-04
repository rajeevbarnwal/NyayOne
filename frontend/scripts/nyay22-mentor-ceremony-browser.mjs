import { lstat, mkdir, mkdtemp, readFile, rm, writeFile } from 'node:fs/promises';
import { createServer as createHttpServer } from 'node:http';
import { dirname, isAbsolute, join, relative, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { tmpdir } from 'node:os';
import { chromium } from 'playwright';
import { build as buildVite, preview as previewVite } from 'vite';
import {
  assertExactNyay22BrowserInventory,
  canonicalNyay22BrowserFailureCode,
  scanNyay22BrowserEvidence,
} from './lib/nyay22-mentor-ceremony-browser-contract.mjs';

const HOST = '127.0.0.1';
const FRONTEND = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const EVIDENCE_PATH = process.env.NYAY22_BROWSER_EVIDENCE_PATH?.trim() || null;
const FAILURE_PATH = process.env.NYAY22_BROWSER_FAILURE_PATH?.trim() || null;
const LIVE_API_BASE_URL = process.env.NYAY22_LIVE_API_BASE_URL?.trim() || null;
const LIVE_FIXTURE_PATH = process.env.NYAY22_LIVE_FIXTURE_PATH?.trim() || null;
const RUNNER_TEMP = process.env.RUNNER_TEMP?.trim() || null;
const PRODUCTION_BUILD_REQUIRED = process.env.NYAY22_BROWSER_PRODUCTION_BUILD === 'true';
const PREVIEW_PORT = Number.parseInt(process.env.NYAY22_BROWSER_WEB_PORT ?? '0', 10);
const MENTOR_COOKIE = 'nyayone_mentor_session';
let diagnosticStage = 'fixture-start';
const API_PATH = Object.freeze({
  exchange: '/api/v1/auth/mentor/ceremony/exchange',
  verify: '/api/v1/auth/mentor/ceremony/verify',
  session: '/api/v1/auth/mentor/session',
  rotate: '/api/v1/auth/mentor/session/rotate',
  revoke: '/api/v1/auth/mentor/session/revoke',
  studentSession: '/api/v1/auth/student/session',
});

function deferred() {
  let resolvePromise;
  const promise = new Promise((resolveValue) => { resolvePromise = resolveValue; });
  return { promise, resolve: resolvePromise };
}

function verificationProjection() {
  return {
    result: 'current_positive',
    provenanceClass: 'nyayone_reviewed_identity',
    policyVersion: 'mentor-proof.v1',
    verifiedAt: '2026-09-04T10:00:00Z',
    currentAt: '2026-09-04T10:00:00Z',
    ownershipBinding: 'tutor_profile_user_equals_actor',
  };
}

function sessionProjection() {
  return {
    schemaVersion: 'mentor-session.v1',
    sessionClass: 'mentor',
    mentorRole: 'tutor',
    state: 'active',
    purposeCode: 'student_guidance',
    scopes: ['engagement:read', 'session:rotate', 'session:end'],
    permittedProfileSlices: ['display_name', 'preferred_language'],
    sameActorVerified: true,
    tutorProfileStatus: 'active',
    verification: verificationProjection(),
    subjectSharingEligibility: 'allowed',
    consent: {
      purposeCode: 'student_guidance',
      version: 'mentor-consent.v1',
      status: 'granted',
      recordedAt: '2026-09-04T10:00:00Z',
    },
    absoluteLifetimeSeconds: 28_800,
    idleTimeoutSeconds: 1_800,
    issuedAt: '2026-09-04T10:00:00Z',
    expiresAt: '2026-09-04T11:00:00Z',
  };
}

function lifecycleProjection() {
  return {
    schemaVersion: 'mentor-lifecycle.v1',
    action: 'revoked',
    state: 'revoked',
    sessionAuthorityPresent: false,
    auditEventRecorded: true,
    effectiveAt: '2026-09-04T10:30:00Z',
  };
}

function requestCookiePresent(request, expectedGeneration) {
  return String(request.headers.cookie ?? '').split(';').some((part) => (
    part.trim() === `${MENTOR_COOKIE}=generation-${expectedGeneration}`
  ));
}

function createFixtureServer() {
  let webOrigin = null;
  const state = {
    active: false,
    generation: 0,
    holds: new Map(),
    trace: [],
  };

  function armHold(operation) {
    const entered = deferred();
    const released = deferred();
    const hold = { entered, released };
    state.holds.set(operation, hold);
    return {
      entered: entered.promise,
      release: () => released.resolve(),
    };
  }

  async function passHold(operation) {
    const hold = state.holds.get(operation);
    if (!hold) return;
    hold.entered.resolve();
    await hold.released.promise;
    state.holds.delete(operation);
  }

  function corsHeaders() {
    return {
      'Access-Control-Allow-Credentials': 'true',
      'Access-Control-Allow-Headers': 'Content-Type, Idempotency-Key, X-Request-ID',
      'Access-Control-Allow-Methods': 'DELETE, GET, OPTIONS, POST',
      'Access-Control-Allow-Origin': webOrigin,
      'Cache-Control': 'private, no-store',
      'Content-Type': 'application/json; charset=utf-8',
      Vary: 'Cookie, Origin',
      'X-Content-Type-Options': 'nosniff',
    };
  }

  function send(response, status, body, extraHeaders = {}) {
    response.writeHead(status, { ...corsHeaders(), ...extraHeaders });
    response.end(JSON.stringify(body));
  }

  function deny(response) {
    send(response, 401, {
      detail: {
        code: 'AUTHENTICATION_REQUIRED',
        message: 'Request failed',
        retryable: false,
      },
    });
  }

  const server = createHttpServer(async (request, response) => {
    const requestUrl = new URL(request.url ?? '/', `http://${HOST}`);
    const method = request.method ?? 'GET';
    if (method === 'OPTIONS') {
      response.writeHead(204, corsHeaders());
      response.end();
      return;
    }

    const idempotencyPresent = typeof request.headers['idempotency-key'] === 'string'
      && /^[A-Za-z0-9._~-]{16,200}$/u.test(request.headers['idempotency-key']);
    const originAccepted = request.headers.origin === webOrigin;
    state.trace.push({
      method,
      path: requestUrl.pathname,
      canonical: requestUrl.search === '' && requestUrl.hash === '',
      originAccepted,
      idempotencyPresent,
      selectorHeadersAbsent: !Object.keys(request.headers).some((name) => (
        /(?:actor|owner|mentor|profile|session|token|subject)/iu.test(name)
      )),
    });

    if (method === 'GET' && requestUrl.pathname === API_PATH.studentSession) {
      send(response, 200, { authenticated: false, actor: null });
      return;
    }
    if (method === 'GET' && requestUrl.pathname === API_PATH.session) {
      if (!state.active || !requestCookiePresent(request, state.generation)) {
        deny(response);
        return;
      }
      send(response, 200, sessionProjection());
      return;
    }

    const operation = requestUrl.pathname === API_PATH.exchange ? 'exchange'
      : requestUrl.pathname === API_PATH.rotate ? 'rotate'
        : requestUrl.pathname === API_PATH.revoke ? 'revoke'
          : null;
    if (method !== 'POST' || operation === null || !originAccepted || !idempotencyPresent) {
      send(response, 422, {
        detail: { code: 'INVALID_REQUEST', message: 'Request failed', retryable: false },
      });
      return;
    }

    await passHold(operation);
    if (operation === 'exchange') {
      state.active = true;
      state.generation += 1;
      send(response, 201, sessionProjection(), {
        'Set-Cookie': `${MENTOR_COOKIE}=generation-${state.generation}; Path=/; HttpOnly; SameSite=Lax`,
      });
      return;
    }
    if (!state.active || !requestCookiePresent(request, state.generation)) {
      deny(response);
      return;
    }
    if (operation === 'rotate') {
      state.generation += 1;
      send(response, 200, sessionProjection(), {
        'Set-Cookie': `${MENTOR_COOKIE}=generation-${state.generation}; Path=/; HttpOnly; SameSite=Lax`,
      });
      return;
    }
    state.active = false;
    send(response, 200, lifecycleProjection(), {
      'Set-Cookie': `${MENTOR_COOKIE}=; Path=/; HttpOnly; SameSite=Lax; Max-Age=0`,
    });
  });

  return {
    server,
    state,
    armHold,
    setWebOrigin: (value) => { webOrigin = value; },
  };
}

function listen(server) {
  return new Promise((resolveListen, rejectListen) => {
    server.once('error', rejectListen);
    server.listen(0, HOST, () => {
      server.off('error', rejectListen);
      const address = server.address();
      if (!address || typeof address === 'string') {
        rejectListen(new Error('NYAY22_FIXTURE_ADDRESS_INVALID'));
        return;
      }
      resolveListen(address.port);
    });
  });
}

function closeServer(server) {
  return new Promise((resolveClose) => server.close(() => resolveClose()));
}

async function startProductionHarness(apiBase, { port = 0, sameOriginProxy = false } = {}) {
  const previousApiBase = process.env.VITE_API_BASE_URL;
  const outputRoot = await mkdtemp(join(tmpdir(), 'nyay22-production-browser-'));
  process.env.VITE_API_BASE_URL = sameOriginProxy ? '' : apiBase;
  try {
    await buildVite({
      configFile: resolve(FRONTEND, 'vite.config.ts'),
      root: FRONTEND,
      logLevel: 'silent',
      build: {
        outDir: outputRoot,
        emptyOutDir: true,
        rollupOptions: {
          input: resolve(FRONTEND, 'scripts/fixtures/nyay22-browser-harness.html'),
        },
      },
    });
    const vite = await previewVite({
      configFile: false,
      root: FRONTEND,
      build: { outDir: outputRoot },
      logLevel: 'silent',
      preview: {
        host: HOST,
        port,
        strictPort: port > 0,
        proxy: sameOriginProxy ? {
          '/api': {
            target: apiBase,
            changeOrigin: false,
          },
        } : undefined,
      },
    });
    const localUrl = vite.resolvedUrls?.local[0];
    if (!localUrl) {
      vite.httpServer.close();
      await rm(outputRoot, { recursive: true, force: true });
      throw new Error('NYAY22_PRODUCTION_PREVIEW_START_FAILED');
    }
    return {
      close: async () => {
        await new Promise((resolveClose) => vite.httpServer.close(resolveClose));
        await rm(outputRoot, { recursive: true, force: true });
      },
      webOrigin: new URL(localUrl).origin,
    };
  } catch (error) {
    await rm(outputRoot, { recursive: true, force: true });
    throw error;
  } finally {
    if (previousApiBase === undefined) delete process.env.VITE_API_BASE_URL;
    else process.env.VITE_API_BASE_URL = previousApiBase;
  }
}

async function readPrivateLiveFixture() {
  if (!LIVE_FIXTURE_PATH || !RUNNER_TEMP) {
    throw new Error('NYAY22_LIVE_FIXTURE_REQUIRED');
  }
  const root = resolve(RUNNER_TEMP);
  const target = resolve(LIVE_FIXTURE_PATH);
  const child = relative(root, target);
  if (!child || child.startsWith('..') || isAbsolute(child)) {
    throw new Error('NYAY22_LIVE_FIXTURE_INVALID');
  }
  let raw;
  try {
    const metadata = await lstat(target);
    if (!metadata.isFile() || metadata.isSymbolicLink() || (metadata.mode & 0o777) !== 0o600) {
      throw new Error('NYAY22_LIVE_FIXTURE_INVALID');
    }
    raw = await readFile(target, 'utf8');
  } finally {
    await rm(target, { force: true });
  }
  let fixture;
  try {
    fixture = JSON.parse(raw);
  } catch {
    throw new Error('NYAY22_LIVE_FIXTURE_INVALID');
  }
  if (!fixture || typeof fixture !== 'object' || Array.isArray(fixture)
    || Object.keys(fixture).sort().join(',') !== 'ceremonyCookie,schemaVersion'
    || fixture.schemaVersion !== 'nyay22-live-browser-fixture.v1'
    || typeof fixture.ceremonyCookie !== 'string'
    || !/^[0-9a-f]{64}$/u.test(fixture.ceremonyCookie)) {
    throw new Error('NYAY22_LIVE_FIXTURE_INVALID');
  }
  return fixture;
}

function validApiOrigin(value) {
  try {
    const parsed = new URL(value);
    return parsed.origin === value && parsed.protocol === 'http:' && parsed.hostname === HOST;
  } catch {
    return false;
  }
}

async function runLiveBackendLifecycle(browser) {
  if (!PRODUCTION_BUILD_REQUIRED) {
    return { required: true, bound: false, code: 'NYAY22_PRODUCTION_BINDING_REQUIRED' };
  }
  if (!LIVE_API_BASE_URL || !validApiOrigin(LIVE_API_BASE_URL)) {
    throw new Error('NYAY22_LIVE_BACKEND_ORIGIN_INVALID');
  }
  diagnosticStage = 'live-fixture-consume';
  const privateFixture = await readPrivateLiveFixture();
  diagnosticStage = 'live-production-build';
  const liveHarness = await startProductionHarness(LIVE_API_BASE_URL, {
    port: PREVIEW_PORT,
    sameOriginProxy: true,
  });
  const context = await browser.newContext();
  try {
    await context.addCookies([{
      name: 'nyayone_mentor_ceremony',
      value: privateFixture.ceremonyCookie,
      domain: HOST,
      path: '/api/v1/auth/mentor',
      httpOnly: true,
      sameSite: 'Strict',
      secure: false,
    }]);
    diagnosticStage = 'live-harness-ready';
    const { page, readiness } = await openHarness(context, liveHarness.webOrigin);
    diagnosticStage = 'live-verify';
    const verified = await page.evaluate(() => globalThis.nyay22Harness.verify());
    diagnosticStage = 'live-exchange';
    const exchanged = await page.evaluate(() => globalThis.nyay22Harness.exchange());
    const mountedAfterExchange = await page.evaluate(
      () => globalThis.nyay22Harness.privateMount(),
    );
    const exchangeCookies = await context.cookies(liveHarness.webOrigin);
    const exchangedCookie = exchangeCookies.find((item) => item.name === MENTOR_COOKIE);
    const cookieContract = Boolean(
      exchangedCookie
      && exchangedCookie.domain === HOST
      && exchangedCookie.path === '/'
      && exchangedCookie.httpOnly === true
      && exchangedCookie.sameSite === 'Lax'
      && exchangedCookie.secure === false,
    );
    diagnosticStage = 'live-rotate';
    const rotated = await page.evaluate(() => globalThis.nyay22Harness.rotate());
    const mountedAfterRotate = await page.evaluate(
      () => globalThis.nyay22Harness.privateMount(),
    );
    diagnosticStage = 'live-revoke';
    const revoked = await page.evaluate(() => globalThis.nyay22Harness.revoke());
    const deniedAfterRevoke = await page.evaluate(
      () => globalThis.nyay22Harness.privateMount(),
    );
    const finalSession = await page.evaluate(async () => {
      const response = await fetch('/api/v1/auth/mentor/session', {
        credentials: 'include',
        method: 'GET',
      });
      await response.arrayBuffer();
      return {
        status: response.status,
        noStore: response.headers.get('cache-control') === 'private, no-store',
      };
    });
    const finalCookies = await context.cookies(liveHarness.webOrigin);
    const retired = !finalCookies.some((item) => item.name === MENTOR_COOKIE);
    const bound = readiness.available === true
      && verified.schema === 'mentor-acceptance.v1'
      && verified.status === 'acceptance_required'
      && verified.state === 'proof_verified'
      && verified.session === 'absent'
      && exchanged.schema === 'mentor-session.v1'
      && exchanged.state === 'active'
      && mountedAfterExchange.mounted === true
      && mountedAfterExchange.state === 'active'
      && cookieContract
      && rotated.schema === 'mentor-session.v1'
      && rotated.state === 'active'
      && mountedAfterRotate.mounted === true
      && mountedAfterRotate.state === 'active'
      && revoked.action === 'revoked'
      && revoked.state === 'absent'
      && deniedAfterRevoke.mounted === false
      && deniedAfterRevoke.code === 'MENTOR_SESSION_REQUIRED'
      && finalSession.status === 401
      && finalSession.noStore
      && retired;
    return {
      required: true,
      bound,
      verify: verified.state,
      verifySession: verified.session,
      exchange: exchanged.state,
      exchangeMount: mountedAfterExchange.mounted,
      cookieAttributes: cookieContract ? 'contract-match' : 'contract-mismatch',
      rotate: rotated.state,
      rotateMount: mountedAfterRotate.mounted,
      revoke: revoked.action,
      finalMount: deniedAfterRevoke.mounted ? 'unexpected' : 'denied',
      finalSession: finalSession.status,
      retired,
    };
  } finally {
    await context.close();
    await liveHarness.close();
  }
}

async function openHarness(context, webOrigin) {
  const page = await context.newPage();
  await page.goto(`${webOrigin}/scripts/fixtures/nyay22-browser-harness.html`, {
    waitUntil: 'domcontentloaded',
  });
  await page.waitForSelector('body[data-harness-ready="true"]', { state: 'attached' });
  const readiness = await page.evaluate(() => globalThis.nyay22Harness.ready());
  return { page, readiness };
}

async function status(page) {
  return page.evaluate(() => globalThis.nyay22Harness.status());
}

async function waitForTransitionCount(page, kind, previous) {
  await page.waitForFunction(
    ({ transitionKind, prior }) => globalThis.nyay22Harness.status()[transitionKind] > prior,
    { transitionKind: kind, prior: previous },
  );
}

async function unsupportedBoundary(browser, webOrigin, script) {
  const context = await browser.newContext();
  await context.addInitScript(script);
  const requests = [];
  const { page, readiness } = await openHarness(context, webOrigin);
  page.on('request', (request) => {
    if (new URL(request.url()).pathname === API_PATH.session) requests.push('mentor-session');
  });
  const result = await page.evaluate(() => globalThis.nyay22Harness.privateMount());
  const observed = await status(page);
  await context.close();
  return {
    available: readiness.available,
    mounted: result.mounted,
    unavailable: observed.unavailable,
    mentorRequests: requests.length,
  };
}

async function run() {
  const fixture = createFixtureServer();
  let productionHarness = null;
  let browser;
  try {
    diagnosticStage = 'fixture-listen';
    const apiPort = await listen(fixture.server);
    diagnosticStage = 'production-build';
    const startedVite = await startProductionHarness(`http://${HOST}:${apiPort}`);
    productionHarness = startedVite;
    const { webOrigin } = startedVite;
    fixture.setWebOrigin(webOrigin);
    diagnosticStage = 'vite-readiness';
    diagnosticStage = 'chromium-launch';
    browser = await chromium.launch({ headless: true });
    diagnosticStage = 'live-backend-positive-lifecycle';
    const liveLifecycle = await runLiveBackendLifecycle(browser);
    const context = await browser.newContext();
    diagnosticStage = 'primary-harness';
    const { page, readiness } = await openHarness(context, webOrigin);
    diagnosticStage = 'peer-create';
    const peerPage = await context.newPage();
    diagnosticStage = 'peer-navigation';
    await peerPage.goto(`${webOrigin}/scripts/fixtures/nyay22-browser-harness.html`, {
      waitUntil: 'domcontentloaded',
    });
    diagnosticStage = 'peer-module-ready';
    await peerPage.waitForSelector('body[data-harness-ready="true"]', { state: 'attached' });
    diagnosticStage = 'peer-lock-ready';
    const peerReadiness = await peerPage.evaluate(() => globalThis.nyay22Harness.ready());

    diagnosticStage = 'exchange-linearization';
    const beforeExchange = await status(peerPage);
    const exchangeHold = fixture.armHold('exchange');
    const exchangeRun = page.evaluate(() => globalThis.nyay22Harness.exchange());
    await exchangeHold.entered;
    await waitForTransitionCount(peerPage, 'starts', beforeExchange.starts);
    const exchangeDenied = await peerPage.evaluate(() => globalThis.nyay22Harness.privateMount());
    exchangeHold.release();
    const exchangeResult = await exchangeRun;
    await waitForTransitionCount(peerPage, 'ends', beforeExchange.ends);
    const afterExchange = await status(peerPage);
    const mountedAfterExchange = await peerPage.evaluate(
      () => globalThis.nyay22Harness.privateMount(),
    );

    const cookiesAfterExchange = await context.cookies();
    const mentorCookie = cookiesAfterExchange.find((cookie) => cookie.name === MENTOR_COOKIE);
    const cookieAttributesValid = Boolean(
      mentorCookie
      && mentorCookie.domain === HOST
      && mentorCookie.path === '/'
      && mentorCookie.httpOnly
      && mentorCookie.sameSite === 'Lax'
      && mentorCookie.secure === false,
    );

    diagnosticStage = 'rotation-linearization';
    const beforeRotate = await status(peerPage);
    const rotateHold = fixture.armHold('rotate');
    const rotateRun = page.evaluate(() => globalThis.nyay22Harness.rotate());
    await rotateHold.entered;
    await waitForTransitionCount(peerPage, 'starts', beforeRotate.starts);
    const rotateDenied = await peerPage.evaluate(() => globalThis.nyay22Harness.privateMount());
    rotateHold.release();
    const rotateResult = await rotateRun;
    await waitForTransitionCount(peerPage, 'ends', beforeRotate.ends);
    const afterRotate = await status(peerPage);
    const mountedAfterRotate = await peerPage.evaluate(
      () => globalThis.nyay22Harness.privateMount(),
    );

    diagnosticStage = 'revocation-linearization';
    const beforeRevoke = await status(peerPage);
    const revokeHold = fixture.armHold('revoke');
    const revokeRun = page.evaluate(() => globalThis.nyay22Harness.revoke());
    await revokeHold.entered;
    await waitForTransitionCount(peerPage, 'starts', beforeRevoke.starts);
    const revokeDenied = await peerPage.evaluate(() => globalThis.nyay22Harness.privateMount());
    revokeHold.release();
    const revokeResult = await revokeRun;
    await waitForTransitionCount(peerPage, 'ends', beforeRevoke.ends);
    const afterRevoke = await status(peerPage);
    const deniedAfterRevoke = await peerPage.evaluate(
      () => globalThis.nyay22Harness.privateMount(),
    );
    const cookiesAfterRevoke = await context.cookies();

    await peerPage.evaluate(() => {
      globalThis.postMessage({ sessionClass: 'mentor', state: 'active' }, globalThis.origin);
    });
    const deniedAfterMessage = await peerPage.evaluate(
      () => globalThis.nyay22Harness.privateMount(),
    );
    const peerFinal = await status(peerPage);
    const storage = await peerPage.evaluate(() => ({
      local: Object.keys(globalThis.localStorage).length,
      sessionEntries: Object.keys(globalThis.sessionStorage).length,
    }));

    diagnosticStage = 'unsupported-capabilities';
    const unsupportedLocks = await unsupportedBoundary(browser, webOrigin, () => {
      Object.defineProperty(globalThis.navigator, 'locks', {
        configurable: true,
        get: () => undefined,
      });
    });
    const unsupportedChannel = await unsupportedBoundary(browser, webOrigin, () => {
      Object.defineProperty(globalThis, 'BroadcastChannel', {
        configurable: true,
        value: undefined,
      });
    });

    const mentorAuthSource = await readFile(
      resolve(FRONTEND, 'src/features/mentor/lib/mentorAuth.ts'),
      'utf8',
    );
    const m01AdminOnly = /roles\.includes\(['"]admin['"]\)/u.test(mentorAuthSource)
      && !/roles\.includes\(['"](?:tutor|lawyer)['"]\)/u.test(mentorAuthSource);

    const mutationTrace = fixture.state.trace.filter((item) => (
      [API_PATH.exchange, API_PATH.rotate, API_PATH.revoke].includes(item.path)
    ));
    const canonicalTrace = fixture.state.trace.every((item) => (
      Object.values(API_PATH).includes(item.path)
      && item.canonical
      && item.selectorHeadersAbsent
    )) && mutationTrace.length === 3
      && mutationTrace.every((item) => item.originAccepted && item.idempotencyPresent);

    diagnosticStage = 'evidence-seal';
    const transitionDenied = (result) => result.mounted === false
      && result.code === 'student_auth_transition_active';
    const unsupportedDenied = (result) => result.available === false
      && result.mounted === false
      && result.unavailable > 0
      && result.mentorRequests === 0;
    const rows = [
      {
        name: 'runtime-chromium',
        expected: 'production-built real Chromium and both coordination primitives',
        actual: {
          engine: 'chromium',
          productionBuild: true,
          locks: readiness.available,
          peer: peerReadiness.available,
        },
        pass: readiness.available === true
          && peerReadiness.available === true,
      },
      {
        name: 'live-backend-positive-lifecycle',
        expected: 'shipped client verifies, exchanges, mounts, rotates, revokes, then observes canonical 401 against live 0023 backend',
        actual: liveLifecycle,
        pass: liveLifecycle.required === true && liveLifecycle.bound === true,
      },
      {
        name: 'canonical-request-trace',
        expected: 'exact paths, no selectors, and browser Origin plus opaque key on mutations',
        actual: { canonical: canonicalTrace, mutations: mutationTrace.length },
        pass: canonicalTrace,
      },
      {
        name: 'mentor-cookie-attributes',
        expected: 'host-only HttpOnly SameSite=Lax Path=/ and retired on revoke',
        actual: {
          attributes: cookieAttributesValid ? 'contract-match' : 'contract-mismatch',
          retired: !cookiesAfterRevoke.some((cookie) => cookie.name === MENTOR_COOKIE),
        },
        pass: cookieAttributesValid
          && !cookiesAfterRevoke.some((cookie) => cookie.name === MENTOR_COOKIE),
      },
      {
        name: 'cross-tab-exchange-linearized',
        expected: 'peer private mount denied during exchange and transition settles once',
        actual: {
          denied: transitionDenied(exchangeDenied),
          state: exchangeResult.state,
          startDelta: afterExchange.starts - beforeExchange.starts,
          endDelta: afterExchange.ends - beforeExchange.ends,
        },
        pass: transitionDenied(exchangeDenied)
          && exchangeResult.state === 'active'
          && afterExchange.starts - beforeExchange.starts === 1
          && afterExchange.ends - beforeExchange.ends === 1,
      },
      {
        name: 'private-mount-after-canonical-session',
        expected: 'private mount occurs only after canonical session projection is active',
        actual: { mounted: mountedAfterExchange.mounted, state: mountedAfterExchange.state },
        pass: mountedAfterExchange.mounted === true && mountedAfterExchange.state === 'active',
      },
      {
        name: 'cross-tab-rotation-linearized',
        expected: 'peer denied during rotation and active projection rediscovered afterward',
        actual: {
          denied: transitionDenied(rotateDenied),
          state: rotateResult.state,
          remounted: mountedAfterRotate.mounted,
          startDelta: afterRotate.starts - beforeRotate.starts,
          endDelta: afterRotate.ends - beforeRotate.ends,
        },
        pass: transitionDenied(rotateDenied)
          && rotateResult.state === 'active'
          && mountedAfterRotate.mounted === true
          && afterRotate.starts - beforeRotate.starts === 1
          && afterRotate.ends - beforeRotate.ends === 1,
      },
      {
        name: 'cross-tab-revocation-linearized',
        expected: 'peer denied during revocation and remains denied after authoritative absence',
        actual: {
          during: transitionDenied(revokeDenied),
          action: revokeResult.action,
          after: deniedAfterRevoke.mounted,
          startDelta: afterRevoke.starts - beforeRevoke.starts,
          endDelta: afterRevoke.ends - beforeRevoke.ends,
        },
        pass: transitionDenied(revokeDenied)
          && revokeResult.action === 'revoked'
          && deniedAfterRevoke.mounted === false
          && afterRevoke.starts - beforeRevoke.starts === 1
          && afterRevoke.ends - beforeRevoke.ends === 1,
      },
      {
        name: 'unsupported-web-locks-denies-private-mount',
        expected: 'no private mount and no mentor request without Web Locks',
        actual: unsupportedLocks,
        pass: unsupportedDenied(unsupportedLocks),
      },
      {
        name: 'unsupported-broadcast-channel-denies-private-mount',
        expected: 'no private mount and no mentor request without BroadcastChannel',
        actual: unsupportedChannel,
        pass: unsupportedDenied(unsupportedChannel),
      },
      {
        name: 'postmessage-no-authority',
        expected: 'forged message creates no mentor authority or private mount',
        actual: { mounted: deniedAfterMessage.mounted, privateMounts: peerFinal.privateMounts },
        pass: deniedAfterMessage.mounted === false && peerFinal.privateMounts === 2,
      },
      {
        name: 'browser-storage-authority-free',
        expected: 'no localStorage or sessionStorage mentor authority',
        actual: storage,
        pass: storage.local === 0 && storage.sessionEntries === 0,
      },
      {
        name: 'm01-admin-only-preserved',
        expected: 'M-01 remains admin-only and receives no tutor or lawyer-session control',
        actual: { adminOnly: m01AdminOnly },
        pass: m01AdminOnly,
      },
      {
        name: 'evidence-privacy',
        expected: 'all emitted diagnostics are PII, credential, and authority free',
        actual: { verdict: 'pending-final-scan' },
        pass: true,
      },
    ];

    const preliminaryScan = scanNyay22BrowserEvidence(rows.slice(0, -1));
    rows.at(-1).actual = { verdict: preliminaryScan.code };
    rows.at(-1).pass = preliminaryScan.pass;
    const summary = assertExactNyay22BrowserInventory(rows);
    const result = {
      schemaVersion: 'nyay22-browser-evidence.v1',
      rows,
      summary,
      authorityModel: 'withServerProvenMentorSession',
    };
    if (scanNyay22BrowserEvidence(result).pass !== true) {
      throw new Error('NYAY22_FINAL_EVIDENCE_PRIVATE');
    }
    if (EVIDENCE_PATH) {
      await mkdir(dirname(EVIDENCE_PATH), { recursive: true });
      await writeFile(EVIDENCE_PATH, `${JSON.stringify(result, null, 2)}\n`);
    }
    process.stdout.write(`${JSON.stringify(result, null, 2)}\n`);
    if (summary.failed > 0) process.exitCode = 1;
    await context.close();
  } finally {
    if (browser) await browser.close();
    if (productionHarness) await productionHarness.close();
    if (fixture.server.listening) await closeServer(fixture.server);
  }
}

run().catch(async (error) => {
  const failure = {
    schemaVersion: 'nyay22-browser-failure.v1',
    stage: diagnosticStage,
    code: canonicalNyay22BrowserFailureCode(error),
  };
  if (scanNyay22BrowserEvidence(failure).pass !== true) {
    failure.stage = 'diagnostic-redacted';
    failure.code = 'NYAY22_BROWSER_FAILURE';
  }
  if (FAILURE_PATH) {
    await mkdir(dirname(FAILURE_PATH), { recursive: true });
    await writeFile(FAILURE_PATH, `${JSON.stringify(failure, null, 2)}\n`);
  }
  process.stderr.write(`${JSON.stringify(failure)}\n`);
  process.exitCode = 1;
});
