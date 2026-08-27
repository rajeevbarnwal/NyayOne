import { afterEach, describe, expect, it, vi } from 'vitest';
import legalNameCorpus from '../../../../../contracts/unicode-legal-name-v1.json';
import {
  dismissProfilePrompt,
  getStudentProfileProjection,
  normalizeLegalName,
  PROFILE_WRITE_TIMEOUT_MS,
  profileErrorMessage,
  ProfileApiError,
  requestInstitutionalEmailVerification,
  updateAcademicProfile,
  updatePersonalProfile,
  validateLegalName,
} from './profileApi';

const PROJECTION_WIRE = {
  profile_version: 7,
  completion_version: 'v1',
  completion_percent: 67,
  completed_sections: ['personal', 'academic'],
  missing_requirements: ['interests.interests', 'interests.goals'],
  next_incomplete_section: 'interests',
  is_complete: false,
  institutional_email_status: 'pending',
  guardian: { required: false, status: 'not_required' },
  access_mode: 'full',
  disabled_capabilities: [],
  profile_prompt: { should_show: true, dismissed_for_session: false },
  profile: {
    personal: {
      first_name: 'Aditi',
      middle_name: null,
      last_name: 'Nair',
      date_of_birth: '2002-03-14',
      preferred_language: 'en',
      city: 'Bengaluru',
      pronouns: null,
    },
    academic: {
      college: 'NLSIU',
      year_of_study: '3',
      enrolment_number: 'KA/1234/2023',
      institutional_email: 'aditi@example.edu',
      bar_enrolment_number: null,
    },
    interests: { interests: [], goals: [] },
  },
} as const;

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  });
}

afterEach(() => {
  vi.useRealTimers();
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

describe('canonical server-authoritative profile projection', () => {
  it('GETs and strictly maps every authority field', async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse(PROJECTION_WIRE));
    vi.stubGlobal('fetch', fetchMock);

    await expect(getStudentProfileProjection()).resolves.toEqual({
      profileVersion: 7,
      completionVersion: 'v1',
      completionPercent: 67,
      completedSections: ['personal', 'academic'],
      missingRequirements: ['interests.interests', 'interests.goals'],
      nextIncompleteSection: 'interests',
      isComplete: false,
      institutionalEmailStatus: 'pending',
      guardian: { required: false, status: 'not_required' },
      accessMode: 'full',
      disabledCapabilities: [],
      profilePrompt: { shouldShow: true, dismissedForSession: false },
      profile: {
        personal: {
          firstName: 'Aditi', middleName: null, lastName: 'Nair',
          dateOfBirth: '2002-03-14', preferredLanguage: 'en', city: 'Bengaluru', pronouns: null,
        },
        academic: {
          college: 'NLSIU', yearOfStudy: '3', enrolmentNumber: 'KA/1234/2023',
          institutionalEmail: 'aditi@example.edu', barEnrolmentNumber: null,
        },
        interests: { interests: [], goals: [] },
      },
    });
    expect(String(fetchMock.mock.calls[0]?.[0])).toContain('/api/v1/student/profile');
  });

  it('rejects a malformed or invented completion projection', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(jsonResponse({
      ...PROJECTION_WIRE,
      completion_percent: 82,
    })));
    await expect(getStudentProfileProjection()).rejects.toEqual(
      expect.objectContaining({ status: 502, code: 'invalid_profile_projection' }),
    );
  });

  it('fails a hung initial projection fetch closed at the bounded timeout', async () => {
    vi.useFakeTimers();
    const fetchMock = vi.fn().mockImplementation((_url: string, init: RequestInit) => (
      new Promise((_resolve, reject) => {
        init.signal?.addEventListener('abort', () => {
          reject(new DOMException('timeout', 'AbortError'));
        });
      })
    ));
    vi.stubGlobal('fetch', fetchMock);

    const attempt = getStudentProfileProjection();
    const assertion = expect(attempt).rejects.toEqual(expect.objectContaining({
      status: 0,
      code: 'profile_request_timeout',
    }));
    await vi.advanceTimersByTimeAsync(PROFILE_WRITE_TIMEOUT_MS);
    await assertion;
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it('honours an explicit lower-level caller cancellation signal', async () => {
    const caller = new AbortController();
    let transportSignal: AbortSignal | undefined;
    const fetchMock = vi.fn().mockImplementation((_url: string, init: RequestInit) => (
      new Promise<Response>((_resolve, reject) => {
        transportSignal = init.signal ?? undefined;
        init.signal?.addEventListener('abort', () => {
          reject(new DOMException('caller cancelled', 'AbortError'));
        }, { once: true });
      })
    ));
    vi.stubGlobal('fetch', fetchMock);

    const attempt = getStudentProfileProjection(caller.signal);
    await vi.waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(1));
    expect(transportSignal?.aborted ?? true).toBe(false);

    caller.abort('caller_cancelled');
    await expect(attempt).rejects.toEqual(expect.objectContaining({ name: 'AbortError' }));
    expect(transportSignal?.aborted).toBe(true);
  });

  it.each([
    ['guardian contradiction', { ...PROJECTION_WIRE, guardian: { required: false, status: 'required_pending' } }],
    ['access contradiction', { ...PROJECTION_WIRE, access_mode: 'limited', disabled_capabilities: [] }],
    ['prompt contradiction', { ...PROJECTION_WIRE, profile_prompt: { should_show: false, dismissed_for_session: false } }],
    ['duplicate interests', {
      ...PROJECTION_WIRE,
      profile: { ...PROJECTION_WIRE.profile, interests: { interests: ['Tax', 'Tax'], goals: [] } },
    }],
    ['overlong interest', {
      ...PROJECTION_WIRE,
      profile: { ...PROJECTION_WIRE.profile, interests: { interests: ['x'.repeat(81)], goals: [] } },
    }],
    ['overlong city', {
      ...PROJECTION_WIRE,
      profile: { ...PROJECTION_WIRE.profile, personal: { ...PROJECTION_WIRE.profile.personal, city: 'x'.repeat(121) } },
    }],
    ['consumer-domain institutional email', {
      ...PROJECTION_WIRE,
      profile: {
        ...PROJECTION_WIRE.profile,
        academic: { ...PROJECTION_WIRE.profile.academic, institutional_email: 'aditi@gmail.com' },
      },
    }],
    ['completion/profile contradiction', {
      ...PROJECTION_WIRE,
      profile: { ...PROJECTION_WIRE.profile, personal: { ...PROJECTION_WIRE.profile.personal, city: null } },
    }],
  ])('rejects %s', async (_label, invalid) => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(jsonResponse(invalid)));
    await expect(getStudentProfileProjection()).rejects.toEqual(
      expect.objectContaining({ status: 502, code: 'invalid_profile_projection' }),
    );
  });
});

describe('versioned section mutations', () => {
  it('PATCHes the full personal section with expected_profile_version', async () => {
    const updated = {
      ...PROJECTION_WIRE,
      profile_version: 8,
      profile: {
        ...PROJECTION_WIRE.profile,
        personal: {
          ...PROJECTION_WIRE.profile.personal,
          first_name: 'Á',
          middle_name: 'D’Arcy',
          pronouns: 'she/her',
        },
      },
    };
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse(updated));
    vi.stubGlobal('fetch', fetchMock);

    const result = await updatePersonalProfile({
      expectedProfileVersion: 7,
      firstName: 'A\u0301',
      middleName: 'D’Arcy',
      lastName: 'Nair',
      dateOfBirth: '2002-03-14',
      preferredLanguage: 'en',
      city: 'Bengaluru',
      pronouns: 'she/her',
    });

    expect(result).toMatchObject({ certainty: 'confirmed', projection: { profileVersion: 8 } });

    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toContain('/api/v1/student/profile/personal');
    expect(init.method).toBe('PATCH');
    expect(new Headers(init.headers).get('Idempotency-Key')).toMatch(
      /^[A-Za-z0-9._~-]{16,200}$/,
    );
    expect(JSON.parse(String(init.body))).toEqual({
      expected_profile_version: 7,
      first_name: 'Á',
      middle_name: 'D’Arcy',
      last_name: 'Nair',
      date_of_birth: '2002-03-14',
      preferred_language: 'en',
      city: 'Bengaluru',
      pronouns: 'she/her',
    });
  });

  it('does not confirm a 2xx projection whose version skipped the submitted CAS successor', async () => {
    const contaminatedResponse = {
      ...PROJECTION_WIRE,
      profile_version: 9,
      profile: {
        ...PROJECTION_WIRE.profile,
        personal: { ...PROJECTION_WIRE.profile.personal, city: 'Pune' },
      },
    };
    const latestWinner = {
      ...PROJECTION_WIRE,
      profile_version: 9,
      profile: {
        ...PROJECTION_WIRE.profile,
        personal: { ...PROJECTION_WIRE.profile.personal, city: 'Mumbai' },
      },
    };
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(jsonResponse(contaminatedResponse))
      .mockResolvedValueOnce(jsonResponse(latestWinner));
    vi.stubGlobal('fetch', fetchMock);

    await expect(updatePersonalProfile({
      expectedProfileVersion: 7,
      firstName: 'Aditi', middleName: null, lastName: 'Nair', dateOfBirth: '2002-03-14',
      preferredLanguage: 'en', city: 'Pune', pronouns: null,
    })).rejects.toEqual(expect.objectContaining({
      code: 'profile_write_uncertain',
      latestProjection: expect.objectContaining({ profileVersion: 9 }),
    }));
    expect(fetchMock).toHaveBeenCalledTimes(2);
    expect((fetchMock.mock.calls[1]?.[1] as RequestInit).method).toBe('GET');
  });

  it('does not confirm a 2xx projection whose section differs from the submitted values', async () => {
    const mismatchedResponse = {
      ...PROJECTION_WIRE,
      profile_version: 8,
      profile: {
        ...PROJECTION_WIRE.profile,
        personal: { ...PROJECTION_WIRE.profile.personal, city: 'Mumbai' },
      },
    };
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(jsonResponse(mismatchedResponse))
      .mockResolvedValueOnce(jsonResponse(mismatchedResponse));
    vi.stubGlobal('fetch', fetchMock);

    await expect(updatePersonalProfile({
      expectedProfileVersion: 7,
      firstName: 'Aditi', middleName: null, lastName: 'Nair', dateOfBirth: '2002-03-14',
      preferredLanguage: 'en', city: 'Pune', pronouns: null,
    })).rejects.toEqual(expect.objectContaining({
      code: 'profile_write_uncertain',
      latestProjection: expect.objectContaining({ profileVersion: 8 }),
    }));
    expect(fetchMock).toHaveBeenCalledTimes(2);
  });

  it('surfaces a typed conflict with the authoritative current projection and never retries', async () => {
    const current = { ...PROJECTION_WIRE, profile_version: 9 };
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse({
      detail: {
        code: 'profile_version_conflict',
        current_profile_version: 9,
        current_projection: current,
      },
    }, 409));
    vi.stubGlobal('fetch', fetchMock);

    await expect(updateAcademicProfile({
      expectedProfileVersion: 7,
      college: 'NALSAR',
      yearOfStudy: '4',
      enrolmentNumber: 'TS/8/2024',
      institutionalEmail: null,
      barEnrolmentNumber: null,
    })).rejects.toEqual(expect.objectContaining<Partial<ProfileApiError>>({
      status: 409,
      code: 'profile_version_conflict',
      currentProfileVersion: 9,
    }));
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it('never auto-accepts a typed conflict even when its section matches the draft', async () => {
    const current = {
      ...PROJECTION_WIRE,
      profile_version: 9,
      institutional_email_status: 'not_provided',
      profile: {
        ...PROJECTION_WIRE.profile,
        academic: {
          college: 'NALSAR', year_of_study: '4', enrolment_number: 'TS/8/2024',
          institutional_email: null, bar_enrolment_number: null,
        },
      },
    };
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse({
      detail: {
        code: 'profile_version_conflict',
        current_profile_version: 9,
        current_projection: current,
      },
    }, 409));
    vi.stubGlobal('fetch', fetchMock);

    await expect(updateAcademicProfile({
      expectedProfileVersion: 7,
      college: 'NALSAR',
      yearOfStudy: '4',
      enrolmentNumber: 'TS/8/2024',
      institutionalEmail: null,
      barEnrolmentNumber: null,
    })).rejects.toEqual(expect.objectContaining<Partial<ProfileApiError>>({
      status: 409,
      code: 'profile_version_conflict',
      currentProfileVersion: 9,
    }));
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it('reconciles an uncertain write with one authoritative GET and never blindly retries PATCH', async () => {
    const reconciled = {
      ...PROJECTION_WIRE,
      profile_version: 8,
      institutional_email_status: 'not_provided',
      profile: {
        ...PROJECTION_WIRE.profile,
        academic: {
          college: 'NALSAR', year_of_study: '4', enrolment_number: 'TS/8/2024',
          institutional_email: null, bar_enrolment_number: null,
        },
      },
    };
    const fetchMock = vi.fn()
      .mockRejectedValueOnce(new TypeError('connection reset after send'))
      .mockResolvedValueOnce(jsonResponse(reconciled));
    vi.stubGlobal('fetch', fetchMock);

    const result = await updateAcademicProfile({
      expectedProfileVersion: 7,
      college: 'NALSAR',
      yearOfStudy: '4',
      enrolmentNumber: 'TS/8/2024',
      institutionalEmail: null,
      barEnrolmentNumber: null,
    });
    expect(result.certainty).toBe('reconciled');
    expect(result.projection.profileVersion).toBe(8);
    expect(fetchMock).toHaveBeenCalledTimes(2);
    expect((fetchMock.mock.calls[0]?.[1] as RequestInit).method).toBe('PATCH');
    expect((fetchMock.mock.calls[1]?.[1] as RequestInit).method).toBe('GET');
  });

  it('does not misattribute a later matching projection to an uncertain write', async () => {
    const laterUnrelatedWrite = {
      ...PROJECTION_WIRE,
      profile_version: 9,
      institutional_email_status: 'not_provided',
      profile: {
        ...PROJECTION_WIRE.profile,
        academic: {
          college: 'NALSAR', year_of_study: '4', enrolment_number: 'TS/8/2024',
          institutional_email: null, bar_enrolment_number: null,
        },
      },
    };
    const fetchMock = vi.fn()
      .mockRejectedValueOnce(new TypeError('connection reset before commit'))
      .mockResolvedValueOnce(jsonResponse(laterUnrelatedWrite));
    vi.stubGlobal('fetch', fetchMock);

    await expect(updateAcademicProfile({
      expectedProfileVersion: 7,
      college: 'NALSAR',
      yearOfStudy: '4',
      enrolmentNumber: 'TS/8/2024',
      institutionalEmail: null,
      barEnrolmentNumber: null,
    })).rejects.toEqual(expect.objectContaining({
      status: 0,
      code: 'profile_write_uncertain',
      latestProjection: expect.objectContaining({ profileVersion: 9 }),
    }));
    expect(fetchMock).toHaveBeenCalledTimes(2);
  });

  it('keeps navigation blocked when an uncertain write cannot be confirmed', async () => {
    const fetchMock = vi.fn()
      .mockRejectedValueOnce(new TypeError('connection reset after send'))
      .mockResolvedValueOnce(jsonResponse(PROJECTION_WIRE));
    vi.stubGlobal('fetch', fetchMock);

    await expect(updateAcademicProfile({
      expectedProfileVersion: 7,
      college: 'NALSAR',
      yearOfStudy: '4',
      enrolmentNumber: 'TS/8/2024',
      institutionalEmail: null,
      barEnrolmentNumber: null,
    })).rejects.toEqual(expect.objectContaining({
      status: 0,
      code: 'profile_write_uncertain',
      latestProjection: expect.objectContaining({ profileVersion: 7 }),
    }));
    expect(fetchMock).toHaveBeenCalledTimes(2);
  });

  it('aborts a hung write at the bounded timeout and reconciles before returning', async () => {
    vi.useFakeTimers();
    const reconciled = {
      ...PROJECTION_WIRE,
      profile_version: 8,
      profile: {
        ...PROJECTION_WIRE.profile,
        personal: { ...PROJECTION_WIRE.profile.personal, city: 'Pune' },
      },
    };
    const fetchMock = vi.fn()
      .mockImplementationOnce((_url: string, init: RequestInit) => new Promise((_resolve, reject) => {
        init.signal?.addEventListener('abort', () => reject(new DOMException('timeout', 'AbortError')));
      }))
      .mockResolvedValueOnce(jsonResponse(reconciled));
    vi.stubGlobal('fetch', fetchMock);

    const attempt = updatePersonalProfile({
      expectedProfileVersion: 7,
      firstName: 'Aditi', middleName: null, lastName: 'Nair', dateOfBirth: '2002-03-14',
      preferredLanguage: 'en', city: 'Pune', pronouns: null,
    });
    const assertion = expect(attempt).resolves.toMatchObject({ certainty: 'reconciled' });
    await vi.advanceTimersByTimeAsync(PROFILE_WRITE_TIMEOUT_MS);
    await assertion;
    expect(fetchMock).toHaveBeenCalledTimes(2);
  });

  it('reconciles a committed write whose response is HTTP 500', async () => {
    const committed = {
      ...PROJECTION_WIRE,
      profile_version: 8,
      profile: {
        ...PROJECTION_WIRE.profile,
        personal: { ...PROJECTION_WIRE.profile.personal, city: 'Pune' },
      },
    };
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(jsonResponse({ detail: { code: 'profile_unavailable' } }, 500))
      .mockResolvedValueOnce(jsonResponse(committed));
    vi.stubGlobal('fetch', fetchMock);

    await expect(updatePersonalProfile({
      expectedProfileVersion: 7,
      firstName: 'Aditi', middleName: null, lastName: 'Nair', dateOfBirth: '2002-03-14',
      preferredLanguage: 'en', city: 'Pune', pronouns: null,
    })).resolves.toMatchObject({ certainty: 'reconciled', projection: { profileVersion: 8 } });
    expect(fetchMock).toHaveBeenCalledTimes(2);
  });

  it('surfaces a noncommitted HTTP 500 as uncertain with the latest projection', async () => {
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(jsonResponse({ detail: { code: 'profile_unavailable' } }, 500))
      .mockResolvedValueOnce(jsonResponse(PROJECTION_WIRE));
    vi.stubGlobal('fetch', fetchMock);

    await expect(updatePersonalProfile({
      expectedProfileVersion: 7,
      firstName: 'Aditi', middleName: null, lastName: 'Nair', dateOfBirth: '2002-03-14',
      preferredLanguage: 'en', city: 'Pune', pronouns: null,
    })).rejects.toEqual(expect.objectContaining({
      code: 'profile_write_uncertain',
      latestProjection: expect.objectContaining({ profileVersion: 7 }),
    }));
    expect(fetchMock).toHaveBeenCalledTimes(2);
  });

  it('keeps the original write uncertain when its single reconciliation GET also fails', async () => {
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(jsonResponse({ detail: { code: 'profile_unavailable' } }, 503))
      .mockResolvedValueOnce(jsonResponse({ detail: { code: 'profile_unavailable' } }, 500));
    vi.stubGlobal('fetch', fetchMock);

    await expect(updatePersonalProfile({
      expectedProfileVersion: 7,
      firstName: 'Aditi', middleName: null, lastName: 'Nair', dateOfBirth: '2002-03-14',
      preferredLanguage: 'en', city: 'Pune', pronouns: null,
    })).rejects.toEqual(expect.objectContaining({ status: 0, code: 'profile_write_uncertain' }));
    expect(fetchMock).toHaveBeenCalledTimes(2);
  });

  it('dismisses the prompt server-side with an empty body', async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse({
      ...PROJECTION_WIRE,
      profile_prompt: { should_show: false, dismissed_for_session: true },
    }));
    vi.stubGlobal('fetch', fetchMock);
    await dismissProfilePrompt();
    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toContain('/api/v1/student/profile/prompt-dismiss');
    expect(init.method).toBe('POST');
    expect(JSON.parse(String(init.body))).toEqual({});
  });

  it('reconciles prompt dismissal after a committed-then-500 response', async () => {
    const dismissed = {
      ...PROJECTION_WIRE,
      profile_prompt: { should_show: false, dismissed_for_session: true },
    };
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(jsonResponse({ detail: { code: 'profile_unavailable' } }, 500))
      .mockResolvedValueOnce(jsonResponse(dismissed));
    vi.stubGlobal('fetch', fetchMock);

    await expect(dismissProfilePrompt()).resolves.toMatchObject({ certainty: 'reconciled' });
    expect(fetchMock).toHaveBeenCalledTimes(2);
  });

  it('surfaces prompt dismissal as uncertain when its reconciliation GET fails', async () => {
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(jsonResponse({ detail: { code: 'profile_unavailable' } }, 504))
      .mockRejectedValueOnce(new TypeError('reconciliation offline'));
    vi.stubGlobal('fetch', fetchMock);

    await expect(dismissProfilePrompt()).rejects.toEqual(expect.objectContaining({
      status: 0,
      code: 'profile_write_uncertain',
    }));
    expect(fetchMock).toHaveBeenCalledTimes(2);
  });

  it.each([
    [401, 'authentication_required', 'session ended'],
    [403, 'dob_step_up_required', 'additional identity check'],
    [422, 'invalid_profile_field', 'highlighted fields'],
    [429, 'rate_limited', 'Wait a moment'],
  ])('surfaces typed %s failures without retrying', async (status, code, copy) => {
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse({ detail: { code } }, status));
    vi.stubGlobal('fetch', fetchMock);
    const attempt = updateAcademicProfile({
      expectedProfileVersion: 7,
      college: 'NALSAR', yearOfStudy: '4', enrolmentNumber: 'TS/8/2024',
      institutionalEmail: null, barEnrolmentNumber: null,
    });
    const error = await attempt.catch((caught: unknown) => caught);
    expect(error).toEqual(expect.objectContaining({ status, code }));
    expect(profileErrorMessage(error)).toContain(copy);
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });
});

describe('institutional-email verification request', () => {
  it('requests only the saved server-owned email and returns the canonical pending projection', async () => {
    const pending = { ...PROJECTION_WIRE, institutional_email_status: 'pending' } as const;
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse(pending, 202));
    vi.stubGlobal('fetch', fetchMock);

    await expect(requestInstitutionalEmailVerification()).resolves.toEqual({
      certainty: 'confirmed',
      projection: expect.objectContaining({ institutionalEmailStatus: 'pending' }),
    });
    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toContain('/api/v1/auth/student/verification/email/request');
    expect(init.method).toBe('POST');
    expect(JSON.parse(String(init.body))).toEqual({});
    expect(JSON.stringify(init)).not.toMatch(/(?:email|registration|profile|owner)_id/iu);
  });

  it('does not mistake a pre-existing pending email for proof that an uncertain request committed', async () => {
    const pending = { ...PROJECTION_WIRE, institutional_email_status: 'pending' } as const;
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(jsonResponse({ detail: { code: 'provider_unavailable' } }, 503))
      .mockResolvedValueOnce(jsonResponse(pending));
    vi.stubGlobal('fetch', fetchMock);

    await expect(requestInstitutionalEmailVerification()).rejects.toEqual(
      expect.objectContaining({
        code: 'profile_write_uncertain',
        latestProjection: expect.objectContaining({ institutionalEmailStatus: 'pending' }),
      }),
    );
    expect(fetchMock).toHaveBeenCalledTimes(2);
    expect((fetchMock.mock.calls[1] as [string])[0]).toContain('/api/v1/student/profile');
  });
});

describe('shared Unicode legal-name corpus', () => {
  for (const testCase of legalNameCorpus.cases) {
    it(testCase.id, () => {
      const repeat = 'repeat' in testCase && typeof testCase.repeat === 'number'
        ? testCase.repeat
        : 1;
      const repeated = testCase.input.repeat(repeat);
      expect(validateLegalName(repeated)).toBe(testCase.valid);
      if (testCase.valid) {
        expect(normalizeLegalName(repeated)).toBe(
          testCase.normalized?.repeat(repeat),
        );
      }
    });
  }
});
