/**
 * Wave 2 tutoring — pure client-side rule mirrors (SAATHI-65 / SAATHI-66, P4).
 *
 * Every function here duplicates a rule the backend already enforces
 * (`backend/app/services/tutoring/*`). The SERVER STAYS AUTHORITATIVE: these
 * exist only so the UI can pre-empt an obviously invalid submit, render a
 * policy preview, and drive the hold countdown between polls. When a server
 * verdict disagrees with a value computed here, the server verdict wins and is
 * what the screen renders.
 *
 * Money is INTEGER PAISE end to end (matrix D-06 / `payments.assert_paise`).
 * Nothing in this module performs float arithmetic on an amount: formatting
 * splits paise with integer division and only ever groups the rupee integer.
 */

/* --------------------------------------------------------------------------
 * Frozen constants (mirrors of backend settings / service constants)
 * -------------------------------------------------------------------------- */

/** `settings.booking_hold_minutes` default. The API echoes `hold_minutes`. */
export const DEFAULT_HOLD_MINUTES = 10;
/** Non-colour urgency threshold for the hold countdown (reference NEG-HOLD-06). */
export const HOLD_URGENT_AT_SECONDS = 120;
/** `settings.refund_free_cancel_hours` default; the API echoes it per verdict. */
export const DEFAULT_REFUND_FREE_CANCEL_HOURS = 24;
/** `reviews.MIN_RATING` / `MAX_RATING`. */
export const REVIEW_MIN_RATING = 1;
export const REVIEW_MAX_RATING = 5;
/** `reviews.MIN_BODY` / `MAX_BODY`, measured after trim, same as the server. */
export const REVIEW_MIN_BODY = 10;
export const REVIEW_MAX_BODY = 1000;
/** `availability.DEFAULT_TIMEZONE`. */
export const DEFAULT_TIMEZONE = 'Asia/Kolkata';

/* --------------------------------------------------------------------------
 * Money — integer paise only
 * -------------------------------------------------------------------------- */

/** Raised when a caller hands a non-integer to a money formatter. */
export class MoneyNotIntegerPaiseError extends Error {
  readonly code = 'MONEY_NOT_INTEGER_PAISE';
  constructor(readonly received: unknown) {
    super('MONEY_NOT_INTEGER_PAISE');
  }
}

const RUPEE_GROUPER = new Intl.NumberFormat('en-IN', { useGrouping: true });

/**
 * Format integer paise as an Indian-grouped rupee string.
 *
 * The rupee part and the paise part are split with integer division, so the
 * fractional component is never produced by dividing by 100 in floating point.
 * A negative amount (a discount line) renders with a true minus sign.
 */
export function formatPaise(paise: number): string {
  if (!Number.isInteger(paise)) throw new MoneyNotIntegerPaiseError(paise);
  const negative = paise < 0;
  const magnitude = Math.abs(paise);
  const rupees = Math.trunc(magnitude / 100);
  const fraction = magnitude % 100;
  return `${negative ? '−' : ''}₹${RUPEE_GROUPER.format(rupees)}.${String(fraction).padStart(2, '0')}`;
}

/** Sum integer-paise lines without ever leaving integer arithmetic. */
export function sumPaise(...lines: number[]): number {
  let total = 0;
  for (const line of lines) {
    if (!Number.isInteger(line)) throw new MoneyNotIntegerPaiseError(line);
    total += line;
  }
  return total;
}

/* --------------------------------------------------------------------------
 * Booking hold countdown
 * -------------------------------------------------------------------------- */

export type HoldLevel = 'normal' | 'urgent' | 'expired';

export interface HoldCountdown {
  /** Whole seconds left, floored at 0. */
  secondsLeft: number;
  /** mm:ss for the `role="timer"` accessible name and the display. */
  label: string;
  level: HoldLevel;
  /**
   * The non-colour cue this level must also render (WCAG 1.4.1). The screen
   * reads this so urgency is never expressed by hue alone.
   */
  nonColourCue: string;
  /** True once the hold is gone: the slot is released and nothing is charged. */
  expired: boolean;
}

/** mm:ss, floored at 00:00. Minutes are not capped at 59 (a 90 min TTL reads 90:00). */
export function mmss(secondsLeft: number): string {
  const total = Math.max(0, Math.floor(secondsLeft));
  const minutes = Math.floor(total / 60);
  const seconds = total % 60;
  return `${String(minutes).padStart(2, '0')}:${String(seconds).padStart(2, '0')}`;
}

/**
 * Derive the countdown state from the hold's server-issued `expires_at`.
 *
 * The client never invents the deadline: it subtracts from the instant the API
 * returned. Crossing zero is a UI transition only; the authoritative refusal is
 * the server's `HOLD_EXPIRED`.
 */
export function holdCountdown(
  expiresAtIso: string | null | undefined,
  now: Date | number = Date.now(),
  urgentAtSeconds: number = HOLD_URGENT_AT_SECONDS,
): HoldCountdown {
  const nowMs = typeof now === 'number' ? now : now.getTime();
  const deadline = expiresAtIso ? Date.parse(expiresAtIso) : Number.NaN;
  const secondsLeft = Number.isNaN(deadline)
    ? 0
    : Math.max(0, Math.floor((deadline - nowMs) / 1000));
  if (secondsLeft <= 0) {
    return {
      secondsLeft: 0,
      label: mmss(0),
      level: 'expired',
      nonColourCue: 'wording changes to released, the timer stops and pay is disabled',
      expired: true,
    };
  }
  if (secondsLeft < urgentAtSeconds) {
    return {
      secondsLeft,
      label: mmss(secondsLeft),
      level: 'urgent',
      nonColourCue: 'thicker border, underlined remaining time and "Under two minutes left."',
      expired: false,
    };
  }
  return {
    secondsLeft,
    label: mmss(secondsLeft),
    level: 'normal',
    nonColourCue: 'plain text',
    expired: false,
  };
}

/* --------------------------------------------------------------------------
 * Cancellation / reschedule policy preview
 * -------------------------------------------------------------------------- */

/**
 * Hours from `now` to the start, quantised to two decimals and floored at 0 —
 * the same shape as `payments.hours_before` (`Decimal(f"{delta:.2f}")`), so the
 * preview lands on the same side of the boundary as the server verdict.
 */
export function hoursBeforeStart(
  startUtcIso: string,
  now: Date | number = Date.now(),
): number {
  const nowMs = typeof now === 'number' ? now : now.getTime();
  const startMs = Date.parse(startUtcIso);
  if (Number.isNaN(startMs)) return 0;
  const raw = (startMs - nowMs) / 3600000;
  if (raw <= 0) return 0;
  return Math.round(raw * 100) / 100;
}

export type RefundDecision = 'full_refund' | 'no_auto_refund' | 'admin_exception';

export interface PolicyPreview {
  hoursBeforeStart: number;
  policyWindowHours: number;
  /** Server rule: `hrs >= window` earns the automatic full refund (inclusive). */
  refundDecision: RefundDecision;
  refundPaise: number;
  /** Server rule: a free reschedule needs `hrs >= window`; inside it refuses. */
  rescheduleFree: boolean;
  /** True once the start has passed: cancel and reschedule are both closed. */
  started: boolean;
}

/**
 * Client mirror of `payments.assess_refund` + the `sessions.reschedule` notice
 * check, including the INCLUSIVE boundary: exactly 24.00 hours before start is
 * still outside the window, so it is a free reschedule and a full refund.
 */
export function policyPreview(options: {
  startUtcIso: string;
  capturedPaise: number;
  now?: Date | number;
  policyWindowHours?: number;
  cancelledByRole?: 'student' | 'tutor' | 'admin';
}): PolicyPreview {
  const {
    startUtcIso,
    capturedPaise,
    now = Date.now(),
    policyWindowHours = DEFAULT_REFUND_FREE_CANCEL_HOURS,
    cancelledByRole = 'student',
  } = options;
  if (!Number.isInteger(capturedPaise)) throw new MoneyNotIntegerPaiseError(capturedPaise);
  const hours = hoursBeforeStart(startUtcIso, now);
  const nowMs = typeof now === 'number' ? now : now.getTime();
  const started = Date.parse(startUtcIso) <= nowMs;
  // Frozen precedence: tutor cancellation > admin exception > the 24h window.
  if (cancelledByRole === 'tutor') {
    return {
      hoursBeforeStart: hours,
      policyWindowHours,
      refundDecision: 'full_refund',
      refundPaise: capturedPaise,
      rescheduleFree: !started && hours >= policyWindowHours,
      started,
    };
  }
  const outsideWindow = !started && hours >= policyWindowHours;
  return {
    hoursBeforeStart: hours,
    policyWindowHours,
    refundDecision: outsideWindow ? 'full_refund' : 'no_auto_refund',
    refundPaise: outsideWindow ? capturedPaise : 0,
    rescheduleFree: outsideWindow,
    started,
  };
}

/* --------------------------------------------------------------------------
 * Review validation (mirror of reviews.validate_rating / validate_body)
 * -------------------------------------------------------------------------- */

export type ReviewValidationCode =
  | 'REVIEW_RATING_OUT_OF_RANGE'
  | 'REVIEW_TEXT_TOO_SHORT'
  | 'REVIEW_TEXT_TOO_LONG';

export interface ReviewValidation {
  ok: boolean;
  codes: ReviewValidationCode[];
  /** Trimmed length, which is what the server measures. */
  length: number;
}

/**
 * Rating must be an integer 1..5 (a boolean and a float are both rejected, as
 * on the server). Text is OPTIONAL; when present it must be 10..1000
 * characters AFTER trimming.
 */
export function validateReview(rating: unknown, body?: string | null): ReviewValidation {
  const codes: ReviewValidationCode[] = [];
  const ratingOk =
    typeof rating === 'number'
    && Number.isInteger(rating)
    && rating >= REVIEW_MIN_RATING
    && rating <= REVIEW_MAX_RATING;
  if (!ratingOk) codes.push('REVIEW_RATING_OUT_OF_RANGE');
  const text = typeof body === 'string' ? body.trim() : '';
  const length = text.length;
  if (body !== null && body !== undefined && length > 0) {
    if (length < REVIEW_MIN_BODY) codes.push('REVIEW_TEXT_TOO_SHORT');
    else if (length > REVIEW_MAX_BODY) codes.push('REVIEW_TEXT_TOO_LONG');
  }
  return { ok: codes.length === 0, codes, length };
}

/* --------------------------------------------------------------------------
 * Search input normalisation (mirror of the GET /tutors query ceilings)
 * -------------------------------------------------------------------------- */

export const SEARCH_MAX_LENGTH = 120;

export function normaliseSearch(raw: string | null | undefined): string {
  return String(raw ?? '').replace(/\s+/g, ' ').trim().slice(0, SEARCH_MAX_LENGTH);
}

/* --------------------------------------------------------------------------
 * Time rendering — the session's retained zone AND the reader's own zone
 * -------------------------------------------------------------------------- */

/** The reader's IANA zone as the platform reports it, with a safe fallback. */
export function browserTimeZone(): string {
  try {
    return Intl.DateTimeFormat().resolvedOptions().timeZone || DEFAULT_TIMEZONE;
  } catch {
    return DEFAULT_TIMEZONE;
  }
}

function formatter(timeZone: string, options: Intl.DateTimeFormatOptions): Intl.DateTimeFormat {
  try {
    return new Intl.DateTimeFormat('en-IN', { ...options, timeZone });
  } catch {
    // An unknown zone must not blank the screen; fall back to the reader's.
    return new Intl.DateTimeFormat('en-IN', options);
  }
}

/** "Wed, 5 Aug 2026" in the given zone. */
export function formatDateInZone(utcIso: string, timeZone: string): string {
  return formatter(timeZone, {
    weekday: 'short',
    day: 'numeric',
    month: 'short',
    year: 'numeric',
  }).format(new Date(utcIso));
}

/** "6:30 pm" in the given zone. */
export function formatTimeInZone(utcIso: string, timeZone: string): string {
  return formatter(timeZone, { hour: 'numeric', minute: '2-digit', hour12: true })
    .format(new Date(utcIso));
}

/** The zone's short name for this instant, e.g. "IST" or "GMT+5:30". */
export function zoneAbbreviation(utcIso: string, timeZone: string): string {
  const parts = formatter(timeZone, { timeZoneName: 'short' }).formatToParts(new Date(utcIso));
  return parts.find((p) => p.type === 'timeZoneName')?.value ?? timeZone;
}

export interface SlotTimeLabels {
  /** "Wed, 5 Aug 2026 · 6:30 pm to 7:15 pm" in the retained session zone. */
  sessionZone: string;
  /** The retained IANA zone plus its abbreviation, e.g. "Asia/Kolkata (IST)". */
  sessionZoneLabel: string;
  /** The same instant in the reader's own zone, or null when it is the same zone. */
  readerZone: string | null;
  readerZoneLabel: string | null;
}

/**
 * Render one slot/session window in the session's RETAINED IANA zone, and also
 * in the reader's zone whenever the two differ. The retained zone is what the
 * mentor and the record agree on, so it always leads.
 */
export function slotTimeLabels(
  startUtcIso: string,
  endUtcIso: string,
  sessionTimeZone: string,
  readerTimeZone: string = browserTimeZone(),
): SlotTimeLabels {
  const range = (zone: string): string =>
    `${formatDateInZone(startUtcIso, zone)} · ${formatTimeInZone(startUtcIso, zone)} to ${formatTimeInZone(endUtcIso, zone)}`;
  const sessionZoneLabel = `${sessionTimeZone} (${zoneAbbreviation(startUtcIso, sessionTimeZone)})`;
  const sameZone = readerTimeZone === sessionTimeZone;
  return {
    sessionZone: range(sessionTimeZone),
    sessionZoneLabel,
    readerZone: sameZone ? null : range(readerTimeZone),
    readerZoneLabel: sameZone
      ? null
      : `${readerTimeZone} (${zoneAbbreviation(startUtcIso, readerTimeZone)})`,
  };
}

/** Whole minutes between two instants — a duration, never money. */
export function durationMinutes(startUtcIso: string, endUtcIso: string): number {
  const ms = Date.parse(endUtcIso) - Date.parse(startUtcIso);
  return Number.isNaN(ms) ? 0 : Math.round(ms / 60000);
}
