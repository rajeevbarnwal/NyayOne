/**
 * Authority regression for the tutoring completion action (independent-QA
 * defect D2, matrix D4/D5).
 *
 * The bug: S-35 rendered a "Record completion (mentor or administrator)" button
 * on the STUDENT surface and fired `POST /complete`, which the server is bound
 * to refuse with FORBIDDEN. That is an unauthorised action exposed in the
 * production student experience, not negative testing.
 *
 * These tests pin the corrected rule from the student side:
 *   1. NO completion control renders on any student screen, in any session or
 *      attendance state, before or after the scheduled end;
 *   2. confirm / dispute are offered ONLY once a Sprint 1 administrator has
 *      recorded completion (`attendance_state === 'recorded'`);
 *   3. the shipped student source cannot dispatch the call at all — the adapter
 *      is not imported and the control's copy no longer exists.
 */
import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import { describe, expect, it } from 'vitest';
import { renderToStaticMarkup } from 'react-dom/server';
import { MemoryRouter } from 'react-router-dom';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { SessionLifecycle } from './SessionScreens';
import { tutoringKeys, type AttendanceState, type TutoringSession } from '../lib/tutoringApi';

const SESSION_ID = '11111111-2222-4333-8444-555555555555';
const HOUR = 3_600_000;

function makeSession(overrides: Partial<TutoringSession> = {}): TutoringSession {
  const start = new Date(Date.now() - 3 * HOUR);
  const end = new Date(Date.now() - 2 * HOUR);
  return {
    id: SESSION_ID,
    slotId: 'slot-1',
    tutorId: 'tutor-1',
    studentUserId: 'student-1',
    orderId: 'order-1',
    status: 'confirmed',
    version: 1,
    startUtc: start.toISOString(),
    endUtc: end.toISOString(),
    ianaTimezone: 'Asia/Kolkata',
    startLocal: start.toISOString(),
    endLocal: end.toISOString(),
    attendanceState: null,
    attendanceVersion: null,
    ...overrides,
  };
}

/** Render S-35 at one view with the server state already in the cache. */
function renderStudent(view: string, session: TutoringSession | null): string {
  const client = new QueryClient({
    defaultOptions: { queries: { enabled: false, retry: false } },
  });
  if (session) client.setQueryData(tutoringKeys.session(session.id), session);
  const search = session ? `?session=${session.id}&view=${view}` : `?view=${view}`;
  return renderToStaticMarkup(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={[`/s-35${search}`]}>
        <SessionLifecycle />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

const STUDENT_VIEWS = ['list', 'manage', 'policy', 'reschedule', 'attendance', 'review', 'prejoin'];
const ATTENDANCE_STATES: (AttendanceState | null)[] = [
  null, 'pending', 'recorded', 'confirmed', 'disputed', 'resolved',
];

/** Anything that would let a reader dispatch `POST /complete` from this screen. */
function assertNoCompletionControl(html: string, where: string): void {
  expect(html, `${where} must not name the completion action`).not.toMatch(/record completion/i);
  expect(html, `${where} must not carry a completion control`).not.toContain('record-completion');
  expect(html, `${where} must not offer a completion button`).not.toMatch(
    /<button[^>]*>(?:(?!<\/button>).)*complete\s+(?:this\s+)?session/is,
  );
}

describe('D2: the student surface offers no completion control anywhere', () => {
  it('renders no completion control in any view, for any attendance state', () => {
    for (const state of ATTENDANCE_STATES) {
      for (const view of STUDENT_VIEWS) {
        const session = makeSession({ attendanceState: state, attendanceVersion: state ? 1 : null });
        assertNoCompletionControl(renderStudent(view, session), `S-35 ${view} / attendance=${state}`);
      }
    }
  });

  it('renders no completion control before the scheduled end either', () => {
    const future = makeSession({
      startUtc: new Date(Date.now() + 26 * HOUR).toISOString(),
      endUtc: new Date(Date.now() + 27 * HOUR).toISOString(),
    });
    for (const view of STUDENT_VIEWS) {
      assertNoCompletionControl(renderStudent(view, future), `S-35 ${view} / before the end`);
    }
  });

  it('renders no completion control on the session list, loaded or empty', () => {
    assertNoCompletionControl(renderStudent('list', null), 'S-35 list');
  });

  it('explains the Sprint 1 administrator-only recorder instead of offering the action', () => {
    const html = renderStudent('manage', makeSession());
    expect(html).toMatch(/an administrator records completion/i);
    expect(html).not.toMatch(/mentor or an administrator records completion/i);
  });
});

describe('D5: confirm and dispute appear only after completion is recorded', () => {
  it('offers both controls once attendance is recorded', () => {
    const html = renderStudent('attendance', makeSession({
      attendanceState: 'recorded',
      attendanceVersion: 1,
    }));
    expect(html).toContain('Confirm attendance');
    expect(html).toContain('Dispute this');
    expect(html).toMatch(/administrator recorded this session/i);
    expect(html).not.toMatch(/your mentor recorded this session/i);
    assertNoCompletionControl(html, 'S-35 attendance / recorded');
  });

  it('offers neither control while no completion record exists', () => {
    for (const state of [null, 'pending'] as const) {
      const html = renderStudent('attendance', makeSession({ attendanceState: state }));
      expect(html, `attendance=${state} must not offer confirm`).not.toContain('Confirm attendance');
      expect(html, `attendance=${state} must not offer dispute`).not.toContain('Dispute this');
      expect(html).toMatch(/Attendance is not decided yet/);
    }
  });

  it('offers neither control once the record has moved past `recorded`', () => {
    for (const state of ['confirmed', 'disputed', 'resolved'] as const) {
      const html = renderStudent('attendance', makeSession({
        attendanceState: state,
        attendanceVersion: 2,
      }));
      expect(html, `attendance=${state} must not re-offer confirm`).not.toContain('Confirm attendance');
      expect(html, `attendance=${state} must not re-offer dispute`).not.toContain('Dispute this');
    }
  });

  it('keeps reviewing blocked while attendance is absent or disputed', () => {
    for (const state of [null, 'pending', 'recorded', 'disputed'] as const) {
      const html = renderStudent('review', makeSession({ attendanceState: state }));
      expect(html).toContain('REVIEW_BLOCKED');
      expect(html).toMatch(/Reviewing is locked until attendance is confirmed/);
    }
  });
});

describe('static canary: the student source cannot dispatch completion', () => {
  const path = join(process.cwd(), 'src', 'features', 'student', 'tutoring', 'SessionScreens.tsx');
  /** Comments stripped, so an explanatory note cannot pass or fail the gate. */
  const source = readFileSync(path, 'utf8')
    .replace(/\/\*[\s\S]*?\*\//g, ' ')
    .replace(/(^|[^:])\/\/.*$/gm, '$1 ');

  it('reads the source it claims to check', () => {
    expect(source.length).toBeGreaterThan(200);
  });

  it('never imports or calls the completion adapter', () => {
    expect(source).not.toContain('completeSession');
    expect(source).not.toContain('completeMutation');
  });

  it('never posts to the completion endpoint by hand', () => {
    expect(source).not.toMatch(/\/complete\b/);
  });

  it('cannot name an authorised actor, so it cannot form the call', () => {
    // `completeSession` demands a TutoringActor whose role is 'tutor' | 'admin'.
    expect(source).not.toContain('TutoringActor');
    expect(source).not.toContain('actorClaimsHeaders');
  });
});
