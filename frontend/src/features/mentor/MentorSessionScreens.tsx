/**
 * M-01 `mentor/completion` — the AUTHORISED completion surface (matrix D4).
 *
 * Design read (legalsaathi-ui-design STEP 0):
 *   * Direction — the locked Option C2 tutoring scope. Every colour, radius and
 *     control on this screen is an existing `--tt-*` token reached through the
 *     shared `TutoringPrimitives`; no hue, no component and no motion is
 *     invented for it (docs/design/tutoring/option_c2_reference_v1,
 *     TOKEN_COMPONENT_MOTION_SPEC §4).
 *   * Dials — density calm, motion still, variance safe. An authority surface
 *     that moves people's attendance records should be sober, not lively.
 *   * Screen intent — one job: a mentor or administrator records completion for
 *     a session they own. One primary action per row, and nothing else.
 *
 * Why this screen exists (independent-QA defect D2). Recording completion is a
 * tutor/admin action on the server (`attendance.RECORDER_ROLES`), so the STUDENT
 * screen S-35 must not render or dispatch it — a control that knowingly fires a
 * request the server refuses with FORBIDDEN is an unauthorised action exposed in
 * the production student experience, not negative testing. The action lives here
 * instead, behind `MentorGuard`, and nowhere else in the app.
 *
 *   GET  /api/v1/tutoring/sessions            the caller's OWN sessions (server-scoped)
 *   POST /api/v1/tutoring/sessions/{id}/complete   D4, tutor/admin, after the end
 *
 * The client gate below (ended? already recorded?) mirrors the server rule so
 * the reader is not offered a doomed action; it never DECIDES it. The server
 * still answers with `ATTENDANCE_TOO_EARLY`, `ATTENDANCE_STATE_INVALID`,
 * `FORBIDDEN` or a non-enumerating `NOT_FOUND`, and that verdict is final.
 */
import { useMemo, useState, type ReactNode } from 'react';
import { Link } from 'react-router-dom';
import { useMutation, useQuery } from '@tanstack/react-query';
import { useAuth } from '../../app/authContext';
import { mentorActorFromAuth, mentorRouteDenial } from './lib/mentorAuth';
import {
  completeSession,
  listTutoringSessions,
  tutoringKeys,
  tutoringRetry,
  type AttendanceRecord,
  type TutoringActor,
  type TutoringSession,
} from '../student/lib/tutoringApi';
import { durationMinutes, slotTimeLabels } from '../student/lib/tutoringRules';
import {
  Banner,
  Chip,
  Disclosure,
  EmptyState,
  Ic,
  Kv,
  LoadingState,
  TutoringScreen,
  TypedErrorState,
  useAnnouncer,
  useRouteArrival,
} from '../student/tutoring/TutoringPrimitives';

/** The canonical id for the mentor completion screen (outside the student S-01..S-99 registry). */
export const MENTOR_COMPLETION_SCREEN_ID = 'M-01';

/** Server statuses from which a completion may still be recorded (`attendance.record`). */
export const COMPLETABLE_STATUSES = ['confirmed', 'rescheduled'];

/**
 * The ONE mutation this surface may dispatch, exported so a test can prove the
 * control is wired to the authorised call — and that the call carries a
 * tutor/admin actor rather than the student dev-stub claims.
 */
export function completionMutationOptions(actor: TutoringActor) {
  return {
    mutationFn: (sessionId: string): Promise<AttendanceRecord> =>
      completeSession(sessionId, actor),
    retry: tutoringRetry,
  };
}

/** True once the scheduled end has passed — the server's inclusive boundary. */
export function hasEnded(session: TutoringSession, now: number = Date.now()): boolean {
  const end = Date.parse(session.endUtc);
  return Number.isFinite(end) && end <= now;
}

/** Whether this screen offers the completion control for a session, and why not. */
export function completionOffered(
  session: TutoringSession,
  now: number = Date.now(),
): { offered: boolean; reason: string } {
  if (session.attendanceState) {
    return {
      offered: false,
      reason: `Attendance is already ${session.attendanceState}. Completion is recorded once per session.`,
    };
  }
  if (!COMPLETABLE_STATUSES.includes(session.status)) {
    return {
      offered: false,
      reason: `This session is ${session.status}, so there is nothing to complete.`,
    };
  }
  if (!hasEnded(session, now)) {
    return {
      offered: false,
      reason: 'Completion opens after the scheduled end. The server refuses an early finish.',
    };
  }
  return { offered: true, reason: 'The scheduled end has passed.' };
}

/* ========================================================================== *
 * Guard — nothing below mounts for an unauthorised reader
 * ========================================================================== */

/**
 * Denies anonymous / student / unverified actors BEFORE any session data or
 * completion control mounts. Children are not rendered when denied, so there is
 * no hidden, disabled or flag-gated copy of the action anywhere in the tree.
 */
export function MentorGuard({ children }: { children: ReactNode }) {
  const auth = useAuth();
  const denial = mentorRouteDenial(auth);
  if (!denial) return <>{children}</>;
  return <MentorDenied denial={denial} />;
}

/** The denial surface: an explanation and a way in, never a session and never an action. */
export function MentorDenied({ denial }: { denial: string }) {
  return (
    <TutoringScreen screenId={MENTOR_COMPLETION_SCREEN_ID}>
      <div>
        <div className="tt-eyebrow">Restricted · mentor workspace</div>
        <h1 className="tt-h tt-arrival" style={{ marginTop: '4px', fontSize: '19px' }}>
          Mentor sign-in required
        </h1>
      </div>
      <Banner
        tone="warn"
        title={denial}
        detail="Recording completion for a tutoring session belongs to the mentor who taught it or to an administrator. No session, and no completion control, is shown here until you are signed in as one."
        code="FORBIDDEN"
      />
      <Link className="tt-btn tt-btn--block" to="/auth/lawyer">
        <Ic name="lock" />
        Go to mentor sign-in and verification
      </Link>
      <p className="tt-svr">
        server-authoritative: role and ownership are re-checked on every request · this screen
        only decides what to show
      </p>
    </TutoringScreen>
  );
}

/* ========================================================================== *
 * M-01 — the mentor's own sessions, with the completion action
 * ========================================================================== */

export function MentorSessionCompletion() {
  const auth = useAuth();
  const actor = mentorActorFromAuth(auth);
  useRouteArrival(`${MENTOR_COMPLETION_SCREEN_ID}:${actor?.role ?? 'denied'}`);
  // Defence in depth: the route is already wrapped in MentorGuard, and the
  // screen refuses to compose an actor of its own if it is ever mounted bare.
  if (!actor) return <MentorDenied denial={mentorRouteDenial(auth) ?? 'Mentor sign-in required'} />;
  return <MentorCompletionList actor={actor} />;
}

function MentorCompletionList({ actor }: { actor: TutoringActor }) {
  const [announceRegion, announce] = useAnnouncer();
  const [recorded, setRecorded] = useState<AttendanceRecord | null>(null);
  const params = useMemo(() => ({ status: COMPLETABLE_STATUSES, limit: 50 }), []);
  const query = useQuery({
    queryKey: tutoringKeys.mentorSessions(actor),
    queryFn: () => listTutoringSessions(params, actor),
    retry: tutoringRetry,
    staleTime: 10_000,
  });

  const mutation = useMutation({
    ...completionMutationOptions(actor),
    onSuccess: (record) => {
      setRecorded(record);
      announce(
        `Completion recorded. Attendance is ${record.state} and the student can now confirm or dispute it.`,
      );
      void query.refetch();
    },
  });

  const sessions = query.data?.items ?? [];

  return (
    <TutoringScreen screenId={MENTOR_COMPLETION_SCREEN_ID}>
      {announceRegion}
      <div>
        <div className="tt-eyebrow">
          {actor.role === 'admin' ? 'Administrator · authorised actions' : 'Mentor · your calendar'}
        </div>
        <h1 className="tt-h tt-arrival">Record completion</h1>
        <p className="tt-p" style={{ marginTop: '5px' }}>
          {actor.role === 'admin'
            ? 'Sessions you may close on a mentor’s behalf. Recording completion opens the student’s confirm or dispute step.'
            : 'Sessions on your own calendar. Once you record completion, your student can confirm it or open a dispute.'}
        </p>
      </div>

      {recorded && (
        <Banner
          tone="ok"
          title="Completion recorded"
          detail="The session is closed and the student can now confirm or dispute this attendance record. Recording it again is refused."
          code={`ATTENDANCE_${recorded.state.toUpperCase()}`}
        />
      )}

      {query.isPending && <LoadingState what="your sessions" />}
      {query.isError && <TypedErrorState error={query.error} onRecover={() => query.refetch()} />}
      {mutation.isError && (
        <TypedErrorState
          error={mutation.error}
          recoveryLabel="Reload your sessions"
          onRecover={() => query.refetch()}
        />
      )}

      {query.isSuccess && sessions.length === 0 && (
        <EmptyState
          title="Nothing waiting to be completed"
          detail="No session on your calendar is open for a completion record right now. A session appears here once it is booked, and its action unlocks after the scheduled end."
        />
      )}

      {sessions.map((session) => (
        <MentorSessionRow
          key={session.id}
          session={session}
          pending={mutation.isPending && mutation.variables === session.id}
          onRecord={() => mutation.mutate(session.id)}
        />
      ))}

      <Disclosure summary="What the server decides here" icon="info">
        <Kv label="Who may record">Your session, or an administrator</Kv>
        <Kv label="Before the scheduled end">ATTENDANCE_TOO_EARLY</Kv>
        <Kv label="Already recorded">ATTENDANCE_STATE_INVALID</Kv>
        <Kv label="Not your session">NOT_FOUND</Kv>
        <p className="tt-p tt-muted">
          Every refusal above leaves the record exactly as it was, and the student is never
          offered this action at all.
        </p>
      </Disclosure>

      <p className="tt-svr">
        server-authoritative: this list is scoped to your account · completion, its timing and its
        provenance are all server decisions
      </p>
    </TutoringScreen>
  );
}

function MentorSessionRow({
  session,
  pending,
  onRecord,
}: {
  session: TutoringSession;
  pending: boolean;
  onRecord: () => void;
}) {
  const labels = slotTimeLabels(session.startUtc, session.endUtc, session.ianaTimezone);
  const gate = completionOffered(session);
  return (
    <article className="tt-tut">
      <div className="tt-tut__bd">
        <div className="tt-chiprow">
          <Chip tone={session.status === 'cancelled' ? 'r' : 'g'}>{session.status}</Chip>
          <Chip tone={session.attendanceState ? 'i' : 't'}>
            {session.attendanceState
              ? `Attendance ${session.attendanceState}`
              : 'No completion record'}
          </Chip>
        </div>
        <div>
          <b style={{ fontSize: '13.5px' }}>{labels.sessionZone}</b>
          <span style={{ display: 'block', fontSize: '12px', color: 'var(--tt-mut)', fontWeight: 700 }}>
            {labels.sessionZoneLabel}
            {labels.readerZone ? ` · your time ${labels.readerZone}` : ''}
          </span>
        </div>
        <div className="tt-row">
          <span className="tt-muted">
            {durationMinutes(session.startUtc, session.endUtc)} minutes
          </span>
          <span className="tt-mono" style={{ fontSize: '11.5px' }}>{session.id}</span>
        </div>
        {gate.offered ? (
          <button
            type="button"
            className="tt-btn tt-btn--jade tt-btn--block"
            data-action="record-completion"
            disabled={pending}
            onClick={onRecord}
          >
            <Ic name="check" />
            {pending ? 'Recording completion' : 'Record completion'}
          </button>
        ) : (
          <p className="tt-p tt-muted">{gate.reason}</p>
        )}
      </div>
    </article>
  );
}
