/**
 * S-35 `tutoring/session` (SAATHI-66, matrix D1-D5, E1, F1-F3, I1, I2).
 *
 * One canonical screen id carrying the whole session lifecycle, exactly as the
 * approved reference package does (decision D-11): list, manage, cancellation
 * policy and refund, reschedule, completion, attendance confirm/dispute, the
 * live-room entry point, and reviews.
 *
 *   GET  /api/v1/tutoring/sessions                      list (scoped to caller)
 *   GET  /api/v1/tutoring/sessions/{id}                 detail
 *   POST /api/v1/tutoring/sessions/{id}/reschedule       D2
 *   POST /api/v1/tutoring/sessions/{id}/cancel           D3 (+ refund verdict)
 *   POST /api/v1/tutoring/sessions/{id}/complete         D4
 *   POST /api/v1/tutoring/sessions/{id}/attendance/*     D5
 *   POST /api/v1/tutoring/sessions/{id}/join-credentials E1
 *   POST /api/v1/tutoring/sessions/{id}/review           F1/F2
 *
 * MEDIA AND CREDENTIAL PRIVACY (matrix J1). The raw join token lives in a ref
 * for the lifetime of the room and nowhere else: not in React Query's cache, not
 * in a query key, not in the URL, not in storage, not in a log. Only the
 * REDACTED projection is ever put in render state. Device enumeration keeps
 * `deviceId` in memory to open a track and never reads or renders `label`, so no
 * device name exists to leak. There is no peer connection here, so no SDP and no
 * ICE candidate is ever produced — the video-provider seam (W2-9) is still
 * Product-pending and the room says so rather than pretending otherwise.
 */
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { Link, useSearchParams } from 'react-router-dom';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import {
  ATTENDANCE_DISPUTE_REASON_CODES,
  REVIEW_BLOCKED,
  TutoringApiError,
  cancelSession,
  completeSession,
  confirmAttendance,
  createReview,
  disputeAttendance,
  getAvailability,
  getTutoringSession,
  issueJoinCredentials,
  listTutoringSessions,
  redactJoinCredential,
  rescheduleSession,
  tutoringKeys,
  tutoringRetry,
  type AttendanceDisputeReasonCode,
  type AvailabilitySlot,
  type CancelResult,
  type JoinCredential,
  type RedactedJoinCredential,
  type TutoringSession,
} from '../lib/tutoringApi';
import {
  REVIEW_MAX_BODY,
  REVIEW_MAX_RATING,
  REVIEW_MIN_BODY,
  browserTimeZone,
  durationMinutes,
  formatPaise,
  policyPreview,
  slotTimeLabels,
  validateReview,
} from '../lib/tutoringRules';
import {
  Banner,
  Chip,
  Disclosure,
  Dock,
  EmptyState,
  Ic,
  Kv,
  LoadingState,
  Modal,
  TutoringScreen,
  TypedErrorState,
  useAnnouncer,
  useRouteArrival,
} from './TutoringPrimitives';

type View = 'list' | 'manage' | 'policy' | 'reschedule' | 'attendance' | 'review' | 'prejoin' | 'room';

const VIEWS: View[] = ['list', 'manage', 'policy', 'reschedule', 'attendance', 'review', 'prejoin', 'room'];

function readView(raw: string | null, sessionId: string): View {
  if (raw && (VIEWS as string[]).includes(raw)) return raw as View;
  return sessionId ? 'manage' : 'list';
}

/* ========================================================================== *
 * Entry point
 * ========================================================================== */

export function SessionLifecycle() {
  const [sp, setSp] = useSearchParams();
  const sessionId = sp.get('session') ?? '';
  const view = readView(sp.get('view'), sessionId);
  useRouteArrival(`S-35:${view}:${sessionId}`);

  const go = useCallback((next: View, id: string = sessionId): void => {
    const params = new URLSearchParams();
    if (id) params.set('session', id);
    params.set('view', next);
    setSp(params, { replace: false });
  }, [sessionId, setSp]);

  if (view === 'list' || !sessionId) return <SessionList go={go} />;
  if (view === 'room') return <LiveRoom sessionId={sessionId} go={go} />;
  return <SessionDetailViews sessionId={sessionId} view={view} go={go} />;
}

type Go = (next: View, id?: string) => void;

/* ========================================================================== *
 * D1 — the session list
 * ========================================================================== */

/**
 * A session that has not happened yet, in the server's own vocabulary
 * (`SESSION_STATUSES` in backend/app/models/wave2.py). There is no `scheduled`
 * status: the server refuses an unknown filter with 422 VALIDATION_ERROR, so
 * naming one here made the default tab of this screen an error banner.
 */
const LIVE_STATUSES = ['confirmed', 'pending_provider', 'rescheduled'];

const STATUS_TABS: Array<{ key: string; label: string; statuses?: string[] }> = [
  { key: 'upcoming', label: 'Upcoming', statuses: LIVE_STATUSES },
  { key: 'finished', label: 'Finished', statuses: ['completed', 'disputed'] },
  { key: 'cancelled', label: 'Cancelled', statuses: ['cancelled'] },
  { key: 'all', label: 'Everything' },
];

function SessionList({ go }: { go: Go }) {
  const [tab, setTab] = useState('upcoming');
  const statuses = STATUS_TABS.find((t) => t.key === tab)?.statuses;
  const params = useMemo(() => ({ status: statuses, limit: 50 }), [statuses]);
  const query = useQuery({
    queryKey: tutoringKeys.sessions({ status: statuses }),
    queryFn: () => listTutoringSessions(params),
    retry: tutoringRetry,
    staleTime: 15_000,
  });

  return (
    <TutoringScreen screenId="S-35">
      <div>
        <div className="tt-eyebrow">Your chambers diary</div>
        <h1 className="tt-h tt-arrival">Sessions</h1>
        <p className="tt-p" style={{ marginTop: '5px' }}>
          Join, reschedule, cancel, confirm attendance and review — all from the server&apos;s own
          record of each session.
        </p>
      </div>

      <div className="tt-railwrap">
        <div className="tt-rails" role="group" aria-label="Filter sessions by status">
          {STATUS_TABS.map((t) => (
            <button
              key={t.key}
              type="button"
              className="tt-rail"
              aria-pressed={tab === t.key}
              onClick={() => setTab(t.key)}
            >
              <i aria-hidden />
              {t.label}
            </button>
          ))}
        </div>
      </div>

      {query.isPending && <LoadingState what="your sessions" />}
      {query.isError && <TypedErrorState error={query.error} onRecover={() => query.refetch()} />}

      {query.isSuccess && query.data.items.length === 0 && (
        <EmptyState
          title="Nothing here yet"
          detail="When you book a mentor, the session appears here with its join, reschedule and cancel actions."
          action={<Link className="tt-btn tt-btn--block" to="/s-31">Find a mentor</Link>}
        />
      )}

      {query.isSuccess && query.data.items.map((session) => (
        <SessionRow key={session.id} session={session} go={go} />
      ))}

      <p className="tt-svr">
        server-authoritative: this list is scoped to your account · eligibility, refunds and
        attendance are all server decisions
      </p>
    </TutoringScreen>
  );
}

function SessionRow({ session, go }: { session: TutoringSession; go: Go }) {
  const labels = slotTimeLabels(session.startUtc, session.endUtc, session.ianaTimezone);
  const policy = policyPreview({ startUtcIso: session.startUtc, capturedPaise: 0 });
  return (
    <article className="tt-tut">
      <div className="tt-tut__bd">
        <div className="tt-chiprow">
          <Chip tone={LIVE_STATUSES.includes(session.status) ? 'g' : session.status === 'cancelled' ? 'r' : 'i'}>
            {session.status}
          </Chip>
          {session.attendanceState && (
            <Chip tone={session.attendanceState === 'confirmed' ? 'g' : session.attendanceState === 'disputed' ? 'r' : 'i'}>
              Attendance {session.attendanceState}
            </Chip>
          )}
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
            {policy.started ? ' · start has passed' : ` · in about ${Math.round(policy.hoursBeforeStart)} h`}
          </span>
          <button type="button" className="tt-btn tt-btn--jade" onClick={() => go('manage', session.id)}>
            <Ic name="cal" />
            Open
          </button>
        </div>
      </div>
    </article>
  );
}

/* ========================================================================== *
 * Manage / policy / reschedule / attendance / review / pre-join
 * ========================================================================== */

function SessionDetailViews({
  sessionId,
  view,
  go,
}: {
  sessionId: string;
  view: View;
  go: Go;
}) {
  const query = useQuery({
    queryKey: tutoringKeys.session(sessionId),
    queryFn: () => getTutoringSession(sessionId),
    retry: tutoringRetry,
    staleTime: 10_000,
  });

  if (query.isPending) {
    return <TutoringScreen screenId="S-35"><LoadingState what="this session" /></TutoringScreen>;
  }
  if (query.isError) {
    return (
      <TutoringScreen screenId="S-35">
        <TypedErrorState
          error={query.error}
          recoveryLabel="Back to my sessions"
          onRecover={() => go('list', '')}
        />
      </TutoringScreen>
    );
  }

  const session = query.data;
  const refresh = () => { void query.refetch(); };

  if (view === 'policy') return <PolicyView session={session} go={go} />;
  if (view === 'reschedule') return <RescheduleView session={session} go={go} onDone={refresh} />;
  if (view === 'attendance') return <AttendanceView session={session} go={go} onDone={refresh} />;
  if (view === 'review') return <ReviewView session={session} go={go} />;
  if (view === 'prejoin') return <PreJoinView session={session} go={go} />;
  return <ManageView session={session} go={go} onDone={refresh} />;
}

function SessionHeading({ session }: { session: TutoringSession }) {
  const labels = slotTimeLabels(session.startUtc, session.endUtc, session.ianaTimezone);
  return (
    <div>
      <Chip tone={LIVE_STATUSES.includes(session.status) ? 'g' : 'i'}>{session.status}</Chip>
      <h1 className="tt-h tt-arrival" style={{ marginTop: '8px', fontSize: '19px' }}>
        {labels.sessionZone}
      </h1>
      <p className="tt-p" style={{ fontSize: '12.5px' }}>
        {labels.sessionZoneLabel}
        {labels.readerZone && <> · your time {labels.readerZone} ({labels.readerZoneLabel})</>}
      </p>
    </div>
  );
}

/* -------------------------------- manage --------------------------------- */

function ManageView({
  session,
  go,
  onDone,
}: {
  session: TutoringSession;
  go: Go;
  onDone: () => void;
}) {
  const [announceRegion, announce] = useAnnouncer();
  const queryClient = useQueryClient();
  const [confirmCancel, setConfirmCancel] = useState(false);
  const [cancelled, setCancelled] = useState<CancelResult | null>(null);
  const policy = policyPreview({ startUtcIso: session.startUtc, capturedPaise: 0 });

  const cancelMutation = useMutation({
    mutationFn: () => cancelSession({
      sessionId: session.id,
      // Optimistic concurrency: a session that moved under us is refused with
      // SESSION_STALE_VERSION rather than overwriting the newer change.
      expectedVersion: session.version,
    }),
    retry: tutoringRetry,
    onSuccess: (result) => {
      setConfirmCancel(false);
      setCancelled(result);
      queryClient.setQueryData(tutoringKeys.session(session.id), result);
      announce(
        result.refund && result.refund.amountPaise > 0
          ? `Session cancelled. ${formatPaise(result.refund.amountPaise)} is being refunded.`
          : 'Session cancelled. No automatic refund applies at this notice.',
      );
      onDone();
    },
  });

  const completeMutation = useMutation({
    mutationFn: () => completeSession(session.id),
    retry: tutoringRetry,
    onSuccess: (record) => {
      announce(`Completion recorded. Attendance is now ${record.state}.`);
      onDone();
    },
  });

  const dock = (
    <Dock>
      {policy.started ? (
        <button type="button" className="tt-btn tt-btn--jade tt-btn--block" onClick={() => go('attendance')}>
          <Ic name="check" />
          Go to attendance
        </button>
      ) : (
        <button type="button" className="tt-btn tt-btn--jade tt-btn--block" onClick={() => go('prejoin')}>
          <Ic name="join" />
          Enter the room
        </button>
      )}
      <div className="tt-dockrow">
        <button type="button" className="tt-btn" onClick={() => go('policy')}>
          <Ic name="refund" />
          Cancel or reschedule
        </button>
        <Link className="tt-btn" to={`/s-34?session=${encodeURIComponent(session.id)}`}>
          <Ic name="info" />
          Receipt
        </Link>
      </div>
    </Dock>
  );

  return (
    <TutoringScreen screenId="S-35" dock={dock}>
      {announceRegion}
      <button type="button" className="tt-btn" style={{ alignSelf: 'flex-start' }} onClick={() => go('list', '')}>
        <Ic name="back" />
        All sessions
      </button>
      <SessionHeading session={session} />

      {cancelled ? (
        <RefundOutcome result={cancelled} />
      ) : policy.started ? (
        <Banner
          tone="info"
          title="The scheduled start has passed"
          detail="Cancellation is closed. Attendance opens after the scheduled end, and a review follows a confirmed attendance record."
        />
      ) : (
        <Banner
          tone={policy.rescheduleFree ? 'info' : 'warn'}
          title={
            policy.rescheduleFree
              ? `Free cancellation and reschedule for another ${Math.floor(policy.hoursBeforeStart - policy.policyWindowHours)} hours`
              : 'Inside the notice window'
          }
          detail={
            policy.rescheduleFree
              ? `You are ${policy.hoursBeforeStart} hours before the start, which is outside the ${policy.policyWindowHours} hour window, so cancelling earns a full refund and rescheduling is free.`
              : `You are ${policy.hoursBeforeStart} hours before the start, inside the ${policy.policyWindowHours} hour window. Cancelling now earns no automatic refund and a free reschedule is refused. An administrator can still review your case.`
          }
        />
      )}

      <Disclosure summary="Session details" icon="info" open>
        <Kv label="Length">{durationMinutes(session.startUtc, session.endUtc)} minutes</Kv>
        <Kv label="Timezone kept with the session">{session.ianaTimezone}</Kv>
        <Kv label="Your device timezone">{browserTimeZone()}</Kv>
        <Kv label="Session reference">
          <span className="tt-mono" style={{ fontSize: '12px' }}>{session.id}</span>
        </Kv>
        <Kv label="Record version">{session.version}</Kv>
        <Kv label="Attendance">{session.attendanceState ?? 'Not decided yet'}</Kv>
      </Disclosure>

      {policy.started && (
        <>
          <button
            type="button"
            className="tt-btn tt-btn--block"
            disabled={completeMutation.isPending}
            onClick={() => completeMutation.mutate()}
          >
            <Ic name="check" />
            Record completion (mentor or administrator)
          </button>
          <p className="tt-p tt-muted">
            Only your mentor or an administrator may record completion, and only after the
            scheduled end. If that is not you, the server refuses this and says so.
          </p>
          {completeMutation.isError && <TypedErrorState error={completeMutation.error} />}
        </>
      )}

      {cancelMutation.isError && (
        <TypedErrorState
          error={cancelMutation.error}
          recoveryLabel="Reload this session"
          onRecover={onDone}
        />
      )}

      {!cancelled && !policy.started && (
        <button
          type="button"
          className="tt-btn tt-btn--terra tt-btn--block"
          onClick={() => setConfirmCancel(true)}
        >
          <Ic name="refund" />
          Cancel this session
        </button>
      )}

      <p className="tt-svr">
        server-authoritative: eligibility, refund amount and settlement · refunds are idempotent by
        refund reference
      </p>

      {confirmCancel && (
        <Modal title="Cancel this session?" onDismiss={() => setConfirmCancel(false)}>
          <p className="tt-p" style={{ fontSize: '13px' }}>
            {policy.rescheduleFree
              ? 'You are outside the notice window, so the server will assess a full refund of the captured amount. This cannot be undone.'
              : 'You are inside the notice window, so no automatic refund applies. You may prefer to reschedule instead. This cannot be undone.'}
          </p>
          <button
            type="button"
            className="tt-btn tt-btn--terra tt-btn--block"
            disabled={cancelMutation.isPending}
            onClick={() => cancelMutation.mutate()}
          >
            <Ic name="refund" />
            {cancelMutation.isPending ? 'Cancelling' : 'Yes, cancel and assess the refund'}
          </button>
          <button type="button" className="tt-btn tt-btn--block" onClick={() => setConfirmCancel(false)}>
            <Ic name="close" />
            Keep my session
          </button>
        </Modal>
      )}
    </TutoringScreen>
  );
}

/** The server's own refund verdict, rendered from integer paise. */
function RefundOutcome({ result }: { result: CancelResult }) {
  const refund = result.refund;
  if (!refund) {
    return (
      <Banner
        tone="warn"
        title="Session cancelled, no refund recorded"
        detail="The server cancelled the session and recorded no refund for it. Nothing further is needed from you."
      />
    );
  }
  const due = refund.amountPaise > 0;
  const step = due ? 3 : 1;
  return (
    <>
      <Banner
        tone={due ? 'ok' : 'warn'}
        title={due ? 'Cancelled with a refund' : 'Cancelled with no automatic refund'}
        detail={
          due
            ? `The server assessed ${formatPaise(refund.amountPaise)} under the ${refund.policyWindowHours} hour policy, ${refund.hoursBeforeStart} hours before the start.`
            : `At ${refund.hoursBeforeStart} hours before the start you were inside the ${refund.policyWindowHours} hour window, so no automatic refund applies. An administrator can still review this.`
        }
        code={refund.decision.toUpperCase()}
      />
      {due && (
        <div className="tt-amt">
          <div className="tt-amt__eyebrow">Returning to you</div>
          <div className="tt-amt__big tt-mono">{formatPaise(refund.amountPaise)}</div>
          <div style={{ fontSize: '12.5px', color: 'var(--tt-ink2)', lineHeight: 1.5 }}>
            Back to the instrument you paid with. Repeat requests return the same refund reference,
            so you cannot be refunded twice.
          </div>
          <div className="tt-chiprow">
            <Chip tone="g">No deduction</Chip>
            {result.refundId && <Chip tone="t">Reference recorded</Chip>}
          </div>
          <div className="tt-prog" aria-label={`Refund progress: step ${step} of 5`}>
            <span>Step {step} of 5</span>
            {[1, 2, 3, 4, 5].map((i) => <i key={i} className={i <= step ? 'on' : ''} />)}
          </div>
        </div>
      )}
      {result.refundId && (
        <Disclosure summary="References" icon="copy">
          <Kv label="Session">
            <span className="tt-mono" style={{ fontSize: '12px' }}>{result.id}</span>
          </Kv>
          <Kv label="Refund">
            <span className="tt-mono" style={{ fontSize: '12px' }}>{result.refundId}</span>
          </Kv>
          <Kv label="Reminders revoked">{result.remindersRevoked}</Kv>
        </Disclosure>
      )}
    </>
  );
}

/* -------------------------------- policy --------------------------------- */

function PolicyView({ session, go }: { session: TutoringSession; go: Go }) {
  const policy = policyPreview({ startUtcIso: session.startUtc, capturedPaise: 0 });
  return (
    <TutoringScreen
      screenId="S-35"
      dock={
        <Dock>
          <button
            type="button"
            className="tt-btn tt-btn--jade tt-btn--block"
            disabled={policy.started}
            aria-disabled={policy.started}
            aria-describedby={policy.started ? 'tt-resch-why' : undefined}
            onClick={() => go('reschedule')}
          >
            <Ic name="cal" />
            {policy.rescheduleFree ? 'Reschedule free' : 'Try to reschedule'}
          </button>
          <button type="button" className="tt-btn tt-btn--block" onClick={() => go('manage')}>
            <Ic name="back" />
            Back to the session
          </button>
        </Dock>
      }
    >
      <SessionHeading session={session} />
      <h2 className="tt-h">What happens if you cancel now</h2>
      <Banner
        tone={policy.rescheduleFree ? 'info' : 'warn'}
        title={
          policy.started
            ? 'The start has passed, so cancellation is closed'
            : policy.rescheduleFree
              ? 'Outside the notice window'
              : 'Inside the notice window'
        }
        detail={
          policy.started
            ? 'You can still go to attendance once the session ends.'
            : policy.rescheduleFree
              ? `At ${policy.hoursBeforeStart} hours before the start you are outside the ${policy.policyWindowHours} hour window, so the server assesses a full refund and a reschedule is free.`
              : `At ${policy.hoursBeforeStart} hours before the start you are inside the ${policy.policyWindowHours} hour window. No automatic refund and no free reschedule. Only an audited administrator exception moves money inside the window.`
        }
      />
      {policy.started && (
        <p className="tt-p tt-muted" id="tt-resch-why">
          Rescheduling is unavailable because the scheduled start has already passed.
        </p>
      )}
      <div className="tt-dis">
        <div className="tt-dis__body" style={{ paddingTop: '12px' }}>
          <Kv label="Free cancellation window">
            {policy.policyWindowHours} hours or more before the start
          </Kv>
          <Kv label="Boundary">Exactly {policy.policyWindowHours} hours is still free</Kv>
          <Kv label="Inside the window">Audited administrator exception only</Kv>
          <Kv label="Reschedule">Free outside the window, payment preserved</Kv>
        </div>
      </div>
      <p className="tt-svr">
        server-authoritative: the frozen policy computes every refund · this preview mirrors the
        same rule and never decides it
      </p>
    </TutoringScreen>
  );
}

/* ------------------------------ reschedule ------------------------------- */

function RescheduleView({
  session,
  go,
  onDone,
}: {
  session: TutoringSession;
  go: Go;
  onDone: () => void;
}) {
  const [announceRegion, announce] = useAnnouncer();
  const queryClient = useQueryClient();
  const [chosen, setChosen] = useState<string | null>(null);
  const params = useMemo(() => ({ timezone: session.ianaTimezone, limit: 50 }), [session.ianaTimezone]);
  const availability = useQuery({
    queryKey: tutoringKeys.availability(session.tutorId, params),
    queryFn: () => getAvailability(session.tutorId, params),
    retry: tutoringRetry,
    staleTime: 10_000,
  });

  const mutation = useMutation({
    mutationFn: (newSlotId: string) => rescheduleSession({
      sessionId: session.id,
      newSlotId,
      expectedVersion: session.version,
    }),
    retry: tutoringRetry,
    onSuccess: (result) => {
      queryClient.setQueryData(tutoringKeys.session(session.id), result);
      announce('Rescheduled. Your payment moved to the new time.');
      onDone();
      go('manage');
    },
  });

  const slots = (availability.data?.slots ?? []).filter((s) => s.slotId !== session.slotId);

  return (
    <TutoringScreen
      screenId="S-35"
      dock={
        <Dock>
          <button
            type="button"
            className="tt-btn tt-btn--jade tt-btn--block"
            disabled={!chosen || mutation.isPending}
            aria-disabled={!chosen || mutation.isPending}
            onClick={() => chosen && mutation.mutate(chosen)}
          >
            <Ic name="cal" />
            {mutation.isPending ? 'Moving your session' : 'Confirm the new time'}
          </button>
          <button type="button" className="tt-btn tt-btn--block" onClick={() => go('manage')}>
            <Ic name="back" />
            Back to the session
          </button>
        </Dock>
      }
    >
      {announceRegion}
      <SessionHeading session={session} />
      <h2 className="tt-h">Choose a new time</h2>
      <p className="tt-p">
        Times are shown in {session.ianaTimezone}, the zone kept with your session. Your payment
        moves with you and nothing is charged again.
      </p>

      {mutation.isError && (
        <TypedErrorState
          error={mutation.error}
          recoveryLabel="Reload this session"
          onRecover={onDone}
        />
      )}

      {availability.isPending && <LoadingState what="open times" />}
      {availability.isError && (
        <TypedErrorState error={availability.error} onRecover={() => availability.refetch()} />
      )}

      {availability.isSuccess && slots.length === 0 && (
        <EmptyState
          title="No other open times"
          detail="Your mentor has nothing else open right now. Keep this session, or cancel it and choose another mentor."
        />
      )}

      {slots.length > 0 && (
        <div className="tt-slots" role="radiogroup" aria-label="New session time">
          {slots.map((slot) => (
            <RescheduleSlot
              key={slot.slotId}
              slot={slot}
              zone={availability.data?.ianaTimezone ?? session.ianaTimezone}
              selected={chosen === slot.slotId}
              onSelect={() => setChosen(slot.slotId)}
            />
          ))}
        </div>
      )}

      <p className="tt-svr">
        server-authoritative: slot availability, the notice window and reminder revocation
      </p>
    </TutoringScreen>
  );
}

function RescheduleSlot({
  slot,
  zone,
  selected,
  onSelect,
}: {
  slot: AvailabilitySlot;
  zone: string;
  selected: boolean;
  onSelect: () => void;
}) {
  const bookable = slot.status === 'available';
  const labels = slotTimeLabels(slot.startUtc, slot.endUtc, zone);
  return (
    <button
      type="button"
      role="radio"
      aria-checked={selected}
      className="tt-slotbtn"
      disabled={!bookable}
      aria-disabled={!bookable}
      onClick={onSelect}
      style={selected ? { borderColor: 'var(--tt-jade)' } : undefined}
    >
      <span className="tt-sl">
        {labels.sessionZone}
        <small>
          {slot.durationMinutes} minutes · {labels.sessionZoneLabel}
          {labels.readerZone ? ` · your time ${labels.readerZone}` : ''}
        </small>
      </span>
      <Chip tone={bookable ? (selected ? 'g' : 'i') : slot.status === 'held' ? 't' : 'r'}>
        {bookable ? (selected ? 'Chosen' : 'Available') : slot.status === 'held' ? 'Held by another student' : 'Booked'}
      </Chip>
    </button>
  );
}

/* ------------------------------ attendance ------------------------------- */

const DISPUTE_LABELS: Record<AttendanceDisputeReasonCode, string> = {
  tutor_absent: 'My mentor did not attend',
  session_cut_short: 'The session ended much too early',
  wrong_session: 'This was not the session I booked',
  technical_failure: 'A technical failure stopped the session',
  other: 'Something else',
};

function AttendanceView({
  session,
  go,
  onDone,
}: {
  session: TutoringSession;
  go: Go;
  onDone: () => void;
}) {
  const [announceRegion, announce] = useAnnouncer();
  const [reasonCode, setReasonCode] = useState<AttendanceDisputeReasonCode>('tutor_absent');
  const [disputing, setDisputing] = useState(false);
  const state = session.attendanceState;
  const version = session.attendanceVersion ?? undefined;

  const confirmMutation = useMutation({
    mutationFn: () => confirmAttendance({ sessionId: session.id, expectedVersion: version }),
    retry: tutoringRetry,
    onSuccess: (record) => {
      announce(`Attendance ${record.state}. Your review is now open.`);
      onDone();
    },
  });

  const disputeMutation = useMutation({
    mutationFn: () => disputeAttendance({
      sessionId: session.id,
      expectedVersion: version,
      reasonCode,
    }),
    retry: tutoringRetry,
    onSuccess: (record) => {
      setDisputing(false);
      announce(`Attendance ${record.state}. An administrator will review it.`);
      onDone();
    },
  });

  const banner = (() => {
    switch (state) {
      case null:
      case undefined:
      case 'pending':
        return {
          tone: 'info' as const,
          title: 'Attendance is not decided yet',
          detail: 'Attendance opens after the scheduled end. Your mentor records it first, then you confirm or dispute it.',
        };
      case 'recorded':
        return {
          tone: 'info' as const,
          title: 'Your mentor recorded this session as attended',
          detail: 'Confirm it if that matches what happened, or dispute it and an administrator will look at the case.',
        };
      case 'confirmed':
        return {
          tone: 'ok' as const,
          title: 'You confirmed attendance',
          detail: 'Thank you. Your review is now open.',
        };
      case 'disputed':
        return {
          tone: 'warn' as const,
          title: 'Your dispute is open',
          detail: 'An administrator is reviewing this. Reviewing stays closed until it is resolved, and nothing more is needed from you.',
        };
      case 'resolved':
        return {
          tone: 'ok' as const,
          title: 'The dispute was resolved',
          detail: 'An administrator decided the outcome and recorded it against this session.',
        };
      default:
        return {
          tone: 'info' as const,
          title: `Attendance is ${state}`,
          detail: 'This is the state the server currently holds for this session.',
        };
    }
  })();

  return (
    <TutoringScreen
      screenId="S-35"
      dock={
        <Dock>
          {state === 'recorded' ? (
            <button
              type="button"
              className="tt-btn tt-btn--jade tt-btn--block"
              disabled={confirmMutation.isPending}
              onClick={() => confirmMutation.mutate()}
            >
              <Ic name="check" />
              {confirmMutation.isPending ? 'Confirming' : 'Confirm attendance'}
            </button>
          ) : state === 'confirmed' ? (
            <button type="button" className="tt-btn tt-btn--jade tt-btn--block" onClick={() => go('review')}>
              <Ic name="star" />
              Leave a review
            </button>
          ) : (
            <button type="button" className="tt-btn tt-btn--jade tt-btn--block" onClick={onDone}>
              <Ic name="clock" />
              Refresh attendance
            </button>
          )}
          {state === 'recorded' && (
            <button
              type="button"
              className="tt-btn tt-btn--block"
              style={{ minHeight: 'var(--tt-target-min)' }}
              onClick={() => setDisputing(true)}
            >
              <Ic name="warn" />
              Dispute this
            </button>
          )}
        </Dock>
      }
    >
      {announceRegion}
      <button type="button" className="tt-btn" style={{ alignSelf: 'flex-start' }} onClick={() => go('manage')}>
        <Ic name="back" />
        Back to the session
      </button>
      <SessionHeading session={session} />
      <Banner
        tone={banner.tone}
        title={banner.title}
        detail={banner.detail}
        code={state ? `ATTENDANCE_${String(state).toUpperCase()}` : undefined}
      />

      {confirmMutation.isError && (
        <TypedErrorState error={confirmMutation.error} recoveryLabel="Reload attendance" onRecover={onDone} />
      )}
      {disputeMutation.isError && (
        <TypedErrorState error={disputeMutation.error} recoveryLabel="Reload attendance" onRecover={onDone} />
      )}

      <Disclosure summary="What each state means" icon="info">
        <Kv label="Before the scheduled end">ATTENDANCE_TOO_EARLY</Kv>
        <Kv label="Someone changed it first">ATTENDANCE_STALE_VERSION</Kv>
        <Kv label="Action does not apply">ATTENDANCE_STATE_INVALID</Kv>
        <Kv label="Not your session">NOT_FOUND</Kv>
        <p className="tt-p tt-muted">
          Every refusal above leaves the record exactly as it was. Reload and read the current state.
        </p>
      </Disclosure>

      <p className="tt-svr">
        server-authoritative: attendance state, its version and every dispute resolution
      </p>

      {disputing && (
        <Modal title="Dispute this attendance record?" onDismiss={() => setDisputing(false)}>
          <p className="tt-p" style={{ fontSize: '13px' }}>
            Choose the closest reason. We send a code, not a description, because it reaches
            operators and the audit trail. Do not include anyone&apos;s personal details.
          </p>
          <div className="tt-fld">
            <label htmlFor="tt-reason">Reason</label>
            <select
              id="tt-reason"
              className="tt-in tt-sel"
              value={reasonCode}
              onChange={(event) => setReasonCode(event.target.value as AttendanceDisputeReasonCode)}
            >
              {ATTENDANCE_DISPUTE_REASON_CODES.map((code) => (
                <option key={code} value={code}>{DISPUTE_LABELS[code]}</option>
              ))}
            </select>
          </div>
          <button
            type="button"
            className="tt-btn tt-btn--terra tt-btn--block"
            disabled={disputeMutation.isPending}
            onClick={() => disputeMutation.mutate()}
          >
            <Ic name="warn" />
            {disputeMutation.isPending ? 'Submitting' : 'Submit the dispute'}
          </button>
          <button type="button" className="tt-btn tt-btn--block" onClick={() => setDisputing(false)}>
            <Ic name="close" />
            Cancel
          </button>
        </Modal>
      )}
    </TutoringScreen>
  );
}

/* -------------------------------- review --------------------------------- */

function ReviewView({ session, go }: { session: TutoringSession; go: Go }) {
  const [announceRegion, announce] = useAnnouncer();
  const [rating, setRating] = useState(0);
  const [body, setBody] = useState('');
  const [submitted, setSubmitted] = useState(false);
  const attendanceConfirmed = session.attendanceState === 'confirmed';

  const validation = validateReview(rating || undefined, body);
  const mutation = useMutation({
    mutationFn: () => createReview({
      sessionId: session.id,
      rating,
      ...(body.trim() ? { body: body.trim() } : {}),
    }),
    retry: tutoringRetry,
    onSuccess: () => {
      setSubmitted(true);
      announce('Your review was submitted and is now with moderation.');
    },
  });

  const blocked = mutation.error instanceof TutoringApiError
    && mutation.error.code === REVIEW_BLOCKED;

  if (submitted) {
    return (
      <TutoringScreen
        screenId="S-35"
        dock={
          <Dock>
            <button type="button" className="tt-btn tt-btn--jade tt-btn--block" onClick={() => go('manage')}>
              <Ic name="back" />
              Back to the session
            </button>
          </Dock>
        }
      >
        {announceRegion}
        <SessionHeading session={session} />
        <Banner
          tone="ok"
          title="Thank you, your review was submitted"
          detail="It goes to moderation before it appears on the mentor profile, so it is not counted in the public average yet."
        />
      </TutoringScreen>
    );
  }

  return (
    <TutoringScreen
      screenId="S-35"
      dock={
        <Dock>
          <button
            type="button"
            className="tt-btn tt-btn--jade tt-btn--block"
            disabled={!attendanceConfirmed || !validation.ok || mutation.isPending}
            aria-disabled={!attendanceConfirmed || !validation.ok || mutation.isPending}
            aria-describedby="tt-review-why"
            onClick={() => mutation.mutate()}
          >
            <Ic name="star" />
            {mutation.isPending ? 'Submitting' : 'Submit review'}
          </button>
          <button type="button" className="tt-btn tt-btn--block" onClick={() => go('manage')}>
            <Ic name="back" />
            Back to the session
          </button>
        </Dock>
      }
    >
      {announceRegion}
      <SessionHeading session={session} />

      {!attendanceConfirmed && (
        <Banner
          tone="warn"
          title="Reviewing is locked until attendance is confirmed"
          detail={
            session.attendanceState === 'disputed'
              ? 'Your dispute is still open, so reviewing stays closed until an administrator resolves it.'
              : 'A review needs a confirmed attendance record. Confirm attendance first and come straight back.'
          }
          code={REVIEW_BLOCKED}
        />
      )}
      {!attendanceConfirmed && (
        <button type="button" className="tt-btn tt-btn--block" onClick={() => go('attendance')}>
          <Ic name="check" />
          Go to attendance
        </button>
      )}

      <fieldset style={{ border: 'none', padding: 0, margin: 0 }}>
        <legend className="tt-h" style={{ fontSize: '13px', fontWeight: 800, padding: '0 0 8px' }}>
          Your rating, 1 to {REVIEW_MAX_RATING} stars
        </legend>
        <div className="tt-stars" role="radiogroup" aria-label={`Rating out of ${REVIEW_MAX_RATING}`}>
          {[1, 2, 3, 4, 5].map((value) => (
            <label key={value} className="tt-star" data-on={value <= rating ? '1' : '0'}>
              <input
                className="tt-sr"
                type="radio"
                name="tt-rating"
                value={value}
                checked={rating === value}
                onChange={() => setRating(value)}
              />
              <span className="tt-sr">{value} star{value === 1 ? '' : 's'}</span>
              <Ic name="star" />
            </label>
          ))}
        </div>
      </fieldset>

      <div className="tt-fld">
        <label htmlFor="tt-review-body">
          What was useful? Optional, and {REVIEW_MIN_BODY} to {REVIEW_MAX_BODY} characters if you write one
        </label>
        <textarea
          id="tt-review-body"
          className="tt-in"
          rows={5}
          maxLength={REVIEW_MAX_BODY}
          value={body}
          aria-describedby="tt-review-count"
          aria-invalid={validation.codes.includes('REVIEW_TEXT_TOO_SHORT') || undefined}
          onChange={(event) => setBody(event.target.value)}
          style={{ minHeight: '110px' }}
        />
        <span className="tt-muted" id="tt-review-count" aria-live="polite">
          {validation.length} of {REVIEW_MAX_BODY} characters
          {validation.codes.includes('REVIEW_TEXT_TOO_SHORT')
            && ` · at least ${REVIEW_MIN_BODY} needed`}
        </span>
      </div>

      <p className="tt-p tt-muted" id="tt-review-why">
        {!attendanceConfirmed
          ? 'Submitting is unavailable because attendance is not confirmed.'
          : validation.codes.includes('REVIEW_RATING_OUT_OF_RANGE')
            ? 'Choose a rating between 1 and 5 stars to submit.'
            : validation.codes.includes('REVIEW_TEXT_TOO_SHORT')
              ? `Your text needs at least ${REVIEW_MIN_BODY} characters, or leave it empty.`
              : 'Ready to submit. The server checks these limits again and its verdict is final.'}
      </p>

      {mutation.isError && (
        <TypedErrorState
          error={mutation.error}
          recoveryLabel={blocked ? 'Go to attendance' : undefined}
          onRecover={blocked ? () => go('attendance') : undefined}
        />
      )}

      <Banner
        tone="info"
        title="Reviews are moderated"
        detail="Do not include the names of other people, case numbers, or anything you would not want published."
      />

      <p className="tt-svr">
        server-authoritative: review eligibility, the 1 to 5 and {REVIEW_MIN_BODY} to
        {' '}{REVIEW_MAX_BODY} limits, moderation and the public aggregate
      </p>
    </TutoringScreen>
  );
}

/* ------------------------- pre-join / device check ------------------------ */

type MediaProblem =
  | 'permission_denied'
  | 'no_device'
  | 'device_busy'
  | 'unsupported'
  | 'insecure'
  | 'constraint'
  | 'unknown';

function classifyMediaError(error: unknown): MediaProblem {
  const name = (error as { name?: string } | null)?.name ?? '';
  if (name === 'NotAllowedError' || name === 'SecurityError') return 'permission_denied';
  if (name === 'NotFoundError') return 'no_device';
  if (name === 'NotReadableError' || name === 'AbortError') return 'device_busy';
  if (name === 'OverconstrainedError') return 'constraint';
  return 'unknown';
}

const MEDIA_COPY: Record<MediaProblem, { title: string; detail: string; recovery: string }> = {
  permission_denied: {
    title: 'Your browser is blocking the camera or microphone',
    detail: 'Open the site permissions in your address bar, allow camera and microphone, then test again. You can also enter with audio only.',
    recovery: 'Test again',
  },
  no_device: {
    title: 'No camera or microphone found',
    detail: 'Connect a device and test again. You can still enter to listen.',
    recovery: 'Test again',
  },
  device_busy: {
    title: 'Your camera is in use by another app',
    detail: 'Close the other video app, then test again.',
    recovery: 'Test again',
  },
  unsupported: {
    title: 'This browser cannot run video sessions',
    detail: 'Open the session in the current version of Chrome, Edge, Safari or Firefox.',
    recovery: 'Test again',
  },
  insecure: {
    title: 'This page is not on a secure connection',
    detail: 'Video needs a secure connection. Open the session from the secure link in your confirmation.',
    recovery: 'Test again',
  },
  constraint: {
    title: 'Your camera cannot use the requested quality',
    detail: 'Retry in standard quality to continue.',
    recovery: 'Retry in standard quality',
  },
  unknown: {
    title: 'The device test did not complete',
    detail: 'Nothing was recorded and nothing left your browser. Try the test again.',
    recovery: 'Test again',
  },
};

/**
 * Local media handle. Deliberately narrow: counts and ids only.
 * `label` is NEVER read from `enumerateDevices()`, so no device name exists in
 * this process to leak into state, a log or the DOM.
 */
interface DeviceCensus {
  cameras: number;
  microphones: number;
}

function PreJoinView({ session, go }: { session: TutoringSession; go: Go }) {
  const [announceRegion, announce] = useAnnouncer();
  const [problem, setProblem] = useState<MediaProblem | null>(null);
  const [tested, setTested] = useState(false);
  const [census, setCensus] = useState<DeviceCensus>({ cameras: 0, microphones: 0 });
  const [camOn, setCamOn] = useState(true);
  const video = useRef<HTMLVideoElement | null>(null);
  const stream = useRef<MediaStream | null>(null);

  const release = useCallback(() => {
    stream.current?.getTracks().forEach((track) => track.stop());
    stream.current = null;
    if (video.current) video.current.srcObject = null;
  }, []);

  useEffect(() => release, [release]);

  /**
   * Bind the live track to the element AFTER render. The element is always in
   * the tree (the off state is an overlay, not a replacement), so the ref can
   * never be null at the moment a track arrives.
   */
  useEffect(() => {
    if (video.current && stream.current) video.current.srcObject = stream.current;
  }, [camOn, tested]);

  const test = useCallback(async (audioOnly: boolean) => {
    setProblem(null);
    if (typeof window === 'undefined' || !window.isSecureContext) {
      setProblem('insecure');
      return;
    }
    if (!navigator.mediaDevices?.getUserMedia) {
      setProblem('unsupported');
      return;
    }
    release();
    try {
      const media = await navigator.mediaDevices.getUserMedia({
        audio: true,
        video: audioOnly ? false : true,
      });
      stream.current = media;
      if (video.current && !audioOnly) video.current.srcObject = media;
      setCamOn(!audioOnly);
      setTested(true);
      // Count only. `device.label` is intentionally not read.
      const devices = await navigator.mediaDevices.enumerateDevices();
      setCensus({
        cameras: devices.filter((d) => d.kind === 'videoinput').length,
        microphones: devices.filter((d) => d.kind === 'audioinput').length,
      });
      announce(audioOnly ? 'Microphone ready. Camera off.' : 'Camera and microphone ready.');
    } catch (error) {
      setProblem(classifyMediaError(error));
      announce('The device test did not complete.');
    }
  }, [announce, release]);

  const copy = problem ? MEDIA_COPY[problem] : null;
  const labels = slotTimeLabels(session.startUtc, session.endUtc, session.ianaTimezone);

  return (
    <TutoringScreen
      screenId="S-35"
      dock={
        <Dock>
          <button
            type="button"
            className="tt-btn tt-btn--jade tt-btn--block"
            onClick={() => (tested ? go('room') : void test(false))}
          >
            <Ic name={tested ? 'join' : 'dev'} />
            {tested ? 'Enter the room' : 'Test camera and microphone'}
          </button>
          <div className="tt-dockrow">
            {problem === 'permission_denied' || problem === 'no_device' ? (
              <button type="button" className="tt-btn" onClick={() => void test(true)}>
                <Ic name="mic" />
                Enter with audio only
              </button>
            ) : (
              <button type="button" className="tt-btn" onClick={() => go('manage')}>
                <Ic name="back" />
                Back to the session
              </button>
            )}
          </div>
        </Dock>
      }
    >
      {announceRegion}
      <div>
        <div className="tt-eyebrow">Before you enter</div>
        <h1 className="tt-h tt-arrival" style={{ marginTop: '4px', fontSize: '19px' }}>
          Room entry check
        </h1>
        <p className="tt-p" style={{ fontSize: '12.5px' }}>
          {labels.sessionZone} · {labels.sessionZoneLabel}
        </p>
      </div>

      {copy ? (
        <>
          <Banner tone="err" title={copy.title} detail={copy.detail} code={problem?.toUpperCase()} />
          <button type="button" className="tt-btn tt-btn--block" onClick={() => void test(false)}>
            {copy.recovery}
          </button>
        </>
      ) : (
        <Banner
          tone="info"
          title={tested ? 'Your devices are ready' : 'Test your camera and microphone'}
          detail="Nothing is recorded, and no device name leaves your browser. Entry itself is a server decision, asked for when you enter."
        />
      )}

      <div className="tt-preview">
        <video ref={video} autoPlay playsInline muted aria-label="Your camera preview" />
        {!(camOn && tested) && (
          <div className="tt-preview__off">
            <Ic name="camOff" />
            <div style={{ marginTop: '8px' }}>
              {tested ? 'Camera off' : 'Camera preview starts when you test'}
            </div>
          </div>
        )}
      </div>

      {tested && (
        <div className="tt-chiprow">
          <Chip tone="i">{census.cameras} camera{census.cameras === 1 ? '' : 's'} detected</Chip>
          <Chip tone="i">{census.microphones} microphone{census.microphones === 1 ? '' : 's'} detected</Chip>
        </div>
      )}

      <p className="tt-p tt-muted">
        No media, device name or join credential is written to the address bar, this
        browser&apos;s storage, a cookie or any log.
      </p>

      <p className="tt-svr">
        server-authoritative: entry eligibility, credential lifetime and ownership · the client
        never grants itself entry
      </p>
    </TutoringScreen>
  );
}

/* ================================ live room ============================== */

type SelfPosition = 'br' | 'bl' | 'tl' | 'tr';
const POSITIONS: SelfPosition[] = ['br', 'bl', 'tl', 'tr'];
const POSITION_WORDS: Record<SelfPosition, string> = {
  br: 'bottom right',
  bl: 'bottom left',
  tl: 'top left',
  tr: 'top right',
};

function LiveRoom({ sessionId, go }: { sessionId: string; go: Go }) {
  const [announceRegion, announce] = useAnnouncer();

  /**
   * THE RAW CREDENTIAL LIVES HERE AND ONLY HERE.
   * A ref, not React state and not a query cache entry, so it is never part of
   * a serialisable render tree, never a query key and never persisted. Render
   * state gets the redacted projection instead.
   */
  const rawCredential = useRef<JoinCredential | null>(null);
  const [credential, setCredential] = useState<RedactedJoinCredential | null>(null);
  const [issueError, setIssueError] = useState<unknown>(null);
  const [micOn, setMicOn] = useState(true);
  const [camOn, setCamOn] = useState(true);
  const [sheetOpen, setSheetOpen] = useState(false);
  const [selfMin, setSelfMin] = useState(false);
  const [selfPos, setSelfPos] = useState<SelfPosition>('br');
  const [leaveOpen, setLeaveOpen] = useState(false);
  const [elapsed, setElapsed] = useState(0);

  const video = useRef<HTMLVideoElement | null>(null);
  const stream = useRef<MediaStream | null>(null);
  const infoButton = useRef<HTMLButtonElement | null>(null);
  const sheetClose = useRef<HTMLButtonElement | null>(null);

  const session = useQuery({
    queryKey: tutoringKeys.session(sessionId),
    queryFn: () => getTutoringSession(sessionId),
    retry: tutoringRetry,
    staleTime: 30_000,
  });

  /* ------- page scroll is disabled for the room family, and only there ----- */
  useEffect(() => {
    const root = document.documentElement;
    const body = document.body;
    root.setAttribute('data-tt-room', '1');
    body.setAttribute('data-tt-room', '1');
    return () => {
      root.removeAttribute('data-tt-room');
      body.removeAttribute('data-tt-room');
    };
  }, []);

  /* ---------------- local media, released on leave and unmount ------------- */
  const releaseMedia = useCallback(() => {
    stream.current?.getTracks().forEach((track) => track.stop());
    stream.current = null;
    if (video.current) video.current.srcObject = null;
  }, []);

  useEffect(() => {
    let cancelled = false;
    const open = async (): Promise<void> => {
      if (!navigator.mediaDevices?.getUserMedia) return;
      try {
        const media = await navigator.mediaDevices.getUserMedia({ audio: true, video: true });
        if (cancelled) {
          media.getTracks().forEach((t) => t.stop());
          return;
        }
        stream.current = media;
        if (video.current) video.current.srcObject = media;
      } catch {
        // The pre-join check already explains every refusal; the room simply
        // shows the camera-off tile rather than repeating the diagnosis.
        setCamOn(false);
      }
    };
    void open();
    return () => { cancelled = true; releaseMedia(); };
  }, [releaseMedia]);

  /* ------------------------ E1: ask for the credential -------------------- */
  useEffect(() => {
    let cancelled = false;
    const issue = async (): Promise<void> => {
      try {
        const issued = await issueJoinCredentials(sessionId);
        if (cancelled) return;
        rawCredential.current = issued;
        setCredential(redactJoinCredential(issued));
        setIssueError(null);
        announce('You are in the room.');
      } catch (error) {
        if (!cancelled) setIssueError(error);
      }
    };
    void issue();
    return () => {
      cancelled = true;
      // Drop the secret the moment the room goes away.
      rawCredential.current = null;
    };
  }, [sessionId, announce]);

  useEffect(() => {
    const timer = window.setInterval(() => setElapsed((value) => value + 1), 1000);
    return () => window.clearInterval(timer);
  }, []);

  const toggleMic = (): void => {
    const next = !micOn;
    setMicOn(next);
    stream.current?.getAudioTracks().forEach((track) => { track.enabled = next; });
    announce(next ? 'Microphone on' : 'Microphone muted');
  };

  const toggleCam = (): void => {
    const next = !camOn;
    setCamOn(next);
    // Stopping the track is what actually releases the device indicator.
    stream.current?.getVideoTracks().forEach((track) => { track.enabled = next; });
    announce(next ? 'Camera on' : 'Camera off');
  };

  const openSheet = (): void => {
    setSheetOpen(true);
    announce('Session details opened');
    requestAnimationFrame(() => sheetClose.current?.focus());
  };

  const closeSheet = (): void => {
    setSheetOpen(false);
    announce('Session details closed');
    infoButton.current?.focus();
  };

  useEffect(() => {
    if (!sheetOpen) return;
    const onKey = (event: KeyboardEvent): void => {
      if (event.key === 'Escape') { event.preventDefault(); closeSheet(); }
    };
    document.addEventListener('keydown', onKey);
    return () => document.removeEventListener('keydown', onKey);
    // closeSheet is stable enough for the sheet's lifetime.
  }, [sheetOpen]);

  const leave = (): void => {
    releaseMedia();
    rawCredential.current = null;
    setCredential(null);
    setLeaveOpen(false);
    go('attendance');
  };

  const moveSelf = (): void => {
    const next = POSITIONS[(POSITIONS.indexOf(selfPos) + 1) % POSITIONS.length];
    setSelfPos(next);
    announce(`Self-view moved to ${POSITION_WORDS[next]}`);
  };

  const clock = `${String(Math.floor(elapsed / 60)).padStart(2, '0')}:${String(elapsed % 60).padStart(2, '0')}`;
  const minutes = session.data ? durationMinutes(session.data.startUtc, session.data.endUtc) : null;
  const labels = session.data
    ? slotTimeLabels(session.data.startUtc, session.data.endUtc, session.data.ianaTimezone)
    : null;

  return (
    <TutoringScreen screenId="S-35" bare>
      {announceRegion}
      <div className="tt-live-host">
        <main className="tt-live" data-family="room">
          <div className="tt-lh">
            <Chip tone="g">{issueError ? 'Not admitted' : credential ? 'In the room' : 'Joining'}</Chip>
            <span className="t">Mentoring session</span>
            <span className="tt-grow" />
            <span className="m">{clock}</span>
            <button
              type="button"
              className="tt-cb"
              ref={infoButton}
              aria-label="Session, connection and privacy details"
              aria-expanded={sheetOpen}
              onClick={openSheet}
            >
              <Ic name="info" />
            </button>
          </div>

          <div className="tt-stage">
            <div className="tt-mtile">
              <svg viewBox="0 0 420 830" preserveAspectRatio="xMidYMid slice" aria-hidden focusable="false">
                <defs>
                  <linearGradient id="tt-room-bg" x1="0" y1="0" x2=".3" y2="1">
                    <stop offset="0" stopColor="var(--tt-room-1)" />
                    <stop offset=".55" stopColor="var(--tt-room-2)" />
                    <stop offset="1" stopColor="var(--tt-room-3)" />
                  </linearGradient>
                </defs>
                <rect width="420" height="830" fill="url(#tt-room-bg)" />
              </svg>

              {issueError ? (
                <div className="tt-veil">
                  <b>You are not admitted to this room</b>
                  <span>
                    The server refused the entry credential, so no room was opened and no media was
                    sent. The reason is below.
                  </span>
                </div>
              ) : !credential ? (
                <div className="tt-veil">
                  <b>Asking the server for entry</b>
                  <span>
                    Entry is a server decision. Your camera and microphone are open locally only
                    until it answers.
                  </span>
                </div>
              ) : (
                <div className="tt-veil">
                  <b>Waiting for your mentor&apos;s stream</b>
                  <span>
                    Your entry is authorised for room {credential.roomRef}. The media transport
                    itself is not contracted yet, so no remote stream is claimed here.
                  </span>
                </div>
              )}

              {issueError ? (
                <div className="tt-rbanner tt-rbanner--err" role="alert">
                  <Ic name="warn" />
                  <div>
                    <div className="tt-banner__t">
                      {issueError instanceof TutoringApiError ? issueError.code : 'ENTRY_REFUSED'}
                    </div>
                    <div className="tt-banner__d">
                      {issueError instanceof TutoringApiError
                        ? issueError.serverMessage
                        : 'The request did not reach LegalSaathi.'}
                    </div>
                  </div>
                </div>
              ) : null}

              <div className="tt-nm">
                Mentor
                <span
                  style={{ width: '8px', height: '8px', borderRadius: '50%', background: 'var(--tt-jade)' }}
                  aria-hidden
                />
              </div>
            </div>

            <div className="tt-self" data-min={selfMin ? '1' : '0'} data-pos={selfPos}>
              {/* Always mounted so the ref exists when a track arrives; the
                  camera-off state is an overlay, never a swapped element. */}
              <video ref={video} autoPlay playsInline muted aria-label="Your camera tile" />
              {!camOn && (
                <svg
                  viewBox="0 0 100 130"
                  aria-hidden
                  focusable="false"
                  style={{ position: 'absolute', inset: 0 }}
                >
                  <rect width="100" height="130" fill="var(--tt-studio2)" />
                </svg>
              )}
              <div className="tt-nm2">{camOn ? 'You' : 'Camera off'}</div>
              <div className="tt-selfctl">
                <button
                  type="button"
                  className="tt-sb tt-selfmove"
                  aria-label={`Move self-view, currently ${POSITION_WORDS[selfPos]}`}
                  onClick={moveSelf}
                >
                  <Ic name="move" />
                </button>
                <button
                  type="button"
                  className="tt-sb"
                  aria-pressed={selfMin}
                  aria-label={selfMin ? 'Restore self-view' : 'Minimise self-view'}
                  onClick={() => {
                    setSelfMin(!selfMin);
                    announce(selfMin ? 'Self-view restored' : 'Self-view minimised');
                  }}
                >
                  <Ic name="min" />
                </button>
              </div>
            </div>
          </div>

          <div className="tt-lctrl">
            <button
              type="button"
              className="tt-cb"
              aria-pressed={!micOn}
              aria-label={micOn ? 'Mute microphone' : 'Unmute microphone'}
              onClick={toggleMic}
            >
              <Ic name={micOn ? 'mic' : 'micOff'} />
            </button>
            <button
              type="button"
              className="tt-cb"
              aria-pressed={!camOn}
              aria-label={camOn ? 'Turn camera off' : 'Turn camera on'}
              onClick={toggleCam}
            >
              <Ic name={camOn ? 'cam' : 'camOff'} />
            </button>
            <button
              type="button"
              className="tt-cb"
              aria-label="Device settings"
              onClick={() => { releaseMedia(); go('prejoin'); }}
            >
              <Ic name="dev" />
            </button>
            <button
              type="button"
              className="tt-cb tt-cb--leave"
              onClick={() => setLeaveOpen(true)}
            >
              <Ic name="leave" />
              <span>Leave</span>
            </button>
          </div>

          <div
            className="tt-sheet"
            role="dialog"
            aria-modal="false"
            aria-label="Session details"
            data-open={sheetOpen ? '1' : '0'}
          >
            <div className="tt-grab" aria-hidden />
            <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
              <h2 className="tt-h" style={{ fontSize: '17px' }}>Session details</h2>
              <span className="tt-grow" />
              <button
                type="button"
                className="tt-ib"
                ref={sheetClose}
                aria-label="Close session details"
                onClick={closeSheet}
              >
                <Ic name="close" />
              </button>
            </div>
            <div className="tt-kv"><span>Elapsed</span><b className="tt-mono">{clock}</b></div>
            {labels && <div className="tt-kv"><span>Scheduled</span><b>{labels.sessionZone}</b></div>}
            {labels && <div className="tt-kv"><span>Session timezone</span><b>{labels.sessionZoneLabel}</b></div>}
            {minutes !== null && <div className="tt-kv"><span>Length</span><b>{minutes} minutes</b></div>}
            {credential && (
              <>
                <div className="tt-kv">
                  <span>Room</span>
                  <b className="tt-mono" style={{ fontSize: '12px' }}>{credential.roomRef}</b>
                </div>
                <div className="tt-kv">
                  <span>Your participant reference</span>
                  <b className="tt-mono" style={{ fontSize: '12px' }}>{credential.participantRef}</b>
                </div>
                <div className="tt-kv">
                  {/* The projection carries the literal "[redacted]": the raw
                      token never reaches render state at all. */}
                  <span>Entry credential</span>
                  <b className="tt-mono" style={{ fontSize: '12px' }}>
                    {credential.joinToken} · in memory only
                  </b>
                </div>
                <div className="tt-kv">
                  <span>Credential expires</span>
                  <b>{credential.ttlSeconds} seconds after issue</b>
                </div>
              </>
            )}
            <p className="tt-p tt-muted" style={{ marginTop: '8px' }}>
              No media, device name or join credential is kept in this browser. Leaving releases
              your camera and microphone.
            </p>
          </div>
          {sheetOpen && (
            <button
              type="button"
              className="tt-sheet-scrim"
              aria-label="Close session details"
              onClick={closeSheet}
            />
          )}

          {leaveOpen && (
            <Modal title="Leave this session?" onDismiss={() => setLeaveOpen(false)}>
              <p className="tt-p" style={{ fontSize: '13px' }}>
                Your camera and microphone are released when you leave, and your entry credential is
                dropped. You can ask to enter again while the session is running.
              </p>
              <button type="button" className="tt-btn tt-btn--terra tt-btn--block" onClick={leave}>
                <Ic name="leave" />
                Leave the session
              </button>
              <button type="button" className="tt-btn tt-btn--block" onClick={() => setLeaveOpen(false)}>
                <Ic name="close" />
                Stay in the room
              </button>
            </Modal>
          )}
        </main>
      </div>
    </TutoringScreen>
  );
}
