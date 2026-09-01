export const CANONICAL_READINESS_RESPONSES = Object.freeze({
  session: Object.freeze({ method: 'GET', path: '/api/v1/auth/student/session' }),
  profile: Object.freeze({ method: 'GET', path: '/api/v1/student/profile' }),
  otpState: Object.freeze({ method: 'GET', path: '/api/v1/auth/student/otp/state' }),
});

export const READINESS_DIAGNOSTIC_FIELDS = Object.freeze([
  'stage',
  'kind',
  'method',
  'path',
  'status',
  'errorClass',
]);

class CanonicalReadinessError extends Error {
  constructor(code, diagnostic) {
    super(code);
    this.name = 'CanonicalReadinessError';
    this.diagnostic = Object.freeze(diagnostic);
  }
}

function safeDiagnostic(stage, kind, descriptor, status, errorClass) {
  return {
    stage,
    kind,
    method: descriptor.method,
    path: descriptor.path,
    status,
    errorClass,
  };
}

function canonicalApiOriginError() {
  return new CanonicalReadinessError('CANONICAL_API_ORIGIN_INVALID', safeDiagnostic(
    'arm', 'unknown', { method: 'GET', path: '/' }, null, 'CANONICAL_API_ORIGIN_INVALID',
  ));
}

export function isCanonicalReadinessResponse(response, apiOrigin, descriptor) {
  const url = new URL(response.url());
  return response.request().method() === descriptor.method
    && url.origin === apiOrigin
    && url.pathname === descriptor.path
    && url.search === ''
    && url.hash === '';
}

export function armCanonicalReadiness(page, { apiOrigin, requirements, stage = 'observe' }) {
  let normalizedOrigin;
  try {
    normalizedOrigin = new URL(apiOrigin).origin;
  } catch {
    throw canonicalApiOriginError();
  }
  if (normalizedOrigin !== apiOrigin) {
    throw canonicalApiOriginError();
  }
  const frozenRequirements = Object.freeze([...requirements]);
  const kinds = frozenRequirements.map((requirement) => requirement.kind);
  if (new Set(kinds).size !== kinds.length) {
    throw new CanonicalReadinessError('CANONICAL_RESPONSE_REQUIREMENT_DUPLICATE', safeDiagnostic(
      'arm', 'unknown', { method: 'GET', path: '/' }, null,
      'CANONICAL_RESPONSE_REQUIREMENT_DUPLICATE',
    ));
  }
  const pending = frozenRequirements.map((requirement) => {
    const descriptor = CANONICAL_READINESS_RESPONSES[requirement.kind];
    if (!descriptor) {
      throw new CanonicalReadinessError('CANONICAL_RESPONSE_REQUIREMENT_UNKNOWN', safeDiagnostic(
        'arm', 'unknown', { method: 'GET', path: '/' }, null,
        'CANONICAL_RESPONSE_REQUIREMENT_UNKNOWN',
      ));
    }
    const safeStage = typeof stage === 'string' && /^[a-z0-9_-]+$/u.test(stage)
      ? stage
      : 'observe';
    return Object.freeze({
      descriptor,
      kind: requirement.kind,
      promise: page.waitForResponse((response) => (
        isCanonicalReadinessResponse(response, normalizedOrigin, descriptor)
      )).catch(() => {
        throw new CanonicalReadinessError('CANONICAL_RESPONSE_UNOBSERVED', safeDiagnostic(
          safeStage, requirement.kind, descriptor, null, 'CANONICAL_RESPONSE_UNOBSERVED',
        ));
      }),
    });
  });
  return Object.freeze({
    pending: Object.freeze(pending),
    requirements: frozenRequirements,
  });
}

export async function settleCanonicalReadiness(armed) {
  const responses = new Map();
  const diagnostics = [];
  for (const pending of armed.pending) {
    const response = await pending.promise;
    let finishedError;
    try {
      finishedError = await response.finished();
    } catch {
      throw new CanonicalReadinessError('CANONICAL_RESPONSE_UNFINISHED', safeDiagnostic(
        'settle', pending.kind, pending.descriptor, response.status(),
        'CANONICAL_RESPONSE_UNFINISHED',
      ));
    }
    if (finishedError !== null) {
      throw new CanonicalReadinessError('CANONICAL_RESPONSE_UNFINISHED', safeDiagnostic(
        'settle', pending.kind, pending.descriptor, response.status(),
        'CANONICAL_RESPONSE_UNFINISHED',
      ));
    }
    if (response.status() !== 200) {
      throw new CanonicalReadinessError('CANONICAL_RESPONSE_STATUS_INVALID', safeDiagnostic(
        'settle', pending.kind, pending.descriptor, response.status(),
        'CANONICAL_RESPONSE_STATUS_INVALID',
      ));
    }
    const diagnostic = Object.freeze(safeDiagnostic(
      'settle', pending.kind, pending.descriptor, response.status(), null,
    ));
    diagnostics.push(diagnostic);
    responses.set(pending.kind, Object.freeze({ diagnostic, response }));
  }
  return Object.freeze({
    diagnostics: Object.freeze(diagnostics),
    get(kind) {
      return responses.get(kind);
    },
  });
}

export async function waitForRouteDomSettled(
  page,
  expectedPath,
  { settledReadiness, selector, expectedSearch = '' },
) {
  const readiness = await settledReadiness;
  await page.waitForURL((url) => (
    url.pathname === expectedPath && url.search === expectedSearch && url.hash === ''
  ));
  await page.locator(selector).waitFor({ state: 'visible' });
  return readiness;
}

export async function waitForVisualCensusSettled(
  page,
  {
    assertion,
    expectedTheme,
    requireRevisionLLockup,
    readinessAttempts = 1,
  },
) {
  if (assertion !== 'browser:redesigned_heading_stack' || readinessAttempts !== 1) {
    throw new CanonicalReadinessError('VISUAL_CENSUS_CONTRACT_INVALID', safeDiagnostic(
      'visual', 'unknown', { method: 'GET', path: '/' }, null,
      'VISUAL_CENSUS_CONTRACT_INVALID',
    ));
  }
  await page.waitForFunction(({ theme, lockupRequired }) => {
    const activeTheme = document.documentElement.getAttribute('data-theme');
    const lockup = document.querySelector('.v321-lockup');
    return activeTheme === theme && (!lockupRequired || lockup instanceof SVGElement);
  }, { theme: expectedTheme, lockupRequired: requireRevisionLLockup });
  await page.evaluate(async () => {
    await document.fonts.ready;
    await new Promise((resolveFrame) => requestAnimationFrame(resolveFrame));
    await new Promise((resolveFrame) => requestAnimationFrame(resolveFrame));
  });
  return Object.freeze({
    assertion,
    expectedTheme,
    lockupRequired: requireRevisionLLockup,
    readinessAttempts,
  });
}
