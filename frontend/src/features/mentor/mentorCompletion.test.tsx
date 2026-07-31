/**
 * The AUTHORISED completion surface (M-01, matrix D4; independent-QA defect D2).
 *
 * Three things are pinned here:
 *   1. who may mount it — `mentorActorFromAuth` denies anonymous, student,
 *      unverified and sentinel-subject sessions, and the screen renders a
 *      denial with no session and no control for them;
 *   2. what it offers — the completion control renders for a verified mentor on
 *      a session that has ended and has no attendance record yet, and is
 *      withheld (with a reason) in every other case;
 *   3. what it dispatches — the control's own mutation issues exactly one
 *      `POST /api/v1/tutoring/sessions/{id}/complete` carrying TUTOR/ADMIN
 *      claims, never the student dev-stub claims.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { renderToStaticMarkup } from 'react-dom/server';
import { MemoryRouter } from 'react-router-dom';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { ANONYMOUS_AUTH, AuthProvider, type AuthState } from '../../app/authContext';
import { mentorActorFromAuth, mentorRouteDenial } from './lib/mentorAuth';
import {
  COMPLETABLE_STATUSES,
  MentorGuard,
  MentorSessionCompletion,
  completionMutationOptions,
  completionOffered,
  hasEnded,
} from './MentorSessionScreens';
import { mentorRoutes } from './screens';
import {
  DEV_ACTOR_CLAIMS_HEADER,
  tutoringKeys,
  type AttendanceState,
  type TutoringActor,
  type TutoringSession,
} from '../student/lib/tutoringApi';

const HOUR = 3_600_000;
const MENTOR_SUBJECT = 'usr_7f3c9a21b4d6';
const SESSION_ID = '99999999-8888-4777-8666-555555555555';

const VERIFIED_MENTOR: AuthState = {
  isAuthenticated: true,
  userId: MENTOR_SUBJECT,
  roles: ['lawyer'],
  studentVerification: 'draft',
  lawyerVerification: 'verified',
  filingRole: 'lawyer',
  isMinor: false,
};

const ADMIN: AuthState = { ...VERIFIED_MENTOR, roles: ['admin'], lawyerVerification: 'draft' };

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

function renderMentor(auth: AuthState, sessions: TutoringSession[] | null): string {
  const client = new QueryClient({
    defaultOptions: { queries: { enabled: false, retry: false } },
  });
  const actor = mentorActorFromAuth(auth);
  if (actor && sessions) {
    client.setQueryData(tutoringKeys.mentorSessions(actor), {
      items: sessions,
      role: actor.role,
      limit: 50,
      offset: 0,
    });
  }
  return renderToStaticMarkup(
    <QueryClientProvider client={client}>
      <AuthProvider value={auth}>
        <MemoryRouter initialEntries={['/mentor/sessions']}>
          <MentorGuard><MentorSessionCompletion /></MentorGuard>
        </MemoryRouter>
      </AuthProvider>
    </QueryClientProvider>,
  );
}

/* ------------------------------------------------------------------ who --- */

describe('who may act as a mentor', () => {
  it('denies anonymous, student, client and moderator sessions', () => {
    const denied: AuthState[] = [
      ANONYMOUS_AUTH,
      { ...VERIFIED_MENTOR, roles: ['student'] },
      { ...VERIFIED_MENTOR, roles: ['student', 'lawyer'] },
      { ...VERIFIED_MENTOR, roles: ['moderator'] },
      { ...VERIFIED_MENTOR, roles: [] },
    ];
    for (const auth of denied) {
      expect(mentorActorFromAuth(auth)).toBeNull();
      expect(mentorRouteDenial(auth)).toBeTruthy();
    }
  });

  it('denies a lawyer session that has not passed verification', () => {
    for (const phase of ['draft', 'submitted', 'needs_info', 'rejected'] as const) {
      expect(mentorActorFromAuth({ ...VERIFIED_MENTOR, lawyerVerification: phase })).toBeNull();
    }
  });

  it('denies a session with no stable opaque subject', () => {
    for (const userId of [null, '', '  ', '+9198*****21', 'someone@example.com', 'pending_details']) {
      expect(mentorActorFromAuth({ ...VERIFIED_MENTOR, userId })).toBeNull();
    }
  });

  it('maps a verified lawyer session to the tutor actor and an admin to admin', () => {
    expect(mentorActorFromAuth(VERIFIED_MENTOR)).toEqual({ userId: MENTOR_SUBJECT, role: 'tutor' });
    expect(mentorActorFromAuth(ADMIN)).toEqual({ userId: MENTOR_SUBJECT, role: 'admin' });
    // Most privileged first, exactly like the server's `_service_role`.
    expect(mentorActorFromAuth({ ...VERIFIED_MENTOR, roles: ['tutor', 'admin'] })?.role).toBe('admin');
    expect(mentorRouteDenial(VERIFIED_MENTOR)).toBeNull();
  });
});

/* ----------------------------------------------------------------- what --- */

describe('when the completion control is offered', () => {
  it('is offered on an ended, un-recorded session in a live status', () => {
    for (const status of COMPLETABLE_STATUSES) {
      expect(completionOffered(makeSession({ status })).offered).toBe(true);
    }
  });

  it('is withheld before the scheduled end', () => {
    const future = makeSession({
      startUtc: new Date(Date.now() + 2 * HOUR).toISOString(),
      endUtc: new Date(Date.now() + 3 * HOUR).toISOString(),
    });
    expect(hasEnded(future)).toBe(false);
    const gate = completionOffered(future);
    expect(gate.offered).toBe(false);
    expect(gate.reason).toMatch(/after the scheduled end/i);
  });

  it('treats the scheduled end itself as ended, like the server boundary', () => {
    const now = Date.now();
    expect(hasEnded(makeSession({ endUtc: new Date(now).toISOString() }), now)).toBe(true);
    expect(hasEnded(makeSession({ endUtc: new Date(now + 1).toISOString() }), now)).toBe(false);
  });

  it('is withheld once any attendance record exists', () => {
    const states: AttendanceState[] = ['pending', 'recorded', 'confirmed', 'disputed', 'resolved'];
    for (const state of states) {
      expect(completionOffered(makeSession({ attendanceState: state })).offered).toBe(false);
    }
  });

  it('is withheld for a session that is not live', () => {
    for (const status of ['cancelled', 'completed', 'disputed']) {
      expect(completionOffered(makeSession({ status })).offered).toBe(false);
    }
  });
});

describe('the mentor screen', () => {
  it('is registered on its own guarded route, outside the student registry', () => {
    expect(mentorRoutes).toHaveLength(1);
    expect(mentorRoutes[0].path).toBe('/mentor/sessions');
    expect(mentorRoutes[0].screenId).toBe('M-01');
    expect(mentorRoutes[0].guarded).toBe(true);
    expect(mentorRoutes[0].path.startsWith('/s-')).toBe(false);
  });

  it('renders a denial with no session and no control for an unauthorised reader', () => {
    const unauthorised: AuthState[] = [
      ANONYMOUS_AUTH,
      { ...VERIFIED_MENTOR, roles: ['student'] },
      { ...VERIFIED_MENTOR, lawyerVerification: 'submitted' },
    ];
    for (const auth of unauthorised) {
      const html = renderMentor(auth, [makeSession()]);
      expect(html).toContain('Mentor sign-in required');
      expect(html).not.toContain('record-completion');
      expect(html).not.toMatch(/>\s*Record completion\s*</);
      expect(html).not.toContain(SESSION_ID);
    }
  });

  it('renders the completion control for a verified mentor on an ended session', () => {
    const html = renderMentor(VERIFIED_MENTOR, [makeSession()]);
    expect(html).toContain('data-screen="M-01"');
    expect(html).toContain('data-action="record-completion"');
    expect(html).toMatch(/Record completion/);
    expect(html).toContain(SESSION_ID);
  });

  it('renders the same control for an administrator', () => {
    const html = renderMentor(ADMIN, [makeSession()]);
    expect(html).toContain('data-action="record-completion"');
    expect(html).toMatch(/Administrator/);
  });

  it('withholds the control, with a reason, before the end and after a record', () => {
    const notYet = renderMentor(VERIFIED_MENTOR, [makeSession({
      startUtc: new Date(Date.now() + 2 * HOUR).toISOString(),
      endUtc: new Date(Date.now() + 3 * HOUR).toISOString(),
    })]);
    expect(notYet).not.toContain('data-action="record-completion"');
    expect(notYet).toMatch(/Completion opens after the scheduled end/);

    const already = renderMentor(VERIFIED_MENTOR, [makeSession({ attendanceState: 'recorded' })]);
    expect(already).not.toContain('data-action="record-completion"');
    expect(already).toMatch(/already recorded/i);
  });

  it('renders an honest empty state rather than an unusable action', () => {
    const html = renderMentor(VERIFIED_MENTOR, []);
    expect(html).toContain('Nothing waiting to be completed');
    expect(html).not.toContain('data-action="record-completion"');
  });
});

/* ------------------------------------------------------------ dispatch --- */

describe('what the control dispatches', () => {
  let fetchMock: ReturnType<typeof vi.fn>;

  beforeEach(() => {
    fetchMock = vi.fn(async () => new Response(
      JSON.stringify({
        session_id: SESSION_ID,
        state: 'recorded',
        version: 1,
        recorded_by_role: 'tutor',
        recorded_at: '2026-07-19T10:00:00+00:00',
        confirmed_at: null,
        disputed_at: null,
        resolved_at: null,
        resolution: null,
        session_status: 'completed',
      }),
      { status: 200, headers: { 'Content-Type': 'application/json' } },
    ));
    vi.stubGlobal('fetch', fetchMock);
  });

  afterEach(() => {
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
  });

  it('posts to the completion endpoint with the signed-in mentor claims', async () => {
    const actor: TutoringActor = { userId: MENTOR_SUBJECT, role: 'tutor' };
    const record = await completionMutationOptions(actor).mutationFn(SESSION_ID);
    expect(record.state).toBe('recorded');
    expect(fetchMock).toHaveBeenCalledTimes(1);
    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toContain(`/api/v1/tutoring/sessions/${SESSION_ID}/complete`);
    expect(init.method).toBe('POST');
    const claims = JSON.parse(new Headers(init.headers).get(DEV_ACTOR_CLAIMS_HEADER) ?? '{}');
    expect(claims).toEqual({ sub: MENTOR_SUBJECT, roles: ['tutor'] });
    // Never the student dev-stub identity that the S-35 screens use.
    expect(claims.roles).not.toContain('student');
  });

  it('posts admin claims when an administrator records it', async () => {
    const actor: TutoringActor = { userId: MENTOR_SUBJECT, role: 'admin' };
    await completionMutationOptions(actor).mutationFn(SESSION_ID);
    const [, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    const claims = JSON.parse(new Headers(init.headers).get(DEV_ACTOR_CLAIMS_HEADER) ?? '{}');
    expect(claims.roles).toEqual(['admin']);
  });

  it('surfaces a typed server refusal instead of pretending it worked', async () => {
    fetchMock.mockResolvedValueOnce(new Response(
      JSON.stringify({ detail: { code: 'FORBIDDEN', message: 'nope', retryable: false } }),
      { status: 403, headers: { 'Content-Type': 'application/json' } },
    ));
    const actor: TutoringActor = { userId: MENTOR_SUBJECT, role: 'tutor' };
    await expect(completionMutationOptions(actor).mutationFn(SESSION_ID))
      .rejects.toMatchObject({ code: 'FORBIDDEN', status: 403 });
  });
});
