import { afterEach, describe, expect, it, vi } from 'vitest';
import { readFileSync } from 'node:fs';
import { logoutStudent } from './registrationApi';
import { clearStudentBrowserContext } from './studentBrowserContext';
import { clearStudentAuthTransitionNotice, hasStudentLogoutFailure, recordStudentAuthTransitionNotice, subscribeStudentAuthTransitionNotice } from './studentAuthTransitionNotice';

afterEach(() => { clearStudentBrowserContext(); clearStudentAuthTransitionNotice(); vi.unstubAllGlobals(); vi.restoreAllMocks(); });

describe('PR1 logout truth', () => {
  const actor = { sub: '00000000-0000-4000-8000-000000000084', roles: ['student'], student_profile_id: '00000000-0000-4000-8000-000000000085', student_verification: 'draft', is_minor: false, consent_state: ['registration'] };
  const response = (body: unknown) => new Response(JSON.stringify(body), { headers: { 'Content-Type': 'application/json' } });
  function arrange(probe: () => Promise<Response>) {
    vi.stubGlobal('window', { dispatchEvent: vi.fn(() => true) });
    vi.stubGlobal('fetch', vi.fn().mockResolvedValueOnce(response({})).mockImplementationOnce(probe));
  }
  it('does not report success when POST succeeds but the server still recognizes the session', async () => {
    arrange(async () => response({ authenticated: true, actor }));
    await expect(logoutStudent()).rejects.toMatchObject({ code: 'student_auth_transition_not_anonymous' });
  });
  it('does not report success when the authoritative post-logout session probe is unavailable', async () => {
    arrange(async () => { throw new TypeError('network unavailable'); });
    await expect(logoutStudent()).rejects.toThrow('network unavailable');
  });
  it('permits success after the server confirms anonymous', async () => {
    arrange(async () => response({ authenticated: false, actor: null }));
    await expect(logoutStudent()).resolves.toBeUndefined();
  });
  it('never navigates from the S-07 logout finally block', () => {
    const source = readFileSync('src/features/student/auth/V34Screens.tsx', 'utf8');
    const handler = source.match(/async function signOut\(\)[\s\S]*?\n {2}\}/)?.[0];
    expect(handler).toBeDefined();
    expect(handler).not.toMatch(/finally\s*\{\s*nav/);
  });

  it('publishes a process-only failure that survives UI remount and clears at the next lifecycle', () => {
    const changed = vi.fn();
    const unsubscribe = subscribeStudentAuthTransitionNotice(changed);
    try {
      recordStudentAuthTransitionNotice('sign_out_failed');
      expect(hasStudentLogoutFailure()).toBe(true);
      expect(changed).toHaveBeenCalledTimes(1);
      clearStudentAuthTransitionNotice();
      expect(hasStudentLogoutFailure()).toBe(false);
      expect(changed).toHaveBeenCalledTimes(2);
    } finally { unsubscribe(); }
  });

  it('keeps account-deletion notices distinct from logout and removes subscriptions', () => {
    const changed = vi.fn();
    const unsubscribe = subscribeStudentAuthTransitionNotice(changed);
    unsubscribe();
    recordStudentAuthTransitionNotice('account_deletion_failed');
    expect(hasStudentLogoutFailure()).toBe(false);
    expect(changed).not.toHaveBeenCalled();
  });
});
