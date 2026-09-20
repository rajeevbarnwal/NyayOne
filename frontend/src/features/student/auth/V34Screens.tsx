import { createContext, useContext, useEffect, useMemo, useRef, useState, useSyncExternalStore, type KeyboardEvent, type ReactNode } from 'react';
import { Navigate, useLocation, useNavigate } from 'react-router-dom';
import type { ThemeMode } from '../../../hooks/useTheme';
import { useStudentSession, type StudentSessionPhase } from '../../../app/authContext';
import {
  DOB_ERROR,
  MOBILE_ERROR,
  isRegistrableDob,
  isValidMobile,
  nameErrorMessage,
  namePartsToPayload,
  todayLocalISO,
  validateNameParts,
} from '../lib/registration';
import { PRIVACY_NOTICE_VERSION, TERMS_VERSION } from '../lib/consent';
import {
  RegistrationApiError,
  cancelStudentOtp,
  registerStudent,
  resendStudentOtp,
  getLoginChannels,
  isMaskedEmailDestination,
  isMaskedMobileDestination,
  startEmailLoginOtp,
  startLoginOtp,
  type LoginChannels,
  verifyLoginOtp,
  verifyStudentOtp,
  logoutStudent,
} from '../lib/registrationApi';
import { useOtpFlowState } from '../lib/useOtpFlowState';
import { isValidOtpInput, normalizeOtpDigits } from '../lib/otpInput';
import { ProfileStep1, ProfileStep2 } from '../profile/ProfileScreens';
import {
  profileErrorMessage,
  profileSectionRoute,
  type StudentProfileProjection,
} from '../lib/profileApi';
import { resolveProfileStepRoute, useDismissProfilePrompt, useStudentProfileProjection } from '../profile/profileHooks';
import { isStudentMutationCancellation } from '../lib/useStudentMutation';
import { InfoTooltip } from '../components';
import { consumeStudentAuthTransitionNotice, hasStudentLogoutFailure, recordStudentAuthTransitionNotice, subscribeStudentAuthTransitionNotice } from '../lib/studentAuthTransitionNotice';
import { useRouteContinuation } from '../lib/routeContinuation';
import { resolvedProfileReauthResumeRoute } from '../profile/profileReauthHandoff';
import { NyayOneAuthSelectors } from './NyayOneAuthSelectors';
import { NyayOneRevLIcon, NyayOneRevLLockup, type NyayOneRevLIconName } from './NyayOneRevLIcon';
import { S01R2, readR2OnboardingSeen } from './S01R2';
import { S02R2 } from './S02R2';
import { S06Recovery } from './S06Recovery';

type ScreenProps = { theme?: ThemeMode; toggleTheme?: () => void };
const OtpScreenThemeContext = createContext<ScreenProps>({});
type IconName =
  | 'add' | 'back' | 'calendar' | 'career' | 'check' | 'clinical' | 'close'
  | 'community' | 'digest' | 'drafting' | 'forward' | 'home' | 'key' | 'moon'
  | 'moot' | 'prep' | 'profile' | 'research' | 'retry' | 'save' | 'send' | 'sun'
  | 'verify';

const SESSION_BOUNDARY_FAILURE_CODES = new Set([
  'invalid_student_session_projection',
  'session_unavailable',
  'student_reauth_session_unavailable',
]);

export function otpVerificationFailureMessage(caught: unknown): string {
  const code = caught instanceof Error ? caught.message : '';
  if (
    code.startsWith('student_auth_transition_')
    || SESSION_BOUNDARY_FAILURE_CODES.has(code)
  ) {
    return 'This browser cannot safely change sessions. Check browser privacy support and try again.';
  }
  if (caught instanceof RegistrationApiError && ['locked', 'otp_locked'].includes(caught.code)) {
    const seconds = caught.otpState?.lockedForSeconds;
    return seconds === null || seconds === undefined
      ? 'Too many attempts. Verification is temporarily locked.'
      : `Too many attempts. Try again in ${seconds} seconds.`;
  }
  if (caught instanceof RegistrationApiError && ['expired', 'otp_expired'].includes(caught.code)) {
    return 'That code has expired. Request a new code when the server allows it.';
  }
  return 'That code could not be verified. Check all six digits.';
}

function V34Icon({ name, size = 24 }: { name: IconName; size?: number }) {
  const common = { fill: 'none', stroke: 'currentColor', strokeWidth: 1.9, strokeLinecap: 'round' as const, strokeLinejoin: 'round' as const };
  return (
    <svg className={`v34-icon v34-icon--${name}`} width={size} height={size} viewBox="0 0 24 24" aria-hidden="true" tabIndex={-1} focusable="false">
      {name === 'key' && <><circle cx="8" cy="9" r="4" {...common}/><path d="m11 12 8 8m-4-4 2-2" {...common}/></>}
      {name === 'add' && <><circle cx="9" cy="8" r="4" {...common}/><path d="M2.5 21c.5-4.3 3-6.6 6.5-6.6 1.6 0 3 .5 4.1 1.3" {...common}/><circle cx="18" cy="17.5" r="4" className="v34-icon__fill"/><path d="M18 15.5v4m-2-2h4" stroke="var(--v34-on-icon)" strokeWidth="1.8" strokeLinecap="round"/></>}
      {name === 'send' && <><path d="M21 3 3 10l7 2.5L21 3Z" className="v34-icon__fill"/><path d="m21 3-5.5 18-5.5-8.5L21 3Z" className="v34-icon__fill2"/></>}
      {name === 'forward' && <><rect x="3" y="3" width="12" height="18" rx="2" className="v34-icon__fill"/><path d="M11 12h10m-4-4 4 4-4 4" {...common}/></>}
      {name === 'check' && <><circle cx="12" cy="12" r="10" className="v34-icon__fill2"/><path d="m7 12.5 3 3 7-7" stroke="white" strokeWidth="2.2" fill="none" strokeLinecap="round" strokeLinejoin="round"/></>}
      {name === 'close' && <><path d="m6 6 12 12M18 6 6 18" {...common}/></>}
      {name === 'verify' && <><circle cx="12" cy="12" r="10" className="v34-icon__fill"/><path d="m7 12.5 3 3 7-7" stroke="var(--v34-on-icon)" strokeWidth="2.2" fill="none" strokeLinecap="round" strokeLinejoin="round"/></>}
      {name === 'retry' && <><path d="M20 12a8 8 0 1 1-2.6-5.9" {...common}/><path d="M18 3v4h-4" {...common}/></>}
      {name === 'back' && <path d="m15 5-7 7 7 7" {...common}/>} 
      {name === 'save' && <><path d="M6 3h12v18l-6-4.5L6 21V3Z" className="v34-icon__fill"/><path d="m9 9 2 2 4-4" stroke="var(--v34-on-icon)" strokeWidth="2" fill="none" strokeLinecap="round"/></>}
      {name === 'sun' && <><circle cx="12" cy="12" r="4" className="v34-icon__fill"/><path d="M12 2v2m0 16v2M2 12h2m16 0h2M5 5l1.5 1.5m11 11L19 19M5 19l1.5-1.5m11-11L19 5" {...common}/></>}
      {name === 'moon' && <path d="M20 15A8.5 8.5 0 0 1 9 4a9 9 0 1 0 11 11Z" className="v34-icon__fill"/>}
      {name === 'home' && <><path d="m3 11 9-7 9 7" {...common}/><path d="M5 10v10h14V10M9 20v-6h6v6" {...common}/></>}
      {name === 'research' && <><circle cx="10" cy="10" r="6" {...common}/><path d="m14.5 14.5 5 5M10 7v6m-3-3h6" {...common}/></>}
      {name === 'calendar' && <><rect x="3" y="5" width="18" height="16" rx="2" {...common}/><path d="M7 3v4m10-4v4M3 10h18" {...common}/></>}
      {name === 'prep' && <><circle cx="12" cy="12" r="9" {...common}/><circle cx="12" cy="12" r="4" {...common}/><path d="M12 3v5m9 4h-5m-4 9v-5M3 12h5" {...common}/></>}
      {name === 'digest' && <><path d="M5 4h12a2 2 0 0 1 2 2v14H7a2 2 0 0 1-2-2V4Z" {...common}/><path d="M9 8h6m-6 4h6m-6 4h4" {...common}/></>}
      {name === 'moot' && <><path d="M12 3v17M7 6h10M5 9l-3 6h6L5 9Zm14 0-3 6h6l-3-6ZM8 21h8" {...common}/></>}
      {name === 'drafting' && <><path d="m4 17-.8 3.8L7 20l11-11-3-3L4 17Z" {...common}/><path d="m13.5 7.5 3 3" {...common}/></>}
      {name === 'career' && <><rect x="3" y="7" width="18" height="13" rx="2" {...common}/><path d="M9 7V4h6v3m-3 4v5m-2-2h4" {...common}/></>}
      {name === 'clinical' && <><circle cx="12" cy="12" r="9" {...common}/><path d="M12 7v10M7 12h10" {...common}/></>}
      {name === 'community' && <><path d="M4 5h16v11H9l-5 4V5Z" {...common}/><path d="M8 9h8m-8 3h5" {...common}/></>}
      {name === 'profile' && <><circle cx="12" cy="8" r="4" {...common}/><path d="M4 21c.8-4.2 3.6-6.5 8-6.5s7.2 2.3 8 6.5" {...common}/></>}
    </svg>
  );
}

function ThemeButton({ theme = 'light', toggleTheme }: ScreenProps) {
  return (
    <button type="button" className="v34-theme" onClick={toggleTheme} aria-label={`Switch to ${theme === 'dark' ? 'light' : 'dark'} theme`}>
      <V34Icon name={theme === 'dark' ? 'moon' : 'sun'} size={20}/>
    </button>
  );
}

function RevLTopbar({ theme, toggleTheme }: ScreenProps) {
  return (
    <header className="v321-topbar">
      <NyayOneRevLLockup reversed={theme === 'dark'}/>
      <nav aria-label="Product areas">
        <button type="button" disabled aria-disabled="true">Home</button>
        <button type="button" disabled aria-disabled="true">Research</button>
        <button type="button" disabled aria-disabled="true">Calendar</button>
        <button type="button" disabled aria-disabled="true">Careers</button>
        <button type="button" disabled aria-disabled="true">Profile</button>
      </nav>
      <span className="v321-secure">Secure Access</span>
      {toggleTheme && <ThemeButton theme={theme} toggleTheme={toggleTheme}/>}
    </header>
  );
}

function RevLBrandPanel({ verification = false }: { verification?: boolean }) {
  return (
    <aside className={`v321-brandpanel${verification ? ' v321-brandpanel--verification' : ''}`} aria-label="NyayOne student account benefits">
      <span className="v321-brandpanel__ring" aria-hidden="true"/>
      <NyayOneRevLLockup reversed/>
      <div className="v321-brandpanel__copy">
        {!verification && <span className="v321-eyebrow">A legal workspace for students</span>}
        <h2>{verification
          ? 'Your account begins with verified access.'
          : <><span className="v321-brandpanel__desktop-copy">Learn the law.<br/>Build your path.</span><span className="v321-brandpanel__mobile-copy">The record of your law-school career.</span></>}</h2>
        <p>{verification
          ? 'Successful verification signs you in. Profile completion is recommended, not forced.'
          : <><span className="v321-brandpanel__desktop-copy">Research, opportunities, mentoring and your professional profile, connected through one trusted NyayOne identity.</span><span className="v321-brandpanel__mobile-copy">Internships, moots, research and mentors: one verified student identity, private by default.</span></>}</p>
        <div className="v321-brandpanel__benefits" role="group" aria-label="Account benefits">
          <span>{verification ? 'Passwordless' : 'Passwordless access'}</span><span>Private by design</span><span>Built for law students</span>
        </div>
      </div>
      <span className="v321-brandpanel__legal">Legal, on the record</span>
    </aside>
  );
}

function RevLLegalFooter({ plainText = false }: { plainText?: boolean }) {
  if (plainText) return <footer className="v321-legal"><span>Privacy Notice</span><span aria-hidden="true">·</span><span>Terms</span><span aria-hidden="true">·</span><span>Accessibility</span></footer>;
  return <footer className="v321-legal"><a href="/s-19">Privacy Notice</a><span aria-hidden="true">·</span><a href="/terms">Terms</a><span aria-hidden="true">·</span><a href="/accessibility">Accessibility</a></footer>;
}

function PrivacyNote() {
  return (
    <div className="v321-privacy-note">
      <NyayOneRevLIcon name="shield" framed={false}/>
      <span>If these details match an account, we’ll send a sign-in code. For your privacy, the response looks the same either way. Data handled under the DPDP Act, 2023.</span>
    </div>
  );
}

export async function retireStudentOtpPersonaContext(
  retire: () => ReturnType<typeof cancelStudentOtp>,
  onRetired: ((state: Awaited<ReturnType<typeof cancelStudentOtp>>) => void) | undefined,
  returnToPersona: () => void,
): Promise<void> {
  const state = await retire();
  onRetired?.(state);
  returnToPersona();
}

function CreateAccountContext({
  disabled = false,
  onChangeStart,
  onRetired,
  onChangeError,
}: {
  disabled?: boolean;
  onChangeStart?: () => void;
  onRetired?: (state: Awaited<ReturnType<typeof cancelStudentOtp>>) => void;
  onChangeError?: () => void;
}) {
  const nav = useNavigate();
  const [changing, setChanging] = useState(false);
  async function changePersona() {
    if (disabled || changing) return;
    onChangeStart?.();
    setChanging(true);
    try {
      await retireStudentOtpPersonaContext(
        cancelStudentOtp,
        onRetired,
        () => nav('/s-03', { replace: true, state: { nyay7Focus: 'persona' } }),
      );
    } catch {
      onChangeError?.();
    } finally {
      setChanging(false);
    }
  }
  return (
    <div className="v321-context" data-nyayone-create-context="">
      <span className="v321-context__persona"><NyayOneRevLIcon name="users"/>Joining as <b>Student</b><button type="button" data-nyayone-persona-change="" aria-label="Change persona" onClick={() => { void changePersona(); }} disabled={disabled || changing}>Change</button></span>
      <NyayOneAuthSelectors showPersona={false} compact/>
    </div>
  );
}

function Screen({ id, variant = 'auth', aside, children }: { id: string; variant?: 'auth' | 'app' | 'splash' | 'wizard'; aside?: ReactNode; children: ReactNode }) {
  const revisionL = ['S-03', 'S-04', 'S-05', 'S-08', 'S-09'].includes(id);
  if (revisionL) {
    return (
      <div className={`v34-screen v34-screen--${variant} v321-screen`} data-screen={id} data-nyayone-design="3.2.1-rev-l">
        {aside}
        {children}
      </div>
    );
  }
  return (
    <section className={`v34-screen v34-screen--${variant}`} data-screen={id} aria-labelledby={`${id}-title`}>
      {aside}
      {children}
    </section>
  );
}

function Pane({ children }: { children: ReactNode }) {
  return <div className="v34-pane"><div className="v34-status" aria-hidden="true"><span>9:41</span><span>100</span></div>{children}</div>;
}

function Field({ id, label, value, onChange, type = 'text', inputMode, autoComplete, placeholder, optional, inlineOptional = false, required, error, help, max, maxLength, prefix, revisionLIcon }: {
  id: string; label: string; value: string; onChange: (value: string) => void; type?: string; inputMode?: 'text' | 'numeric' | 'tel' | 'email'; autoComplete?: string;
  placeholder?: string; optional?: boolean; inlineOptional?: boolean; required?: boolean; error?: string; help?: string; max?: string; maxLength?: number; prefix?: string; revisionLIcon?: NyayOneRevLIconName;
}) {
  const describedBy = error ? `${id}-error` : undefined;
  return (
    <div className={`v34-field${error ? ' v34-field--error' : ''}${optional ? ' v34-field--optional' : ''}`}>
      <span className="v34-field__top">
        <label htmlFor={id}>{revisionLIcon && <span className="v321-icon--indigo"><NyayOneRevLIcon name={revisionLIcon}/></span>}<span>{label}</span>{optional && inlineOptional && <> <span className="v321-optional-label">(Optional)</span></>}</label>
        <span className="v34-field__meta">
          {optional && !inlineOptional && <small>OPTIONAL</small>}
          {help && <InfoTooltip label={`More information about ${label}`} text={help}/>}
        </span>
      </span>
      <span className="v34-field__control">{prefix && <span>{prefix}</span>}<input id={id} value={value} type={type} inputMode={inputMode} autoComplete={autoComplete} placeholder={placeholder} max={max} maxLength={maxLength} required={required} aria-required={required || undefined} aria-invalid={error ? true : undefined} aria-describedby={describedBy} onChange={(event) => onChange(event.target.value)}/></span>
      {error && <span id={`${id}-error`} className="v34-field__error" role="alert">{error}</span>}
    </div>
  );
}

export function splashDestination(
  phase: StudentSessionPhase,
  r2OnboardingSeen = false,
): string | null {
  if (phase === 'authenticated') return '/s-07';
  if (phase === 'anonymous') return r2OnboardingSeen ? '/s-03' : '/s-02';
  return null;
}

export function V34Splash() {
  const nav = useNavigate();
  const session = useStudentSession();
  useEffect(() => {
    const destination = splashDestination(session.phase, readR2OnboardingSeen());
    if (destination) nav(destination, { replace: true });
  }, [nav, session.phase]);
  return <S01R2 phase={session.phase} retry={() => { void session.refresh(); }}/>;
}

export function V34Onboarding() {
  return <S02R2/>;
}

export function V34AuthGate(props: ScreenProps) {
  const nav = useNavigate();
  const location = useLocation();
  const [deletionAccepted] = useState(() => (
    consumeStudentAuthTransitionNotice('account_deletion_accepted')
  ));
  useEffect(() => {
    if ((location.state as { nyay7Focus?: string } | null)?.nyay7Focus !== 'persona') return;
    const frame = requestAnimationFrame(() => {
      document.querySelector<HTMLButtonElement>('[data-screen="S-03"] [data-nyayone-persona-trigger]')?.focus();
    });
    return () => cancelAnimationFrame(frame);
  }, [location.state]);
  return (
    <Screen id="S-03">
      <RevLTopbar {...props}/>
      <RevLBrandPanel/>
      <Pane><main id="main-content" aria-labelledby="S-03-title" className="v34-main v321-form v321-form--gateway">
        <div><span className="v321-eyebrow">Welcome to NyayOne</span><h1 id="S-03-title" className="v34-title">Where would you like to begin?</h1><p className="v34-lede">Return to your workspace or create a secure student account in a few clear steps.</p></div>
        {deletionAccepted && (
          <div className="v34-banner" role="status">
            <b>DELETION REQUEST ACCEPTED</b>
            <span>You have been signed out and this browser's student context has been cleared.</span>
          </div>
        )}
        <button type="button" className="v321-primary" aria-label="Sign In Securely" onClick={() => nav('/s-04')}><NyayOneRevLIcon name="otp"/><span>Sign In Securely</span></button>
        <p className="v321-signin-note">Signing in? Your saved role and language apply automatically. No need to choose again.</p>
        <div className="v321-join-card"><span className="v321-eyebrow">New here? Choose how you join</span><NyayOneAuthSelectors/><button type="button" className="v321-secondary" aria-label="Create Student Account" onClick={() => nav('/s-08')}><span className="v321-icon--indigo"><NyayOneRevLIcon name="userplus"/></span><span>Create Student Account</span></button></div>
        <p className="v321-consent">By continuing, you acknowledge the Privacy Notice. No sign-in code is requested on this screen. Persona and language set presentation and routing intent only. They are never authorization.</p>
        <span className="v321-dpdp"><i aria-hidden="true"/>DPDP Act, 2023</span>
      </main><RevLLegalFooter plainText/></Pane>
    </Screen>
  );
}

const LOGIN_EMAIL_RE = /^[^\s@]+@[^\s@]+\.[^\s@]{2,}$/u;
const LOGIN_EMAIL_ERROR = 'Enter a valid email address.';

function isValidLoginEmail(value: string): boolean {
  const trimmed = value.trim();
  return trimmed.length > 0 && [...trimmed].length <= 254 && LOGIN_EMAIL_RE.test(trimmed);
}

export function V34Login(props: ScreenProps) {
  // NYAY-12: channel availability is a server projection (fail-closed). Until
  // the projection arrives, or if the server disables email, S-04 renders the
  // sealed mobile-only presentation.
  const [channels, setChannels] = useState<LoginChannels | null>(null);
  const session = useStudentSession();
  useEffect(() => {
    // The shared request lease refuses reads while the session bootstrap
    // transition is active; re-read the projection once the phase settles.
    if (session.phase === 'pending') return undefined;
    let active = true;
    getLoginChannels()
      .then((projection) => { if (active) setChannels(projection); })
      .catch(() => { if (active) setChannels(null); });
    return () => { active = false; };
  }, [session.phase]);
  return <V34LoginForm {...props} channels={channels}/>;
}

export function V34LoginForm(props: ScreenProps & { channels: LoginChannels | null; initialChannel?: 'mobile' | 'email' }) {
  const { channels, initialChannel, ...topbarProps } = props;
  const nav = useNavigate();
  const emailEnabled = channels?.email === true;
  const [channel, setChannel] = useState<'mobile' | 'email'>(emailEnabled && initialChannel === 'email' ? 'email' : 'mobile');
  const [mobile, setMobile] = useState('');
  const [email, setEmail] = useState('');
  const [busy, setBusy] = useState(false);
  const [errors, setErrors] = useState<Record<string, string>>({});
  const pendingLogin = useRef<AbortController | null>(null);
  useEffect(() => () => {
    pendingLogin.current?.abort();
    pendingLogin.current = null;
  }, []);
  const activeChannel = emailEnabled ? channel : 'mobile';
  function chooseChannel(next: 'mobile' | 'email') {
    if (next === 'email' && !emailEnabled) return;
    setChannel(next);
    setErrors({});
  }
  async function submit() {
    if (busy || pendingLogin.current) return;
    const next: Record<string, string> = {};
    if (activeChannel === 'email') {
      if (!isValidLoginEmail(email)) next.email = LOGIN_EMAIL_ERROR;
    } else if (!isValidMobile(mobile)) {
      next.mobile = MOBILE_ERROR;
    }
    setErrors(next);
    if (Object.keys(next).length) return;
    const request = new AbortController();
    pendingLogin.current = request;
    // Navigation can retire this screen while a response is pending. Abort
    // the transport and separately fence every continuation to this request.
    const isCurrentRequest = () => pendingLogin.current === request && !request.signal.aborted;
    setBusy(true);
    try {
      if (activeChannel === 'email') {
        await startEmailLoginOtp(email.trim(), request.signal);
      } else {
        await startLoginOtp(mobile, request.signal);
      }
      if (!isCurrentRequest()) return;
      nav('/s-05');
    } catch (caught) {
      if (!isCurrentRequest()) return;
      if (caught instanceof RegistrationApiError && caught.code === 'email_login_disabled') {
        setErrors({ submit: 'Email sign-in is not available right now. Use your mobile number.' });
      } else {
        setErrors({ submit: 'A one time code could not be requested. Please retry.' });
      }
    } finally {
      if (isCurrentRequest()) {
        pendingLogin.current = null;
        setBusy(false);
      }
    }
  }
  return (
    <Screen id="S-04">
      <RevLTopbar {...topbarProps}/>
      <RevLBrandPanel/>
      <Pane><main id="main-content" aria-labelledby="S-04-title" className="v34-main v321-form v321-form--login">
        <CreateAccountContext
          disabled={busy}
          onChangeStart={() => { setBusy(true); setMobile(''); setEmail(''); setErrors({}); }}
          onChangeError={() => {
            setBusy(false);
            setErrors({ submit: 'Your sign-in context could not be safely cleared. Please retry.' });
          }}
        />
        <span className="v321-eyebrow">Sign in</span>
        <h1 id="S-04-title" className="v34-title">How do you want to sign in?</h1>
        <div className="v321-segment" role="group" aria-label="Sign-in identity">
          <button type="button" aria-pressed={activeChannel === 'mobile'} onClick={() => chooseChannel('mobile')} disabled={busy || undefined}><span className="v321-icon--indigo"><NyayOneRevLIcon name="sim"/></span><span>Mobile Number</span></button>
          <button type="button" aria-pressed={activeChannel === 'email'} aria-disabled={emailEnabled ? undefined : true} disabled={!emailEnabled || busy} onClick={() => chooseChannel('email')}><span className="v321-icon--gold"><NyayOneRevLIcon name="badge"/></span><span>Verified Email</span></button>
        </div>
        <div className="v34-fieldset">
          {activeChannel === 'email'
            ? <Field id="v34-login-email" label="EMAIL ADDRESS" value={email} onChange={setEmail} type="email" inputMode="email" autoComplete="email" error={errors.email} maxLength={254} revisionLIcon="badge"/>
            : <Field id="v34-login-mobile" label="Mobile Number" value={mobile} onChange={setMobile} type="tel" inputMode="numeric" autoComplete="tel-national" prefix="+91" error={errors.mobile} maxLength={15} revisionLIcon="sim"/>}
        </div>
        <p className="v321-help">{activeChannel === 'email'
          ? 'We sign you in with a one-time code by email to your verified address. Only an email you have already verified from your profile can sign you in.'
          : emailEnabled
            ? 'We sign you in with a one-time code by SMS. A verified email from your profile can also sign you in.'
            : 'We sign you in with a one-time code by SMS. Mobile is the only enabled login channel in this release.'}</p>
        {errors.submit && <span className="v34-field__error" role="alert">{errors.submit}</span>}
        <PrivacyNote/>
        <button type="button" className="v321-primary" onClick={submit} disabled={busy} aria-label="Send Code"><NyayOneRevLIcon name="send"/><span>Send Code</span></button>
      </main><RevLLegalFooter plainText/></Pane>
    </Screen>
  );
}

export function V34AccountRecovery() {
  return <S06Recovery/>;
}

const S07_PREVIEWS = [
  { title: 'Internships', icon: 'brief', color: '#2E3A8C', text: '3 new matches for arbitration in Bengaluru' },
  { title: 'Moot Court', icon: 'mic2', color: '#9A2B21', text: 'Memorial workspace · draft due Mon' },
  { title: 'Research', icon: 'book', color: '#0E6470', text: 'Saved thread: anticipatory bail standard' },
  { title: 'Mentors', icon: 'users', color: '#1E6B4A', text: 'Adv. Meera Krishnan · Wed 6:30 PM' },
] as const;

/** Revision L primitives used only by the S-07 landing composition. */
function S07Icon({ name }: { name: 'spark' | 'clock' | 'brief' | 'mic2' | 'book' | 'users' }) {
  if (name === 'users') return <NyayOneRevLIcon name="users" framed={false}/>;
  return (
    <svg width="18" height="18" viewBox="0 0 24 24" aria-hidden="true" tabIndex={-1} focusable="false">
      {name === 'spark' && <><path d="M12 3l1.9 5.3L19.2 10l-5.3 1.9L12 17.2l-1.9-5.3L4.8 10l5.3-1.7z" fill="currentColor" opacity=".18"/><path d="M12 3l1.9 5.3L19.2 10l-5.3 1.9L12 17.2l-1.9-5.3L4.8 10l5.3-1.7z" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinejoin="round"/><path d="M18.6 15.6l.8 2.2 2.2.8-2.2.8-.8 2.2-.8-2.2-2.2-.8 2.2-.8z" fill="currentColor"/></>}
      {name === 'clock' && <><circle cx="12" cy="12" r="8.5" fill="currentColor" opacity=".14"/><circle cx="12" cy="12" r="8.5" fill="none" stroke="currentColor" strokeWidth="1.9"/><path d="M12 7.5V12l3 2" fill="none" stroke="currentColor" strokeWidth="1.9" strokeLinecap="round" strokeLinejoin="round"/></>}
      {name === 'brief' && <><rect x="3.5" y="7" width="17" height="12.5" rx="2.5" fill="currentColor" opacity=".16"/><rect x="3.5" y="7" width="17" height="12.5" rx="2.5" fill="none" stroke="currentColor" strokeWidth="1.9"/><path d="M9 7V5.5A1.5 1.5 0 0 1 10.5 4h3A1.5 1.5 0 0 1 15 5.5V7M3.5 12h17" fill="none" stroke="currentColor" strokeWidth="1.9"/></>}
      {name === 'mic2' && <><rect x="9.3" y="3.5" width="5.4" height="10.5" rx="2.7" fill="currentColor" opacity=".2"/><rect x="9.3" y="3.5" width="5.4" height="10.5" rx="2.7" fill="none" stroke="currentColor" strokeWidth="1.9"/><path d="M6 11.5a6 6 0 0 0 12 0M12 17.5V20" fill="none" stroke="currentColor" strokeWidth="1.9" strokeLinecap="round"/></>}
      {name === 'book' && <><path d="M5 4.5h6a2 2 0 0 1 2 2V20a2 2 0 0 0-2-1.5H5z" fill="currentColor" opacity=".16"/><path d="M5 4.5h6a2 2 0 0 1 2 2V20a2 2 0 0 0-2-1.5H5zM19 4.5h-6a0 0 0 0 0 0 0V20a2 2 0 0 1 2-1.5h4z" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinejoin="round"/></>}
    </svg>
  );
}

export const PROFILE_PROMPT_DISMISS_NAVIGATION = {
  to: '/s-14',
  options: { replace: true, state: { focusProfilePromptDestination: true } },
} as const;

export function verifiedHomeShouldAutoOpenDashboard(
  profile: StudentProfileProjection | undefined,
  dismissalInFlight: boolean,
): boolean {
  return Boolean(
    profile
    && !dismissalInFlight
    && (profile.isComplete || profile.profilePrompt.dismissedForSession || !profile.profilePrompt.shouldShow),
  );
}

export function V34VerifiedHome(props: ScreenProps) {
  const nav = useNavigate();
  const captureContinuation = useRouteContinuation();
  const logoutFailed = useSyncExternalStore(subscribeStudentAuthTransitionNotice, hasStudentLogoutFailure, () => false);
  const profile = useStudentProfileProjection();
  const dismiss = useDismissProfilePrompt();
  const backgroundRef = useRef<HTMLDivElement>(null);
  const dialogRef = useRef<HTMLDivElement>(null);
  const headingRef = useRef<HTMLHeadingElement>(null);
  const dismissInFlight = useRef(false);
  const [dismissError, setDismissError] = useState<string | null>(null);
  const dismissErrorRef = useRef<HTMLDivElement>(null);
  useEffect(() => { if (dismissError) dismissErrorRef.current?.focus(); }, [dismissError]);
  const showDialog = Boolean(profile.data && !profile.data.isComplete && profile.data.profilePrompt.shouldShow);

  useEffect(() => {
    if (verifiedHomeShouldAutoOpenDashboard(profile.data, dismissInFlight.current)) {
      nav('/s-14', { replace: true });
    }
  }, [nav, profile.data]);

  useEffect(() => {
    const background = backgroundRef.current;
    if (!showDialog || !background) return undefined;
    background.setAttribute('inert', '');
    headingRef.current?.focus();
    return () => { background.removeAttribute('inert'); };
  }, [showDialog]);

  async function signOut() {
    const current = captureContinuation();
    try {
      await logoutStudent();
      if (current()) nav('/s-03', { replace: true });
      // In the real auth provider the transition can unmount this dialog.
      // Its route guard then redirects only after an authoritative anonymous probe.
    } catch {
      // Process-only, non-identifying notice survives the transition's unmount.
      // It is cleared by the next session lifecycle; never claim server revocation.
      recordStudentAuthTransitionNotice('sign_out_failed');
    }
  }

  async function dismissAndContinue() {
    if (dismissInFlight.current) return;
    dismissInFlight.current = true;
    setDismissError(null);
    try {
      await dismiss.mutateAsync();
      nav(PROFILE_PROMPT_DISMISS_NAVIGATION.to, PROFILE_PROMPT_DISMISS_NAVIGATION.options);
    } catch (error) {
      dismissInFlight.current = false;
      if (isStudentMutationCancellation(error)) return;
      setDismissError(profileErrorMessage(error));
    }
  }

  function trapDialogKeys(event: KeyboardEvent<HTMLDivElement>) {
    if (event.key === 'Escape') {
      event.preventDefault();
      void dismissAndContinue();
      return;
    }
    if (event.key !== 'Tab') return;
    const focusable = Array.from(dialogRef.current?.querySelectorAll<HTMLElement>(
      'button:not([disabled]), a[href], [tabindex]:not([tabindex="-1"])',
    ) ?? []);
    if (focusable.length === 0) { event.preventDefault(); return; }
    const first = focusable[0]; const last = focusable[focusable.length - 1];
    if (event.shiftKey && (document.activeElement === first || document.activeElement === headingRef.current)) { event.preventDefault(); last.focus(); }
    else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first.focus(); }
  }

  if (!profile.data) {
    return <Screen id="S-07" variant="app"><Pane><main className="v34-main"><h1 id="S-07-title" className="sr-only">Student workspace</h1>{profile.isPending ? <div role="status">Loading your profile…</div> : <div role="alert">{profileErrorMessage(profile.error)} <button type="button" onClick={() => { void profile.refetch(); }}>Retry profile</button></div>}</main></Pane></Screen>;
  }
  if (!showDialog) return <Screen id="S-07" variant="app"><Pane><main className="v34-main"><h1 id="S-07-title" className="sr-only">Student workspace</h1><div role="status">Opening your dashboard…</div></main></Pane></Screen>;
  const projection = profile.data;
  const personal = projection.profile.personal;
  const fullName = [personal.firstName, personal.middleName, personal.lastName].filter(Boolean).join(' ');
  const initials = [personal.firstName, personal.lastName].map((name) => [...name.trim()][0] ?? '').join('').toUpperCase();
  return (
    <section className="v34-screen v34-screen--app v34-s07" data-screen="S-07" aria-labelledby="S-07-title">
      <div ref={backgroundRef} className="v34-s07-background" data-testid="profile-prompt-background" aria-hidden={showDialog ? true : undefined}>
        <div className="v34-s07-app">
          <header className="v34-s07-appbar">
            <span className="v34-s07-desktopbrand"><NyayOneRevLLockup/></span>
            <span className="v34-s07-mobilebrand"><img src="/brand/nyayone-mark.svg" alt="" aria-hidden="true" draggable="false"/><b>NyayOne</b></span>
            <nav className="v34-s07-nav" aria-label="Site">
              <button type="button" onClick={() => nav('/s-14')}>Home</button>
              {['Research', 'Calendar', 'Careers'].map((label) => <button type="button" key={label} aria-disabled="true">{label}</button>)}
              <button type="button" onClick={() => nav('/s-17')}>Profile</button>
            </nav>
            <div className="v34-s07-tools"><ThemeButton {...props}/><button type="button" className="v34-s07-avatar" aria-label={`Your Profile · ${fullName}`} onClick={() => nav('/s-17')}><span>{initials}</span></button></div>
          </header>
          <div className="v34-s07-body">
            <div className="v34-s07-main">
              <div className="v34-s07-eyebrow">Student workspace · S-07 Home</div>
              <h1 id="S-07-title" className="v34-s07-title">Your legal journey, in one place.</h1>
              <p className="v34-s07-copy">Continue your law-school record: internships, moots, research and mentors.</p>
              {projection.accessMode === 'limited' && <div className="v34-s07-note v34-s07-note--limited"><NyayOneRevLIcon name="shield" framed={false}/><span><b>Limited access.</b> Community and sharing stay off until guardian consent is recorded.</span><button type="button" className="v34-s07-button" onClick={() => nav('/s-16')}>Guardian Consent</button></div>}
              <div className="v34-s07-tiles">
                {S07_PREVIEWS.map((item) => <button type="button" className="v34-s07-tile" aria-disabled="true" key={item.title}><h3><span className="v34-s07-tile-icon" style={{ color: item.color, backgroundColor: `${item.color}1F` }}><S07Icon name={item.icon}/></span>{item.title}</h3><p>{item.text}</p><p className="v34-s07-preview-label">Preview only</p></button>)}
              </div>
              <div className="v34-s07-note">
                <NyayOneRevLIcon name={projection.institutionalEmailStatus === 'verified' ? 'checkc' : 'shield'} framed={false}/>
                <span>{projection.institutionalEmailStatus === 'verified' ? 'Institutional email verified.' : 'Institutional email not verified yet, so some listings stay locked.'}</span>
                {projection.institutionalEmailStatus !== 'verified' && <button type="button" className="v34-s07-button" onClick={() => nav('/s-15')}><NyayOneRevLIcon name="badge"/>Verify Now</button>}
              </div>
            </div>
            <aside className="v34-s07-aside">
              <div><div className="v34-s07-eyebrow">Why complete your profile?</div><p>Internship matches, moot records and mentor suggestions all key off your college, year and interests. Two minutes now, better matches all year.</p></div>
              <div><div className="v34-s07-eyebrow">Privacy</div><p>Every field is private by default. Gold appears only when something is verified.</p></div>
            </aside>
          </div>
        </div>
      </div>
      <div className="v34-dialog-backdrop v34-s07-backdrop">
        <div ref={dialogRef} role="dialog" aria-modal="true" aria-labelledby="profile-completion-dialog-title" aria-describedby="profile-completion-dialog-description" data-testid="profile-completion-dialog" className="v34-card v34-dialog v34-s07-dialog" onKeyDown={trapDialogKeys}>
          <button type="button" className="v34-hit v34-dialog__close" aria-label="Close profile prompt" onClick={() => { void dismissAndContinue(); }} disabled={dismiss.isPending}><V34Icon name="close" size={20}/></button>
          <div className="v34-s07-eyebrow">Profile · {projection.completionPercent}% complete · S-07</div>
          <h2 ref={headingRef} tabIndex={-1} id="profile-completion-dialog-title">Complete your profile</h2>
          <p id="profile-completion-dialog-description">Add your academic background and interests for more relevant internships, learning and research suggestions. You can do this now or return from Profile at any time.</p>
          <div className="v34-s07-progress" role="progressbar" aria-label="Profile completion" aria-valuenow={projection.completionPercent} aria-valuemin={0} aria-valuemax={100}><span style={{ width: `${projection.completionPercent}%` }}/></div>
          {dismissError && <div ref={dismissErrorRef} tabIndex={-1} role="alert" data-testid="profile-save-error">{dismissError}</div>}
          <div className="v34-s07-actions">
            <button type="button" className="v34-hit v34-s07-button v34-s07-button--primary" onClick={() => nav(profileSectionRoute(projection.nextIncompleteSection))} disabled={dismiss.isPending}><span className="v321-revl-icon" aria-hidden="true"><S07Icon name="spark"/></span>Complete Profile</button>
            <button type="button" className="v34-hit v34-s07-button" onClick={() => { void dismissAndContinue(); }} disabled={dismiss.isPending}><span className="v321-revl-icon" aria-hidden="true"><S07Icon name="clock"/></span>Maybe Later</button>
          </div>
          {logoutFailed && <div role="alert" className="v34-well">Sign out could not be confirmed. Your server session may still be active. Try Sign out again.</div>}
          <div className="v34-s07-session-actions"><button type="button" className="v34-hit v34-linkbtn" onClick={signOut}>Sign out</button></div>
        </div>
      </div>
    </section>
  );
}

export function V34Register(props: ScreenProps) {
  const nav = useNavigate();
  const captureContinuation = useRouteContinuation();
  const [firstName, setFirstName] = useState(''); const [middleName, setMiddleName] = useState(''); const [lastName, setLastName] = useState('');
  const [mobile, setMobile] = useState(''); const [dob, setDob] = useState('');
  const [termsAccepted, setTermsAccepted] = useState(false);
  const [privacyNoticeAcknowledged, setPrivacyNoticeAcknowledged] = useState(false);
  const [busy, setBusy] = useState(false);
  const [errors, setErrors] = useState<Record<string, string>>({});
  const errorSummaryRef = useRef<HTMLDivElement>(null);
  const errorTargets: Record<string, string> = {
    firstName: 'v34-first', middleName: 'v34-middle', lastName: 'v34-last',
    mobile: 'v34-mobile', dob: 'v34-dob', terms: 'v34-terms', privacy: 'v34-privacy',
    submit: 'S-08-title',
  };
  const errorRows = Object.entries(errors);
  useEffect(() => {
    if (errorRows.length > 0) errorSummaryRef.current?.focus();
  }, [errors]);
  async function submit() {
    const next: Record<string, string> = {}; const parts = { firstName, middleName, lastName }; const nameErrors = validateNameParts(parts);
    if (nameErrors.firstName) next.firstName = nameErrorMessage('firstName', nameErrors.firstName); if (nameErrors.middleName) next.middleName = nameErrorMessage('middleName', nameErrors.middleName); if (nameErrors.lastName) next.lastName = nameErrorMessage('lastName', nameErrors.lastName);
    if (!isValidMobile(mobile)) next.mobile = MOBILE_ERROR; if (!dob) next.dob = 'Enter your date of birth.'; else if (!isRegistrableDob(dob, new Date())) next.dob = DOB_ERROR;
    if (!termsAccepted) next.terms = 'Accept the Terms to continue.';
    if (!privacyNoticeAcknowledged) next.privacy = 'Acknowledge the Privacy Notice to continue.';
    setErrors(next); if (Object.keys(next).length) return;
    const payload = namePartsToPayload(parts);
    const current = captureContinuation();
    setBusy(true);
    try {
      await registerStudent({
        firstName: payload.firstName,
        middleName: payload.middleName,
        lastName: payload.lastName,
        mobile,
        dob,
        termsAccepted: true,
        termsVersion: TERMS_VERSION,
        privacyNoticeAcknowledged: true,
        privacyNoticeVersion: PRIVACY_NOTICE_VERSION,
      });
      if (current()) nav('/s-09');
    } catch { if (current()) setErrors({ submit: 'Registration or code delivery could not be completed. Check your details or try again later.' }); }
    finally { if (current()) setBusy(false); }
  }
  return (
    <Screen id="S-08">
      <RevLTopbar {...props}/>
      <RevLBrandPanel/>
      <Pane><main id="main-content" aria-labelledby="S-08-title" className="v34-main v321-form v321-form--register">
        <CreateAccountContext
          disabled={busy}
          onChangeStart={() => {
            setBusy(true);
            setFirstName(''); setMiddleName(''); setLastName(''); setMobile(''); setDob('');
            setTermsAccepted(false); setPrivacyNoticeAcknowledged(false); setErrors({});
          }}
          onChangeError={() => {
            setBusy(false);
            setErrors({ submit: 'Your registration context could not be safely cleared. Please retry.' });
          }}
        />
        <div><span className="v321-eyebrow">Create account</span><h1 id="S-08-title" className="v34-title">Create your student account.</h1></div>
        <div ref={errorSummaryRef} id="s08-error-summary" tabIndex={-1} role={errorRows.length > 0 ? 'alert' : undefined} hidden={errorRows.length === 0} className="v34-well">
          <h2>Review the highlighted fields</h2><ul>{errorRows.map(([field, message]) => <li key={field}><a href={`#${errorTargets[field] ?? 'S-08-title'}`}>{message}</a></li>)}</ul>
        </div>
        <div className="v34-fieldset"><div className="v34-row"><Field id="v34-first" label="First Name" value={firstName} onChange={setFirstName} autoComplete="given-name" required error={errors.firstName} revisionLIcon="idcard"/><Field id="v34-middle" label="Middle Name" value={middleName} onChange={setMiddleName} autoComplete="additional-name" optional inlineOptional error={errors.middleName}/></div><Field id="v34-last" label="Last Name" value={lastName} onChange={setLastName} autoComplete="family-name" required error={errors.lastName}/><Field id="v34-mobile" label="Mobile Number" value={mobile} onChange={setMobile} type="tel" inputMode="numeric" autoComplete="tel-national" prefix="+91" maxLength={15} required error={errors.mobile} revisionLIcon="sim"/><Field id="v34-dob" label="Date of Birth" value={dob} onChange={setDob} type="date" required error={errors.dob} help={`Required for eligibility; must be on or before ${todayLocalISO()}.`}/><p className="v321-help v321-help--dob">Used once to check whether guardian consent applies (S-16). Not shown on your profile.</p></div>
        <div className="v34-well v34-checks"><label htmlFor="v34-terms"><input id="v34-terms" type="checkbox" required aria-required="true" aria-invalid={errors.terms ? true : undefined} aria-describedby={errors.terms ? 'v34-terms-error' : undefined} checked={termsAccepted} onChange={(event) => setTermsAccepted(event.target.checked)}/>I accept the Terms.</label>{errors.terms && <span id="v34-terms-error" role="alert" className="v34-field__error">{errors.terms}</span>}<label htmlFor="v34-privacy"><input id="v34-privacy" type="checkbox" required aria-required="true" aria-invalid={errors.privacy ? true : undefined} aria-describedby={errors.privacy ? 'v34-privacy-error' : undefined} checked={privacyNoticeAcknowledged} onChange={(event) => setPrivacyNoticeAcknowledged(event.target.checked)}/>I acknowledge the Privacy Notice.</label>{errors.privacy && <span id="v34-privacy-error" role="alert" className="v34-field__error">{errors.privacy}</span>}</div>
        {errors.submit && <span role="alert" className="v34-field__error">{errors.submit}</span>}
        <button type="button" className="v321-primary" aria-label="Create Account" data-tip="Create Account" onClick={submit} disabled={busy}><NyayOneRevLIcon name="userplus"/><span>Create Account</span></button>
        <PrivacyNote/>
      </main><RevLLegalFooter plainText/></Pane>
    </Screen>
  );
}

function V34OtpChallenge({ purpose }: { purpose: 'login' | 'signup' }) {
  const nav = useNavigate();
  const captureContinuation = useRouteContinuation();
  const topbarProps = useContext(OtpScreenThemeContext);
  const [code, setCode] = useState('');
  const [status, setStatus] = useState('');
  const [busy, setBusy] = useState(false);
  const session = useStudentSession();
  const otpFlow = useOtpFlowState(undefined, { enabled: session.phase === 'anonymous' });
  const flow = otpFlow.state;
  const expires = flow?.expiresInSeconds ?? 0;
  const resend = flow?.resendInSeconds ?? 0;
  const attempts = flow?.attemptsLeft;
  const screenId = purpose === 'signup' ? 'S-09' : 'S-05';
  const backRoute = purpose === 'signup' ? '/s-08' : '/s-04';

  useEffect(() => {
    if (!otpFlow.loadError) return;
    setCode('');
    setStatus('');
    setBusy(false);
  }, [otpFlow.loadError]);

  function captureFailure(caught: unknown) {
    if (caught instanceof RegistrationApiError && caught.otpState) {
      otpFlow.adopt(caught.otpState);
    }
    setStatus(otpVerificationFailureMessage(caught));
  }

  async function submit() {
    if (!isValidOtpInput(code)) { setStatus('Enter all six digits.'); return; }
    if (flow?.status !== 'pending' || flow.purpose !== purpose) {
      setStatus('Start registration or sign in before entering a code.');
      return;
    }
    const current = captureContinuation();
    setBusy(true);
    try {
      const result = purpose === 'signup'
        ? await verifyStudentOtp(code)
        : await verifyLoginOtp(code);
      if (!current()) return;
      otpFlow.adopt(result);
      const resumeRoute = purpose === 'login'
        ? resolvedProfileReauthResumeRoute()
        : null;
      nav(resumeRoute ?? '/s-07', { replace: true });
    } catch (caught) {
      if (current()) captureFailure(caught);
    } finally {
      if (current()) setBusy(false);
    }
  }
  async function resendCode() {
    if (flow?.status !== 'pending' || !flow.resendAllowed) return;
    setBusy(true);
    try {
      otpFlow.adopt(await resendStudentOtp());
      setCode('');
      setStatus('A new code was sent.');
    } catch (caught) {
      if (caught instanceof RegistrationApiError && caught.otpState) {
        otpFlow.adopt(caught.otpState);
      }
      setStatus('A new code could not be sent yet. Follow the server countdown and retry.');
    } finally {
      setBusy(false);
    }
  }
  const studentContext = purpose === 'signup' ? (
    <CreateAccountContext
      disabled={busy}
      onChangeStart={() => { setBusy(true); setCode(''); setStatus(''); }}
      onRetired={otpFlow.adopt}
      onChangeError={() => {
        setBusy(false);
        setStatus('Your verification context could not be safely cleared. Please retry.');
      }}
    />
  ) : null;
  const verificationAside = <><RevLTopbar {...topbarProps}/><RevLBrandPanel verification/></>;
  const formClass = `v34-main v321-form v321-form--otp${purpose === 'signup' ? ' v321-form--signup-otp' : ''}`;
  if (session.phase === 'pending' || (session.phase === 'anonymous' && otpFlow.loading)) {
    return (
      <Screen id={screenId} aside={verificationAside}>
        <Pane><main id="main-content" aria-labelledby={`${screenId}-title`} className={formClass}>
          {studentContext}
          <h1 id={`${screenId}-title`} className="v34-title">Checking verification state</h1>
          <div className="v34-well" role="status">Restoring the server verification state…</div>
        </main><RevLLegalFooter plainText/></Pane>
      </Screen>
    );
  }
  if (session.phase !== 'anonymous') {
    return (
      <Navigate
        to={session.phase === 'authenticated'
          ? (purpose === 'login' ? resolvedProfileReauthResumeRoute() : null) ?? '/s-07'
          : '/s-03'}
        replace
        state={{ nyay7Focus: 'persona' }}
      />
    );
  }
  if (otpFlow.loadError || flow?.status !== 'pending' || flow.purpose !== purpose) {
    return <Navigate to="/s-03" replace state={{ nyay7Focus: 'persona' }}/>;
  }
  const digits = Array.from({ length: 6 }, (_, index) => code[index] ?? '');
  // NYAY-12 destination continuity: only a server-masked mobile or email
  // destination is ever rendered; anything else falls back to neutral copy.
  const emailDestination = isMaskedEmailDestination(flow?.destinationMasked);
  const destination = isMaskedMobileDestination(flow?.destinationMasked)
    ? `+91 ••••• ••${String(flow?.destinationMasked).slice(-3)}`
    : emailDestination
      ? String(flow?.destinationMasked)
      : (purpose === 'signup' ? 'your mobile' : 'your sign-in identity');
  const changeLabel = emailDestination && purpose !== 'signup'
    ? 'Change email address'
    : (purpose === 'signup' ? 'Change registration details' : 'Change mobile number');
  return (
    <Screen id={screenId} aside={verificationAside}>
      <Pane><main id="main-content" aria-labelledby={`${screenId}-title`} className={formClass}>
        {studentContext}
        <div><span className="v321-eyebrow">{purpose === 'signup' ? 'Create account' : 'Verify account'}</span><h1 id={`${screenId}-title`} className="v34-title">{purpose === 'signup' ? 'Verify your new account.' : 'Enter the code'}</h1>{purpose === 'login' && <p className="v34-lede">Six digits sent to <b className="v321-mono">{destination}</b>. Your code stays valid for the time shown below. <button type="button" className="v321-inline-action" aria-label={changeLabel} onClick={() => nav(backRoute)} disabled={busy}><NyayOneRevLIcon name="pen"/><span>Change</span></button></p>}</div>
        {purpose === 'signup' && <p className="v34-lede">One code to <b className="v321-mono">{destination}</b> confirms this account is yours. <button type="button" className="v321-inline-action" aria-label={changeLabel} onClick={() => nav(backRoute)} disabled={busy}><NyayOneRevLIcon name="pen"/><span>Change</span></button></p>}
        <span className="sr-only">One-time code</span>
        <label className="v34-otp">{digits.map((digit, index) => <span key={index} aria-hidden="true">{digit}</span>)}<input aria-label="Six digit code" inputMode="numeric" autoComplete="one-time-code" maxLength={6} value={code} disabled={busy} onChange={(event) => setCode(normalizeOtpDigits(event.target.value))} onPaste={(event) => { event.preventDefault(); setCode(normalizeOtpDigits(event.clipboardData.getData('text'))); }}/></label>
        <p className="v321-otp-help">Paste or platform autofill works. The field accepts the full code at once.</p>
        {status && <div className="v34-banner" role="alert">{status}</div>}
        <div className="v34-card v34-kv"><span>Expires in <b className="v321-mono">{Math.floor(expires / 60).toString().padStart(2, '0')}:{(expires % 60).toString().padStart(2, '0')}</b></span><span>Resend in <b className="v321-mono">{flow?.resendAllowed ? '00:00' : `${Math.floor(resend / 60).toString().padStart(2, '0')}:${String(resend % 60).padStart(2, '0')}`}</b></span><span>Tries left <b>{attempts ?? '—'}</b></span></div>
        <div className="v321-button-row"><button type="button" className="v321-primary" aria-label="Verify and continue" onClick={submit} disabled={busy || code.length !== 6 || flow?.status !== 'pending' || (flow.lockedForSeconds ?? 0) > 0}><NyayOneRevLIcon name="checkc"/><span>Verify and Continue</span></button><button type="button" className="v321-secondary" disabled={!flow?.resendAllowed || busy} onClick={resendCode}><span className="v321-icon--indigo"><NyayOneRevLIcon name="refresh"/></span><span>Resend Code</span></button></div>
      </main><RevLLegalFooter plainText/></Pane>
    </Screen>
  );
}

export function V34LoginOtp(props: ScreenProps) {
  return <OtpScreenThemeContext.Provider value={props}><V34OtpChallenge purpose="login"/></OtpScreenThemeContext.Provider>;
}

export function V34OtpVerify(props: ScreenProps) {
  return <OtpScreenThemeContext.Provider value={props}><V34OtpChallenge purpose="signup"/></OtpScreenThemeContext.Provider>;
}

export function V34ProfileStep1() {
  const location = useLocation();
  const params = useMemo(() => new URLSearchParams(location.search), [location.search]);
  const profile = useStudentProfileProjection();
  if (!profile.data) {
    return <Screen id="S-10" variant="wizard"><Pane><main className="v34-main">{profile.isPending ? <div role="status">Loading your profile…</div> : <div role="alert">{profileErrorMessage(profile.error)} <button type="button" onClick={() => { void profile.refetch(); }}>Retry profile</button></div>}</main></Pane></Screen>;
  }
  const decision = resolveProfileStepRoute(params.get('section'), profile.data);
  if ('redirect' in decision) return <Navigate to={decision.redirect} replace />;
  return decision.render === 'academic' ? <ProfileStep2/> : <ProfileStep1/>;
}
