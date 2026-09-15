import { useEffect, useRef, type FocusEvent, type FormEvent, type ReactNode } from 'react';
import { NyayOneRevLIcon, NyayOneRevLLockup } from './NyayOneRevLIcon';
import './S06R2.css';

export type S06R2State = 'entry' | 'invalidnum' | 'submitting' | 'challenge' | 'wrong' | 'cooldown' | 'expired' | 'locked' | 'neterr' | 'success';
export type S06R2Props = Readonly<{
  state: S06R2State;
  mobile: string;
  code: string;
  destinationMasked: string | null;
  expiresInSeconds: number | null;
  resendInSeconds: number | null;
  attemptsLeft: number | null;
  lockedForSeconds: number | null;
  busy: boolean;
  authorityReady: boolean;
  resendAllowed: boolean;
  focusRequest?: number;
  onMobileChange: (value: string) => void;
  onCodeChange: (value: string) => void;
  onSend: () => void;
  onVerify: () => void;
  onResend: () => void;
  onChangeNumber: () => void;
  onBack: () => void;
  onRetry: () => void;
}>;

function timeLabel(seconds: number | null): string {
  if (seconds === null || !Number.isFinite(seconds) || seconds < 0) return 'Unavailable';
  const whole = Math.ceil(seconds);
  return `${Math.floor(whole / 60)}:${String(whole % 60).padStart(2, '0')}`;
}

export function focusRecoveryTarget(root: HTMLElement, state: S06R2State) {
  const selector = state === 'neterr' ? '[data-recovery-retry]'
    : state === 'locked' || state === 'success' ? '[data-recovery-return]'
      : state === 'entry' || state === 'invalidnum' || state === 'submitting' ? '#v34-reset-mobile'
        : '#v34-recovery-code';
  root.querySelector<HTMLElement>(selector)?.focus();
}

/** Vector primitives come from the approved R2 source, including its clock fallback. */
function RecoveryIcon({ name, framed = true }: { name: 'back' | 'guard' | 'clock' | 'login' | 'shield'; framed?: boolean }) {
  const svg = <svg width={framed ? 18 : 20} height={framed ? 18 : 20} viewBox="0 0 24 24" aria-hidden="true">
    {name === 'back' && <><circle cx="12" cy="12" r="9" fill="currentColor" opacity=".14"/><path d="M13.8 7.8 9.6 12l4.2 4.2" fill="none" stroke="currentColor" strokeWidth="1.9" strokeLinecap="round" strokeLinejoin="round"/></>}
    {name === 'guard' && <><circle cx="9" cy="9" r="3.2" fill="currentColor" opacity=".16"/><circle cx="9" cy="9" r="3.2" fill="none" stroke="currentColor" strokeWidth="1.8"/><path d="M3.5 19a5.5 5.5 0 0 1 11 0" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round"/><path d="M17 8.5l4 1.6v2.6c0 2.3-1.7 4-4 5.1-.9-.4-1.7-1-2.4-1.6" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinejoin="round"/></>}
    {name === 'clock' && <><path d="M12 3l1.9 5.3L19.2 10l-5.3 1.9L12 17.2l-1.9-5.3L4.8 10l5.3-1.7z" fill="currentColor" opacity=".18"/><path d="M12 3l1.9 5.3L19.2 10l-5.3 1.9L12 17.2l-1.9-5.3L4.8 10l5.3-1.7z" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinejoin="round"/><path d="M18.6 15.6l.8 2.2 2.2.8-2.2.8-.8 2.2-.8-2.2-2.2-.8 2.2-.8z" fill="currentColor"/></>}
    {name === 'login' && <><path d="M10 4.5h6.5A1.5 1.5 0 0 1 18 6v12a1.5 1.5 0 0 1-1.5 1.5H10" fill="none" stroke="currentColor" strokeWidth="1.9" strokeLinecap="round"/><circle cx="10" cy="12" r="7.5" fill="currentColor" opacity=".12"/><path d="M3.5 12H13M10 8.5 13.5 12 10 15.5" fill="none" stroke="currentColor" strokeWidth="1.9" strokeLinecap="round" strokeLinejoin="round"/></>}
    {name === 'shield' && <><path d="M12 3.5 5 6v5.2c0 4.4 3 7.4 7 9.3 4-1.9 7-4.9 7-9.3V6z" fill="currentColor" opacity=".14"/><path d="M12 3.5 5 6v5.2c0 4.4 3 7.4 7 9.3 4-1.9 7-4.9 7-9.3V6z" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinejoin="round"/><path d="m9.2 11.8 2 2 3.6-3.8" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round"/></>}
  </svg>;
  return framed ? <span className="s06-r2__icon" aria-hidden="true">{svg}</span> : svg;
}

function ErrorIcon() {
  return <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.9" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><path d="M6 6l12 12M18 6 6 18"/></svg>;
}

function Brand() {
  return <aside className="s06-r2__brand">
    <div className="s06-r2__ring" aria-hidden="true"><svg viewBox="0 0 320 360"><rect x="16" y="20" width="272" height="324" rx="20" fill="none" stroke="currentColor" strokeWidth="2" opacity=".55"/><rect x="40" y="24" width="2.5" height="312" rx="1.25" fill="currentColor" opacity=".45"/>{Array.from({ length: 9 }, (_, i) => <rect key={i} x="40" y={54 + i * 30} width={220 - (i % 3) * 42} height="5" rx="2.5" fill="currentColor" opacity=".5"/>)}</svg></div>
    <div className="s06-r2__lockup"><NyayOneRevLLockup reversed/></div>
    <div className="s06-r2__brandcopy s06-r2__mobile"><h1>Keep your law-school record in one place.</h1><p>Profile, opportunities and case notes, together.</p></div>
    <div className="s06-r2__brandcopy s06-r2__desktop"><div className="s06-r2__eyebrow">A legal workspace for students</div><h1>Learn the law.<br/>Build your path.</h1><p>One record of your academics, interests and verified details.</p><div className="s06-r2__benefits">{['Your record, together', 'Opportunities that fit', 'Read with the source'].map(text => <div key={text}><i aria-hidden="true"/>{text}</div>)}</div></div>
    <div className="s06-r2__legal"><span>Privacy Notice</span><span aria-hidden="true">·</span><span>Terms</span></div>
  </aside>;
}

/** Controlled presentation only. Server/session authority and routing remain in the controller. */
export function S06R2(props: S06R2Props) {
  const { state, busy, mobile, code, onBack } = props;
  const root = useRef<HTMLElement>(null);
  const focusedRequest = useRef(0);
  const lastKeyboardTarget = useRef<HTMLElement | null>(null);
  const rememberKeyboardTarget = (event: FocusEvent<HTMLElement>) => {
    const target = event.target;
    lastKeyboardTarget.current = target instanceof HTMLElement && target.matches(':focus-visible') ? target : null;
  };
  const focusRequest = props.focusRequest ?? 0;
  useEffect(() => {
    if (busy || !root.current) return;
    const replacedKeyboardControl = lastKeyboardTarget.current && !lastKeyboardTarget.current.isConnected
      && document.activeElement === document.body;
    if (!replacedKeyboardControl && (focusRequest === 0 || focusRequest === focusedRequest.current)) return;
    focusedRequest.current = focusRequest;
    focusRecoveryTarget(root.current, state);
  }, [busy, focusRequest, state]);
  const terminal = state === 'locked' || state === 'neterr' || state === 'success';
  const entry = state === 'entry' || state === 'invalidnum' || state === 'submitting';
  const sending = busy || state === 'submitting';
  const displayedMobile = /^[0-9]{10}$/.test(mobile) ? `${mobile.slice(0, 5)} ${mobile.slice(5)}` : mobile;
  const lockSeconds = props.lockedForSeconds;
  const lockDuration = lockSeconds !== null && lockSeconds > 0 && lockSeconds % 60 === 0
    ? `${lockSeconds / 60} ${lockSeconds === 60 ? 'minute' : 'minutes'}` : timeLabel(lockSeconds);
  // Let the controller produce the R2 inline error for a nonempty invalid entry.
  // No network request or validation authority originates in this presentation.
  const canSend = mobile.trim().length > 0 && props.authorityReady && !sending;
  const expires = props.expiresInSeconds;
  const attempts = props.attemptsLeft;
  const canVerify = /^[0-9]{6}$/.test(code) && props.authorityReady && !busy && state !== 'expired' && !terminal
    && expires !== null && Number.isFinite(expires) && expires > 0
    && attempts !== null && Number.isFinite(attempts) && attempts > 0;
  const canResend = props.authorityReady && props.resendAllowed && !busy && !terminal;
  const header = <div className="s06-r2__header">{!terminal && <button type="button" className="s06-r2__back" onClick={onBack} aria-label="Back to sign in"><RecoveryIcon name="back" framed={false}/></button>}<div className="s06-r2__eyebrow">Account recovery</div></div>;
  const title = (heading: string, copy: ReactNode) => <div><h1 className="s06-r2__title">{heading}</h1><p className="s06-r2__description">{copy}</p></div>;
  const submit = (event: FormEvent) => {
    event.preventDefault();
    if (entry ? canSend : canVerify) (entry ? props.onSend : props.onVerify)();
  };
  const metaRow = (icon: ReactNode, label: string, value: string | number) => <div className="s06-r2__metarow">{icon}<span>{label}</span><b>{value}</b></div>;
  const body = entry ? <>
    {title('Recover your account.', 'Enter the mobile number you sign in with. We will send a six-digit code to it.')}
    {state === 'invalidnum' && <div className="s06-r2__summary" role="alert"><a href="#v34-reset-mobile">Enter a valid 10-digit mobile number</a></div>}
    <div className="s06-r2__field"><label htmlFor="v34-reset-mobile">Registered mobile number</label><div className="s06-r2__mobilefield"><span className="s06-r2__prefix">+91</span><input className="s06-r2__input" id="v34-reset-mobile" inputMode="numeric" autoComplete="tel-national" maxLength={11} value={displayedMobile} readOnly={sending} onChange={event => props.onMobileChange(event.target.value.replace(/\s/g, ''))} aria-invalid={state === 'invalidnum' || undefined} aria-describedby={state === 'invalidnum' ? 's06-mobile-error' : undefined}/></div>{state === 'invalidnum' && <div className="s06-r2__error" id="s06-mobile-error"><ErrorIcon/>Enter all 10 digits of your registered mobile number.</div>}</div>
    <div className="s06-r2__privacy"><svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.9" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><path d="M12 3l7 3v6c0 4-3 7-7 9-4-2-7-5-7-9V6z"/></svg><span>If this number matches an account, we will send a code. The response looks the same either way.</span></div>
    <div className="s06-r2__actions"><button className="s06-r2__button s06-r2__button--primary" type="submit" disabled={!canSend}>{state === 'submitting' ? 'Sending…' : <><NyayOneRevLIcon name="send"/>Send recovery code</>}</button></div>
  </> : !terminal ? <>
    {(state === 'wrong' || state === 'expired') && <span className={`s06-r2__chip s06-r2__chip--${state}`}><span aria-hidden="true"/>{state === 'wrong' ? 'Incorrect code' : 'Code expired'}</span>}
    {title('Enter the recovery code.', props.destinationMasked ? <>Sent to <b className="s06-r2__mono">{props.destinationMasked}</b>.</> : 'The recovery response is unavailable. Change number to try again.')}
    <div className="s06-r2__otpwrap"><div className="s06-r2__otpboxes" aria-hidden="true">{Array.from({ length: 6 }, (_, i) => <i className="s06-r2__digit" key={i}>{code[i] ?? ''}</i>)}</div><input className="s06-r2__otp" id="v34-recovery-code" inputMode="numeric" autoComplete="one-time-code" maxLength={6} aria-label="Six-digit recovery code" aria-invalid={state === 'wrong' || undefined} aria-describedby={state === 'wrong' ? 's06-code-error' : state === 'cooldown' ? 's06-resend-cooldown' : undefined} value={code} readOnly={busy} onChange={event => props.onCodeChange(event.target.value)} onPaste={event => { event.preventDefault(); if (!busy) props.onCodeChange(event.clipboardData.getData('text').replace(/[\s-]/g, '')); }}/></div>
    {state === 'wrong' && <div className="s06-r2__error" id="s06-code-error" role="alert"><ErrorIcon/>That code is not correct. Check the last six digits you received.</div>}
    {state === 'cooldown' && <div className="s06-r2__error" id="s06-resend-cooldown" role="status">A new code cannot be sent yet. Wait for the resend countdown, then try again.</div>}
    <div className="s06-r2__metadata">
      {metaRow(<RecoveryIcon name="clock"/>, 'Code expires in', state === 'expired' || expires === 0 ? 'Expired' : timeLabel(expires))}
      {metaRow(<NyayOneRevLIcon name="refresh"/>, 'Resend available', props.resendAllowed ? 'Now' : props.resendInSeconds === null ? 'Unavailable' : `in ${timeLabel(props.resendInSeconds)}`)}
      {metaRow(<RecoveryIcon name="shield"/>, 'Attempts left', attempts !== null && Number.isFinite(attempts) && attempts >= 0 ? attempts : 'Unavailable')}
    </div>
    <div className="s06-r2__actions s06-r2__actions--verify"><button className="s06-r2__button s06-r2__button--primary" type="submit" disabled={!canVerify}><NyayOneRevLIcon name="checkc"/>Verify and continue</button><div className="s06-r2__buttonrow"><button className="s06-r2__button" type="button" onClick={props.onResend} disabled={!canResend}><NyayOneRevLIcon name="refresh"/>Resend code</button><button className="s06-r2__button" type="button" onClick={props.onChangeNumber} disabled={busy}><NyayOneRevLIcon name="pen"/>Change number</button></div></div>
  </> : state === 'locked' ? <>
    <span className="s06-r2__tile s06-r2__tile--error" aria-hidden="true"><RecoveryIcon name="clock" framed={false}/></span>
    {title('Recovery is paused.', lockSeconds !== null && Number.isFinite(lockSeconds) && lockSeconds > 0 ? `Too many attempts were made for this number. You can try again in ${lockDuration}.` : 'Too many attempts were made for this number. Try again after the recovery pause ends.')}
    <button className="s06-r2__button" type="button" onClick={onBack} data-recovery-return><RecoveryIcon name="back"/>Back to sign in</button>
  </> : state === 'neterr' ? <>
    <span className="s06-r2__tile s06-r2__tile--error" aria-hidden="true"><RecoveryIcon name="guard" framed={false}/></span>
    {title('We could not reach NyayOne.', 'We could not confirm whether your code was sent. Check your connection and try again.')}
    <button className="s06-r2__button s06-r2__button--primary" type="button" onClick={props.onRetry} disabled={busy} data-recovery-retry><NyayOneRevLIcon name="refresh"/>Try again</button><button className="s06-r2__button s06-r2__button--ghost" type="button" onClick={onBack}>Back to sign in</button>
  </> : <>
    <span className="s06-r2__tile s06-r2__tile--success" aria-hidden="true"><NyayOneRevLIcon name="checkc" framed={false}/></span>
    {title('Your account is ready.', 'Sign in with your mobile number to continue. You are not signed in yet.')}
    <button className="s06-r2__button s06-r2__button--primary" type="button" onClick={onBack} data-recovery-return><RecoveryIcon name="login"/>Back to sign in</button>
  </>;
  return <section ref={root} onFocusCapture={rememberKeyboardTarget} className={`s06-r2${terminal ? ' s06-r2--terminal' : ''}`} data-screen="S-06" data-state={state} data-nyayone-design="3.2.1-r2" aria-label="Account recovery"><Brand/><div className="s06-r2__body">{terminal ? <div className="s06-r2__column">{header}{body}</div> : <form className="s06-r2__column s06-r2__column--form" onSubmit={submit} noValidate aria-busy={busy}>{header}{body}</form>}</div></section>;
}
