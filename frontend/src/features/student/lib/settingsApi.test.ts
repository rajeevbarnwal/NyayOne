import { afterEach, describe, expect, it, vi } from 'vitest';
import {
  getStudentProfile,
  updateStudentProfile,
  getStudentSettings,
  updateStudentSettings,
  requestDataExport,
  requestAccountDeletion,
  getPrivacyRequest,
  savePrivacyRequestRef,
  loadPrivacyRequestRef,
  clearPrivacyRequestRef,
  SettingsApiError,
  SETTINGS_CONFLICT_CODE,
  REAUTH_REQUIRED_CODE,
} from './settingsApi';

afterEach(() => {
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

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  });
}

describe('server-authoritative student profile API (SAATHI-58)', () => {
  it('maps the profile wire shape to camelCase', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(jsonResponse({
      first_name: 'Aditi',
      middle_name: null,
      last_name: 'Nair',
      college: 'NLSIU',
      year_of_study: '3rd year',
      masked_mobile: '••••••3210',
    })));

    const profile = await getStudentProfile();
    expect(profile).toEqual({
      firstName: 'Aditi',
      middleName: null,
      lastName: 'Nair',
      college: 'NLSIU',
      yearOfStudy: '3rd year',
      enrolmentNumber: null,
      institutionalEmail: null,
      barEnrolmentNumber: null,
      interests: null,
      careerGoal: null,
      maskedMobile: '••••••3210',
    });
  });

  it('PATCHes college/year_of_study in snake_case', async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse({
      first_name: 'Aditi',
      middle_name: null,
      last_name: 'Nair',
      college: 'NALSAR University of Law',
      year_of_study: '4th year · B.A. LL.B. (Hons.)',
      masked_mobile: '••••••3210',
    }));
    vi.stubGlobal('fetch', fetchMock);

    await updateStudentProfile({
      college: 'NALSAR University of Law',
      yearOfStudy: '4th year · B.A. LL.B. (Hons.)',
    });
    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toContain('/api/v1/student/profile');
    expect(init.method).toBe('PATCH');
    expect(JSON.parse(String(init.body))).toEqual({
      college: 'NALSAR University of Law',
      year_of_study: '4th year · B.A. LL.B. (Hons.)',
    });
  });
});

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

  it('posts confirmation + reauth_recovery_id for deletion', async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse(
      { request_id: 'opaque-delete-1', status: 'pending' },
      202,
    ));
    vi.stubGlobal('fetch', fetchMock);

    await requestAccountDeletion({ confirmation: 'DELETE', reauthRecoveryId: 'recovery-1' });
    const [, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(JSON.parse(String(init.body))).toEqual({
      confirmation: 'DELETE',
      reauth_recovery_id: 'recovery-1',
    });
  });

  it('surfaces the typed 401 reauth_required error', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(jsonResponse(
      { detail: { code: REAUTH_REQUIRED_CODE } },
      401,
    )));
    await expect(requestAccountDeletion({ confirmation: 'DELETE', reauthRecoveryId: 'stale' }))
      .rejects.toEqual(expect.objectContaining({ status: 401, code: REAUTH_REQUIRED_CODE }));
  });

  it('surfaces a typed 422 for a wrong confirmation phrase', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(jsonResponse(
      { detail: { code: 'invalid_confirmation', field: 'confirmation' } },
      422,
    )));
    await expect(requestAccountDeletion({ confirmation: 'delete', reauthRecoveryId: 'recovery-1' }))
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

  it('persists only the opaque request id to sessionStorage (no PII)', () => {
    const session = new Map<string, string>();
    const storage = (map: Map<string, string>): Storage => ({
      get length() { return map.size; },
      clear: () => map.clear(),
      getItem: (key) => map.get(key) ?? null,
      key: (index) => [...map.keys()][index] ?? null,
      removeItem: (key) => { map.delete(key); },
      setItem: (key, value) => { map.set(key, value); },
    });
    vi.stubGlobal('window', { sessionStorage: storage(session) });

    savePrivacyRequestRef('export', 'opaque-export-1');
    expect(loadPrivacyRequestRef('export')).toBe('opaque-export-1');
    expect([...session.values()].join(' ')).toBe('opaque-export-1');
    clearPrivacyRequestRef('export');
    expect(loadPrivacyRequestRef('export')).toBeNull();
  });
});
