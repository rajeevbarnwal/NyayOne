import { describe, expect, it } from 'vitest';
import { renderToStaticMarkup } from 'react-dom/server';
import { MemoryRouter } from 'react-router-dom';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { AuthProvider, type AuthState } from '../../../app/authContext';
import {
  CalendarAdd,
  CalendarConflictScreen,
  CalendarMonth,
  CalendarPreferencesScreen,
  copyPrivateFeedUrl,
  failedSourceRetryFilters,
  reconcileFailedSourceRetry,
} from './CalendarScreens';

const STUDENT: AuthState = {
  isAuthenticated: true,
  userId: '00000000-0000-4000-8000-0000000000de',
  roles: ['student'],
  studentVerification: 'verified',
  lawyerVerification: 'draft',
  filingRole: null,
  isMinor: false,
};

function render(path: string, component: React.ReactElement, seed?: (client: QueryClient) => void): string {
  const client = new QueryClient({ defaultOptions: { queries: { enabled: false, retry: false } } });
  seed?.(client);
  return renderToStaticMarkup(
    <QueryClientProvider client={client}>
      <AuthProvider value={STUDENT}>
        <MemoryRouter initialEntries={[path]}>{component}</MemoryRouter>
      </AuthProvider>
    </QueryClientProvider>,
  );
}

const PREVIEW = {
  id: 'event-1', sourceType: 'exam' as const, title: 'CLAT mock',
  startsAt: '2026-08-03T10:00:00Z', endsAt: '2026-08-03T11:00:00Z',
  timezone: 'Asia/Kolkata', status: 'scheduled' as const, sourceUrl: '/s-55',
};

const EVENT_DETAIL = {
  ...PREVIEW,
  privacyClassification: 'personal' as const,
  eventKind: null,
  version: 1,
  createdAt: '2026-08-02T00:00:00Z',
  updatedAt: '2026-08-02T00:00:00Z',
};

describe('Wave 5 S-90–S-93 calendar screens', () => {
  it('renders server-authoritative S90 loading state with an explicit readiness contract', () => {
    const html = render('/s-90', <CalendarMonth />);
    expect(html).toContain('data-screen="S-90"');
    expect(html).toContain('data-wave5-ready="loading"');
    expect(html).toContain('Loading your private calendar');
    expect(html).not.toContain('CAM application deadline');
  });

  it('renders S91 strict personal-event fields and no device-storage success copy', () => {
    const html = render('/s-91', <CalendarAdd />);
    expect(html).toContain('data-screen="S-91"');
    expect(html).toContain('maxLength="160"');
    expect(html).toContain('type="date"');
    expect(html).toContain('Timezone');
    expect(html).toContain('Add to calendar');
    expect(html).toContain('does not store them in localStorage');
    expect(html).not.toContain('stored on your device');
    expect(html).not.toContain('/s-91?mode=detail');
    expect(html).not.toContain('cal-tab-event');
  });

  it('never renders Edit/Delete for imported reminders or tutoring events', () => {
    for (const sourceType of ['reminder', 'tutoring'] as const) {
      const html = render('/s-91?event=event-1', <CalendarAdd />, (client) => client.setQueryData(
        ['calendar', 'event', 'event-1'],
        { ...EVENT_DETAIL, sourceType, sourceUrl: sourceType === 'reminder' ? '/s-82' : '/s-35' },
      ));
      expect(html).toContain('Go to source');
      expect(html).not.toContain('>Edit<');
      expect(html).not.toContain('>Delete<');
    }
  });

  it('renders Edit/Delete only for an owner-created personal event', () => {
    const html = render('/s-91?event=event-1', <CalendarAdd />, (client) => client.setQueryData(
      ['calendar', 'event', 'event-1'],
      { ...EVENT_DETAIL, sourceType: 'reminder', eventKind: 'reminder' },
    ));
    expect(html).toContain('>Edit<');
    expect(html).toContain('>Delete<');
    expect(html).not.toContain('Go to source');
  });

  it('keeps an imported credential reminder read-only even though its source type is reminder', () => {
    const eventId = '00000000-0000-4000-8000-000000000295';
    const html = render(`/s-91?event=${eventId}`, <CalendarAdd />, (client) => client.setQueryData(
      ['calendar', 'event', eventId],
      {
        id: eventId,
        sourceType: 'reminder',
        title: 'Credential renewal reminder',
        startsAt: '2026-08-05T10:00:00Z',
        endsAt: '2026-08-05T10:30:00Z',
        timezone: 'Asia/Kolkata',
        status: 'scheduled',
        privacyClassification: 'personal',
        eventKind: null,
        sourceUrl: '/s-82',
        version: 1,
        createdAt: '2026-08-02T00:00:00Z',
        updatedAt: '2026-08-02T00:00:00Z',
      },
    ));
    expect(html).toContain('Credential renewal reminder');
    expect(html).toContain('Go to source');
    expect(html).not.toContain('>Edit<');
    expect(html).not.toContain('>Delete<');
  });

  it('renders persisted conflict status plus accessible dismiss/resolve controls', () => {
    const html = render('/s-92', <CalendarConflictScreen />, (client) => client.setQueryData(['calendar', 'conflicts'], {
      items: [{ id: 'conflict-1', leftEventId: 'event-1', rightEventId: 'event-2', left: PREVIEW,
        right: { ...PREVIEW, id: 'event-2', title: 'Tutoring session', sourceType: 'tutoring' },
        status: 'active', detectedAt: '2026-08-02T00:00:00Z', version: 1 }], total: 1,
    }));
    expect(html).toContain('data-screen="S-92"');
    expect(html).toContain('data-wave5-ready="ready"');
    expect(html).toContain('Dismiss');
    expect(html).toContain('Mark resolved');
    expect(html).toContain('CLAT mock');
    expect(html).toContain('Tutoring session');
  });

  it('renders reminder controls from server values', () => {
    const html = render('/s-93?tab=reminders', <CalendarPreferencesScreen />, (client) => client.setQueryData(['calendar', 'reminder-preferences'], [{
      id: 'pref-1', sourceType: 'exam', channel: 'in_app', enabled: true, leadMinutes: 30,
      quietStartMin: 1320, quietEndMin: 420, timezone: 'Asia/Kolkata', version: 1, updatedAt: '2026-08-02T00:00:00Z',
    }]));
    expect(html).toContain('Reminder preferences');
    expect(html).toContain('Send this reminder');
    expect(html).toContain('22:00');
    expect(html).toContain('07:00');
    expect(html).toContain('Timezone');
    expect(html).toContain('<option selected="">Asia/Kolkata</option>');
    expect(html).not.toContain('role="tablist"');
    expect(html).not.toContain('role="tab"');
  });

  it('labels expired export truthfully and permits replacement without rendering any feed secret', () => {
    const html = render('/s-93?tab=export', <CalendarPreferencesScreen />, (client) => {
      client.setQueryData(['calendar', 'exports'], {
        items: [{ id: 'export-1', status: 'expired', timezone: 'Asia/Kolkata', expiresAt: '2026-08-01T00:00:00Z', revokedAt: null, tokenReturnedOnce: true, version: 1 }], total: 1,
      });
      client.setQueryData(['calendar', 'view-preferences'], {
        viewMode: 'month', sourceTypes: ['exam'], fromDate: null, toDate: null,
        timezone: 'Europe/London', version: 2, updatedAt: '2026-08-02T00:00:00Z',
      });
    });
    expect(html).toContain('Previous feed: expired');
    expect(html).toContain('Create private feed');
    expect(html).toContain('Export timezone');
    expect(html).toContain('<option selected="">Europe/London</option>');
    expect(html).toContain('Anyone holding this private URL can read the feed until it expires or you revoke it');
    expect(html).not.toContain('feed_url');
    expect(html).not.toContain('calendar-feeds/');
  });

  it('offers explicit rotation for an active feed without rendering its secret', () => {
    const html = render('/s-93?tab=export', <CalendarPreferencesScreen />, (client) => {
      client.setQueryData(['calendar', 'exports'], {
        items: [{ id: 'export-1', status: 'active', timezone: 'UTC', expiresAt: '2026-11-01T00:00:00Z', revokedAt: null, tokenReturnedOnce: true, version: 1 }], total: 1,
      });
      client.setQueryData(['calendar', 'view-preferences'], {
        viewMode: 'month', sourceTypes: ['exam'], fromDate: null, toDate: null,
        timezone: 'Asia/Kolkata', version: 2, updatedAt: '2026-08-02T00:00:00Z',
      });
    });
    expect(html).toContain('Rotate feed');
    expect(html).toContain('Revoke feed');
    expect(html).not.toContain('calendar-feeds/');
  });

  it('retains the one-time feed URL when clipboard permission blocks a copy', async () => {
    const feedUrl = 'https://calendar.example/api/v1/public/calendar-feeds/test-secret.ics';
    const blocked = await copyPrivateFeedUrl(feedUrl, { writeText: async () => { throw new Error('blocked'); } });
    expect(blocked).toEqual({ copied: false, retainedFeedUrl: feedUrl });
    const copied = await copyPrivateFeedUrl(feedUrl, { writeText: async () => undefined });
    expect(copied).toEqual({ copied: true, retainedFeedUrl: null });
  });

  it('retries only failed source types and reconciles only their rows', () => {
    const filters = failedSourceRetryFilters(['tutoring', 'reminder'], {
      fromDate: '2026-08-01', toDate: '2026-08-31', timezone: 'UTC',
    });
    expect(filters).toEqual({
      sourceTypes: ['tutoring', 'reminder'], fromDate: '2026-08-01', toDate: '2026-08-31', timezone: 'UTC',
    });
    const exam = { ...EVENT_DETAIL, id: 'exam-1', sourceType: 'exam' as const };
    const staleTutoring = { ...EVENT_DETAIL, id: 'tutoring-old', sourceType: 'tutoring' as const };
    const freshTutoring = { ...EVENT_DETAIL, id: 'tutoring-new', sourceType: 'tutoring' as const };
    const reconciled = reconcileFailedSourceRetry(
      { items: [exam, staleTutoring], total: 2, failedSources: ['tutoring'] },
      { items: [freshTutoring], total: 1, failedSources: [] },
      ['tutoring'],
    );
    expect(reconciled.items.map((item) => item.id)).toEqual(['exam-1', 'tutoring-new']);
    expect(reconciled.failedSources).toEqual([]);
  });

  it('fails closed for an anonymous actor before any calendar data renders', () => {
    const client = new QueryClient({ defaultOptions: { queries: { enabled: false } } });
    const html = renderToStaticMarkup(<QueryClientProvider client={client}><MemoryRouter><CalendarMonth /></MemoryRouter></QueryClientProvider>);
    expect(html).toContain('data-wave5-ready="restricted"');
    expect(html).toContain('Sign in with your student account');
  });
});
