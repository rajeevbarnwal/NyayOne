/**
 * S-33 `tutoring/hold` and S-34 `tutoring/detail` (SAATHI-65, matrix B1, C1, D1).
 *
 *   S-33  POST /api/v1/tutoring/booking-holds        (one winner per slot)
 *         GET  /api/v1/tutoring/booking-holds/{id}   (server truth on expiry)
 *         POST /api/v1/payments/orders               (tokenised, provider-hosted)
 *         POST /api/v1/tutoring/sessions             (only for a PAID hold)
 *   S-34  GET  /api/v1/tutoring/sessions/{id}        (confirmed session detail)
 *
 * PAYMENT PRIVACY (matrix J1 / decision D-05). This file contains no input for a
 * card number, expiry, security code or authentication code, and no state that
 * could hold one. The card step is rendered as the provider's hosted surface;
 * the only secret that crosses this boundary is a provider token, and the
 * adapter refuses anything that is not `tok_…` before it reaches the network.
 * Nothing here writes to localStorage, sessionStorage, a cookie or the URL
 * beyond the opaque slot / hold / session ids that already appear in the route.
 */
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { Link, useNavigate, useSearchParams } from 'react-router-dom';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import {
  HOLD_CONFLICT,
  HOLD_EXPIRED,
  PAYMENT_UNVERIFIED,
  SLOT_UNAVAILABLE,
  TutoringApiError,
  createBookingHold,
  createPaymentOrder,
  createTutoringSession,
  getAvailability,
  getBookingHold,
  getTutoringSession,
  newIdempotencyKey,
  tutoringKeys,
  tutoringRetry,
  type BookingHold,
  type PaymentOrder,
} from '../lib/tutoringApi';
import {
  DEFAULT_HOLD_MINUTES,
  DEFAULT_REFUND_FREE_CANCEL_HOURS,
  browserTimeZone,
  durationMinutes,
  formatPaise,
  holdCountdown,
  policyPreview,
  slotTimeLabels,
  type HoldCountdown,
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

/**
 * FEE — the amount is the SERVER's, and this screen only renders it.
 *
 * This used to read `VITE_TUTORING_SESSION_FEE_PAISE` (a build-time deployment
 * setting) and hand the result to `POST /payments/orders`, because P3 published
 * no price. That made the price CLIENT-AUTHORITATIVE: a caller could propose
 * any amount, and a correctly signed provider callback then only proved payment
 * of the amount the caller chose. Both the env read and the
 * `AMOUNT_NOT_PUBLISHED` state that depended on it are gone.
 *
 * The API now publishes the price — `price_paise` on an availability slot and,
 * once the slot is reserved, the immutable snapshot on the hold — so this screen
 * reads `hold.pricePaise` (falling back to the slot's published price while the
 * hold is still in flight) and renders it. The amount is still forwarded on the
 * order request, but ONLY as an optimistic confirmation of what was displayed:
 * the server charges its own number and answers a disagreement with the typed
 * `PAYMENT_AMOUNT_MISMATCH`. Money stays INTEGER PAISE end to end; `formatPaise`
 * is the only thing that ever turns paise into rupees.
 */
type CheckoutStage = 'holding' | 'summary' | 'authorising' | 'awaiting' | 'confirmed';

/* ========================================================================== *
 * S-33 — booking hold and the tokenised payment step
 * ========================================================================== */

export function BookingHoldScreen() {
  const [sp] = useSearchParams();
  const slotId = sp.get('slot') ?? '';
  const tutorId = sp.get('tutor') ?? '';
  const queryClient = useQueryClient();
  const navigate = useNavigate();
  const [announceRegion, announce] = useAnnouncer();
  useRouteArrival(`S-33:${slotId}`);
  const backToProfile = useCallback(
    () => navigate(`/s-32?tutor=${encodeURIComponent(tutorId)}`),
    [navigate, tutorId],
  );

  /**
   * One idempotency key per booking ATTEMPT, held in component memory. Reusing
   * it is what makes a repeat submit replay instead of double charging; a fresh
   * attempt asks for a new key.
   */
  const holdKey = useRef(newIdempotencyKey('hold'));
  const orderKey = useRef(newIdempotencyKey('order'));

  const [hold, setHold] = useState<BookingHold | null>(null);
  const [order, setOrder] = useState<PaymentOrder | null>(null);
  const [stage, setStage] = useState<CheckoutStage>('holding');
  const [leaveOpen, setLeaveOpen] = useState(false);
  const [urgencyAnnounced, setUrgencyAnnounced] = useState(false);

  /* -------- the slot itself, so the screen can name what is being held ----- */
  const availabilityParams = useMemo(() => ({ limit: 50 }), []);
  const availability = useQuery({
    queryKey: tutoringKeys.availability(tutorId, availabilityParams),
    queryFn: () => getAvailability(tutorId, availabilityParams),
    enabled: Boolean(tutorId),
    retry: tutoringRetry,
    staleTime: 10_000,
  });
  const slot = availability.data?.slots.find((s) => s.slotId === slotId);

  /**
   * The payable amount, in INTEGER PAISE, straight from the server. The hold's
   * snapshot wins once it exists (it is the number the order will be charged
   * at); the slot's published price fills the moment before that. `null` means
   * "not loaded yet", never "guess one".
   */
  const feePaise: number | null = hold?.pricePaise ?? slot?.pricePaise ?? null;

  /* -------------------------------- B1 hold ------------------------------- */
  const holdMutation = useMutation({
    mutationFn: () => createBookingHold({ slotId, idempotencyKey: holdKey.current }),
    retry: tutoringRetry,
    onSuccess: (created) => {
      setHold(created);
      setStage('summary');
      announce(
        created.replayed
          ? 'Your existing hold on this slot was returned.'
          : `This slot is held for you for ${created.holdMinutes} minutes.`,
      );
    },
  });

  const startHold = holdMutation.mutate;
  useEffect(() => {
    if (slotId) startHold();
  }, [slotId, startHold]);

  /* --------------- live countdown, driven by the server deadline ---------- */
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    if (!hold?.expiresAt || stage === 'confirmed') return;
    const timer = window.setInterval(() => setNow(Date.now()), 1000);
    return () => window.clearInterval(timer);
  }, [hold?.expiresAt, stage]);

  const countdown: HoldCountdown = holdCountdown(hold?.expiresAt, now);

  /**
   * The server stays authoritative on expiry: when the local countdown reaches
   * zero the hold is RE-READ rather than assumed dead, so a clock skew cannot
   * strand a hold that is still live.
   */
  const holdCheck = useQuery({
    queryKey: tutoringKeys.hold(hold?.id ?? ''),
    queryFn: () => getBookingHold(hold?.id ?? ''),
    enabled: Boolean(hold?.id) && countdown.expired && stage !== 'confirmed',
    retry: tutoringRetry,
    staleTime: 0,
  });
  const serverSaysExpired = holdCheck.data?.expired === true
    || (holdCheck.data ? holdCheck.data.status !== 'active' : false);
  const expired = countdown.expired && (serverSaysExpired || holdCheck.isError);

  useEffect(() => {
    if (countdown.level === 'urgent' && !urgencyAnnounced) {
      setUrgencyAnnounced(true);
      announce('Under two minutes left on your hold.');
    }
    if (expired) announce('Your hold expired and the slot was released. Nothing was charged.');
    // `announce` is stable for the life of the screen.
  }, [countdown.level, expired, urgencyAnnounced, announce]);

  /* ------------------------- C1 tokenised order --------------------------- */
  const orderMutation = useMutation({
    mutationFn: (amountPaise: number) => createPaymentOrder({
      holdId: hold?.id ?? '',
      amountPaise,
      idempotencyKey: orderKey.current,
      currency: 'INR',
      // No payment token is passed from this screen: the provider's hosted
      // surface owns the instrument, and the order is created before any
      // instrument exists. A token would only ever be handed over by the
      // provider callback, never typed here.
    }),
    retry: tutoringRetry,
    onSuccess: (created) => {
      setOrder(created);
      setStage('authorising');
      announce(
        created.replayed
          ? 'This payment order already existed and was returned unchanged.'
          : 'Payment order created. Continue in your bank or provider window.',
      );
    },
  });

  /* ------------------- C3 session, only for a PAID hold ------------------- */
  const sessionMutation = useMutation({
    mutationFn: () => createTutoringSession(hold?.id ?? ''),
    retry: tutoringRetry,
    onSuccess: (created) => {
      setStage('confirmed');
      queryClient.setQueryData(tutoringKeys.session(created.id), created);
      announce('Payment verified by the provider. Your session is confirmed.');
    },
  });

  const releaseAndLeave = useCallback(() => {
    // Nothing to call: a hold is released by its own TTL and the server charges
    // nothing. Leaving simply stops occupying the reader's attention.
    setLeaveOpen(false);
    backToProfile();
  }, [backToProfile]);

  if (!slotId) {
    return (
      <TutoringScreen screenId="S-33">
        <EmptyState
          title="No slot chosen"
          detail="Pick a time on a mentor profile to start a hold."
          action={<Link className="tt-btn tt-btn--block" to="/s-31">Find a mentor</Link>}
        />
      </TutoringScreen>
    );
  }

  const labels = slot
    ? slotTimeLabels(slot.startUtc, slot.endUtc, slot.ianaTimezone)
    : null;

  const policy = slot && feePaise !== null
    ? policyPreview({ startUtcIso: slot.startUtc, capturedPaise: feePaise })
    : null;

  const holdError = holdMutation.error;
  const raceLost = holdError instanceof TutoringApiError
    && (holdError.code === HOLD_CONFLICT || holdError.code === SLOT_UNAVAILABLE);

  const dock = (
    <Dock>
      <div className="tt-dock__top">
        <span style={{ fontSize: '12px', fontWeight: 800, color: 'var(--tt-mut)' }}>
          Total payable
        </span>
        <span className="tt-dock__tot">
          {/* Server figure or nothing: this screen never invents a total. */}
          {feePaise === null ? '—' : formatPaise(feePaise)}
        </span>
      </div>
      {stage === 'confirmed' ? (
        <Link className="tt-btn tt-btn--jade tt-btn--block" to="/s-35">
          <Ic name="check" />
          View your confirmed session
        </Link>
      ) : (
        <button
          type="button"
          className="tt-btn tt-btn--jade tt-btn--block"
          disabled={
            !hold
            || expired
            || feePaise === null
            || orderMutation.isPending
            || sessionMutation.isPending
          }
          aria-disabled={
            !hold || expired || feePaise === null
              || orderMutation.isPending || sessionMutation.isPending
          }
          onClick={() => {
            if (feePaise === null || !hold) return;
            if (stage === 'summary') orderMutation.mutate(feePaise);
            else sessionMutation.mutate();
          }}
        >
          <Ic name="lock" />
          {stage === 'summary'
            ? `Pay ${feePaise === null ? '' : formatPaise(feePaise)} securely`
            : orderMutation.isPending || sessionMutation.isPending
              ? 'Waiting for the provider'
              : 'Check payment and confirm'}
        </button>
      )}
      <button
        type="button"
        className="tt-btn tt-btn--block"
        style={{ minHeight: 'var(--tt-target-min)' }}
        onClick={() => setLeaveOpen(true)}
      >
        <Ic name="close" />
        Cancel payment
      </button>
    </Dock>
  );

  return (
    <TutoringScreen screenId="S-33" dock={dock}>
      {announceRegion}

      <div>
        <div className="tt-eyebrow">Step 2 of 3 · secure payment</div>
        <h1 className="tt-h tt-arrival" style={{ marginTop: '4px' }}>
          Hold and pay for this time
        </h1>
        {labels && (
          <p className="tt-p" style={{ fontSize: '12.5px' }}>
            {labels.sessionZone} · {labels.sessionZoneLabel}
            {labels.readerZone && <> · your time {labels.readerZone}</>}
          </p>
        )}
      </div>

      {/* B1 — the hold, with its countdown. Never colour alone. */}
      {hold && !expired && (
        <div className="tt-holdsticky">
          <div
            className="tt-hold"
            data-urgent={countdown.level === 'urgent' ? '1' : '0'}
            role="timer"
            aria-label={`Slot hold time remaining ${countdown.label}`}
          >
            <Ic name="timer" />
            <span className="tt-hold__t">{countdown.label}</span>
            <span className="tt-hold__c">
              {countdown.level === 'urgent' && <b>Under two minutes left. </b>}
              Seat held for you. If it ends, the slot is released and <b>nothing is charged</b>.
            </span>
          </div>
        </div>
      )}

      {holdMutation.isPending && <LoadingState what="your hold" />}

      {raceLost && (
        <TypedErrorState
          error={holdError}
          recoveryLabel="See other times with this mentor"
          onRecover={backToProfile}
        />
      )}

      {holdMutation.isError && !raceLost && (
        <TypedErrorState
          error={holdError}
          onRecover={() => {
            holdKey.current = newIdempotencyKey('hold');
            holdMutation.mutate();
          }}
        />
      )}

      {expired && (
        <TypedErrorState
          error={new TutoringApiError(409, HOLD_EXPIRED, 'hold expired', false)}
          recoveryLabel="Pick another time"
          onRecover={backToProfile}
        />
      )}

      {/* C1 — the tokenised, provider-hosted payment step. */}
      {stage !== 'confirmed' && feePaise !== null && (
        <>
          <Chip tone="t">Provider hosted · tokenised</Chip>
          <section className="tt-dis" style={{ borderColor: 'var(--tt-line2)' }}>
            <div className="tt-dis__body" style={{ paddingTop: '12px' }}>
              <Kv label={`Mentoring session · ${slot ? durationMinutes(slot.startUtc, slot.endUtc) : '—'} min`}>
                <span className="tt-mono">{formatPaise(feePaise)}</span>
              </Kv>
              <Kv label="Total payable">
                <span className="tt-mono">{formatPaise(feePaise)}</span>
              </Kv>
            </div>
          </section>

          <div className="tt-fld">
            <span className="tt-lbl">Card details</span>
            <div className="tt-in tt-in--hosted" role="group" aria-label="Card details, provider hosted">
              Entered in your payment provider
            </div>
            <p className="tt-p tt-muted" id="tt-hosted-note">
              LegalSaathi never receives your card number, security code or the authentication code
              your bank sends. Those fields exist only inside the provider surface.
            </p>
          </div>

          {order && (
            <Disclosure summary="Payment order" icon="lock" open>
              <Kv label="Provider">{order.provider}</Kv>
              <Kv label="Order reference">
                <span className="tt-mono" style={{ fontSize: '12px' }}>{order.providerOrderRef}</span>
              </Kv>
              <Kv label="Amount">
                <span className="tt-mono">{formatPaise(order.amountPaise)}</span>
              </Kv>
              <Kv label="Status">{order.status}</Kv>
              {order.brand && order.maskedLast4 && (
                <Kv label="Instrument">{order.brand} ending {order.maskedLast4}</Kv>
              )}
              {order.replayed && (
                <p className="tt-p tt-muted">
                  This order already existed. The same request key returned it unchanged, so you
                  cannot be charged twice.
                </p>
              )}
            </Disclosure>
          )}

          {orderMutation.isError && (
            <TypedErrorState
              error={orderMutation.error}
              onRecover={() => orderMutation.mutate(feePaise)}
            />
          )}

          {stage === 'authorising' && !sessionMutation.isError && (
            <Banner
              tone="info"
              title="Waiting for the provider to confirm"
              detail={
                'We create your session only when a signature-verified payment event arrives, '
                + 'never on a screen animation. Keep this page open, or come back to it later.'
              }
            />
          )}

          {sessionMutation.isError && (
            <TypedErrorState
              error={sessionMutation.error}
              recoveryLabel={
                sessionMutation.error instanceof TutoringApiError
                  && sessionMutation.error.code === PAYMENT_UNVERIFIED
                  ? 'Check again'
                  : undefined
              }
              onRecover={() => sessionMutation.mutate()}
            />
          )}
        </>
      )}

      {stage === 'confirmed' && (
        <Banner
          tone="ok"
          title="Payment verified by the provider"
          detail="A signature-verified payment event was received and your session now exists."
        />
      )}

      <Disclosure summary="How your payment is protected" icon="lock">
        <p className="tt-p" style={{ fontSize: '12.5px' }}>
          Card fields are <b>provider hosted and tokenised</b>. LegalSaathi never sees or stores
          your card number, security code or payment one-time code. Your session is created only
          after the provider confirms payment.
        </p>
      </Disclosure>

      {policy && (
        <p className="tt-p tt-muted">
          Cancelling later than {policy.policyWindowHours} hours before the start means no automatic
          refund. You can still ask an administrator to review your case.
        </p>
      )}
      {!policy && (
        <p className="tt-p tt-muted">
          Free cancellation applies until {DEFAULT_REFUND_FREE_CANCEL_HOURS} hours before the start.
          The server decides every refund from the frozen policy.
        </p>
      )}

      <p className="tt-svr">
        server-authoritative: hold TTL ({hold?.holdMinutes ?? DEFAULT_HOLD_MINUTES} min), slot lock,
        payment verification and every amount · money is integer paise
      </p>

      {leaveOpen && (
        <Modal
          title="Leave payment and release your slot?"
          onDismiss={() => setLeaveOpen(false)}
        >
          <p className="tt-p" style={{ fontSize: '13px' }}>
            Your {hold?.holdMinutes ?? DEFAULT_HOLD_MINUTES} minute hold ends if you leave. Nothing
            has been charged. Someone else may take this time.
          </p>
          <button
            type="button"
            className="tt-btn tt-btn--jade tt-btn--block"
            onClick={() => setLeaveOpen(false)}
          >
            <Ic name="lock" />
            Stay and finish paying
          </button>
          <button type="button" className="tt-btn tt-btn--block" onClick={releaseAndLeave}>
            <Ic name="close" />
            Leave and release the slot
          </button>
        </Modal>
      )}
    </TutoringScreen>
  );
}

/* ========================================================================== *
 * S-34 — confirmed session detail
 * ========================================================================== */

export function SessionConfirmed() {
  const [sp] = useSearchParams();
  const sessionId = sp.get('session') ?? '';
  useRouteArrival(`S-34:${sessionId}`);

  const session = useQuery({
    queryKey: tutoringKeys.session(sessionId),
    queryFn: () => getTutoringSession(sessionId),
    enabled: Boolean(sessionId),
    retry: tutoringRetry,
    staleTime: 15_000,
  });

  if (!sessionId) {
    return (
      <TutoringScreen screenId="S-34">
        <EmptyState
          title="No session selected"
          detail="Open a session from your sessions list to see its confirmation and receipt."
          action={<Link className="tt-btn tt-btn--block" to="/s-35">Go to my sessions</Link>}
        />
      </TutoringScreen>
    );
  }

  if (session.isPending) {
    return (
      <TutoringScreen screenId="S-34">
        <LoadingState what="this session" />
      </TutoringScreen>
    );
  }

  if (session.isError) {
    return (
      <TutoringScreen screenId="S-34">
        <TypedErrorState error={session.error} onRecover={() => session.refetch()} />
      </TutoringScreen>
    );
  }

  const data = session.data;
  const labels = slotTimeLabels(data.startUtc, data.endUtc, data.ianaTimezone);
  // Server vocabulary (`SESSION_STATUSES`): a booked session is `confirmed`, or
  // `rescheduled` once it has been moved. `scheduled` is not a status the server
  // has; it is kept only so an older payload cannot regress this receipt.
  const confirmed =
    data.status === 'confirmed' || data.status === 'rescheduled' || data.status === 'scheduled';
  const minutes = durationMinutes(data.startUtc, data.endUtc);
  const policy = policyPreview({ startUtcIso: data.startUtc, capturedPaise: 0 });

  const dock = (
    <Dock>
      <Link className="tt-btn tt-btn--jade tt-btn--block" to={`/s-35?session=${encodeURIComponent(data.id)}`}>
        <Ic name="cal" />
        Manage this session
      </Link>
    </Dock>
  );

  return (
    <TutoringScreen screenId="S-34" dock={dock}>
      {confirmed ? (
        <div className="tt-band">
          <span className="tt-seal"><Ic name="check" /></span>
          <div>
            <div className="tt-eyebrow" style={{ color: 'var(--tt-jade)' }}>Confirmed and paid</div>
            <h1 className="tt-h tt-arrival" style={{ marginTop: '2px', fontSize: '19px' }}>
              Your session is booked
            </h1>
            <p className="tt-p" style={{ fontSize: '12.5px' }}>
              Status reported by the server: {data.status}
            </p>
          </div>
        </div>
      ) : (
        <Banner
          tone={data.status === 'cancelled' ? 'warn' : 'info'}
          title={`This session is ${data.status}`}
          detail="Confirmation is rendered only from the server's own record, never from a client guess."
          code={data.status.toUpperCase()}
        />
      )}

      <div className="tt-row">
        <span style={{ fontSize: '13.5px', minWidth: 0 }}>
          <b>{labels.sessionZone}</b>
          <span style={{ display: 'block', fontSize: '12px', color: 'var(--tt-mut)', fontWeight: 700 }}>
            {labels.sessionZoneLabel}
          </span>
          {labels.readerZone && (
            <span style={{ display: 'block', fontSize: '12px', color: 'var(--tt-mut)', fontWeight: 700 }}>
              Your time: {labels.readerZone} · {labels.readerZoneLabel}
            </span>
          )}
        </span>
        <Chip tone={policy.started ? 'g' : 'i'}>
          {policy.started ? 'Room entry is open' : 'Room entry opens near the start'}
        </Chip>
      </div>

      {/* D-10 / E1: join eligibility is a SERVER decision, so this is a link to the
          room entry point on S-35, never a client clock comparison that grants entry. */}
      <Link
        className="tt-btn tt-btn--jade tt-btn--block"
        to={`/s-35?session=${encodeURIComponent(data.id)}&view=prejoin`}
      >
        <Ic name="join" />
        Go to the room entry check
      </Link>
      <p className="tt-p tt-muted">
        The room asks the server for a short-lived credential when you enter. Your device is only
        tested locally; no device name leaves this browser.
      </p>

      <Disclosure summary="Session details" icon="info" open>
        <Kv label="Length">{minutes} minutes · one to one</Kv>
        <Kv label="Timezone kept with the session">{data.ianaTimezone}</Kv>
        <Kv label="Your device timezone">{browserTimeZone()}</Kv>
        <Kv label="Session reference">
          <span className="tt-mono" style={{ fontSize: '12px' }}>{data.id}</span>
        </Kv>
        <Kv label="Payment order">
          <span className="tt-mono" style={{ fontSize: '12px' }}>{data.orderId ?? 'Not recorded'}</span>
        </Kv>
        <Kv label="Attendance">{data.attendanceState ?? 'Decided after the scheduled end'}</Kv>
      </Disclosure>

      <Disclosure summary="Cancellation and reschedule policy" icon="refund">
        <Kv label="Free window">
          {policy.policyWindowHours} hours or more before the start
        </Kv>
        <Kv label="Right now">
          {policy.started
            ? 'The start has passed, so cancellation is closed'
            : policy.rescheduleFree
              ? 'Reschedule is free and cancelling earns a full refund'
              : 'Inside the window: an administrator must review any refund'}
        </Kv>
        <p className="tt-p tt-muted">
          The refund amount and the reschedule verdict are computed by the server from the frozen
          policy. This preview mirrors the same rule so the outcome is not a surprise.
        </p>
      </Disclosure>

      <div className="tt-actrow">
        <Link className="tt-btn" to="/s-35">
          <Ic name="cal" />
          All my sessions
        </Link>
      </div>

      <p className="tt-svr">
        server-authoritative: confirmation, join eligibility, credential lifetime and refund policy
      </p>
    </TutoringScreen>
  );
}
