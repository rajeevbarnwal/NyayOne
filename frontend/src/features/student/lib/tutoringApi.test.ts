import { afterEach, describe, expect, it, vi } from 'vitest';
import {
  ATTENDANCE_TOO_EARLY,
  ForbiddenPaymentFieldError,
  HOLD_CONFLICT,
  HOLD_EXPIRED,
  PAYMENT_TOKEN_PATTERN,
  PAYMENT_UNVERIFIED,
  PROVIDER_UNAVAILABLE,
  RATE_LIMIT_EXCEEDED,
  RESCHEDULE_WINDOW_CLOSED,
  REVIEW_BLOCKED,
  SESSION_STALE_VERSION,
  TutoringApiError,
  VALIDATION_ERROR,
  buildTutorSearchQuery,
  cancelSession,
  confirmAttendance,
  createBookingHold,
  createPaymentOrder,
  createReview,
  createTutoringSession,
  disputeAttendance,
  editReview,
  getAvailability,
  getBookingHold,
  getTutoringCapabilities,
  getTutor,
  getTutoringSession,
  isRetryableTutoringError,
  issueJoinCredentials,
  listTutoringSessions,
  newIdempotencyKey,
  redactJoinCredential,
  rescheduleSession,
  searchTutors,
  tutoringKeys,
  tutoringRetry,
} from './tutoringApi';

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  });
}

/** A typed refusal in the frozen P3 envelope. */
function typedError(status: number, code: string, extra: Record<string, unknown> = {}): Response {
  return jsonResponse(
    { detail: { code, message: `${code} refused`, retryable: false, ...extra } },
    status,
  );
}

function stubFetch(...responses: Response[]): ReturnType<typeof vi.fn> {
  const mock = vi.fn();
  for (const response of responses) mock.mockResolvedValueOnce(response);
  vi.stubGlobal('fetch', mock);
  return mock;
}

const TUTOR_WIRE = {
  id: '11111111-1111-4111-8111-111111111111',
  display_name: 'Adv. Meera Krishnan',
  headline: 'Arbitration counsel and clause-drafting mentor',
  experience_years: 11,
  rating_avg: '4.80',
  rating_count: 126,
  verified_identity: true,
  verified_credentials: true,
  status: 'published',
};

const SLOT_WIRE = {
  slot_id: '22222222-2222-4222-8222-222222222222',
  tutor_id: TUTOR_WIRE.id,
  start_utc: '2026-08-05T13:00:00+00:00',
  end_utc: '2026-08-05T13:45:00+00:00',
  iana_timezone: 'Asia/Kolkata',
  status: 'available',
  start_local: '2026-08-05T18:30:00+05:30',
  end_local: '2026-08-05T19:15:00+05:30',
  duration_minutes: 45,
};

const SESSION_WIRE = {
  id: '33333333-3333-4333-8333-333333333333',
  slot_id: SLOT_WIRE.slot_id,
  tutor_id: TUTOR_WIRE.id,
  student_user_id: '44444444-4444-4444-8444-444444444444',
  order_id: '55555555-5555-4555-8555-555555555555',
  status: 'scheduled',
  version: 3,
  start_utc: SLOT_WIRE.start_utc,
  end_utc: SLOT_WIRE.end_utc,
  iana_timezone: 'Asia/Kolkata',
  start_local: SLOT_WIRE.start_local,
  end_local: SLOT_WIRE.end_local,
  attendance_state: 'marked',
  attendance_version: 2,
};

/* ========================================================================== *
 * A1/A2/A3 — discovery
 * ========================================================================== */

describe('A1 tutor search', () => {
  it('builds the documented snake_case query string with sort and paging', () => {
    const parsed = new URLSearchParams(buildTutorSearchQuery({
      q: 'arbitration',
      subject: 'Arbitration',
      level: 'llb',
      minRating: 4.5,
      minExperienceYears: 5,
      verifiedOnly: true,
      sort: 'experience_desc',
      limit: 10,
      offset: 20,
    }));
    expect(parsed.get('q')).toBe('arbitration');
    expect(parsed.get('min_rating')).toBe('4.5');
    expect(parsed.get('min_experience_years')).toBe('5');
    expect(parsed.get('verified_only')).toBe('true');
    expect(parsed.get('sort')).toBe('experience_desc');
    expect(parsed.get('limit')).toBe('10');
    expect(parsed.get('offset')).toBe('20');
  });

  it('omits verified_only when it is not requested and defaults sort/paging', () => {
    const parsed = new URLSearchParams(buildTutorSearchQuery({}));
    expect(parsed.has('verified_only')).toBe(false);
    expect(parsed.get('sort')).toBe('rating_desc');
    expect(parsed.get('limit')).toBe('20');
    expect(parsed.get('offset')).toBe('0');
  });

  it('maps the page, keeps rating_avg a string and echoes allowed_sorts', async () => {
    const mock = stubFetch(jsonResponse({
      items: [TUTOR_WIRE],
      total: 4,
      limit: 20,
      offset: 0,
      has_more: true,
      sort: 'rating_desc',
      allowed_sorts: ['rating_desc', 'name_asc'],
    }));
    const result = await searchTutors({ q: 'arbitration' });
    expect(result.total).toBe(4);
    expect(result.hasMore).toBe(true);
    expect(result.allowedSorts).toEqual(['rating_desc', 'name_asc']);
    expect(result.items[0]).toEqual(expect.objectContaining({
      id: TUTOR_WIRE.id,
      displayName: 'Adv. Meera Krishnan',
      experienceYears: 11,
      // A string, so the client never re-averages a rating in floating point.
      ratingAvg: '4.80',
      verifiedCredentials: true,
    }));
    const [url, init] = mock.mock.calls[0] as [string, RequestInit];
    expect(url).toContain('/api/v1/tutors?');
    expect(new Headers(init.headers).get('X-Actor-Claims')).toBeTruthy();
  });

  it('maps a 422 unknown-sort refusal to the typed code', async () => {
    stubFetch(typedError(422, VALIDATION_ERROR, { field: 'sort' }));
    await expect(searchTutors({ q: 'x' })).rejects.toMatchObject({
      status: 422,
      code: VALIDATION_ERROR,
      field: 'sort',
    });
  });

  it('maps the 429 limiter envelope with its retry hint', async () => {
    stubFetch(jsonResponse({
      detail: {
        code: RATE_LIMIT_EXCEEDED,
        message: 'Too many requests',
        limit: 60,
        window_seconds: 60,
        retry_after_seconds: 17,
      },
    }, 429));
    try {
      await searchTutors();
      expect.unreachable('a 429 must reject');
    } catch (error) {
      const typed = error as TutoringApiError;
      expect(typed.status).toBe(429);
      expect(typed.code).toBe(RATE_LIMIT_EXCEEDED);
      expect(typed.retryAfterSeconds).toBe(17);
      expect(typed.extra.limit).toBe(60);
    }
  });
});

describe('A2 tutor detail carries provenance and the published aggregate', () => {
  it('maps source, source_url, retrieved_at, subjects and the distribution', async () => {
    stubFetch(jsonResponse({
      ...TUTOR_WIRE,
      source: 'bar_council_register',
      source_url: 'https://example.org/register/1',
      retrieved_at: '2026-07-01T00:00:00+00:00',
      subjects: [{ subject: 'Arbitration', level: 'llb' }],
      rating_aggregate: {
        tutor_id: TUTOR_WIRE.id,
        rating_count: 126,
        rating_avg: '4.80',
        distribution: { '4': 26, '5': 100 },
      },
    }));
    const detail = await getTutor(TUTOR_WIRE.id);
    expect(detail.source).toBe('bar_council_register');
    expect(detail.sourceUrl).toBe('https://example.org/register/1');
    expect(detail.retrievedAt).toBe('2026-07-01T00:00:00+00:00');
    expect(detail.subjects).toEqual([{ subject: 'Arbitration', level: 'llb' }]);
    expect(detail.ratingAggregate.distribution['5']).toBe(100);
  });

  it('maps the non-enumerating 404 to NOT_FOUND without inventing a 403', async () => {
    stubFetch(typedError(404, 'NOT_FOUND'));
    await expect(getTutor('nope')).rejects.toMatchObject({ status: 404, code: 'NOT_FOUND' });
  });
});

describe('A3 availability surfaces the timezone and the DST verdict', () => {
  it('maps slots and reports an ambiguous local resolution', async () => {
    const mock = stubFetch(jsonResponse({
      tutor_id: TUTOR_WIRE.id,
      iana_timezone: 'Europe/London',
      window: { from_utc: SLOT_WIRE.start_utc, to_utc: null },
      local_resolution: {
        from_local: {
          requested_local: '2026-10-25T01:30:00',
          resolved_local: '2026-10-25T01:30:00',
          instant_utc: '2026-10-25T00:30:00+00:00',
          classification: 'ambiguous',
          dst_adjusted: false,
        },
      },
      slots: [SLOT_WIRE],
      limit: 50,
      offset: 0,
    }));
    const result = await getAvailability(TUTOR_WIRE.id, {
      timezone: 'Europe/London',
      fromLocal: '2026-10-25T01:30:00',
    });
    expect(result.ianaTimezone).toBe('Europe/London');
    expect(result.localResolution.from_local?.classification).toBe('ambiguous');
    expect(result.slots[0]).toEqual(expect.objectContaining({
      slotId: SLOT_WIRE.slot_id,
      ianaTimezone: 'Asia/Kolkata',
      status: 'available',
      durationMinutes: 45,
    }));
    const [url] = mock.mock.calls[0] as [string];
    expect(url).toContain('timezone=Europe%2FLondon');
    expect(url).toContain('from_local=2026-10-25T01%3A30%3A00');
  });

  it('maps an unknown IANA name to the typed 422', async () => {
    stubFetch(typedError(422, VALIDATION_ERROR, { field: 'timezone' }));
    await expect(getAvailability(TUTOR_WIRE.id, { timezone: 'Mars/Olympus' }))
      .rejects.toMatchObject({ code: VALIDATION_ERROR, field: 'timezone' });
  });
});

/* ========================================================================== *
 * B1 — holds, including the lost race
 * ========================================================================== */

describe('B1 booking holds', () => {
  const HOLD_WIRE = {
    id: '66666666-6666-4666-8666-666666666666',
    slot_id: SLOT_WIRE.slot_id,
    status: 'active',
    expires_at: '2026-08-05T12:10:00+00:00',
    hold_minutes: 10,
    replayed: false,
  };

  it('sends slot_id plus the idempotency key in body AND header', async () => {
    const mock = stubFetch(jsonResponse(HOLD_WIRE, 201));
    const hold = await createBookingHold({ slotId: SLOT_WIRE.slot_id, idempotencyKey: 'k-1' });
    expect(hold).toEqual(expect.objectContaining({
      id: HOLD_WIRE.id,
      slotId: SLOT_WIRE.slot_id,
      holdMinutes: 10,
      replayed: false,
      expiresAt: '2026-08-05T12:10:00+00:00',
    }));
    const [url, init] = mock.mock.calls[0] as [string, RequestInit];
    expect(url).toContain('/api/v1/tutoring/booking-holds');
    expect(JSON.parse(String(init.body))).toEqual({
      slot_id: SLOT_WIRE.slot_id,
      idempotency_key: 'k-1',
    });
    expect(new Headers(init.headers).get('Idempotency-Key')).toBe('k-1');
  });

  it('reports a replayed hold so a repeat submit is not a second booking', async () => {
    stubFetch(jsonResponse({ ...HOLD_WIRE, replayed: true }, 200));
    const hold = await createBookingHold({ slotId: SLOT_WIRE.slot_id, idempotencyKey: 'k-1' });
    expect(hold.replayed).toBe(true);
  });

  it('maps HOLD_CONFLICT — someone else won the slot race — and does not retry it', async () => {
    stubFetch(typedError(409, HOLD_CONFLICT, { slot_id: SLOT_WIRE.slot_id }));
    try {
      await createBookingHold({ slotId: SLOT_WIRE.slot_id, idempotencyKey: 'k-2' });
      expect.unreachable('a lost race must reject');
    } catch (error) {
      const typed = error as TutoringApiError;
      expect(typed.status).toBe(409);
      expect(typed.code).toBe(HOLD_CONFLICT);
      expect(typed.extra.slot_id).toBe(SLOT_WIRE.slot_id);
      expect(isRetryableTutoringError(typed)).toBe(false);
    }
  });

  it('maps SLOT_UNAVAILABLE for a slot that is gone', async () => {
    stubFetch(typedError(409, 'SLOT_UNAVAILABLE'));
    await expect(createBookingHold({ slotId: 's', idempotencyKey: 'k' }))
      .rejects.toMatchObject({ code: 'SLOT_UNAVAILABLE', status: 409 });
  });

  it('reads the server verdict on expiry rather than trusting the local clock', async () => {
    stubFetch(jsonResponse({ ...HOLD_WIRE, status: 'expired', expired: true }));
    const hold = await getBookingHold(HOLD_WIRE.id);
    expect(hold.expired).toBe(true);
    expect(hold.status).toBe('expired');
  });
});

/* ========================================================================== *
 * C1/C3 — payment order and session creation
 * ========================================================================== */

describe('C1 tokenised payment order', () => {
  const ORDER_WIRE = {
    id: '77777777-7777-4777-8777-777777777777',
    hold_id: '66666666-6666-4666-8666-666666666666',
    provider: 'deterministic',
    provider_order_ref: 'ord_TEST_1',
    amount_paise: 96082,
    currency: 'INR',
    status: 'created',
    brand: 'Visa',
    masked_last4: '1111',
    replayed: false,
  };

  it('sends integer paise, INR and the idempotency key', async () => {
    const mock = stubFetch(jsonResponse(ORDER_WIRE, 201));
    const order = await createPaymentOrder({
      holdId: ORDER_WIRE.hold_id,
      amountPaise: 96082,
      idempotencyKey: 'ord-1',
    });
    expect(order.amountPaise).toBe(96082);
    expect(order.maskedLast4).toBe('1111');
    const body = JSON.parse(String((mock.mock.calls[0] as [string, RequestInit])[1].body));
    expect(body).toEqual({
      hold_id: ORDER_WIRE.hold_id,
      amount_paise: 96082,
      idempotency_key: 'ord-1',
      currency: 'INR',
    });
    expect('payment_token' in body).toBe(false);
  });

  it('accepts a provider token only in the frozen tok_ shape', () => {
    expect(PAYMENT_TOKEN_PATTERN.test('tok_abc123')).toBe(true);
    expect(PAYMENT_TOKEN_PATTERN.test('4111111111111111')).toBe(false);
    expect(PAYMENT_TOKEN_PATTERN.test('tok_')).toBe(false);
  });

  it('refuses a PAN in the token field BEFORE any request leaves the device', async () => {
    const mock = stubFetch(jsonResponse(ORDER_WIRE, 201));
    await expect(createPaymentOrder({
      holdId: ORDER_WIRE.hold_id,
      amountPaise: 96082,
      idempotencyKey: 'ord-2',
      paymentToken: '4111111111111111',
    })).rejects.toBeInstanceOf(ForbiddenPaymentFieldError);
    expect(mock).not.toHaveBeenCalled();
  });

  it('refuses a non-integer amount before any request leaves the device', async () => {
    const mock = stubFetch(jsonResponse(ORDER_WIRE, 201));
    await expect(createPaymentOrder({
      holdId: ORDER_WIRE.hold_id,
      amountPaise: 960.82,
      idempotencyKey: 'ord-3',
    })).rejects.toBeInstanceOf(ForbiddenPaymentFieldError);
    expect(mock).not.toHaveBeenCalled();
  });

  it('maps HOLD_EXPIRED on paying against a dead hold', async () => {
    stubFetch(typedError(409, HOLD_EXPIRED));
    await expect(createPaymentOrder({ holdId: 'h', amountPaise: 1, idempotencyKey: 'k' }))
      .rejects.toMatchObject({ code: HOLD_EXPIRED, status: 409 });
  });

  it('maps PROVIDER_UNAVAILABLE and honours its retryable flag', async () => {
    stubFetch(jsonResponse({
      detail: {
        code: PROVIDER_UNAVAILABLE,
        message: 'provider rejected the order',
        retryable: true,
        provider_code: 'gateway_timeout',
      },
    }, 503));
    try {
      await createPaymentOrder({ holdId: 'h', amountPaise: 1, idempotencyKey: 'k' });
      expect.unreachable('503 must reject');
    } catch (error) {
      const typed = error as TutoringApiError;
      expect(typed.code).toBe(PROVIDER_UNAVAILABLE);
      expect(typed.retryable).toBe(true);
      expect(isRetryableTutoringError(typed)).toBe(true);
    }
  });

  it('maps a FastAPI request-shape rejection (extra="forbid") without echoing a value', async () => {
    // This is the shape a submitted `cvv` field would produce.
    stubFetch(jsonResponse({
      detail: [{ loc: ['body', 'cvv'], msg: 'Extra inputs are not permitted', type: 'extra_forbidden' }],
    }, 422));
    try {
      await createPaymentOrder({ holdId: 'h', amountPaise: 1, idempotencyKey: 'k' });
      expect.unreachable('422 must reject');
    } catch (error) {
      const typed = error as TutoringApiError;
      expect(typed.code).toBe(VALIDATION_ERROR);
      expect(typed.field).toBe('cvv');
      expect(JSON.stringify(typed.extra)).not.toContain('4111');
    }
  });
});

describe('C3 session creation', () => {
  it('maps a replayed session with its reminder count', async () => {
    stubFetch(jsonResponse({ ...SESSION_WIRE, replayed: true, reminder_jobs: 3 }, 200));
    const created = await createTutoringSession('66666666-6666-4666-8666-666666666666');
    expect(created.replayed).toBe(true);
    expect(created.reminderJobs).toBe(3);
    expect(created.ianaTimezone).toBe('Asia/Kolkata');
    expect(created.version).toBe(3);
  });

  it('maps PAYMENT_UNVERIFIED for an unpaid hold', async () => {
    stubFetch(typedError(400, PAYMENT_UNVERIFIED, { hold_id: 'h' }));
    await expect(createTutoringSession('h'))
      .rejects.toMatchObject({ code: PAYMENT_UNVERIFIED, status: 400 });
  });
});

/* ========================================================================== *
 * D1..D5 — sessions, reschedule, cancel, attendance
 * ========================================================================== */

describe('D1 session reads', () => {
  it('maps a list scoped to the caller, repeating status as the API expects', async () => {
    const mock = stubFetch(jsonResponse({
      items: [SESSION_WIRE], role: 'student', limit: 50, offset: 0,
    }));
    const result = await listTutoringSessions({ status: ['scheduled', 'completed'] });
    expect(result.role).toBe('student');
    expect(result.items[0].attendanceState).toBe('marked');
    const [url] = mock.mock.calls[0] as [string];
    expect(url).toContain('status=scheduled');
    expect(url).toContain('status=completed');
  });

  it('maps cross-user isolation as NOT_FOUND', async () => {
    stubFetch(typedError(404, 'NOT_FOUND'));
    await expect(getTutoringSession('other')).rejects.toMatchObject({ status: 404 });
  });
});

describe('D2 reschedule', () => {
  it('sends the new slot with expected_version and maps reminders_revoked', async () => {
    const mock = stubFetch(jsonResponse({ ...SESSION_WIRE, reminders_revoked: 2 }));
    const result = await rescheduleSession({
      sessionId: SESSION_WIRE.id,
      newSlotId: 'new-slot',
      expectedVersion: 3,
    });
    expect(result.remindersRevoked).toBe(2);
    const body = JSON.parse(String((mock.mock.calls[0] as [string, RequestInit])[1].body));
    expect(body).toEqual({ new_slot_id: 'new-slot', expected_version: 3 });
  });

  it('maps RESCHEDULE_WINDOW_CLOSED with the policy window it applied', async () => {
    stubFetch(typedError(409, RESCHEDULE_WINDOW_CLOSED, {
      hours_before_start: '5.50',
      policy_window_hours: 24,
    }));
    try {
      await rescheduleSession({ sessionId: 's', newSlotId: 'n' });
      expect.unreachable('inside the window must reject');
    } catch (error) {
      const typed = error as TutoringApiError;
      expect(typed.code).toBe(RESCHEDULE_WINDOW_CLOSED);
      expect(typed.policyWindowHours).toBe(24);
      expect(typed.extra.hours_before_start).toBe('5.50');
      expect(isRetryableTutoringError(typed)).toBe(false);
    }
  });
});

describe('D3 cancel and the refund verdict', () => {
  it('maps the full-refund verdict, keeping the amount an integer', async () => {
    stubFetch(jsonResponse({
      ...SESSION_WIRE,
      status: 'cancelled',
      refund: {
        decision: 'full_refund',
        amount_paise: 96082,
        reason: 'cancel_ge_24h',
        hours_before_start: '24.00',
        policy_window_hours: 24,
      },
      refund_id: '88888888-8888-4888-8888-888888888888',
      reminders_revoked: 3,
    }));
    const result = await cancelSession({ sessionId: SESSION_WIRE.id, expectedVersion: 3 });
    expect(result.refund).toEqual({
      decision: 'full_refund',
      amountPaise: 96082,
      reason: 'cancel_ge_24h',
      hoursBeforeStart: '24.00',
      policyWindowHours: 24,
    });
    expect(Number.isInteger(result.refund?.amountPaise)).toBe(true);
    expect(result.refundId).toBe('88888888-8888-4888-8888-888888888888');
  });

  it('maps the inside-window verdict as no refund due', async () => {
    stubFetch(jsonResponse({
      ...SESSION_WIRE,
      status: 'cancelled',
      refund: {
        decision: 'no_auto_refund',
        amount_paise: 0,
        reason: null,
        hours_before_start: '5.50',
        policy_window_hours: 24,
      },
      refund_id: null,
      reminders_revoked: 1,
    }));
    const result = await cancelSession({ sessionId: SESSION_WIRE.id });
    expect(result.refund?.decision).toBe('no_auto_refund');
    expect(result.refund?.amountPaise).toBe(0);
    expect(result.refundId).toBeNull();
  });

  it('maps SESSION_STALE_VERSION so a stale page cannot overwrite a newer change', async () => {
    stubFetch(typedError(409, SESSION_STALE_VERSION, { expected: 3, actual: 4 }));
    await expect(cancelSession({ sessionId: 's', expectedVersion: 3 }))
      .rejects.toMatchObject({ code: SESSION_STALE_VERSION, status: 409 });
  });
});

describe('D5 attendance', () => {
  const ATTENDANCE_WIRE = {
    session_id: SESSION_WIRE.id,
    state: 'confirmed',
    version: 3,
    recorded_by_role: 'tutor',
    recorded_at: '2026-08-05T14:00:00+00:00',
    confirmed_at: '2026-08-05T14:10:00+00:00',
    disputed_at: null,
    resolved_at: null,
    resolution: null,
    session_status: 'completed',
  };

  it('maps a confirmation with its version', async () => {
    const mock = stubFetch(jsonResponse(ATTENDANCE_WIRE));
    const record = await confirmAttendance({ sessionId: SESSION_WIRE.id, expectedVersion: 2 });
    expect(record).toEqual(expect.objectContaining({
      state: 'confirmed', version: 3, recordedByRole: 'tutor', sessionStatus: 'completed',
    }));
    const body = JSON.parse(String((mock.mock.calls[0] as [string, RequestInit])[1].body));
    expect(body).toEqual({ expected_version: 2 });
  });

  it('sends a dispute reason CODE, never a narrative', async () => {
    const mock = stubFetch(jsonResponse({ ...ATTENDANCE_WIRE, state: 'disputed' }));
    await disputeAttendance({
      sessionId: SESSION_WIRE.id, expectedVersion: 2, reasonCode: 'tutor_absent',
    });
    const body = JSON.parse(String((mock.mock.calls[0] as [string, RequestInit])[1].body));
    expect(body).toEqual({ expected_version: 2, reason_code: 'tutor_absent' });
    expect(String(body.reason_code)).toMatch(/^[a-z0-9_]+$/);
  });

  it('maps ATTENDANCE_TOO_EARLY before the scheduled end', async () => {
    stubFetch(typedError(409, ATTENDANCE_TOO_EARLY));
    await expect(confirmAttendance({ sessionId: 's' }))
      .rejects.toMatchObject({ code: ATTENDANCE_TOO_EARLY, status: 409 });
  });
});

/* ========================================================================== *
 * E1 — join credentials
 * ========================================================================== */

describe('E1 join credentials', () => {
  const CREDENTIAL_WIRE = {
    session_id: SESSION_WIRE.id,
    grant_id: '99999999-9999-4999-8999-999999999999',
    room_ref: 'room_TEST_1',
    participant_ref: 'part_TEST_1',
    permissions: ['publish', 'subscribe'],
    join_token: 'jointoken-TEST-do-not-log',
    issued_at: '2026-08-05T13:00:00+00:00',
    expires_at: '2026-08-05T13:05:00+00:00',
    ttl_seconds: 300,
    superseded: true,
    video_room_url: 'wss://video.example.test',
    video_ice_transport_policy: 'relay',
  };

  it('maps the one-time credential, including that it superseded the previous grant', async () => {
    stubFetch(jsonResponse(CREDENTIAL_WIRE, 201));
    const issued = await issueJoinCredentials(SESSION_WIRE.id);
    expect(issued.roomRef).toBe('room_TEST_1');
    expect(issued.ttlSeconds).toBe(300);
    expect(issued.superseded).toBe(true);
    expect(issued.joinToken).toBe('jointoken-TEST-do-not-log');
    expect(issued.videoRoomUrl).toBe('wss://video.example.test');
    expect(issued.videoIceTransportPolicy).toBe('relay');
  });

  it('redacts the raw token for any rendered or logged projection', async () => {
    stubFetch(jsonResponse(CREDENTIAL_WIRE, 201));
    const redacted = redactJoinCredential(await issueJoinCredentials(SESSION_WIRE.id));
    expect(redacted.joinToken).toBe('[redacted]');
    expect(JSON.stringify(redacted)).not.toContain('jointoken-TEST-do-not-log');
    // Everything a screen legitimately needs survives the redaction.
    expect(redacted.roomRef).toBe('room_TEST_1');
    expect(redacted.participantRef).toBe('part_TEST_1');
  });

  it('maps an unauthorised credential request without leaking why', async () => {
    stubFetch(typedError(404, 'NOT_FOUND'));
    await expect(issueJoinCredentials('someone-elses-session'))
      .rejects.toMatchObject({ status: 404, code: 'NOT_FOUND' });
  });

  it('maps GRANT_EXPIRED and GRANT_REVOKED as non-retryable 410s', async () => {
    for (const code of ['GRANT_EXPIRED', 'GRANT_REVOKED']) {
      stubFetch(typedError(410, code));
      try {
        await issueJoinCredentials(SESSION_WIRE.id);
        expect.unreachable('410 must reject');
      } catch (error) {
        expect((error as TutoringApiError).code).toBe(code);
        expect(isRetryableTutoringError(error)).toBe(false);
      }
      vi.unstubAllGlobals();
    }
  });
});

describe('runtime tutoring capabilities', () => {
  it('maps the independent video switch and browser endpoint', async () => {
    stubFetch(jsonResponse({
      video_calls_enabled: true,
      video_transport: 'livekit',
      video_room_url: 'wss://video.example.test',
      video_ice_transport_policy: 'relay',
      join_credential_ttl_seconds: 300,
      recording_enabled: false,
    }));
    await expect(getTutoringCapabilities()).resolves.toEqual({
      videoCallsEnabled: true,
      videoTransport: 'livekit',
      videoRoomUrl: 'wss://video.example.test',
      videoIceTransportPolicy: 'relay',
      joinCredentialTtlSeconds: 300,
      recordingEnabled: false,
    });
  });

  it('maps the disabled state without inventing a provider URL', async () => {
    stubFetch(jsonResponse({
      video_calls_enabled: false,
      video_transport: 'none',
      video_room_url: null,
      video_ice_transport_policy: 'all',
      join_credential_ttl_seconds: 300,
      recording_enabled: false,
    }));
    const result = await getTutoringCapabilities();
    expect(result.videoCallsEnabled).toBe(false);
    expect(result.videoTransport).toBe('none');
    expect(result.videoRoomUrl).toBeNull();
    expect(result.videoIceTransportPolicy).toBe('all');
  });
});

/* ========================================================================== *
 * F1/F2 — reviews
 * ========================================================================== */

describe('F1/F2 reviews', () => {
  const REVIEW_WIRE = {
    id: 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa',
    session_id: SESSION_WIRE.id,
    tutor_id: TUTOR_WIRE.id,
    rating: 5,
    body: 'The clause drill was exactly what I needed.',
    published: false,
    edit_deadline_at: '2026-08-12T14:00:00+00:00',
    deleted: false,
    moderation_state: 'pending',
    rating_aggregate: {
      tutor_id: TUTOR_WIRE.id, rating_count: 126, rating_avg: '4.80', distribution: { '5': 100 },
    },
  };

  it('maps a created review, its moderation state and the aggregate', async () => {
    const mock = stubFetch(jsonResponse(REVIEW_WIRE, 201));
    const review = await createReview({
      sessionId: SESSION_WIRE.id, rating: 5, body: REVIEW_WIRE.body,
    });
    expect(review.published).toBe(false);
    expect(review.moderationState).toBe('pending');
    expect(review.ratingAggregate?.ratingCount).toBe(126);
    const body = JSON.parse(String((mock.mock.calls[0] as [string, RequestInit])[1].body));
    expect(body).toEqual({ rating: 5, body: REVIEW_WIRE.body });
  });

  it('omits body entirely when the caller did not pass it', async () => {
    const mock = stubFetch(jsonResponse(REVIEW_WIRE, 201));
    await createReview({ sessionId: SESSION_WIRE.id, rating: 4 });
    const body = JSON.parse(String((mock.mock.calls[0] as [string, RequestInit])[1].body));
    expect(body).toEqual({ rating: 4 });
    expect('body' in body).toBe(false);
  });

  it('distinguishes "leave the text alone" from "remove the text" on edit', async () => {
    const mock = stubFetch(jsonResponse(REVIEW_WIRE), jsonResponse(REVIEW_WIRE));
    await editReview({ reviewId: REVIEW_WIRE.id, rating: 5 });
    expect(JSON.parse(String((mock.mock.calls[0] as [string, RequestInit])[1].body)))
      .toEqual({ rating: 5 });
    await editReview({ reviewId: REVIEW_WIRE.id, body: null });
    expect(JSON.parse(String((mock.mock.calls[1] as [string, RequestInit])[1].body)))
      .toEqual({ body: null });
  });

  it('maps REVIEW_BLOCKED while attendance is absent or disputed', async () => {
    stubFetch(typedError(409, REVIEW_BLOCKED, { attendance_state: 'disputed' }));
    try {
      await createReview({ sessionId: SESSION_WIRE.id, rating: 5 });
      expect.unreachable('a blocked review must reject');
    } catch (error) {
      const typed = error as TutoringApiError;
      expect(typed.code).toBe(REVIEW_BLOCKED);
      expect(typed.extra.attendance_state).toBe('disputed');
      expect(isRetryableTutoringError(typed)).toBe(false);
    }
  });

  it('maps the server rating/text refusal as VALIDATION_ERROR with its field', async () => {
    stubFetch(typedError(422, VALIDATION_ERROR, { field: 'body', length: 9 }));
    await expect(createReview({ sessionId: 's', rating: 5, body: 'too short' }))
      .rejects.toMatchObject({ code: VALIDATION_ERROR, field: 'body' });
  });
});

/* ========================================================================== *
 * Retry predicate
 * ========================================================================== */

describe('retry predicate: 4xx never, 5xx and transport failures once', () => {
  const err = (status: number, code = 'X', retryable?: boolean): TutoringApiError =>
    new TutoringApiError(status, code, 'm', retryable);

  it('never retries a deterministic 4xx verdict', () => {
    for (const status of [400, 401, 403, 404, 409, 410, 422, 429, 499]) {
      expect(isRetryableTutoringError(err(status))).toBe(false);
    }
  });

  it('retries a 5xx and a transport failure', () => {
    expect(isRetryableTutoringError(err(500))).toBe(true);
    expect(isRetryableTutoringError(err(502))).toBe(true);
    expect(isRetryableTutoringError(err(503, PROVIDER_UNAVAILABLE, true))).toBe(true);
    expect(isRetryableTutoringError(new TypeError('Failed to fetch'))).toBe(true);
    expect(isRetryableTutoringError(undefined)).toBe(true);
  });

  it('honours an explicit retryable:false on a 5xx over the status', () => {
    expect(isRetryableTutoringError(err(503, PROVIDER_UNAVAILABLE, false))).toBe(false);
  });

  it('caps React Query at a single retry and never retries a 4xx', () => {
    expect(tutoringRetry(0, err(500))).toBe(true);
    expect(tutoringRetry(1, err(500))).toBe(false);
    expect(tutoringRetry(0, err(409, HOLD_CONFLICT))).toBe(false);
    expect(tutoringRetry(0, err(429, RATE_LIMIT_EXCEEDED))).toBe(false);
  });
});

/* ========================================================================== *
 * Transport details
 * ========================================================================== */

describe('transport', () => {
  it('falls back to an http_<status> code when the body is not an envelope', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(
      new Response('<html>gateway</html>', { status: 502 }),
    ));
    await expect(getTutor('x')).rejects.toMatchObject({ status: 502, code: 'http_502' });
  });

  it('propagates a transport failure unchanged so it stays retryable', async () => {
    vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new TypeError('Failed to fetch')));
    await expect(getTutor('x')).rejects.toBeInstanceOf(TypeError);
  });

  it('mints distinct idempotency keys per attempt', () => {
    expect(newIdempotencyKey('hold')).not.toBe(newIdempotencyKey('hold'));
    expect(newIdempotencyKey('hold').startsWith('hold-')).toBe(true);
  });

  it('never puts a secret in a query key', () => {
    const keys = [
      tutoringKeys.tutors({ q: 'x' }),
      tutoringKeys.tutor('t'),
      tutoringKeys.availability('t', {}),
      tutoringKeys.hold('h'),
      tutoringKeys.sessions({}),
      tutoringKeys.session('s'),
    ];
    const serialised = JSON.stringify(keys);
    expect(serialised).not.toMatch(/token|pan|cvv|otp|sdp|candidate/i);
    for (const key of keys) expect(key[0]).toBe('tutoring');
  });
});
