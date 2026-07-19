/**
 * S19.2 — Reminder Preferences and Privacy-Safe Notifications (SAATHI-290/292).
 *
 * Pure, framework-free domain for user-scoped reminder preferences and the
 * privacy-safe notification-preview policy. Consumes the S19.1 calendar source
 * contract (CalendarSourceType / SOURCE_LABELS) from `./calendar`. No live
 * SMS/email/push is dispatched here — the "preview" is a redacted, in-app
 * representation only.
 *
 * Hardening (independent-QA remediation at 083d1c76 → this commit):
 *  - Strict input validation: non-boolean `enabled`, malformed `updatedAt`, and
 *    unsupported timezones are typed errors and are never seeded or persisted.
 *  - Full stored-schema validation at every persistence boundary; malformed
 *    persisted state is never trusted (read → null; load → safe defaults, never
 *    overwriting the stored blob).
 *  - Privacy: previews redact identifiers (email, phone, event/case/client IDs)
 *    for EVERY classification, including `public`; source labels come from a
 *    trusted enum, never arbitrary caller text.
 *  - Authorization: an explicit actor/role model at the service boundary; a
 *    wrong role is a typed `unauthorized` error distinct from cross-user
 *    `forbidden`.
 *  - Concurrency/idempotency: optimistic concurrency via `expectedUpdatedAt`
 *    (typed `conflict`), plus idempotency-key replay protection so a retry can
 *    never duplicate audit effects.
 */
import { defaultKvStore, type KvStore } from '../../../lib/kvStore';
import { CALENDAR_SOURCE_TYPES, SOURCE_LABELS, type CalendarSourceType } from './calendar';

export const REMINDER_CHANNELS = ['in_app', 'email_digest', 'push'] as const;
export type ReminderChannel = (typeof REMINDER_CHANNELS)[number];

/** Allowed lead times in minutes before an event (0 = at start). */
export const REMINDER_LEAD_MINUTES: readonly number[] = [0, 10, 30, 60, 120, 24 * 60];
export const DEFAULT_TIMEZONE = 'Asia/Kolkata';
export const NO_LIVE_DELIVERY_NOTICE =
  'Reminders preview in-app only; no live SMS, email or push is sent (integration pending).';

/** Roles that may appear at the service boundary. Only `student` owns their prefs. */
export const STUDENT_ROLES = ['student', 'moderator', 'admin', 'system', 'guest'] as const;
export type StudentRole = (typeof STUDENT_ROLES)[number];

/** An explicit actor at the service boundary. A bare string is shorthand for a `student` actor. */
export interface Actor {
  readonly subjectId: string;
  readonly role: StudentRole;
}
export type Requester = string | Actor;

export interface ReminderPref {
  readonly sourceType: CalendarSourceType;
  readonly channel: ReminderChannel;
  readonly enabled: boolean;
  readonly leadMinutes: number;
  /** Quiet hours as minutes from local midnight, [0, 1440). start === end ⇒ no quiet window. */
  readonly quietStartMin: number;
  readonly quietEndMin: number;
  readonly timezone: string;
}

/** Non-sensitive audit trail entry (no titles/notes/identifiers are ever recorded). */
export interface AuditEntry {
  readonly at: string;
  readonly action: 'save';
  readonly sourceType: CalendarSourceType;
  readonly channel: ReminderChannel;
}

export interface ReminderPrefState {
  readonly studentId: string;
  readonly prefs: readonly ReminderPref[];
  readonly updatedAt: string;
  /** Append-only, non-sensitive audit trail. Optional for backward compatibility. */
  readonly audit?: readonly AuditEntry[];
  /** Applied idempotency keys, for retry replay-protection. Optional for backward compatibility. */
  readonly seenKeys?: readonly string[];
}

export type ReminderErrorReason =
  | 'source'
  | 'channel'
  | 'enabled'
  | 'lead_time'
  | 'quiet_range'
  | 'timezone'
  | 'timestamp'
  | 'forbidden'
  | 'unauthorized'
  | 'conflict';
export type ReminderResult = { ok: true; state: ReminderPrefState } | { ok: false; reason: ReminderErrorReason };

/** Options for concurrency control and idempotent retries. */
export interface SaveOptions {
  /** Optimistic-concurrency token; must equal the stored `updatedAt` (or null for a first write). */
  readonly expectedUpdatedAt?: string | null;
  /** Idempotency key; a repeated key is a no-op replay that produces no new audit effect. */
  readonly idempotencyKey?: string;
}

const key = (studentId: string) => `ls-reminder-prefs-${studentId}`;

// ---- Identifier redaction (applied to EVERY preview, including `public`) ----
const EMAIL_RE = /[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}/g;
// Phone: an optional +, then 8+ digits possibly separated by space/()-.
const PHONE_RE = /\+?\d(?:[\d\s().-]{6,})\d/g;
// Case / client / event identifiers, e.g. EV-99177, CASE-1234, CL-0007.
const ID_RE = /\b[A-Za-z]{2,}-\d{3,}\b/g;
const REDACTED = '[redacted]';

/** Strip email / phone / case-style identifiers from arbitrary text. */
export function redactIdentifiers(text: string): string {
  if (typeof text !== 'string' || !text) return '';
  return text.replace(EMAIL_RE, REDACTED).replace(PHONE_RE, REDACTED).replace(ID_RE, REDACTED);
}

/** True when `tz` is a valid IANA timezone the runtime accepts. */
export function isValidTimezone(tz: unknown): tz is string {
  if (!tz || typeof tz !== 'string') return false;
  try {
    new Intl.DateTimeFormat('en-US', { timeZone: tz });
    return true;
  } catch {
    return false;
  }
}

/** True when `value` is a real, parseable ISO-8601 timestamp string. */
export function isIsoTimestamp(value: unknown): value is string {
  if (typeof value !== 'string' || !value) return false;
  if (!/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d{1,3})?(Z|[+-]\d{2}:\d{2})$/.test(value)) return false;
  return Number.isFinite(Date.parse(value));
}

/** Validate a preference; returns null when valid or a typed reason when not. */
export function validatePref(input: Partial<ReminderPref>): ReminderErrorReason | null {
  if (!input.sourceType || !CALENDAR_SOURCE_TYPES.includes(input.sourceType)) return 'source';
  if (!input.channel || !(REMINDER_CHANNELS as readonly string[]).includes(input.channel)) return 'channel';
  if (typeof input.enabled !== 'boolean') return 'enabled';
  if (typeof input.leadMinutes !== 'number' || !REMINDER_LEAD_MINUTES.includes(input.leadMinutes)) return 'lead_time';
  const inRange = (n: unknown) => typeof n === 'number' && Number.isInteger(n) && n >= 0 && n < 1440;
  if (!inRange(input.quietStartMin) || !inRange(input.quietEndMin)) return 'quiet_range';
  if (!isValidTimezone(input.timezone)) return 'timezone';
  return null;
}

/**
 * Validate a full persisted state blob before trusting it. Guards ownership,
 * timestamp, every pref row, and the optional audit/seenKeys shapes.
 */
export function isValidState(value: unknown, studentId: string): value is ReminderPrefState {
  if (!value || typeof value !== 'object') return false;
  const s = value as Record<string, unknown>;
  if (s.studentId !== studentId) return false;
  if (!isIsoTimestamp(s.updatedAt)) return false;
  if (!Array.isArray(s.prefs)) return false;
  for (const p of s.prefs) {
    if (!p || typeof p !== 'object') return false;
    if (validatePref(p as Partial<ReminderPref>) !== null) return false;
  }
  if (s.audit !== undefined && !Array.isArray(s.audit)) return false;
  if (s.seenKeys !== undefined && !Array.isArray(s.seenKeys)) return false;
  return true;
}

/** Safe defaults for a new user: in-app on for every source, 30-min lead, 22:00–07:00 quiet. */
export function defaultPrefs(timezone: string = DEFAULT_TIMEZONE): ReminderPref[] {
  const tz = isValidTimezone(timezone) ? timezone : DEFAULT_TIMEZONE;
  return CALENDAR_SOURCE_TYPES.map((sourceType) => ({
    sourceType,
    channel: 'in_app' as ReminderChannel,
    enabled: true,
    leadMinutes: 30,
    quietStartMin: 22 * 60,
    quietEndMin: 7 * 60,
    timezone: tz,
  }));
}

/**
 * Redacted preview for a candidate event.
 *  - The source label is redacted (never echoes caller-provided identifiers).
 *  - `personal`/`restricted` events never expose their real title/notes — only
 *    a generic phrase.
 *  - `public` events show the title but with identifiers (email/phone/case IDs)
 *    stripped — a public classification is not a licence to leak PII.
 */
export function maskedPreview(
  event: { title: string; privacyClassification?: 'public' | 'personal' | 'restricted' },
  sourceLabel: string,
): string {
  const label = redactIdentifiers(sourceLabel);
  const cls = event.privacyClassification ?? 'personal';
  if (cls === 'public') return `${label}: ${redactIdentifiers(event.title)}`;
  return `${label}: You have an upcoming item`; // no private title/notes/links
}

/**
 * Preview using the trusted source-label enum keyed by CalendarSourceType — the
 * preferred entry point, since it cannot echo arbitrary caller-provided labels.
 */
export function maskedPreviewForSource(
  event: { title: string; privacyClassification?: 'public' | 'personal' | 'restricted' },
  sourceType: CalendarSourceType,
): string {
  return maskedPreview(event, SOURCE_LABELS[sourceType]);
}

export class ReminderPrefService {
  constructor(private store: KvStore = defaultKvStore()) {}

  /** Normalize a requester into an explicit actor (bare string ⇒ student). */
  private toActor(requester: Requester): Actor {
    return typeof requester === 'string' ? { subjectId: requester, role: 'student' } : requester;
  }

  /**
   * Authorize an actor against a student's private prefs. Only the owning
   * `student` may read/write. Wrong role ⇒ `unauthorized`; right role but wrong
   * subject ⇒ `forbidden` (cross-user).
   */
  private authorize(
    studentId: string,
    requester: Requester,
  ): { ok: true } | { ok: false; reason: 'forbidden' | 'unauthorized' } {
    if (!studentId) return { ok: false, reason: 'forbidden' };
    const actor = this.toActor(requester);
    if (actor.role !== 'student') return { ok: false, reason: 'unauthorized' };
    if (actor.subjectId !== studentId) return { ok: false, reason: 'forbidden' };
    return { ok: true };
  }

  /** Read the raw stored state only if it passes full schema validation, else null. */
  private validStored(studentId: string): ReminderPrefState | null {
    const raw = this.store.get<unknown>(key(studentId));
    return isValidState(raw, studentId) ? raw : null;
  }

  /**
   * Load a returning user's saved prefs, or seed safe defaults for a new user
   * (not persisted until saved). Malformed persisted state is NOT trusted and is
   * NOT overwritten — the caller gets safe defaults to render. An unsupported
   * timezone is sanitized to the default; `Mars/Phobos` is never seeded.
   */
  load(studentId: string, timezone: string = DEFAULT_TIMEZONE): ReminderPrefState {
    if (!studentId) return { studentId: '', prefs: [], updatedAt: '' };
    const valid = this.validStored(studentId);
    if (valid) return valid;
    return { studentId, prefs: defaultPrefs(timezone), updatedAt: '' };
  }

  /**
   * Idempotent upsert of one preference (keyed by sourceType + channel). Repeated
   * saves of the same key replace, never duplicate. Enforces authorization,
   * strict validation, ISO timestamps, optimistic concurrency and idempotency.
   */
  savePref(studentId: string, requester: Requester, pref: ReminderPref, now: string, opts?: SaveOptions): ReminderResult {
    const auth = this.authorize(studentId, requester);
    if (!auth.ok) return auth;
    const reason = validatePref(pref);
    if (reason) return { ok: false, reason };
    if (!isIsoTimestamp(now)) return { ok: false, reason: 'timestamp' };

    // Safe recovery: if the stored blob is corrupt, rebuild from defaults rather
    // than trusting malformed rows. Good, valid state is used as-is.
    const base: ReminderPrefState =
      this.validStored(studentId) ?? {
        studentId,
        prefs: defaultPrefs(pref.timezone),
        updatedAt: '',
        audit: [],
        seenKeys: [],
      };

    // Idempotent replay: a previously-applied key is a no-op with no new audit.
    const seen = base.seenKeys ?? [];
    if (opts?.idempotencyKey && seen.includes(opts.idempotencyKey)) {
      return { ok: true, state: base };
    }

    // Optimistic concurrency: reject a write built on a stale baseline.
    if (opts && opts.expectedUpdatedAt !== undefined) {
      const current = base.updatedAt || null;
      const expected = opts.expectedUpdatedAt ?? null;
      if (current !== expected) return { ok: false, reason: 'conflict' };
    }

    const others = base.prefs.filter((p) => !(p.sourceType === pref.sourceType && p.channel === pref.channel));
    const audit: AuditEntry[] = [
      ...(base.audit ?? []),
      { at: now, action: 'save', sourceType: pref.sourceType, channel: pref.channel },
    ];
    const seenKeys = opts?.idempotencyKey ? [...seen, opts.idempotencyKey] : [...seen];
    const state: ReminderPrefState = { studentId, prefs: [...others, pref], updatedAt: now, audit, seenKeys };
    this.store.set(key(studentId), state);
    return { ok: true, state };
  }

  /**
   * Read stored prefs. A denied actor (wrong role or cross-user) returns null
   * with no existence leak; malformed persisted state also returns null (never
   * trusted).
   */
  read(studentId: string, requester: Requester): ReminderPrefState | null {
    if (!this.authorize(studentId, requester).ok) return null;
    return this.validStored(studentId);
  }

  /** A source/channel is eligible for a preview only when an enabled pref exists. */
  isPreviewEligible(state: ReminderPrefState, sourceType: CalendarSourceType, channel: ReminderChannel): boolean {
    return state.prefs.some((p) => p.sourceType === sourceType && p.channel === channel && p.enabled);
  }
}
