import { afterEach, describe, expect, it, vi } from 'vitest';
import {
  loadRegistrationSession,
  getStudentSession,
  logoutStudent,
  registerStudent,
  saveAcademicProfile,
  requestInstitutionalEmailVerification,
  saveRegistrationSession,
  startLoginOtp,
  verifyLoginOtp,
} from './registrationApi';

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe('server-authoritative student registration API', () => {
  it('maps split names, exact mobile, DOB and consent to the backend contract', async () => {
    const fetchMock = vi.fn().mockResolvedValue(new Response(JSON.stringify({
      registration_id: 'opaque-registration-id',
      status: 'otp_pending',
    }), { status: 201, headers: { 'Content-Type': 'application/json' } }));
    vi.stubGlobal('fetch', fetchMock);

    const result = await registerStudent({
      firstName: 'Aditi',
      middleName: null,
      lastName: 'Nair',
      mobile: '9876543210',
      dob: '2004-03-14',
      policyVersion: 'dpdp-2023.v1',
    }, 'idempotency-1');

    expect(result.registration_id).toBe('opaque-registration-id');
    const [, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(new Headers(init.headers).get('Idempotency-Key')).toBe('idempotency-1');
    expect(JSON.parse(String(init.body))).toEqual({
      first_name: 'Aditi',
      middle_name: null,
      last_name: 'Nair',
      mobile: '9876543210',
      dob: '2004-03-14',
      consent: { accepted: true, policy_version: 'dpdp-2023.v1' },
    });
  });

  it('maps every legacy academic field to the profile API', async () => {
    const fetchMock = vi.fn().mockResolvedValue(new Response(
      JSON.stringify({ status: 'saved' }),
      { status: 200, headers: { 'Content-Type': 'application/json' } },
    ));
    vi.stubGlobal('fetch', fetchMock);

    await saveAcademicProfile({
      registrationId: 'opaque-registration-id',
      college: 'NLSIU',
      yearOfStudy: '3rd year',
      enrolmentNumber: 'KA/1234/2023',
      institutionalEmail: 'aditi@nls.ac.in',
      barEnrolmentNumber: 'D/1234/2024',
    });
    const [, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(JSON.parse(String(init.body))).toEqual({
      registration_id: 'opaque-registration-id',
      college: 'NLSIU',
      year_of_study: '3rd year',
      enrolment_number: 'KA/1234/2023',
      institutional_email: 'aditi@nls.ac.in',
      bar_enrolment_number: 'D/1234/2024',
    });
  });

  it('posts the S-15 email request to the typed server boundary', async () => {
    const fetchMock = vi.fn().mockResolvedValue(new Response(
      JSON.stringify({ status: 'pending' }),
      { status: 202, headers: { 'Content-Type': 'application/json' } },
    ));
    vi.stubGlobal('fetch', fetchMock);

    await expect(requestInstitutionalEmailVerification(
      'opaque-registration-id',
      '  aditi@nls.ac.in  ',
    )).resolves.toEqual({ status: 'pending' });

    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toContain('/api/v1/auth/student/verification/email/request');
    expect(init.method).toBe('POST');
    expect(JSON.parse(String(init.body))).toEqual({
      registration_id: 'opaque-registration-id',
      institutional_email: 'aditi@nls.ac.in',
    });
  });

  it('persists only opaque/minimal state and removes the legacy PII draft', () => {
    const session = new Map<string, string>();
    const local = new Map<string, string>([
      ['legalsaathi.student.profile.v1', JSON.stringify({ mobile: '9876543210', fullName: 'Aditi Nair' })],
    ]);
    const storage = (map: Map<string, string>): Storage => ({
      get length() { return map.size; },
      clear: () => map.clear(),
      getItem: (key) => map.get(key) ?? null,
      key: (index) => [...map.keys()][index] ?? null,
      removeItem: (key) => { map.delete(key); },
      setItem: (key, value) => { map.set(key, value); },
    });
    vi.stubGlobal('window', {
      sessionStorage: storage(session),
      localStorage: storage(local),
    });

    saveRegistrationSession({
      registrationId: 'opaque-registration-id',
      destinationMasked: '••••••3210',
      issuedAt: 123,
      isMinor: false,
      guardianConsentPending: false,
    });

    expect(loadRegistrationSession()?.registrationId).toBe('opaque-registration-id');
    expect(local.has('legalsaathi.student.profile.v1')).toBe(false);
    const serialized = [...session.values()].join(' ');
    expect(serialized).not.toContain('9876543210');
    expect(serialized).not.toContain('Aditi');
  });

  it('preserves the production typed field-error contract', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response(JSON.stringify({
      detail: {
        code: 'validation_error',
        field: 'mobile',
        message: 'Request validation failed',
      },
      request_id: 'request-1',
    }), { status: 422, headers: { 'Content-Type': 'application/json' } })));

    await expect(registerStudent({
      firstName: 'Aditi',
      middleName: null,
      lastName: 'Nair',
      mobile: '98765432101',
      dob: '2004-03-14',
      policyVersion: 'dpdp-2023.v1',
    })).rejects.toEqual(expect.objectContaining({
      status: 422,
      code: 'validation_error',
      field: 'mobile',
    }));
  });

  it('uses the real cookie-backed login/session/logout endpoints without exposing a token', async () => {
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(new Response(JSON.stringify({ login_id: 'a'.repeat(32) }), {
        status: 202, headers: { 'Content-Type': 'application/json' },
      }))
      .mockResolvedValueOnce(new Response(JSON.stringify({ status: 'authenticated' }), {
        status: 200, headers: { 'Content-Type': 'application/json' },
      }))
      .mockResolvedValueOnce(new Response(JSON.stringify({
        authenticated: true,
        actor: {
          sub: 'opaque-user-id', roles: ['student'], student_profile_id: null,
          student_verification: 'draft', is_minor: false, consent_state: ['registration'],
        },
      }), { status: 200, headers: { 'Content-Type': 'application/json' } }))
      .mockResolvedValueOnce(new Response(JSON.stringify({ status: 'logged_out' }), {
        status: 200, headers: { 'Content-Type': 'application/json' },
      }));
    vi.stubGlobal('fetch', fetchMock);

    const loginId = await startLoginOtp('9876543210');
    await verifyLoginOtp(loginId, '123456');
    const actor = await getStudentSession();
    await logoutStudent();

    expect(loginId).toBe('a'.repeat(32));
    expect(actor?.sub).toBe('opaque-user-id');
    expect(fetchMock.mock.calls.map(([url]) => String(url))).toEqual([
      expect.stringContaining('/api/v1/auth/student/login/otp/start'),
      expect.stringContaining('/api/v1/auth/student/login/otp/verify'),
      expect.stringContaining('/api/v1/auth/student/session'),
      expect.stringContaining('/api/v1/auth/student/logout'),
    ]);
    for (const [, init] of fetchMock.mock.calls as Array<[string, RequestInit]>) {
      expect(init.credentials).toBe('include');
      expect(String(init.body ?? '')).not.toContain('session_token');
    }
  });

  it('maps the non-error anonymous session probe to no actor', async () => {
    const fetchMock = vi.fn().mockResolvedValue(new Response(JSON.stringify({
      authenticated: false,
      actor: null,
    }), { status: 200, headers: { 'Content-Type': 'application/json' } }));
    vi.stubGlobal('fetch', fetchMock);
    await expect(getStudentSession()).resolves.toBeNull();
    expect(fetchMock).toHaveBeenCalledOnce();
  });
});
