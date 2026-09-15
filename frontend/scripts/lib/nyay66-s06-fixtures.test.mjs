import { describe, expect, it, vi } from 'vitest';
import { mockR2Application, R2_LIVE_STATES, R2_STATES, R2_VIEWPORTS } from './nyay66-r2.mjs';

const origin = 'http://127.0.0.1:4317';
const api = '/api/v1/auth/student';
const states = ['entry', 'invalidnum', 'submitting', 'challenge', 'wrong', 'expired', 'locked', 'neterr', 'success'];
const wireKeys = ['attempts_left', 'destination_masked', 'expires_in_seconds', 'locked_for_seconds', 'purpose', 'resend_allowed', 'resend_in_seconds', 'status'];

// A contract double with only real-browser operations: no DOM-writing,
// component fixture, force-click, storage seeding, or navigation suppression.
function browserDouble({ failState, wrongRequest = false, deferStartRequest = false } = {}) {
  let handler, mobile = '', code = '', pendingStart;
  const actions = [], replies = [], waiting = [];
  const page = {
    clock: { setFixedTime: async value => actions.push(['fixed-date', value.toISOString()]) },
    route: async (pattern, fn) => { expect(pattern).toBe('**/*'); handler = fn; },
    waitForResponse: predicate => new Promise(resolve => waiting.push({ predicate, resolve })),
    goto: async url => {
      actions.push(['goto', url]);
      await request(`${api}/session`);
      await request(`${api}/otp/state`);
    },
    url: () => origin + '/s-06',
    locator: selector => ({ waitFor: async () => {
      actions.push(['wait', selector]);
      if (failState && selector.includes(`data-state="${failState}"`)) throw Error('REAL_UI_STATE_MISSING');
    } }),
    getByLabel: (name, options) => ({ fill: async value => {
      actions.push(['fill', name, value, options]);
      if (name === 'Registered mobile number') mobile = value;
      else if (name === 'Six-digit recovery code') code = value;
      else throw Error('UNEXPECTED_FIELD');
    } }),
    getByRole: (role, options) => ({
      click: async clickOptions => {
        actions.push(['click', role, options, clickOptions]);
        if (options.name === 'Send recovery code') {
          if (/^\d{10}$/.test(mobile)) {
            if (deferStartRequest) pendingStart = () => request(`${api}/recovery/start`, 'POST', { mobile });
            else await request(`${api}/recovery/start`, 'POST', { mobile });
          }
        } else if (options.name === 'Verify and continue') {
          const result = await request(`${api}/recovery/verify`, 'POST', wrongRequest ? { code, mobile } : { code });
          if (result?.body?.status === 'verified') await request(`${api}/recovery/complete`, 'POST', {});
        } else if (role === 'heading' && options.name === 'Recover your account.') {
          // Normal pointer interaction on non-interactive content removes the
          // input focus ring without DOM mutations or injected blur calls.
        } else throw Error('UNEXPECTED_CLICK');
      },
      waitFor: async () => actions.push(['heading', role, options]),
    }),
  };
  async function request(path, method = 'GET', body) {
    const url = path.startsWith('http') ? path : origin + path;
    let result;
    await handler({
      request: () => ({ url: () => url, method: () => method, postDataJSON: () => body }),
      abort: async () => { result = { aborted: true }; actions.push(['abort', url]); },
      continue: async () => { result = { continued: true }; },
      fulfill: async response => {
        result = { url, method, status: response.status, body: JSON.parse(response.body), headers: response.headers };
        replies.push(result);
        const responseObject = { url: () => url, status: () => response.status, request: () => ({ method: () => method }), finished: async () => undefined };
        for (const waiter of waiting.splice(0)) {
          if (waiter.predicate(responseObject)) waiter.resolve(responseObject);
          else waiting.push(waiter);
        }
      },
    });
    return result;
  }
  return { page, actions, replies, request, releaseStart: () => pendingStart() };
}

describe('S-06 R2 real-route visual fixtures', () => {
  it('measures all nine approved recovery states at all three immutable viewport rows', () => {
    expect(R2_STATES.filter(row => row.screen === 'S-06').map(row => row.state)).toEqual(states);
    expect(R2_LIVE_STATES.filter(view => view.startsWith('s06-'))).toEqual(states.map(state => `s06-${state}`));
    expect(R2_VIEWPORTS).toHaveLength(3);
  });

  it.each(states)('drives %s through the product route and labels the synthetic fixed display clock', async state => {
    const browser = browserDouble(), errors = [];
    const evidence = await mockR2Application(browser.page, `s06-${state}`, origin, errors);
    expect(errors).toEqual([]);
    expect(evidence).toMatchObject({ evidenceKind: 'live-route', syntheticServer: true, state: `s06-${state}`, displayClock: { kind: 'fixed-date', value: '2026-09-12T09:00:00.000Z', timersRunning: true }, artificialDelay: false, navigationFrozen: false });
    expect(browser.actions.filter(action => action[0] === 'goto')).toEqual([['goto', origin + '/s-06']]);
    expect(browser.actions).toContainEqual(['fixed-date', '2026-09-12T09:00:00.000Z']);
    expect(browser.actions).toContainEqual(['wait', `[data-screen="S-06"][data-state="${state}"]`]);
    expect(evidence.expectedHttpErrors).toEqual(state === 'wrong'
      ? [{ method: 'POST', url: origin + api + '/recovery/verify', status: 401 }]
      : state === 'neterr' ? [{ method: 'POST', url: origin + api + '/recovery/start', status: 503 }] : []);
  });

  it('validates an incomplete number with a normal Send action and makes no recovery request', async () => {
    const browser = browserDouble();
    const evidence = await mockR2Application(browser.page, 's06-invalidnum', origin, []);
    expect(browser.actions).toContainEqual(['fill', 'Registered mobile number', '98765', { exact: true }]);
    expect(browser.actions).toContainEqual(['click', 'button', { name: 'Send recovery code', exact: true }, undefined]);
    expect(evidence.recoveryRequests).toEqual([]);
    expect(browser.replies.some(reply => reply.url.includes('/recovery/'))).toBe(false);
  });

  it('types the entry sample then normally clicks the heading to capture the unfocused default state', async () => {
    const browser = browserDouble();
    const evidence = await mockR2Application(browser.page, 's06-entry', origin, []);
    expect(browser.actions).toContainEqual(['fill', 'Registered mobile number', '9876543210', { exact: true }]);
    expect(browser.actions.filter(action => action[0] === 'click')).toEqual([
      ['click', 'heading', { name: 'Recover your account.', exact: true }, undefined],
    ]);
    expect(evidence.recoveryRequests).toEqual([]);
  });

  it('waits for the actual submitting request when React renders before fetch reaches the route handler', async () => {
    const browser = browserDouble({ deferStartRequest: true });
    let settled = false;
    const capture = mockR2Application(browser.page, 's06-submitting', origin, []).then(
      value => { settled = true; return { value }; },
      error => { settled = true; return { error }; },
    );
    await vi.waitFor(() => expect(browser.actions).toContainEqual(['wait', '[data-screen="S-06"][data-state="submitting"]']));
    expect(settled).toBe(false);
    await browser.releaseStart();
    const result = await capture;
    expect(result.error).toBeUndefined();
    expect(result.value.recoveryRequests).toEqual(['POST /api/v1/auth/student/recovery/start']);
    expect(browser.replies.some(reply => reply.url.endsWith('/recovery/start'))).toBe(false);
  });

  it('fails within the bounded request wait when submitting never dispatches its request', async () => {
    vi.useFakeTimers();
    try {
      const browser = browserDouble({ deferStartRequest: true });
      const capture = mockR2Application(browser.page, 's06-submitting', origin, []).then(
        value => ({ value }), error => ({ error }),
      );
      await vi.advanceTimersByTimeAsync(0);
      expect(browser.actions).toContainEqual(['wait', '[data-screen="S-06"][data-state="submitting"]']);
      await vi.advanceTimersByTimeAsync(20_000);
      expect((await capture).error?.message).toBe('R2_S06_SUBMITTING_REQUEST_UNOBSERVED');
    } finally { vi.useRealTimers(); }
  });

  it('holds only the submitting network response, not product navigation or timers', async () => {
    const browser = browserDouble();
    const evidence = await mockR2Application(browser.page, 's06-submitting', origin, []);
    expect(evidence.pendingResponse).toEqual({ method: 'POST', url: origin + api + '/recovery/start', cancelledBy: 'context-disposal' });
    expect(evidence.recoveryRequests).toEqual(['POST /api/v1/auth/student/recovery/start']);
    expect(browser.replies.some(reply => reply.url.endsWith('/recovery/start'))).toBe(false);
  });

  it.each([
    ['challenge', 272, 22, 3, 0, false],
    ['expired', 0, 0, 3, 0, true],
    ['locked', 272, 22, 0, 1800, false],
  ])('uses exact server projection for %s without exposing a raw identifier', async (state, expiry, resend, attempts, lock, resendAllowed) => {
    const browser = browserDouble();
    await mockR2Application(browser.page, `s06-${state}`, origin, []);
    const projection = browser.replies.find(reply => reply.url.endsWith('/recovery/start')).body;
    expect(Object.keys(projection).sort()).toEqual(wireKeys);
    expect(projection).toEqual({ status: 'pending', purpose: 'recovery', destination_masked: '••••••0340', expires_in_seconds: expiry, resend_in_seconds: resend, attempts_left: attempts, locked_for_seconds: lock, resend_allowed: resendAllowed });
    const readback = await browser.request(api + '/otp/state');
    expect(readback.body).toEqual(projection);
  });

  it('wrong-code state comes only from a typed 401 and the next GET retains reduced server attempts', async () => {
    const browser = browserDouble();
    await mockR2Application(browser.page, 's06-wrong', origin, []);
    const failure = browser.replies.find(reply => reply.url.endsWith('/recovery/verify'));
    expect(failure.status).toBe(401);
    expect(failure.body.detail.code).toBe('recovery_failed');
    expect(failure.body.detail.otp_state).toMatchObject({ purpose: 'recovery', attempts_left: 2, expires_in_seconds: 184, resend_in_seconds: 8 });
    expect((await browser.request(api + '/otp/state')).body).toEqual(failure.body.detail.otp_state);
  });

  it('network failure is a typed 503, never a fake successful response', async () => {
    const browser = browserDouble();
    await mockR2Application(browser.page, 's06-neterr', origin, []);
    const failure = browser.replies.find(reply => reply.url.endsWith('/recovery/start'));
    expect(failure.status).toBe(503);
    expect(failure.body).toEqual({ detail: { code: 'otp_delivery_unavailable' } });
  });

  it('success verifies then consumes the recovery proof, never authenticates or navigates away', async () => {
    const browser = browserDouble();
    const evidence = await mockR2Application(browser.page, 's06-success', origin, []);
    expect(evidence.recoveryRequests).toEqual(['POST /api/v1/auth/student/recovery/start', 'POST /api/v1/auth/student/recovery/verify', 'POST /api/v1/auth/student/recovery/complete']);
    const proof = browser.replies.find(reply => reply.url.endsWith('/recovery/verify')).body;
    const retired = browser.replies.find(reply => reply.url.endsWith('/recovery/complete')).body;
    expect(proof).toMatchObject({ status: 'verified', purpose: 'recovery', destination_masked: null, attempts_left: null, resend_allowed: false });
    expect(retired).toEqual({ ...proof, status: 'unavailable', purpose: null });
    expect((await browser.request(api + '/otp/state')).body).toEqual(retired);
    expect((await browser.request(api + '/session')).body).toEqual({ authenticated: false, actor: null });
    expect(browser.actions).toContainEqual(['heading', 'heading', { name: 'Your account is ready.', exact: true }]);
  });

  it('fails rather than manufacturing a missing UI state', async () => {
    const browser = browserDouble({ failState: 'wrong' });
    await expect(mockR2Application(browser.page, 's06-wrong', origin, [])).rejects.toThrow('REAL_UI_STATE_MISSING');
  });

  it('rejects outbound and unmatched API calls while allowing same-origin application assets', async () => {
    const browser = browserDouble(), errors = [];
    await mockR2Application(browser.page, 's06-entry', origin, errors);
    expect(await browser.request('https://untrusted.example/api/v1/auth/student/session')).toEqual({ aborted: true });
    expect(await browser.request('/api/v1/unexpected')).toEqual({ aborted: true });
    expect(await browser.request('/assets/index.js')).toEqual({ continued: true });
    expect(errors).toEqual(['OUTBOUND_REQUEST', 'UNMATCHED_API']);
  });

  it('rejects unplanned writes, reordered completion, malformed payloads and duplicate mutation authority', async () => {
    const browser = browserDouble(), errors = [];
    await mockR2Application(browser.page, 's06-success', origin, errors);
    for (const [path, body] of [['/recovery/start', { mobile: '9876500340' }], ['/recovery/complete', {}], ['/recovery/verify', { code: '419037', mobile: '9876500340' }]]) {
      expect(await browser.request(api + path, 'POST', body)).toEqual({ aborted: true });
    }
    expect(errors).toHaveLength(3);
    expect(errors.every(error => error === 'UNEXPECTED_RECOVERY_MUTATION')).toBe(true);
  });
});
