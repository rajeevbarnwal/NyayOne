export const NYAY19_ASSERTION_INVENTORY = Object.freeze([
  'setup-disposable-student',
  'login-a-authority-cookie',
  'actor-a-context-seeded',
  'rotation-b-invalidates-a',
  'rotation-a-retirement-and-clear',
  'logout-precondition-two-cookies',
  'logout-cookie-retirement',
  'logout-context-clear',
  'expiry-login-and-context-seed',
  'expiry-anonymous-and-retirement',
  'expiry-context-clear',
  'deletion-login-and-context-seed',
  'deletion-reauth-authority',
  'deletion-cookie-retirement-and-ack',
  'deletion-context-clear',
  'deletion-stale-cookie-denied',
  'browser-mutation-trace',
  'evidence-privacy-and-finality',
]);

export const NYAY19_MUTATION_TRACE = Object.freeze([
  Object.freeze({ path: '/api/v1/auth/student/login/otp/start', body: 'mobile' }),
  Object.freeze({ path: '/api/v1/auth/student/login/otp/verify', body: 'code' }),
  Object.freeze({ path: '/api/v1/auth/student/login/otp/start', body: 'mobile' }),
  Object.freeze({ path: '/api/v1/auth/student/login/otp/verify', body: 'code' }),
  Object.freeze({ path: '/api/v1/auth/student/recovery/start', body: 'mobile' }),
  Object.freeze({ path: '/api/v1/auth/student/logout', body: 'empty' }),
  Object.freeze({ path: '/api/v1/auth/student/login/otp/start', body: 'mobile' }),
  Object.freeze({ path: '/api/v1/auth/student/login/otp/verify', body: 'code' }),
  Object.freeze({ path: '/api/v1/auth/student/login/otp/start', body: 'mobile' }),
  Object.freeze({ path: '/api/v1/auth/student/login/otp/verify', body: 'code' }),
  Object.freeze({ path: '/api/v1/auth/student/recovery/start', body: 'mobile' }),
  Object.freeze({ path: '/api/v1/auth/student/recovery/verify', body: 'code' }),
  Object.freeze({ path: '/api/v1/student/privacy/delete', body: 'confirmation' }),
]);

export const NYAY19_ABORT_STAGE_INVENTORY = Object.freeze([
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

export const NYAY19_ABORT_EXCEPTION_CLASS_INVENTORY = Object.freeze([
  'timeout',
  'error',
  'non_error',
]);

export const NYAY19_SEEDED_MUTANT_INVENTORY = Object.freeze([
  'assertion-missing-row',
  'assertion-extra-row',
  'assertion-duplicate-row',
  'assertion-reordered-rows',
  'assertion-untyped-verdict',
  'origin-missing',
  'origin-wrong',
  'origin-duplicate',
  'trace-missing-request',
  'trace-extra-request',
  'trace-reordered-request',
  'trace-wrong-method',
  'trace-wrong-api-origin',
  'trace-wrong-path',
  'trace-wrong-query',
  'trace-missing-body-key',
  'trace-extra-body-key',
  'trace-invalid-mobile-shape',
  'trace-invalid-code-shape',
  'trace-invalid-confirmation',
  'trace-nonempty-logout',
  'trace-unreadable-body',
  'cookie-extra-cookie',
  'cookie-wrong-name',
  'cookie-duplicate-cookie',
  'cookie-domain-cookie',
  'cookie-wrong-attributes',
  'issuance-domain-attribute',
  'issuance-wrong-max-age',
  'issuance-missing-flow-retirement',
  'issuance-empty-value',
  'issuance-wrong-attributes',
  'issuance-duplicate-attribute',
  'issuance-wrong-order-cardinality',
  'flow-issuance-missing',
  'flow-issuance-wrong-max-age',
  'flow-issuance-domain-attribute',
  'flow-issuance-duplicate-header',
  'retirement-missing-header',
  'retirement-extra-header',
  'retirement-reordered-header',
  'retirement-nonempty-value',
  'retirement-domain-attribute',
  'retirement-wrong-attributes',
  'retirement-invalid-max-age-or-expiry',
  'retirement-duplicate-attribute',
  'context-unseeded-memory',
  'context-retained-storage',
  'context-retained-query-cache',
  'context-retained-mutation-cache',
  'context-retained-registration-attempt',
  'context-retained-profile-draft',
  'context-removed-control',
  'evidence-mobile',
  'evidence-otp',
  'evidence-bearer',
  'evidence-uuid',
  'evidence-explicit-secret',
  'expiry-natural-demands-retirement',
  'expiry-stale-skips-retirement',
  'cooldown-invalid-config',
  'cooldown-wait-removed',
  'cooldown-post-response-anchor-bypass',
  'flow-ttl-invalid-config',
  'lifecycle-expiry-attribution-bypass',
  'actor-extra-field',
  'actor-wrong-role',
  'actor-mapped-mismatch',
  'probe-recombined-channels',
  'probe-missing-ambient',
  'probe-missing-bearer',
  'probe-channel-isolation-bypass',
  'probe-cardinality-or-verdict-bypass',
  'denial-wrong-status',
  'denial-envelope-shape',
  'denial-request-id-integrity',
  'source-lifecycle-oracle-bypass',
]);

export function parseNyay19SessionTtl(value) {
  if (typeof value !== 'string' || !/^(?:[2-9]|[12]\d|30)$/u.test(value)) {
    throw new Error('NYAY19_SESSION_TTL_INVALID');
  }
  return Number.parseInt(value, 10);
}

export function parseNyay19OtpCooldown(value) {
  if (value !== '1') throw new Error('NYAY19_OTP_COOLDOWN_INVALID');
  return 1;
}

export function parseNyay19OtpFlowTtl(value) {
  if (typeof value !== 'string' || !/^[1-9]\d{0,3}$/u.test(value)) {
    throw new Error('NYAY19_OTP_FLOW_TTL_INVALID');
  }
  const parsed = Number.parseInt(value, 10);
  if (parsed > 3_600) throw new Error('NYAY19_OTP_FLOW_TTL_INVALID');
  return parsed;
}

export function nextNyay19LoginIssuanceDelay(lastIssuedAt, now, cooldownSeconds) {
  if (!Number.isFinite(lastIssuedAt)
      || !Number.isFinite(now)
      || cooldownSeconds !== 1) return Number.NaN;
  return Math.max(0, lastIssuedAt + (cooldownSeconds * 1_000) + 250 - now);
}

export function inspectNyay19SessionBootstrap(observation) {
  const countFields = ['requestCount', 'responseCount', 'finishedCount', 'failedCount'];
  const countsValid = observation
    && countFields.every((field) => (
      Number.isSafeInteger(observation[field]) && observation[field] >= 0
    ));
  const requestCount = countsValid ? observation.requestCount : 0;
  const responseCount = countsValid ? observation.responseCount : 0;
  const finishedCount = countsValid ? observation.finishedCount : 0;
  const failedCount = countsValid ? observation.failedCount : 0;
  const exactCardinality = Boolean(countsValid)
    && requestCount === 2
    && responseCount === 2;
  const finishedSettlementExact = exactCardinality
    && finishedCount === 2
    && failedCount === 0;
  const responsesSuccessful = observation?.responsesSuccessful === true;
  return {
    expectedCount: 2,
    requestCount,
    responseCount,
    finishedCount,
    failedCount,
    countsValid: Boolean(countsValid),
    exactCardinality,
    finishedSettlementExact,
    responsesSuccessful,
    pass: finishedSettlementExact && responsesSuccessful,
  };
}

export function buildNyay19AbortEnvelope(stage, error, rowsCompleted) {
  const safeStage = NYAY19_ABORT_STAGE_INVENTORY.includes(stage) ? stage : 'unknown';
  const errorLike = (typeof error === 'object' && error !== null) || typeof error === 'function';
  let errorName = errorLike ? 'Error' : null;
  if (errorLike) {
    try { if (typeof error.name === 'string') errorName = error.name; } catch { /* map below */ }
  }
  const timeout = errorName === 'TimeoutError'
    || errorName === 'Nyay19BootstrapTimeoutError';
  const exceptionClass = timeout
    ? 'timeout'
    : errorName === null ? 'non_error' : 'error';
  const safeRowsCompleted = Number.isSafeInteger(rowsCompleted)
      && rowsCompleted >= 0
      && rowsCompleted <= NYAY19_ASSERTION_INVENTORY.length
    ? rowsCompleted
    : 0;
  return {
    marker: 'NYAY19_BROWSER_GATE_ABORTED',
    stage: safeStage,
    exceptionClass,
    timeout: exceptionClass === 'timeout',
    rowsCompleted: safeRowsCompleted,
  };
}

export function hasFutureCookieExpiry(cookie, now, marginMs = 1_000) {
  return cookie
    && typeof cookie.expires === 'number'
    && Number.isFinite(cookie.expires)
    && Number.isFinite(now)
    && Number.isFinite(marginMs)
    && marginMs >= 0
    && (cookie.expires * 1_000) > now + marginMs;
}

export async function hasExactSingleOrigin(request, expectedOrigin) {
  try {
    const headers = await request.headersArray();
    if (!Array.isArray(headers)) return false;
    const origins = headers.filter((header) => (
      header
      && typeof header.name === 'string'
      && header.name.toLowerCase() === 'origin'
    ));
    return origins.length === 1
      && typeof origins[0].value === 'string'
      && origins[0].value === expectedOrigin;
  } catch {
    return false;
  }
}

function hasExactSingleOriginHeaders(headers, expectedOrigin) {
  if (!Array.isArray(headers)) return false;
  const origins = headers.filter((header) => (
    header
    && typeof header.name === 'string'
    && header.name.toLowerCase() === 'origin'
  ));
  return origins.length === 1
    && typeof origins[0].value === 'string'
    && origins[0].value === expectedOrigin;
}

export async function hasExactProtectedAuthorityChannel(
  request,
  channel,
  cookieName,
  rawValue,
  expectedOrigin,
  expectedPath = '/api/v1/student/profile',
) {
  if (!request || !['ambient', 'bearer'].includes(channel)) return false;
  try {
    const headers = await request.headersArray();
    if (!Array.isArray(headers)) return false;
    const authorization = headers.filter((header) => (
      header?.name?.toLowerCase() === 'authorization'
    ));
    const cookies = headers.filter((header) => header?.name?.toLowerCase() === 'cookie');
    const url = new URL(request.url());
    const requestExact = request.method() === 'GET'
      && url.origin === expectedOrigin
      && url.pathname === expectedPath
      && url.search === ''
      && url.hash === '';
    if (channel === 'ambient') {
      return requestExact
        && authorization.length === 0
        && cookies.length === 1
        && cookies[0].value === `${cookieName}=${rawValue}`;
    }
    return requestExact
      && authorization.length === 1
      && authorization[0].value === `Bearer ${rawValue}`
      && cookies.length === 0;
  } catch {
    return false;
  }
}

export async function hasExactAuthenticationRequired(response, body) {
  try {
    const headers = await response.headersArray();
    if (!Array.isArray(headers)) return false;
    const requestIds = headers.filter((header) => (
      header?.name?.toLowerCase() === 'x-request-id'
    ));
    return response.status() === 401
      && body
      && typeof body === 'object'
      && Object.keys(body).sort().join(',') === 'detail,request_id'
      && body.detail
      && typeof body.detail === 'object'
      && Object.keys(body.detail).sort().join(',') === 'code,message'
      && body.detail.code === 'authentication_required'
      && body.detail.message === 'Request failed'
      && typeof body.request_id === 'string'
      && /^[\da-f]{32}$/u.test(body.request_id)
      && requestIds.length === 1
      && requestIds[0].value === body.request_id;
  } catch {
    return false;
  }
}

export function inspectIndependentProtectedProbes(ambient, bearer) {
  const distinct = ambient?.request && bearer?.request && ambient.request !== bearer.request;
  const ambientExact = ambient?.channel === 'ambient'
    && ambient.requestCount === 1
    && ambient.channelExact === true
    && ambient.denialExact === true;
  const bearerExact = bearer?.channel === 'bearer'
    && bearer.requestCount === 1
    && bearer.cookiesBefore === 0
    && bearer.cookiesAfter === 0
    && bearer.channelExact === true
    && bearer.denialExact === true;
  return {
    distinct: Boolean(distinct),
    ambientExact,
    bearerExact,
    pass: Boolean(distinct) && ambientExact && bearerExact,
  };
}

export function inspectCaptureFinality(reset, reads) {
  const resetExact = reset?.status === 200
    && reset?.body
    && typeof reset.body === 'object'
    && !Array.isArray(reset.body)
    && Object.keys(reset.body).join(',') === 'status'
    && reset.body.status === 'reset';
  const emptyReads = Array.isArray(reads)
    && reads.length === 2
    && reads.every((read) => (
      read?.status === 200
      && read.body
      && typeof read.body === 'object'
      && !Array.isArray(read.body)
      && Object.keys(read.body).length === 0
    ));
  return {
    resetExact: Boolean(resetExact),
    emptyReadCount: Array.isArray(reads)
      ? reads.filter((read) => read?.body && Object.keys(read.body).length === 0).length
      : 0,
    settledEmptyTwice: Boolean(emptyReads),
    pass: Boolean(resetExact) && Boolean(emptyReads),
  };
}

export function hasExactAuthenticatedStudentSession(body, mappedActor) {
  if (!body
      || typeof body !== 'object'
      || Object.keys(body).sort().join(',') !== 'actor,authenticated'
      || body.authenticated !== true
      || !body.actor
      || typeof body.actor !== 'object') return false;
  const actor = body.actor;
  const actorKeys = [
    'consent_state', 'is_minor', 'roles', 'student_profile_id',
    'student_verification', 'sub',
  ];
  const canonicalUuid = /^[\da-f]{8}-[\da-f]{4}-[1-5][\da-f]{3}-[89ab][\da-f]{3}-[\da-f]{12}$/u;
  const consentExact = Array.isArray(actor.consent_state)
    && actor.consent_state.every((value) => typeof value === 'string' && value.length > 0)
    && new Set(actor.consent_state).size === actor.consent_state.length
    && [...actor.consent_state].sort().every((value, index) => value === actor.consent_state[index]);
  return Object.keys(actor).sort().join(',') === actorKeys.join(',')
    && canonicalUuid.test(actor.sub)
    && Array.isArray(actor.roles)
    && actor.roles.length === 1
    && actor.roles[0] === 'student'
    && (actor.student_profile_id === null || canonicalUuid.test(actor.student_profile_id))
    && ['draft', 'verified'].includes(actor.student_verification)
    && typeof actor.is_minor === 'boolean'
    && consentExact
    && mappedActor
    && JSON.stringify(mappedActor) === JSON.stringify(actor);
}

function hasExactBodyShape(body, expectedShape) {
  if (!body || typeof body !== 'object' || Array.isArray(body)) return false;
  const keys = Object.keys(body).sort();
  if (expectedShape === 'empty') return keys.length === 0;
  if (expectedShape === 'mobile') {
    return keys.join(',') === 'mobile' && /^\d{10}$/u.test(body.mobile);
  }
  if (expectedShape === 'code') {
    return keys.join(',') === 'code' && /^\d{6}$/u.test(body.code);
  }
  return expectedShape === 'confirmation'
    && keys.join(',') === 'confirmation'
    && body.confirmation === 'DELETE';
}

export async function snapshotNyay19MutationRequest(request) {
  try {
    // Invoke every Playwright accessor while the request event is current.
    // The returned promise may settle later, but no metadata read is deferred
    // across navigations or the deliberate session-expiry wait.
    const method = request.method();
    const rawUrl = request.url();
    const body = request.postDataJSON();
    const headers = await request.headersArray();
    return { readable: true, method, rawUrl, body, headers };
  } catch {
    return { readable: false };
  }
}

async function resolveMutationProjection(entry) {
  if (entry?.snapshot) {
    try { return await entry.snapshot; } catch { return { readable: false }; }
  }
  if (!entry?.request) return { readable: false };
  return snapshotNyay19MutationRequest(entry.request);
}

export async function inspectExactOrderedMutationTrace(
  trace,
  expected,
  expectedOrigin,
  expectedApiOrigin,
) {
  const traceArray = Array.isArray(trace) ? trace : [];
  const expectedArray = Array.isArray(expected) ? expected : [];
  const exactCardinality = Array.isArray(trace)
    && Array.isArray(expected)
    && expected.length > 0
    && trace.length === expected.length;
  const components = await Promise.all(expectedArray.map(async (oracle, index) => {
    const projection = await resolveMutationProjection(traceArray[index]);
    const base = {
      slot: index,
      inspectionReadable: projection?.readable === true,
      methodExact: false,
      apiOriginExact: false,
      pathExact: false,
      emptySearch: false,
      emptyHash: false,
      bodyShapeExact: false,
      originHeaderExact: false,
      pass: false,
    };
    if (!oracle || projection?.readable !== true) return base;
    try {
      const url = new URL(projection.rawUrl);
      const component = {
        ...base,
        methodExact: projection.method === 'POST',
        apiOriginExact: url.origin === expectedApiOrigin,
        pathExact: url.pathname === oracle.path,
        emptySearch: url.search === '',
        emptyHash: url.hash === '',
        bodyShapeExact: hasExactBodyShape(projection.body, oracle.body),
        originHeaderExact: hasExactSingleOriginHeaders(projection.headers, expectedOrigin),
      };
      component.pass = component.methodExact
        && component.apiOriginExact
        && component.pathExact
        && component.emptySearch
        && component.emptyHash
        && component.bodyShapeExact
        && component.originHeaderExact;
      return component;
    } catch {
      return base;
    }
  }));
  const failingSlots = components.filter((component) => !component.pass)
    .map((component) => component.slot);
  return {
    expectedCount: expectedArray.length,
    observedCount: traceArray.length,
    exactCardinality,
    inspectionReadable: exactCardinality
      && components.every((component) => component.inspectionReadable),
    failingSlots,
    components,
    pass: exactCardinality && failingSlots.length === 0,
  };
}

export async function hasExactOrderedMutationTrace(
  trace,
  expected,
  expectedOrigin,
  expectedApiOrigin,
) {
  return (await inspectExactOrderedMutationTrace(
    trace,
    expected,
    expectedOrigin,
    expectedApiOrigin,
  )).pass;
}

function isLocalHttp(url) {
  try {
    const parsed = new URL(url);
    return parsed.protocol === 'http:'
      && ['127.0.0.1', 'localhost', '::1'].includes(parsed.hostname);
  } catch {
    return false;
  }
}

export function inspectAuthorityCookieInventory(cookies, expectedNames, apiBaseUrl) {
  let host = null;
  try { host = new URL(apiBaseUrl).hostname; } catch { /* fail closed below */ }
  const expectedSecure = !isLocalHttp(apiBaseUrl);
  const names = Array.isArray(cookies) ? cookies.map((cookie) => cookie?.name) : [];
  const expectedCounts = new Map();
  for (const name of Array.isArray(expectedNames) ? expectedNames : []) {
    expectedCounts.set(name, (expectedCounts.get(name) ?? 0) + 1);
  }
  const actualCounts = new Map();
  for (const name of names) actualCounts.set(name, (actualCounts.get(name) ?? 0) + 1);
  const exactNames = Array.isArray(expectedNames)
    && names.length === expectedNames.length
    && expectedCounts.size === actualCounts.size
    && [...expectedCounts].every(([name, count]) => actualCounts.get(name) === count);
  const attributesExact = exactNames && cookies.every((cookie) => (
    cookie
    && cookie.domain === host
    && !cookie.domain.startsWith('.')
    && cookie.path === '/api/v1'
    && cookie.httpOnly === true
    && cookie.secure === expectedSecure
    && cookie.sameSite === 'Strict'
    && typeof cookie.value === 'string'
    && cookie.value.length >= 32
    && !/^[-\da-f]{36}$/iu.test(cookie.value)
  ));
  return {
    expectedCount: Array.isArray(expectedNames) ? expectedNames.length : 0,
    total: Array.isArray(cookies) ? cookies.length : 0,
    exactNames,
    attributesExact,
    pass: exactNames && attributesExact,
  };
}

function parseSetCookie(raw) {
  if (typeof raw !== 'string') return null;
  const segments = raw.split(';').map((segment) => segment.trim());
  const firstEquals = segments[0]?.indexOf('=') ?? -1;
  if (firstEquals <= 0) return null;
  const name = segments[0].slice(0, firstEquals);
  const rawValue = segments[0].slice(firstEquals + 1);
  const attributes = new Map();
  for (const segment of segments.slice(1)) {
    if (!segment) return null;
    const equals = segment.indexOf('=');
    const key = (equals === -1 ? segment : segment.slice(0, equals)).toLowerCase();
    const value = equals === -1 ? true : segment.slice(equals + 1);
    if (attributes.has(key)) return null;
    attributes.set(key, value);
  }
  return { name, rawValue, attributes };
}

function inspectRetirement(cookie, expectedSecure) {
  const allowedAttributes = new Set([
    'expires', 'httponly', 'max-age', 'path', 'samesite', ...(expectedSecure ? ['secure'] : []),
  ]);
  const expiry = cookie?.attributes?.get('expires');
  const expiryTime = typeof expiry === 'string' ? Date.parse(expiry) : Number.NaN;
  const component = {
    parsed: Boolean(cookie),
    emptyValue: cookie?.rawValue === '' || cookie?.rawValue === '""',
    attributeCardinalityExact: cookie?.attributes?.size === allowedAttributes.size,
    onlyExpectedAttributes: Boolean(cookie)
      && [...cookie.attributes.keys()].every((key) => allowedAttributes.has(key)),
    pathExact: cookie?.attributes?.get('path') === '/api/v1',
    httpOnlyExact: cookie?.attributes?.get('httponly') === true,
    maxAgeZero: cookie?.attributes?.get('max-age') === '0',
    sameSiteStrict: typeof cookie?.attributes?.get('samesite') === 'string'
      && cookie.attributes.get('samesite').toLowerCase() === 'strict',
    expiryParseable: Number.isFinite(expiryTime),
    expiryNotFuture: Number.isFinite(expiryTime)
      && expiryTime <= Date.now() + (5 * 60 * 1_000),
    secureExact: expectedSecure
      ? cookie?.attributes?.get('secure') === true
      : Boolean(cookie) && !cookie.attributes.has('secure'),
    domainAbsent: Boolean(cookie) && !cookie.attributes.has('domain'),
  };
  return {
    ...component,
    pass: Object.values(component).every(Boolean),
  };
}

function exactIssuance(cookie, expectedSecure, expectedMaxAge) {
  if (!cookie || !Number.isSafeInteger(expectedMaxAge) || expectedMaxAge <= 0) return false;
  const allowedAttributes = new Set([
    'httponly', 'max-age', 'path', 'samesite', ...(expectedSecure ? ['secure'] : []),
  ]);
  return cookie.rawValue !== ''
    && cookie.rawValue !== '""'
    && cookie.rawValue.length >= 32
    && !/^[-\da-f]{36}$/iu.test(cookie.rawValue)
    && cookie.attributes.size === allowedAttributes.size
    && [...cookie.attributes.keys()].every((key) => allowedAttributes.has(key))
    && cookie.attributes.get('path') === '/api/v1'
    && cookie.attributes.get('httponly') === true
    && cookie.attributes.get('max-age') === String(expectedMaxAge)
    && typeof cookie.attributes.get('samesite') === 'string'
    && cookie.attributes.get('samesite').toLowerCase() === 'strict'
    && (expectedSecure
      ? cookie.attributes.get('secure') === true
      : !cookie.attributes.has('secure'))
    && !cookie.attributes.has('domain')
    && !cookie.attributes.has('expires');
}

export function inspectCookieTransitionHeaders(headers, expected, apiBaseUrl) {
  const expectedSecure = !isLocalHttp(apiBaseUrl);
  const setCookies = Array.isArray(headers)
    ? headers.filter((header) => header?.name?.toLowerCase() === 'set-cookie')
    : [];
  const parsed = setCookies.map((header) => parseSetCookie(header.value));
  const exact = Array.isArray(expected)
    && parsed.length === expected.length
    && parsed.every((cookie, index) => {
      const descriptor = expected[index];
      if (!descriptor || cookie?.name !== descriptor.name) return false;
      if (descriptor.action === 'issue') {
        return exactIssuance(cookie, expectedSecure, descriptor.maxAge);
      }
      return descriptor.action === 'retire' && inspectRetirement(cookie, expectedSecure).pass;
    });
  return {
    expectedCount: Array.isArray(expected) ? expected.length : 0,
    total: setCookies.length,
    exact,
    pass: exact,
  };
}

export function inspectCookieRetirementHeaders(headers, expectedNames, apiBaseUrl) {
  const expectedSecure = !isLocalHttp(apiBaseUrl);
  const setCookies = Array.isArray(headers)
    ? headers.filter((header) => header?.name?.toLowerCase() === 'set-cookie')
    : [];
  const parsed = setCookies.map((header) => parseSetCookie(header.value));
  const exactNames = Array.isArray(expectedNames)
    && parsed.length === expectedNames.length
    && parsed.every((cookie, index) => cookie?.name === expectedNames[index]);
  const exactRetirements = exactNames
    && parsed.every((cookie) => inspectRetirement(cookie, expectedSecure).pass);
  const components = parsed.map((cookie) => inspectRetirement(cookie, expectedSecure));
  return {
    expectedCount: Array.isArray(expectedNames) ? expectedNames.length : 0,
    total: setCookies.length,
    exactNames,
    exactRetirements,
    components,
    pass: exactNames && exactRetirements,
  };
}

function exactControlState(value) {
  return value?.theme === 'dark'
    && value?.locale === 'hi'
    && value?.unrelated === 'retain';
}

export function inspectStudentContextBoundary(before, after) {
  const beforeExact = before?.managedExpectedCount > 0
    && before?.managedPresentCount === before.managedExpectedCount
    && before?.registrationAttemptPresent === true
    && before?.profileDraftPresent === true
    && Number.isSafeInteger(before?.queryCacheCount)
    && before.queryCacheCount > 0
    && Number.isSafeInteger(before?.mutationCacheCount)
    && before.mutationCacheCount > 0
    && exactControlState(before?.controls);
  const afterExact = after?.managedExpectedCount === before?.managedExpectedCount
    && after?.managedPresentCount === 0
    && after?.registrationAttemptPresent === false
    && after?.profileDraftPresent === false
    && after?.queryCacheCount === 0
    && after?.mutationCacheCount === 0
    && exactControlState(after?.controls);
  return { beforeExact, afterExact, pass: beforeExact && afterExact };
}

function containsUnsafeSensitiveField(value) {
  if (Array.isArray(value)) return value.some(containsUnsafeSensitiveField);
  if (!value || typeof value !== 'object') return false;
  return Object.entries(value).some(([key, child]) => {
    const normalized = key.replace(/([a-z])([A-Z])/gu, '$1_$2').toLowerCase();
    if (/(?:^|[_-])(?:token|mobile|otp|code|subject|profile_id|request_id|cookie_value)(?:$|[_-])/u.test(normalized)) {
      return typeof child === 'string' || typeof child === 'number';
    }
    return containsUnsafeSensitiveField(child);
  });
}

export function scanNyay19Evidence(value, forbiddenValues = []) {
  let serialised = '';
  try { serialised = JSON.stringify(value); } catch { return false; }
  if (typeof serialised !== 'string' || containsUnsafeSensitiveField(value)) return false;
  const planted = Array.isArray(forbiddenValues)
    ? forbiddenValues.filter((item) => typeof item === 'string' && item.length > 0)
    : [];
  if (planted.some((item) => serialised.includes(item))) return false;
  return !/\b\d{10}\b/u.test(serialised)
    && !/\b\d{6}\b/u.test(serialised)
    && !/\b[\da-f]{8}-[\da-f]{4}-[1-5][\da-f]{3}-[89ab][\da-f]{3}-[\da-f]{12}\b/iu.test(serialised)
    && !/\bBearer[ \t]+(?=[-A-Za-z0-9._~+/=]{32,}(?![-A-Za-z0-9._~+/=]))[-A-Za-z0-9._~+/]+=*(?![-A-Za-z0-9._~+/=])/iu.test(serialised);
}

export function assertExactAssertionInventory(rows) {
  if (!Array.isArray(rows)) throw new Error('NYAY19_ASSERTION_INVENTORY_MISMATCH');
  const names = rows.map((row) => row?.name);
  const exact = names.length === NYAY19_ASSERTION_INVENTORY.length
    && names.every((name, index) => name === NYAY19_ASSERTION_INVENTORY[index]);
  const unique = new Set(names).size === names.length;
  const typed = rows.every((row) => row && typeof row.pass === 'boolean');
  if (!exact || !unique || !typed) {
    throw new Error('NYAY19_ASSERTION_INVENTORY_MISMATCH');
  }
}

export function summarizeNyay19Rows(rows) {
  assertExactAssertionInventory(rows);
  const passed = rows.filter((row) => row.pass).length;
  return {
    expectedTotal: NYAY19_ASSERTION_INVENTORY.length,
    total: rows.length,
    passed,
    failed: rows.length - passed,
    rows,
  };
}
