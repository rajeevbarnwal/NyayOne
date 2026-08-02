import { describe, expect, it } from 'vitest';
import { buildDashboardWeek, currentWeek, dashboardWeekday } from './Dashboard';
import type { CalendarEventRecord } from '../lib/calendarApi';

const EVENT: CalendarEventRecord = {
  id: 'event-1',
  sourceType: 'exam',
  title: 'Timezone boundary event',
  startsAt: '2026-08-02T23:30:00.000Z',
  endsAt: '2026-08-03T00:30:00.000Z',
  timezone: 'UTC',
  status: 'scheduled',
  privacyClassification: 'personal',
  eventKind: null,
  sourceUrl: '/s-55',
  version: 1,
  createdAt: '2026-08-02T00:00:00.000Z',
  updatedAt: '2026-08-02T00:00:00.000Z',
};

describe('Dashboard selected-timezone current week', () => {
  it('derives a Monday-first week from the current instant in the selected timezone', () => {
    const now = new Date('2026-08-02T20:00:00.000Z');
    expect(currentWeek(now, 'Asia/Kolkata').map((date) => date.toISOString().slice(0, 10)))
      .toEqual(['2026-08-03', '2026-08-04', '2026-08-05', '2026-08-06', '2026-08-07', '2026-08-08', '2026-08-09']);
    expect(currentWeek(now, 'America/New_York')[0].toISOString().slice(0, 10)).toBe('2026-07-27');
    expect(dashboardWeekday(now, 'Asia/Kolkata')).toBe('Monday');
    expect(dashboardWeekday(now, 'America/New_York')).toBe('Sunday');
  });

  it('projects events into the selected timezone rather than the source timezone', () => {
    const week = buildDashboardWeek(new Date('2026-08-03T05:00:00.000Z'), 'Asia/Kolkata', [EVENT]);
    expect(week[0]).toMatchObject({ key: '2026-08-03', dow: 'MON', date: 3 });
    expect(week[0].event).toContain('05:00');
  });
});
