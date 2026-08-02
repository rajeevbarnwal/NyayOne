import { apiFetch, newRequestId } from '../../../lib/apiClient';
import type {
  CalendarEventStatus,
  CalendarSourceType,
  PersonalEventType,
  PrivacyClassification,
} from './calendar';

const BASE = '/api/v1/calendar';

export type CalendarViewMode = 'month' | 'week' | 'day';
export type ReminderChannel = 'in_app' | 'email_digest' | 'push';
export type ReminderLeadMinutes = 0 | 10 | 30 | 60 | 120 | 1440;

export interface CalendarEventRecord {
  id: string;
  sourceType: CalendarSourceType;
  title: string;
  startsAt: string;
  endsAt: string;
  timezone: string;
  status: CalendarEventStatus;
  privacyClassification: PrivacyClassification;
  eventKind: PersonalEventType | null;
  sourceUrl: string;
  version: number;
  createdAt: string;
  updatedAt: string;
}

export interface CalendarEventList {
  items: CalendarEventRecord[];
  total: number;
  failedSources: CalendarSourceType[];
}

export interface CalendarViewPreferences {
  viewMode: CalendarViewMode;
  sourceTypes: CalendarSourceType[];
  fromDate: string | null;
  toDate: string | null;
  timezone: string;
  version: number;
  updatedAt: string;
}

export interface CalendarReminderPreference {
  id: string;
  sourceType: CalendarSourceType;
  channel: ReminderChannel;
  enabled: boolean;
  leadMinutes: ReminderLeadMinutes;
  quietStartMin: number;
  quietEndMin: number;
  timezone: string;
  version: number;
  updatedAt: string;
}

export interface CalendarEventPreview {
  id: string;
  sourceType: CalendarSourceType;
  title: string;
  startsAt: string;
  endsAt: string;
  timezone: string;
  status: CalendarEventStatus;
  sourceUrl: string;
}

export interface CalendarConflict {
  id: string;
  leftEventId: string;
  rightEventId: string;
  left: CalendarEventPreview;
  right: CalendarEventPreview;
  status: string;
  detectedAt: string;
  version: number;
}

/** Export metadata is intentionally secret-free. */
export interface CalendarExportSummary {
  id: string;
  status: string;
  timezone: string;
  expiresAt: string;
  revokedAt: string | null;
  tokenReturnedOnce: boolean;
  version: number;
}

/** The raw feed URL exists only in the immediate create response. */
export interface CreatedCalendarExport extends CalendarExportSummary {
  oneTimeFeedUrl: string | null;
}

interface EventWire {
  id: string;
  source_type: CalendarSourceType;
  title: string;
  starts_at: string;
  ends_at: string;
  timezone: string;
  status: CalendarEventStatus;
  privacy_classification: PrivacyClassification;
  event_kind: PersonalEventType | null;
  source_url: string;
  version: number;
  created_at: string;
  updated_at: string;
}

interface EventListWire {
  items: EventWire[];
  total: number;
  failed_sources: CalendarSourceType[];
}

interface ViewPreferenceWire {
  view_mode: CalendarViewMode;
  source_types: CalendarSourceType[];
  from_date: string | null;
  to_date: string | null;
  timezone: string;
  version: number;
  updated_at: string;
}

interface ReminderPreferenceWire {
  id: string;
  source_type: CalendarSourceType;
  channel: ReminderChannel;
  enabled: boolean;
  lead_minutes: ReminderLeadMinutes;
  quiet_start_min: number;
  quiet_end_min: number;
  timezone: string;
  version: number;
  updated_at: string;
}

interface EventPreviewWire {
  id: string;
  source_type: CalendarSourceType;
  title: string;
  starts_at: string;
  ends_at: string;
  timezone: string;
  status: CalendarEventStatus;
  source_url: string;
}

interface ConflictWire {
  id: string;
  left_event_id: string;
  right_event_id: string;
  left: EventPreviewWire;
  right: EventPreviewWire;
  status: string;
  detected_at: string;
  version: number;
}

interface ExportWire {
  id: string;
  status: string;
  timezone: string;
  expires_at: string;
  revoked_at: string | null;
  feed_url: string | null;
  token_returned_once: boolean;
  version: number;
}

export class CalendarApiError extends Error {
  constructor(
    readonly status: number,
    readonly code: string,
    message: string,
    readonly field?: string,
    readonly retryable = false,
  ) {
    super(message);
    this.name = 'CalendarApiError';
  }
}

function mapEvent(item: EventWire): CalendarEventRecord {
  return {
    id: item.id,
    sourceType: item.source_type,
    title: item.title,
    startsAt: item.starts_at,
    endsAt: item.ends_at,
    timezone: item.timezone,
    status: item.status,
    privacyClassification: item.privacy_classification,
    eventKind: item.event_kind,
    sourceUrl: item.source_url,
    version: item.version,
    createdAt: item.created_at,
    updatedAt: item.updated_at,
  };
}

function mapViewPreference(item: ViewPreferenceWire): CalendarViewPreferences {
  return {
    viewMode: item.view_mode,
    sourceTypes: item.source_types,
    fromDate: item.from_date,
    toDate: item.to_date,
    timezone: item.timezone,
    version: item.version,
    updatedAt: item.updated_at,
  };
}

function mapReminder(item: ReminderPreferenceWire): CalendarReminderPreference {
  return {
    id: item.id,
    sourceType: item.source_type,
    channel: item.channel,
    enabled: item.enabled,
    leadMinutes: item.lead_minutes,
    quietStartMin: item.quiet_start_min,
    quietEndMin: item.quiet_end_min,
    timezone: item.timezone,
    version: item.version,
    updatedAt: item.updated_at,
  };
}

function mapPreview(item: EventPreviewWire): CalendarEventPreview {
  return {
    id: item.id,
    sourceType: item.source_type,
    title: item.title,
    startsAt: item.starts_at,
    endsAt: item.ends_at,
    timezone: item.timezone,
    status: item.status,
    sourceUrl: item.source_url,
  };
}

function mapConflict(item: ConflictWire): CalendarConflict {
  return {
    id: item.id,
    leftEventId: item.left_event_id,
    rightEventId: item.right_event_id,
    left: mapPreview(item.left),
    right: mapPreview(item.right),
    status: item.status,
    detectedAt: item.detected_at,
    version: item.version,
  };
}

function mapExport(item: ExportWire): CalendarExportSummary {
  return {
    id: item.id,
    status: item.status,
    timezone: item.timezone,
    expiresAt: item.expires_at,
    revokedAt: item.revoked_at,
    tokenReturnedOnce: item.token_returned_once,
    version: item.version,
  };
}

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const headers = new Headers(init.headers);
  if (init.body && !headers.has('Content-Type')) headers.set('Content-Type', 'application/json');
  const response = await apiFetch(`${BASE}${path}`, { ...init, headers });
  if (!response.ok) {
    let body: { detail?: string | { code?: string; message?: string; field?: string; retryable?: boolean } } = {};
    try { body = await response.json() as typeof body; } catch { /* fail closed below */ }
    const detail = typeof body.detail === 'object' && body.detail ? body.detail : {};
    throw new CalendarApiError(
      response.status,
      detail.code ?? `calendar_http_${response.status}`,
      detail.message ?? (typeof body.detail === 'string' ? body.detail : 'Calendar request failed.'),
      detail.field,
      detail.retryable ?? response.status >= 500,
    );
  }
  if (response.status === 204) return undefined as T;
  return response.json() as Promise<T>;
}

export function calendarErrorCopy(error: unknown): string {
  if (!(error instanceof CalendarApiError)) return 'Calendar is temporarily unavailable. Please try again.';
  const copy: Record<string, string> = {
    calendar_invalid_date_range: 'The start date must be on or before the end date.',
    calendar_invalid_timezone: 'Choose a supported timezone.',
    calendar_invalid_datetime: 'Choose a valid date and time.',
    calendar_event_not_found: 'This calendar item is not available.',
    calendar_export_not_found: 'This private calendar feed is no longer available.',
    calendar_stale_version: 'Your calendar changed in another session. Reload and try again.',
    idempotency_conflict: 'This request was already used with different details. Try again.',
    unauthenticated: 'Sign in to use your calendar.',
    forbidden: 'You do not have access to this calendar item.',
  };
  return copy[error.code] ?? error.message ?? 'Calendar request failed.';
}

export interface CalendarEventFilters {
  sourceTypes?: CalendarSourceType[];
  fromDate?: string | null;
  toDate?: string | null;
  timezone?: string;
}

export async function listCalendarEvents(filters: CalendarEventFilters = {}): Promise<CalendarEventList> {
  const query = new URLSearchParams();
  for (const source of filters.sourceTypes ?? []) query.append('source_type', source);
  if (filters.fromDate) query.set('from_date', filters.fromDate);
  if (filters.toDate) query.set('to_date', filters.toDate);
  if (filters.timezone) query.set('timezone', filters.timezone);
  const wire = await request<EventListWire>(`/events${query.size ? `?${query.toString()}` : ''}`);
  return { items: wire.items.map(mapEvent), total: wire.total, failedSources: wire.failed_sources };
}

export interface CreateCalendarEventInput {
  title: string;
  startsAt: string;
  endsAt: string;
  timezone: string;
  status: CalendarEventStatus;
  privacyClassification: 'personal' | 'restricted';
  eventKind: PersonalEventType;
}

export async function createCalendarEvent(input: CreateCalendarEventInput, idempotencyKey = newRequestId()): Promise<CalendarEventRecord> {
  const wire = await request<EventWire>('/events', {
    method: 'POST',
    headers: { 'Idempotency-Key': idempotencyKey },
    body: JSON.stringify({
      title: input.title,
      starts_at: input.startsAt,
      ends_at: input.endsAt,
      timezone: input.timezone,
      status: input.status,
      privacy_classification: input.privacyClassification,
      event_kind: input.eventKind,
    }),
  });
  return mapEvent(wire);
}

export async function getCalendarEvent(id: string): Promise<CalendarEventRecord> {
  return mapEvent(await request<EventWire>(`/events/${encodeURIComponent(id)}`));
}

export async function updateCalendarEvent(
  id: string,
  input: CreateCalendarEventInput & { expectedVersion: number },
): Promise<CalendarEventRecord> {
  const wire = await request<EventWire>(`/events/${encodeURIComponent(id)}`, {
    method: 'PUT',
    body: JSON.stringify({
      title: input.title,
      starts_at: input.startsAt,
      ends_at: input.endsAt,
      timezone: input.timezone,
      status: input.status,
      privacy_classification: input.privacyClassification,
      event_kind: input.eventKind,
      expected_version: input.expectedVersion,
    }),
  });
  return mapEvent(wire);
}

export async function deleteCalendarEvent(id: string): Promise<void> {
  await request<void>(`/events/${encodeURIComponent(id)}`, { method: 'DELETE' });
}

export async function getCalendarViewPreferences(): Promise<CalendarViewPreferences> {
  return mapViewPreference(await request<ViewPreferenceWire>('/view-preferences'));
}

export async function updateCalendarViewPreferences(input: Omit<CalendarViewPreferences, 'version' | 'updatedAt'> & { expectedVersion: number }): Promise<CalendarViewPreferences> {
  const wire = await request<ViewPreferenceWire>('/view-preferences', {
    method: 'PUT',
    body: JSON.stringify({
      view_mode: input.viewMode,
      source_types: input.sourceTypes,
      from_date: input.fromDate,
      to_date: input.toDate,
      timezone: input.timezone,
      expected_version: input.expectedVersion,
    }),
  });
  return mapViewPreference(wire);
}

export async function listCalendarReminderPreferences(): Promise<CalendarReminderPreference[]> {
  const wire = await request<{ items: ReminderPreferenceWire[] }>('/reminder-preferences');
  return wire.items.map(mapReminder);
}

export async function updateCalendarReminderPreference(input: Omit<CalendarReminderPreference, 'id' | 'version' | 'updatedAt'> & { expectedVersion: number }): Promise<CalendarReminderPreference> {
  const wire = await request<ReminderPreferenceWire>('/reminder-preferences', {
    method: 'PUT',
    body: JSON.stringify({
      source_type: input.sourceType,
      channel: input.channel,
      enabled: input.enabled,
      lead_minutes: input.leadMinutes,
      quiet_start_min: input.quietStartMin,
      quiet_end_min: input.quietEndMin,
      timezone: input.timezone,
      expected_version: input.expectedVersion,
    }),
  });
  return mapReminder(wire);
}

export async function checkCalendarConflicts(eventIds?: string[], persist = true): Promise<{ items: CalendarConflict[]; total: number }> {
  const wire = await request<{ items: ConflictWire[]; total: number }>('/conflicts/check', {
    method: 'POST',
    body: JSON.stringify({ event_ids: eventIds, persist }),
  });
  return { items: wire.items.map(mapConflict), total: wire.total };
}

export async function updateCalendarConflict(
  id: string,
  status: 'active' | 'dismissed' | 'resolved',
  expectedVersion: number,
): Promise<CalendarConflict> {
  return mapConflict(await request<ConflictWire>(`/conflicts/${encodeURIComponent(id)}`, {
    method: 'PATCH',
    body: JSON.stringify({ status, expected_version: expectedVersion }),
  }));
}

export async function listCalendarExports(): Promise<{ items: CalendarExportSummary[]; total: number }> {
  const wire = await request<{ items: ExportWire[]; total: number }>('/exports');
  // mapExport deliberately drops feed_url even if a broken server sends one.
  return { items: wire.items.map(mapExport), total: wire.total };
}

export async function getCalendarExport(id: string): Promise<CalendarExportSummary> {
  return mapExport(await request<ExportWire>(`/exports/${encodeURIComponent(id)}`));
}

export async function createCalendarExport(timezone: string, idempotencyKey = newRequestId()): Promise<CreatedCalendarExport> {
  const wire = await request<ExportWire>('/exports', {
    method: 'POST',
    headers: { 'Idempotency-Key': idempotencyKey },
    body: JSON.stringify({ timezone }),
  });
  return { ...mapExport(wire), oneTimeFeedUrl: wire.feed_url };
}

/**
 * Rotate through the server's single transactional create/rotate command.
 * Calling DELETE first would strand the user without a working feed if the
 * replacement creation failed after revocation.
 */
export async function rotateCalendarExport(timezone: string, idempotencyKey = newRequestId()): Promise<CreatedCalendarExport> {
  return createCalendarExport(timezone, idempotencyKey);
}

export async function revokeCalendarExport(id: string): Promise<CalendarExportSummary> {
  return mapExport(await request<ExportWire>(`/exports/${encodeURIComponent(id)}`, { method: 'DELETE' }));
}
