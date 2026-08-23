/**
 * Option C2 component layer for the Wave 2 tutoring screens (S-31 … S-35).
 *
 * Ported from the approved reference package's component inventory
 * (docs/design/tutoring/option_c2_reference_v1, TOKEN_COMPONENT_MOTION_SPEC §4)
 * as real React components. The reference's own renderer is deliberately NOT
 * lifted: it is string templating around global objects (IMPLEMENTATION_HANDOFF
 * §2 forbids importing it), so the composition is re-expressed here while the
 * class names, geometry and copy intent stay the reference's.
 *
 * Every colour is a scoped `--tt-*` token (see the `.st-tutoring` block in
 * student.css). Nothing here hard-codes a hue.
 */
import {
  useCallback,
  useEffect,
  useId,
  useRef,
  useState,
  type ReactNode,
} from 'react';
import { useNavigationType } from 'react-router-dom';
import { StudentScreen } from '../components';
import {
  ADMIN_EXCEPTION_UNAUTHORISED,
  AMOUNT_MISMATCH,
  PAYMENT_AMOUNT_MISMATCH,
  SESSION_PRICE_INVALID,
  ATTENDANCE_STALE_VERSION,
  ATTENDANCE_STATE_INVALID,
  ATTENDANCE_TOO_EARLY,
  AUTHENTICATION_REQUIRED,
  DUPLICATE_EVENT,
  FORBIDDEN,
  GRANT_EXPIRED,
  GRANT_REVOKED,
  HOLD_CONFLICT,
  HOLD_EXPIRED,
  HTTP_FORBIDDEN,
  IDEMPOTENCY_KEY_REUSE,
  NOT_FOUND,
  PAYMENT_UNVERIFIED,
  PROVIDER_UNAVAILABLE,
  RATE_LIMIT_EXCEEDED,
  REFUND_DUPLICATE,
  REFUND_NOT_ALLOWED,
  RESCHEDULE_WINDOW_CLOSED,
  REVIEW_BLOCKED,
  REVIEW_DUPLICATE,
  REVIEW_EDIT_WINDOW_CLOSED,
  REVIEW_NOT_MODERATABLE,
  SESSION_NOT_ENDED,
  SESSION_STALE_VERSION,
  SESSION_STATE_INVALID,
  SLOT_UNAVAILABLE,
  TutoringApiError,
  VALIDATION_ERROR,
} from '../lib/tutoringApi';

/* ========================================================================== *
 * Icons — the reference's 24x24 stroke set. Decorative by default.
 * ========================================================================== */

const PATHS: Record<string, string> = {
  search: 'M10.5 4.3a6.2 6.2 0 1 0 0 12.4 6.2 6.2 0 0 0 0-12.4ZM15.5 15.5 21 21',
  chev: 'M6 9.5 12 15.5 18 9.5',
  lock: 'M6 13a2.5 2.5 0 0 1 2.5-2.5h7A2.5 2.5 0 0 1 18 13v4a2.5 2.5 0 0 1-2.5 2.5h-7A2.5 2.5 0 0 1 6 17v-4ZM8.5 10.5V8a3.5 3.5 0 0 1 7 0v2.5',
  cal: 'M4 8.5A3 3 0 0 1 7 5.5h10a3 3 0 0 1 3 3v9a3 3 0 0 1-3 3H7a3 3 0 0 1-3-3v-9ZM8 3.5v4M16 3.5v4',
  timer: 'M12 6.5a7 7 0 1 0 0 14 7 7 0 0 0 0-14ZM12 10.5v3l2 2M9.5 3.5h5',
  check: 'm8.5 12.2 2.4 2.4 4.6-4.8M12 3a9 9 0 1 0 0 18 9 9 0 0 0 0-18Z',
  join: 'M3.5 9.5a3 3 0 0 1 3-3h6.5a3 3 0 0 1 3 3v5a3 3 0 0 1-3 3H6.5a3 3 0 0 1-3-3v-5Zm12.5 1 4.5-2.5v8L16 13.5',
  leave: 'M13 4.5H6.5A1.5 1.5 0 0 0 5 6v12a1.5 1.5 0 0 0 1.5 1.5H13M16 8.5 19.5 12 16 15.5M19.5 12H9.5',
  mic: 'M9.4 6.6A2.6 2.6 0 0 1 12 4a2.6 2.6 0 0 1 2.6 2.6v4.8A2.6 2.6 0 0 1 12 14a2.6 2.6 0 0 1-2.6-2.6V6.6ZM6 11.5a6 6 0 0 0 12 0M12 17.5V20',
  micOff: 'M9.4 6.6A2.6 2.6 0 0 1 12 4a2.6 2.6 0 0 1 2.6 2.6v4.8A2.6 2.6 0 0 1 12 14M4.5 4.5l15 15M12 17.5V20M6 11.5a6 6 0 0 0 9.7 4.7',
  cam: 'M3.5 9.5a3 3 0 0 1 3-3h6.5a3 3 0 0 1 3 3v5a3 3 0 0 1-3 3H6.5a3 3 0 0 1-3-3v-5Zm12.5 1 4.5-2.5v8L16 13.5',
  camOff: 'M3.5 9.5a3 3 0 0 1 3-3h6.5a3 3 0 0 1 3 3v5a3 3 0 0 1-3 3H6.5a3 3 0 0 1-3-3v-5Zm12.5 1 4.5-2.5v8L16 13.5M3.5 4.5l17 15',
  dev: 'M3.5 7a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v5.5a2 2 0 0 1-2 2h-9a2 2 0 0 1-2-2V7ZM7.5 18h5M15.5 11.5a1.5 1.5 0 0 1 1.5-1.5h2a1.5 1.5 0 0 1 1.5 1.5V17a1.5 1.5 0 0 1-1.5 1.5h-2A1.5 1.5 0 0 1 15.5 17v-5.5Z',
  info: 'M12 3a9 9 0 1 0 0 18 9 9 0 0 0 0-18ZM12 11v5.5M12 8v.4',
  warn: 'M12 4.5 21 19.5H3zM12 10v4M12 16.6v.4',
  copy: 'M8.5 11a2.5 2.5 0 0 1 2.5-2.5h6A2.5 2.5 0 0 1 19.5 11v6a2.5 2.5 0 0 1-2.5 2.5h-6A2.5 2.5 0 0 1 8.5 17v-6ZM6 15H5.5A1.5 1.5 0 0 1 4 13.5v-8A1.5 1.5 0 0 1 5.5 4h8A1.5 1.5 0 0 1 15 5.5V6',
  dl: 'M12 4.5V14m-3.5-3 3.5 3.5 3.5-3.5M5 17.5v1A1.5 1.5 0 0 0 6.5 20h11a1.5 1.5 0 0 0 1.5-1.5v-1',
  share: 'M12 14V4.5M8.5 7.5 12 4l3.5 3.5M6 12v6.5A1.5 1.5 0 0 0 7.5 20h9a1.5 1.5 0 0 0 1.5-1.5V12',
  refund: 'M12 4.5a7.5 7.5 0 1 0 0 15 7.5 7.5 0 0 0 0-15ZM9.2 9h5.6M9.2 11.6h5.6M9.6 9c2.6 0 3.4 1 3.4 2.2 0 1.4-1.1 2.2-2.8 2.2H9.6l3.4 3.6',
  min: 'M6 12h12',
  move: 'M12 4.5v15M4.5 12h15M9.5 7.5 12 5l2.5 2.5M9.5 16.5 12 19l2.5-2.5M7.5 9.5 5 12l2.5 2.5M16.5 9.5 19 12l-2.5 2.5',
  star: 'm12 4.5 2.4 5 5.4.7-3.9 3.8.9 5.4-4.8-2.6-4.8 2.6.9-5.4L4.2 10.2l5.4-.7z',
  close: 'M6 6l12 12M18 6 6 18',
  back: 'M14.5 6 8.5 12l6 6',
  clock: 'M12 5a7 7 0 1 0 0 14 7 7 0 0 0 0-14ZM12 8.5V12l2.5 1.6',
};

export type IconName = keyof typeof PATHS | string;

/** Decorative icon. A meaningful icon takes `label` and becomes role="img". */
export function Ic({ name, label, className }: { name: IconName; label?: string; className?: string }) {
  const decorative = !label;
  return (
    <svg
      className={`tt-ic ${className ?? ''}`.trim()}
      viewBox="0 0 24 24"
      {...(decorative
        ? { 'aria-hidden': true, focusable: false }
        : { role: 'img', 'aria-label': label })}
    >
      <path className="s" d={PATHS[name] ?? ''} />
    </svg>
  );
}

/**
 * Monogram medallion. A generated identity mark, not a photograph: the API
 * exposes no avatar, and inventing one would be a fake-precision tell.
 */
export function Portrait({ initials, accent }: { initials: string; accent?: boolean }) {
  return (
    <span className="tt-por">
      <svg viewBox="0 0 100 100" aria-hidden focusable="false">
        <rect width="100" height="100" fill="var(--tt-jadeq)" />
        <circle cx="50" cy="42" r="20" fill="var(--tt-jade)" />
        <path d="M18 84c7-19 17-28 32-28s25 9 32 28z" fill="var(--tt-jade)" />
        {accent && (
          <path
            d="M29 40c0-13 9-22 21-22s21 9 21 22"
            fill="none"
            stroke="var(--tt-terra)"
            strokeWidth="4.5"
            strokeLinecap="round"
          />
        )}
        <text
          x="50"
          y="97"
          textAnchor="middle"
          fontFamily="IBM Plex Mono, monospace"
          fontSize="14"
          fill="var(--tt-jade)"
        >
          {initials}
        </text>
      </svg>
    </span>
  );
}

/** Two-letter monogram from a display name. */
export function monogram(name: string): string {
  const words = name.replace(/^(adv|dr|prof)\.?\s+/i, '').split(/\s+/).filter(Boolean);
  if (words.length === 0) return '··';
  if (words.length === 1) return words[0].slice(0, 2).toUpperCase();
  return (words[0][0] + words[words.length - 1][0]).toUpperCase();
}

/* ========================================================================== *
 * Layout
 * ========================================================================== */

/**
 * Deterministic destination presentation: a forward navigation scrolls to the
 * top and moves focus to the screen heading. Back/Forward (POP) is left to the
 * browser so the reader's prior position survives.
 */
export function useRouteArrival(screenKey: string): void {
  const navType = useNavigationType();
  useEffect(() => {
    if (navType === 'POP') return;
    window.scrollTo(0, 0);
    const heading = document.querySelector<HTMLElement>('.st-tutoring .tt-arrival');
    if (heading) {
      heading.setAttribute('tabindex', '-1');
      heading.focus({ preventScroll: true });
    }
    // Mount-only per screen (deps intentionally exclude navType): re-running on
    // param-driven re-renders would steal focus from a form control.
  }, [screenKey]);
}

export function TutoringScreen({
  screenId,
  children,
  dock,
  bare,
}: {
  screenId: string;
  children: ReactNode;
  dock?: ReactNode;
  /**
   * The live room owns the whole viewport, so it opts out of the screen bar and
   * the scrolling body while STAYING inside `.st-tutoring` — the `--tt-*` tokens
   * are scoped there and a fixed descendant still inherits them.
   */
  bare?: boolean;
}) {
  if (bare) {
    return (
      <StudentScreen screenId={screenId} className="st-tutoring">
        {children}
      </StudentScreen>
    );
  }
  return (
    <StudentScreen screenId={screenId} className="st-tutoring">
      <header className="tt-bar">
        <span className="tt-wm"><i aria-hidden>§</i> NyayOne</span>
        <span className="tt-grow" />
        <span className="tt-sid">{screenId}</span>
      </header>
      <div className={`tt-body ${dock ? 'tt-hasdock' : ''}`.trim()}>{children}</div>
      {dock}
    </StudentScreen>
  );
}

export function Dock({ children }: { children: ReactNode }) {
  return <div className="tt-dock">{children}</div>;
}

/* ========================================================================== *
 * Primitives
 * ========================================================================== */

export type ChipTone = 'g' | 't' | 'i' | 'gd' | 'r' | 'plain';

/** Colour AND shape: circle jade, rotated square terracotta, square indigo. */
export function Chip({ tone = 'plain', children }: { tone?: ChipTone; children: ReactNode }) {
  return (
    <span className={`tt-chip ${tone === 'plain' ? '' : `tt-chip--${tone}`}`.trim()}>
      <span className="d" aria-hidden />
      {children}
    </span>
  );
}

export type BannerTone = 'ok' | 'warn' | 'err' | 'info';

/**
 * The typed state surface. An error tone is `role="alert"` (assertive) and
 * everything else is `role="status"`, per the reference a11y spec §3.
 */
export function Banner({
  tone,
  title,
  detail,
  code,
  children,
}: {
  tone: BannerTone;
  title: string;
  detail?: ReactNode;
  /** The machine code, shown verbatim so a reader can quote it to support. */
  code?: string;
  children?: ReactNode;
}) {
  return (
    <div className={`tt-banner tt-banner--${tone}`} role={tone === 'err' ? 'alert' : 'status'}>
      <Ic name={tone === 'err' || tone === 'warn' ? 'warn' : tone === 'ok' ? 'check' : 'info'} />
      <div>
        <div className="tt-banner__t">{title}</div>
        {detail && <div className="tt-banner__d">{detail}</div>}
        {code && <code className="tt-banner__code">{code}</code>}
        {children}
      </div>
    </div>
  );
}

export function Kv({ label, children }: { label: ReactNode; children: ReactNode }) {
  return (
    <div className="tt-kv">
      <span>{label}</span>
      <b>{children}</b>
    </div>
  );
}

export function Disclosure({
  summary,
  icon = 'info',
  open,
  children,
}: {
  summary: string;
  icon?: IconName;
  open?: boolean;
  children: ReactNode;
}) {
  return (
    <details className="tt-dis" open={open}>
      <summary>
        <Ic name={icon} />
        {summary}
        <Ic name="chev" className="tt-cv" />
      </summary>
      <div className="tt-dis__body">{children}</div>
    </details>
  );
}

/**
 * A single polite live region per screen, cleared and refilled on the next
 * frame so a repeated identical message is announced again.
 */
export function useAnnouncer(): [ReactNode, (message: string) => void] {
  const [message, setMessage] = useState('');
  const frame = useRef<number | null>(null);
  useEffect(() => () => {
    if (frame.current !== null) cancelAnimationFrame(frame.current);
  }, []);
  /** Stable for the life of the screen, so it is safe in an effect's deps. */
  const announce = useCallback((next: string): void => {
    setMessage('');
    if (frame.current !== null) cancelAnimationFrame(frame.current);
    frame.current = requestAnimationFrame(() => setMessage(next));
  }, []);
  const region = (
    <p className="tt-sr" aria-live="polite" aria-atomic="true">{message}</p>
  );
  return [region, announce];
}

/**
 * Modal dialog with focus moved inside, Tab trapped, Escape to dismiss, and the
 * whole background marked `inert` + `aria-hidden` (a11y spec §2). Financial and
 * destructive confirmations are always icon PLUS text.
 */
export function Modal({
  title,
  children,
  onDismiss,
}: {
  title: string;
  children: ReactNode;
  onDismiss: () => void;
}) {
  const titleId = useId();
  const box = useRef<HTMLDivElement | null>(null);
  const layer = useRef<HTMLDivElement | null>(null);
  useEffect(() => {
    /*
     * Mark EVERYTHING outside the dialog's own ancestor chain `inert` +
     * `aria-hidden`, walking up to the screen region. A single pass over the
     * region's direct children is not enough: the live room nests the dialog
     * several levels down, and marking that whole subtree inert would disable
     * the dialog itself.
     */
    const region = document.querySelector<HTMLElement>('.st-tutoring');
    const backdrops: HTMLElement[] = [];
    let node: HTMLElement | null = layer.current;
    while (node && node !== region) {
      const parent: HTMLElement | null = node.parentElement;
      if (!parent) break;
      for (const sibling of Array.from(parent.children)) {
        if (sibling !== node && sibling instanceof HTMLElement) backdrops.push(sibling);
      }
      node = parent;
    }
    backdrops.forEach((el) => {
      el.setAttribute('inert', '');
      el.setAttribute('aria-hidden', 'true');
    });
    /*
     * A11Y-01 (WCAG 2.4.3 Focus Order): remember what had focus BEFORE the
     * dialog steals it, so closing can hand focus back to the control that
     * opened it. Without this the focus lands on <body> and a keyboard or
     * screen-reader user is dumped at the top of the document, losing their
     * place — reproduced by the browser oracle, which asserted the opener is
     * refocused after Escape and after a scrim dismiss.
     */
    const opener = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    const focusable = box.current?.querySelector<HTMLElement>(
      'button, [href], input, select, textarea, [tabindex]:not([tabindex="-1"])',
    );
    focusable?.focus();
    const onKey = (event: KeyboardEvent): void => {
      if (event.key === 'Escape') {
        event.preventDefault();
        onDismiss();
        return;
      }
      if (event.key !== 'Tab' || !box.current) return;
      const items = Array.from(
        box.current.querySelectorAll<HTMLElement>(
          'button:not([disabled]), [href], input, select, textarea, [tabindex]:not([tabindex="-1"])',
        ),
      );
      if (items.length === 0) return;
      const first = items[0];
      const last = items[items.length - 1];
      if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault();
        first.focus();
      } else if (event.shiftKey && document.activeElement === first) {
        event.preventDefault();
        last.focus();
      }
    };
    document.addEventListener('keydown', onKey);
    return () => {
      document.removeEventListener('keydown', onKey);
      backdrops.forEach((el) => {
        el.removeAttribute('inert');
        el.removeAttribute('aria-hidden');
      });
      // Return focus to the opener. The inert/aria-hidden attributes are
      // removed FIRST above, otherwise the opener is still inert and .focus()
      // is a no-op. Guard on connectedness: the opener can legitimately have
      // been unmounted by the same state change that closed the dialog, and in
      // that case the browser's own default placement is the honest outcome.
      if (opener && opener.isConnected) opener.focus();
    };
  }, [onDismiss]);
  return (
    <div className="tt-modal-layer" ref={layer}>
      <button type="button" className="tt-scrim" aria-label="Dismiss dialog" onClick={onDismiss} />
      <div className="tt-modal" role="dialog" aria-modal="true" aria-labelledby={titleId} ref={box}>
        <h2 className="tt-h" id={titleId} style={{ fontSize: '17px' }}>{title}</h2>
        {children}
      </div>
    </div>
  );
}

/* ========================================================================== *
 * Typed backend error -> a usable UI state
 * ========================================================================== *
 * Each row is (title, what actually happened, what the reader does next). The
 * codes come from backend/app/services/tutoring/errors.py; nothing here is a
 * generic "something went wrong".
 */

export interface TypedErrorCopy {
  tone: BannerTone;
  title: string;
  detail: string;
  /** Label for the recovery affordance the screen should offer, when there is one. */
  recovery?: string;
}

const ERROR_COPY: Record<string, TypedErrorCopy> = {
  [HOLD_EXPIRED]: {
    tone: 'warn',
    title: 'Your hold expired and the slot was released',
    detail:
      'The hold ran out before payment completed. Nothing was charged. Pick a slot again to start a fresh hold.',
    recovery: 'Pick another slot',
  },
  [HOLD_CONFLICT]: {
    tone: 'err',
    title: 'Another student reached this slot first',
    detail:
      'Exactly one hold wins a slot, and this time it was not yours. Nothing was charged. The other times on this mentor are still open.',
    recovery: 'See other times',
  },
  [SLOT_UNAVAILABLE]: {
    tone: 'err',
    title: 'That time is no longer bookable',
    detail:
      'The slot was taken, withdrawn or has already passed. Nothing was charged. Choose another time from the mentor availability.',
    recovery: 'See other times',
  },
  [PAYMENT_UNVERIFIED]: {
    tone: 'err',
    title: 'Payment is not verified yet',
    detail:
      'We create a session only after the payment provider confirms, never on a screen animation. If money left your account, the confirmation will follow and your booking appears here.',
    recovery: 'Check payment status',
  },
  [AMOUNT_MISMATCH]: {
    tone: 'err',
    title: 'The amount did not match the booking',
    detail:
      'The server rejected the amount for this hold, so nothing was charged. Reopen the booking to get the current total.',
    recovery: 'Reload the total',
  },
  [PAYMENT_AMOUNT_MISMATCH]: {
    tone: 'err',
    title: 'The price changed while you were paying',
    detail:
      'The amount this screen showed is not the price the server holds for this session, so nothing was charged. Reload to see the current total before paying.',
    recovery: 'Reload the total',
  },
  [SESSION_PRICE_INVALID]: {
    tone: 'err',
    title: 'This session is not correctly priced yet',
    detail:
      'The server does not hold a valid price for this mentor, so it refused to take any money and nothing was charged. Try another mentor, or come back once the price is published.',
    recovery: 'See other mentors',
  },
  [IDEMPOTENCY_KEY_REUSE]: {
    tone: 'err',
    title: 'That request key was already used for a different booking',
    detail:
      'A key can only ever replay its own request. Nothing new was created and nothing was charged twice. Start this booking again.',
    recovery: 'Start again',
  },
  [DUPLICATE_EVENT]: {
    tone: 'info',
    title: 'That update had already been applied',
    detail:
      'The provider sent the same event twice. It was applied once, and the repeat changed nothing.',
  },
  [REVIEW_NOT_MODERATABLE]: {
    tone: 'info',
    title: 'This review has already been decided',
    detail:
      'It has been approved, rejected or removed, so there is nothing left to decide. Nothing changed.',
  },
  [PROVIDER_UNAVAILABLE]: {
    tone: 'err',
    title: 'The provider is unavailable right now',
    detail:
      'Nothing was charged. Retrying is safe: the same request key means you cannot be charged twice.',
    recovery: 'Retry',
  },
  [RATE_LIMIT_EXCEEDED]: {
    tone: 'warn',
    title: 'Too many requests for now',
    detail:
      'You have reached the limit for this action. Nothing was lost. Wait for the window to pass and try once more.',
    recovery: 'Try again shortly',
  },
  [RESCHEDULE_WINDOW_CLOSED]: {
    tone: 'warn',
    title: 'Too close to the start to reschedule for free',
    detail:
      'A free reschedule needs at least the notice window before the start. Your session is unchanged and your payment is untouched. An administrator can still review your case.',
    recovery: 'Request an admin exception',
  },
  [REFUND_NOT_ALLOWED]: {
    tone: 'warn',
    title: 'No automatic refund at this notice',
    detail:
      'Cancelling now does not earn an automatic refund under the frozen policy. Your session is unchanged until you confirm, and you can still ask an administrator to review it.',
    recovery: 'Request an admin exception',
  },
  [REFUND_DUPLICATE]: {
    tone: 'info',
    title: 'This refund already exists',
    detail:
      'A refund for this booking has already succeeded. Repeat requests return the same refund reference, so you cannot be refunded twice.',
    recovery: 'View the refund',
  },
  [SESSION_STALE_VERSION]: {
    tone: 'warn',
    title: 'This page is out of date',
    detail:
      'The session changed after this page loaded, so your action was refused rather than overwriting the newer change. Reload to see the current state.',
    recovery: 'Reload the session',
  },
  [SESSION_STATE_INVALID]: {
    tone: 'warn',
    title: 'That action does not apply in this state',
    detail:
      'The session has already moved on, so this action no longer applies. Nothing changed. Reload to see where it is now.',
    recovery: 'Reload the session',
  },
  [SESSION_NOT_ENDED]: {
    tone: 'warn',
    title: 'The session has not ended yet',
    detail:
      'Completion and attendance open only after the scheduled end. Come back once the session finishes.',
  },
  [ATTENDANCE_TOO_EARLY]: {
    tone: 'warn',
    title: 'Attendance is not open yet',
    detail:
      'Attendance can only be recorded after the scheduled end. Nothing was recorded.',
  },
  [ATTENDANCE_STALE_VERSION]: {
    tone: 'warn',
    title: 'The attendance record changed while you were here',
    detail:
      'Someone updated attendance after this page loaded, so your action was refused instead of overwriting it. Reload and read the current record.',
    recovery: 'Reload attendance',
  },
  [ATTENDANCE_STATE_INVALID]: {
    tone: 'warn',
    title: 'That attendance action does not apply',
    detail:
      'Attendance is already in a state where this action is not available. Nothing changed.',
    recovery: 'Reload attendance',
  },
  [REVIEW_BLOCKED]: {
    tone: 'warn',
    title: 'Reviewing is locked until attendance is confirmed',
    detail:
      'A review needs a confirmed attendance record. While attendance is absent or disputed the review stays closed, and your text is not lost.',
    recovery: 'Go to attendance',
  },
  [REVIEW_DUPLICATE]: {
    tone: 'info',
    title: 'You have already reviewed this session',
    detail:
      'One review per session. Your existing review is still editable inside its edit window.',
    recovery: 'Edit your review',
  },
  [REVIEW_EDIT_WINDOW_CLOSED]: {
    tone: 'warn',
    title: 'The edit window for this review has closed',
    detail:
      'Reviews can be changed for a limited period after posting. Your published review is unchanged.',
  },
  [GRANT_EXPIRED]: {
    tone: 'warn',
    title: 'Your join credential expired',
    detail:
      'Join credentials are deliberately short lived. Ask for a fresh one to enter the room; nothing about your booking changed.',
    recovery: 'Get a fresh join credential',
  },
  [GRANT_REVOKED]: {
    tone: 'warn',
    title: 'That join credential was replaced',
    detail:
      'Issuing a new credential revokes the previous one, so an older join attempt stops working. Request entry again from this page.',
    recovery: 'Rejoin',
  },
  [ADMIN_EXCEPTION_UNAUTHORISED]: {
    tone: 'err',
    title: 'Only an administrator can make that exception',
    detail:
      'Exceptions inside the policy window are audited and must name the authorising administrator. Nothing changed.',
  },
  [NOT_FOUND]: {
    tone: 'err',
    title: 'We cannot find that',
    detail:
      'It does not exist, or it is not yours to open. Go back to your sessions and pick again.',
    recovery: 'Back to sessions',
  },
  [FORBIDDEN]: {
    tone: 'err',
    title: 'Your account may not do that',
    detail:
      'This action belongs to a different role. Nothing changed.',
  },
  [HTTP_FORBIDDEN]: {
    tone: 'err',
    title: 'Your account may not do that',
    detail:
      'This action belongs to a different role. Nothing changed.',
  },
  [AUTHENTICATION_REQUIRED]: {
    tone: 'err',
    title: 'Please sign in again',
    detail:
      'Your session with NyayOne has ended. Sign in and reopen this page; nothing was lost.',
    recovery: 'Sign in',
  },
  [VALIDATION_ERROR]: {
    tone: 'err',
    title: 'The server refused those details',
    detail:
      'One of the values did not pass the server rules, so nothing was saved. Correct the highlighted field and try again.',
  },
};

/** Copy for a typed refusal, with an honest fallback that still names the code. */
export function typedErrorCopy(error: unknown): TypedErrorCopy & { code: string } {
  if (error instanceof TutoringApiError) {
    const copy = ERROR_COPY[error.code];
    if (copy) return { ...copy, code: error.code };
    return {
      tone: error.status >= 500 ? 'err' : 'warn',
      title: 'The server refused this request',
      detail:
        error.retryable === true
          ? 'Nothing was changed. This one is safe to retry.'
          : 'Nothing was changed. Quote the code below if you contact support.',
      recovery: error.retryable === true ? 'Retry' : undefined,
      code: error.code,
    };
  }
  return {
    tone: 'err',
    title: 'We could not reach NyayOne',
    detail:
      'Your request did not leave the device, so nothing was submitted and nothing was charged. Check your connection and try again.',
    recovery: 'Retry',
    code: 'NETWORK_UNREACHABLE',
  };
}

/**
 * Render a typed refusal as a banner plus, optionally, the recovery action the
 * copy names. `onRecover` is the screen's own handler — the banner never
 * invents navigation.
 */
export function TypedErrorState({
  error,
  onRecover,
  recoveryLabel,
}: {
  error: unknown;
  onRecover?: () => void;
  recoveryLabel?: string;
}) {
  const copy = typedErrorCopy(error);
  const label = recoveryLabel ?? copy.recovery;
  const extra =
    error instanceof TutoringApiError && error.retryAfterSeconds !== undefined
      ? ` Try again in about ${error.retryAfterSeconds} seconds.`
      : '';
  return (
    <>
      <Banner tone={copy.tone} title={copy.title} detail={copy.detail + extra} code={copy.code} />
      {onRecover && label && (
        <button type="button" className="tt-btn tt-btn--block" onClick={onRecover}>
          {label}
        </button>
      )}
    </>
  );
}

/* ========================================================================== *
 * Loading and empty states
 * ========================================================================== */

export function LoadingState({ what }: { what: string }) {
  return (
    <div className="tt-banner tt-banner--info" role="status">
      <Ic name="clock" />
      <div>
        <div className="tt-banner__t">Loading {what}</div>
        <div className="tt-banner__d">Reading the current state from the server.</div>
      </div>
    </div>
  );
}

export function EmptyState({
  title,
  detail,
  action,
}: {
  title: string;
  detail: string;
  action?: ReactNode;
}) {
  return (
    <>
      <Banner tone="info" title={title} detail={detail} />
      {action}
    </>
  );
}
