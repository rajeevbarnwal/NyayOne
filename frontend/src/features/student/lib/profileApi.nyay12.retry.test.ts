import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import { afterEach, describe, expect, it, vi } from 'vitest';

const fetchMock = vi.hoisted(() => vi.fn());
vi.mock('./studentApiClient', () => ({
  studentApiFetch: fetchMock,
}));

import * as api from './profileApi';

const IDENTITY = {
  id: '00000000-0000-4000-8000-00000000c0de',
  email_masked: 's•••••@example.test',
  state: 'pending',
  is_primary: false,
  verification: { status: 'active', expires_in_seconds: 280, resend_in_seconds: 12, attempts_left: 3 },
};

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), { status, headers: { 'content-type': 'application/json' } });
}

afterEach(() => fetchMock.mockReset());

describe('NYAY-12 idempotency key preservation (Copilot r3952693857)', () => {
  it('uses a caller-supplied key verbatim and reuses it across a retry of the same operation', async () => {
    fetchMock.mockRejectedValueOnce(new TypeError('network'));
    fetchMock.mockResolvedValueOnce(jsonResponse({ status: 'accepted', identity: IDENTITY }, 202));
    const idempotencyKey = api.newEmailIdentityIdempotencyKey();
    await expect(api.addEmailIdentity('student@example.test', { idempotencyKey })).rejects.toBeInstanceOf(TypeError);
    const result = await api.addEmailIdentity('student@example.test', { idempotencyKey });
    expect(result.status).toBe('accepted');
    const keys = fetchMock.mock.calls.map(([, init]) => new Headers((init as RequestInit).headers).get('Idempotency-Key'));
    expect(keys).toEqual([idempotencyKey, idempotencyKey]);
  });

  it('accepts a supplied key for every lifecycle mutation and generates one only when absent', async () => {
    const supplied = api.newEmailIdentityIdempotencyKey();
    const calls: Array<[() => Promise<unknown>, string]> = [
      [() => api.verifyEmailIdentity(IDENTITY.id, '123456', { idempotencyKey: supplied }), 'verified'],
      [() => api.resendEmailIdentity(IDENTITY.id, { idempotencyKey: supplied }), 'accepted'],
      [() => api.removeEmailIdentity(IDENTITY.id, { idempotencyKey: supplied }), 'removed'],
      [() => api.setPrimaryEmailIdentity(IDENTITY.id, { idempotencyKey: supplied }), 'primary'],
    ];
    for (const [call, status] of calls) {
      fetchMock.mockResolvedValueOnce(jsonResponse({ status, identity: { ...IDENTITY, state: status === 'removed' ? 'removed' : 'verified', is_primary: status === 'primary', verification: { status: 'none', expires_in_seconds: null, resend_in_seconds: null, attempts_left: null } } }, status === 'accepted' ? 202 : 200));
      await call();
      const [, init] = fetchMock.mock.calls[fetchMock.mock.calls.length - 1] as [string, RequestInit];
      expect(new Headers(init.headers).get('Idempotency-Key')).toBe(supplied);
    }
    fetchMock.mockResolvedValueOnce(jsonResponse({ status: 'accepted', identity: IDENTITY }, 202));
    await api.addEmailIdentity('student@example.test');
    const [, init] = fetchMock.mock.calls[fetchMock.mock.calls.length - 1] as [string, RequestInit];
    const generated = new Headers(init.headers).get('Idempotency-Key');
    expect(generated).toMatch(/^[A-Za-z0-9._~-]{16,200}$/u);
    expect(generated).not.toBe(supplied);
  });

  it('rejects a supplied key outside the server alphabet before any request', async () => {
    await expect(api.addEmailIdentity('student@example.test', { idempotencyKey: 'bad key!' })).rejects.toMatchObject({ code: 'invalid_idempotency_key' });
    expect(fetchMock).not.toHaveBeenCalled();
  });
});

describe('NYAY-12 cancellation propagation (Copilot r3952693880)', () => {
  it('forwards an AbortSignal to the listing request and surfaces the abort', async () => {
    const controller = new AbortController();
    fetchMock.mockImplementationOnce((_path: string, init: RequestInit) => new Promise((_resolve, reject) => {
      init.signal?.addEventListener('abort', () => reject(new DOMException('aborted', 'AbortError')));
    }));
    const pending = api.listEmailIdentities(controller.signal);
    controller.abort();
    await expect(pending).rejects.toMatchObject({ name: 'AbortError' });
    const [, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(init.signal).toBe(controller.signal);
  });

  it('wires the query-function signal through the hook', () => {
    const hooks = readFileSync(join(process.cwd(), 'src/features/student/profile/profileHooks.ts'), 'utf8');
    const block = hooks.slice(hooks.indexOf('export function useEmailIdentities'), hooks.indexOf('function useEmailIdentityMutation'));
    expect(block).toMatch(/queryFn:\s*\(\{\s*signal\s*\}(?:\s*:\s*QueryFunctionContext)?\)\s*=>\s*listEmailIdentities\(signal\)/u);
    expect(block).not.toContain('(_context: QueryFunctionContext) => listEmailIdentities()');
  });

  it('generates one key per owner action in the panel and reuses it for the mutation retry', () => {
    const screens = readFileSync(join(process.cwd(), 'src/features/student/profile/ProfileScreens.tsx'), 'utf8');
    const panel = screens.slice(screens.indexOf('export function EmailIdentityPanel('), screens.indexOf('export function ProfileView'));
    expect(panel.match(/newEmailIdentityIdempotencyKey\(\)/gu)).toHaveLength(5);
    expect(panel).toContain('idempotencyKey');
    const hooks = readFileSync(join(process.cwd(), 'src/features/student/profile/profileHooks.ts'), 'utf8');
    expect(hooks).toContain('({ email, idempotencyKey }) => addEmailIdentity(email, { idempotencyKey })');
    expect(hooks).toContain('({ identityId, code, idempotencyKey }) => verifyEmailIdentity(identityId, code, { idempotencyKey })');
  });
});
