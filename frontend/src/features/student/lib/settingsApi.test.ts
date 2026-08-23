import { afterEach, describe, expect, it, vi } from 'vitest';
import { readFileSync } from 'node:fs';
import { queryClient } from '../../../app/queryClient';
import { getProfileDraft, updateProfileDraft } from './profileStore';
import { getRegistrationAttempt, setRegistrationAttempt } from './registrationAttemptStore';
import {
  STUDENT_AUTH_CHANGED_EVENT,
  STUDENT_AUTH_TRANSITION_STARTED_EVENT,
  clearStudentBrowserContext,
} from './studentBrowserContext';
import {
  getStudentSettings,
  updateStudentSettings,
  requestDataExport,
  requestAccountDeletion,
  getPrivacyRequest,
  SettingsApiError,
  SETTINGS_CONFLICT_CODE,
  REAUTH_REQUIRED_CODE,
} from './settingsApi';

const settingsApiSource = readFileSync(new URL('./settingsApi.ts', import.meta.url), 'utf8');
const settingsScreenSource = readFileSync(new URL('../settings/SettingsScreens.tsx', import.meta.url), 'utf8');
const reportSource = readFileSync(new URL('./report.ts', import.meta.url), 'utf8');
const reminderSource = readFileSync(new URL('./reminderPrefs.ts', import.meta.url), 'utf8');

afterEach(() => {
  clearStudentBrowserContext();
  queryClient.clear();
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

const SETTINGS_WIRE = {
  theme: 'dark',
  language: 'English',
  notif_email: true,
  notif_sms: false,
  notif_updates: true,
  version: 7,
  privacy: [
    { kind: 'analytics', enabled: true },
    { kind: 'marketing', enabled: false },
    { kind: 'share_partners', enabled: false },
  ],
};
const DELETE_REQUEST_ID = 'a'.repeat(32);
const ACCEPTED_DELETE_REQUEST_ID = 'b'.repeat(32);

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  });
}

function storage(map: Map<string, string>): Storage {
  return {
    get length() { return map.size; },
    clear: () => map.clear(),
    getItem: (key) => map.get(key) ?? null,
    key: (index) => [...map.keys()][index] ?? null,
    removeItem: (key) => { map.delete(key); },
    setItem: (key, value) => { map.set(key, value); },
  };
}

describe('server-authoritative student settings API (SAATHI-58)', () => {
  it('maps the settings wire shape including privacy consents', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(jsonResponse(SETTINGS_WIRE)));
    const settings = await getStudentSettings();
    expect(settings).toEqual({
      theme: 'dark',
      language: 'English',
      notifEmail: true,
      notifSms: false,
      notifUpdates: true,
      version: 7,
      privacy: [
        { kind: 'analytics', enabled: true },
        { kind: 'marketing', enabled: false },
        { kind: 'share_partners', enabled: false },
      ],
    });
  });

  it('sends expected_version with the PATCH payload', async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse({ ...SETTINGS_WIRE, notif_sms: true, version: 8 }));
    vi.stubGlobal('fetch', fetchMock);

    const updated = await updateStudentSettings({ notifSms: true }, 7);
    expect(updated.version).toBe(8);
    const [, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    const body = JSON.parse(String(init.body)) as Record<string, unknown>;
    expect(body.expected_version).toBe(7);
    expect(body.notif_sms).toBe(true);
    expect(body.theme).toBeUndefined();
  });

  it('raises the typed 409 settings_version_conflict error on a stale version', async () => {
    vi.stubGlobal('fetch', vi.fn().mockImplementation(() => Promise.resolve(jsonResponse(
      { detail: { code: SETTINGS_CONFLICT_CODE } },
      409,
    ))));

    const attempt = updateStudentSettings({ theme: 'light' }, 3);
    await expect(attempt).rejects.toBeInstanceOf(SettingsApiError);
    await expect(updateStudentSettings({ theme: 'light' }, 3)).rejects.toEqual(
      expect.objectContaining({ status: 409, code: SETTINGS_CONFLICT_CODE }),
    );
  });
});

describe('DPDP privacy request API (SAATHI-58 / S-19)', () => {
  it('keeps request polling references in component memory and requires explicit private stores', () => {
    expect(settingsApiSource).not.toContain('sessionStorage');
    expect(settingsApiSource).not.toMatch(/(?:save|load|clear)PrivacyRequestRef/);
    expect(settingsScreenSource).not.toMatch(/(?:save|load|clear)PrivacyRequestRef/);
    expect(reportSource).not.toContain('defaultKvStore');
    expect(reportSource).not.toMatch(/store:\s*KvStore\s*=/u);
    expect(reminderSource).not.toContain('defaultKvStore');
    expect(reminderSource).not.toMatch(/store:\s*KvStore\s*=/u);
  });

  it('requests an export with an Idempotency-Key header', async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse(
      { request_id: 'opaque-export-1', status: 'pending' },
      202,
    ));
    vi.stubGlobal('fetch', fetchMock);

    const accepted = await requestDataExport('idem-1');
    expect(accepted).toEqual({ requestId: 'opaque-export-1', status: 'pending' });
    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toContain('/api/v1/student/privacy/export');
    expect(new Headers(init.headers).get('Idempotency-Key')).toBe('idem-1');
  });

  it('posts confirmation only and relies on the HttpOnly recovery proof', async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse(
      { request_id: DELETE_REQUEST_ID, status: 'pending' },
      202,
    ));
    vi.stubGlobal('fetch', fetchMock);

    await requestAccountDeletion({ confirmation: 'DELETE' });
    const [, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(new Headers(init.headers).has('X-Actor-Claims')).toBe(false);
    expect(JSON.parse(String(init.body))).toEqual({
      confirmation: 'DELETE',
    });
    expect(String(init.body)).not.toMatch(
      /(?:registration|login|recovery)(?:_(?:id|token)|(?:Id|Token))/,
    );
  });

  it('retires all browser context when account deletion is accepted', async () => {
    const local = new Map<string, string>([
      ['legalsaathi.student.profile.v1', '{"firstName":"Aditi"}'],
      ['legalsaathi.student.onboarding.v34', 'seen'],
      ['legalsaathi.internship.applications.v1', 'private'],
      ['legalsaathi.clinical.export-audit.v1', 'private'],
      ['ls-theme', 'dark'],
      ['ls-locale', 'en'],
    ]);
    const session = new Map<string, string>([
      ['legalsaathi.student.privacy.export.v1', 'opaque-export'],
      ['legalsaathi.student.privacy.delete.v1', 'opaque-delete'],
    ]);
    const dispatchEvent = vi.fn((_event: Event) => true);
    vi.stubGlobal('window', {
      localStorage: storage(local),
      sessionStorage: storage(session),
      dispatchEvent,
    });
    vi.stubGlobal('fetch', vi.fn()
      .mockResolvedValueOnce(jsonResponse(
        { request_id: ACCEPTED_DELETE_REQUEST_ID, status: 'pending' },
        202,
      ))
      .mockResolvedValueOnce(jsonResponse({ authenticated: false, actor: null })));
    setRegistrationAttempt({ body: 'private', key: 'private-idempotency' });
    updateProfileDraft({ firstName: 'Aditi', dateOfBirth: '2004-03-14' });
    queryClient.setQueryData(['student-settings'], SETTINGS_WIRE);
    queryClient.getMutationCache().build(queryClient, {
      mutationKey: ['delete-account'],
      mutationFn: async () => 'private',
    });

    await expect(requestAccountDeletion({ confirmation: 'DELETE' })).resolves.toEqual({
      requestId: ACCEPTED_DELETE_REQUEST_ID,
      status: 'pending',
    });

    expect(getRegistrationAttempt()).toBeNull();
    expect(getProfileDraft().firstName).toBe('');
    expect(queryClient.getQueryCache().getAll()).toEqual([]);
    expect(queryClient.getMutationCache().getAll()).toEqual([]);
    expect([...session.entries()]).toEqual([]);
    expect([...local.entries()]).toEqual([
      ['ls-theme', 'dark'],
      ['ls-locale', 'en'],
    ]);
    expect(dispatchEvent.mock.calls.map(([event]) => (event as Event).type)).toEqual([
      STUDENT_AUTH_TRANSITION_STARTED_EVENT,
      STUDENT_AUTH_CHANGED_EVENT,
    ]);
  });

  it.each([
    ['missing request id', { status: 'pending' }, 202],
    ['extra authority field', { request_id: DELETE_REQUEST_ID, status: 'pending', actor: 'forged' }, 202],
    ['wrong request id shape', { request_id: 'opaque-delete', status: 'pending' }, 202],
    ['wrong workflow status', { request_id: DELETE_REQUEST_ID, status: 'complete' }, 202],
    ['wrong HTTP status', { request_id: DELETE_REQUEST_ID, status: 'pending' }, 200],
  ])('rejects a %s even when session authority concurrently becomes anonymous', async (_label, body, status) => {
    vi.stubGlobal('window', {
      localStorage: storage(new Map()),
      sessionStorage: storage(new Map()),
      dispatchEvent: vi.fn(() => true),
    });
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(jsonResponse(body, status))
      .mockResolvedValueOnce(jsonResponse({ authenticated: false, actor: null }));
    vi.stubGlobal('fetch', fetchMock);

    await expect(requestAccountDeletion({ confirmation: 'DELETE' }))
      .rejects.toEqual(expect.objectContaining({
        status: 502,
        code: expect.stringMatching(/^invalid_(?:privacy_request_projection|settings_response_status)$/u),
      }));
    expect(fetchMock).toHaveBeenCalledTimes(2);
  });

  it('surfaces typed 401 reauth_required after fail-closed transition cleanup', async () => {
    queryClient.setQueryData(['valid-session'], 'retain');
    setRegistrationAttempt({ body: 'retain', key: 'retain' });
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(jsonResponse(
      { detail: { code: REAUTH_REQUIRED_CODE } },
      401,
    )));
    await expect(requestAccountDeletion({ confirmation: 'DELETE' }))
      .rejects.toEqual(expect.objectContaining({ status: 401, code: REAUTH_REQUIRED_CODE }));
    expect(queryClient.getQueryData(['valid-session'])).toBeUndefined();
    expect(getRegistrationAttempt()).toBeNull();
  });

  it('surfaces a typed 422 for a wrong confirmation phrase', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(jsonResponse(
      { detail: { code: 'invalid_confirmation', field: 'confirmation' } },
      422,
    )));
    await expect(requestAccountDeletion({ confirmation: 'delete' }))
      .rejects.toEqual(expect.objectContaining({
        status: 422,
        code: 'invalid_confirmation',
        field: 'confirmation',
      }));
  });

  it('polls a privacy request by id and maps the wire shape', async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse({
      request_id: 'opaque-export-1',
      kind: 'export',
      status: 'processing',
      created_at: '2026-07-27T00:00:00Z',
    }));
    vi.stubGlobal('fetch', fetchMock);

    const req = await getPrivacyRequest('opaque-export-1');
    expect(req).toEqual({
      requestId: 'opaque-export-1',
      kind: 'export',
      status: 'processing',
      createdAt: '2026-07-27T00:00:00Z',
    });
    const [url] = fetchMock.mock.calls[0] as [string];
    expect(url).toContain('/api/v1/student/privacy/requests/opaque-export-1');
  });

  it('never persists the private workflow reference in browser storage', async () => {
    const session = new Map<string, string>();
    const setItem = vi.fn((key: string, value: string) => { session.set(key, value); });
    vi.stubGlobal('window', { sessionStorage: { ...storage(session), setItem } });
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(jsonResponse(
      { request_id: 'opaque-export-1', status: 'pending' },
      202,
    )));

    await requestDataExport('idem-memory-only');

    expect(setItem).not.toHaveBeenCalled();
    expect([...session.entries()]).toEqual([]);
  });

  it('does not consult inaccessible browser storage while creating a privacy request', async () => {
    vi.stubGlobal('window', {
      get sessionStorage(): Storage { throw new DOMException('denied'); },
    });
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(jsonResponse(
      { request_id: 'opaque-export-2', status: 'pending' },
      202,
    )));

    await expect(requestDataExport('idem-no-storage')).resolves.toEqual({
      requestId: 'opaque-export-2', status: 'pending',
    });
  });
});
