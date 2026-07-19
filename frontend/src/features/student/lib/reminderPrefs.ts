/**
 * S19.2 — Reminder Preferences and Privacy-Safe Notifications (SAATHI-290/292).
 *
 * Pure, framework-free domain for user-scoped reminder preferences and the
 * privacy-safe notification-preview policy. Consumes the S19.1 calendar source
 * contract (CalendarSourceType) from `./calendar`. No live SMS/email/push is
 * dispatched here — the "preview" is a redacted, in-app representation only.
 *
 * Guardrails (from the Jira Developer Execution Spec):
 *  - Preferences are scoped by student, source type and channel.
 *  - Persistence is idempotent (upsert by source+channel — never duplicates).
 *  - Previews mask private titles/notes and never expose evidence links or
 *    private identifiers.
 *  - Unsupported channel / timezone / lead-time / quiet-hours are typed errors.
 */
import { defaultKvStore, type KvStore } from '../../../lib/kvStore';
import { CALENDAR_SOURCE_TYPES, type CalendarSourceType } from './calendar';

export const REMINDER_CHANNELS = ['in_app', 'email_digest', 'push'] as const;
export type ReminderChannel = (typeof REMINDER_CHANNELS)[number];

/** Allowed lead times in minutes before an event (0 = at start). */
export const REMINDER_LEAD_MINUTES: readonly number[] = [0, 10, 30, 60, 120, 24 * 60];
export const DEFAULT_TIMEZONE = 'Asia/Kolkata';
export const NO_LIVE_DELIVERY_NOTICE =
  'Reminders preview in-app only; no live SMS, email or push is sent (integration pending).';

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
export interface ReminderPrefState {
  readonly studentId: string;
  readonly prefs: readonly ReminderPref[];
  readonly updatedAt: string;
}

export type ReminderErrorReason = 'source' | 'channel' | 'lead_time' | 'quiet_range' | 'timezone' | 'forbidden';
export type ReminderResult = { ok: true; state: ReminderPrefState } | { ok: false; reason: ReminderErrorReason };

const key = (studentId: string) => `ls-reminder-prefs-${studentId}`;

/** True when `tz` is a valid IANA timezone the runtime accepts. */
export function isValidTimezone(tz: string): boolean {
  if (!tz || typeof tz !== 'string') return false;
  try {
    new Intl.DateTimeFormat('en-US', { timeZone: tz });
    return true;
  } catch {
    return false;
  }
}

/** Validate a preference; returns null when valid or a typed reason when not. */
export function validatePref(input: Partial<ReminderPref>): ReminderErrorReason | null {
  if (!input.sourceType || !CALENDAR_SOURCE_TYPES.includes(input.sourceType)) return 'source';
  if (!input.channel || !(REMINDER_CHANNELS as readonly string[]).includes(input.channel)) return 'channel';
  if (typeof input.leadMinutes !== 'number' || !REMINDER_LEAD_MINUTES.includes(input.leadMinutes)) return 'lead_time';
  const inRange = (n: unknown) => typeof n === 'number' && Number.isInteger(n) && n >= 0 && n < 1440;
  if (!inRange(input.quietStartMin) || !inRange(input.quietEndMin)) return 'quiet_range';
  if (!input.timezone || !isValidTimezone(input.timezone)) return 'timezone';
  return null;
}

/** Safe defaults for a new user: in-app on for every source, 30-min lead, 22:00–07:00 quiet. */
export function defaultPrefs(timezone: string = DEFAULT_TIMEZONE): ReminderPref[] {
  return CALENDAR_SOURCE_TYPES.map((sourceType) => ({
    sourceType,
    channel: 'in_app' as ReminderChannel,
    enabled: true,
    leadMinutes: 30,
    quietStartMin: 22 * 60,
    quietEndMin: 7 * 60,
    timezone,
  }));
}

/**
 * Redacted preview for a candidate event. Private/restricted events never expose
 * their real title, notes, evidence links or identifiers — only a generic label
 * and the (already non-sensitive) source label.
 */
export function maskedPreview(
  event: { title: string; privacyClassification?: 'public' | 'personal' | 'restricted' },
  sourceLabel: string,
): string {
  const cls = event.privacyClassification ?? 'personal';
  if (cls === 'public') return `${sourceLabel}: ${event.title}`;
  return `${sourceLabel}: You have an upcoming item`; // no private title/notes/links
}

export class ReminderPrefService {
  constructor(private store: KvStore = defaultKvStore()) {}

  /** Load a returning user's saved prefs, or seed defaults for a new user (not persisted until saved). */
  load(studentId: string, timezone: string = DEFAULT_TIMEZONE): ReminderPrefState {
    if (!studentId) return { studentId: '', prefs: [], updatedAt: '' };
    const saved = this.store.get<ReminderPrefState>(key(studentId));
    if (saved && saved.studentId === studentId) return saved;
    return { studentId, prefs: defaultPrefs(timezone), updatedAt: '' };
  }

  /**
   * Idempotent upsert of one preference (keyed by sourceType + channel). Repeated
   * saves of the same key replace, never duplicate. Cross-user writes are refused.
   */
  savePref(studentId: string, requester: string, pref: ReminderPref, now: string): ReminderResult {
    if (!studentId || requester !== studentId) return { ok: false, reason: 'forbidden' };
    const reason = validatePref(pref);
    if (reason) return { ok: false, reason };
    const current = this.load(studentId, pref.timezone);
    const others = current.prefs.filter((p) => !(p.sourceType === pref.sourceType && p.channel === pref.channel));
    const state: ReminderPrefState = { studentId, prefs: [...others, pref], updatedAt: now };
    this.store.set(key(studentId), state);
    return { ok: true, state };
  }

  /** Read another/own user's stored prefs; a cross-user read returns null (no existence leak). */
  read(studentId: string, requester: string): ReminderPrefState | null {
    if (!studentId || requester !== studentId) return null;
    return this.store.get<ReminderPrefState>(key(studentId));
  }

  /** A source/channel is eligible for a preview only when an enabled pref exists. */
  isPreviewEligible(state: ReminderPrefState, sourceType: CalendarSourceType, channel: ReminderChannel): boolean {
    return state.prefs.some((p) => p.sourceType === sourceType && p.channel === channel && p.enabled);
  }
}
