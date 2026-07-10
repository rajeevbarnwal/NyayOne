/**
 * Session, device, and account security logic (SAATHI-4 · P0.3).
 *
 * Pure, framework-free logic mirroring the server rules. The server is always
 * authoritative for sessions; the client renders derived state only.
 *
 * Security invariants (load-bearing):
 *  - NEVER store or return raw tokens, OTPs, passwords, or secrets. Sessions are
 *    referenced by an opaque id; any credential material is represented by a
 *    non-reversible fingerprint only.
 *  - Configurable session expiry + refresh; refresh is refused once the refresh
 *    window has lapsed or the device is revoked.
 *  - Rate limiting + lockout resist brute force on login and password/OTP reset.
 *  - Sensitive actions require re-authentication.
 *  - Every login / failed login / logout / reset / device revocation is audited.
 *  - Biometric/native re-auth is a capability boundary, not a live implementation.
 */

// --- Configurable policy (server-owned; mirrored here) -----------------------

export interface SessionPolicy {
  readonly sessionTtlMs: number;
  readonly refreshTtlMs: number;
  readonly maxFailedAttempts: number;
  readonly lockMs: number;
  /** Re-auth is required for a sensitive action if the session is older than this. */
  readonly reauthWithinMs: number;
}

export const DEFAULT_SESSION_POLICY: SessionPolicy = {
  sessionTtlMs: 30 * 60 * 1000, // 30 min access window
  refreshTtlMs: 7 * 24 * 60 * 60 * 1000, // 7 day refresh window
  maxFailedAttempts: 5,
  lockMs: 15 * 60 * 1000,
  reauthWithinMs: 5 * 60 * 1000, // sensitive actions need auth in the last 5 min
};

// --- Sessions ----------------------------------------------------------------

export interface Session {
  readonly id: string; // opaque handle — NOT a token
  readonly userId: string;
  readonly deviceId: string;
  readonly issuedAt: number;
  readonly expiresAt: number;
  readonly refreshExpiresAt: number;
  readonly lastAuthAt: number;
  readonly revoked: boolean;
}

export function issueSession(userId: string, deviceId: string, now: number, policy: SessionPolicy = DEFAULT_SESSION_POLICY): Session {
  return {
    id: `sess_${userId}_${deviceId}_${now}`,
    userId,
    deviceId,
    issuedAt: now,
    expiresAt: now + policy.sessionTtlMs,
    refreshExpiresAt: now + policy.refreshTtlMs,
    lastAuthAt: now,
    revoked: false,
  };
}

export function isSessionActive(s: Session, now: number): boolean {
  return !s.revoked && now < s.expiresAt;
}

export function canRefresh(s: Session, now: number): boolean {
  return !s.revoked && now < s.refreshExpiresAt;
}

/** Slide the access window forward. Refresh is refused when the window lapsed. */
export function refreshSession(s: Session, now: number, policy: SessionPolicy = DEFAULT_SESSION_POLICY): Session | null {
  if (!canRefresh(s, now)) return null;
  return { ...s, expiresAt: now + policy.sessionTtlMs };
}

export function revokeSession(s: Session): Session {
  return { ...s, revoked: true };
}

/** Sensitive actions require a recent authentication. */
export function requiresReauth(s: Session, now: number, policy: SessionPolicy = DEFAULT_SESSION_POLICY): boolean {
  return now - s.lastAuthAt > policy.reauthWithinMs;
}

export function markReauthenticated(s: Session, now: number): Session {
  return { ...s, lastAuthAt: now };
}

export const SENSITIVE_ACTIONS = [
  'change_password',
  'revoke_device',
  'export_case_file',
  'update_bank_details',
  'delete_account',
] as const;
export type SensitiveAction = (typeof SENSITIVE_ACTIONS)[number];
export function isSensitiveAction(a: string): a is SensitiveAction {
  return (SENSITIVE_ACTIONS as readonly string[]).includes(a);
}

// --- Devices -----------------------------------------------------------------

export interface DeviceRecord {
  readonly deviceId: string;
  readonly label: string; // e.g. "Pixel 8 · Chrome" — no PII
  readonly lastSeen: number;
  readonly current: boolean;
  readonly revoked: boolean;
}

export function revokeDevice(devices: readonly DeviceRecord[], deviceId: string): DeviceRecord[] {
  return devices.map((d) => (d.deviceId === deviceId ? { ...d, revoked: true, current: false } : d));
}

/** A revoked device's sessions must not refresh — helper for the session layer. */
export function deviceActive(devices: readonly DeviceRecord[], deviceId: string): boolean {
  const d = devices.find((x) => x.deviceId === deviceId);
  return !!d && !d.revoked;
}

// --- Rate limiting / lockout (login + reset) ---------------------------------

export interface AttemptState {
  readonly failures: number;
  readonly lockedUntil: number | null;
}

export const FRESH_ATTEMPTS: AttemptState = { failures: 0, lockedUntil: null };

export function isLockedOut(a: AttemptState, now: number): boolean {
  return a.lockedUntil !== null && now < a.lockedUntil;
}

/** Register a failed attempt; locks out once the max is reached. */
export function registerFailure(a: AttemptState, now: number, policy: SessionPolicy = DEFAULT_SESSION_POLICY): AttemptState {
  if (isLockedOut(a, now)) return a;
  const failures = a.failures + 1;
  if (failures >= policy.maxFailedAttempts) {
    return { failures, lockedUntil: now + policy.lockMs };
  }
  return { failures, lockedUntil: null };
}

export function registerSuccess(): AttemptState {
  return FRESH_ATTEMPTS;
}

// --- Credential fingerprint (never store raw secrets) ------------------------

/**
 * Non-reversible fingerprint for a credential/token, for equality checks and
 * audit correlation only. This is a NON-cryptographic stand-in for the
 * server-side hash; the raw value must never leave the input.
 */
export function fingerprint(secret: string): string {
  let h = 2166136261 >>> 0;
  for (let i = 0; i < secret.length; i += 1) {
    h ^= secret.charCodeAt(i);
    h = Math.imul(h, 16777619) >>> 0;
  }
  return `fp_${h.toString(16)}`;
}

// --- Security audit -----------------------------------------------------------

export type SecurityEventType =
  | 'login'
  | 'login_failed'
  | 'logout'
  | 'session_refresh'
  | 'password_reset'
  | 'device_revoked'
  | 'reauth'
  | 'lockout';

export interface SecurityAuditEvent {
  readonly type: SecurityEventType;
  readonly userId: string;
  readonly deviceId: string;
  readonly timestamp: number;
  /** Optional non-reversible correlation fingerprint — never a raw secret. */
  readonly ref?: string;
}
export function securityEvent(type: SecurityEventType, userId: string, deviceId: string, now: number, ref?: string): SecurityAuditEvent {
  return { type, userId, deviceId, timestamp: now, ref };
}

// --- Biometric / native re-auth capability boundary --------------------------

export type BiometricCapability = 'available' | 'unavailable';
/**
 * Native biometric re-auth is only offered when the mobile shell reports the
 * capability. In the web/dev shell it is 'unavailable' — a disabled boundary,
 * never a faked "success".
 */
export function biometricCapability(nativeAvailable: boolean): BiometricCapability {
  return nativeAvailable ? 'available' : 'unavailable';
}

// --- Unusual-login/reset notification (adapter boundary; no external send) ----

export interface SecurityNotifier {
  notify(event: SecurityAuditEvent): void;
}
export function createStubSecurityNotifier(sink: SecurityAuditEvent[] = []): SecurityNotifier {
  return { notify: (e) => { sink.push(e); } };
}

export const SECURITY_EVENT_LABELS: Record<SecurityEventType, string> = {
  login: 'Signed in',
  login_failed: 'Failed sign-in',
  logout: 'Signed out',
  session_refresh: 'Session refreshed',
  password_reset: 'Password reset',
  device_revoked: 'Device signed out',
  reauth: 'Re-authenticated',
  lockout: 'Locked (too many attempts)',
};
