import { useEffect, useMemo, useRef, useState, type KeyboardEvent, type ReactNode } from 'react';
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
  registerStudent,
  resendStudentOtp,
  startLoginOtp,
  startRecovery,
  verifyLoginOtp,
  verifyRecovery,
  completeRecovery,
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
import { consumeStudentAuthTransitionNotice } from '../lib/studentAuthTransitionNotice';
import { resolvedProfileReauthResumeRoute } from '../profile/profileReauthHandoff';

type ScreenProps = { theme?: ThemeMode; toggleTheme?: () => void };
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

function Brand() {
  return <div className="v34-brand"><img className="v34-brand__mark" src="/brand/nyayone-mark.svg" alt="" aria-hidden="true" draggable="false"/><span><b>NyayOne</b><small>STUDENT MODULE</small></span></div>;
}

function AuthAside({ title, copy }: { title: string; copy: string }) {
  return (
    <aside className="v34-aside">
      <Brand/>
      <h2>{title}</h2>
      <p>{copy}</p>
      <div className="v34-rule"/>
      <ul>
        <li><V34Icon name="check" size={19}/> Verified by one time code. Your college is never contacted.</li>
        <li><V34Icon name="verify" size={19}/> Consent is granular and revocable under the DPDP Act.</li>
        <li><V34Icon name="research" size={19}/> Research is a study aid. Every answer carries its authorities.</li>
      </ul>
      <small>Sample content only. No production record is displayed here.</small>
    </aside>
  );
}

function Screen({ id, variant = 'auth', aside, children }: { id: string; variant?: 'auth' | 'app' | 'splash' | 'wizard'; aside?: ReactNode; children: ReactNode }) {
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

function PaneHead({ id, back, children }: { id: string; back?: () => void; children?: ReactNode }) {
  return (
    <div className="v34-panehead">
      {back && <button type="button" className="v34-hit" onClick={back}><V34Icon name="back" size={17}/>Back</button>}
      <span className="v34-mono">{id}</span><span className="v34-grow"/>{children}
    </div>
  );
}

function IconAction({ label, icon, onClick, disabled, secondary = false }: { label: string; icon: IconName; onClick?: () => void; disabled?: boolean; secondary?: boolean }) {
  return (
    <button type="button" className={`v34-iconbtn${secondary ? ' v34-iconbtn--secondary' : ''}`} aria-label={label} data-tip={label} onClick={onClick} disabled={disabled}>
      <V34Icon name={icon} size={26}/>
    </button>
  );
}

function Footer({ hint, children }: { hint: ReactNode; children: ReactNode }) {
  return <footer className="v34-footer"><div className="v34-actions"><span className="v34-actions__hint">{hint}</span>{children}</div></footer>;
}

function Field({ id, label, value, onChange, type = 'text', inputMode, autoComplete, placeholder, optional, required, error, help, max, maxLength, prefix }: {
  id: string; label: string; value: string; onChange: (value: string) => void; type?: string; inputMode?: 'text' | 'numeric' | 'tel' | 'email'; autoComplete?: string;
  placeholder?: string; optional?: boolean; required?: boolean; error?: string; help?: string; max?: string; maxLength?: number; prefix?: string;
}) {
  const describedBy = error ? `${id}-error` : undefined;
  return (
    <div className={`v34-field${error ? ' v34-field--error' : ''}${optional ? ' v34-field--optional' : ''}`}>
      <span className="v34-field__top">
        <label htmlFor={id}>{label}</label>
        <span className="v34-field__meta">
          {optional && <small>OPTIONAL</small>}
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
  _retiredOnboardingSeen = false,
): string | null {
  if (phase === 'authenticated') return '/s-07';
  if (phase === 'anonymous') return '/s-02';
  return null;
}

export function V34Splash() {
  const nav = useNavigate();
  const session = useStudentSession();
  useEffect(() => {
    const destination = splashDestination(session.phase);
    if (destination) nav(destination, { replace: true });
  }, [nav, session.phase]);
  return (
    <Screen id="S-01" variant="splash">
      <div className="v34-splash__hero">
        <span className="v34-jaali v34-jaali--one"/><span className="v34-jaali v34-jaali--two"/>
        <div className="v34-splash__ring"><i/><i/><i/><img src="/brand/nyayone-mark.svg" alt="" aria-hidden="true" draggable="false"/></div>
        <div className="v34-splash__lockup"><h1 id="S-01-title">NyayOne</h1><p>For students of law in India. Sources first, always.</p></div>
        <div className="v34-splash__strip"><span>INTERNSHIPS</span><span>MOOTS</span><span>DIGESTS</span><span>RESEARCH</span></div>
      </div>
      <div className="v34-splash__foot">
        {session.phase === 'unavailable' ? (
          <><span role="alert">Session check unavailable.</span><button type="button" className="v34-hit" onClick={() => { void session.refresh(); }}>Retry</button></>
        ) : (
          <><div role="progressbar" aria-label="Checking your session" aria-valuemin={0} aria-valuemax={100} aria-valuenow={62}><i/></div><span>Checking your session</span></>
        )}
      </div>
    </Screen>
  );
}

const ONBOARDING = [
  { title: 'The years before the bar, organised.', copy: 'Internships, moots, digests and citation-bound research. One student account.', art: 'A STUDENT DESK, ORGANISED' },
  { title: 'Read the judgment, not a summary of a summary.', copy: 'Digests carry the citation, the bench and the year. Every research answer points back to authority.', art: 'A READING ROOM OF AUTHORITIES' },
  { title: 'Build evidence of the work you do.', copy: 'Keep verified records of moots, clinics and learning milestones without making private details public.', art: 'A TRUSTED STUDENT WALLET' },
] as const;

export function V34Onboarding() {
  const nav = useNavigate();
  const [index, setIndex] = useState(0);
  const item = ONBOARDING[index];
  const finish = () => { nav('/s-03'); };
  return (
    <Screen id="S-02" aside={<AuthAside title="The years before the bar, organised." copy="Internships, moots, digests and citation-bound research. One student account."/>}>
      <Pane><main className="v34-main">
        <div className="v34-onboard__top"><span className="v34-mono">{String(index + 1).padStart(2, '0')} / 03</span><span className="v34-meter"><i style={{ width: `${((index + 1) / 3) * 100}%` }}/></span><button className="v34-hit" onClick={finish}>Skip</button></div>
        <div className="v34-illustration" aria-label={item.art}>{item.art}</div>
        <h1 id="S-02-title" className="v34-title">{item.title}</h1><p className="v34-lede">{item.copy}</p><span className="v34-grow"/>
      </main><Footer hint={index === 2 ? 'Choose how you want to sign in.' : 'Continue through the short introduction.'}><IconAction label={index === 2 ? 'Get started' : 'Next slide'} icon="forward" onClick={() => index === 2 ? finish() : setIndex((value) => value + 1)}/></Footer></Pane>
    </Screen>
  );
}

export function V34AuthGate(props: ScreenProps) {
  const nav = useNavigate();
  const [language, setLanguage] = useState('English');
  const [deletionAccepted] = useState(() => (
    consumeStudentAuthTransitionNotice('account_deletion_accepted')
  ));
  return (
    <Screen id="S-03" aside={<AuthAside title="The years before the bar, organised." copy="Built for students in India, not adapted from a firm tool."/>}>
      <Pane><main className="v34-main">
        <div className="v34-mobilebrand"><Brand/><ThemeButton {...props}/></div>
        <h1 id="S-03-title" className="v34-display">Welcome. Let us get you in.</h1>
        {deletionAccepted && (
          <div className="v34-banner" role="status">
            <b>DELETION REQUEST ACCEPTED</b>
            <span>You have been signed out and this browser's student context has been cleared.</span>
          </div>
        )}
        <p className="v34-lede">Sign in if you have an account, or create one as a law student. Verification takes about a minute.</p><div className="v34-rule"/>
        <div><span className="v34-mono">LANGUAGE</span><div className="v34-chips" role="radiogroup" aria-label="Language">{['English', 'हिंदी', 'More'].map((name) => <button key={name} type="button" role="radio" aria-checked={language === name} className={language === name ? 'is-on' : ''} onClick={() => setLanguage(name)}>{name}</button>)}</div></div><span className="v34-grow"/>
      </main><Footer hint={<>Sign in, or register as a law student. Read the <a href="/s-19">privacy notice</a> first.</>}><IconAction secondary label="Register as a student" icon="add" onClick={() => nav('/s-08')}/><IconAction label="Sign in" icon="key" onClick={() => nav('/s-04')}/></Footer></Pane>
    </Screen>
  );
}

export function V34Login() {
  const nav = useNavigate();
  const [mobile, setMobile] = useState('');
  const [busy, setBusy] = useState(false);
  const [errors, setErrors] = useState<Record<string, string>>({});
  async function submit() {
    const next: Record<string, string> = {};
    if (!isValidMobile(mobile)) next.mobile = MOBILE_ERROR;
    setErrors(next);
    if (Object.keys(next).length) return;
    setBusy(true);
    try {
      await startLoginOtp(mobile);
      nav('/s-05');
    } catch {
      setErrors({ submit: 'A one time code could not be requested. Please retry.' });
    } finally {
      setBusy(false);
    }
  }
  return (
    <Screen id="S-04" aside={<AuthAside title="Welcome back." copy="Sign in with the mobile number on your account. We will send a short-lived one time code."/>}>
      <Pane><PaneHead id="S-04 · SIGN IN" back={() => nav('/s-03')}/><main className="v34-main">
        <h1 id="S-04-title" className="v34-title">Sign in</h1><div className="v34-fieldset">
          <Field id="v34-login-mobile" label="MOBILE NUMBER" value={mobile} onChange={setMobile} type="tel" inputMode="numeric" autoComplete="tel-national" prefix="+91" error={errors.mobile} maxLength={15}/>
        </div>{errors.submit && <span className="v34-field__error" role="alert">{errors.submit}</span>}<div className="v34-inlineactions"><button className="v34-hit" onClick={() => nav('/s-06')}>Recover account</button></div><span className="v34-grow"/>
      </main><Footer hint={<>New here? <button className="v34-textlink" onClick={() => nav('/s-08')}>Create a student account</button></>}><IconAction label="Send one time code" icon="send" onClick={submit} disabled={busy}/></Footer></Pane>
    </Screen>
  );
}

export function V34AccountRecovery() {
  const nav = useNavigate();
  const [mobile, setMobile] = useState('');
  const [code, setCode] = useState('');
  const [error, setError] = useState('');
  const [message, setMessage] = useState('');
  const otpFlow = useOtpFlowState();
  const recoveryPending = otpFlow.state?.status === 'pending'
    && otpFlow.state.purpose === 'recovery';
  async function send() {
    if (!isValidMobile(mobile)) { setError(MOBILE_ERROR); return; }
    setError('');
    try {
      otpFlow.adopt(await startRecovery(mobile));
      setMessage('If an account matches, a six digit recovery code has been sent.');
    } catch {
      // Known and decoy identities retain the same user-facing failure shape.
      setMessage('A recovery code could not be requested. Please retry.');
    }
  }
  async function verifyCode() {
    if (!/^\d{6}$/.test(code)) { setError('Enter the complete 6-digit recovery code.'); return; }
    try {
      otpFlow.adopt(await verifyRecovery(code));
      otpFlow.adopt(await completeRecovery());
      setError('');
      nav('/s-04', { replace: true });
    } catch (caught) {
      if (caught instanceof RegistrationApiError && caught.otpState) {
        otpFlow.adopt(caught.otpState);
      }
      setError('Recovery could not be verified. Check the code or request a new one.');
    }
  }
  return (
    <Screen id="S-06" aside={<AuthAside title="Recover your account." copy="The response stays identical whether or not the number is registered."/>}>
      <Pane><PaneHead id="S-06 · RECOVERY" back={() => nav('/s-04')}/><main className="v34-main">
        <h1 id="S-06-title" className="v34-title">Account recovery</h1><p className="v34-lede">Tell us the mobile number on the account. We will send a six digit code.</p>
        <Field id="v34-reset-mobile" label="MOBILE NUMBER" value={mobile} onChange={setMobile} type="tel" inputMode="numeric" prefix="+91" placeholder="10 digit number" maxLength={15} error={error}/>
        {recoveryPending && <Field id="v34-recovery-code" label="6-DIGIT RECOVERY CODE" value={code} onChange={(value) => setCode(value.replace(/\D/g, '').slice(0, 6))} inputMode="numeric" autoComplete="one-time-code" maxLength={6}/>}
        {message && <div className="v34-well" role="status">{message}</div>}<div className="v34-rule"/><div><span className="v34-mono v34-accent">WHY THE WORDING IS CAREFUL</span><p className="v34-copy">The same confirmation protects your identity from anyone probing mobile numbers.</p></div><span className="v34-grow"/>
      </main><Footer hint={recoveryPending ? 'Use the latest recovery code. It can only be consumed once.' : 'We will text a six digit code to that number.'}><IconAction label={recoveryPending ? 'Verify recovery code' : 'Send the code'} icon={recoveryPending ? 'verify' : 'send'} onClick={recoveryPending ? verifyCode : send}/></Footer></Pane>
    </Screen>
  );
}

const HOME_NAV: readonly { label: string; icon: IconName }[] = [
  { label: 'Home', icon: 'home' },
  { label: 'Ask', icon: 'research' },
  { label: 'Calendar', icon: 'calendar' },
  { label: 'Exam Prep', icon: 'prep' },
  { label: 'Case Digests', icon: 'digest' },
  { label: 'Moot Court', icon: 'moot' },
  { label: 'Drafting Lab', icon: 'drafting' },
  { label: 'Internships', icon: 'career' },
  { label: 'Career & Jobs', icon: 'career' },
  { label: 'Clinical Hours', icon: 'clinical' },
  { label: 'Community', icon: 'community' },
  { label: 'Profile & Settings', icon: 'profile' },
];

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
  const profile = useStudentProfileProjection();
  const dismiss = useDismissProfilePrompt();
  const backgroundRef = useRef<HTMLDivElement>(null);
  const dialogRef = useRef<HTMLDivElement>(null);
  const headingRef = useRef<HTMLHeadingElement>(null);
  const dismissInFlight = useRef(false);
  const [dismissError, setDismissError] = useState<string | null>(null);
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
    try { await logoutStudent(); } finally {
      nav('/s-03', { replace: true });
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
  return (
    <>
      <div ref={backgroundRef} data-testid="profile-prompt-background" aria-hidden={showDialog ? true : undefined}>
         <Screen id="S-07" variant="app" aside={<nav className="v34-sidenav" aria-label="Main"><Brand/>{HOME_NAV.map((item, index) => <button type="button" key={item.label} className={index === 0 ? 'is-on' : ''} onClick={() => index === 11 ? nav('/s-17') : undefined}><V34Icon name={item.icon} size={19}/>{item.label}</button>)}<span className="v34-grow"/><small>Bar enrolment is optional and private.</small></nav>}>
          <Pane><header className="v34-appbar"><Brand/><button type="button" className="v34-command">Ask a question or search…</button><button type="button" className="v34-hit v34-linkbtn" onClick={signOut}>Sign out</button><ThemeButton {...props}/></header><main className="v34-main"><h1 id="S-07-title" className="v34-display">Welcome, {projection.profile.personal.firstName}.</h1><div className="v34-card"><b className="v34-stat">{projection.completionPercent}%</b><span>profile complete</span></div></main></Pane>
        </Screen>
      </div>
      <div className="v34-dialog-backdrop">
        <div ref={dialogRef} role="dialog" aria-modal="true" aria-labelledby="profile-completion-dialog-title" aria-describedby="profile-completion-dialog-description" data-testid="profile-completion-dialog" className="v34-card v34-dialog" onKeyDown={trapDialogKeys}>
          <button type="button" className="v34-hit v34-dialog__close" aria-label="Close profile prompt" onClick={() => { void dismissAndContinue(); }} disabled={dismiss.isPending}><V34Icon name="close" size={20}/></button>
          <h2 ref={headingRef} tabIndex={-1} id="profile-completion-dialog-title">Complete your profile</h2>
          <p id="profile-completion-dialog-description">Your profile is {projection.completionPercent}% complete. Finish the next section to tailor your student workspace.</p>
          {dismissError && <div role="alert" data-testid="profile-save-error">{dismissError}</div>}
          <div className="v34-actions">
            <button type="button" className="v34-hit v34-linkbtn" onClick={signOut}>Sign out</button>
            <button type="button" className="v34-hit" onClick={() => { void dismissAndContinue(); }} disabled={dismiss.isPending}>Maybe Later</button>
            <button type="button" className="v34-hit" onClick={() => nav(profileSectionRoute(projection.nextIncompleteSection))}>Complete Profile</button>
          </div>
        </div>
      </div>
    </>
  );
}

export function V34Register(props: ScreenProps) {
  const nav = useNavigate();
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
      nav('/s-09');
    } catch { setErrors({ submit: 'Registration or code delivery could not be completed. Check your details or try again later.' }); }
    finally { setBusy(false); }
  }
  return (
    <Screen id="S-08" aside={<AuthAside title="The years before the bar, organised." copy="Create your secure account, then complete your profile after verification."/>}>
      <Pane><PaneHead id="S-08 · STEP 1 OF 2" back={() => nav('/s-03')}><ThemeButton {...props}/></PaneHead><main className="v34-main">
        <div><h1 id="S-08-title" className="v34-title">Create your student account</h1><p className="v34-copy">Enter only your core legal identity, mobile number and date of birth. Academic details follow after verification.</p></div>
        <div ref={errorSummaryRef} id="s08-error-summary" tabIndex={-1} role={errorRows.length > 0 ? 'alert' : undefined} hidden={errorRows.length === 0} className="v34-well">
          <h2>Review the highlighted fields</h2><ul>{errorRows.map(([field, message]) => <li key={field}><a href={`#${errorTargets[field] ?? 'S-08-title'}`}>{message}</a></li>)}</ul>
        </div>
        <div className="v34-fieldset"><div className="v34-row v34-row--three"><Field id="v34-first" label="FIRST NAME" value={firstName} onChange={setFirstName} autoComplete="given-name" required error={errors.firstName}/><Field id="v34-middle" label="MIDDLE NAME" value={middleName} onChange={setMiddleName} autoComplete="additional-name" optional error={errors.middleName}/><Field id="v34-last" label="LAST NAME" value={lastName} onChange={setLastName} autoComplete="family-name" required error={errors.lastName}/></div>
          <div className="v34-row"><Field id="v34-mobile" label="MOBILE NUMBER" value={mobile} onChange={setMobile} type="tel" inputMode="numeric" autoComplete="tel-national" prefix="+91" maxLength={15} required error={errors.mobile} help="Exactly 10 digits. The one time code is sent here."/><Field id="v34-dob" label="DATE OF BIRTH" value={dob} onChange={setDob} type="date" required error={errors.dob} help={`Required for eligibility; must be on or before ${todayLocalISO()}.`}/></div>
        </div><div className="v34-well v34-checks"><label htmlFor="v34-terms"><input id="v34-terms" type="checkbox" required aria-required="true" aria-invalid={errors.terms ? true : undefined} aria-describedby={errors.terms ? 'v34-terms-error' : undefined} checked={termsAccepted} onChange={(event) => setTermsAccepted(event.target.checked)}/>I accept the Terms.</label>{errors.terms && <span id="v34-terms-error" role="alert" className="v34-field__error">{errors.terms}</span>}<label htmlFor="v34-privacy"><input id="v34-privacy" type="checkbox" required aria-required="true" aria-invalid={errors.privacy ? true : undefined} aria-describedby={errors.privacy ? 'v34-privacy-error' : undefined} checked={privacyNoticeAcknowledged} onChange={(event) => setPrivacyNoticeAcknowledged(event.target.checked)}/>I acknowledge the Privacy Notice.</label>{errors.privacy && <span id="v34-privacy-error" role="alert" className="v34-field__error">{errors.privacy}</span>}</div>{errors.submit && <span role="alert" className="v34-field__error">{errors.submit}</span>}<span className="v34-grow"/>
      </main><Footer hint="The code expires after it is sent. Registration uses one-time-code verification only."><IconAction label="Send one time code" icon="send" onClick={submit} disabled={busy}/></Footer></Pane>
    </Screen>
  );
}

function V34OtpChallenge({ purpose }: { purpose: 'login' | 'signup' }) {
  const nav = useNavigate();
  const [code, setCode] = useState('');
  const [status, setStatus] = useState('');
  const [busy, setBusy] = useState(false);
  const otpFlow = useOtpFlowState();
  const flow = otpFlow.state;
  const expires = flow?.expiresInSeconds ?? 0;
  const resend = flow?.resendInSeconds ?? 0;
  const attempts = flow?.attemptsLeft;

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
    setBusy(true);
    try {
      const result = purpose === 'signup'
        ? await verifyStudentOtp(code)
        : await verifyLoginOtp(code);
      otpFlow.adopt(result);
      const resumeRoute = purpose === 'login'
        ? resolvedProfileReauthResumeRoute()
        : null;
      nav(resumeRoute ?? '/s-07', { replace: true });
    } catch (caught) {
      captureFailure(caught);
    } finally {
      setBusy(false);
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
  const digits = Array.from({ length: 6 }, (_, index) => code[index] ?? '');
  const screenId = purpose === 'signup' ? 'S-09' : 'S-05';
  const backRoute = purpose === 'signup' ? '/s-08' : '/s-04';
  return (
    <Screen id={screenId} aside={<AuthAside title="One code, then you are in." copy="Codes are short-lived. Repeated wrong entries trigger a temporary lock."/>}>
      <Pane><PaneHead id={`${screenId} · VERIFY`} back={() => nav(backRoute)}/><main className="v34-main">
        <div><h1 id={`${screenId}-title`} className="v34-title">Enter the code</h1><p className="v34-lede">Six digits, sent to {flow?.destinationMasked ?? 'your mobile'}.</p></div>
        <label className="v34-otp">{digits.map((digit, index) => <span key={index} aria-hidden="true">{digit}</span>)}<input aria-label="Six digit code" inputMode="numeric" autoComplete="one-time-code" maxLength={6} value={code} onChange={(event) => setCode(normalizeOtpDigits(event.target.value))} onPaste={(event) => { event.preventDefault(); setCode(normalizeOtpDigits(event.clipboardData.getData('text'))); }}/></label>
        {otpFlow.loading && <div className="v34-well" role="status">Restoring the server verification state…</div>}
        {otpFlow.loadError && <div className="v34-banner" role="alert">Verification state is unavailable. Retry the state check before continuing.</div>}
        {status && <div className="v34-banner" role="alert">{status}</div>}<div className="v34-card v34-kv"><span>Code expires in <b>{Math.floor(expires / 60).toString().padStart(2, '0')}:{(expires % 60).toString().padStart(2, '0')}</b></span><span>Resend available in <button className="v34-textlink" disabled={!flow?.resendAllowed || busy} onClick={resendCode}>{flow?.resendAllowed ? 'Resend now' : `${Math.floor(resend / 60).toString().padStart(2, '0')}:${String(resend % 60).padStart(2, '0')}`}</button></span><span>Tries left <b>{attempts ?? '—'}</b></span></div><span className="v34-grow"/>
      </main><Footer hint="Enter all six digits to verify."><IconAction label="Verify and continue" icon="verify" onClick={submit} disabled={busy || code.length !== 6 || flow?.status !== 'pending' || (flow.lockedForSeconds ?? 0) > 0}/></Footer></Pane>
    </Screen>
  );
}

export function V34LoginOtp() {
  return <V34OtpChallenge purpose="login"/>;
}

export function V34OtpVerify() {
  return <V34OtpChallenge purpose="signup"/>;
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
