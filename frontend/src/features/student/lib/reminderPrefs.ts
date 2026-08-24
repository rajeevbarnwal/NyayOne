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
import type { KvStore } from '../../../lib/kvStore';
import {
  STUDENT_REMINDER_PREF_STORAGE_KEY_PREFIX,
  studentReminderPrefStorageKey,
} from './studentLegacyStorage';
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
  | 'shape'
  | 'idempotency_key'
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

export const REMINDER_PREF_STORAGE_KEY_PREFIX = STUDENT_REMINDER_PREF_STORAGE_KEY_PREFIX;
const key = studentReminderPrefStorageKey;

// ---- Identifier redaction (applied to EVERY preview, including `public`) ----
const EMAIL_RE = /[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}/g;
// Phone: an optional +, then 8+ digits possibly separated by space/()-.
const PHONE_RE = /\+?\d(?:[\d\s().-]{6,})\d/g;
// Indian court/case citations with a parenthetical class, e.g. W.P.(C) 123/2026, SLP(C) 456/2023.
const LEGAL_PAREN_RE = /\b[A-Za-z][A-Za-z.]*\([A-Za-z]{1,5}\)\s?\d{1,6}\/\d{2,4}\b/g;
// Dotted-abbreviation citations, e.g. Crl.A. 45/2025, C.S. 12/2024, O.M.P. 7/2023.
const LEGAL_DOTTED_RE = /\b(?:[A-Za-z]{1,5}\.){1,4}[A-Za-z]{0,4}\.?\s?\d{1,6}\/\d{2,4}\b/g;
// CNR (Case Number Record): 16 chars, e.g. DLHC010012342026 — case-insensitive.
const CNR_RE = /\b[A-Za-z]{4}\d{2}[A-Za-z0-9]{6}\d{4}\b/gi;
// Case / client / event identifiers, e.g. EV-99177, CASE-1234, CL-0007.
const ID_RE = /\b[A-Za-z]{2,}-\d{3,}\b/g;
// Bare docket / diary number in <number>/<year> form, e.g. 123/2026 (last, as a net).
const DOCKET_RE = /\b\d{1,6}\/\d{2,4}\b/g;
const REDACTED = '[redacted]';

/**
 * Strip identifiers from arbitrary text: email, phone, Indian legal case-number
 * formats (parenthetical + dotted citations, CNR), hyphenated case/client/event
 * IDs, and bare docket/diary <number>/<year> tokens. Applied to EVERY preview,
 * so a `public` classification is never a licence to leak PII.
 */
export function redactIdentifiers(text: string): string {
  if (typeof text !== 'string' || !text) return '';
  return text
    .replace(EMAIL_RE, REDACTED)
    .replace(PHONE_RE, REDACTED)
    .replace(LEGAL_PAREN_RE, REDACTED)
    .replace(LEGAL_DOTTED_RE, REDACTED)
    .replace(CNR_RE, REDACTED)
    .replace(ID_RE, REDACTED)
    .replace(DOCKET_RE, REDACTED);
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

function isLeapYear(year: number): boolean {
  return (year % 4 === 0 && year % 100 !== 0) || year % 400 === 0;
}

/**
 * True when `value` is a real, strictly valid ISO-8601 timestamp. Unlike
 * `Date.parse`, this rejects impossible calendar dates (e.g. 2026-02-30, which
 * `Date.parse` silently normalizes to March 2) by validating every component:
 * month 1–12, day within the actual month length (leap-year aware), time fields
 * in range, and a valid timezone designator/offset.
 */
export function isIsoTimestamp(value: unknown): value is string {
  if (typeof value !== 'string' || !value) return false;
  const m = /^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2}):(\d{2})(?:\.(\d{1,3}))?(Z|[+-]\d{2}:\d{2})$/.exec(value);
  if (!m) return false;
  const year = Number(m[1]);
  const month = Number(m[2]);
  const day = Number(m[3]);
  const hour = Number(m[4]);
  const minute = Number(m[5]);
  const second = Number(m[6]);
  if (month < 1 || month > 12) return false;
  if (hour > 23 || minute > 59 || second > 59) return false;
  const daysInMonth = [31, isLeapYear(year) ? 29 : 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31][month - 1];
  if (day < 1 || day > daysInMonth) return false;
  const offset = m[8];
  if (offset !== 'Z') {
    const offHour = Number(offset.slice(1, 3));
    const offMin = Number(offset.slice(4, 6));
    // Valid UTC offsets span ±14:00. At the ±14 boundary the minutes must be 00,
    // so +14:00/-14:00 pass but +14:01 and -14:30 are rejected.
    if (offHour > 14) return false;
    if (offHour === 14 && offMin !== 0) return false;
    if (offMin > 59) return false;
  }
  return true;
}

/** The exact, exhaustive set of keys a persisted ReminderPref row may carry. */
const PREF_KEYS: readonly string[] = [
  'sourceType', 'channel', 'enabled', 'leadMinutes', 'quietStartMin', 'quietEndMin', 'timezone',
];

/** Validate a preference; returns null when valid or a typed reason when not. */
export function validatePref(input: Partial<ReminderPref>): ReminderErrorReason | null {
  if (!input || typeof input !== 'object' || Array.isArray(input)) return 'shape';
  // Exact shape: reject any unknown field (e.g. an injected `privateNarrative`)
  // even when the required preference fields are otherwise valid.
  for (const k of Object.keys(input)) if (!PREF_KEYS.includes(k)) return 'shape';
  if (!input.sourceType || !CALENDAR_SOURCE_TYPES.includes(input.sourceType)) return 'source';
  if (!input.channel || !(REMINDER_CHANNELS as readonly string[]).includes(input.channel)) return 'channel';
  if (typeof input.enabled !== 'boolean') return 'enabled';
  if (typeof input.leadMinutes !== 'number' || !REMINDER_LEAD_MINUTES.includes(input.leadMinutes)) return 'lead_time';
  const inRange = (n: unknown) => typeof n === 'number' && Number.isInteger(n) && n >= 0 && n < 1440;
  if (!inRange(input.quietStartMin) || !inRange(input.quietEndMin)) return 'quiet_range';
  if (!isValidTimezone(input.timezone)) return 'timezone';
  return null;
}

/** Upper bounds guarding against unreasonably large persisted state. */
const MAX_IDEMPOTENCY_KEY_LEN = 200;
const MAX_COLLECTION_LEN = 10000;
const AUDIT_ENTRY_KEYS = ['at', 'action', 'sourceType', 'channel'] as const;

/** Audit entries are metadata-only: exact safe shape, no extra/narrative fields. */
export function isValidAuditEntry(value: unknown): value is AuditEntry {
  if (!value || typeof value !== 'object' || Array.isArray(value)) return false;
  const keys = Object.keys(value as Record<string, unknown>);
  if (keys.length !== AUDIT_ENTRY_KEYS.length || !keys.every((k) => (AUDIT_ENTRY_KEYS as readonly string[]).includes(k))) {
    return false;
  }
  const e = value as Record<string, unknown>;
  if (!isIsoTimestamp(e.at)) return false;
  if (e.action !== 'save') return false;
  if (typeof e.sourceType !== 'string' || !CALENDAR_SOURCE_TYPES.includes(e.sourceType as CalendarSourceType)) return false;
  if (typeof e.channel !== 'string' || !(REMINDER_CHANNELS as readonly string[]).includes(e.channel)) return false;
  return true;
}

/** An idempotency key must be a non-empty (non-whitespace), bounded string. */
export function isValidSeenKey(value: unknown): value is string {
  return typeof value === 'string' && value.trim().length > 0 && value.length <= MAX_IDEMPOTENCY_KEY_LEN;
}

/** The exact, exhaustive set of top-level keys a persisted state blob may carry. */
const STATE_KEYS: readonly string[] = ['studentId', 'prefs', 'updatedAt', 'audit', 'seenKeys'];

/**
 * Validate a full persisted state blob before trusting it. Guards ownership,
 * timestamp, every pref row, uniqueness of (sourceType, channel), and the
 * optional audit/seenKeys shapes (metadata-only entries, bounded string keys,
 * bounded collection sizes). Anything malformed → not trusted.
 */
export function isValidState(value: unknown, studentId: string): value is ReminderPrefState {
  if (!value || typeof value !== 'object' || Array.isArray(value)) return false;
  const s = value as Record<string, unknown>;
  // Exact top-level shape: reject any unknown field (e.g. an injected
  // `privateCaseNotes`); only the documented optional audit/seenKeys are allowed.
  for (const k of Object.keys(s)) if (!STATE_KEYS.includes(k)) return false;
  if (s.studentId !== studentId) return false;
  if (!isIsoTimestamp(s.updatedAt)) return false;
  if (!Array.isArray(s.prefs) || s.prefs.length > MAX_COLLECTION_LEN) return false;
  const pairs = new Set<string>();
  for (const p of s.prefs) {
    if (!p || typeof p !== 'object') return false;
    if (validatePref(p as Partial<ReminderPref>) !== null) return false;
    const pp = p as ReminderPref;
    const pairId = `${pp.sourceType}|${pp.channel}`;
    if (pairs.has(pairId)) return false; // duplicate (sourceType, channel) row
    pairs.add(pairId);
  }
  if (s.audit !== undefined) {
    if (!Array.isArray(s.audit) || s.audit.length > MAX_COLLECTION_LEN) return false;
    for (const entry of s.audit) if (!isValidAuditEntry(entry)) return false;
  }
  if (s.seenKeys !== undefined) {
    if (!Array.isArray(s.seenKeys) || s.seenKeys.length > MAX_COLLECTION_LEN) return false;
    for (const k of s.seenKeys) if (!isValidSeenKey(k)) return false;
  }
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

/** The trusted, closed set of source labels (values of SOURCE_LABELS). */
const TRUSTED_LABELS: ReadonlySet<string> = new Set(Object.values(SOURCE_LABELS));
/** Neutral fallback used when a caller passes a non-trusted label. */
const NEUTRAL_LABEL = 'Reminder';

/**
 * Preview using the trusted source-label enum keyed by CalendarSourceType. This
 * is the CANONICAL, preferred entry point for all production preview generation
 * (calendar/reminders screens) — it cannot echo arbitrary caller-supplied text.
 */
export function maskedPreviewForSource(
  event: { title: string; privacyClassification?: 'public' | 'personal' | 'restricted' },
  sourceType: CalendarSourceType,
): string {
  return renderPreview(event, SOURCE_LABELS[sourceType]);
}

/**
 * Redacted preview from a raw label string. Retained for compatibility, but the
 * label is trust-gated: only a value from the SOURCE_LABELS enum is echoed; any
 * other caller-supplied string (e.g. `"Confidential client Jane Doe"`) is
 * replaced with a neutral label so arbitrary sensitive text can never leak.
 * Prefer maskedPreviewForSource in production.
 */
export function maskedPreview(
  event: { title: string; privacyClassification?: 'public' | 'personal' | 'restricted' },
  sourceLabel: string,
): string {
  const trusted = TRUSTED_LABELS.has(sourceLabel) ? sourceLabel : NEUTRAL_LABEL;
  return renderPreview(event, trusted);
}

/** Internal: build the redacted preview string from an already-trusted label. */
function renderPreview(
  event: { title: string; privacyClassification?: 'public' | 'personal' | 'restricted' },
  trustedLabel: string,
): string {
  const label = redactIdentifiers(trustedLabel);
  const cls = event.privacyClassification ?? 'personal';
  if (cls === 'public') return `${label}: ${redactIdentifiers(event.title)}`;
  return `${label}: You have an upcoming item`; // no private title/notes/links
}

export class ReminderPrefService {
  constructor(private store: KvStore) {}

  /**
   * Normalize a requester into an explicit actor. A malformed runtime actor
   * (null, array, non-object, empty/absent subjectId, non-string role) yields
   * null — the caller maps that to a typed authorization failure. Never throws.
   */
  private toActor(requester: Requester): Actor | null {
    if (typeof requester === 'string') {
      return requester.length > 0 ? { subjectId: requester, role: 'student' } : null;
    }
    if (!requester || typeof requester !== 'object' || Array.isArray(requester)) return null;
    const r = requester as unknown as Record<string, unknown>;
    if (typeof r.subjectId !== 'string' || r.subjectId.length === 0) return null;
    if (typeof r.role !== 'string') return null;
    return { subjectId: r.subjectId, role: r.role as StudentRole };
  }

  /**
   * Authorize an actor against a student's private prefs. Only the owning
   * `student` may read/write. A malformed actor or unknown/non-owner role ⇒
   * `unauthorized` (never throws, never leaks existence); a valid `student`
   * acting on someone else's data ⇒ `forbidden` (cross-user).
   */
  private authorize(
    studentId: string,
    requester: Requester,
  ): { ok: true } | { ok: false; reason: 'forbidden' | 'unauthorized' } {
    if (!studentId || typeof studentId !== 'string') return { ok: false, reason: 'unauthorized' };
    const actor = this.toActor(requester);
    if (!actor) return { ok: false, reason: 'unauthorized' };
    if (!(STUDENT_ROLES as readonly string[]).includes(actor.role)) return { ok: false, reason: 'unauthorized' };
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
    // Validate an incoming idempotency key BEFORE any mutation: a non-string,
    // empty/whitespace-only or over-long key is a typed failure, never silently
    // treated as absent — and nothing (state or audit) is written on failure.
    if (opts && opts.idempotencyKey !== undefined && !isValidSeenKey(opts.idempotencyKey)) {
      return { ok: false, reason: 'idempotency_key' };
    }

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
