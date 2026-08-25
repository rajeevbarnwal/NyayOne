import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { describe, expect, it } from 'vitest';
import {
  NYAY19_ABORT_EXCEPTION_CLASS_INVENTORY,
  NYAY19_ABORT_STAGE_INVENTORY,
  NYAY19_ASSERTION_INVENTORY,
  NYAY19_MUTATION_TRACE,
  NYAY19_SEEDED_MUTANT_INVENTORY,
  buildNyay19AbortEnvelope,
  assertExactAssertionInventory,
  hasExactAuthenticatedStudentSession,
  hasExactAuthenticationRequired,
  hasExactOrderedMutationTrace,
  hasExactProtectedAuthorityChannel,
  hasExactSingleOrigin,
  hasFutureCookieExpiry,
  inspectAuthorityCookieInventory,
  inspectCaptureFinality,
  inspectCookieRetirementHeaders,
  inspectCookieTransitionHeaders,
  inspectExactOrderedMutationTrace,
  inspectIndependentProtectedProbes,
  inspectNyay19SessionBootstrap,
  inspectStudentContextBoundary,
  nextNyay19LoginIssuanceDelay,
  parseNyay19OtpCooldown,
  parseNyay19OtpFlowTtl,
  parseNyay19SessionTtl,
  scanNyay19Evidence,
  snapshotNyay19MutationRequest,
  summarizeNyay19Rows,
} from './nyay19-auth-lifecycle-runner-contract.mjs';

const WEB_ORIGIN = 'http://127.0.0.1:4179';
const API = 'http://127.0.0.1:1139';
const SESSION_COOKIE = 'nyayone_session';
const FLOW_COOKIE = 'nyayone_otp_flow';
const OPAQUE = 'opaque-cookie-value-that-is-longer-than-thirty-two';
const STANDARD_BASE64 = 'b7gBSpPcJW63AEmS2yRttv9IkdojbLX+R5DZImu0/UY=';
const STANDARD_BASE64_UNPADDED = STANDARD_BASE64.replace(/=+$/u, '');

const requestWith = ({
  path,
  body,
  method = 'POST',
  headers = [{ name: 'Origin', value: WEB_ORIGIN }],
  bodyFailure = false,
  origin = API,
  query = '',
}) => ({
  method: () => method,
  url: () => `${origin}${path}${query}`,
  headersArray: async () => headers,
  postDataJSON: () => {
    if (bodyFailure) throw new Error('planted unreadable body');
    return body;
  },
});

const REQUEST_ID = '0123456789abcdef0123456789abcdef';

const denialResponse = ({ status = 401, headers } = {}) => ({
  status: () => status,
  headersArray: async () => headers ?? [{ name: 'X-Request-ID', value: REQUEST_ID }],
});

const denialBody = (overrides = {}) => ({
  detail: { code: 'authentication_required', message: 'Request failed' },
  request_id: REQUEST_ID,
  ...overrides,
});

const actor = () => ({
  sub: '123e4567-e89b-42d3-a456-426614174000',
  roles: ['student'],
  student_profile_id: '123e4567-e89b-42d3-a456-426614174001',
  student_verification: 'verified',
  is_minor: false,
  consent_state: ['privacy', 'terms'],
});

const authenticatedSession = (rawActor = actor()) => ({
  authenticated: true,
  actor: rawActor,
});

const ambientRequest = (raw = OPAQUE, overrides = {}) => requestWith({
  method: 'GET',
  path: '/api/v1/student/profile',
  body: undefined,
  headers: [{ name: 'Cookie', value: `${SESSION_COOKIE}=${raw}` }],
  ...overrides,
});

const bearerRequest = (raw = OPAQUE, overrides = {}) => requestWith({
  method: 'GET',
  path: '/api/v1/student/profile',
  body: undefined,
  headers: [{ name: 'Authorization', value: `Bearer ${raw}` }],
  ...overrides,
});

function bodyFor(shape) {
  if (shape === 'mobile') return { mobile: '8765432109' };
  if (shape === 'code') return { code: '135790' };
  if (shape === 'confirmation') return { confirmation: 'DELETE' };
  return {};
}

function validTrace() {
  return NYAY19_MUTATION_TRACE.map((entry) => ({
    request: requestWith({ path: entry.path, body: bodyFor(entry.body) }),
  }));
}

const validRows = () => NYAY19_ASSERTION_INVENTORY.map((name) => ({
  name,
  expected: 'aggregate contract',
  actual: { exact: true },
  pass: true,
}));

const cookiePolicy = (name, scope = 'current') => name === SESSION_COOKIE
  ? (scope === 'legacy'
    ? { path: '/api/v1', sameSite: 'Strict' }
    : { path: '/', sameSite: 'Lax' })
  : { path: '/api/v1', sameSite: 'Strict' };

const validCookie = (name, overrides = {}) => ({
  name,
  value: OPAQUE,
  domain: '127.0.0.1',
  path: cookiePolicy(name).path,
  httpOnly: true,
  secure: false,
  sameSite: cookiePolicy(name).sameSite,
  ...overrides,
});

const retirement = (name, suffix = '', scope = 'current') => {
  const policy = cookiePolicy(name, scope);
  return {
    name: 'Set-Cookie',
    value: `${name}=""; expires=Thu, 01 Jan 1970 00:00:00 GMT; HttpOnly; Max-Age=0; Path=${policy.path}; SameSite=${policy.sameSite.toLowerCase()}${suffix}`,
  };
};

const verifyTransition = () => ({
  headers: [
    retirement(SESSION_COOKIE, '', 'legacy'),
    issuance(SESSION_COOKIE, 20),
    retirement(FLOW_COOKIE),
  ],
  expected: [
    { name: SESSION_COOKIE, action: 'retire', scope: 'legacy' },
    { name: SESSION_COOKIE, action: 'issue', maxAge: 20 },
    { name: FLOW_COOKIE, action: 'retire' },
  ],
});

const authOnlyRetirement = () => ({
  headers: [
    retirement(SESSION_COOKIE),
    retirement(SESSION_COOKIE, '', 'legacy'),
  ],
  expected: [
    { name: SESSION_COOKIE, action: 'retire' },
    { name: SESSION_COOKIE, action: 'retire', scope: 'legacy' },
  ],
});

const completeRetirement = () => ({
  headers: [
    retirement(SESSION_COOKIE),
    retirement(SESSION_COOKIE, '', 'legacy'),
    retirement(FLOW_COOKIE),
  ],
  expected: [
    { name: SESSION_COOKIE, action: 'retire' },
    { name: SESSION_COOKIE, action: 'retire', scope: 'legacy' },
    { name: FLOW_COOKIE, action: 'retire' },
  ],
});

const issuance = (name, maxAge, suffix = '') => {
  const policy = cookiePolicy(name);
  return {
    name: 'Set-Cookie',
    value: `${name}=${OPAQUE}; HttpOnly; Max-Age=${maxAge}; Path=${policy.path}; SameSite=${policy.sameSite.toLowerCase()}${suffix}`,
  };
};

const contextBefore = () => ({
  managedExpectedCount: 15,
  managedPresentCount: 15,
  retiredActorRegistryAbsent: true,
  registrationAttemptPresent: true,
  profileDraftPresent: true,
  queryCacheCount: 2,
  mutationCacheCount: 1,
  controls: {
    theme: 'dark',
    retiredLocale: 'hi',
    retiredReviewer: '1',
    retiredOnboardingSeen: 'seen',
    unrelated: 'retain',
  },
});

const contextAfter = () => ({
  managedExpectedCount: 15,
  managedPresentCount: 0,
  retiredActorRegistryAbsent: true,
  registrationAttemptPresent: false,
  profileDraftPresent: false,
  queryCacheCount: 0,
  mutationCacheCount: 0,
  controls: {
    theme: 'dark',
    retiredLocale: null,
    retiredReviewer: null,
    retiredOnboardingSeen: null,
    unrelated: 'retain',
  },
});

function assertRunnerWiring(source) {
  if (!/summarizeNyay19Rows[\s\S]*from ['"]\.\/lib\/nyay19-auth-lifecycle-runner-contract\.mjs['"]/.test(source)) {
    throw new Error('NYAY19_RUNNER_CONTRACT_IMPORT_MISSING');
  }
  if (!/const summary = summarizeNyay19Rows\(rows\);/.test(source)) {
    throw new Error('NYAY19_RUNNER_SUMMARY_MISSING');
  }
  if (!/if \(summary\.failed > 0\) process\.exitCode = 1;/.test(source)) {
    throw new Error('NYAY19_RUNNER_FAILURE_EXIT_MISSING');
  }
  const exactRegistrationWire = `        data: {
          first_name: 'Nyay',
          middle_name: null,
          last_name: 'Lifecycle',
          mobile,
          dob: '2004-03-14',
          terms_accepted: true,
          terms_version: 'dpdp-2023.v1',
          privacy_notice_acknowledged: true,
          privacy_notice_version: 'dpdp-2023.v1',
        },`;
  if (!source.includes(exactRegistrationWire)) {
    throw new Error('NYAY19_RUNNER_REGISTRATION_WIRE_MISMATCH');
  }
  if (!/setup\.registrationHttp === 202/.test(source)) {
    throw new Error('NYAY19_RUNNER_REGISTRATION_STATUS_MISMATCH');
  }
  if (/\bconsent:\s*\{\s*accepted:/u.test(source) || /setup\.registrationHttp === 201/u.test(source)) {
    throw new Error('NYAY19_RUNNER_OBSOLETE_REGISTRATION_CONTRACT');
  }
  if (/getByRole\(['"]button['"], \{ name: ['"]Use a one time code['"] \}\)\.click\(\)/u.test(source)) {
    throw new Error('NYAY19_RUNNER_OBSOLETE_LOGIN_MODE_TOGGLE');
  }
  const exactDualPathDescriptors = `const ROOT_SESSION_RETIREMENT = Object.freeze({
  name: SESSION_COOKIE, action: 'retire',
});
const LEGACY_SESSION_RETIREMENT = Object.freeze({
  name: SESSION_COOKIE, action: 'retire', scope: 'legacy',
});
const FLOW_RETIREMENT = Object.freeze({
  name: FLOW_COOKIE, action: 'retire',
});
const AUTH_ONLY_SESSION_RETIREMENTS = Object.freeze([
  ROOT_SESSION_RETIREMENT,
  LEGACY_SESSION_RETIREMENT,
]);
const AUTH_AND_FLOW_RETIREMENTS = Object.freeze([
  ROOT_SESSION_RETIREMENT,
  LEGACY_SESSION_RETIREMENT,
  FLOW_RETIREMENT,
]);`;
  if (!source.includes(exactDualPathDescriptors)) {
    throw new Error('NYAY19_RUNNER_DUAL_PATH_COOKIE_DESCRIPTORS_MISSING');
  }
  if (!/const loginCookieTransition = inspectCookieTransitionHeaders\([\s\S]*?\[\s*LEGACY_SESSION_RETIREMENT,\s*\{ name: SESSION_COOKIE, action: ['"]issue['"], maxAge: SESSION_TTL_SECONDS \},\s*FLOW_RETIREMENT,\s*\]/u.test(source)) {
    throw new Error('NYAY19_RUNNER_VERIFY_COOKIE_INVENTORY_MISMATCH');
  }
  const authOnlyRetirementUses = source.match(
    /inspectCookieRetirementHeaders\([\s\S]{0,160}?AUTH_ONLY_SESSION_RETIREMENTS,/gu,
  ) ?? [];
  if (authOnlyRetirementUses.length !== 2) {
    throw new Error('NYAY19_RUNNER_AUTH_ONLY_RETIREMENT_INVENTORY_MISMATCH');
  }
  const authAndFlowRetirementUses = source.match(
    /inspectCookieRetirementHeaders\([\s\S]{0,160}?AUTH_AND_FLOW_RETIREMENTS,/gu,
  ) ?? [];
  if (authAndFlowRetirementUses.length !== 2) {
    throw new Error('NYAY19_RUNNER_AUTH_AND_FLOW_RETIREMENT_INVENTORY_MISMATCH');
  }
  if (/(?:'[^'\n]*|"[^"\n]*)\bbearer[ \t]+[-A-Za-z0-9._~+/=]+/iu.test(source)) {
    throw new Error('NYAY19_RUNNER_BEARER_LIKE_EVIDENCE_PROSE');
  }
  const setupSource = source.slice(
    source.indexOf('async function setupDisposableStudent'),
    source.indexOf('async function productStudentSession'),
  );
  if (!/const registration = await context\.request\.post\([\s\S]*\);\s*lastLoginIssueConfirmedAt = Date\.now\(\);\s*await rememberCookieValues\(context\);/u.test(setupSource)) {
    throw new Error('NYAY19_RUNNER_SIGNUP_LOGIN_FLOOR_ANCHOR_MISSING');
  }
  const rotatedRealmRediscovery = `  await loginA.page.reload({ waitUntil: 'domcontentloaded' });
  await loginA.page.waitForURL((url) => url.pathname === '/s-03');
  await loginA.page.locator('[data-screen="S-03"]').waitFor({ state: 'visible' });
`;
  const rotationSource = source.slice(
    source.indexOf("  currentStage = 'rotation';"),
    source.indexOf("  currentStage = 'logout';"),
  );
  const rotatedProbeIndex = rotationSource.indexOf(
    '  const rotatedSession = await productStudentSession(loginA.page);',
  );
  const rediscoveryIndex = rotationSource.indexOf(rotatedRealmRediscovery);
  const contextInspectionIndex = rotationSource.indexOf(
    '  const afterA = await studentContextSnapshot(loginA.page, loginA.actor);',
  );
  if (!(rotatedProbeIndex >= 0
      && rediscoveryIndex > rotatedProbeIndex
      && contextInspectionIndex > rediscoveryIndex)) {
    throw new Error('NYAY19_RUNNER_ROTATED_REALM_REDISCOVERY_MISSING');
  }
  const recordedNames = [...source.matchAll(/\brecord\(\s*['"]([^'"]+)['"]/gu)]
    .map((match) => match[1]);
  if (JSON.stringify(recordedNames) !== JSON.stringify(NYAY19_ASSERTION_INVENTORY)) {
    throw new Error('NYAY19_RUNNER_ASSERTION_SOURCE_MISMATCH');
  }
  for (const required of [
    /let lastLoginIssueConfirmedAt = 0;/,
    /await waitForNextLoginIssuance\(\);[\s\S]*const startResponse = await startPromise;\s*lastLoginIssueConfirmedAt = Date\.now\(\);/,
    /mutationTrace\.push\(\{ snapshot: snapshotNyay19MutationRequest\(request\) \}\);/,
    /const mutationTraceInspection = await inspectExactOrderedMutationTrace\(/,
    /const mutationTraceExact = mutationTraceInspection\.pass;/,
    /mutationTrace,\s*NYAY19_MUTATION_TRACE,\s*WEB_ORIGIN,\s*API_ORIGIN,/,
    /inspectionReadable: mutationTraceInspection\.inspectionReadable/,
    /failingSlots: mutationTraceInspection\.failingSlots/,
    /components: mutationTraceInspection\.components/,
    /const startCookieTransition = inspectCookieTransitionHeaders\([\s\S]*maxAge: OTP_FLOW_TTL_SECONDS/,
    /const loginCookieTransition = inspectCookieTransitionHeaders\(/,
    /\{ name: SESSION_COOKIE, action: ['"]issue['"], maxAge: SESSION_TTL_SECONDS \}/,
    /\[\s*LEGACY_SESSION_RETIREMENT,\s*\{ name: SESSION_COOKIE, action: ['"]issue['"], maxAge: SESSION_TTL_SECONDS \},\s*FLOW_RETIREMENT,\s*\]/,
    /const recoveryForLogout = await startRecoveryFlowForLogout\(loginB\.page, mobile\);\s*await latestOtp\(mobile\);/,
    /recoveryForLogout\.startCookieTransitionExact/,
    /const sessionCookieB = cookiesBeforeLogout\.find\(\(cookie\) => cookie\.name === SESSION_COOKIE\);\s*const rawCookieB = sessionCookieB\?\.value \?\? '';/,
    /const recoveryStartTransition = inspectCookieTransitionHeaders\([\s\S]*maxAge: OTP_FLOW_TTL_SECONDS/,
    /const recoveryVerifyTransition = inspectCookieTransitionHeaders\(/,
    /maxAge: RECOVERY_PROOF_TTL_SECONDS/,
    /const rotationCookieStillLive = hasFutureCookieExpiry\(sessionCookieA, Date\.now\(\)\);/,
    /&& rotationCookieStillLive/,
    /const staleRotationProbes = await independentStaleAuthorityProbes\(browser, rawCookieA\);/,
    /const logoutStaleProbes = await independentStaleAuthorityProbes\(browser, rawCookieB\);\s*const logoutCookieStillLive = hasFutureCookieExpiry\(sessionCookieB, Date\.now\(\)\);/,
    /&& logoutCookieStillLive/,
    /const staleExpiryAuthorityProbes = await independentStaleAuthorityProbes\([\s\S]*rawExpiryCookie,/,
    /const staleDeletionProbes = await independentStaleAuthorityProbes\(browser, rawDeleteCookie\);\s*const deletionCookieStillLive = hasFutureCookieExpiry\(\s*preDeletionSessionCookie,\s*Date\.now\(\),\s*\);/,
    /staleDeletionProbes\.pass && deletionCookieStillLive/,
    /return inspectIndependentProtectedProbes\(ambient, bearer\);/,
    /const ambient = await ambientCookieOnlyProtectedProbe\(browser, rawCookie\);\s*const bearer = await bearerOnlyProtectedProbe\(browser, rawCookie\);/,
    /credentials: ['"]include['"],[\s\S]*channel: ['"]ambient['"][\s\S]*credentials: ['"]omit['"],[\s\S]*Authorization: `Bearer \$\{bearer\}`/,
    /hasExactProtectedAuthorityChannel\([\s\S]*['"]ambient['"][\s\S]*hasExactProtectedAuthorityChannel\([\s\S]*['"]bearer['"]/,
    /denialExact: await hasExactAuthenticationRequired\(response, body\)/,
    /hasExactAuthenticatedStudentSession\(session\.body, session\.actor\)/,
    /hasExactAuthenticatedStudentSession\(sessionDelete\.body, sessionDelete\.actor\)/,
    /const rotationRetirement = inspectCookieRetirementHeaders\(/,
    /const logoutRetirement = inspectCookieRetirementHeaders\(/,
    /const deletionRetirement = inspectCookieRetirementHeaders\(/,
    /const boundaryA = inspectStudentContextBoundary\(beforeA, afterA\);/,
    /const boundaryB = inspectStudentContextBoundary\(beforeB, afterB\);/,
    /const boundaryExpiry = inspectStudentContextBoundary\(beforeExpiry, afterExpiry\);/,
    /const localBase = \[[\s\S]*['"]ls-locale['"][\s\S]*['"]ls-reviewer['"][\s\S]*['"]ls-onboarding-seen['"][\s\S]*\];/,
    /localStorage\.setItem\(['"]nyayone\.theme\.v1['"], ['"]dark['"]\);/,
    /localStorage\.setItem\(['"]ls-locale['"], ['"]hi['"]\);/,
    /localStorage\.setItem\(['"]ls-reviewer['"], ['"]1['"]\);/,
    /localStorage\.setItem\(['"]ls-onboarding-seen['"], ['"]seen['"]\);/,
    /theme: localStorage\.getItem\(['"]nyayone\.theme\.v1['"]\)/,
    /retiredLocale: localStorage\.getItem\(['"]ls-locale['"]\)/,
    /retiredReviewer: localStorage\.getItem\(['"]ls-reviewer['"]\)/,
    /retiredOnboardingSeen: localStorage\.getItem\(['"]ls-onboarding-seen['"]\)/,
    /localStorage\.getItem\(['"]legalsaathi\.student\.cleanup-registry\.v1['"]\) === null\s*&& sessionStorage\.getItem\(['"]legalsaathi\.student\.cleanup-registry\.v1['"]\) === null/,
    /await loginExpiry\.page\.close\(\);\s*const expiryRestartPage = await openProtectedProbePage\(loginExpiry\.context\);\s*const expiredSession = await productStudentSession\(expiryRestartPage\);/,
    /const afterExpiry = await studentContextSnapshot\(expiryRestartPage, loginExpiry\.actor\);/,
    /const boundaryDelete = inspectStudentContextBoundary\(beforeDelete, afterDelete\);/,
    /const naturalExpirySetCookieCount = naturalExpiryHeaders\.filter\(/,
    /naturalExpirySetCookieCount === 0/,
    /const staleExpiryProbe = await staleCookieSessionProbe\(browser, rawExpiryCookie\);/,
    /&& staleExpiryProbe\.retirementExact/,
    /&& staleExpiryProbe\.correlatedStaleCookieExact/,
    /retirementComponents: retirement\.components/,
    /const probeId = `nyay19-session-probe-\$\{sessionProbeSequence\}`;/,
    /requestIds\.length === 1 && requestIds\[0\]\.value === probeId/,
    /studentApi\.studentApiFetch\([\s\S]*\{ method: ['"]GET['"], requestId \}/,
    /return \{ response, body, actor, request: response\.request\(\) \};/,
    /const SESSION_BOOTSTRAP_EXPECTED = 1;/,
    /const SESSION_BOOTSTRAP_TIMEOUT_MS = 10_000;/,
    /function isExactBootstrapSessionRequest\(request\) \{[\s\S]*return request\.method\(\) === ['"]GET['"]\s*&& url\.origin === API_ORIGIN\s*&& url\.pathname === ['"]\/api\/v1\/auth\/student\/session['"]\s*&& url\.search === ['"]['"]\s*&& url\.hash === ['"]['"];/,
    /page\.on\(['"]request['"], onRequest\);\s*page\.on\(['"]response['"], onResponse\);\s*page\.on\(['"]requestfinished['"], onRequestFinished\);\s*page\.on\(['"]requestfailed['"], onRequestFailed\);/,
    /responsesSuccessful = responsesSuccessful && response\.status\(\) === 200;/,
    /const bootstrap = createExactSessionBootstrapBarrier\(page\);[\s\S]*bootstrap\.waitForExact\(\),[\s\S]*page\.goto\([\s\S]*timeout: SESSION_BOOTSTRAP_TIMEOUT_MS[\s\S]*const inspection = bootstrap\.inspect\(\);[\s\S]*inspection\.expectedCount !== SESSION_BOOTSTRAP_EXPECTED \|\| !inspection\.pass/,
    /async function staleCookieSessionProbe\(browser, rawCookie\) \{[\s\S]*const page = await openProtectedProbePage\(context\);\s*await context\.addCookies\([\s\S]*const session = await productStudentSession\(page\);/,
    /const correlatedStaleCookieExact = await hasExactProtectedAuthorityChannel\([\s\S]*['"]\/api\/v1\/auth\/student\/session['"]/,
    /&& staleExpiryAuthorityProbes\.pass/,
    /const evidencePrivacyExact = scanNyay19Evidence\(/,
    /const captureProviderCleared = await clearCaptureEvidence\(\);/,
    /for \(let index = 0; index < 2; index \+= 1\)[\s\S]*setTimeout\(resolve, 250\)[\s\S]*inspectCaptureFinality/,
    /captureProviderCleared\.pass/,
    /loginA\.startCookieTransitionExact/,
    /loginB\.startCookieTransitionExact/,
    /loginExpiry\.startCookieTransitionExact/,
    /loginDelete\.startCookieTransitionExact/,
    /recoveryStartTransition\.pass/,
    /const preDeletionSessionCookie = beforeDeleteCookies\s*\.find\(\(cookie\) => cookie\.name === SESSION_COOKIE\);\s*const rawDeleteCookie = preDeletionSessionCookie\?\.value \?\? '';/,
    /currentStage = ['"]expiry_stale_probe['"];\s*const staleExpiryProbe = await staleCookieSessionProbe/,
    /\} catch \(error\) \{\s*const candidateAbortEnvelope = buildNyay19AbortEnvelope\(currentStage, error, rows\.length\);/,
    /const abortEnvelope = scanNyay19Evidence\([\s\S]*candidateAbortEnvelope[\s\S]*forbiddenEvidenceValues[\s\S]*buildNyay19AbortEnvelope\(['"]unknown['"], new Error\(\), 0\);/,
    /process\.stderr\.write\(`\$\{JSON\.stringify\(abortEnvelope\)\}\\n`\);/,
  ]) {
    if (!required.test(source)) throw new Error('NYAY19_RUNNER_REQUIRED_ORACLE_MISSING');
  }
  if (/\.headers\(\)\.origin/u.test(source)) {
    throw new Error('NYAY19_PROVISIONAL_ORIGIN_ORACLE_PRESENT');
  }
  if (/url\.origin === API_ORIGIN && request\.method\(\) === ['"]POST['"]/u.test(source)) {
    throw new Error('NYAY19_FILTERED_MUTATION_CAPTURE_PRESENT');
  }
  if (/waitForLoadState\(['"]networkidle['"]\)/u.test(source)) {
    throw new Error('NYAY19_NETWORK_IDLE_BOOTSTRAP_PRESENT');
  }
  if (/JSON\.stringify\(error\)|error\.(?:message|stack|cause)/u.test(source)) {
    throw new Error('NYAY19_RAW_ABORT_ERROR_PRESENT');
  }
}

describe('NYAY-19 browser runner exact contract', () => {
  it('pins all frozen gate cardinalities independently', () => {
    expect(NYAY19_ASSERTION_INVENTORY).toHaveLength(18);
    expect(NYAY19_MUTATION_TRACE).toHaveLength(13);
    expect(NYAY19_SEEDED_MUTANT_INVENTORY).toHaveLength(82);
  });

  it('pins stable abort stages and exception classes', () => {
    expect(NYAY19_ABORT_STAGE_INVENTORY).toEqual([
      'unknown',
      'launch',
      'setup',
      'login_a',
      'rotation',
      'logout',
      'expiry_login',
      'expiry_wait',
      'expiry_stale_probe',
      'expiry_context',
      'deletion_login',
      'deletion_reauth',
      'deletion_submit',
      'deletion_stale_probe',
      'trace',
      'finality',
      'summary',
    ]);
    expect(NYAY19_ABORT_EXCEPTION_CLASS_INVENTORY).toEqual([
      'timeout', 'error', 'non_error',
    ]);
  });

  it('accepts only an exact successful single-request session bootstrap settlement', () => {
    expect(inspectNyay19SessionBootstrap({
      requestCount: 1,
      responseCount: 1,
      finishedCount: 1,
      failedCount: 0,
      responsesSuccessful: true,
    })).toMatchObject({
      expectedCount: 1,
      exactCardinality: true,
      finishedSettlementExact: true,
      responsesSuccessful: true,
      pass: true,
    });
  });

  it.each([
    ['extra', {
      requestCount: 2, responseCount: 2, finishedCount: 2, failedCount: 0,
      responsesSuccessful: true,
    }],
    ['missing', {
      requestCount: 0, responseCount: 0, finishedCount: 0, failedCount: 0,
      responsesSuccessful: true,
    }],
    ['unsettled', {
      requestCount: 1, responseCount: 1, finishedCount: 0, failedCount: 0,
      responsesSuccessful: true,
    }],
    ['failed', {
      requestCount: 1, responseCount: 0, finishedCount: 0, failedCount: 1,
      responsesSuccessful: true,
    }],
    ['unsuccessful', {
      requestCount: 1, responseCount: 1, finishedCount: 1, failedCount: 0,
      responsesSuccessful: false,
    }],
  ])('fails closed for planted %s session bootstrap state', (_name, observation) => {
    expect(inspectNyay19SessionBootstrap(observation).pass).toBe(false);
  });

  it('builds only an allowlisted privacy-safe abort envelope', () => {
    const secret = 'opaque-cookie-value-that-must-never-escape-abort-evidence';
    const timeoutError = Object.assign(new Error(secret), {
      name: 'Nyay19BootstrapTimeoutError',
      stack: `stack ${secret}`,
      cause: { token: secret },
    });
    const envelope = buildNyay19AbortEnvelope('expiry_stale_probe', timeoutError, 9);
    expect(envelope).toEqual({
      marker: 'NYAY19_BROWSER_GATE_ABORTED',
      stage: 'expiry_stale_probe',
      exceptionClass: 'timeout',
      timeout: true,
      rowsCompleted: 9,
    });
    expect(Object.keys(envelope).sort()).toEqual([
      'exceptionClass', 'marker', 'rowsCompleted', 'stage', 'timeout',
    ]);
    expect(scanNyay19Evidence(envelope, [secret])).toBe(true);
    expect(buildNyay19AbortEnvelope('not-a-stage', timeoutError, 99)).toMatchObject({
      stage: 'unknown', rowsCompleted: 0,
    });
    expect(buildNyay19AbortEnvelope('launch', new Error(secret), 0)).toMatchObject({
      exceptionClass: 'error', timeout: false,
    });
    expect(buildNyay19AbortEnvelope('launch', secret, 0)).toMatchObject({
      exceptionClass: 'non_error', timeout: false,
    });
  });

  it('pins the canonical session TTL range', () => {
    expect(parseNyay19SessionTtl('2')).toBe(2);
    expect(parseNyay19SessionTtl('20')).toBe(20);
    expect(parseNyay19SessionTtl('30')).toBe(30);
    for (const mutant of ['', '0', '1', '01', '+2', '2.0', '31', ' 20', '20 ', 'true']) {
      expect(() => parseNyay19SessionTtl(mutant)).toThrow('NYAY19_SESSION_TTL_INVALID');
    }
  });

  it('pins flow TTL parsing and the exact one-second resend cooldown', () => {
    expect(parseNyay19OtpCooldown('1')).toBe(1);
    for (const mutant of ['', '0', '01', '2', ' 1', '1 ']) {
      expect(() => parseNyay19OtpCooldown(mutant)).toThrow('NYAY19_OTP_COOLDOWN_INVALID');
    }
    expect(parseNyay19OtpFlowTtl('1')).toBe(1);
    expect(parseNyay19OtpFlowTtl('600')).toBe(600);
    expect(parseNyay19OtpFlowTtl('3600')).toBe(3600);
    for (const mutant of ['', '0', '01', '+1', '3601', '600.0', ' 600']) {
      expect(() => parseNyay19OtpFlowTtl(mutant)).toThrow('NYAY19_OTP_FLOW_TTL_INVALID');
    }
  });

  it('pins first-call and post-response anchored repeat-login timing', () => {
    expect(nextNyay19LoginIssuanceDelay(0, 10_000, 1)).toBe(0);
    expect(nextNyay19LoginIssuanceDelay(10_000, 10_000, 1)).toBe(1_250);
    expect(nextNyay19LoginIssuanceDelay(10_000, 11_249, 1)).toBe(1);
    expect(nextNyay19LoginIssuanceDelay(10_000, 11_250, 1)).toBe(0);
    expect(Number.isNaN(nextNyay19LoginIssuanceDelay(Number.NaN, 10_000, 1))).toBe(true);
    expect(Number.isNaN(nextNyay19LoginIssuanceDelay(0, 10_000, 2))).toBe(true);
  });

  it('accepts only the exact ordered assertion inventory and pinned total', () => {
    expect(summarizeNyay19Rows(validRows())).toMatchObject({
      expectedTotal: NYAY19_ASSERTION_INVENTORY.length,
      total: NYAY19_ASSERTION_INVENTORY.length,
      passed: NYAY19_ASSERTION_INVENTORY.length,
      failed: 0,
    });
  });

  const assertionMutants = [
    ['assertion-missing-row', () => validRows().slice(0, -1)],
    ['assertion-extra-row', () => [...validRows(), { name: 'extra', pass: true }]],
    ['assertion-duplicate-row', () => validRows().map((row, index, all) => index === 1 ? all[0] : row)],
    ['assertion-reordered-rows', () => {
      const rows = validRows();
      [rows[0], rows[1]] = [rows[1], rows[0]];
      return rows;
    }],
    ['assertion-untyped-verdict', () => validRows().map((row, index) => index === 0 ? { ...row, pass: 1 } : row)],
  ];
  it.each(assertionMutants)('kills seeded mutant %s', (_name, mutate) => {
    expect(() => assertExactAssertionInventory(mutate())).toThrow(
      'NYAY19_ASSERTION_INVENTORY_MISMATCH',
    );
  });

  it('accepts one exact raw Origin and fails closed on access errors', async () => {
    const exact = requestWith({ path: '/x', body: {} });
    await expect(hasExactSingleOrigin(exact, WEB_ORIGIN)).resolves.toBe(true);
    await expect(hasExactSingleOrigin({
      headersArray: async () => { throw new Error('planted'); },
    }, WEB_ORIGIN)).resolves.toBe(false);
  });

  const originMutants = [
    ['origin-missing', []],
    ['origin-wrong', [{ name: 'Origin', value: 'http://127.0.0.1:9999' }]],
    ['origin-duplicate', [
      { name: 'Origin', value: WEB_ORIGIN },
      { name: 'oRiGiN', value: WEB_ORIGIN },
    ]],
  ];
  it.each(originMutants)('kills seeded mutant %s', async (_name, headers) => {
    await expect(hasExactSingleOrigin(
      requestWith({ path: '/x', body: {}, headers }),
      WEB_ORIGIN,
    )).resolves.toBe(false);
  });
  it('fails closed when raw headers cannot be read', async () => {
    await expect(hasExactSingleOrigin({}, WEB_ORIGIN)).resolves.toBe(false);
  });

  it('accepts the exact ordered mutation trace', async () => {
    await expect(hasExactOrderedMutationTrace(
      validTrace(),
      NYAY19_MUTATION_TRACE,
      WEB_ORIGIN,
      API,
    )).resolves.toBe(true);
  });

  it('returns privacy-safe typed trace diagnostics and snapshots at request time', async () => {
    const inspection = await inspectExactOrderedMutationTrace(
      validTrace(),
      NYAY19_MUTATION_TRACE,
      WEB_ORIGIN,
      API,
    );
    expect(inspection).toMatchObject({
      expectedCount: 13,
      observedCount: 13,
      exactCardinality: true,
      inspectionReadable: true,
      failingSlots: [],
      pass: true,
    });
    expect(inspection.components).toHaveLength(13);
    expect(inspection.components.every((component) => component.pass)).toBe(true);
    expect(scanNyay19Evidence(inspection)).toBe(true);
    await expect(inspectExactOrderedMutationTrace([], [], WEB_ORIGIN, API)).resolves
      .toMatchObject({ exactCardinality: false, pass: false });

    let releaseHeaders;
    const headers = new Promise((resolveHeaders) => { releaseHeaders = resolveHeaders; });
    const calls = [];
    const snapshot = snapshotNyay19MutationRequest({
      method: () => { calls.push('method'); return 'POST'; },
      url: () => { calls.push('url'); return `${API}/api/v1/auth/student/logout`; },
      postDataJSON: () => { calls.push('body'); return {}; },
      headersArray: () => { calls.push('headers'); return headers; },
    });
    expect(calls).toEqual(['method', 'url', 'body', 'headers']);
    releaseHeaders([{ name: 'Origin', value: WEB_ORIGIN }]);
    await expect(snapshot).resolves.toMatchObject({ readable: true, method: 'POST', body: {} });
  });

  it('fails closed when a request-header snapshot or stored snapshot promise rejects', async () => {
    const rejectedHeaders = snapshotNyay19MutationRequest({
      method: () => 'POST',
      url: () => `${API}/api/v1/auth/student/logout`,
      postDataJSON: () => ({}),
      headersArray: () => Promise.reject(new Error('headers unavailable')),
    });
    await expect(rejectedHeaders).resolves.toEqual({ readable: false });

    const inspection = await inspectExactOrderedMutationTrace(
      [{ snapshot: Promise.reject(new Error('snapshot unavailable')) }],
      [NYAY19_MUTATION_TRACE[0]],
      WEB_ORIGIN,
      API,
    );
    expect(inspection).toMatchObject({
      expectedCount: 1,
      observedCount: 1,
      exactCardinality: true,
      inspectionReadable: false,
      failingSlots: [0],
      pass: false,
    });
    expect(inspection.components).toEqual([expect.objectContaining({
      slot: 0,
      inspectionReadable: false,
      pass: false,
    })]);
    expect(scanNyay19Evidence(inspection)).toBe(true);
  });

  const traceMutants = [
    ['trace-missing-request', (trace) => trace.slice(0, -1)],
    ['trace-extra-request', (trace) => [...trace, trace.at(-1)]],
    ['trace-reordered-request', (trace) => {
      [trace[0], trace[1]] = [trace[1], trace[0]];
      return trace;
    }],
    ['trace-wrong-method', (trace) => {
      trace[0] = { request: requestWith({ path: NYAY19_MUTATION_TRACE[0].path, body: bodyFor('mobile'), method: 'PUT' }) };
      return trace;
    }],
    ['trace-wrong-api-origin', (trace) => {
      trace[0] = { request: requestWith({
        path: NYAY19_MUTATION_TRACE[0].path,
        body: bodyFor('mobile'),
        origin: 'http://127.0.0.1:9999',
      }) };
      return trace;
    }],
    ['trace-wrong-path', (trace) => {
      trace[0] = { request: requestWith({ path: '/api/v1/auth/student/logout', body: bodyFor('mobile') }) };
      return trace;
    }],
    ['trace-wrong-query', (trace) => {
      trace[0] = { request: requestWith({
        path: NYAY19_MUTATION_TRACE[0].path,
        body: bodyFor('mobile'),
        query: '?mobile=8765432109',
      }) };
      return trace;
    }],
    ['trace-missing-body-key', (trace) => {
      trace[0] = { request: requestWith({ path: NYAY19_MUTATION_TRACE[0].path, body: {} }) };
      return trace;
    }],
    ['trace-extra-body-key', (trace) => {
      trace[0] = { request: requestWith({ path: NYAY19_MUTATION_TRACE[0].path, body: { mobile: '8765432109', extra: true } }) };
      return trace;
    }],
    ['trace-invalid-mobile-shape', (trace) => {
      trace[0] = { request: requestWith({ path: NYAY19_MUTATION_TRACE[0].path, body: { mobile: '876543210' } }) };
      return trace;
    }],
    ['trace-invalid-code-shape', (trace) => {
      trace[1] = { request: requestWith({ path: NYAY19_MUTATION_TRACE[1].path, body: { code: '13579' } }) };
      return trace;
    }],
    ['trace-invalid-confirmation', (trace) => {
      const index = trace.length - 1;
      trace[index] = { request: requestWith({ path: NYAY19_MUTATION_TRACE[index].path, body: { confirmation: 'delete' } }) };
      return trace;
    }],
    ['trace-nonempty-logout', (trace) => {
      const index = NYAY19_MUTATION_TRACE.findIndex((entry) => entry.body === 'empty');
      trace[index] = { request: requestWith({ path: NYAY19_MUTATION_TRACE[index].path, body: { extra: true } }) };
      return trace;
    }],
    ['trace-unreadable-body', (trace) => {
      trace[0] = { request: requestWith({ path: NYAY19_MUTATION_TRACE[0].path, body: {}, bodyFailure: true }) };
      return trace;
    }],
  ];
  it.each(traceMutants)('kills seeded mutant %s', async (_name, mutate) => {
    await expect(hasExactOrderedMutationTrace(
      mutate(validTrace()),
      NYAY19_MUTATION_TRACE,
      WEB_ORIGIN,
      API,
    )).resolves.toBe(false);
  });

  it('accepts unordered exact live-cookie inventory', () => {
    expect(inspectAuthorityCookieInventory([
      validCookie(FLOW_COOKIE),
      validCookie(SESSION_COOKIE),
    ], [SESSION_COOKIE, FLOW_COOKIE], API).pass).toBe(true);
  });

  const cookieMutants = [
    ['cookie-extra-cookie', [[validCookie(SESSION_COOKIE), validCookie(FLOW_COOKIE)]]],
    ['cookie-wrong-name', [[validCookie('wrong')]]],
    ['cookie-duplicate-cookie', [[validCookie(SESSION_COOKIE), validCookie(SESSION_COOKIE)]]],
    ['cookie-domain-cookie', [[validCookie(SESSION_COOKIE, { domain: '.127.0.0.1' })]]],
    ['cookie-wrong-attributes', [
      [validCookie(SESSION_COOKIE, { path: '/api/v1' })],
      [validCookie(SESSION_COOKIE, { httpOnly: false })],
      [validCookie(SESSION_COOKIE, { secure: true })],
      [validCookie(SESSION_COOKIE, { sameSite: 'Strict' })],
      [validCookie(SESSION_COOKIE, { value: 'short' })],
    ]],
  ];
  it.each(cookieMutants)('kills seeded mutant %s', (_name, variants) => {
    for (const cookies of variants) {
      expect(inspectAuthorityCookieInventory(cookies, [SESSION_COOKIE], API).pass).toBe(false);
    }
  });

  it('accepts the exact legacy retirement, root issuance and flow retirement verify transition', () => {
    const transition = verifyTransition();
    expect(inspectCookieTransitionHeaders(
      transition.headers,
      transition.expected,
      API,
    ).pass).toBe(true);
  });

  const issuanceMutants = [
    ['issuance-domain-attribute', [[
      retirement(SESSION_COOKIE, '', 'legacy'),
      issuance(SESSION_COOKIE, 20, '; Domain=127.0.0.1'),
      retirement(FLOW_COOKIE),
    ]]],
    ['issuance-wrong-max-age', [[
      retirement(SESSION_COOKIE, '', 'legacy'),
      issuance(SESSION_COOKIE, 21),
      retirement(FLOW_COOKIE),
    ]]],
    ['issuance-missing-flow-retirement', [[
      retirement(SESSION_COOKIE, '', 'legacy'),
      issuance(SESSION_COOKIE, 20),
    ]]],
    ['issuance-empty-value', [[
      retirement(SESSION_COOKIE, '', 'legacy'),
      { ...issuance(SESSION_COOKIE, 20), value: issuance(SESSION_COOKIE, 20).value.replace(`=${OPAQUE}`, '=""') },
      retirement(FLOW_COOKIE),
    ]]],
    ['issuance-wrong-attributes', [
      [
        retirement(SESSION_COOKIE, '', 'legacy'),
        { ...issuance(SESSION_COOKIE, 20), value: issuance(SESSION_COOKIE, 20).value.replace('Path=/', 'Path=/api/v1') },
        retirement(FLOW_COOKIE),
      ],
      [
        retirement(SESSION_COOKIE, '', 'legacy'),
        { ...issuance(SESSION_COOKIE, 20), value: issuance(SESSION_COOKIE, 20).value.replace('; HttpOnly', '') },
        retirement(FLOW_COOKIE),
      ],
      [
        retirement(SESSION_COOKIE, '', 'legacy'),
        { ...issuance(SESSION_COOKIE, 20), value: issuance(SESSION_COOKIE, 20).value.replace('SameSite=lax', 'SameSite=strict') },
        retirement(FLOW_COOKIE),
      ],
      [
        retirement(SESSION_COOKIE, '', 'legacy'),
        issuance(SESSION_COOKIE, 20, '; Secure'),
        retirement(FLOW_COOKIE),
      ],
    ]],
    ['issuance-duplicate-attribute', [[
      retirement(SESSION_COOKIE, '', 'legacy'),
      issuance(SESSION_COOKIE, 20, '; Path=/'),
      retirement(FLOW_COOKIE),
    ]]],
    ['issuance-wrong-order-cardinality', [
      [
        retirement(FLOW_COOKIE),
        retirement(SESSION_COOKIE, '', 'legacy'),
        issuance(SESSION_COOKIE, 20),
      ],
      [
        retirement(SESSION_COOKIE, '', 'legacy'),
        issuance(SESSION_COOKIE, 20),
        retirement(FLOW_COOKIE),
        retirement('extra'),
      ],
    ]],
  ];
  it.each(issuanceMutants)('kills seeded mutant %s', (_name, variants) => {
    const { expected } = verifyTransition();
    for (const headers of variants) {
      expect(inspectCookieTransitionHeaders(headers, expected, API).pass).toBe(false);
    }
  });

  it('accepts exact root then legacy auth-only retirement for stale and rotated sessions', () => {
    const transition = authOnlyRetirement();
    expect(inspectCookieRetirementHeaders(
      transition.headers,
      transition.expected,
      API,
    ).pass).toBe(true);
  });

  it('accepts only exact action-qualified retirement descriptors with known policy', () => {
    const inspection = inspectCookieRetirementHeaders(
      [
        retirement(SESSION_COOKIE),
        retirement(SESSION_COOKIE, '', 'legacy'),
        retirement(FLOW_COOKIE),
      ],
      [
        { name: SESSION_COOKIE, action: 'retire' },
        { name: SESSION_COOKIE, action: 'retire', scope: 'legacy' },
        { name: FLOW_COOKIE, action: 'retire' },
      ],
      API,
    );

    expect(inspection.pass).toBe(true);
    expect(inspection.components).toHaveLength(3);
    expect(inspection.components.every((component) => component.policyKnown)).toBe(true);
  });

  it('rejects malformed retirement descriptors fail closed', () => {
    const exactHeader = [retirement(SESSION_COOKIE)];
    const invalidDescriptors = [
      SESSION_COOKIE,
      { name: SESSION_COOKIE },
      { name: SESSION_COOKIE, action: 'issue' },
      { action: 'retire' },
      { name: '', action: 'retire' },
      { name: 'unowned_cookie', action: 'retire' },
      { name: SESSION_COOKIE, action: 'retire', scope: null },
      { name: SESSION_COOKIE, action: 'retire', scope: undefined },
      { name: SESSION_COOKIE, action: 'retire', scope: 'unowned' },
      { name: SESSION_COOKIE, action: 'retire', extra: true },
    ];

    for (const descriptor of invalidDescriptors) {
      const inspection = inspectCookieRetirementHeaders(
        exactHeader,
        [descriptor],
        API,
      );
      expect(inspection.pass).toBe(false);
      expect(inspection.components[0]?.policyKnown).toBe(false);
    }
  });

  it('keeps exact Path and SameSite retirement attributes mandatory', () => {
    const expected = [{ name: SESSION_COOKIE, action: 'retire' }];
    const exact = retirement(SESSION_COOKIE);
    const wrongPath = {
      ...exact,
      value: exact.value.replace('Path=/', 'Path=/api/v1'),
    };
    const wrongSameSite = {
      ...exact,
      value: exact.value.replace('SameSite=lax', 'SameSite=strict'),
    };

    const wrongPathInspection = inspectCookieRetirementHeaders([wrongPath], expected, API);
    const wrongSameSiteInspection = inspectCookieRetirementHeaders(
      [wrongSameSite],
      expected,
      API,
    );
    expect(wrongPathInspection.pass).toBe(false);
    expect(wrongPathInspection.components[0]).toMatchObject({
      policyKnown: true,
      pathExact: false,
      sameSiteExact: true,
    });
    expect(wrongSameSiteInspection.pass).toBe(false);
    expect(wrongSameSiteInspection.components[0]).toMatchObject({
      policyKnown: true,
      pathExact: true,
      sameSiteExact: false,
    });
  });

  it('accepts one exact host-only flow issuance', () => {
    expect(inspectCookieTransitionHeaders(
      [issuance(FLOW_COOKIE, 600)],
      [{ name: FLOW_COOKIE, action: 'issue', maxAge: 600 }],
      API,
    ).pass).toBe(true);
  });

  const flowIssuanceMutants = [
    ['flow-issuance-missing', [[]]],
    ['flow-issuance-wrong-max-age', [[issuance(FLOW_COOKIE, 601)]]],
    ['flow-issuance-domain-attribute', [[
      issuance(FLOW_COOKIE, 600, '; Domain=127.0.0.1'),
    ]]],
    ['flow-issuance-duplicate-header', [[
      issuance(FLOW_COOKIE, 600),
      issuance(FLOW_COOKIE, 600),
    ]]],
  ];
  it.each(flowIssuanceMutants)('kills seeded mutant %s', (_name, variants) => {
    for (const headers of variants) {
      expect(inspectCookieTransitionHeaders(
        headers,
        [{ name: FLOW_COOKIE, action: 'issue', maxAge: 600 }],
        API,
      ).pass).toBe(false);
    }
  });

  it('accepts ordered exact root, legacy and flow retirement headers', () => {
    const transition = completeRetirement();
    const inspection = inspectCookieRetirementHeaders(
      transition.headers,
      transition.expected,
      API,
    );
    expect(inspection.pass).toBe(true);
    expect(inspection.components).toHaveLength(3);
    expect(inspection.components.every((component) => component.pass)).toBe(true);
    expect(scanNyay19Evidence(inspection)).toBe(true);
  });

  const retirementMutants = [
    ['retirement-missing-header', [[
      retirement(SESSION_COOKIE), retirement(SESSION_COOKIE, '', 'legacy'),
    ]]],
    ['retirement-extra-header', [[
      retirement(SESSION_COOKIE), retirement(SESSION_COOKIE, '', 'legacy'),
      retirement(FLOW_COOKIE), retirement('extra'),
    ]]],
    ['retirement-reordered-header', [[
      retirement(FLOW_COOKIE), retirement(SESSION_COOKIE),
      retirement(SESSION_COOKIE, '', 'legacy'),
    ]]],
    ['retirement-nonempty-value', [[
      { ...retirement(SESSION_COOKIE), value: retirement(SESSION_COOKIE).value.replace('=""', '=planted') },
      retirement(SESSION_COOKIE, '', 'legacy'),
      retirement(FLOW_COOKIE),
    ]]],
    ['retirement-domain-attribute', [[
      retirement(SESSION_COOKIE, '; Domain=127.0.0.1'),
      retirement(SESSION_COOKIE, '', 'legacy'), retirement(FLOW_COOKIE),
    ]]],
    ['retirement-wrong-attributes', [
      [
        { ...retirement(SESSION_COOKIE), value: retirement(SESSION_COOKIE).value.replace('Path=/', 'Path=/api/v1') },
        retirement(SESSION_COOKIE, '', 'legacy'),
        retirement(FLOW_COOKIE),
      ],
      [
        { ...retirement(SESSION_COOKIE), value: retirement(SESSION_COOKIE).value.replace('; HttpOnly', '') },
        retirement(SESSION_COOKIE, '', 'legacy'),
        retirement(FLOW_COOKIE),
      ],
      [
        { ...retirement(SESSION_COOKIE), value: retirement(SESSION_COOKIE).value.replace('SameSite=lax', 'SameSite=strict') },
        retirement(SESSION_COOKIE, '', 'legacy'),
        retirement(FLOW_COOKIE),
      ],
      [
        retirement(SESSION_COOKIE, '; Secure'), retirement(SESSION_COOKIE, '', 'legacy'),
        retirement(FLOW_COOKIE),
      ],
    ]],
    ['retirement-invalid-max-age-or-expiry', [
      [
        { ...retirement(SESSION_COOKIE), value: retirement(SESSION_COOKIE).value.replace('; Max-Age=0', '') },
        retirement(SESSION_COOKIE, '', 'legacy'),
        retirement(FLOW_COOKIE),
      ],
      [
        { ...retirement(SESSION_COOKIE), value: retirement(SESSION_COOKIE).value.replace('Thu, 01 Jan 1970 00:00:00 GMT', 'invalid') },
        retirement(SESSION_COOKIE, '', 'legacy'),
        retirement(FLOW_COOKIE),
      ],
      [
        { ...retirement(SESSION_COOKIE), value: retirement(SESSION_COOKIE).value.replace('Thu, 01 Jan 1970 00:00:00 GMT', 'Thu, 01 Jan 2099 00:00:00 GMT') },
        retirement(SESSION_COOKIE, '', 'legacy'),
        retirement(FLOW_COOKIE),
      ],
    ]],
    ['retirement-duplicate-attribute', [[
      retirement(SESSION_COOKIE, '; Path=/'), retirement(SESSION_COOKIE, '', 'legacy'),
      retirement(FLOW_COOKIE),
    ]]],
  ];
  it.each(retirementMutants)('kills seeded mutant %s', (_name, variants) => {
    const { expected } = completeRetirement();
    for (const headers of variants) {
      expect(inspectCookieRetirementHeaders(headers, expected, API).pass).toBe(false);
    }
  });

  const legacyRetirementMutants = [
    ['legacy-retirement-missing', (transition) => {
      transition.headers.splice(1, 1);
    }],
    ['legacy-retirement-wrong-policy', (transition) => {
      transition.headers[1] = retirement(SESSION_COOKIE);
    }],
    ['legacy-retirement-duplicate', (transition) => {
      transition.headers.splice(1, 0, retirement(SESSION_COOKIE, '', 'legacy'));
    }],
    ['legacy-retirement-reordered', (transition) => {
      [transition.headers[0], transition.headers[1]] = [
        transition.headers[1], transition.headers[0],
      ];
    }],
  ];
  it.each(legacyRetirementMutants)('kills seeded mutant %s in every raw inventory', (
    _name,
    mutate,
  ) => {
    for (const makeTransition of [verifyTransition, authOnlyRetirement, completeRetirement]) {
      const transition = makeTransition();
      mutate(transition);
      const inspection = transition.expected[0]?.action
        ? inspectCookieTransitionHeaders(transition.headers, transition.expected, API)
        : inspectCookieRetirementHeaders(transition.headers, transition.expected, API);
      expect(inspection.pass).toBe(false);
    }
  });

  it('accepts only a fully seeded then fully cleared student context', () => {
    expect(inspectStudentContextBoundary(contextBefore(), contextAfter())).toEqual({
      beforeExact: true,
      afterExact: true,
      pass: true,
    });
  });

  it('rejects any retired device value surviving a lifecycle boundary', () => {
    for (const [key, value] of [
      ['retiredLocale', 'hi'],
      ['retiredReviewer', '1'],
      ['retiredOnboardingSeen', 'seen'],
    ]) {
      const after = contextAfter();
      after.controls[key] = value;
      expect(inspectStudentContextBoundary(contextBefore(), after).pass).toBe(false);
    }
  });

  const contextMutants = [
    ['context-browser-backed-actor-registry', (before, after) => [
      { ...before, retiredActorRegistryAbsent: false }, after,
    ]],
    ['context-unseeded-memory', (before, after) => [{ ...before, registrationAttemptPresent: false }, after]],
    ['context-retained-storage', (before, after) => [before, { ...after, managedPresentCount: 1 }]],
    ['context-retained-query-cache', (before, after) => [before, { ...after, queryCacheCount: 1 }]],
    ['context-retained-mutation-cache', (before, after) => [before, { ...after, mutationCacheCount: 1 }]],
    ['context-retained-registration-attempt', (before, after) => [before, { ...after, registrationAttemptPresent: true }]],
    ['context-retained-profile-draft', (before, after) => [before, { ...after, profileDraftPresent: true }]],
    ['context-removed-control', (before, after) => [
      before,
      { ...after, controls: { ...after.controls, unrelated: null } },
    ]],
  ];
  it.each(contextMutants)('kills seeded mutant %s', (_name, mutate) => {
    const [before, after] = mutate(contextBefore(), contextAfter());
    expect(inspectStudentContextBoundary(before, after).pass).toBe(false);
  });

  it('accepts aggregate-only evidence', () => {
    expect(scanNyay19Evidence(validRows(), ['planted-secret'])).toBe(true);
    expect(scanNyay19Evidence({
      expected: 'independent ambient and bearer channels, including bearer-only denial',
      pass: true,
    })).toBe(true);
  });

  it('rejects URL-safe, JWT-like and standard-base64 Authorization bearer values', () => {
    for (const token of [
      OPAQUE,
      'eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiJwbGFudGVkIn0.signature0123456789',
      STANDARD_BASE64,
      STANDARD_BASE64_UNPADDED,
    ]) {
      expect(scanNyay19Evidence({ leak: `Bearer ${token}` })).toBe(false);
      expect(scanNyay19Evidence({ leak: `bearer ${token}` })).toBe(false);
    }
    expect(scanNyay19Evidence({ expected: `Bearer ${'a'.repeat(31)}` })).toBe(true);
    expect(scanNyay19Evidence({ leak: `Bearer ${'a'.repeat(30)}==` })).toBe(false);
  });

  const evidenceMutants = [
    ['evidence-mobile', { leak: '8765432109' }, []],
    ['evidence-otp', { leak: '135790' }, []],
    ['evidence-bearer', { leak: `Bearer ${STANDARD_BASE64}` }, []],
    ['evidence-uuid', { leak: '123e4567-e89b-42d3-a456-426614174000' }, []],
    ['evidence-explicit-secret', { leak: 'planted-secret' }, ['planted-secret']],
  ];
  it.each(evidenceMutants)('kills seeded mutant %s', (_name, value, forbidden) => {
    expect(scanNyay19Evidence(value, forbidden)).toBe(false);
  });

  it('accepts an exact authenticated student session and mapped actor', () => {
    const rawActor = actor();
    expect(hasExactAuthenticatedStudentSession(
      authenticatedSession(rawActor),
      structuredClone(rawActor),
    )).toBe(true);
  });

  it('accepts exact isolated ambient and bearer authority channels', async () => {
    await expect(hasExactProtectedAuthorityChannel(
      ambientRequest(),
      'ambient',
      SESSION_COOKIE,
      OPAQUE,
      API,
    )).resolves.toBe(true);
    await expect(hasExactProtectedAuthorityChannel(
      bearerRequest(),
      'bearer',
      SESSION_COOKIE,
      OPAQUE,
      API,
    )).resolves.toBe(true);
  });

  it('accepts two distinct exact protected denials', () => {
    const ambient = {
      channel: 'ambient', request: {}, requestCount: 1, channelExact: true, denialExact: true,
    };
    const bearer = {
      channel: 'bearer', request: {}, requestCount: 1, cookiesBefore: 0, cookiesAfter: 0,
      channelExact: true, denialExact: true,
    };
    expect(inspectIndependentProtectedProbes(ambient, bearer).pass).toBe(true);
  });

  it('accepts the exact typed authentication-required envelope and request ID header', async () => {
    await expect(hasExactAuthenticationRequired(
      denialResponse(),
      denialBody(),
    )).resolves.toBe(true);
  });

  it('separates naturally live cookie authority from expiry attribution', () => {
    expect(hasFutureCookieExpiry({ expires: 20 }, 10_000, 1_000)).toBe(true);
    expect(hasFutureCookieExpiry({ expires: 11 }, 10_000, 1_000)).toBe(false);
  });

  it('accepts reset plus two settled exact-empty capture reads', () => {
    expect(inspectCaptureFinality(
      { status: 200, body: { status: 'reset' } },
      [{ status: 200, body: {} }, { status: 200, body: {} }],
    )).toEqual({ resetExact: true, emptyReadCount: 2, settledEmptyTwice: true, pass: true });
  });

  it('pins the executable runner to every fail-closed oracle', () => {
    const source = readFileSync(resolve('scripts/nyay19-auth-lifecycle-browser.mjs'), 'utf8');
    expect(() => assertRunnerWiring(source)).not.toThrow();
  });

  const rejectSourceMutation = (source, mutate, label = 'source mutant') => {
    const mutated = mutate(source);
    expect(mutated).not.toBe(source);
    expect(() => assertRunnerWiring(mutated), label).toThrow();
  };

  it('kills the obsolete nested-consent and HTTP 201 setup contract', () => {
    const source = readFileSync(resolve('scripts/nyay19-auth-lifecycle-browser.mjs'), 'utf8');
    const currentConsent = `          terms_accepted: true,
          terms_version: 'dpdp-2023.v1',
          privacy_notice_acknowledged: true,
          privacy_notice_version: 'dpdp-2023.v1',`;
    const obsoleteConsent = "          consent: { accepted: true, policy_version: 'nyay19-browser-lifecycle' },";

    rejectSourceMutation(
      source,
      (value) => value.replace(currentConsent, obsoleteConsent),
      'obsolete nested consent',
    );
    rejectSourceMutation(
      source,
      (value) => value.replace('setup.registrationHttp === 202', 'setup.registrationHttp === 201'),
      'obsolete registration status',
    );
    rejectSourceMutation(
      source,
      (value) => value.replace(
        '    lastLoginIssueConfirmedAt = Date.now();\n    await rememberCookieValues(context);',
        '    await rememberCookieValues(context);',
      ),
      'signup-to-login resend floor anchor',
    );
    rejectSourceMutation(
      source,
      (value) => value.replace(
        "  await page.locator('[data-screen=\"S-04\"]').waitFor({ state: 'visible' });",
        "  await page.locator('[data-screen=\"S-04\"]').waitFor({ state: 'visible' });\n  await page.getByRole('button', { name: 'Use a one time code' }).click();",
      ),
      'obsolete login mode toggle',
    );
  });

  it('kills a rotated realm rediscovery bypass before context inspection', () => {
    const source = readFileSync(resolve('scripts/nyay19-auth-lifecycle-browser.mjs'), 'utf8');
    const rediscovery = `  await loginA.page.reload({ waitUntil: 'domcontentloaded' });
  await loginA.page.waitForURL((url) => url.pathname === '/s-03');
  await loginA.page.locator('[data-screen="S-03"]').waitFor({ state: 'visible' });
`;
    rejectSourceMutation(
      source,
      (value) => value.replace(rediscovery, ''),
      'rotated realm rediscovery bypass',
    );
  });

  const exactProbePair = () => ({
    ambient: {
      channel: 'ambient', request: {}, requestCount: 1, channelExact: true, denialExact: true,
    },
    bearer: {
      channel: 'bearer', request: {}, requestCount: 1, cookiesBefore: 0, cookiesAfter: 0,
      channelExact: true, denialExact: true,
    },
  });

  const advancedMutants = [
    ['expiry-natural-demands-retirement', async (source) => rejectSourceMutation(
      source,
      (value) => value.replaceAll(
        'naturalExpirySetCookieCount === 0',
        'naturalExpirySetCookieCount === 1',
      ),
    )],
    ['expiry-stale-skips-retirement', async (source) => {
      for (const [from, to] of [
        ['&& staleExpiryProbe.retirementExact', '&& true'],
        ['&& staleExpiryProbe.correlatedStaleCookieExact', '&& true'],
        ['const SESSION_BOOTSTRAP_EXPECTED = 1;', 'const SESSION_BOOTSTRAP_EXPECTED = 2;'],
        ['const SESSION_BOOTSTRAP_TIMEOUT_MS = 10_000;', 'const SESSION_BOOTSTRAP_TIMEOUT_MS = 30_000;'],
        ["return request.method() === 'GET'", 'return true'],
        ['&& url.origin === API_ORIGIN', '&& true'],
        ["&& url.pathname === '/api/v1/auth/student/session'", '&& true'],
        ["&& url.search === ''", '&& true'],
        ["&& url.hash === '';", '&& true;'],
        ["page.on('requestfinished', onRequestFinished);", "page.on('requestfinished', () => {});"],
        ['responsesSuccessful = responsesSuccessful && response.status() === 200;', 'responsesSuccessful = true;'],
        ['bootstrap.waitForExact(),', 'Promise.resolve(),'],
        [
          'if (inspection.expectedCount !== SESSION_BOOTSTRAP_EXPECTED || !inspection.pass)',
          'if (false)',
        ],
        [
          'const page = await openProtectedProbePage(context);\n    await context.addCookies([',
          'const pagePromise = openProtectedProbePage(context);\n    await context.addCookies([',
        ],
        ['requestIds.length === 1 && requestIds[0].value === probeId', 'true'],
        ["{ method: 'GET', requestId }", "{ method: 'GET' }"],
        ['const correlatedStaleCookieExact = await hasExactProtectedAuthorityChannel(', 'const correlatedStaleCookieExact = await Boolean('],
        ['retirementComponents: retirement.components', 'retirementComponents: []'],
        [
          "localStorage.getItem('legalsaathi.student.cleanup-registry.v1') === null",
          'true',
        ],
        ['  await loginExpiry.page.close();\n', ''],
        [
          'const expiredSession = await productStudentSession(expiryRestartPage);',
          'const expiredSession = await productStudentSession(loginExpiry.page);',
        ],
        [
          'const afterExpiry = await studentContextSnapshot(expiryRestartPage, loginExpiry.actor);',
          'const afterExpiry = await studentContextSnapshot(loginExpiry.page, loginExpiry.actor);',
        ],
      ]) {
        rejectSourceMutation(source, (value) => value.replaceAll(from, to), from);
      }
    }],
    ['cooldown-invalid-config', async () => {
      expect(() => parseNyay19OtpCooldown('2')).toThrow('NYAY19_OTP_COOLDOWN_INVALID');
      expect(Number.isNaN(nextNyay19LoginIssuanceDelay(10_000, 10_000, 2))).toBe(true);
    }],
    ['cooldown-wait-removed', async (source) => rejectSourceMutation(
      source,
      (value) => value.replace('  await waitForNextLoginIssuance();\n', ''),
    )],
    ['cooldown-post-response-anchor-bypass', async (source) => rejectSourceMutation(
      source,
      (value) => value.replace(
        '  const startResponse = await startPromise;\n  lastLoginIssueConfirmedAt = Date.now();',
        '  lastLoginIssueConfirmedAt = Date.now();\n  const startResponse = await startPromise;',
      ),
    )],
    ['flow-ttl-invalid-config', async () => {
      expect(() => parseNyay19OtpFlowTtl('601.0')).toThrow('NYAY19_OTP_FLOW_TTL_INVALID');
      expect(() => parseNyay19OtpFlowTtl('3601')).toThrow('NYAY19_OTP_FLOW_TTL_INVALID');
    }],
    ['lifecycle-expiry-attribution-bypass', async (source) => {
      expect(hasFutureCookieExpiry({ expires: 11 }, 10_000, 1_000)).toBe(false);
      for (const field of [
        'rotationCookieStillLive',
        'logoutCookieStillLive',
        'deletionCookieStillLive',
      ]) {
        rejectSourceMutation(source, (value) => value.replaceAll(`&& ${field}`, '&& true'));
        rejectSourceMutation(source, (value) => value.replaceAll(`&& ${field}`, ''));
      }
      rejectSourceMutation(source, (value) => value.replace(
        'const logoutCookieStillLive = hasFutureCookieExpiry(sessionCookieB, Date.now());',
        'const logoutCookieStillLive = hasFutureCookieExpiry(sessionCookieA, Date.now());',
      ));
      rejectSourceMutation(source, (value) => value.replace(
        'const logoutStaleProbes = await independentStaleAuthorityProbes(browser, rawCookieB);\n  const logoutCookieStillLive',
        'const logoutCookieStillLive',
      ).replace(
        ' = hasFutureCookieExpiry(sessionCookieB, Date.now());',
        ' = hasFutureCookieExpiry(sessionCookieB, Date.now());\n  const logoutStaleProbes = await independentStaleAuthorityProbes(browser, rawCookieB);',
      ));
      rejectSourceMutation(source, (value) => value.replace(
        'preDeletionSessionCookie,\n    Date.now(),',
        'sessionCookieA,\n    Date.now(),',
      ));
      rejectSourceMutation(source, (value) => value.replace(
        "const rawDeleteCookie = preDeletionSessionCookie?.value ?? '';",
        'const rawDeleteCookie = rawCookieA;',
      ));
      rejectSourceMutation(source, (value) => value.replace(
        'const staleDeletionProbes = await independentStaleAuthorityProbes(browser, rawDeleteCookie);\n  const deletionCookieStillLive = hasFutureCookieExpiry(\n    preDeletionSessionCookie,\n    Date.now(),\n  );',
        'const deletionCookieStillLive = hasFutureCookieExpiry(\n    preDeletionSessionCookie,\n    Date.now(),\n  );\n  const staleDeletionProbes = await independentStaleAuthorityProbes(browser, rawDeleteCookie);',
      ));
    }],
    ['actor-extra-field', async () => {
      const mutant = { ...actor(), mobile: 'redacted' };
      expect(hasExactAuthenticatedStudentSession(authenticatedSession(mutant), mutant)).toBe(false);
      expect(hasExactAuthenticatedStudentSession(
        { ...authenticatedSession(), extra: true },
        actor(),
      )).toBe(false);
    }],
    ['actor-wrong-role', async () => {
      const mutant = { ...actor(), roles: ['student', 'admin'] };
      expect(hasExactAuthenticatedStudentSession(authenticatedSession(mutant), mutant)).toBe(false);
    }],
    ['actor-mapped-mismatch', async () => {
      expect(hasExactAuthenticatedStudentSession(
        authenticatedSession(),
        { ...actor(), is_minor: true },
      )).toBe(false);
    }],
    ['probe-recombined-channels', async () => {
      const { ambient, bearer } = exactProbePair();
      bearer.request = ambient.request;
      expect(inspectIndependentProtectedProbes(ambient, bearer).pass).toBe(false);
    }],
    ['probe-missing-ambient', async () => {
      const { bearer } = exactProbePair();
      expect(inspectIndependentProtectedProbes(undefined, bearer).pass).toBe(false);
    }],
    ['probe-missing-bearer', async () => {
      const { ambient } = exactProbePair();
      expect(inspectIndependentProtectedProbes(ambient, undefined).pass).toBe(false);
    }],
    ['probe-channel-isolation-bypass', async () => {
      await expect(hasExactProtectedAuthorityChannel(
        ambientRequest(OPAQUE, { headers: [
          { name: 'Cookie', value: `${SESSION_COOKIE}=${OPAQUE}` },
          { name: 'Authorization', value: `Bearer ${OPAQUE}` },
        ] }),
        'ambient', SESSION_COOKIE, OPAQUE, API,
      )).resolves.toBe(false);
      await expect(hasExactProtectedAuthorityChannel(
        bearerRequest(OPAQUE, { headers: [
          { name: 'Authorization', value: `Bearer ${OPAQUE}` },
          { name: 'Cookie', value: `${SESSION_COOKIE}=${OPAQUE}` },
        ] }),
        'bearer', SESSION_COOKIE, OPAQUE, API,
      )).resolves.toBe(false);
      await expect(hasExactProtectedAuthorityChannel(
        bearerRequest('wrong'),
        'bearer', SESSION_COOKIE, OPAQUE, API,
      )).resolves.toBe(false);
    }],
    ['probe-cardinality-or-verdict-bypass', async () => {
      const variants = [];
      for (const mutation of [
        (pair) => { pair.ambient.requestCount = 2; },
        (pair) => { pair.ambient.channelExact = false; },
        (pair) => { pair.bearer.denialExact = false; },
        (pair) => { pair.bearer.cookiesBefore = 1; },
        (pair) => { pair.bearer.cookiesAfter = 1; },
      ]) {
        const pair = exactProbePair();
        mutation(pair);
        variants.push(pair);
      }
      for (const pair of variants) {
        expect(inspectIndependentProtectedProbes(pair.ambient, pair.bearer).pass).toBe(false);
      }
    }],
    ['denial-wrong-status', async () => {
      await expect(hasExactAuthenticationRequired(
        denialResponse({ status: 403 }),
        denialBody(),
      )).resolves.toBe(false);
    }],
    ['denial-envelope-shape', async () => {
      for (const body of [
        { detail: denialBody().detail },
        { ...denialBody(), extra: true },
        denialBody({ detail: { ...denialBody().detail, extra: true } }),
        denialBody({ detail: { code: 'authentication_required', message: 'wrong' } }),
        denialBody({ detail: { code: 'wrong', message: 'Request failed' } }),
      ]) {
        await expect(hasExactAuthenticationRequired(denialResponse(), body)).resolves.toBe(false);
      }
    }],
    ['denial-request-id-integrity', async () => {
      const variants = [
        [denialResponse(), denialBody({ request_id: 'not-hex' })],
        [denialResponse(), denialBody({ request_id: '1123456789abcdef0123456789abcdef' })],
        [denialResponse({ headers: [] }), denialBody()],
        [denialResponse({ headers: [
          { name: 'X-Request-ID', value: REQUEST_ID },
          { name: 'x-request-id', value: REQUEST_ID },
        ] }), denialBody()],
      ];
      for (const [response, body] of variants) {
        await expect(hasExactAuthenticationRequired(response, body)).resolves.toBe(false);
      }
    }],
    ['source-lifecycle-oracle-bypass', async (source) => {
      for (const [from, to] of [
        ['const summary = summarizeNyay19Rows(rows);', 'const summary = { failed: 0 };'],
        ['if (summary.failed > 0) process.exitCode = 1;', 'process.exitCode = 0;'],
        ["'setup-disposable-student',", "'setup-disposable-student-mutated',"],
        ['const mutationTraceInspection = await inspectExactOrderedMutationTrace(', 'const mutationTraceInspection = await Boolean('],
        ['const logoutRetirement = inspectCookieRetirementHeaders(', 'const logoutRetirement = Object.assign('],
        ['const boundaryDelete = inspectStudentContextBoundary(beforeDelete, afterDelete);', 'const boundaryDelete = { pass: true };'],
        ['const evidencePrivacyExact = scanNyay19Evidence(', 'const evidencePrivacyExact = Boolean('],
        ['  await latestOtp(mobile);\n  const cookiesBeforeLogout', '  const cookiesBeforeLogout'],
        ['const logoutStaleProbes = await independentStaleAuthorityProbes(browser, rawCookieB);', 'const logoutStaleProbes = { pass: true };'],
        ["localStorage.setItem('nyayone.theme.v1', 'dark');", "localStorage.setItem('ls-theme', 'dark');"],
        ["retiredLocale: localStorage.getItem('ls-locale')", 'retiredLocale: null'],
        ["retiredReviewer: localStorage.getItem('ls-reviewer')", 'retiredReviewer: null'],
        ["retiredOnboardingSeen: localStorage.getItem('ls-onboarding-seen')", 'retiredOnboardingSeen: null'],
        ['const ambient = await ambientCookieOnlyProtectedProbe(browser, rawCookie);', 'const ambient = await bearerOnlyProtectedProbe(browser, rawCookie);'],
        ['const bearer = await bearerOnlyProtectedProbe(browser, rawCookie);', 'const bearer = ambient;'],
        ['return inspectIndependentProtectedProbes(ambient, bearer);', 'return { pass: true };'],
        ['mutationTrace.push({ snapshot: snapshotNyay19MutationRequest(request) });', 'mutationTrace.push({ request });'],
        ['inspectionReadable: mutationTraceInspection.inspectionReadable', 'inspectionReadable: true'],
        ['components: mutationTraceInspection.components', 'components: []'],
        ['const captureProviderCleared = await clearCaptureEvidence();', 'const captureProviderCleared = { pass: true };'],
        ['denialExact: await hasExactAuthenticationRequired(response, body)', 'denialExact: true'],
        [
          'buildNyay19AbortEnvelope(currentStage, error, rows.length)',
          'buildNyay19AbortEnvelope(currentStage, error, 0)',
        ],
        [
          'const abortEnvelope = scanNyay19Evidence(',
          'const abortEnvelope = Boolean(',
        ],
        [
          'process.stderr.write(`${JSON.stringify(abortEnvelope)}\\n`);',
          'process.stderr.write(`${JSON.stringify(error)}\\n`);',
        ],
        ["currentStage = 'expiry_stale_probe';", "currentStage = 'expiry_wait';"],
      ]) {
        rejectSourceMutation(source, (value) => value.replaceAll(from, to), from);
      }
      for (const field of [
        'loginA.startCookieTransitionExact',
        'loginB.startCookieTransitionExact',
        'loginExpiry.startCookieTransitionExact',
        'loginDelete.startCookieTransitionExact',
        'recoveryForLogout.startCookieTransitionExact',
        'recoveryStartTransition.pass',
        'captureProviderCleared.pass',
      ]) {
        rejectSourceMutation(source, (value) => value.replaceAll(field, 'true'));
      }
      for (const invalid of [
        inspectCaptureFinality(
          { status: 500, body: { status: 'reset' } },
          [{ status: 200, body: {} }, { status: 200, body: {} }],
        ),
        inspectCaptureFinality(
          { status: 200, body: { status: 'reset' } },
          [{ status: 200, body: {} }],
        ),
        inspectCaptureFinality(
          { status: 200, body: { status: 'reset' } },
          [{ status: 200, body: {} }, { status: 200, body: { code: 'late' } }],
        ),
      ]) expect(invalid.pass).toBe(false);
    }],
  ];
  it.each(advancedMutants)('kills seeded mutant %s', async (_name, exercise) => {
    const source = readFileSync(resolve('scripts/nyay19-auth-lifecycle-browser.mjs'), 'utf8');
    await exercise(source);
  });

  it('executes every pinned seeded mutant exactly once', () => {
    const covered = [
      ...assertionMutants,
      ...originMutants,
      ...traceMutants,
      ...cookieMutants,
      ...issuanceMutants,
      ...flowIssuanceMutants,
      ...retirementMutants,
      ...legacyRetirementMutants,
      ...contextMutants,
      ...evidenceMutants,
      ...advancedMutants,
    ].map(([name]) => name);
    expect(covered).toEqual(NYAY19_SEEDED_MUTANT_INVENTORY);
    expect(new Set(covered).size).toBe(covered.length);
    expect(covered).toHaveLength(82);
  });
});
