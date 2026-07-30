import { describe, expect, it } from 'vitest';
import {
  DEFAULT_REFUND_FREE_CANCEL_HOURS,
  HOLD_URGENT_AT_SECONDS,
  MoneyNotIntegerPaiseError,
  REVIEW_MAX_BODY,
  REVIEW_MIN_BODY,
  durationMinutes,
  formatPaise,
  holdCountdown,
  hoursBeforeStart,
  mmss,
  normaliseSearch,
  policyPreview,
  slotTimeLabels,
  sumPaise,
  validateReview,
} from './tutoringRules';

/* ========================================================================== *
 * Money — integer paise, never float arithmetic
 * ========================================================================== */

describe('money is integer paise (matrix D-06)', () => {
  it('formats paise with Indian grouping and a two-digit fraction', () => {
    expect(formatPaise(0)).toBe('₹0.00');
    expect(formatPaise(1)).toBe('₹0.01');
    expect(formatPaise(99)).toBe('₹0.99');
    expect(formatPaise(100)).toBe('₹1.00');
    expect(formatPaise(89900)).toBe('₹899.00');
    expect(formatPaise(96082)).toBe('₹960.82');
  });

  it('groups lakh-scale amounts the Indian way', () => {
    expect(formatPaise(12345678)).toBe('₹1,23,456.78');
  });

  it('renders a discount with a true minus sign, not a hyphen', () => {
    expect(formatPaise(-10000)).toBe('−₹100.00');
  });

  it('refuses a non-integer rather than silently rounding money', () => {
    expect(() => formatPaise(96082.5)).toThrow(MoneyNotIntegerPaiseError);
    expect(() => formatPaise(Number.NaN)).toThrow(MoneyNotIntegerPaiseError);
    try {
      formatPaise(1.5);
    } catch (error) {
      expect((error as MoneyNotIntegerPaiseError).code).toBe('MONEY_NOT_INTEGER_PAISE');
    }
  });

  it('sums lines in integers and refuses a float line', () => {
    expect(sumPaise(89900, 16182, -10000)).toBe(96082);
    expect(() => sumPaise(100, 0.5)).toThrow(MoneyNotIntegerPaiseError);
  });
});

/* ========================================================================== *
 * Hold countdown / expiry transition
 * ========================================================================== */

describe('booking-hold countdown and its expiry transition (matrix B1)', () => {
  const now = Date.parse('2026-08-05T12:00:00Z');
  const at = (secondsAhead: number): string =>
    new Date(now + secondsAhead * 1000).toISOString();

  it('formats mm:ss and floors at zero', () => {
    expect(mmss(0)).toBe('00:00');
    expect(mmss(9)).toBe('00:09');
    expect(mmss(600)).toBe('10:00');
    expect(mmss(-40)).toBe('00:00');
  });

  it('reads normal while more than two minutes remain', () => {
    const state = holdCountdown(at(600), now);
    expect(state).toMatchObject({ secondsLeft: 600, label: '10:00', level: 'normal', expired: false });
    expect(state.nonColourCue).toBe('plain text');
  });

  it('crosses to urgent at the two-minute threshold with a non-colour cue', () => {
    expect(holdCountdown(at(HOLD_URGENT_AT_SECONDS), now).level).toBe('normal');
    const urgent = holdCountdown(at(HOLD_URGENT_AT_SECONDS - 1), now);
    expect(urgent.level).toBe('urgent');
    expect(urgent.label).toBe('01:59');
    expect(urgent.nonColourCue).toContain('underlined');
  });

  it('transitions to expired exactly at the deadline and stays there', () => {
    expect(holdCountdown(at(1), now).expired).toBe(false);
    const atDeadline = holdCountdown(at(0), now);
    expect(atDeadline).toMatchObject({ secondsLeft: 0, label: '00:00', level: 'expired', expired: true });
    expect(holdCountdown(at(-90), now).level).toBe('expired');
  });

  it('treats a missing or unparseable deadline as expired rather than infinite', () => {
    expect(holdCountdown(null, now).expired).toBe(true);
    expect(holdCountdown(undefined, now).expired).toBe(true);
    expect(holdCountdown('not-a-date', now).expired).toBe(true);
  });

  it('subtracts from the server deadline, so a longer configured TTL just works', () => {
    // 90-minute hold: minutes are not capped at 59.
    expect(holdCountdown(at(90 * 60), now).label).toBe('90:00');
  });
});

/* ========================================================================== *
 * Cancellation / reschedule policy — the 24 hour boundary
 * ========================================================================== */

describe('the refund and reschedule boundary at exactly 24 hours (matrix D2/D3)', () => {
  const now = Date.parse('2026-08-05T12:00:00Z');
  const startIn = (hours: number, extraSeconds = 0): string =>
    new Date(now + hours * 3600_000 + extraSeconds * 1000).toISOString();
  const CAPTURED = 96082;

  it('quantises hours to two decimals exactly like payments.hours_before', () => {
    expect(hoursBeforeStart(startIn(24), now)).toBe(24);
    expect(hoursBeforeStart(startIn(23, 1800), now)).toBe(23.5);
    expect(hoursBeforeStart(startIn(-5), now)).toBe(0);
  });

  it('treats EXACTLY 24.00 hours as outside the window: full refund and free reschedule', () => {
    const preview = policyPreview({ startUtcIso: startIn(24), capturedPaise: CAPTURED, now });
    expect(preview.hoursBeforeStart).toBe(DEFAULT_REFUND_FREE_CANCEL_HOURS);
    expect(preview.refundDecision).toBe('full_refund');
    expect(preview.refundPaise).toBe(CAPTURED);
    expect(preview.rescheduleFree).toBe(true);
    expect(preview.started).toBe(false);
  });

  it('keeps a full refund one second beyond the boundary', () => {
    const preview = policyPreview({ startUtcIso: startIn(24, 1), capturedPaise: CAPTURED, now });
    expect(preview.refundDecision).toBe('full_refund');
    expect(preview.rescheduleFree).toBe(true);
  });

  it('refuses the automatic refund and the free reschedule inside the window', () => {
    const preview = policyPreview({ startUtcIso: startIn(23, 1800), capturedPaise: CAPTURED, now });
    expect(preview.hoursBeforeStart).toBe(23.5);
    expect(preview.refundDecision).toBe('no_auto_refund');
    expect(preview.refundPaise).toBe(0);
    expect(preview.rescheduleFree).toBe(false);
  });

  it('mirrors the server quantisation at 23:59:59 (23.999… rounds to 24.00)', () => {
    // Decimal(f"{delta:.2f}") on the server produces 24.00 here too, so the
    // preview must land on the SAME side of the boundary as the verdict.
    const preview = policyPreview({ startUtcIso: startIn(23, 3599), capturedPaise: CAPTURED, now });
    expect(preview.hoursBeforeStart).toBe(24);
    expect(preview.refundDecision).toBe('full_refund');
  });

  it('closes both actions once the start has passed', () => {
    const preview = policyPreview({ startUtcIso: startIn(-1), capturedPaise: CAPTURED, now });
    expect(preview.started).toBe(true);
    expect(preview.refundDecision).toBe('no_auto_refund');
    expect(preview.rescheduleFree).toBe(false);
  });

  it('gives a tutor cancellation a full refund regardless of the window', () => {
    const preview = policyPreview({
      startUtcIso: startIn(1),
      capturedPaise: CAPTURED,
      now,
      cancelledByRole: 'tutor',
    });
    expect(preview.refundDecision).toBe('full_refund');
    expect(preview.refundPaise).toBe(CAPTURED);
  });

  it('honours a configured window other than 24 hours', () => {
    const preview = policyPreview({
      startUtcIso: startIn(48),
      capturedPaise: CAPTURED,
      now,
      policyWindowHours: 72,
    });
    expect(preview.policyWindowHours).toBe(72);
    expect(preview.refundDecision).toBe('no_auto_refund');
  });

  it('never does float arithmetic on the captured amount', () => {
    expect(() => policyPreview({
      startUtcIso: startIn(48), capturedPaise: 1.5, now,
    })).toThrow(MoneyNotIntegerPaiseError);
  });
});

/* ========================================================================== *
 * Review validation — mirrored client-side, server stays authoritative
 * ========================================================================== */

describe('review validation mirrors reviews.validate_rating / validate_body (F1)', () => {
  const text = (n: number): string => 'a'.repeat(n);

  it('accepts an integer rating 1 to 5', () => {
    for (const rating of [1, 2, 3, 4, 5]) {
      expect(validateReview(rating).ok).toBe(true);
    }
  });

  it('rejects 0, 6, a float, a boolean and a string rating', () => {
    for (const rating of [0, 6, -1, 4.5, true, false, '3', null, undefined]) {
      const result = validateReview(rating as unknown);
      expect(result.ok).toBe(false);
      expect(result.codes).toContain('REVIEW_RATING_OUT_OF_RANGE');
    }
  });

  it('treats text as optional', () => {
    expect(validateReview(5).ok).toBe(true);
    expect(validateReview(5, null).ok).toBe(true);
    expect(validateReview(5, '').ok).toBe(true);
    expect(validateReview(5, '   ').ok).toBe(true);
  });

  it('enforces the 10 and 1000 character boundaries after trimming', () => {
    expect(validateReview(5, text(REVIEW_MIN_BODY - 1)).codes).toContain('REVIEW_TEXT_TOO_SHORT');
    expect(validateReview(5, text(REVIEW_MIN_BODY)).ok).toBe(true);
    expect(validateReview(5, text(REVIEW_MAX_BODY)).ok).toBe(true);
    expect(validateReview(5, text(REVIEW_MAX_BODY + 1)).codes).toContain('REVIEW_TEXT_TOO_LONG');
  });

  it('measures the trimmed length, which is what the server measures', () => {
    const result = validateReview(4, `   ${text(9)}   `);
    expect(result.length).toBe(9);
    expect(result.codes).toContain('REVIEW_TEXT_TOO_SHORT');
  });

  it('reports every failing rule at once', () => {
    const result = validateReview(0, text(4000));
    expect(result.codes).toEqual(
      expect.arrayContaining(['REVIEW_RATING_OUT_OF_RANGE', 'REVIEW_TEXT_TOO_LONG']),
    );
  });
});

/* ========================================================================== *
 * Search normalisation and time rendering
 * ========================================================================== */

describe('search normalisation matches the GET /tutors ceiling', () => {
  it('collapses whitespace, trims and caps at 120 characters', () => {
    expect(normaliseSearch('  arbitration   clause  ')).toBe('arbitration clause');
    expect(normaliseSearch(null)).toBe('');
    expect(normaliseSearch('x'.repeat(200))).toHaveLength(120);
  });
});

describe('times render in the retained zone and the reader zone', () => {
  const startUtc = '2026-08-05T13:00:00+00:00';
  const endUtc = '2026-08-05T13:45:00+00:00';

  it('leads with the session zone and omits the reader zone when they match', () => {
    const labels = slotTimeLabels(startUtc, endUtc, 'Asia/Kolkata', 'Asia/Kolkata');
    expect(labels.sessionZoneLabel).toContain('Asia/Kolkata');
    expect(labels.sessionZone).toContain('2026');
    expect(labels.readerZone).toBeNull();
    expect(labels.readerZoneLabel).toBeNull();
  });

  it('adds the reader zone when it differs, from the SAME instant', () => {
    const labels = slotTimeLabels(startUtc, endUtc, 'Asia/Kolkata', 'Europe/London');
    expect(labels.readerZoneLabel).toContain('Europe/London');
    // 13:00 UTC is 6:30 pm in Kolkata and 2:00 pm in London.
    expect(labels.sessionZone).toMatch(/6:30/);
    expect(labels.readerZone).toMatch(/2:00/);
  });

  it('falls back to the reader zone rather than blanking on an unknown zone', () => {
    expect(() => slotTimeLabels(startUtc, endUtc, 'Mars/Olympus_Mons')).not.toThrow();
  });

  it('computes a duration in whole minutes', () => {
    expect(durationMinutes(startUtc, endUtc)).toBe(45);
    expect(durationMinutes('nope', endUtc)).toBe(0);
  });
});
