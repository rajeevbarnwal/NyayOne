/**
 * In-memory auth-flow context shared across the S1 screens (stub only).
 * Holds the current OTP destination + challenge and the derived minor flag so
 * the register/login screens (S-03/S-05) can hand off to OTP entry (S-06).
 * No persistence, no network — a placeholder for the server-side P0.2 session.
 */
import {
  createChallenge,
  createStubOtpSender,
  type OtpChallenge,
  type OtpDestination,
} from './otp';

interface FlowState {
  destination: OtpDestination | null;
  challenge: OtpChallenge | null;
  isMinor: boolean;
  guardianConsentPending: boolean;
}

const state: FlowState = {
  destination: null,
  challenge: null,
  isMinor: false,
  guardianConsentPending: false,
};

const sender = createStubOtpSender();

/** Deterministic stub code for prototype/QA (never used in production). */
export const STUB_OTP_CODE = '429016';

export function startOtp(destination: OtpDestination, now: number): OtpChallenge {
  sender.send(destination, STUB_OTP_CODE, now); // stub — no network
  const challenge = createChallenge(STUB_OTP_CODE, now);
  state.destination = destination;
  state.challenge = challenge;
  return challenge;
}

export function setChallenge(challenge: OtpChallenge): void {
  state.challenge = challenge;
}

export function setMinor(isMinor: boolean, guardianConsentPending: boolean): void {
  state.isMinor = isMinor;
  state.guardianConsentPending = guardianConsentPending;
}

export function getFlow(): Readonly<FlowState> {
  return state;
}
