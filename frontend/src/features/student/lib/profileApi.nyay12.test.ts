import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import { afterEach, describe, expect, it, vi } from 'vitest';

const fetchMock = vi.hoisted(() => vi.fn());
vi.mock('./studentApiClient', () => ({
  studentApiFetch: fetchMock,
}));

import * as api from './profileApi';

const ROOT = '/api/v1/auth/student/email-identities';
const KEY_RE = /^[A-Za-z0-9._~-]{16,200}$/u;

function jsonResponse(body: unknown, status = 200, headers: Record<string, string> = {}): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'content-type': 'application/json', ...headers },
  });
}

const IDENTITY = {
  id: '00000000-0000-4000-8000-00000000c0de',
  email_masked: 's•••••@example.edu',
  state: 'pending',
  is_primary: false,
  verification: { status: 'active', expires_in_seconds: 280, resend_in_seconds: 12, attempts_left: 3 },
};

afterEach(() => {
  fetchMock.mockReset();
});

function lastCall(): [string, RequestInit] {
  return fetchMock.mock.calls[fetchMock.mock.calls.length - 1] as [string, RequestInit];
}

describe('NYAY-12 email identity client', () => {
  it('lists identities with an exact projection', async () => {
    fetchMock.mockResolvedValueOnce(jsonResponse({ login_channel_enabled: true, max_identities: 3, identities: [IDENTITY] }));
    const listing = await api.listEmailIdentities();
    expect(listing).toEqual({
      loginChannelEnabled: true,
      maxIdentities: 3,
      identities: [{
        id: IDENTITY.id,
        emailMasked: 's•••••@example.edu',
        state: 'pending',
        isPrimary: false,
        verification: { status: 'active', expiresInSeconds: 280, resendInSeconds: 12, attemptsLeft: 3 },
      }],
    });
    const [path, init] = lastCall();
    expect(path).toBe(ROOT);
    expect(init.method).toBe('GET');
  });

  it.each([
    ['extra top-level key', { login_channel_enabled: true, max_identities: 3, identities: [], email: 'raw@example.edu' }],
    ['raw email field', { login_channel_enabled: true, max_identities: 3, identities: [{ ...IDENTITY, email: 'raw@example.edu' }] }],
    ['unmasked destination', { login_channel_enabled: true, max_identities: 3, identities: [{ ...IDENTITY, email_masked: 'student@example.edu' }] }],
    ['unknown state', { login_channel_enabled: true, max_identities: 3, identities: [{ ...IDENTITY, state: 'trusted' }] }],
    ['primary while pending', { login_channel_enabled: true, max_identities: 3, identities: [{ ...IDENTITY, is_primary: true }] }],
    ['absolute time', { login_channel_enabled: true, max_identities: 3, identities: [{ ...IDENTITY, verification: { ...IDENTITY.verification, expires_at: '2026-09-10T09:00:00Z' } }] }],
  ])('rejects a malformed listing (%s)', async (_label, body) => {
    fetchMock.mockResolvedValueOnce(jsonResponse(body));
    await expect(api.listEmailIdentities()).rejects.toMatchObject({ code: 'invalid_email_identity_projection' });
  });

  it('adds an identity with a mandatory idempotency key and JSON body', async () => {
    fetchMock.mockResolvedValueOnce(jsonResponse({ status: 'accepted', identity: IDENTITY }, 202));
    const result = await api.addEmailIdentity('Student.One@Example.EDU');
    expect(result.status).toBe('accepted');
    expect(result.identity.emailMasked).toBe('s•••••@example.edu');
    const [path, init] = lastCall();
    expect(path).toBe(ROOT);
    expect(init.method).toBe('POST');
    expect(JSON.parse(String(init.body))).toEqual({ email: 'Student.One@Example.EDU' });
    expect(new Headers(init.headers).get('Idempotency-Key')).toMatch(KEY_RE);
  });

  it('verifies, resends, removes and promotes with per-call idempotency keys', async () => {
    const keys = new Set<string>();
    for (const [call, expected] of [
      [() => api.verifyEmailIdentity(IDENTITY.id, '123456'), { method: 'POST', path: `${ROOT}/${IDENTITY.id}/verify`, body: { code: '123456' }, status: 'verified' }],
      [() => api.resendEmailIdentity(IDENTITY.id), { method: 'POST', path: `${ROOT}/${IDENTITY.id}/resend`, body: {}, status: 'accepted' }],
      [() => api.removeEmailIdentity(IDENTITY.id), { method: 'DELETE', path: `${ROOT}/${IDENTITY.id}`, body: undefined, status: 'removed' }],
      [() => api.setPrimaryEmailIdentity(IDENTITY.id), { method: 'POST', path: `${ROOT}/${IDENTITY.id}/primary`, body: {}, status: 'primary' }],
    ] as const) {
      fetchMock.mockResolvedValueOnce(jsonResponse({ status: expected.status, identity: { ...IDENTITY, state: expected.status === 'removed' ? 'removed' : 'verified', is_primary: expected.status === 'primary', verification: { status: 'none', expires_in_seconds: null, resend_in_seconds: null, attempts_left: null } } }, expected.status === 'accepted' ? 202 : 200));
      const result = await call();
      expect(result.status).toBe(expected.status);
      const [path, init] = lastCall();
      expect(path).toBe(expected.path);
      expect(init.method).toBe(expected.method);
      if (expected.body !== undefined) expect(JSON.parse(String(init.body))).toEqual(expected.body);
      const key = new Headers(init.headers).get('Idempotency-Key');
      expect(key).toMatch(KEY_RE);
      keys.add(String(key));
    }
    expect(keys.size).toBe(4);
  });

  it('maps typed failures without echoing input and preserves Retry-After', async () => {
    fetchMock.mockResolvedValueOnce(jsonResponse({ detail: { code: 'email_identity_conflict', message: 'Request failed' } }, 409));
    await expect(api.verifyEmailIdentity(IDENTITY.id, '123456')).rejects.toMatchObject({ status: 409, code: 'email_identity_conflict' });
    fetchMock.mockResolvedValueOnce(jsonResponse({ detail: { code: 'email_identity_rate_limited' } }, 429, { 'Retry-After': '17' }));
    await expect(api.resendEmailIdentity(IDENTITY.id)).rejects.toMatchObject({ status: 429, code: 'email_identity_rate_limited', retryAfterSeconds: 17 });
    fetchMock.mockResolvedValueOnce(jsonResponse({ detail: { code: 'authentication_required' } }, 401));
    await expect(api.listEmailIdentities()).rejects.toMatchObject({ status: 401 });
  });

  it('produces human messages that never contain the address or code', () => {
    for (const code of ['email_identity_conflict', 'email_identity_verification_failed', 'email_identity_rate_limited', 'email_delivery_unavailable', 'email_identity_limit_reached', 'email_identity_capability_disabled']) {
      const message = api.emailIdentityErrorMessage(new api.ProfileApiError(409, code));
      expect(message.length).toBeGreaterThan(10);
      expect(message).not.toContain('@');
    }
  });

  it('keeps the identity client storage-free and handle-free', () => {
    const source = readFileSync(join(process.cwd(), 'src/features/student/lib/profileApi.ts'), 'utf8');
    expect(source).not.toMatch(/localStorage|sessionStorage|indexedDB/u);
    expect(source).toContain("'/api/v1/auth/student/email-identities'");
    expect(source).not.toMatch(/\b(?:login|recovery)(?:_(?:id|token)|(?:Id|Token))\b/u);
  });
});
