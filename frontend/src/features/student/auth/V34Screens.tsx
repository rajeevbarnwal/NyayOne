import { useEffect, useMemo, useRef, useState, type ReactNode } from 'react';
import { useLocation, useNavigate } from 'react-router-dom';
import type { ThemeMode } from '../../../hooks/useTheme';
import { useAuth } from '../../../app/authContext';
import {
  DOB_ERROR,
  MOBILE_ERROR,
  composeDisplayName,
  isRegistrableDob,
  isValidMobile,
  nameErrorMessage,
  namePartsToPayload,
  todayLocalISO,
  validateNameParts,
} from '../lib/registration';
import { isMinor, CONSENT_VERSION } from '../lib/consent';
import {
  RegistrationApiError,
  loadRegistrationSession,
  registerStudent,
  resendStudentOtp,
  saveRegistrationSession,
  startLoginOtp,
  startRecovery,
  verifyLoginOtp,
  verifyRecovery,
  completeRecovery,
  verifyStudentOtp,
  logoutStudent,
  notifyStudentAuthChanged,
  checkMobile,
} from '../lib/registrationApi';
import { setMinor } from '../lib/authFlow';
import { isValidOtpFormat, maskDestination } from '../lib/otp';
import { getProfileDraft, updateProfileDraft } from '../lib/profileStore';
import { COLLEGE_OPTIONS } from '../lib/catalog';
import { profileCompletionPct } from '../lib/dashboard';

function formatDDMMYYYY(dateStr: string): string {
  if (!dateStr) return '';
  const parts = dateStr.split('-');
  if (parts.length === 3 && parts[0].length === 4) {
    return `${parts[2]}-${parts[1]}-${parts[0]}`;
  }
  return dateStr;
}

type ScreenProps = { theme?: ThemeMode; toggleTheme?: () => void };
type IconName = 'add' | 'back' | 'check' | 'forward' | 'key' | 'moon' | 'retry' | 'save' | 'send' | 'sun' | 'verify';

const EMAIL_RE = /^[^\s@]+@[^\s@]+\.[^\s@]{2,}$/;
const ONBOARDING_SEEN_KEY = 'legalsaathi.student.onboarding.v34';

function V34Icon({ name, size = 24 }: { name: IconName; size?: number }) {
  const common = { fill: 'none', stroke: 'currentColor', strokeWidth: 1.9, strokeLinecap: 'round' as const, strokeLinejoin: 'round' as const };
  return (
    <svg className={`v34-icon v34-icon--${name}`} width={size} height={size} viewBox="0 0 24 24" aria-hidden="true">
      {name === 'key' && <><circle cx="8" cy="9" r="4" {...common}/><path d="m11 12 8 8m-4-4 2-2" {...common}/></>}
      {name === 'add' && <><circle cx="9" cy="8" r="4" {...common}/><path d="M2.5 21c.5-4.3 3-6.6 6.5-6.6 1.6 0 3 .5 4.1 1.3" {...common}/><circle cx="18" cy="17.5" r="4" className="v34-icon__fill"/><path d="M18 15.5v4m-2-2h4" stroke="var(--v34-on-icon)" strokeWidth="1.8" strokeLinecap="round"/></>}
      {name === 'send' && <><path d="M21 3 3 10l7 2.5L21 3Z" className="v34-icon__fill"/><path d="m21 3-5.5 18-5.5-8.5L21 3Z" className="v34-icon__fill2"/></>}
      {name === 'forward' && <><rect x="3" y="3" width="12" height="18" rx="2" className="v34-icon__fill"/><path d="M11 12h10m-4-4 4 4-4 4" {...common}/></>}
      {name === 'check' && <><circle cx="12" cy="12" r="10" className="v34-icon__fill2"/><path d="m7 12.5 3 3 7-7" stroke="white" strokeWidth="2.2" fill="none" strokeLinecap="round" strokeLinejoin="round"/></>}
      {name === 'verify' && <><circle cx="12" cy="12" r="10" className="v34-icon__fill"/><path d="m7 12.5 3 3 7-7" stroke="var(--v34-on-icon)" strokeWidth="2.2" fill="none" strokeLinecap="round" strokeLinejoin="round"/></>}
      {name === 'retry' && <><path d="M20 12a8 8 0 1 1-2.6-5.9" {...common}/><path d="M18 3v4h-4" {...common}/></>}
      {name === 'back' && <path d="m15 5-7 7 7 7" {...common}/>} 
      {name === 'save' && <><path d="M6 3h12v18l-6-4.5L6 21V3Z" className="v34-icon__fill"/><path d="m9 9 2 2 4-4" stroke="var(--v34-on-icon)" strokeWidth="2" fill="none" strokeLinecap="round"/></>}
      {name === 'sun' && <><circle cx="12" cy="12" r="4" className="v34-icon__fill"/><path d="M12 2v2m0 16v2M2 12h2m16 0h2M5 5l1.5 1.5m11 11L19 19M5 19l1.5-1.5m11-11L19 5" {...common}/></>}
      {name === 'moon' && <path d="M20 15A8.5 8.5 0 0 1 9 4a9 9 0 1 0 11 11Z" className="v34-icon__fill"/>}
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
  return <div className="v34-brand"><span className="v34-brand__mark" aria-hidden="true">§</span><span><b>LegalSaathi</b><small>STUDENT MODULE</small></span></div>;
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
        <li><span aria-hidden="true">▣</span> Consent is granular and revocable under the DPDP Act.</li>
        <li><span aria-hidden="true">¶</span> Research is a study aid. Every answer carries its authorities.</li>
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

function Field({ id, label, value, onChange, type = 'text', inputMode, autoComplete, placeholder, optional, error, help, max, maxLength, prefix, disabled, readOnly }: {
  id: string; label: string; value: string; onChange: (value: string) => void; type?: string; inputMode?: 'text' | 'numeric' | 'tel' | 'email'; autoComplete?: string;
  placeholder?: string; optional?: boolean; error?: string; help?: string; max?: string; maxLength?: number; prefix?: string; disabled?: boolean; readOnly?: boolean;
}) {
  const describedBy = error ? `${id}-error` : help ? `${id}-help` : undefined;
  return (
    <label className={`v34-field${error ? ' v34-field--error' : ''}${optional ? ' v34-field--optional' : ''}`} htmlFor={id}>
      <span className="v34-field__top"><span>{label}</span>{optional && <small>OPTIONAL</small>}</span>
      <span className="v34-field__control">{prefix && <span>{prefix}</span>}<input id={id} value={value} type={type} inputMode={inputMode} autoComplete={autoComplete} placeholder={placeholder} max={max} maxLength={maxLength} disabled={disabled} readOnly={readOnly} aria-invalid={error ? true : undefined} aria-describedby={describedBy} onChange={(event) => onChange(event.target.value)}/></span>
      {error ? <span id={`${id}-error`} className="v34-field__error" role="alert">{error}</span> : help && <span id={`${id}-help`} className="v34-field__help">{help}</span>}
    </label>
  );
}

function Select({ id, label, value, onChange, options, error }: { id: string; label: string; value: string; onChange: (value: string) => void; options: ReadonlyArray<{ value: string; label: string }>; error?: string }) {
  return (
    <label className={`v34-field${error ? ' v34-field--error' : ''}`} htmlFor={id}>
      <span className="v34-field__top"><span>{label}</span></span>
      <span className="v34-field__control"><select id={id} value={value} aria-invalid={error ? true : undefined} onChange={(event) => onChange(event.target.value)}><option value="">Select…</option>{options.map((option) => <option key={option.value} value={option.value}>{option.label}</option>)}</select></span>
      {error && <span className="v34-field__error" role="alert">{error}</span>}
    </label>
  );
}

export function V34Splash() {
  const nav = useNavigate();
  const auth = useAuth();
  useEffect(() => {
    const timer = window.setTimeout(() => {
      const seen = window.localStorage.getItem(ONBOARDING_SEEN_KEY) === 'seen';
      nav(auth.isAuthenticated ? '/s-07' : seen ? '/s-03' : '/s-02', { replace: true });
    }, 900);
    return () => window.clearTimeout(timer);
  }, [auth.isAuthenticated, nav]);
  return (
    <Screen id="S-01" variant="splash">
      <div className="v34-splash__hero">
        <span className="v34-jaali v34-jaali--one"/><span className="v34-jaali v34-jaali--two"/>
        <div className="v34-splash__ring"><i/><i/><i/><span>§</span></div>
        <div className="v34-splash__lockup"><h1 id="S-01-title">LegalSaathi</h1><p>For students of law in India. Sources first, always.</p></div>
        <div className="v34-splash__strip"><span>INTERNSHIPS</span><span>MOOTS</span><span>DIGESTS</span><span>RESEARCH</span></div>
      </div>
      <div className="v34-splash__foot"><div role="progressbar" aria-label="Checking your session" aria-valuemin={0} aria-valuemax={100} aria-valuenow={62}><i/></div><span>Checking your session</span></div>
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
  const finish = () => { window.localStorage.setItem(ONBOARDING_SEEN_KEY, 'seen'); nav('/s-03'); };
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
  const [activeTab, setActiveTab] = useState<'signin' | 'register'>('signin');

  // Sign In state
  const [loginMobile, setLoginMobile] = useState('');
  const [loginPassword, setLoginPassword] = useState('');
  const [loginMode, setLoginMode] = useState<'password' | 'otp'>('password');
  const [loginOtpSent, setLoginOtpSent] = useState(false);
  const [loginOtpId, setLoginOtpId] = useState('');
  const [loginOtpCode, setLoginOtpCode] = useState('');
  const [loginBusy, setLoginBusy] = useState(false);
  const [loginResendCooldown, setLoginResendCooldown] = useState<number>(0);
  const [loginErrors, setLoginErrors] = useState<Record<string, string>>({});

  useEffect(() => {
    if (loginResendCooldown <= 0) return;
    const timer = setInterval(() => {
      setLoginResendCooldown((prev) => Math.max(0, prev - 1));
    }, 1000);
    return () => clearInterval(timer);
  }, [loginResendCooldown]);

  async function handleResendLoginOtp() {
    if (loginResendCooldown > 0 || loginBusy) return;
    setLoginBusy(true);
    try {
      const loginId = await startLoginOtp(loginMobile);
      setLoginOtpId(loginId);
      setLoginResendCooldown(30);
      setLoginErrors({ submit: '✓ A new code was sent to your mobile.' });
      setTimeout(() => setLoginErrors({}), 4000);
    } catch {
      setLoginErrors({ submit: 'Could not resend OTP code. Please retry.' });
    } finally {
      setLoginBusy(false);
    }
  }

  // Register state
  const [firstName, setFirstName] = useState('');
  const [middleName, setMiddleName] = useState('');
  const [lastName, setLastName] = useState('');
  const [regMobile, setRegMobile] = useState('');
  const [dob, setDob] = useState('');
  const [consentAccepted, setConsentAccepted] = useState(true);
  const [regBusy, setRegBusy] = useState(false);
  const [regErrors, setRegErrors] = useState<Record<string, string>>({});
  const [regOtpSent, setRegOtpSent] = useState(false);
  const [registrationId, setRegistrationId] = useState('');
  const [regOtpCode, setRegOtpCode] = useState('');

  async function handleLoginSubmit() {
    const next: Record<string, string> = {};
    if (!isValidMobile(loginMobile)) next.mobile = MOBILE_ERROR;
    if (loginMode === 'password' && (loginPassword.length < 8 || loginPassword.length > 128)) {
      next.password = 'Password must be between 8 and 128 characters.';
    }
    if (loginMode === 'otp' && loginOtpSent && !/^\d{6}$/.test(loginOtpCode)) {
      next.otp = 'Enter the complete 6-digit one time code.';
    }
    setLoginErrors(next);
    if (Object.keys(next).length) return;

    if (loginMode === 'password') {
      try {
        const info = await checkMobile(loginMobile);
        if (info.firstName) {
          updateProfileDraft({ firstName: info.firstName, middleName: info.middleName, lastName: info.lastName });
        }
      } catch {
        /* non-fatal fallback */
      }
      notifyStudentAuthChanged();
      const currentDraft = getProfileDraft();
      const pct = profileCompletionPct(currentDraft);
      if (pct < 100) {
        const nextStep = !currentDraft.college ? 'academic' : 'interests';
        nav(`/s-10?step=${nextStep}`, { replace: true });
      } else {
        nav('/s-14', { replace: true, state: { mobile: loginMobile } });
      }
      return;
    }

    setLoginBusy(true);
    try {
      if (!loginOtpSent) {
        const loginId = await startLoginOtp(loginMobile);
        setLoginOtpId(loginId);
        setLoginOtpSent(true);
        setLoginResendCooldown(30);
        setLoginErrors({});
      } else {
        await verifyLoginOtp(loginOtpId, loginOtpCode);
        try {
          const info = await checkMobile(loginMobile);
          if (info.registered || info.firstName) {
            updateProfileDraft({
              firstName: info.firstName,
              middleName: info.middleName,
              lastName: info.lastName,
              dateOfBirth: info.dateOfBirth,
              city: info.city,
              college: info.college,
              yearOfStudy: info.yearOfStudy,
              enrolmentNumber: info.enrolmentNumber,
            });
          }
        } catch {
          /* non-fatal */
        }
        notifyStudentAuthChanged();
        const currentDraft = getProfileDraft();
        const pct = profileCompletionPct(currentDraft);
        if (pct < 100) {
          const nextStep = !currentDraft.college ? 'academic' : 'interests';
          nav(`/s-10?step=${nextStep}`, { replace: true });
        } else {
          nav('/s-14', { replace: true });
        }
      }
    } catch {
      setLoginErrors({
        submit: !loginOtpSent
          ? 'A one time code could not be requested. Please retry.'
          : 'Invalid or expired one time code. Please re-enter or request a new code.',
      });
    } finally {
      setLoginBusy(false);
    }
  }

  async function handleRegisterSubmit() {
    if (regOtpSent) {
      if (!/^\d{6}$/.test(regOtpCode)) {
        setRegErrors({ otp: 'Enter the complete 6-digit registration code.' });
        return;
      }
      setRegErrors({});
      setRegBusy(true);
      try {
        await verifyStudentOtp(registrationId, regOtpCode);
        updateProfileDraft({ firstName, middleName, lastName, dateOfBirth: dob });
        notifyStudentAuthChanged();
        nav('/s-10');
      } catch (error) {
        setRegErrors({
          submit:
            error instanceof RegistrationApiError && error.code === 'otp_max_attempts'
              ? 'Maximum attempts reached. Please register again.'
              : 'Invalid or expired code. Please re-enter the 6-digit code.',
        });
      } finally {
        setRegBusy(false);
      }
      return;
    }

    const p = { firstName, middleName, lastName };
    const nameErr = validateNameParts(p);
    const next: Record<string, string> = {};
    if (nameErr.firstName) next.firstName = nameErrorMessage('firstName', nameErr.firstName);
    if (nameErr.middleName) next.middleName = nameErrorMessage('middleName', nameErr.middleName);
    if (nameErr.lastName) next.lastName = nameErrorMessage('lastName', nameErr.lastName);
    if (!isValidMobile(regMobile)) next.mobile = MOBILE_ERROR;
    if (!isRegistrableDob(dob)) next.dob = DOB_ERROR;
    if (!consentAccepted) next.consent = 'You must accept the terms and privacy notice to create an account.';

    setRegErrors(next);
    if (Object.keys(next).length) return;

    setRegBusy(true);
    try {
      const payload = namePartsToPayload(p);
      const minor = isMinor(dob, new Date().toISOString());
      const created = await registerStudent({
        firstName: payload.firstName,
        middleName: payload.middleName,
        lastName: payload.lastName,
        mobile: regMobile,
        dob,
        policyVersion: CONSENT_VERSION,
      });

      setRegistrationId(created.registration_id);
      saveRegistrationSession({
        registrationId: created.registration_id,
        destinationMasked: maskDestination({ channel: 'sms', ref: regMobile }),
        issuedAt: Date.now(),
        isMinor: minor,
        guardianConsentPending: minor,
        flowOrigin: 'register',
      });

      setMinor(minor, minor);
      setRegOtpSent(true);
      setRegErrors({});
    } catch (error) {
      const message =
        error instanceof RegistrationApiError
          ? error.code === 'mobile_already_registered'
            ? 'Mobile number is already registered. Switch to Sign In.'
            : error.message
          : 'Could not create account right now. Please retry.';
      setRegErrors({ submit: message });
    } finally {
      setRegBusy(false);
    }
  }

  return (
    <Screen id="S-03" aside={<AuthAside title="The years before the bar, organised." copy="Built for students in India, not adapted from a firm tool."/>}>
      <Pane>
        <main className="v34-main">
          <div className="v34-mobilebrand"><Brand/><ThemeButton {...props}/></div>
          <h1 id="S-03-title" className="v34-display">Welcome. Let us get you in.</h1>
          <p className="v34-lede">Sign in if you have an account, or create one as a law student. Verification takes about a minute.</p>

          <div className="v34-auth-tabs" role="tablist" aria-label="Authentication Mode">
            <button
              type="button"
              role="tab"
              aria-selected={activeTab === 'signin'}
              className={activeTab === 'signin' ? 'is-active' : ''}
              onClick={() => setActiveTab('signin')}
            >
              Sign In
            </button>
            <button
              type="button"
              role="tab"
              aria-selected={activeTab === 'register'}
              className={activeTab === 'register' ? 'is-active' : ''}
              onClick={() => setActiveTab('register')}
            >
              Register
            </button>
          </div>

          {activeTab === 'signin' ? (
            <div className="v34-fieldset" key="signin-fields">
              <Field
                id="s03-login-mobile"
                label="MOBILE NUMBER *"
                value={loginMobile}
                onChange={setLoginMobile}
                type="tel"
                inputMode="numeric"
                autoComplete="tel-national"
                prefix="+91"
                error={loginErrors.mobile}
                maxLength={15}
                disabled={loginMode === 'otp' && loginOtpSent}
              />
              {loginMode === 'password' && (
                <Field
                  id="s03-login-password"
                  label="PASSWORD *"
                  value={loginPassword}
                  onChange={setLoginPassword}
                  type="password"
                  autoComplete="current-password"
                  error={loginErrors.password}
                  maxLength={128}
                />
              )}
              {loginMode === 'otp' && !loginOtpSent && (
                <div className="v34-well" style={{ marginBottom: '12px' }}>
                  Enter your mobile number and click <strong>Send One-Time OTP Code</strong> to receive your 6-digit verification code via SMS.
                </div>
              )}
              {loginMode === 'otp' && loginOtpSent && (
                <>
                  <div className="v34-well" style={{ marginBottom: '12px' }}>
                    Six-digit code sent via SMS to {loginMobile ? maskDestination({ channel: 'sms', ref: loginMobile }) : 'your mobile'}. Enter your code below to sign in.
                  </div>
                  <Field
                    id="s03-login-otp"
                    label="6-DIGIT ONE-TIME CODE *"
                    value={loginOtpCode}
                    onChange={(val) => setLoginOtpCode(val.replace(/\D/g, '').slice(0, 6))}
                    type="text"
                    inputMode="numeric"
                    autoComplete="one-time-code"
                    error={loginErrors.otp}
                    maxLength={6}
                    placeholder="Enter 6-digit OTP code"
                  />
                  <div className="v34-card v34-kv" style={{ marginTop: '12px', padding: '12px' }}>
                    <span>Resend available in: <b>{loginResendCooldown > 0 ? `00:${String(loginResendCooldown).padStart(2, '0')}` : 'Ready'}</b></span>
                    <span>
                      <button
                        type="button"
                        className="v34-textlink"
                        disabled={loginResendCooldown > 0 || loginBusy}
                        onClick={handleResendLoginOtp}
                      >
                        {loginResendCooldown > 0 ? 'Wait to resend' : 'Resend OTP now'}
                      </button>
                    </span>
                  </div>
                </>
              )}
              {loginErrors.submit && <span className="v34-field__error" role="alert">{loginErrors.submit}</span>}
              <div className="v34-inlineactions">
                <button
                  type="button"
                  className="v34-hit v34-linkbtn"
                  onClick={() => {
                    setLoginErrors({});
                    setLoginOtpSent(false);
                    setLoginOtpCode('');
                    setLoginMode((v) => (v === 'password' ? 'otp' : 'password'));
                  }}
                >
                  {loginMode === 'password' ? 'Use a one time code' : 'Use password'}
                </button>
                {loginMode === 'otp' && loginOtpSent ? (
                  <button
                    type="button"
                    className="v34-hit v34-linkbtn"
                    onClick={() => {
                      setLoginOtpSent(false);
                      setLoginOtpCode('');
                      setLoginErrors({});
                    }}
                  >
                    Change mobile number
                  </button>
                ) : (
                  <button type="button" className="v34-hit" onClick={() => nav('/s-06')}>
                    Forgot password
                  </button>
                )}
              </div>
              <button
                type="button"
                className="v34-submit-btn"
                onClick={handleLoginSubmit}
                disabled={loginBusy}
              >
                {loginMode === 'password'
                  ? 'Sign In'
                  : loginOtpSent
                  ? 'Verify OTP & Sign In'
                  : 'Send One-Time OTP Code'}
              </button>
            </div>
          ) : (
            <div className="v34-fieldset" key="register-fields">
              <Field
                id="s03-reg-firstname"
                label="FIRST NAME *"
                value={firstName}
                onChange={setFirstName}
                autoComplete="given-name"
                error={regErrors.firstName}
                maxLength={60}
              />
              <Field
                id="s03-reg-middlename"
                label="MIDDLE NAME"
                optional
                value={middleName}
                onChange={setMiddleName}
                autoComplete="additional-name"
                error={regErrors.middleName}
                maxLength={60}
              />
              <Field
                id="s03-reg-lastname"
                label="LAST NAME *"
                value={lastName}
                onChange={setLastName}
                autoComplete="family-name"
                error={regErrors.lastName}
                maxLength={60}
              />
              <Field
                id="s03-reg-mobile"
                label="MOBILE NUMBER *"
                value={regMobile}
                onChange={setRegMobile}
                type="tel"
                inputMode="numeric"
                autoComplete="tel-national"
                prefix="+91"
                error={regErrors.mobile}
                maxLength={15}
              />
              <Field
                id="s03-reg-dob"
                label="DATE OF BIRTH *"
                value={dob}
                onChange={setDob}
                type="date"
                max={todayLocalISO()}
                error={regErrors.dob}
                help="Real date of birth in local timezone (YYYY-MM-DD)"
              />
              <label htmlFor="s03-reg-consent" style={{ display: 'flex', gap: '8px', alignItems: 'center', margin: '8px 0', fontSize: '13px' }}>
                <input
                  id="s03-reg-consent"
                  type="checkbox"
                  checked={consentAccepted}
                  onChange={(e) => setConsentAccepted(e.target.checked)}
                />
                <span>I agree to the Terms of Service * and Privacy Notice *</span>
              </label>
              {regOtpSent && (
                <>
                  <div className="v34-well" style={{ marginBottom: '12px' }}>
                    Registration code sent via SMS to {maskDestination({ channel: 'sms', ref: regMobile })}. Enter your 6-digit code below to verify your account.
                  </div>
                  <Field
                    id="s03-reg-otp"
                    label="6-DIGIT VERIFICATION CODE *"
                    value={regOtpCode}
                    onChange={(val) => setRegOtpCode(val.replace(/\D/g, '').slice(0, 6))}
                    type="text"
                    inputMode="numeric"
                    autoComplete="one-time-code"
                    error={regErrors.otp}
                    maxLength={6}
                    placeholder="Enter 6-digit OTP code"
                  />
                </>
              )}
              {regErrors.consent && <span className="v34-field__error" role="alert">{regErrors.consent}</span>}
              {regErrors.submit && <span className="v34-field__error" role="alert">{regErrors.submit}</span>}
              <button
                type="button"
                className="v34-submit-btn"
                onClick={handleRegisterSubmit}
                disabled={regBusy}
              >
                {regOtpSent ? 'Verify OTP & Complete Registration' : 'Create account and send OTP'}
              </button>
            </div>
          )}

          <div className="v34-rule" />
          <div>
            <span className="v34-mono">LANGUAGE</span>
            <div className="v34-chips" role="radiogroup" aria-label="Language">
              {['English', 'हिंदी', 'More'].map((name) => (
                <button
                  key={name}
                  type="button"
                  role="radio"
                  aria-checked={language === name}
                  className={language === name ? 'is-on' : ''}
                  onClick={() => setLanguage(name)}
                >
                  {name}
                </button>
              ))}
            </div>
          </div>
          <span className="v34-grow" />
        </main>
        <Footer hint={<>Sign in or register as a law student. Read the <a href="/s-19">privacy notice</a> first.</>}>
          <span />
        </Footer>
      </Pane>
    </Screen>
  );
}

export function V34Login() {
  const nav = useNavigate();
  const location = useLocation();
  const locationState = (location.state as { mobile?: string; password?: string } | null);
  const [mobile, setMobile] = useState(locationState?.mobile || '');
  const [password, setPassword] = useState(locationState?.password || '');
  const [mode, setMode] = useState<'password' | 'otp'>('password');
  const [otpSent, setOtpSent] = useState(false);
  const [otpId, setOtpId] = useState('');
  const [otpCode, setOtpCode] = useState('');
  const [busy, setBusy] = useState(false);
  const [errors, setErrors] = useState<Record<string, string>>({});

  async function submit() {
    const next: Record<string, string> = {};
    if (!isValidMobile(mobile)) next.mobile = MOBILE_ERROR;
    if (mode === 'password' && (password.length < 8 || password.length > 128)) {
      next.password = 'Password must be between 8 and 128 characters.';
    }
    if (mode === 'otp' && otpSent && !/^\d{6}$/.test(otpCode)) {
      next.otp = 'Enter the complete 6-digit one time code.';
    }
    setErrors(next);
    if (Object.keys(next).length) return;

    if (mode === 'password') {
      try {
        const info = await checkMobile(mobile);
        if (info.firstName) {
          updateProfileDraft({ firstName: info.firstName, middleName: info.middleName, lastName: info.lastName });
        }
      } catch {
        /* non-fatal fallback */
      }
      notifyStudentAuthChanged();
      nav('/s-14');
      return;
    }

    setBusy(true);
    try {
      if (!otpSent) {
        const loginId = await startLoginOtp(mobile);
        setOtpId(loginId);
        setOtpSent(true);
        setErrors({});
      } else {
        await verifyLoginOtp(otpId, otpCode);
        notifyStudentAuthChanged();
        nav('/s-14');
      }
    } catch {
      setErrors({
        submit: !otpSent
          ? 'A one time code could not be requested. Please retry.'
          : 'Invalid or expired one time code. Please re-enter or request a new code.',
      });
    } finally {
      setBusy(false);
    }
  }

  return (
    <Screen id="S-04" aside={<AuthAside title="Welcome back." copy="Sign in with the mobile number on your account. A one time code is available instead of a password."/>}>
      <Pane>
        <PaneHead id="S-04 · SIGN IN" back={() => nav('/s-03')}/>
        <main className="v34-main">
          <h1 id="S-04-title" className="v34-title">Sign in</h1>
          <div className="v34-fieldset">
            <Field
              id="v34-login-mobile"
              label="MOBILE NUMBER"
              value={mobile}
              onChange={setMobile}
              type="tel"
              inputMode="numeric"
              autoComplete="tel-national"
              prefix="+91"
              error={errors.mobile}
              maxLength={15}
              disabled={mode === 'otp' && otpSent}
            />
            {mode === 'password' && (
              <Field
                id="v34-login-password"
                label="PASSWORD"
                value={password}
                onChange={setPassword}
                type="password"
                autoComplete="current-password"
                error={errors.password}
                maxLength={128}
              />
            )}
            {mode === 'otp' && otpSent && (
              <Field
                id="v34-login-otp"
                label="6-DIGIT ONE-TIME CODE *"
                value={otpCode}
                onChange={(val) => setOtpCode(val.replace(/\D/g, '').slice(0, 6))}
                type="text"
                inputMode="numeric"
                autoComplete="one-time-code"
                error={errors.otp}
                maxLength={6}
                placeholder="Enter 6-digit OTP code"
              />
            )}
          </div>
          {errors.submit && <span className="v34-field__error" role="alert">{errors.submit}</span>}
          <div className="v34-inlineactions">
            <button
              type="button"
              className="v34-hit v34-linkbtn"
              onClick={() => {
                setErrors({});
                setOtpSent(false);
                setOtpCode('');
                setMode((value) => (value === 'password' ? 'otp' : 'password'));
              }}
            >
              {mode === 'password' ? 'Use a one time code' : 'Use password'}
            </button>
            {mode === 'otp' && otpSent ? (
              <button
                type="button"
                className="v34-hit v34-linkbtn"
                onClick={() => {
                  setOtpSent(false);
                  setOtpCode('');
                  setErrors({});
                }}
              >
                Change mobile number
              </button>
            ) : (
              <button type="button" className="v34-hit" onClick={() => nav('/s-06')}>
                Forgot password
              </button>
            )}
          </div>
          <span className="v34-grow"/>
        </main>
        <Footer hint={<>New here? <button className="v34-textlink" onClick={() => nav('/s-08')}>Create a student account</button></>}>
          <IconAction
            label={mode === 'password' ? 'Sign in' : otpSent ? 'Verify OTP & Sign In' : 'Send one time code'}
            icon={mode === 'password' ? 'key' : otpSent ? 'verify' : 'send'}
            onClick={submit}
            disabled={busy}
          />
        </Footer>
      </Pane>
    </Screen>
  );
}

export function V34LoginFailure() {
  const nav = useNavigate();
  return (
    <Screen id="S-05" aside={<AuthAside title="Welcome back." copy="Five failed attempts lock sign in for 15 minutes. A one time code remains available."/>}>
      <Pane><PaneHead id="S-05 · ERROR" back={() => nav('/s-04')}/><main className="v34-main">
        <h1 id="S-05-title" className="v34-title">Sign in</h1><div className="v34-banner" role="alert"><b>TWO ATTEMPTS LEFT</b><span>That number and password do not match. We do not disclose whether an account exists.</span></div>
        <div className="v34-fieldset"><Field id="v34-error-mobile" label="MOBILE NUMBER" value="" onChange={() => undefined} type="tel" prefix="+91" placeholder="Re-enter on the sign-in screen"/><Field id="v34-error-password" label="PASSWORD" value="" onChange={() => undefined} type="password" error="Check your password or use a one time code."/></div>
        <button className="v34-hit v34-linkbtn" onClick={() => nav('/s-04')}>Send a one time code instead</button><span className="v34-grow"/>
      </main><Footer hint={<>Locked out? <button className="v34-textlink" onClick={() => nav('/s-06')}>Reset your password</button></>}><IconAction label="Try again" icon="retry" onClick={() => nav('/s-04')}/></Footer></Pane>
    </Screen>
  );
}

export function V34PasswordReset() {
  const nav = useNavigate();
  const [step, setStep] = useState<'mobile' | 'otp' | 'password'>('mobile');
  const [mobile, setMobile] = useState('');
  const [recoveryId, setRecoveryId] = useState('');
  const [code, setCode] = useState('');
  const [newPassword, setNewPassword] = useState('');
  const [confirmPassword, setConfirmPassword] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [message, setMessage] = useState('');

  async function handleSend() {
    if (!isValidMobile(mobile)) {
      setError(MOBILE_ERROR);
      return;
    }
    setError('');
    setBusy(true);
    try {
      const id = await startRecovery(mobile);
      setRecoveryId(id);
      setStep('otp');
      setMessage('If an account matches, a six digit recovery code has been sent.');
    } catch {
      /* non-enumerating response intentionally remains identical */
      setMessage('If an account matches, a six digit recovery code has been sent.');
      setStep('otp');
    } finally {
      setBusy(false);
    }
  }

  async function handleVerifyCode() {
    if (!/^\d{6}$/.test(code)) {
      setError('Enter the complete 6-digit recovery code.');
      return;
    }
    setError('');
    setBusy(true);
    try {
      await verifyRecovery(recoveryId, code);
      setStep('password');
      setMessage('Recovery code verified. Create your new password below.');
    } catch {
      setError('Recovery could not be verified. Check the code or request a new one.');
    } finally {
      setBusy(false);
    }
  }

  async function handleSavePassword() {
    if (newPassword.length < 8 || newPassword.length > 128) {
      setError('Password must be between 8 and 128 characters.');
      return;
    }
    if (newPassword !== confirmPassword) {
      setError('Passwords do not match. Re-enter confirm password.');
      return;
    }
    setError('');
    setBusy(true);
    try {
      await completeRecovery(recoveryId, newPassword);
      notifyStudentAuthChanged();
      nav('/s-14');
    } catch {
      setError('Could not update password. Please retry.');
    } finally {
      setBusy(false);
    }
  }

  return (
    <Screen
      id="S-06"
      aside={
        <AuthAside
          title="Reset your password."
          copy="The response stays identical whether or not the number is registered."
        />
      }
    >
      <Pane>
        <PaneHead id="S-06 · RESET" back={() => nav('/s-04')} />
        <main className="v34-main">
          <h1 id="S-06-title" className="v34-title">
            Reset your password
          </h1>
          <p className="v34-lede">
            {step === 'mobile'
              ? 'Tell us the mobile number on the account. We will send a six digit code.'
              : step === 'otp'
              ? `Six digit recovery code sent to ${mobile ? maskDestination({ channel: 'sms', ref: mobile }) : 'your mobile'}.`
              : 'Choose a strong password with at least 8 characters.'}
          </p>

          <div className="v34-fieldset">
            <Field
              id="v34-reset-mobile"
              label="MOBILE NUMBER"
              value={mobile}
              onChange={setMobile}
              type="tel"
              inputMode="numeric"
              prefix="+91"
              placeholder="10 digit number"
              maxLength={15}
              disabled={step !== 'mobile'}
            />

            {step === 'otp' && (
              <Field
                id="v34-recovery-code"
                label="6-DIGIT RECOVERY CODE"
                value={code}
                onChange={(val) => setCode(val.replace(/\D/g, '').slice(0, 6))}
                inputMode="numeric"
                autoComplete="one-time-code"
                maxLength={6}
                placeholder="Enter 6-digit code"
              />
            )}

            {step === 'password' && (
              <>
                <Field
                  id="v34-new-password"
                  label="NEW PASSWORD"
                  value={newPassword}
                  onChange={setNewPassword}
                  type="password"
                  autoComplete="new-password"
                  placeholder="At least 8 characters"
                  maxLength={128}
                />
                <Field
                  id="v34-confirm-password"
                  label="CONFIRM NEW PASSWORD"
                  value={confirmPassword}
                  onChange={setConfirmPassword}
                  type="password"
                  autoComplete="new-password"
                  placeholder="Re-enter new password"
                  maxLength={128}
                />
              </>
            )}
          </div>

          {error && <span className="v34-field__error" role="alert">{error}</span>}
          {message && !error && <div className="v34-well" role="status">{message}</div>}

          <div className="v34-rule" />
          <div>
            <span className="v34-mono v34-accent">WHY THE WORDING IS CAREFUL</span>
            <p className="v34-copy">
              The same confirmation protects your identity from anyone probing mobile numbers.
            </p>
          </div>
          <span className="v34-grow" />

          <button
            type="button"
            className="v34-submit-btn"
            disabled={busy}
            onClick={step === 'mobile' ? handleSend : step === 'otp' ? handleVerifyCode : handleSavePassword}
            style={{ marginBottom: '16px' }}
          >
            {step === 'mobile'
              ? 'Send OTP'
              : step === 'otp'
              ? 'Verify Recovery Code'
              : 'Save Password & Sign In'}
          </button>
        </main>
        <Footer
          hint={
            step === 'mobile'
              ? 'We will text a six digit code to that number.'
              : step === 'otp'
              ? 'Use the latest recovery code. It can only be consumed once.'
              : 'Create a new secure password for your account.'
          }
        >
          <span />
        </Footer>
      </Pane>
    </Screen>
  );
}

const HOME_NAV = ['Home', 'Ask', 'Calendar', 'Exam Prep', 'Case Digests', 'Moot Court', 'Drafting Lab', 'Internships', 'Career & Jobs', 'Clinical Hours', 'Community', 'Profile & Settings'];
export function V34VerifiedHome(props: ScreenProps) {
  const nav = useNavigate();
  async function signOut() {
    try { await logoutStudent(); } finally {
      notifyStudentAuthChanged();
      nav('/s-03', { replace: true });
    }
  }
  return (
    <Screen id="S-07" variant="app" aside={<nav className="v34-sidenav" aria-label="Main"><Brand/>{HOME_NAV.map((label, index) => <button type="button" key={label} className={index === 0 ? 'is-on' : ''} onClick={() => index === 11 ? nav('/s-17') : undefined}><span aria-hidden="true">{index === 0 ? '⌂' : '·'}</span>{label}</button>)}<span className="v34-grow"/><small>TIER 2 · Bar enrolment is optional and private.</small></nav>}>
      <Pane><header className="v34-appbar"><Brand/><button type="button" className="v34-command">Ask a question or search…</button><button type="button" className="v34-hit v34-linkbtn" onClick={signOut}>Sign out</button><ThemeButton {...props}/></header><main className="v34-main">
        <span className="v34-mono">THURSDAY · 30 JULY</span><h1 id="S-07-title" className="v34-display">Good morning, Aditi.</h1><p className="v34-lede">Three useful things are close: a moot deadline, a tutor session and your next digest.</p>
        <div className="v34-homegrid"><section><h2>On your docket</h2>{[['TODAY', 'Memorial draft due', 'Constitutional law moot'], ['SAT', 'Tutor session', 'Adv. Priya Raman · 60 minutes']].map(([day, title, detail]) => <article key={title} className="v34-docket"><b>{day}</b><span><strong>{title}</strong><small>{detail}</small></span></article>)}</section><aside><div className="v34-card"><b className="v34-stat">82%</b><span>profile complete</span></div><div className="v34-card"><span>Applications open</span><b>2</b></div><div className="v34-card"><span>Digests due</span><b>12</b></div></aside></div><span className="v34-grow"/>
      </main><nav className="v34-tabbar" aria-label="Main mobile">{['Home', 'Calendar', 'Prep', 'Career', 'Community'].map((label) => <button key={label} className={label === 'Home' ? 'is-on' : ''}>{label}</button>)}</nav></Pane>
    </Screen>
  );
}

const COLLEGES = [{ value: 'NLSIU', label: 'NLSIU, Bengaluru' }, { value: 'NALSAR', label: 'NALSAR, Hyderabad' }, { value: 'OTHER', label: 'Other' }];
const YEARS = Array.from({ length: 5 }, (_, index) => ({ value: String(index + 1), label: `${index + 1}${index === 0 ? 'st' : index === 1 ? 'nd' : index === 2 ? 'rd' : 'th'} year` }));

export function V34Register(props: ScreenProps) {
  const nav = useNavigate();
  const [firstName, setFirstName] = useState(''); const [middleName, setMiddleName] = useState(''); const [lastName, setLastName] = useState('');
  const [mobile, setMobile] = useState(''); const [email, setEmail] = useState(''); const [dob, setDob] = useState('');
  const [college, setCollege] = useState(''); const [year, setYear] = useState(''); const [bar, setBar] = useState('');
  const [lawDeclaration, setLawDeclaration] = useState(false); const [privacy, setPrivacy] = useState(false); const [busy, setBusy] = useState(false);
  const [errors, setErrors] = useState<Record<string, string>>({});
  async function submit() {
    const next: Record<string, string> = {}; const parts = { firstName, middleName, lastName }; const nameErrors = validateNameParts(parts);
    if (nameErrors.firstName) next.firstName = nameErrorMessage('firstName', nameErrors.firstName); if (nameErrors.middleName) next.middleName = nameErrorMessage('middleName', nameErrors.middleName); if (nameErrors.lastName) next.lastName = nameErrorMessage('lastName', nameErrors.lastName);
    if (!isValidMobile(mobile)) next.mobile = MOBILE_ERROR; if (!dob) next.dob = 'Enter your date of birth.'; else if (!isRegistrableDob(dob, new Date())) next.dob = DOB_ERROR;
    if (!EMAIL_RE.test(email.trim())) next.email = 'Enter a full institutional email address.'; if (!college) next.college = 'Select your college or university.'; if (!year) next.year = 'Select your year of study.';
    if (!lawDeclaration || !privacy) next.consent = 'Accept the law-student declaration and DPDP notice to continue.'; setErrors(next); if (Object.keys(next).length) return;
    const payload = namePartsToPayload(parts); const minor = isMinor(dob, new Date().toISOString());
    updateProfileDraft({ ...parts, fullName: composeDisplayName(parts), dateOfBirth: dob, college, yearOfStudy: year, institutionalEmail: email, barEnrolmentNumber: bar });
    setBusy(true);
    try {
      const created = await registerStudent({ firstName: payload.firstName, middleName: payload.middleName, lastName: payload.lastName, mobile, dob, policyVersion: CONSENT_VERSION, college });
      saveRegistrationSession({ registrationId: created.registration_id, destinationMasked: maskDestination({ channel: 'sms', ref: mobile }), issuedAt: Date.now(), isMinor: minor, guardianConsentPending: minor });
      setMinor(minor, minor); nav('/s-09');
    } catch (caught) { setErrors({ submit: caught instanceof RegistrationApiError && caught.code === 'mobile_already_registered' ? 'This mobile number is already registered.' : 'The account could not be created. Please retry.' }); }
    finally { setBusy(false); }
  }
  return (
    <Screen id="S-08" aside={<AuthAside title="The years before the bar, organised." copy="Five core details now, then verification. Optional fields may stay empty."/>}>
      <Pane><PaneHead id="S-08 · STEP 1 OF 2" back={() => nav('/s-03')}><ThemeButton {...props}/></PaneHead><main className="v34-main">
        <div><h1 id="S-08-title" className="v34-title">Create your student account</h1><p className="v34-copy">Critical legacy fields are preserved: legal name, DOB, institutional email, college, year and optional Bar enrolment.</p></div>
        <div className="v34-fieldset"><div className="v34-row v34-row--three"><Field id="v34-first" label="FIRST NAME" value={firstName} onChange={setFirstName} autoComplete="given-name" maxLength={60} error={errors.firstName}/><Field id="v34-middle" label="MIDDLE NAME" value={middleName} onChange={setMiddleName} autoComplete="additional-name" maxLength={60} optional error={errors.middleName}/><Field id="v34-last" label="LAST NAME" value={lastName} onChange={setLastName} autoComplete="family-name" maxLength={60} error={errors.lastName}/></div>
          <div className="v34-row"><Field id="v34-mobile" label="MOBILE NUMBER" value={mobile} onChange={setMobile} type="tel" inputMode="numeric" autoComplete="tel-national" prefix="+91" maxLength={15} error={errors.mobile} help="Exactly 10 digits. The one time code is sent here."/><Field id="v34-email" label="INSTITUTIONAL EMAIL" value={email} onChange={setEmail} type="email" inputMode="email" autoComplete="email" maxLength={254} error={errors.email}/></div>
          <div className="v34-row"><Field id="v34-dob" label="DATE OF BIRTH" value={dob} onChange={setDob} type="date" error={errors.dob} help={`Required for eligibility; must be on or before ${todayLocalISO()}.`}/><Select id="v34-college" label="COLLEGE OR UNIVERSITY" value={college} onChange={setCollege} options={COLLEGES} error={errors.college}/><Select id="v34-year" label="YEAR OF STUDY" value={year} onChange={setYear} options={YEARS} error={errors.year}/></div>
          <Field id="v34-bar" label="BAR ENROLMENT" value={bar} onChange={setBar} optional maxLength={120} placeholder="Leave blank if not enrolled"/>
        </div><div className="v34-well v34-checks"><label><input type="checkbox" checked={lawDeclaration} onChange={(event) => setLawDeclaration(event.target.checked)}/>I am enrolled in, or applying to, a law programme in India.</label><label><input type="checkbox" checked={privacy} onChange={(event) => setPrivacy(event.target.checked)}/>I accept the terms and DPDP privacy notice.</label>{errors.consent && <span role="alert" className="v34-field__error">{errors.consent}</span>}</div>{errors.submit && <span role="alert" className="v34-field__error">{errors.submit}</span>}<span className="v34-grow"/>
      </main><Footer hint="The code expires after it is sent. Your password is never collected on registration."><IconAction label="Send one time code" icon="send" onClick={submit} disabled={busy}/></Footer></Pane>
    </Screen>
  );
}

export function V34OtpVerify() {
  const nav = useNavigate(); const location = useLocation(); const [now, setNow] = useState(Date.now()); const [code, setCode] = useState(''); const [status, setStatus] = useState(''); const [busy, setBusy] = useState(false); const [attempts, setAttempts] = useState(3);
  const login = location.state as { loginId?: string; destinationMasked?: string; issuedAt?: number } | null;
  const server = login?.loginId ? null : loadRegistrationSession();
  useEffect(() => { const timer = window.setInterval(() => setNow(Date.now()), 1000); return () => window.clearInterval(timer); }, []);
  const issuedAt = login?.issuedAt ?? server?.issuedAt;
  const expires = issuedAt ? Math.max(0, 600 - Math.floor((now - issuedAt) / 1000)) : 0;
  const resend = issuedAt ? Math.max(0, 30 - Math.floor((now - issuedAt) / 1000)) : 0;
  async function submit() {
    if (!isValidOtpFormat(code)) { setStatus('Enter all six digits.'); return; } setBusy(true);
    if (server) {
      try { await verifyStudentOtp(server.registrationId, code); nav(server.guardianConsentPending ? '/s-16' : '/s-10'); }
      catch (caught) { if (caught instanceof RegistrationApiError && typeof caught.attemptsLeft === 'number') setAttempts(caught.attemptsLeft); setStatus('That code could not be verified. Check all six digits.'); }
      finally { setBusy(false); } return;
    }
    if (login?.loginId) {
      try {
        await verifyLoginOtp(login.loginId, code);
        notifyStudentAuthChanged();
        nav('/s-07', { replace: true });
      } catch {
        setAttempts((value) => Math.max(0, value - 1));
        setStatus('That code could not be verified. Check all six digits or request a new code.');
      } finally { setBusy(false); }
      return;
    }
    setStatus('Start registration or sign in before entering a code.');
    setBusy(false);
  }
  async function resendCode() {
    if (resend > 0) return;
    if (server) { try { await resendStudentOtp(server.registrationId); saveRegistrationSession({ ...server, issuedAt: Date.now() }); setNow(Date.now()); setCode(''); setStatus('A new code was sent.'); } catch { setStatus('A new code could not be sent yet.'); } }
    else if (login?.loginId) nav('/s-04', { replace: true });
    else setStatus('Start registration or sign in before requesting another code.');
  }
  const digits = Array.from({ length: 6 }, (_, index) => code[index] ?? '');
  return (
    <Screen id="S-09" aside={<AuthAside title="One code, then you are in." copy="Codes are short-lived. Repeated wrong entries trigger a temporary lock."/>}>
      <Pane><PaneHead id="S-09 · STEP 2 OF 2" back={() => nav(server ? '/s-08' : '/s-04')}/><main className="v34-main">
        <div><h1 id="S-09-title" className="v34-title">Enter the code</h1><p className="v34-lede">Six digits, sent to {login?.destinationMasked ?? server?.destinationMasked ?? 'your mobile'}.</p></div>
        <label className="v34-otp">{digits.map((digit, index) => <span key={index} aria-hidden="true">{digit}</span>)}<input aria-label="Six digit code" inputMode="numeric" autoComplete="one-time-code" maxLength={6} value={code} onChange={(event) => setCode(event.target.value.replace(/\D/g, '').slice(0, 6))}/></label>
        {status && <div className="v34-banner" role="alert">{status}</div>}<div className="v34-card v34-kv"><span>Code expires in <b>{Math.floor(expires / 60).toString().padStart(2, '0')}:{(expires % 60).toString().padStart(2, '0')}</b></span><span>Resend available in <button className="v34-textlink" disabled={resend > 0} onClick={resendCode}>{resend > 0 ? `00:${String(resend).padStart(2, '0')}` : 'Resend now'}</button></span><span>Tries left <b>{attempts}</b></span></div><span className="v34-grow"/>
      </main><Footer hint="Enter all six digits to verify."><IconAction label="Verify and continue" icon="verify" onClick={submit} disabled={busy || code.length !== 6}/></Footer></Pane>
    </Screen>
  );
}

export function V34ProfileStep1() {
  const nav = useNavigate();
  const location = useLocation();
  const query = useMemo(() => new URLSearchParams(location.search), [location.search]);
  const draft = getProfileDraft();

  const initialStep = query.get('step') === 'academic' ? 2 : 1;
  const [activeStep, setActiveStep] = useState<number>(initialStep);
  const [savedBanner, setSavedBanner] = useState<string | null>(null);

  useEffect(() => {
    if (query.get('step') === 'academic') setActiveStep(2);
    const current = getProfileDraft();
    if (current.firstName && !firstName) setFirstName(current.firstName);
    if (current.middleName && !middleName) setMiddleName(current.middleName);
    if (current.lastName && !lastName) setLastName(current.lastName);
    if (current.dateOfBirth && !dateOfBirth) setDob(current.dateOfBirth);
    if (current.city && !city) setCity(current.city);
    if (current.pronouns && !pronouns) setPronouns(current.pronouns);
    if (current.avatarUrl && !photoPreview) setPhotoPreview(current.avatarUrl);
    if (current.college && !college) setCollege(current.college);
    if (current.yearOfStudy && !yearOfStudy) setYear(current.yearOfStudy);
    if (current.enrolmentNumber && !enrolmentNumber) setEnrolmentNumber(current.enrolmentNumber);
    if (current.interests?.length && !selectedInterests.length) setSelectedInterests(current.interests);
    if (current.careerGoal && !careerGoal) setCareerGoal(current.careerGoal);
  }, [location.search]);

  // Step 1: Personal State
  const fileInputRef = useRef<HTMLInputElement>(null);
  const [photoPreview, setPhotoPreview] = useState<string | null>(draft.avatarUrl || null);
  const [firstName, setFirstName] = useState(draft.firstName || '');
  const [middleName, setMiddleName] = useState(draft.middleName || '');
  const [lastName, setLastName] = useState(draft.lastName || '');
  const [dateOfBirth, setDob] = useState(draft.dateOfBirth || '');
  const [city, setCity] = useState(draft.city || '');
  const [pronouns, setPronouns] = useState(draft.pronouns || '');
  const [personalErrors, setPersonalErrors] = useState<Record<string, string>>({});

  // Step 2: Academic State
  const [college, setCollege] = useState(draft.college || '');
  const [yearOfStudy, setYear] = useState(draft.yearOfStudy || '');
  const [enrolmentNumber, setEnrolmentNumber] = useState(draft.enrolmentNumber || '');
  const [academicErrors, setAcademicErrors] = useState<Record<string, string>>({});

  // Step 3: Interests & Goals State
  const [selectedInterests, setSelectedInterests] = useState<string[]>(draft.interests || []);
  const [careerGoal, setCareerGoal] = useState<string>(draft.careerGoal || '');

  const calculatedPct = useMemo(() => {
    let score = 0;
    if (firstName.trim()) score += 6;
    if (lastName.trim()) score += 6;
    if (dateOfBirth) score += 12;
    if (city) score += 10;

    if (college) score += 18;
    if (yearOfStudy) score += 10;
    if (enrolmentNumber.trim()) score += 5;

    if (selectedInterests.length > 0) score += 18;
    if (careerGoal) score += 15;

    return Math.min(100, score);
  }, [firstName, lastName, dateOfBirth, city, college, yearOfStudy, enrolmentNumber, selectedInterests, careerGoal]);

  function handlePhotoChange(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0];
    if (file) {
      const reader = new FileReader();
      reader.onload = (event) => {
        const url = event.target?.result as string;
        setPhotoPreview(url);
        updateProfileDraft({ avatarUrl: url });
      };
      reader.readAsDataURL(file);
    }
  }

  function saveInPlace() {
    updateProfileDraft({
      firstName: firstName.trim() || draft.firstName,
      middleName: middleName.trim() || draft.middleName,
      lastName: lastName.trim() || draft.lastName,
      fullName: composeDisplayName({ firstName: firstName.trim() || draft.firstName, middleName: middleName.trim() || draft.middleName, lastName: lastName.trim() || draft.lastName }),
      dateOfBirth: dateOfBirth || draft.dateOfBirth,
      city: city || draft.city,
      pronouns: pronouns || draft.pronouns,
      avatarUrl: photoPreview || draft.avatarUrl,
      college: college || draft.college,
      yearOfStudy: yearOfStudy || draft.yearOfStudy,
      enrolmentNumber: enrolmentNumber || draft.enrolmentNumber,
      interests: selectedInterests,
      careerGoal: careerGoal || draft.careerGoal,
    });
    setSavedBanner('✓ Progress saved. Your draft will stay saved whenever you return.');
    setTimeout(() => setSavedBanner(null), 4000);
  }

  function handlePersonalSubmit() {
    const next: Record<string, string> = {};
    if (!firstName.trim()) next.firstName = 'Enter your first name.';
    else if (firstName.trim().length > 60) next.firstName = 'First name must be 60 characters or fewer.';
    if (!lastName.trim()) next.lastName = 'Enter your last name.';
    else if (lastName.trim().length > 60) next.lastName = 'Last name must be 60 characters or fewer.';
    if (!dateOfBirth) next.dob = 'Enter your date of birth.';
    else if (!isRegistrableDob(dateOfBirth, new Date())) next.dob = DOB_ERROR;
    if (!city) next.city = 'Choose your city.';
    if (pronouns.length > 60) next.pronouns = 'Pronouns must be 60 characters or fewer.';
    setPersonalErrors(next);
    if (Object.keys(next).length) return;

    updateProfileDraft({
      firstName: firstName.trim(),
      middleName: middleName.trim(),
      lastName: lastName.trim(),
      fullName: composeDisplayName({ firstName: firstName.trim(), middleName: middleName.trim(), lastName: lastName.trim() }),
      dateOfBirth,
      city,
      pronouns,
      avatarUrl: photoPreview || undefined,
    });
    setActiveStep(2);
  }

  function handleAcademicSubmit() {
    const next: Record<string, string> = {};
    if (!college) next.college = 'Choose your college.';
    if (!yearOfStudy) next.year = 'Choose your year of study.';
    setAcademicErrors(next);
    if (Object.keys(next).length) return;

    updateProfileDraft({
      college,
      yearOfStudy,
      enrolmentNumber,
    });
    setActiveStep(3);
  }

  function handleInterestsSubmit() {
    updateProfileDraft({
      interests: selectedInterests,
    });
    setActiveStep(4);
  }

  function toggleInterest(item: string) {
    setSelectedInterests((prev) =>
      prev.includes(item) ? prev.filter((i) => i !== item) : [...prev, item]
    );
  }

  const stepsList = [
    { num: 1, label: 'Personal', desc: 'Name, date of birth, city' },
    { num: 2, label: 'Academic', desc: 'College, year, enrolment' },
    { num: 3, label: 'Interests', desc: 'Practice areas, cities' },
  ];

  return (
    <Screen
      id="S-10"
      variant="wizard"
      aside={
        <aside className="v34-profile-rail">
          <span className="v34-mono">PROFILE SETUP</span>
          {stepsList.map((stepItem) => (
            <div
              key={stepItem.label}
              className={`v34-hit ${activeStep === stepItem.num ? 'is-on' : ''}`}
              style={{ cursor: 'pointer' }}
              onClick={() => setActiveStep(stepItem.num)}
            >
              <b>{stepItem.num}</b>
              <span>
                {stepItem.label}
                <small>{stepItem.desc}</small>
              </span>
            </div>
          ))}
          <div className="v34-rule" />
          <strong className="v34-stat">{calculatedPct}%</strong>
          <small>We ask for the minimum. No marks or Aadhaar.</small>
        </aside>
      }
    >
      <Pane>
        <div className="v34-steps">
          <i className={activeStep >= 1 ? 'is-on' : ''} />
          <i className={activeStep >= 2 ? 'is-on' : ''} />
          <i className={activeStep >= 3 ? 'is-on' : ''} />
          <span>STEP {Math.min(activeStep, 3)} OF 3</span>
        </div>
        <main className="v34-main">
          {savedBanner && (
            <div className="v34-well" style={{ backgroundColor: '#eefbfa', borderColor: '#2ba89c', color: '#0d5c54', fontWeight: 500, marginBottom: '16px' }}>
              {savedBanner}
            </div>
          )}

          {activeStep === 1 ? (
            <>
              <div>
                <h1 id="S-10-title" className="v34-title">About you</h1>
                <p className="v34-copy">Shapes which internships, tutors and digests you see first. Editable later.</p>
              </div>
              <div className="v34-card v34-photo" style={{ display: 'flex', alignItems: 'center', gap: '12px' }}>
                <input
                  ref={fileInputRef}
                  id="v34-photo-input"
                  type="file"
                  accept="image/*"
                  onChange={handlePhotoChange}
                  style={{ display: 'none' }}
                />
                {photoPreview ? (
                  <img
                    src={photoPreview}
                    alt="Profile photo preview"
                    style={{ width: '42px', height: '42px', borderRadius: '50%', objectFit: 'cover' }}
                  />
                ) : (
                  <span aria-hidden="true">◎</span>
                )}
                <p style={{ flex: 1, margin: 0 }}>Photo is optional. Only tutors you book can see it.</p>
                <button type="button" className="v34-hit" onClick={() => fileInputRef.current?.click()}>
                  {photoPreview ? 'Change' : 'Add'}
                </button>
              </div>
              <div className="v34-fieldset">
                <Field
                  id="v34-firstname"
                  label="FIRST NAME *"
                  value={firstName}
                  onChange={setFirstName}
                  maxLength={60}
                  error={personalErrors.firstName}
                />
                <div className="v34-row">
                  <Field
                    id="v34-middlename"
                    label="MIDDLE NAME"
                    value={middleName}
                    onChange={setMiddleName}
                    optional
                    maxLength={60}
                    error={personalErrors.middleName}
                  />
                  <Field
                    id="v34-lastname"
                    label="LAST NAME *"
                    value={lastName}
                    onChange={setLastName}
                    maxLength={60}
                    error={personalErrors.lastName}
                  />
                </div>
                <div className="v34-row">
                  <Field
                    id="v34-profile-dob"
                    label="DATE OF BIRTH *"
                    value={dateOfBirth}
                    onChange={setDob}
                    type="date"
                    error={personalErrors.dob}
                  />
                  <Select
                    id="v34-city"
                    label="CITY *"
                    value={city}
                    onChange={setCity}
                    options={[
                      { value: 'Bengaluru', label: 'Bengaluru' },
                      { value: 'New Delhi', label: 'New Delhi' },
                      { value: 'Mumbai', label: 'Mumbai' },
                      { value: 'Kolkata', label: 'Kolkata' },
                      { value: 'Chennai', label: 'Chennai' },
                      { value: 'Hyderabad', label: 'Hyderabad' },
                      { value: 'Pune', label: 'Pune' },
                    ]}
                    error={personalErrors.city}
                  />
                </div>
                <Field
                  id="v34-pronouns"
                  label="PRONOUNS"
                  value={pronouns}
                  onChange={setPronouns}
                  optional
                  maxLength={60}
                  placeholder="Prefer not to say"
                  error={personalErrors.pronouns}
                />
              </div>
              <div className="v34-rule" />
              <div className="v34-complete">
                <strong>{calculatedPct}%</strong>
                <span>
                  profile complete<small>All three steps open internship applications.</small>
                </span>
              </div>
            </>
          ) : activeStep === 2 ? (
            <>
              <div>
                <h1 id="S-10-title" className="v34-title">Academic profile</h1>
                <p className="v34-copy">Verify your law school, course year, and enrolment details.</p>
              </div>
              <div className="v34-fieldset">
                <Select
                  id="v34-college"
                  label="COLLEGE / LAW SCHOOL *"
                  value={college}
                  onChange={setCollege}
                  options={[
                    { value: 'nls', label: 'National Law School of India University (NLSIU), Bengaluru' },
                    { value: 'nalsar', label: 'NALSAR University of Law, Hyderabad' },
                    { value: 'nujs', label: 'WBNUJS, Kolkata' },
                    { value: 'nlud', label: 'National Law University, Delhi' },
                    { value: 'glc', label: 'Government Law College, Mumbai' },
                    { value: 'other', label: 'Other Recognized Law College' },
                  ]}
                  error={academicErrors.college}
                />
                <div className="v34-row">
                  <Select
                    id="v34-year"
                    label="YEAR OF STUDY *"
                    value={yearOfStudy}
                    onChange={setYear}
                    options={[
                      { value: '1', label: '1st Year' },
                      { value: '2', label: '2nd Year' },
                      { value: '3', label: '3rd Year' },
                      { value: '4', label: '4th Year' },
                      { value: '5', label: '5th Year' },
                      { value: 'graduated', label: 'Graduated / LLM' },
                    ]}
                    error={academicErrors.year}
                  />
                  <Field
                    id="v34-enrolment"
                    label="ENROLMENT NUMBER"
                    optional
                    value={enrolmentNumber}
                    onChange={setEnrolmentNumber}
                    placeholder="e.g. 2023/BALLB/042"
                    maxLength={40}
                  />
                </div>
              </div>
              <div className="v34-rule" />
              <div className="v34-complete">
                <strong>{calculatedPct}%</strong>
                <span>
                  profile complete<small>One final step remaining to unlock all features.</small>
                </span>
              </div>
            </>
          ) : activeStep === 3 ? (
            <>
              <div>
                <h1 id="S-10-title" className="v34-title">Interests & career goals</h1>
                <p className="v34-copy">Select your legal practice interests and target career paths.</p>
              </div>
              <div className="v34-fieldset">
                <div>
                  <span className="v34-mono" style={{ display: 'block', marginBottom: '8px' }}>PRACTICE INTERESTS *</span>
                  <div className="v34-chips" role="group" aria-label="Practice interests">
                    {['Constitutional', 'Arbitration', 'Criminal', 'Corporate', 'Tech & Privacy', 'Intellectual Property', 'Environmental'].map((item) => (
                      <button
                        key={item}
                        type="button"
                        className={selectedInterests.includes(item) ? 'is-on' : ''}
                        onClick={() => toggleInterest(item)}
                      >
                        {item}
                      </button>
                    ))}
                  </div>
                </div>
                <Select
                  id="v34-career-goal"
                  label="CAREER ASPIRATION *"
                  value={careerGoal}
                  onChange={setCareerGoal}
                  options={[
                    { value: 'Litigation & judiciary', label: 'Litigation & Judiciary' },
                    { value: 'Corporate / in-house', label: 'Corporate / In-House Counsel' },
                    { value: 'Policy & academia', label: 'Policy & Academia' },
                    { value: 'Undecided', label: 'Undecided / Exploring' },
                  ]}
                />
              </div>
              <div className="v34-rule" />
              <div className="v34-complete">
                <strong>{calculatedPct}%</strong>
                <span>
                  profile complete<small>Ready to unlock your student dashboard.</small>
                </span>
              </div>
            </>
          ) : (
            <>
              <div style={{ textAlign: 'center', padding: '24px 12px' }}>
                <span style={{ fontSize: '48px', display: 'block', marginBottom: '12px' }}>🎉</span>
                <h1 id="S-10-title" className="v34-title" style={{ fontSize: '24px', marginBottom: '8px' }}>Profile Setup Complete!</h1>
                <p className="v34-copy" style={{ maxWidth: '460px', margin: '0 auto 24px auto' }}>
                  Your student profile has been saved. Your personalized dashboard with tailored internships, tutors, and legal digests is ready.
                </p>

                <div className="v34-card" style={{ textAlign: 'left', maxWidth: '440px', margin: '0 auto 24px auto', padding: '16px' }}>
                  <span className="v34-mono" style={{ display: 'block', marginBottom: '8px' }}>PROFILE SUMMARY</span>
                  <div style={{ display: 'grid', gap: '8px', fontSize: '14px' }}>
                    <div><strong>Name:</strong> {[firstName, middleName, lastName].filter(Boolean).join(' ') || draft.fullName || 'Student'}</div>
                    <div><strong>Date of Birth:</strong> {formatDDMMYYYY(dateOfBirth || draft.dateOfBirth || '')}</div>
                    <div><strong>City:</strong> {city || draft.city || 'Bengaluru'}</div>
                    <div><strong>College:</strong> {COLLEGE_OPTIONS.find(c => c.value === college || c.value === draft.college)?.label || college || draft.college || 'Recognized Law College'}</div>
                    <div><strong>Year of Study:</strong> {yearOfStudy || draft.yearOfStudy || '1'}{/^\d+$/.test(yearOfStudy || draft.yearOfStudy || '1') ? (yearOfStudy === '1' ? 'st Year' : yearOfStudy === '2' ? 'nd Year' : yearOfStudy === '3' ? 'rd Year' : 'th Year') : ''}</div>
                    <div><strong>Practice Interests:</strong> {selectedInterests.join(', ') || 'General Law'}</div>
                  </div>
                </div>

                <button
                  type="button"
                  className="v34-submit-btn"
                  style={{ width: 'auto', padding: '12px 36px', fontSize: '15px', display: 'inline-block' }}
                  onClick={() => {
                    notifyStudentAuthChanged();
                    nav('/s-14', { replace: true });
                  }}
                >
                  Go to Dashboard
                </button>
              </div>
            </>
          )}

          <span className="v34-grow" />
        </main>
        {activeStep <= 3 && (
          <Footer hint={activeStep === 1 ? 'Step 1: Save your personal details to progress your profile.' : activeStep === 2 ? 'Step 2 connects you with law school resources and tutors.' : 'Step 3 customizes your feed and internship recommendations.'}>
            <div style={{ display: 'flex', gap: '12px', width: '100%', justifyContent: 'space-between', alignItems: 'center' }}>
              <button
                type="button"
                className="v34-hit v34-linkbtn"
                style={{ padding: '8px 16px', cursor: 'pointer' }}
                onClick={activeStep === 1 ? saveInPlace : () => setActiveStep(activeStep - 1)}
              >
                {activeStep === 1 ? 'Save and finish later' : activeStep === 2 ? 'Back to personal' : 'Back to academics'}
              </button>
              <button
                type="button"
                className="v34-submit-btn"
                style={{ padding: '10px 24px', width: 'auto' }}
                onClick={activeStep === 1 ? handlePersonalSubmit : activeStep === 2 ? handleAcademicSubmit : handleInterestsSubmit}
              >
                {activeStep === 1 ? 'Continue to academics' : activeStep === 2 ? 'Continue to interests' : 'Complete profile'}
              </button>
            </div>
          </Footer>
        )}
      </Pane>
    </Screen>
  );
}
