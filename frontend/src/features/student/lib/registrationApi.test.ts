import { afterEach, describe, expect, it, vi } from 'vitest';
import {
  RegistrationApiError,
  cancelStudentOtp,
  clearRegistrationSession,
  completeRecovery,
  getOtpFlowState,
  getStudentSession,
  logoutStudent,
  registerStudent,
  resendStudentOtp,
  saveAcademicProfile,
  startLoginOtp,
  startRecovery,
  STUDENT_SESSION_TIMEOUT_MS,
  verifyLoginOtp,
  verifyRecovery,
  verifyStudentOtp,
} from './registrationApi';
import {
  STUDENT_AUTH_CHANGED_EVENT,
  STUDENT_AUTH_TRANSITION_STARTED_EVENT,
} from './studentBrowserContext';
import {
  getRegistrationAttempt,
  setRegistrationAttempt,
} from './registrationAttemptStore';

class TestBroadcastChannel {
  readonly name: string;
  onmessage: ((event: MessageEvent) => void) | null = null;

  constructor(name: string) { this.name = name; }
  postMessage(_data: unknown): void {}
  close(): void {}
}

const FLOW_HANDLE_RE = /(?:registration|login|recovery)(?:_(?:id|token)|(?:Id|Token))/;

const PENDING_WIRE = {
  status: 'pending',
  purpose: 'signup',
  destination_masked: '••••••3210',
  attempts_left: 3,
  expires_in_seconds: 287,
  resend_in_seconds: 17,
  locked_for_seconds: 0,
  resend_allowed: false,
} as const;

const AUTHENTICATED_WIRE = {
  status: 'authenticated',
  purpose: 'signup',
  destination_masked: null,
  attempts_left: null,
  expires_in_seconds: null,
  resend_in_seconds: null,
  locked_for_seconds: null,
  resend_allowed: false,
} as const;

const UNAVAILABLE_WIRE = {
  status: 'unavailable',
  purpose: null,
  destination_masked: null,
  attempts_left: null,
  expires_in_seconds: null,
  resend_in_seconds: null,
  locked_for_seconds: null,
  resend_allowed: false,
} as const;

const ONBOARDING_WIRE = {
  profile_version: 1,
  completion_version: 'v1',
  completion_percent: 0,
  completed_sections: [],
  missing_requirements: [
    'personal.preferred_language',
    'personal.city',
    'academic.college',
    'academic.year_of_study',
    'academic.enrolment_number',
    'interests.interests',
    'interests.goals',
  ],
  next_incomplete_section: 'personal',
  is_complete: false,
  institutional_email_status: 'not_provided',
  guardian: { required: false, status: 'not_required' },
  access_mode: 'full',
  disabled_capabilities: [],
  profile_prompt: { should_show: true, dismissed_for_session: false },
  profile: {
    personal: { first_name: 'Aditi', middle_name: null, last_name: 'Nair', date_of_birth: '2004-03-14', preferred_language: null, city: null, pronouns: null },
    academic: { college: null, year_of_study: null, enrolment_number: null, institutional_email: null, bar_enrolment_number: null },
    interests: { interests: [], goals: [] },
  },
} as const;

const AUTHENTICATED_WITH_ONBOARDING = {
  ...AUTHENTICATED_WIRE,
  onboarding: ONBOARDING_WIRE,
} as const;

const REGISTRATION_ACCEPTED_WIRE = {
  status: 'accepted',
  next: 'otp',
  expires_in_seconds: 300,
  resend_after_seconds: 30,
} as const;

function response(body: unknown, status = 200, headers: Record<string, string> = {}) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json', ...headers },
  });
}

function registrationInput() {
  return {
    firstName: 'Aditi',
    middleName: null,
    lastName: 'Nair',
    mobile: '9876543210',
    dob: '2004-03-14',
    termsAccepted: true,
    termsVersion: 'dpdp-2023.v1',
    privacyNoticeAcknowledged: true,
    privacyNoticeVersion: 'dpdp-2023.v1',
  };
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

afterEach(() => {
  vi.useRealTimers();
  clearRegistrationSession();
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe('server-owned student OTP flow API (NYAY-4)', () => {
  it('retires the server-owned OTP context with an empty-body POST', async () => {
    const fetchMock = vi.fn().mockResolvedValue(response(UNAVAILABLE_WIRE));
    vi.stubGlobal('fetch', fetchMock);

    await expect(cancelStudentOtp()).resolves.toEqual({
      status: 'unavailable',
      purpose: null,
      destinationMasked: null,
      attemptsLeft: null,
      expiresInSeconds: null,
      resendInSeconds: null,
      lockedForSeconds: null,
      resendAllowed: false,
    });

    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toContain('/api/v1/auth/student/otp/cancel');
    expect(init.method).toBe('POST');
    expect(JSON.parse(String(init.body))).toEqual({});
    expect(init.credentials).toBe('include');
  });

  it('clears an uncertain page-memory registration attempt before cancellation resolves', async () => {
    let finishRequest: ((value: Response) => void) | undefined;
    const fetchResult = new Promise<Response>((resolve) => { finishRequest = resolve; });
    vi.stubGlobal('fetch', vi.fn().mockReturnValue(fetchResult));
    setRegistrationAttempt({ body: '{"mobile":"9876543210"}', key: 'attempt-key' });

    const cancellation = cancelStudentOtp();
    expect(getRegistrationAttempt()).toBeNull();

    finishRequest?.(response(UNAVAILABLE_WIRE));
    await expect(cancellation).resolves.toMatchObject({
      status: 'unavailable',
      purpose: null,
    });
  });

  it('rejects a nonterminal cancellation projection fail closed', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(response(PENDING_WIRE)));

    await expect(cancelStudentOtp()).rejects.toEqual(expect.objectContaining({
      status: 502,
      code: 'invalid_otp_cancel_projection',
    }));
  });

  it('holds every realm pending before signup can replace the shared auth cookie', async () => {
    const order: string[] = [];
    const browserWindow = new EventTarget();
    browserWindow.addEventListener(STUDENT_AUTH_TRANSITION_STARTED_EVENT, () => order.push('start'));
    browserWindow.addEventListener(STUDENT_AUTH_CHANGED_EVENT, () => order.push('end'));
    vi.stubGlobal('window', browserWindow);
    vi.stubGlobal('BroadcastChannel', TestBroadcastChannel);
    const fetchMock = vi.fn(async (url: string) => {
      order.push(url.includes('/session') ? 'session' : 'verify');
      return url.includes('/session')
        ? response({
          authenticated: true,
          actor: {
            sub: '00000000-0000-4000-8000-000000002701', roles: ['student'],
            student_profile_id: '00000000-0000-4000-8000-000000002702',
            student_verification: 'draft', is_minor: false,
            consent_state: ['privacy_notice', 'terms'],
          },
        })
        : response(AUTHENTICATED_WITH_ONBOARDING);
    });
    vi.stubGlobal('fetch', fetchMock);

    await expect(verifyStudentOtp('123456')).resolves.toMatchObject({
      status: 'authenticated', purpose: 'signup',
    });

    expect(order).toEqual(['start', 'verify', 'session', 'end']);
  });
  it('maps the uniform registration acceptance without exposing a correlation handle', async () => {
    const fetchMock = vi.fn().mockResolvedValue(response(REGISTRATION_ACCEPTED_WIRE, 202));
    vi.stubGlobal('fetch', fetchMock);

    const result = await registerStudent(registrationInput(), 'idempotency-1');

    expect(result).toEqual({
      status: 'accepted',
      next: 'otp',
      expiresInSeconds: 300,
      resendAfterSeconds: 30,
    });
    const [, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(new Headers(init.headers).get('Idempotency-Key')).toBe('idempotency-1');
    expect(JSON.parse(String(init.body))).toEqual({
      first_name: 'Aditi',
      middle_name: null,
      last_name: 'Nair',
      mobile: '9876543210',
      dob: '2004-03-14',
      terms_accepted: true,
      terms_version: 'dpdp-2023.v1',
      privacy_notice_acknowledged: true,
      privacy_notice_version: 'dpdp-2023.v1',
    });
    expect(JSON.stringify(result)).not.toMatch(FLOW_HANDLE_RE);
  });

  it.each([
    ['old detailed OTP projection', PENDING_WIRE],
    ['wrong status', { ...REGISTRATION_ACCEPTED_WIRE, status: 'created' }],
    ['wrong next route', { ...REGISTRATION_ACCEPTED_WIRE, next: '/s-09' }],
    ['absolute expiry', { ...REGISTRATION_ACCEPTED_WIRE, expires_at: '2026-08-22T00:00:00Z' }],
    ['extra identity field', { ...REGISTRATION_ACCEPTED_WIRE, registration_id: 'forbidden' }],
  ])('rejects the %s registration response', async (_label, body) => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(response(body, 202)));
    await expect(registerStudent(registrationInput(), 'idempotency-invalid'))
      .rejects.toEqual(expect.objectContaining({
        status: 502,
        code: 'invalid_registration_start_projection',
      }));
  });

  it('never accepts or forwards academic profile data during core registration', async () => {
    const fetchMock = vi.fn().mockResolvedValue(response(REGISTRATION_ACCEPTED_WIRE, 202));
    vi.stubGlobal('fetch', fetchMock);

    const attemptedLegacyInput = {
      ...registrationInput(),
      college: 'NLSIU',
      yearOfStudy: '3',
      institutionalEmail: 'aditi@example.edu',
      barEnrolmentNumber: 'KA/1234/2023',
    } as unknown as Parameters<typeof registerStudent>[0] & Record<string, unknown>;
    await registerStudent(attemptedLegacyInput, 'idempotency-core-only');

    const [, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(JSON.parse(String(init.body))).toEqual({
      first_name: 'Aditi',
      middle_name: null,
      last_name: 'Nair',
      mobile: '9876543210',
      dob: '2004-03-14',
      terms_accepted: true,
      terms_version: 'dpdp-2023.v1',
      privacy_notice_acknowledged: true,
      privacy_notice_version: 'dpdp-2023.v1',
    });
  });

  it('reuses one memory-only idempotency key after an uncertain transport failure', async () => {
    const fetchMock = vi.fn()
      .mockRejectedValueOnce(new TypeError('synthetic network failure'))
      .mockResolvedValueOnce(response(REGISTRATION_ACCEPTED_WIRE, 202));
    vi.stubGlobal('fetch', fetchMock);

    await expect(registerStudent(registrationInput())).rejects.toBeInstanceOf(TypeError);
    await expect(registerStudent(registrationInput())).resolves.toMatchObject({ status: 'accepted' });

    const keys = fetchMock.mock.calls.map(([, init]) => (
      new Headers((init as RequestInit).headers).get('Idempotency-Key')
    ));
    expect(keys[0]).toBeTruthy();
    expect(keys[1]).toBe(keys[0]);
  });

  it('rotates the memory-only key when accepted request content changes', async () => {
    const fetchMock = vi.fn().mockRejectedValue(new TypeError('synthetic network failure'));
    vi.stubGlobal('fetch', fetchMock);
    await expect(registerStudent(registrationInput())).rejects.toBeInstanceOf(TypeError);
    await expect(registerStudent({ ...registrationInput(), lastName: 'Rao' }))
      .rejects.toBeInstanceOf(TypeError);
    const keys = fetchMock.mock.calls.map(([, init]) => (
      new Headers((init as RequestInit).headers).get('Idempotency-Key')
    ));
    expect(keys[0]).not.toBe(keys[1]);
  });

  it('maps relative typed error state and Retry-After without inventing an attempt reset', async () => {
    const locked = {
      ...PENDING_WIRE,
      attempts_left: 0,
      resend_in_seconds: 23,
      locked_for_seconds: 811,
    };
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(response({
      detail: { code: 'otp_locked', otp_state: locked },
    }, 423, { 'Retry-After': '811' })));

    await expect(verifyStudentOtp('000000')).rejects.toEqual(expect.objectContaining({
      status: 423,
      code: 'otp_locked',
      attemptsLeft: 0,
      retryAfterSeconds: 811,
      otpState: expect.objectContaining({
        attemptsLeft: 0,
        resendInSeconds: 23,
        lockedForSeconds: 811,
      }),
    }));
  });

  it('rejects a malformed typed error projection instead of retaining stale authority', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(response({
      detail: {
        code: 'otp_locked',
        otp_state: { ...PENDING_WIRE, destination_masked: '9876543210' },
      },
    }, 423)));
    await expect(verifyStudentOtp('000000')).rejects.toEqual(expect.objectContaining({
      status: 502, code: 'invalid_otp_state',
    }));
  });

  it('uses identifier-free verify/resend bodies and trusts direct mutation projections', async () => {
    const resent = { ...PENDING_WIRE, expires_in_seconds: 299, resend_in_seconds: 29 };
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(response(AUTHENTICATED_WITH_ONBOARDING))
      .mockResolvedValueOnce(response(resent, 202));
    vi.stubGlobal('fetch', fetchMock);

    await expect(verifyStudentOtp('123456')).resolves.toMatchObject({
      status: 'authenticated',
      onboarding: { profileVersion: 1, completionPercent: 0, nextIncompleteSection: 'personal' },
    });
    await expect(resendStudentOtp()).resolves.toMatchObject({
      status: 'pending', expiresInSeconds: 299, resendInSeconds: 29,
    });

    expect(fetchMock).toHaveBeenCalledTimes(2);
    expect(JSON.parse(String((fetchMock.mock.calls[0][1] as RequestInit).body))).toEqual({ code: '123456' });
    expect(JSON.parse(String((fetchMock.mock.calls[1][1] as RequestInit).body))).toEqual({});
    expect(fetchMock.mock.calls.map(([url]) => String(url))).not.toContain(
      expect.stringContaining('/otp/state'),
    );
    const serialised = JSON.stringify(fetchMock.mock.calls);
    expect(serialised).not.toMatch(FLOW_HANDLE_RE);
  });

  it('rejects an authenticated verify response without one exact onboarding projection', async () => {
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(response(AUTHENTICATED_WIRE))
      .mockResolvedValueOnce(response({
        ...AUTHENTICATED_WITH_ONBOARDING,
        onboarding: { ...ONBOARDING_WIRE, completion_percent: 67 },
      }))
      .mockResolvedValueOnce(response({ ...AUTHENTICATED_WITH_ONBOARDING, bearer: 'forbidden' }));
    vi.stubGlobal('fetch', fetchMock);

    for (let attempt = 0; attempt < 3; attempt += 1) {
      await expect(verifyStudentOtp('123456')).rejects.toEqual(expect.objectContaining({
        status: 502,
        code: 'invalid_otp_verification_projection',
      }));
    }
  });

  it('rejects a successful verification projection for the wrong OTP purpose', async () => {
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(response({ ...AUTHENTICATED_WITH_ONBOARDING, purpose: 'login' }))
      .mockResolvedValueOnce(response(AUTHENTICATED_WITH_ONBOARDING));
    vi.stubGlobal('fetch', fetchMock);

    await expect(verifyStudentOtp('123456')).rejects.toEqual(expect.objectContaining({
      status: 502,
      code: 'invalid_otp_verification_projection',
    }));
    await expect(verifyLoginOtp('123456')).rejects.toEqual(expect.objectContaining({
      status: 502,
      code: 'invalid_otp_verification_projection',
    }));
  });

  it('restores the flow after reload only through the HttpOnly-cookie state endpoint', async () => {
    const local = new Map<string, string>([
      ['legalsaathi.student.profile.v1', '{"mobile":"9876543210"}'],
      ['ls-auth-student', '{"phase":"otp_entry","challenge":{"code":"planted"}}'],
    ]);
    const session = new Map<string, string>([
      ['legalsaathi.student.registration.v2', '{"registrationId":"legacy"}'],
    ]);
    vi.stubGlobal('window', { localStorage: storage(local), sessionStorage: storage(session) });
    const fetchMock = vi.fn().mockResolvedValue(response(PENDING_WIRE));
    vi.stubGlobal('fetch', fetchMock);

    await expect(getOtpFlowState()).resolves.toMatchObject({
      status: 'pending', attemptsLeft: 3, expiresInSeconds: 287,
    });
    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toContain('/api/v1/auth/student/otp/state');
    expect(init.method).toBe('GET');
    expect(init.credentials).toBe('include');
    expect(local.size).toBe(0);
    expect(session.size).toBe(0);
  });

  it('rejects malformed or absolute-time flow state fail closed', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(response({
      ...PENDING_WIRE,
      expires_at: '2026-08-21T10:00:00Z',
    })));
    await expect(getOtpFlowState()).rejects.toEqual(expect.objectContaining({
      status: 502, code: 'invalid_otp_state',
    }));
  });

  it('accepts a live flow whose expired verifier can be authoritatively resent', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(response({
      ...PENDING_WIRE,
      expires_in_seconds: 0,
      resend_in_seconds: 0,
      locked_for_seconds: 0,
      resend_allowed: true,
    })));
    await expect(getOtpFlowState()).resolves.toEqual(expect.objectContaining({
      status: 'pending',
      expiresInSeconds: 0,
      resendAllowed: true,
    }));
  });

  it.each([
    ['raw mobile destination', { ...PENDING_WIRE, destination_masked: '9876543210' }],
    ['UUID destination', { ...PENDING_WIRE, destination_masked: '6f1ed002-ab75-4df2-8ec1-6d9194132934' }],
    ['token-like destination', { ...PENDING_WIRE, destination_masked: 'eyJhbGciOiJIUzI1NiJ9' }],
    ['wrong bullet count', { ...PENDING_WIRE, destination_masked: '•••••3210' }],
    ['pending null destination', { ...PENDING_WIRE, destination_masked: null }],
    ['pending null attempt budget', { ...PENDING_WIRE, attempts_left: null }],
    ['pending null expiry', { ...PENDING_WIRE, expires_in_seconds: null }],
    ['resend permitted during cooldown', { ...PENDING_WIRE, resend_allowed: true }],
    ['resend permitted without attempts', {
      ...PENDING_WIRE, attempts_left: 0, resend_in_seconds: 0, resend_allowed: true,
    }],
    ['verified signup status-purpose mismatch', {
      ...AUTHENTICATED_WIRE, status: 'verified', purpose: 'signup',
    }],
    ['authenticated recovery status-purpose mismatch', {
      ...AUTHENTICATED_WIRE, purpose: 'recovery',
    }],
    ['unavailable retains a purpose', {
      ...AUTHENTICATED_WIRE, status: 'unavailable', purpose: 'signup',
    }],
    ['terminal state retains a counter', {
      ...AUTHENTICATED_WIRE, attempts_left: 0,
    }],
    ['terminal state permits resend', {
      ...AUTHENTICATED_WIRE, resend_allowed: true,
    }],
  ])('rejects the %s state mutant', async (_label, mutant) => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(response(mutant)));
    await expect(getOtpFlowState()).rejects.toEqual(expect.objectContaining({
      status: 502, code: 'invalid_otp_state',
    }));
  });

  it('keeps login known/decoy starts shape-identical and never consumes a login id', async () => {
    const loginState = { ...PENDING_WIRE, purpose: 'login' } as const;
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(response(loginState, 202))
      .mockResolvedValueOnce(response(loginState, 202))
      .mockResolvedValueOnce(response({
        ...AUTHENTICATED_WITH_ONBOARDING,
        purpose: 'login',
      }));
    vi.stubGlobal('fetch', fetchMock);

    const known = await startLoginOtp('9876543210');
    const decoy = await startLoginOtp('9000000000');
    await expect(verifyLoginOtp('123456')).resolves.toMatchObject({
      purpose: 'login',
      onboarding: { profileVersion: 1 },
    });

    expect(known).toEqual(decoy);
    expect(JSON.parse(String((fetchMock.mock.calls[2][1] as RequestInit).body))).toEqual({ code: '123456' });
    expect(JSON.stringify(fetchMock.mock.calls)).not.toMatch(FLOW_HANDLE_RE);
  });

  it('uses a cookie-owned recovery proof through verify and complete', async () => {
    const pending = { ...PENDING_WIRE, purpose: 'recovery' } as const;
    const verified = {
      ...pending,
      status: 'verified',
      destination_masked: null,
      attempts_left: null,
      expires_in_seconds: null,
      resend_in_seconds: null,
      locked_for_seconds: null,
      resend_allowed: false,
    } as const;
    const unavailable = { ...verified, status: 'unavailable', purpose: null } as const;
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(response(pending, 202))
      .mockResolvedValueOnce(response(verified))
      .mockResolvedValueOnce(response(unavailable));
    vi.stubGlobal('fetch', fetchMock);

    await startRecovery('9876543210');
    await expect(verifyRecovery('123456')).resolves.toMatchObject({ status: 'verified' });
    await expect(completeRecovery()).resolves.toMatchObject({ status: 'unavailable' });

    expect(JSON.parse(String((fetchMock.mock.calls[1][1] as RequestInit).body))).toEqual({ code: '123456' });
    expect(JSON.parse(String((fetchMock.mock.calls[2][1] as RequestInit).body))).toEqual({});
    expect(JSON.stringify(fetchMock.mock.calls)).not.toMatch(FLOW_HANDLE_RE);
  });
});

describe('bounded server session discovery (NYAY-5)', () => {
  it('fails a hung session discovery closed at a deterministic timeout', async () => {
    vi.useFakeTimers();
    const fetchMock = vi.fn().mockImplementation((_url: string, init: RequestInit) => (
      new Promise((_resolve, reject) => {
        init.signal?.addEventListener('abort', () => {
          reject(new DOMException('timeout', 'AbortError'));
        });
      })
    ));
    vi.stubGlobal('fetch', fetchMock);

    const attempt = getStudentSession();
    const assertion = expect(attempt).rejects.toEqual(expect.objectContaining({
      status: 0,
      code: 'session_unavailable',
    }));
    await vi.advanceTimersByTimeAsync(STUDENT_SESSION_TIMEOUT_MS);
    await assertion;
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });
});

describe('adjacent authenticated student boundaries', () => {
  const projection = {
    profile_version: 7,
    completion_version: 'v1',
    completion_percent: 34,
    completed_sections: ['personal'],
    missing_requirements: [
      'academic.college',
      'academic.year_of_study',
      'academic.enrolment_number',
      'interests.interests',
      'interests.goals',
    ],
    next_incomplete_section: 'academic',
    is_complete: false,
    institutional_email_status: 'not_provided',
    guardian: { required: false, status: 'not_required' },
    access_mode: 'full',
    disabled_capabilities: [],
    profile_prompt: { should_show: true, dismissed_for_session: false },
    profile: {
      personal: { first_name: 'Aditi', middle_name: null, last_name: 'Nair', date_of_birth: '2002-03-14', preferred_language: 'en', city: 'Pune', pronouns: null },
      academic: { college: null, year_of_study: null, enrolment_number: null, institutional_email: null, bar_enrolment_number: null },
      interests: { interests: [], goals: [] },
    },
  };

  it('delegates the legacy academic helper through the versioned canonical boundary', async () => {
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(response(projection))
      .mockResolvedValueOnce(response({
        ...projection,
        profile_version: 8,
        completion_percent: 67,
        completed_sections: ['personal', 'academic'],
        missing_requirements: ['interests.interests', 'interests.goals'],
        next_incomplete_section: 'interests',
        institutional_email_status: 'pending',
        profile: { ...projection.profile, academic: { college: 'NLSIU', year_of_study: '3rd year', enrolment_number: 'KA/1234/2023', institutional_email: 'aditi@nls.ac.in', bar_enrolment_number: 'D/1234/2024' } },
      }));
    vi.stubGlobal('fetch', fetchMock);
    await saveAcademicProfile({
      college: 'NLSIU',
      yearOfStudy: '3rd year',
      enrolmentNumber: 'KA/1234/2023',
      institutionalEmail: 'aditi@nls.ac.in',
      barEnrolmentNumber: 'D/1234/2024',
    });
    const [readUrl, readInit] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(readUrl).toContain('/api/v1/student/profile');
    expect(readInit.method).toBe('GET');
    const [writeUrl, init] = fetchMock.mock.calls[1] as [string, RequestInit];
    expect(writeUrl).toContain('/api/v1/student/profile/academic');
    expect(JSON.parse(String(init.body))).toEqual({
      expected_profile_version: 7,
      college: 'NLSIU',
      year_of_study: '3rd year',
      enrolment_number: 'KA/1234/2023',
      institutional_email: 'aditi@nls.ac.in',
      bar_enrolment_number: 'D/1234/2024',
    });
  });

  it('uses the cookie-backed session/logout endpoints without exposing a token', async () => {
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(response({
        authenticated: true,
        actor: {
          sub: '00000000-0000-4000-8000-000000002701', roles: ['student'],
          student_profile_id: '00000000-0000-4000-8000-000000002702',
          student_verification: 'draft', is_minor: false,
          consent_state: ['privacy_notice', 'terms'],
        },
      }))
      .mockResolvedValueOnce(response({ status: 'logged_out' }));
    vi.stubGlobal('fetch', fetchMock);

    expect((await getStudentSession())?.sub).toBe('00000000-0000-4000-8000-000000002701');
    await logoutStudent();
    for (const [, init] of fetchMock.mock.calls as Array<[string, RequestInit]>) {
      expect(init.credentials).toBe('include');
      expect(String(init.body ?? '')).not.toContain('session_token');
    }
  });

  it.each(['moderator', 'admin', 'safety_officer', 'legal_reviewer'])('accepts an exact server-issued %s session', async (role) => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(response({
      authenticated: true,
      actor: {
        sub: '00000000-0000-4000-8000-000000002740', roles: [role],
        student_profile_id: null, student_verification: 'draft',
        is_minor: false, consent_state: [],
      },
    })));

    await expect(getStudentSession()).resolves.toEqual(expect.objectContaining({ roles: [role] }));
  });

  it.each([
    ['empty', []],
    ['unknown', ['owner']],
    ['mixed', ['moderator', 'admin']],
    ['forged student mix', ['student', 'admin']],
    ['malformed', [7]],
  ])('rejects %s server-session roles fail-closed', async (_label, roles) => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(response({
      authenticated: true,
      actor: {
        sub: '00000000-0000-4000-8000-000000002740', roles,
        student_profile_id: null, student_verification: 'draft',
        is_minor: false, consent_state: [],
      },
    })));

    await expect(getStudentSession()).rejects.toEqual(expect.objectContaining({
      status: 502,
      code: 'invalid_student_session_projection',
    }));
  });

  it.each([
    ['extra outer authority', {
      authenticated: true,
      actor: {
        sub: '00000000-0000-4000-8000-000000002701', roles: ['student'],
        student_profile_id: '00000000-0000-4000-8000-000000002702',
        student_verification: 'draft', is_minor: false,
        consent_state: ['privacy_notice', 'terms'],
      },
      bearer: 'forbidden',
    }],
    ['extra actor authority', {
      authenticated: true,
      actor: {
        sub: '00000000-0000-4000-8000-000000002701', roles: ['student'],
        student_profile_id: '00000000-0000-4000-8000-000000002702',
        student_verification: 'draft', is_minor: false,
        consent_state: ['privacy_notice', 'terms'], token: 'forbidden',
      },
    }],
    ['non-UUID subject', {
      authenticated: true,
      actor: {
        sub: 'opaque-but-not-canonical', roles: ['student'],
        student_profile_id: '00000000-0000-4000-8000-000000002702',
        student_verification: 'draft', is_minor: false,
        consent_state: ['privacy_notice', 'terms'],
      },
    }],
    ['student without profile authority', {
      authenticated: true,
      actor: {
        sub: '00000000-0000-4000-8000-000000002701', roles: ['student'],
        student_profile_id: null, student_verification: 'draft', is_minor: false,
        consent_state: ['privacy_notice', 'terms'],
      },
    }],
    ['staff with student profile authority', {
      authenticated: true,
      actor: {
        sub: '00000000-0000-4000-8000-000000002701', roles: ['moderator'],
        student_profile_id: '00000000-0000-4000-8000-000000002702',
        student_verification: 'draft', is_minor: false, consent_state: [],
      },
    }],
    ['duplicate consent authority', {
      authenticated: true,
      actor: {
        sub: '00000000-0000-4000-8000-000000002701', roles: ['student'],
        student_profile_id: '00000000-0000-4000-8000-000000002702',
        student_verification: 'draft', is_minor: false,
        consent_state: ['terms', 'terms'],
      },
    }],
    ['unknown consent authority', {
      authenticated: true,
      actor: {
        sub: '00000000-0000-4000-8000-000000002701', roles: ['student'],
        student_profile_id: '00000000-0000-4000-8000-000000002702',
        student_verification: 'draft', is_minor: false,
        consent_state: ['all_future_purposes'],
      },
    }],
  ])('rejects %s in the session projection before observing an actor', async (_label, body) => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(response(body)));

    await expect(getStudentSession()).rejects.toEqual(expect.objectContaining({
      status: 502,
      code: 'invalid_student_session_projection',
    }));
  });

  it('preserves the typed field-error contract', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(response({
      detail: { code: 'validation_error', field: 'mobile' },
    }, 422)));
    await expect(registerStudent({ ...registrationInput(), mobile: '98765432101' }))
      .rejects.toEqual(expect.objectContaining({
        status: 422, code: 'validation_error', field: 'mobile',
      }));
  });

  it('retains RegistrationApiError identity for typed consumers', () => {
    expect(new RegistrationApiError(429, 'rate_limited')).toBeInstanceOf(Error);
  });
});
