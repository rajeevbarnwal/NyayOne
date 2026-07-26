import { afterEach, describe, expect, it, vi } from 'vitest';
import {
  loadRegistrationSession,
  registerStudent,
  saveAcademicProfile,
  saveRegistrationSession,
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
});
