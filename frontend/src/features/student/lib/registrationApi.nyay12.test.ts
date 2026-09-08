import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import { afterEach, describe, expect, it, vi } from 'vitest';

const fetchMock = vi.hoisted(() => vi.fn());
vi.mock('./studentApiClient', () => ({
  studentApiFetch: fetchMock,
}));

import * as api from './registrationApi';

function jsonResponse(body: unknown, status = 200, headers: Record<string, string> = {}): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'content-type': 'application/json', ...headers },
  });
}

const PENDING_EMAIL_FLOW = {
  status: 'pending',
  purpose: 'login',
  destination_masked: 's•••••@example.edu',
  attempts_left: 3,
  expires_in_seconds: 300,
  resend_in_seconds: 30,
  locked_for_seconds: 0,
  resend_allowed: false,
};

afterEach(() => {
  fetchMock.mockReset();
});

describe('NYAY-12 login channels projection', () => {
  it('reads the server projection with exact keys and closed channel names', async () => {
    fetchMock.mockResolvedValueOnce(jsonResponse({
      channels: [
        { channel: 'mobile', enabled: true },
        { channel: 'email', enabled: false },
      ],
    }));
    const channels = await api.getLoginChannels();
    expect(channels).toEqual({ mobile: true, email: false });
    const [path, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(path).toBe('/api/v1/auth/student/login/channels');
    expect(init.method).toBe('GET');
  });

  it.each([
    ['extra key', { channels: [{ channel: 'mobile', enabled: true }, { channel: 'email', enabled: true }], flags: {} }],
    ['unknown channel', { channels: [{ channel: 'mobile', enabled: true }, { channel: 'password', enabled: true }] }],
    ['non-boolean', { channels: [{ channel: 'mobile', enabled: 'yes' }, { channel: 'email', enabled: false }] }],
    ['missing email', { channels: [{ channel: 'mobile', enabled: true }] }],
    ['extra row key', { channels: [{ channel: 'mobile', enabled: true }, { channel: 'email', enabled: true, reason: 'x' }] }],
  ])('rejects a malformed projection (%s)', async (_label, body) => {
    fetchMock.mockResolvedValueOnce(jsonResponse(body));
    await expect(api.getLoginChannels()).rejects.toMatchObject({ code: 'invalid_login_channels' });
  });
});

describe('NYAY-12 email login start', () => {
  it('posts the email and adopts the server-masked email destination', async () => {
    fetchMock.mockResolvedValueOnce(jsonResponse(PENDING_EMAIL_FLOW, 202));
    const state = await api.startEmailLoginOtp('Student.One@Example.EDU');
    expect(state.destinationMasked).toBe('s•••••@example.edu');
    expect(state.purpose).toBe('login');
    const [path, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(path).toBe('/api/v1/auth/student/login/email/start');
    expect(init.method).toBe('POST');
    expect(JSON.parse(String(init.body))).toEqual({ email: 'Student.One@Example.EDU' });
  });

  it('rejects unmasked or malformed destinations from the wire', async () => {
    for (const destination of ['student@example.edu', 's•••••example.edu', '••••••@example.edu', '']) {
      fetchMock.mockResolvedValueOnce(jsonResponse({ ...PENDING_EMAIL_FLOW, destination_masked: destination }, 202));
      await expect(api.startEmailLoginOtp('student@example.edu')).rejects.toMatchObject({ code: 'invalid_otp_state' });
    }
  });

  it('surfaces the typed disabled-channel failure without inventing a fallback', async () => {
    fetchMock.mockResolvedValueOnce(jsonResponse({ detail: { code: 'email_login_disabled' } }, 403));
    await expect(api.startEmailLoginOtp('student@example.edu')).rejects.toMatchObject({ status: 403, code: 'email_login_disabled' });
  });

  it('keeps the OTP flow wire closed and storage-free', () => {
    const source = readFileSync(join(process.cwd(), 'src/features/student/lib/registrationApi.ts'), 'utf8');
    expect(source).not.toMatch(/localStorage|sessionStorage|indexedDB/u);
    expect(source).toContain("'/api/v1/auth/student/login/email/start'");
    expect(source).toContain("'/api/v1/auth/student/login/channels'");
  });
});
