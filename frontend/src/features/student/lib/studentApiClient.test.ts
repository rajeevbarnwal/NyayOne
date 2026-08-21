import { afterEach, describe, expect, it, vi } from 'vitest';
import { queryClient } from '../../../app/queryClient';
import { studentApiFetch } from './studentApiClient';
import { clearStudentBrowserContext } from './studentBrowserContext';

function jsonResponse(body: unknown, status = 401): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  });
}

afterEach(() => {
  clearStudentBrowserContext();
  queryClient.clear();
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe('studentApiFetch authentication lifecycle', () => {
  it.each([
    ['detail envelope', { detail: { code: 'authentication_required' } }],
    ['error envelope', { error: { code: 'authentication_required' } }],
    ['nested error detail', { error: { detail: { code: 'authentication_required' } } }],
  ])('clears on the exact typed code in the %s and leaves the original body readable', async (_label, body) => {
    const dispatchEvent = vi.fn(() => true);
    vi.stubGlobal('window', { dispatchEvent });
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(jsonResponse(body)));
    queryClient.setQueryData(['private-student'], { owner: 'student-A' });

    const response = await studentApiFetch('/api/v1/student/private');

    expect(await response.json()).toEqual(body);
    expect(queryClient.getQueryData(['private-student'])).toBeUndefined();
    expect(dispatchEvent).toHaveBeenCalledTimes(1);
  });

  it.each([
    ['incorrect OTP', { detail: { code: 'incorrect_otp' } }],
    ['step-up required', { detail: { code: 'reauth_required' } }],
    ['near-match code', { detail: { code: 'authentication_required_later' } }],
    ['untyped 401', { detail: 'authentication_required' }],
  ])('does not clear a still-valid student context for %s', async (_label, body) => {
    const dispatchEvent = vi.fn(() => true);
    vi.stubGlobal('window', { dispatchEvent });
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(jsonResponse(body)));
    queryClient.setQueryData(['private-student'], 'retain');

    await studentApiFetch('/api/v1/auth/student/otp/verify');

    expect(queryClient.getQueryData(['private-student'])).toBe('retain');
    expect(dispatchEvent).not.toHaveBeenCalled();
  });

  it('fails closed without consuming or throwing on malformed non-JSON 401 bodies', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response('not-json', { status: 401 })));
    queryClient.setQueryData(['private-student'], 'retain-until-typed-proof');

    const response = await studentApiFetch('/api/v1/auth/student/otp/verify');

    expect(await response.text()).toBe('not-json');
    expect(queryClient.getQueryData(['private-student'])).toBe('retain-until-typed-proof');
  });

  it('can suppress notification for the session bootstrap while still clearing', async () => {
    const dispatchEvent = vi.fn(() => true);
    vi.stubGlobal('window', { dispatchEvent });
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(jsonResponse({
      detail: { code: 'authentication_required' },
    })));
    queryClient.setQueryData(['private-student'], 'clear');

    await studentApiFetch(
      '/api/v1/auth/student/session',
      {},
      { notifyAuthChanged: false },
    );

    expect(queryClient.getQueryData(['private-student'])).toBeUndefined();
    expect(dispatchEvent).not.toHaveBeenCalled();
  });
});
