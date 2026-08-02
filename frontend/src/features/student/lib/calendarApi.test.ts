import { afterEach, describe, expect, it, vi } from 'vitest';
import {
  CalendarApiError,
  checkCalendarConflicts,
  createCalendarEvent,
  createCalendarExport,
  deleteCalendarEvent,
  getCalendarEvent,
  getCalendarExport,
  listCalendarEvents,
  listCalendarExports,
  updateCalendarConflict,
  updateCalendarEvent,
  updateCalendarReminderPreference,
  updateCalendarViewPreferences,
} from './calendarApi';

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

function response(body: unknown, status = 200): Response {
  return new Response(status === 204 ? null : JSON.stringify(body), {
    status,
    headers: status === 204 ? undefined : { 'Content-Type': 'application/json' },
  });
}

const EVENT = {
  id: '00000000-0000-4000-8000-000000000901',
  source_type: 'reminder', source_id: 'manual-1', title: 'Judiciary mock',
  starts_at: '2026-08-03T13:30:00Z', ends_at: '2026-08-03T14:30:00Z',
  timezone: 'Asia/Kolkata', status: 'scheduled', privacy_classification: 'personal',
  event_kind: 'study',
  source_url: '/s-91', version: 1,
  created_at: '2026-08-02T00:00:00Z', updated_at: '2026-08-02T00:00:00Z',
} as const;

const PREVIEW = {
  id: EVENT.id, source_type: EVENT.source_type, title: EVENT.title,
  starts_at: EVENT.starts_at, ends_at: EVENT.ends_at, timezone: EVENT.timezone,
  status: EVENT.status, source_url: EVENT.source_url,
};

const EXPORT = {
  id: '00000000-0000-4000-8000-000000000905', status: 'active', timezone: 'Asia/Kolkata',
  expires_at: '2026-08-09T00:00:00Z', revoked_at: null,
  feed_url: 'https://calendar.test/api/v1/public/calendar-feeds/raw-secret-token.ics',
  token_returned_once: true, version: 1,
};

describe('Wave 5 calendar API contract', () => {
  it('maps events, emits repeated source_type filters and relies only on cookie auth', async () => {
    const fetchMock = vi.fn().mockResolvedValue(response({ items: [EVENT], total: 1, failed_sources: ['clinical'] }));
    vi.stubGlobal('fetch', fetchMock);
    const result = await listCalendarEvents({ sourceTypes: ['exam', 'internship'], fromDate: '2026-08-01', timezone: 'Asia/Kolkata' });
    expect(result).toEqual(expect.objectContaining({ total: 1, failedSources: ['clinical'] }));
    expect(result.items[0]).toEqual(expect.objectContaining({ sourceType: 'reminder', startsAt: EVENT.starts_at }));
    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    const parsed = new URL(url);
    expect(parsed.searchParams.getAll('source_type')).toEqual(['exam', 'internship']);
    expect(parsed.searchParams.get('from_date')).toBe('2026-08-01');
    expect(init.credentials).toBe('include');
    expect(new Headers(init.headers).has('X-Actor-Claims')).toBe(false);
  });

  it('creates, gets, updates and deletes a personal event with exact wire/version semantics', async () => {
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(response(EVENT, 201))
      .mockResolvedValueOnce(response(EVENT))
      .mockResolvedValueOnce(response({ ...EVENT, version: 2, title: 'Edited' }))
      .mockResolvedValueOnce(response(null, 204));
    vi.stubGlobal('fetch', fetchMock);
    const input = {
      title: EVENT.title, startsAt: EVENT.starts_at, endsAt: EVENT.ends_at,
      timezone: EVENT.timezone, status: EVENT.status, privacyClassification: EVENT.privacy_classification, eventKind: EVENT.event_kind,
    };
    await createCalendarEvent(input, 'event-idempotency-key');
    await getCalendarEvent(EVENT.id);
    await updateCalendarEvent(EVENT.id, { ...input, title: 'Edited', expectedVersion: 1 });
    await deleteCalendarEvent(EVENT.id);
    const [, createInit] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(new Headers(createInit.headers).get('Idempotency-Key')).toBe('event-idempotency-key');
    expect(JSON.parse(String(createInit.body))).toEqual(expect.objectContaining({ starts_at: EVENT.starts_at, privacy_classification: 'personal', event_kind: 'study' }));
    const [, updateInit] = fetchMock.mock.calls[2] as [string, RequestInit];
    expect(updateInit.method).toBe('PUT');
    expect(JSON.parse(String(updateInit.body))).toEqual(expect.objectContaining({ title: 'Edited', expected_version: 1 }));
    expect((fetchMock.mock.calls[3] as [string, RequestInit])[1].method).toBe('DELETE');
  });

  it('writes view/reminder preferences using optimistic versions and canonical minute values', async () => {
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(response({ view_mode: 'month', source_types: ['exam'], from_date: null, to_date: null, timezone: 'UTC', version: 4, updated_at: '2026-08-02T00:00:00Z' }))
      .mockResolvedValueOnce(response({ id: 'pref-1', source_type: 'exam', channel: 'in_app', enabled: true, lead_minutes: 30, quiet_start_min: 1320, quiet_end_min: 420, timezone: 'UTC', version: 1, updated_at: '2026-08-02T00:00:00Z' }));
    vi.stubGlobal('fetch', fetchMock);
    await updateCalendarViewPreferences({ viewMode: 'month', sourceTypes: ['exam'], fromDate: null, toDate: null, timezone: 'UTC', expectedVersion: 3 });
    await updateCalendarReminderPreference({ sourceType: 'exam', channel: 'in_app', enabled: true, leadMinutes: 30, quietStartMin: 1320, quietEndMin: 420, timezone: 'UTC', expectedVersion: 0 });
    expect(JSON.parse(String((fetchMock.mock.calls[0] as [string, RequestInit])[1].body))).toEqual(expect.objectContaining({ expected_version: 3, source_types: ['exam'] }));
    expect(JSON.parse(String((fetchMock.mock.calls[1] as [string, RequestInit])[1].body))).toEqual(expect.objectContaining({ lead_minutes: 30, quiet_start_min: 1320, expected_version: 0 }));
  });

  it('checks and persists conflict dismissal/resolution with the returned preview contract', async () => {
    const conflict = { id: 'conflict-1', left_event_id: EVENT.id, right_event_id: 'event-2', left: PREVIEW, right: { ...PREVIEW, id: 'event-2' }, status: 'active', detected_at: '2026-08-02T00:00:00Z', version: 1 };
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(response({ items: [conflict], total: 1 }))
      .mockResolvedValueOnce(response({ ...conflict, status: 'resolved', version: 2 }));
    vi.stubGlobal('fetch', fetchMock);
    await expect(checkCalendarConflicts()).resolves.toEqual(expect.objectContaining({ total: 1 }));
    await expect(updateCalendarConflict('conflict-1', 'resolved', 1)).resolves.toEqual(expect.objectContaining({ status: 'resolved', version: 2 }));
    const [, init] = fetchMock.mock.calls[1] as [string, RequestInit];
    expect(init.method).toBe('PATCH');
    expect(JSON.parse(String(init.body))).toEqual({ status: 'resolved', expected_version: 1 });
  });

  it('drops feed_url from collection/detail and exposes it only in the immediate create result', async () => {
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(response({ items: [EXPORT], total: 1 }))
      .mockResolvedValueOnce(response(EXPORT))
      .mockResolvedValueOnce(response(EXPORT, 201));
    vi.stubGlobal('fetch', fetchMock);
    const listed = await listCalendarExports();
    const detail = await getCalendarExport(EXPORT.id);
    const created = await createCalendarExport('Asia/Kolkata', 'export-idempotency-key');
    expect(JSON.stringify(listed)).not.toContain('raw-secret-token');
    expect(JSON.stringify(detail)).not.toContain('raw-secret-token');
    expect(created.oneTimeFeedUrl).toContain('raw-secret-token');
    expect(new Headers((fetchMock.mock.calls[2] as [string, RequestInit])[1].headers).get('Idempotency-Key')).toBe('export-idempotency-key');
  });

  it('keeps structured server failures typed and does not fabricate success', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(response({ detail: { code: 'calendar_stale_version', message: 'stale', field: 'expected_version' } }, 409)));
    await expect(getCalendarEvent('missing')).rejects.toEqual(expect.objectContaining<Partial<CalendarApiError>>({ status: 409, code: 'calendar_stale_version', field: 'expected_version' }));
  });
});
