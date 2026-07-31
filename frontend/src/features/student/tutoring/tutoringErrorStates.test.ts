/**
 * Every typed backend refusal must become a NAMED, recoverable UI state — not a
 * generic "something went wrong". This asserts the mapping the S-31..S-35
 * screens render, for the states the frozen matrix calls out.
 */
import { describe, expect, it } from 'vitest';
import {
  ATTENDANCE_STALE_VERSION,
  ATTENDANCE_TOO_EARLY,
  GRANT_EXPIRED,
  GRANT_REVOKED,
  HOLD_CONFLICT,
  HOLD_EXPIRED,
  NOT_FOUND,
  PAYMENT_UNVERIFIED,
  PROVIDER_UNAVAILABLE,
  RATE_LIMIT_EXCEEDED,
  REFUND_NOT_ALLOWED,
  RESCHEDULE_WINDOW_CLOSED,
  REVIEW_BLOCKED,
  SESSION_STALE_VERSION,
  SLOT_UNAVAILABLE,
  TUTORING_ERROR_CODES,
  TutoringApiError,
  isRetryableTutoringError,
} from '../lib/tutoringApi';
import { typedErrorCopy } from './TutoringPrimitives';

const err = (status: number, code: string, retryable?: boolean, extra = {}): TutoringApiError =>
  new TutoringApiError(status, code, `${code} refused`, retryable, extra);

describe('every typed code the API can return has a named UI state', () => {
  it('covers the whole documented vocabulary with a specific title and detail', () => {
    for (const code of TUTORING_ERROR_CODES) {
      const copy = typedErrorCopy(err(409, code));
      expect(copy.code).toBe(code);
      expect(copy.title.length).toBeGreaterThan(8);
      expect(copy.detail.length).toBeGreaterThan(20);
      // The generic fallback wording must never be what a known code produces.
      expect(copy.title).not.toBe('The server refused this request');
    }
  });

  it('never leaks jargon, a bare status or a null into the reader-facing title', () => {
    for (const code of TUTORING_ERROR_CODES) {
      const copy = typedErrorCopy(err(409, code));
      expect(copy.title).not.toMatch(/\d{3}/);
      // "exception" survives on purpose: an audited ADMIN exception is the
      // product's own vocabulary. Engine jargon is what must never appear.
      expect(copy.title).not.toMatch(/\berror\b|stack|undefined|null|\[object/i);
      expect(copy.detail).not.toMatch(/\bundefined\b|\[object/i);
    }
  });
});

describe('hold expiry and the lost slot race read differently', () => {
  it('HOLD_EXPIRED says the slot was released and nothing was charged', () => {
    const copy = typedErrorCopy(err(409, HOLD_EXPIRED));
    expect(copy.title).toMatch(/expired/i);
    expect(copy.detail).toMatch(/nothing was charged/i);
    expect(copy.recovery).toMatch(/pick another slot/i);
    expect(copy.tone).toBe('warn');
  });

  it('HOLD_CONFLICT says someone else won, and is not retryable', () => {
    const copy = typedErrorCopy(err(409, HOLD_CONFLICT));
    expect(copy.title).toMatch(/another student/i);
    expect(copy.detail).toMatch(/exactly one hold wins/i);
    expect(copy.tone).toBe('err');
    expect(isRetryableTutoringError(err(409, HOLD_CONFLICT))).toBe(false);
  });

  it('SLOT_UNAVAILABLE is distinct from a lost race', () => {
    expect(typedErrorCopy(err(409, SLOT_UNAVAILABLE)).title)
      .not.toBe(typedErrorCopy(err(409, HOLD_CONFLICT)).title);
  });
});

describe('payment and provider failures', () => {
  it('PAYMENT_UNVERIFIED explains that a session follows a verified event only', () => {
    const copy = typedErrorCopy(err(400, PAYMENT_UNVERIFIED));
    expect(copy.detail).toMatch(/after the payment provider confirms/i);
    expect(copy.detail).toMatch(/never on a screen animation/i);
  });

  it('PROVIDER_UNAVAILABLE promises a safe retry via the same request key', () => {
    const copy = typedErrorCopy(err(503, PROVIDER_UNAVAILABLE, true));
    expect(copy.detail).toMatch(/cannot be charged twice/i);
    expect(copy.recovery).toBe('Retry');
  });

  it('an unknown 5xx still gets an honest state that names the code', () => {
    const copy = typedErrorCopy(err(500, 'SOMETHING_NEW', true));
    expect(copy.code).toBe('SOMETHING_NEW');
    expect(copy.recovery).toBe('Retry');
  });

  it('a transport failure says the request never left the device', () => {
    const copy = typedErrorCopy(new TypeError('Failed to fetch'));
    expect(copy.code).toBe('NETWORK_UNREACHABLE');
    expect(copy.detail).toMatch(/did not leave the device/i);
  });
});

describe('rate limiting', () => {
  it('RATE_LIMIT_EXCEEDED is a warning that nothing was lost', () => {
    const copy = typedErrorCopy(err(429, RATE_LIMIT_EXCEEDED, undefined, {
      limit: 60, window_seconds: 60, retry_after_seconds: 12,
    }));
    expect(copy.tone).toBe('warn');
    expect(copy.detail).toMatch(/nothing was lost/i);
  });

  it('exposes retry_after_seconds so the screen can say how long', () => {
    expect(err(429, RATE_LIMIT_EXCEEDED, undefined, { retry_after_seconds: 12 })
      .retryAfterSeconds).toBe(12);
  });
});

describe('the under-24h policy refusals', () => {
  it('RESCHEDULE_WINDOW_CLOSED offers the admin exception, not a dead end', () => {
    const copy = typedErrorCopy(err(409, RESCHEDULE_WINDOW_CLOSED, false, {
      hours_before_start: '5.50', policy_window_hours: 24,
    }));
    expect(copy.title).toMatch(/too close to the start/i);
    expect(copy.detail).toMatch(/payment is untouched/i);
    expect(copy.recovery).toMatch(/admin exception/i);
  });

  it('REFUND_NOT_ALLOWED says the session is unchanged until you confirm', () => {
    const copy = typedErrorCopy(err(409, REFUND_NOT_ALLOWED));
    expect(copy.detail).toMatch(/unchanged/i);
    expect(copy.recovery).toMatch(/admin exception/i);
  });

  it('a stale session refuses rather than overwriting a newer change', () => {
    for (const code of [SESSION_STALE_VERSION, ATTENDANCE_STALE_VERSION]) {
      const copy = typedErrorCopy(err(409, code));
      expect(copy.detail).toMatch(/overwriting|overwrite/i);
      expect(copy.recovery).toMatch(/reload/i);
    }
  });
});

describe('review gating and attendance', () => {
  it('REVIEW_BLOCKED names attendance as the gate and keeps the text', () => {
    const copy = typedErrorCopy(err(409, REVIEW_BLOCKED, false, { attendance_state: 'disputed' }));
    expect(copy.title).toMatch(/locked until attendance is confirmed/i);
    expect(copy.detail).toMatch(/absent or disputed/i);
    expect(copy.detail).toMatch(/not lost/i);
    expect(copy.recovery).toMatch(/attendance/i);
  });

  it('ATTENDANCE_TOO_EARLY says nothing was recorded', () => {
    expect(typedErrorCopy(err(409, ATTENDANCE_TOO_EARLY)).detail).toMatch(/nothing was recorded/i);
  });
});

describe('unauthorised or stale join-credential requests', () => {
  it('a refused credential request is non-enumerating', () => {
    const copy = typedErrorCopy(err(404, NOT_FOUND));
    expect(copy.detail).toMatch(/does not exist, or it is not yours/i);
  });

  it('GRANT_EXPIRED asks for a fresh credential, not a retry of the old one', () => {
    const copy = typedErrorCopy(err(410, GRANT_EXPIRED));
    expect(copy.detail).toMatch(/short lived/i);
    expect(copy.recovery).toMatch(/fresh join credential/i);
  });

  it('GRANT_REVOKED explains that issuing a new credential kills the old one', () => {
    const copy = typedErrorCopy(err(410, GRANT_REVOKED));
    expect(copy.detail).toMatch(/revokes the previous one/i);
  });

  it('no credential copy quotes a token, an SDP or an ICE candidate', () => {
    for (const code of [GRANT_EXPIRED, GRANT_REVOKED, NOT_FOUND]) {
      const copy = typedErrorCopy(err(410, code));
      expect(`${copy.title} ${copy.detail}`).not.toMatch(/candidate:|v=0|tok_/);
    }
  });
});
