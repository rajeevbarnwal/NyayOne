/**
 * OTP verification state machine + delivery adapter boundary (SAATHI-53 / S1.2).
 *
 * Pure, framework-free logic so it is unit-testable and mirrors the server rules.
 * NO external network calls happen here: delivery goes through an `OtpSender`
 * adapter whose only shipped implementation is a local stub. In production the
 * real send/verify runs server-side via the existing P0.2 identity path — the
 * client only renders the resulting state.
 *
 * Rules (from the v3.2 prototype copy + PRD S1.2):
 *  - 6-digit numeric code, valid for 5 minutes.
 *  - 3 attempts; after they are exhausted the login locks for 15 minutes.
 *  - Resend is gated by a short cooldown.
 */

export const OTP_LENGTH = 6;
export const OTP_MAX_ATTEMPTS = 3;
export const OTP_TTL_MS = 5 * 60 * 1000; // "Codes are valid for 5 minutes."
export const OTP_RESEND_COOLDOWN_MS = 30 * 1000;
export const OTP_LOCK_MS = 15 * 60 * 1000; // "Login is locked for 15 minutes."

export type OtpVerifyStatus = 'verified' | 'incorrect' | 'expired' | 'locked';

export interface OtpChallenge {
  /** Stub-only expected code. Never present on the client in production. */
  readonly code: string;
  readonly sentAt: number;
  readonly expiresAt: number;
  readonly attemptsLeft: number;
  readonly lockedUntil: number | null;
}

export interface OtpVerifyResult {
  readonly status: OtpVerifyStatus;
  readonly challenge: OtpChallenge;
}

/** True when the input is a well-formed OTP (6 digits). */
export function isValidOtpFormat(input: string): boolean {
  return new RegExp(`^\\d{${OTP_LENGTH}}$`).test(input);
}

export function createChallenge(code: string, now: number): OtpChallenge {
  return {
    code,
    sentAt: now,
    expiresAt: now + OTP_TTL_MS,
    attemptsLeft: OTP_MAX_ATTEMPTS,
    lockedUntil: null,
  };
}

export function isExpired(ch: OtpChallenge, now: number): boolean {
  return now >= ch.expiresAt;
}

export function isLocked(ch: OtpChallenge, now: number): boolean {
  return ch.lockedUntil !== null && now < ch.lockedUntil;
}

/** Whole seconds until resend is allowed (0 when allowed now). */
export function secondsUntilResend(ch: OtpChallenge, now: number): number {
  const readyAt = ch.sentAt + OTP_RESEND_COOLDOWN_MS;
  return Math.max(0, Math.ceil((readyAt - now) / 1000));
}

export function canResend(ch: OtpChallenge, now: number): boolean {
  return secondsUntilResend(ch, now) === 0;
}

/** Whole seconds until the current code expires (0 when expired). */
export function secondsUntilExpiry(ch: OtpChallenge, now: number): number {
  return Math.max(0, Math.ceil((ch.expiresAt - now) / 1000));
}

/**
 * Attempt to verify a code. Returns a NEW challenge (immutable) plus a status.
 * Lock takes priority, then expiry, then match, then a decremented attempt.
 * When the last attempt is consumed the challenge locks.
 */
export function verify(ch: OtpChallenge, input: string, now: number): OtpVerifyResult {
  if (isLocked(ch, now)) return { status: 'locked', challenge: ch };
  if (isExpired(ch, now)) return { status: 'expired', challenge: ch };
  if (input === ch.code) return { status: 'verified', challenge: ch };

  const attemptsLeft = ch.attemptsLeft - 1;
  if (attemptsLeft <= 0) {
    return {
      status: 'locked',
      challenge: { ...ch, attemptsLeft: 0, lockedUntil: now + OTP_LOCK_MS },
    };
  }
  return { status: 'incorrect', challenge: { ...ch, attemptsLeft } };
}

/** Issue a fresh code, resetting attempts and expiry. */
export function resend(ch: OtpChallenge, newCode: string, now: number): OtpChallenge {
  return createChallenge(newCode, now);
}

// --- Delivery adapter boundary (no external network here) ---

export type OtpChannel = 'sms' | 'email';

export interface OtpDestination {
  readonly channel: OtpChannel;
  /** Opaque/masked reference — never a raw phone/email in logs. */
  readonly ref: string;
}

export interface OtpSendReceipt {
  readonly challengeId: string;
  readonly sentAt: number;
  readonly channel: OtpChannel;
}

export interface OtpSender {
  send(dest: OtpDestination, code: string, now: number): OtpSendReceipt;
}

/**
 * Local stub sender: performs NO network I/O. Stands in for the server-side
 * P0.2 delivery path during development and QA.
 */
export function createStubOtpSender(): OtpSender {
  let seq = 0;
  return {
    send(dest, _code, now) {
      seq += 1;
      return { challengeId: `stub-${dest.channel}-${seq}`, sentAt: now, channel: dest.channel };
    },
  };
}

/** Mask a phone/email for display (never render the raw value). */
export function maskDestination(dest: OtpDestination): string {
  if (dest.channel === 'sms') {
    const digits = dest.ref.replace(/\D/g, '');
    const tail = digits.slice(-3);
    return `+91 ••••• ••${tail || '•••'}`;
  }
  const [user, domain] = dest.ref.split('@');
  const head = user ? user.slice(0, 2) : 'aa';
  return `${head}•••@${domain ?? 'nls.ac.in'}`;
}
