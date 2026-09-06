import {
  armCanonicalReadiness, settleCanonicalReadiness,
  waitForRouteDomSettled, waitForVisualCensusSettled,
} from './browser-response-readiness.mjs';

/** Deterministic schedule against the production seam, not a constant PASS marker. */
export async function runSeededWave3ReadinessVariance({ attempts }) {
  if (attempts !== 1) throw new Error('NYAY37_VARIANCE_RETRY_FORBIDDEN');
  const events = [];
  const observers = [];
  const state = { route: false, response: false, dom: false, visual: false };
  function sample() {
    if (!Object.values(state).every(Boolean)) throw new Error('FAIL_EARLY_SAMPLE');
    events.push('sample');
    return 'PASS';
  }
  const page = {
    waitForResponse(predicate) {
      events.push('arm');
      return new Promise(resolve => observers.push({ predicate, resolve }));
    },
    async waitForURL(predicate) {
      if (!state.route || !predicate(new URL('https://web.example.test/s-82'))) throw new Error('ROUTE_UNSETTLED');
    },
    locator() { return { async waitFor() {
      if (!state.response) throw new Error('DOM_BEFORE_RESPONSE');
      state.dom = true; events.push('route-dom');
    } }; },
    async waitForFunction() {
      if (!state.dom) throw new Error('VISUAL_BEFORE_DOM');
    },
    async evaluate() { state.visual = true; events.push('font-theme-lockup'); },
  };
  const armed = armCanonicalReadiness(page, {
    apiOrigin: 'https://api.example.test', requirements: [{ kind: 'session' }], stage: 'wave3_seed',
  });
  state.route = true; events.push('navigate');
  let legacyOutcome;
  try { sample(); } catch (error) { legacyOutcome = error.message; }
  const response = query => ({
    url: () => `https://api.example.test/api/v1/auth/student/session${query}`,
    request: () => ({ method: () => 'GET' }), status: () => 200,
    async finished() { state.response = true; events.push('response-finished'); return null; },
  });
  // The misleading query-bearing response arrives first and must not settle authority.
  for (const observer of observers) {
    if (observer.predicate(response('?not-canonical=1'))) throw new Error('QUERY_RESPONSE_ACCEPTED');
    if (!observer.predicate(response(''))) throw new Error('CANONICAL_RESPONSE_REJECTED');
    observer.resolve(response(''));
  }
  const settledReadiness = settleCanonicalReadiness(armed);
  await waitForRouteDomSettled(page, '/s-82', { settledReadiness, selector: '[data-screen="S-82"]' });
  await waitForVisualCensusSettled(page, {
    assertion: 'browser:redesigned_heading_stack', expectedTheme: 'dark',
    requireRevisionLLockup: false, readinessAttempts: 1,
  });
  return { attempts, legacyOutcome, settledOutcome: sample(), events };
}
