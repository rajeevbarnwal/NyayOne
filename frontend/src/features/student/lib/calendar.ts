/**
 * S19.1 — Cross-module calendar aggregation (SAATHI-285 / service SAATHI-287).
 *
 * One stable normalized calendar-event contract that every R1 source module is
 * adapted into (internships, exam-prep, clinical-hours, community, tutoring,
 * moot, reminders). The read model is user-scoped and deterministic:
 *   - dedupe by stable (source_type + source_id),
 *   - sort by starts_at then a stable secondary key (id),
 *   - partial-source failures never block healthy sources,
 *   - previews expose ONLY non-restricted fields (never notes, evidence URLs,
 *     verifier identities or other private identifiers).
 *
 * Timezone handling is explicit and DST-safe via Intl (no hand-rolled offsets).
 * No live external integrations — sources are local adapters over in-app data
 * plus stable fixtures for modules that do not yet emit datetimes.
 *
 * TCs: TC-285-01 aggregate+sort · 02 filter+persist · 03 dedupe · 04 timezone
 * boundary · 05 loading/empty/partial-error · 06 deep link · 07 no restricted
 * leakage in previews.
 */
import { defaultKvStore, type KvStore } from '../../../lib/kvStore';
import { formatDateDDMMYYYY } from '../../../lib/dateTime';

// --- contract ---------------------------------------------------------------

export type CalendarSourceType =
  | 'internship'
  | 'exam'
  | 'clinical'
  | 'community'
  | 'tutoring'
  | 'moot'
  | 'reminder';

export const CALENDAR_SOURCE_TYPES: readonly CalendarSourceType[] = [
  'internship', 'exam', 'clinical', 'community', 'tutoring', 'moot', 'reminder',
];

export const SOURCE_LABELS: Record<CalendarSourceType, string> = {
  internship: 'Internships',
  exam: 'Exam prep',
  clinical: 'Clinical hours',
  community: 'Community',
  tutoring: 'Tutoring',
  moot: 'Moot',
  reminder: 'Reminders',
};

/** Canonical in-app route for each source's "Go to source" deep link (real S-NN screens). */
export const SOURCE_ROUTE: Record<CalendarSourceType, string> = {
  internship: '/s-20',
  exam: '/s-55',
  clinical: '/s-61',
  community: '/s-50',
  tutoring: '/s-31',
  moot: '/s-90',
  reminder: '/s-90',
};

/** Supported IANA timezones for the selector (validated via Intl on use). */
export const TIMEZONE_OPTIONS: readonly string[] = [
  'Asia/Kolkata', 'UTC', 'Asia/Dubai', 'Europe/London', 'America/New_York', 'Asia/Singapore',
];

export type CalendarEventStatus = 'scheduled' | 'deadline' | 'tentative' | 'done';
export type PrivacyClassification = 'public' | 'personal' | 'restricted';

/** The single normalized event contract consumed by S19.1/2/3. */
export interface CalendarEvent {
  readonly id: string; // stable derived id: `${sourceType}:${sourceId}`
  readonly sourceType: CalendarSourceType;
  readonly sourceId: string;
  readonly ownerId: string; // student who owns this event (authorization)
  readonly title: string; // already redacted of restricted identifiers
  readonly startsAt: string; // ISO-8601 instant (UTC, `Z`)
  readonly endsAt: string; // ISO-8601 instant (UTC, `Z`)
  readonly timezone: string; // IANA tz for display, e.g. 'Asia/Kolkata'
  readonly status: CalendarEventStatus;
  readonly privacyClassification: PrivacyClassification;
  readonly sourceUrl: string; // in-app deep link only (starts with '/')
  readonly updatedAt: string; // ISO-8601 instant
}

/** Only these fields may ever be shown in a preview/list cell. */
export interface CalendarEventPreview {
  readonly id: string;
  readonly sourceType: CalendarSourceType;
  readonly title: string;
  readonly startsAt: string;
  readonly endsAt: string;
  readonly timezone: string;
  readonly status: CalendarEventStatus;
}

/** Raw record an adapter receives (kept minimal + typed). */
export interface RawSourceRecord {
  readonly sourceId: string;
  readonly ownerId?: string; // defaults to the adapter's owner
  readonly title: string;
  readonly startsAt: string;
  readonly endsAt?: string;
  readonly timezone?: string;
  readonly status?: CalendarEventStatus;
  readonly privacyClassification?: PrivacyClassification;
  readonly sourceUrl: string;
  readonly updatedAt?: string;
}

/** Result of running one source adapter — supports partial failure (TC-285-05). */
export interface SourceResult {
  readonly sourceType: CalendarSourceType;
  readonly ok: boolean;
  readonly events: readonly CalendarEvent[];
  readonly error?: string;
}

export const DEFAULT_TZ = 'Asia/Kolkata';
const RESTRICTED_KEY_RE = /(note|notes|evidence|verifier|email|phone|identity|author|private|url)/i;

// --- typed errors -----------------------------------------------------------

export type CalendarErrorCode =
  | 'invalid_datetime'
  | 'invalid_timezone'
  | 'end_before_start'
  | 'invalid_url'
  | 'not_found'
  | 'forbidden';
export class CalendarError extends Error {
  readonly code: CalendarErrorCode;
  constructor(code: CalendarErrorCode, message?: string) {
    super(message ?? code);
    this.name = 'CalendarError';
    this.code = code;
  }
}

/** Validate an IANA timezone via Intl; throws on anything Intl rejects. */
export function isValidTimezone(tz: string): boolean {
  try {
    new Intl.DateTimeFormat('en-US', { timeZone: tz });
    return true;
  } catch {
    return false;
  }
}

// --- privacy redaction (TC-285-07) ------------------------------------------
// Redact identifier-bearing substrings that must never appear in previews, even
// when embedded in a title. Conservative patterns preserve legitimate titles
// (e.g. "CLAT mock test 3", "Vidhi interview").
const REDACTION_PATTERNS: readonly RegExp[] = [
  /[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}/g, // email
  /\bhttps?:\/\/\S+/gi, // external URL
  /\b(?:\+?\d[\d ()-]{8,}\d)\b/g, // phone-like (>=10 digits w/ separators)
  /\bev(?:idence)?[-_:#]?[A-Za-z0-9]{4,}\b/gi, // evidence identifiers
];
export function containsRestricted(text: string): boolean {
  return REDACTION_PATTERNS.some((re) => { re.lastIndex = 0; return re.test(text); });
}
export function redactRestricted(text: string): string {
  let out = text;
  for (const re of REDACTION_PATTERNS) { re.lastIndex = 0; out = out.replace(re, '[redacted]'); }
  return out;
}

// --- helpers ----------------------------------------------------------------

export function eventId(sourceType: CalendarSourceType, sourceId: string): string {
  return `${sourceType}:${sourceId}`;
}

function isIso(s: string): boolean {
  const t = Date.parse(s);
  return Number.isFinite(t);
}

/**
 * Normalize a raw source record into the stable contract. Throws typed errors.
 * Strict validation (TC-285 remediation): invalid startsAt/endsAt/updatedAt are
 * rejected (an explicitly-supplied invalid endsAt is NEVER silently replaced),
 * the IANA timezone is validated, endsAt earlier than startsAt is rejected, and
 * the title is redacted of restricted identifiers before it can reach a preview.
 */
export function normalizeEvent(
  sourceType: CalendarSourceType,
  raw: RawSourceRecord,
  ownerId = 'self',
): CalendarEvent {
  if (!isIso(raw.startsAt)) throw new CalendarError('invalid_datetime', `bad startsAt for ${raw.sourceId}`);
  const startsAt = new Date(raw.startsAt).toISOString();

  // endsAt: default to startsAt only when NOT supplied; a supplied bad value fails.
  let endsAt = startsAt;
  if (raw.endsAt !== undefined) {
    if (!isIso(raw.endsAt)) throw new CalendarError('invalid_datetime', `bad endsAt for ${raw.sourceId}`);
    endsAt = new Date(raw.endsAt).toISOString();
    if (Date.parse(endsAt) < Date.parse(startsAt)) {
      throw new CalendarError('end_before_start', `endsAt precedes startsAt for ${raw.sourceId}`);
    }
  }

  if (raw.updatedAt !== undefined && !isIso(raw.updatedAt)) {
    throw new CalendarError('invalid_datetime', `bad updatedAt for ${raw.sourceId}`);
  }
  const updatedAt = raw.updatedAt !== undefined ? new Date(raw.updatedAt).toISOString() : startsAt;

  const timezone = raw.timezone ?? DEFAULT_TZ;
  if (!isValidTimezone(timezone)) throw new CalendarError('invalid_timezone', `bad timezone for ${raw.sourceId}`);

  // Deep links must be in-app; never an external or private URL (TC-285-07).
  if (!raw.sourceUrl.startsWith('/') || /^https?:/i.test(raw.sourceUrl)) {
    throw new CalendarError('invalid_url', `source_url must be in-app for ${raw.sourceId}`);
  }

  return {
    id: eventId(sourceType, raw.sourceId),
    sourceType,
    sourceId: raw.sourceId,
    ownerId: raw.ownerId ?? ownerId,
    title: redactRestricted(raw.title), // TC-285-07: redact even if embedded in title
    startsAt,
    endsAt,
    timezone,
    status: raw.status ?? 'scheduled',
    privacyClassification: raw.privacyClassification ?? 'personal',
    sourceUrl: raw.sourceUrl,
    updatedAt,
  };
}

/** A generic adapter: normalize a source's raw records, isolating failures. */
export function runAdapter(
  sourceType: CalendarSourceType,
  load: () => readonly RawSourceRecord[],
  ownerId = 'self',
): SourceResult {
  try {
    const events = load().map((r) => normalizeEvent(sourceType, r, ownerId));
    return { sourceType, ok: true, events };
  } catch (e) {
    return { sourceType, ok: false, events: [], error: e instanceof Error ? e.message : 'adapter_failed' };
  }
}

/** Dedupe by stable id, keeping the first occurrence (TC-285-03). */
export function dedupeEvents(events: readonly CalendarEvent[]): CalendarEvent[] {
  const seen = new Set<string>();
  const out: CalendarEvent[] = [];
  for (const e of events) {
    if (seen.has(e.id)) continue;
    seen.add(e.id);
    out.push(e);
  }
  return out;
}

/** Deterministic chronological sort; stable secondary key = id (TC-285-01). */
export function sortEvents(events: readonly CalendarEvent[]): CalendarEvent[] {
  return [...events].sort((a, b) => {
    const ta = Date.parse(a.startsAt);
    const tb = Date.parse(b.startsAt);
    if (ta !== tb) return ta - tb;
    return a.id < b.id ? -1 : a.id > b.id ? 1 : 0;
  });
}

export interface AggregateResult {
  readonly events: CalendarEvent[];
  readonly failedSources: readonly CalendarSourceType[];
  readonly okSources: readonly CalendarSourceType[];
}

/** Merge source results: dedupe + sort, and surface partial failures. */
export function aggregate(results: readonly SourceResult[]): AggregateResult {
  const all: CalendarEvent[] = [];
  const failed: CalendarSourceType[] = [];
  const ok: CalendarSourceType[] = [];
  for (const r of results) {
    if (r.ok) ok.push(r.sourceType);
    else failed.push(r.sourceType);
    all.push(...r.events);
  }
  return { events: sortEvents(dedupeEvents(all)), failedSources: failed, okSources: ok };
}

// --- explicit view-state + retry contract (TC-285-05) -----------------------

export type CalendarViewStatus = 'loading' | 'empty' | 'success' | 'partial' | 'error';

/** A named source loader; the unit of aggregation, failure and retry. */
export interface SourceLoader {
  readonly sourceType: CalendarSourceType;
  readonly load: () => readonly RawSourceRecord[];
  readonly ownerId?: string;
}

export function runLoaders(loaders: readonly SourceLoader[]): SourceResult[] {
  return loaders.map((l) => runAdapter(l.sourceType, l.load, l.ownerId ?? 'self'));
}

/** Derive the explicit view status from source results (loading is caller-driven). */
export function deriveStatus(
  results: readonly SourceResult[],
  opts: { loading?: boolean } = {},
): CalendarViewStatus {
  if (opts.loading) return 'loading';
  if (results.length === 0) return 'empty';
  const failed = results.filter((r) => !r.ok).length;
  if (failed === results.length) return 'error';
  if (failed > 0) return 'partial';
  return results.some((r) => r.events.length > 0) ? 'success' : 'empty';
}

/**
 * Retry ONLY the failed sources, preserving already-healthy results/events
 * (TC-285-05). Healthy sources are never re-run and their events never dropped.
 */
export function retryFailed(
  prev: readonly SourceResult[],
  loaders: readonly SourceLoader[],
): SourceResult[] {
  const byType = new Map(loaders.map((l) => [l.sourceType, l] as const));
  return prev.map((r) => {
    if (r.ok) return r;
    const l = byType.get(r.sourceType);
    return l ? runAdapter(l.sourceType, l.load, l.ownerId ?? 'self') : r;
  });
}

// --- timezone-aware date boundary (TC-285-04) -------------------------------

/** Local calendar day (yyyy-mm-dd) of an instant in a given IANA timezone. */
export function localDateKey(iso: string, timezone: string): string {
  const d = new Date(iso);
  // en-CA yields yyyy-mm-dd; timeZone applies the correct wall-clock day.
  return new Intl.DateTimeFormat('en-CA', {
    timeZone: timezone,
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
  }).format(d);
}

/** Local wall-clock day in DD-MM-YYYY format for UI rendering. */
export function localDateDisplay(iso: string, timezone: string): string {
  return formatDateDDMMYYYY(localDateKey(iso, timezone));
}

/** Local wall-clock hh:mm AM/PM of an instant in a timezone (12h). */
export function localTime(iso: string, timezone: string): string {
  return new Intl.DateTimeFormat('en-US', {
    timeZone: timezone,
    hour: '2-digit',
    minute: '2-digit',
    hour12: true,
  }).format(new Date(iso));
}

// --- filters ----------------------------------------------------------------

export interface CalendarFilters {
  readonly sources: readonly CalendarSourceType[]; // empty = all
  readonly from: string | null; // yyyy-mm-dd inclusive (local)
  readonly to: string | null; // yyyy-mm-dd inclusive (local)
  readonly timezone: string;
}

export function defaultFilters(): CalendarFilters {
  return { sources: [], from: null, to: null, timezone: DEFAULT_TZ };
}

export function filterEvents(events: readonly CalendarEvent[], f: CalendarFilters): CalendarEvent[] {
  const set = new Set(f.sources);
  return events.filter((e) => {
    if (set.size > 0 && !set.has(e.sourceType)) return false;
    if (f.from || f.to) {
      const day = localDateKey(e.startsAt, f.timezone);
      if (f.from && day < f.from) return false;
      if (f.to && day > f.to) return false;
    }
    return true;
  });
}

// --- privacy-safe preview (TC-285-07) ---------------------------------------

/** Reduce an event to the ONLY fields allowed in list/preview surfaces. */
export function toPreview(e: CalendarEvent): CalendarEventPreview {
  return {
    id: e.id,
    sourceType: e.sourceType,
    title: e.title,
    startsAt: e.startsAt,
    endsAt: e.endsAt,
    timezone: e.timezone,
    status: e.status,
  };
}

/** Guard used by tests + adapters: a preview must carry no restricted keys. */
export function previewLeaksRestricted(p: CalendarEventPreview): boolean {
  return Object.keys(p).some((k) => RESTRICTED_KEY_RE.test(k));
}

// --- deep link (TC-285-06, ownership-aware) ---------------------------------

export type DeepLinkResult =
  | { readonly ok: true; readonly event: CalendarEvent }
  | { readonly ok: false; readonly reason: 'not_found' | 'forbidden' };

/**
 * Resolve a deep link with ownership authorization. Knowing an id is NOT enough:
 * personal/restricted events resolve only for their owner; public events resolve
 * for anyone. Missing → not_found; someone else's private record → forbidden.
 */
export function resolveDeepLink(
  events: readonly CalendarEvent[],
  id: string,
  requesterId: string,
): DeepLinkResult {
  const e = events.find((x) => x.id === id);
  if (!e) return { ok: false, reason: 'not_found' };
  if (e.privacyClassification !== 'public' && e.ownerId !== requesterId) {
    return { ok: false, reason: 'forbidden' };
  }
  return { ok: true, event: e };
}

// --- persistence (user-scoped filters; TC-285-02 refresh persistence) -------

const filtersKey = (userId: string) => `ls-cal-filters-${userId}`;

// --- date-range filter validation (S-90 From/To) ----------------------------

export type DateRangeError = 'from_after_to' | 'invalid_date';
/** Returns null when valid, else a typed error code. Empty from/to are allowed (open range). */
export function validateDateRange(from: string | null, to: string | null): DateRangeError | null {
  const ymd = /^\d{4}-\d{2}-\d{2}$/;
  if (from && !ymd.test(from)) return 'invalid_date';
  if (to && !ymd.test(to)) return 'invalid_date';
  if (from && to && from > to) return 'from_after_to';
  return null;
}

// --- personal event (S-91) ---------------------------------------------------

export const PERSONAL_EVENT_TYPES = ['study', 'deadline', 'meeting', 'reminder', 'other'] as const;
export type PersonalEventType = (typeof PERSONAL_EVENT_TYPES)[number];

/**
 * Canonical human labels for the S-91 manual event types, per Jira Product
 * decision 12314: Study, Deadline, Meeting, Reminder, Other. These are the real
 * rendered/accessible names; the enum VALUES above stay lowercase for the
 * persistence contract. (Exam and Moot are source classifications, not manual
 * personal-event types, so they are intentionally absent here.)
 */
export const PERSONAL_EVENT_TYPE_LABELS: Record<PersonalEventType, string> = {
  study: 'Study',
  deadline: 'Deadline',
  meeting: 'Meeting',
  reminder: 'Reminder',
  other: 'Other',
};

export interface PersonalEventInput {
  readonly title: string;
  readonly date: string; // yyyy-mm-dd (wall date in `timezone`)
  readonly time: string; // HH:mm (wall time in `timezone`)
  readonly type: PersonalEventType;
  readonly timezone: string;
}

export type PersonalEventErrorCode = 'title_required' | 'invalid_date' | 'invalid_time' | 'invalid_type' | 'invalid_timezone';
export class PersonalEventError extends Error {
  readonly code: PersonalEventErrorCode;
  constructor(code: PersonalEventErrorCode, message?: string) {
    super(message ?? code);
    this.name = 'PersonalEventError';
    this.code = code;
  }
}

export function validatePersonalEvent(i: PersonalEventInput): void {
  if (!i.title || !i.title.trim()) throw new PersonalEventError('title_required');
  if (!/^\d{4}-\d{2}-\d{2}$/.test(i.date) || Number.isNaN(Date.parse(`${i.date}T00:00:00Z`))) {
    throw new PersonalEventError('invalid_date');
  }
  if (!/^\d{2}:\d{2}$/.test(i.time)) throw new PersonalEventError('invalid_time');
  if (!(PERSONAL_EVENT_TYPES as readonly string[]).includes(i.type)) throw new PersonalEventError('invalid_type');
  if (!isValidTimezone(i.timezone)) throw new PersonalEventError('invalid_timezone');
}

/**
 * Convert a wall-clock date+time in an IANA timezone to a UTC ISO instant using
 * the Intl offset trick (DST-safe to the minute). Proves timezone/date-boundary
 * handling: the produced instant renders back to the same wall day/time via
 * localDateKey/localTime in that timezone.
 */
export function zonedToUtcIso(date: string, time: string, timezone: string): string {
  const guess = new Date(`${date}T${time}:00Z`); // treat picked wall time as if UTC
  // Offset (ms the zone is ahead of UTC) at this instant — runtime-tz independent.
  const dtf = new Intl.DateTimeFormat('en-US', {
    timeZone: timezone, hour12: false,
    year: 'numeric', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', second: '2-digit',
  });
  const p = dtf.formatToParts(guess).reduce<Record<string, string>>((a, x) => { a[x.type] = x.value; return a; }, {});
  const asZone = Date.UTC(+p.year, +p.month - 1, +p.day, +p.hour % 24, +p.minute, +p.second);
  const offsetMs = asZone - guess.getTime();
  return new Date(guess.getTime() - offsetMs).toISOString();
}

export class CalendarService {
  private store: KvStore;
  private userId: string;

  constructor(userId: string, store: KvStore = defaultKvStore()) {
    this.userId = userId;
    this.store = store;
  }

  getFilters(): CalendarFilters {
    return this.store.get<CalendarFilters>(filtersKey(this.userId)) ?? defaultFilters();
  }

  setFilters(f: CalendarFilters): CalendarFilters {
    this.store.set(filtersKey(this.userId), f);
    return f;
  }

  /** Aggregate + apply persisted filters in one call (screen entry point). */
  view(results: readonly SourceResult[]): { agg: AggregateResult; filtered: CalendarEvent[]; filters: CalendarFilters } {
    const agg = aggregate(results);
    const filters = this.getFilters();
    return { agg, filtered: filterEvents(agg.events, filters), filters };
  }

  // --- personal events (S-91 Add Event, persisted through the service) ------

  private personalKey(): string {
    return `ls-cal-personal-${this.userId}`;
  }

  /** Raw persisted personal events for this user (owner-scoped). */
  listPersonalRaw(): RawSourceRecord[] {
    return this.store.get<RawSourceRecord[]>(this.personalKey()) ?? [];
  }

  /**
   * Add a manual personal event (S-91). Validated + normalized + persisted
   * through the service boundary so it appears on S-90 and survives refresh.
   * Throws PersonalEventError on invalid input (nothing is persisted then).
   */
  addPersonalEvent(input: PersonalEventInput, now: string): CalendarEvent {
    validatePersonalEvent(input); // throws before any write
    const existing = this.listPersonalRaw();
    const sourceId = `me-${Date.parse(now) || Date.now()}-${existing.length + 1}`;
    const startsAt = zonedToUtcIso(input.date, input.time, input.timezone);
    const raw: RawSourceRecord = {
      sourceId,
      ownerId: this.userId,
      title: input.title.trim(),
      startsAt,
      timezone: input.timezone,
      status: input.type === 'deadline' ? 'deadline' : 'scheduled',
      privacyClassification: 'personal',
      sourceUrl: SOURCE_ROUTE.reminder,
      updatedAt: now,
    };
    const normalized = normalizeEvent('reminder', raw, this.userId); // validates before any write
    this.store.set(this.personalKey(), [...existing, raw]);
    return normalized;
  }
}

// --- stable local fixtures (no live integrations) ---------------------------
// Deterministic sample sources so the screen + tests have real ISO datetimes.
// NOTE: titles carry no private identifiers; source_url is always in-app.

export const SAMPLE_INTERNSHIP_EVENTS: readonly RawSourceRecord[] = [
  { sourceId: 'cam-deadline', title: 'CAM application deadline', startsAt: '2026-07-20T18:30:00Z', status: 'deadline', privacyClassification: 'personal', sourceUrl: SOURCE_ROUTE.internship, updatedAt: '2026-07-10T04:00:00Z' },
  { sourceId: 'vidhi-interview', title: 'Vidhi interview', startsAt: '2026-07-22T05:30:00Z', endsAt: '2026-07-22T06:30:00Z', status: 'scheduled', sourceUrl: SOURCE_ROUTE.internship, updatedAt: '2026-07-11T04:00:00Z' },
];

export const SAMPLE_EXAM_EVENTS: readonly RawSourceRecord[] = [
  { sourceId: 'clat-mock-3', title: 'CLAT mock test 3', startsAt: '2026-07-19T04:30:00Z', endsAt: '2026-07-19T06:30:00Z', status: 'scheduled', sourceUrl: SOURCE_ROUTE.exam, updatedAt: '2026-07-09T04:00:00Z' },
];

export const SAMPLE_CLINICAL_EVENTS: readonly RawSourceRecord[] = [
  // title deliberately excludes verifier email / evidence (restricted).
  { sourceId: 'legal-aid-camp', title: 'Legal-aid camp (clinical hours)', startsAt: '2026-07-20T03:30:00Z', endsAt: '2026-07-20T09:30:00Z', status: 'scheduled', sourceUrl: SOURCE_ROUTE.clinical, updatedAt: '2026-07-08T04:00:00Z' },
];

export const SAMPLE_COMMUNITY_EVENTS: readonly RawSourceRecord[] = [
  { sourceId: 'ama-constitution', title: 'Community AMA: Constitutional law', startsAt: '2026-07-21T13:00:00Z', endsAt: '2026-07-21T14:00:00Z', status: 'tentative', privacyClassification: 'public', sourceUrl: SOURCE_ROUTE.community, updatedAt: '2026-07-07T04:00:00Z' },
];

/** Named loaders for the bundled fixtures (owner defaults to the given student). */
export function sampleLoaders(ownerId = 'self'): SourceLoader[] {
  return [
    { sourceType: 'internship', load: () => SAMPLE_INTERNSHIP_EVENTS, ownerId },
    { sourceType: 'exam', load: () => SAMPLE_EXAM_EVENTS, ownerId },
    { sourceType: 'clinical', load: () => SAMPLE_CLINICAL_EVENTS, ownerId },
    { sourceType: 'community', load: () => SAMPLE_COMMUNITY_EVENTS, ownerId },
  ];
}

/** Build the default set of source results from bundled fixtures. */
export function sampleSourceResults(ownerId = 'self'): SourceResult[] {
  return runLoaders(sampleLoaders(ownerId));
}

/**
 * Full set of loaders for a student: bundled module fixtures + the persisted
 * personal-events source (so S-91 additions appear on S-90 and survive refresh).
 */
export function calendarLoaders(svc: CalendarService, ownerId = 'self'): SourceLoader[] {
  return [
    ...sampleLoaders(ownerId),
    { sourceType: 'reminder', load: () => svc.listPersonalRaw(), ownerId },
  ];
}

export const CALENDAR_SOURCE_NOTE =
  'Aggregated from your LegalSaathi activity. Times shown in your selected timezone; external calendar sync is not enabled.';
