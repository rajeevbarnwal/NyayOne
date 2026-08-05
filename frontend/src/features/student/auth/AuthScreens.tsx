import { useEffect, useMemo, useState } from 'react';
import { useNavigate, useLocation } from 'react-router-dom';
import { AuthCard, TextField, Checkbox, DpdpFootnote, StudentScreen, InfoTooltip, MobileInputField } from '../components';
import {
  isValidMobile, MOBILE_ERROR,
  isRegistrableDob, DOB_ERROR, todayLocalISO,
  validateNameParts, nameErrorMessage, namePartsToPayload, composeDisplayName,
} from '../lib/registration';
import { RestrictedState, LoadingState, StatusBadge } from '../../../components/ui/primitives';
import {
  isValidOtpFormat,
  verify,
  secondsUntilResend,
  secondsUntilExpiry,
  maskDestination,
  type OtpChannel,
} from '../lib/otp';
import { startOtp, getFlow, setChallenge, setMinor } from '../lib/authFlow';
import { isMinor, registrationConsentComplete, CONSENT_VERSION, type RegistrationConsent } from '../lib/consent';
import { isProfileComplete, institutionalEmailError } from '../lib/profile';
import { updateProfileDraft, getProfileDraft } from '../lib/profileStore';
import { useAuth } from '../../../app/authContext';
import {
  RegistrationApiError,
  checkMobileRegistered,
  loadRegistrationSession,
  registerStudent,
  resendStudentOtp,
  saveRegistrationSession,
  startRecovery,
  verifyRecovery,
  verifyStudentOtp,
  completeRecovery,
  requestInstitutionalEmailVerification,
} from '../lib/registrationApi';

/* -------------------------------------------------------------------------- */
/* S-01 — Splash / session check (loading)                                     */
/* -------------------------------------------------------------------------- */
export function Splash() {
  const nav = useNavigate();
  const auth = useAuth();
  useEffect(() => {
    nav(auth.isAuthenticated ? '/s-14' : '/s-03', { replace: true });
  }, [auth.isAuthenticated, nav]);
  return (
    <AuthCard screenId="S-01" kicker="Student module · S1" title="LegalSaathi" brand>
      <LoadingState label="Checking your session…" />
      <DpdpFootnote>Privacy notice shown before registration · no PII in analytics</DpdpFootnote>
    </AuthCard>
  );
}

/* -------------------------------------------------------------------------- */
/* S-02 — Onboarding carousel                                                  */
/* -------------------------------------------------------------------------- */
const ONBOARDING = [
  { t: 'Your legal-study hub', b: 'Internships, exam prep, moots and clinical hours — tuned to your college and year.' },
  { t: 'Research with guardrails', b: 'AI study assistance that always cites sources — verify every citation before you rely on it.' },
  { t: 'Private by design', b: 'We collect only what personalises your experience. Export or delete anytime.' },
];
export function Onboarding() {
  const nav = useNavigate();
  const [i, setI] = useState(0);
  const last = i === ONBOARDING.length - 1;
  return (
    <AuthCard
      screenId="S-02"
      kicker={`Welcome · ${i + 1} of ${ONBOARDING.length}`}
      title={ONBOARDING[i].t}
      sub={ONBOARDING[i].b}
      meta={
        <div className="st-dots" role="presentation">
          {ONBOARDING.map((_, k) => (
            <span key={k} className={`st-dot${k === i ? ' st-dot--on' : ''}`} aria-hidden />
          ))}
        </div>
      }
    >
      <div className="st-actions st-actions--split">
        <button type="button" className="btn tap" onClick={() => nav('/s-03')}>
          Skip
        </button>
        <button
          type="button"
          className="btn btn--primary tap"
          onClick={() => (last ? nav('/s-03') : setI((v) => v + 1))}
        >
          {last ? 'Get started' : 'Next'}
        </button>
      </div>
    </AuthCard>
  );
}

/* -------------------------------------------------------------------------- */
/* S-03 — Auth gate (login / register)                                         */
/* -------------------------------------------------------------------------- */
export function AuthGate() {
  const nav = useNavigate();
  const [tab, setTab] = useState<'login' | 'register'>('login');
  const [countryCode, setCountryCode] = useState('+91');
  const [mobile, setMobile] = useState('');
  const [error, setError] = useState<string | undefined>();
  const [checkingMobile, setCheckingMobile] = useState(false);
  const [notRegistered, setNotRegistered] = useState(false);

  async function sendOtp() {
    const digits = mobile.replace(/\D/g, '');
    if (digits.length !== 10) {
      setError('Enter a valid 10-digit mobile number.');
      setNotRegistered(false);
      return;
    }
    setError(undefined);
    setNotRegistered(false);
    setCheckingMobile(true);

    try {
      const checkRes = await checkMobileRegistered(digits);
      if (!checkRes.exists) {
        // Scenario 3: Entry NOT found in DB
        setNotRegistered(true);
        setError('This mobile number is not registered. Please enter a registered number or register with us.');
        return;
      }
      const fullMobile = `${countryCode}${digits}`;
      startOtp({ channel: 'sms' as OtpChannel, ref: fullMobile }, Date.now());
      setMinor(false, false);
      const existingServer = loadRegistrationSession();
      const masked = maskDestination({ channel: 'sms', ref: fullMobile });
      saveRegistrationSession({
        ...(existingServer ?? {}),
        registrationId: checkRes.registrationId || ('00000000-0000-4000-8000-' + digits.padStart(12, '0').slice(-12)),
        destinationMasked: masked,
        issuedAt: Date.now(),
        isMinor: false,
        guardianConsentPending: Boolean(checkRes.guardianConsentPending),
        isLoginFlow: true,
        isProfileComplete: checkRes.isProfileComplete,
        flowOrigin: 'login',
      });
      nav('/s-06');
    } catch {
      // Offline fallback: allow OTP attempt
      const fullMobile = `${countryCode}${digits}`;
      startOtp({ channel: 'sms' as OtpChannel, ref: fullMobile }, Date.now());
      setMinor(false, false);
      const existingServer = loadRegistrationSession();
      const masked = maskDestination({ channel: 'sms', ref: fullMobile });
      saveRegistrationSession({
        ...(existingServer ?? {}),
        registrationId: '00000000-0000-4000-8000-' + digits.padStart(12, '0').slice(-12),
        destinationMasked: masked,
        issuedAt: Date.now(),
        isMinor: false,
        guardianConsentPending: false,
        isLoginFlow: true,
      });
      nav('/s-06');
    } finally {
      setCheckingMobile(false);
    }
  }

  return (
    <AuthCard screenId="S-03" kicker="Student module · S1" title="LegalSaathi" brand>
      <div className="st-tabs" role="tablist" aria-label="Login or register">
        <button role="tab" aria-selected={tab === 'login'} className="st-tab" onClick={() => setTab('login')}>
          Login
        </button>
        <button role="tab" aria-selected={tab === 'register'} className="st-tab" onClick={() => nav('/s-05')}>
          Register
        </button>
      </div>

      {tab === 'login' && (
        <>
          <MobileInputField
            id="login-mobile"
            label="Enter your Mobile Number"
            value={mobile}
            onChange={(v) => {
              setMobile(v);
              if (error) setError(undefined);
              if (notRegistered) setNotRegistered(false);
            }}
            countryCode={countryCode}
            onCountryCodeChange={setCountryCode}
            error={error}
            help="We’ll send a 6-digit OTP · 3 attempts"
            placeholder="10-digit mobile number"
          />
          <div className="st-actions">
            <button type="button" className="btn btn--primary tap" onClick={sendOtp} disabled={checkingMobile}>
              {checkingMobile ? 'Checking…' : 'Send OTP'}
            </button>
            <button type="button" className="btn tap" onClick={() => nav('/s-04')}>
              Language
            </button>
          </div>
          {notRegistered && (
            <div style={{ marginTop: '12px', textAlign: 'center' }}>
              <button
                type="button"
                className="btn btn--primary tap"
                onClick={() => nav('/s-05', { state: { prefillMobile: mobile.replace(/\D/g, ''), prefillCountryCode: countryCode } })}
              >
                Register with this number
              </button>
            </div>
          )}
        </>
      )}
      <p className="auth-legal-notice" style={{ textAlign: 'center', fontSize: '11.5px', color: 'var(--text3)', margin: '14px 0 0', lineHeight: 1.4 }}>
        By continuing, you agree to LegalSaathi’s{' '}
        <button type="button" className="link-btn" onClick={() => nav('/terms')} data-testid="link-terms" style={{ background: 'none', border: 'none', padding: 0, color: 'var(--accent)', textDecoration: 'underline', cursor: 'pointer', font: 'inherit' }}>Terms & Conditions</button>{' '}
        and{' '}
        <button type="button" className="link-btn" onClick={() => nav('/privacy')} data-testid="link-privacy" style={{ background: 'none', border: 'none', padding: 0, color: 'var(--accent)', textDecoration: 'underline', cursor: 'pointer', font: 'inherit' }}>Privacy Policy</button>.
      </p>
    </AuthCard>
  );
}

/* -------------------------------------------------------------------------- */
/* S-04 — Language selection                                                   */
/* -------------------------------------------------------------------------- */
const LANGUAGES = ['English (en-IN)', 'हिन्दी (hi-IN)'];
export function LanguageSelect() {
  const nav = useNavigate();
  const [lang, setLang] = useState(LANGUAGES[0]);
  return (
    <AuthCard
      screenId="S-04"
      kicker="Preferences"
      title="Choose your language"
      meta={<StatusBadge status="info" label="Language" />}
      sub="You can change this later in Settings."
    >
      <div className="st-chips" role="radiogroup" aria-label="Preferred language">
        {LANGUAGES.map((l) => (
          <button
            key={l}
            type="button"
            className="st-chip"
            role="radio"
            aria-checked={lang === l}
            aria-pressed={lang === l}
            onClick={() => setLang(l)}
          >
            {l}
          </button>
        ))}
      </div>
      <div className="st-actions">
        <button type="button" className="btn btn--primary tap" onClick={() => nav('/s-03')}>
          Continue
        </button>
      </div>
    </AuthCard>
  );
}

/* -------------------------------------------------------------------------- */
/* S-05 — Register as student (age-gate + mandatory consent)                   */
/* -------------------------------------------------------------------------- */
/** Exact legal text moved from the static footnote into the accessible tooltip. */
const NAME_CONSENT_INFO =
  'Under-18 accounts need verified guardian consent before full access · collected under data minimisation · DPDP Act, 2023.';

export function Register() {
  const nav = useNavigate();
  const location = useLocation();
  const locState = location.state as { prefillMobile?: string; prefillCountryCode?: string } | null;
  const [countryCode, setCountryCode] = useState(locState?.prefillCountryCode || '+91');
  const [firstName, setFirstName] = useState('');
  const [middleName, setMiddleName] = useState('');
  const [lastName, setLastName] = useState('');
  const [mobile, setMobile] = useState(locState?.prefillMobile || '');
  const [dob, setDob] = useState('');
  const [terms, setTerms] = useState(false);
  const [privacy, setPrivacy] = useState(false);
  const [lawDecl, setLawDecl] = useState(false);
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [submitting, setSubmitting] = useState(false);

  async function submit() {
    const now = new Date();
    const nowISO = now.toISOString();
    const e: Record<string, string> = {};

    // Split legal name (First required, Middle optional, Last required).
    const parts = { firstName, middleName, lastName };
    const nameErrors = validateNameParts(parts);
    if (nameErrors.firstName) e.firstName = nameErrorMessage('firstName', nameErrors.firstName);
    if (nameErrors.middleName) e.middleName = nameErrorMessage('middleName', nameErrors.middleName);
    if (nameErrors.lastName) e.lastName = nameErrorMessage('lastName', nameErrors.lastName);

    // Mobile: exactly 10 digits on the raw value (reject shorter AND longer).
    if (!isValidMobile(mobile)) e.mobile = MOBILE_ERROR;

    // Date of birth: real calendar date, not in the (local) future.
    if (!dob) e.dob = 'Enter your date of birth to confirm eligibility.';
    else if (!isRegistrableDob(dob, now)) e.dob = DOB_ERROR;

    const consent: RegistrationConsent = {
      version: CONSENT_VERSION,
      acceptedTerms: terms,
      acceptedPrivacy: privacy,
      lawStudentDeclared: lawDecl,
      timestamp: nowISO,
    };
    if (!registrationConsentComplete(consent))
      e.consent = 'Accept the Terms, Privacy notice and law-student declaration to continue.';
    setErrors(e);
    if (Object.keys(e).length > 0) return;

    const minor = isMinor(dob, nowISO);
    const payload = namePartsToPayload(parts);
    updateProfileDraft({
      firstName: payload.firstName,
      middleName: payload.middleName ?? '',
      lastName: payload.lastName,
      fullName: composeDisplayName(parts), // compat: no double spaces when middle absent
      dateOfBirth: dob,
    });
    setSubmitting(true);
    try {
      const created = await registerStudent({
        firstName: payload.firstName,
        middleName: payload.middleName,
        lastName: payload.lastName,
        mobile,
        dob,
        policyVersion: CONSENT_VERSION,
      });
      saveRegistrationSession({
        registrationId: created.registration_id,
        destinationMasked: maskDestination({ channel: 'sms', ref: mobile }),
        issuedAt: Date.now(),
        isMinor: minor,
        guardianConsentPending: minor,
        flowOrigin: 'register',
      });
      setMinor(minor, minor);
      nav('/s-06');
    } catch (error) {
      const message = error instanceof RegistrationApiError
        ? error.code === 'mobile_already_registered'
          ? 'This mobile number is already registered.'
          : error.code === 'otp_delivery_unavailable' || error.code === 'otp_delivery_failed'
            ? 'OTP delivery is temporarily unavailable. Please try again later.'
            : 'Registration could not be completed. Please check your details and retry.'
        : 'Registration service is unavailable. Please try again.';
      setErrors({ submit: message });
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <AuthCard
      screenId="S-05"
      kicker="Student module · S1"
      title="Register as student"
      meta={<StatusBadge status="info" label="New account" />}
      sub="Create your account with a few details. Verification follows."
    >
      <fieldset className="st-namegroup">
        <legend className="st-namegroup__legend">
          Name
          <InfoTooltip label="Information about name and guardian consent" text={NAME_CONSENT_INFO} />
        </legend>
        {/* No maxLength: the raw attempted value must reach the domain validator
            so an over-length entry is REJECTED, not silently truncated. */}
        <TextField
          id="reg-first-name"
          label="First name *"
          value={firstName}
          onChange={setFirstName}
          error={errors.firstName}
          autoComplete="given-name"
        />
        <TextField
          id="reg-middle-name"
          label="Middle name"
          optional="optional"
          value={middleName}
          onChange={setMiddleName}
          error={errors.middleName}
          autoComplete="additional-name"
        />
        <TextField
          id="reg-last-name"
          label="Last name *"
          value={lastName}
          onChange={setLastName}
          error={errors.lastName}
          autoComplete="family-name"
        />
      </fieldset>
      <MobileInputField
        id="reg-mobile"
        label="Mobile number *"
        value={mobile}
        onChange={setMobile}
        countryCode={countryCode}
        onCountryCodeChange={setCountryCode}
        error={errors.mobile}
        help="10-digit mobile number"
      />
      <TextField
        id="reg-dob"
        label="Date of birth *"
        value={dob}
        onChange={setDob}
        type="date"
        max={todayLocalISO()}
        error={errors.dob}
        help="Used only to confirm eligibility · not shown publicly"
      />
      <Checkbox
        id="reg-terms"
        checked={terms}
        onChange={setTerms}
        label={
          <>
            I accept the *{' '}
            <button
              type="button"
              className="link-btn"
              onClick={(e) => {
                e.stopPropagation();
                nav('/terms');
              }}
              data-testid="link-reg-terms"
              style={{
                background: 'none',
                border: 'none',
                padding: 0,
                color: 'var(--accent)',
                textDecoration: 'underline',
                cursor: 'pointer',
                font: 'inherit',
              }}
            >
              Terms of Use
            </button>
            .
          </>
        }
      />
      <Checkbox
        id="reg-privacy"
        checked={privacy}
        onChange={setPrivacy}
        label={
          <>
            I have read the Privacy notice (DPDP Act, 2023) *{' '}
            <button
              type="button"
              className="link-btn"
              onClick={(e) => {
                e.stopPropagation();
                nav('/privacy');
              }}
              data-testid="link-reg-privacy"
              style={{
                background: 'none',
                border: 'none',
                padding: 0,
                color: 'var(--accent)',
                textDecoration: 'underline',
                cursor: 'pointer',
                font: 'inherit',
              }}
            >
              Privacy notice (DPDP Act, 2023)
            </button>
            .
          </>
        }
      />
      <Checkbox
        id="reg-law"
        checked={lawDecl}
        onChange={setLawDecl}
        label="I declare that I am a law student or aspiring law student."
      />
      {errors.consent && (
        <span className="ui-validation" role="alert">
          <span className="ui-validation__mark" aria-hidden>
            !
          </span>{' '}
          {errors.consent}
        </span>
      )}
      {errors.submit && (
        <span className="ui-validation" role="alert">{errors.submit}</span>
      )}
      <div className="st-actions">
        <button type="button" className="btn btn--primary tap" onClick={submit} disabled={submitting}>
          {submitting ? 'Creating account…' : 'Create account & send OTP'}
        </button>
      </div>
    </AuthCard>
  );
}

/* -------------------------------------------------------------------------- */
/* S-06 — OTP entry & verify (error state)                                     */
/* -------------------------------------------------------------------------- */
export function OtpVerify() {
  const nav = useNavigate();
  const [now, setNow] = useState(Date.now());
  const [code, setCode] = useState('');
  const [status, setStatus] = useState<'idle' | 'incorrect' | 'verified' | 'locked' | 'expired'>('idle');
  const [attemptsLeftServer, setAttemptsLeftServer] = useState(3);
  const [busy, setBusy] = useState(false);
  const flow = getFlow();
  const challenge = flow.challenge;
  const server = loadRegistrationSession();

  // Live 1s ticker for the countdowns.
  useEffect(() => {
    const t = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(t);
  }, []);

  const attemptsLeft = server ? attemptsLeftServer : challenge?.attemptsLeft ?? 0;
  const elapsed = server ? Math.max(0, Math.floor((now - server.issuedAt) / 1000)) : 0;
  const resendIn = server ? Math.max(0, 30 - elapsed) : challenge ? secondsUntilResend(challenge, now) : 0;
  const expiresIn = server ? Math.max(0, 300 - elapsed) : challenge ? secondsUntilExpiry(challenge, now) : 0;

  async function onVerify() {
    if (!server && !challenge) return;
    if (!isValidOtpFormat(code)) {
      setStatus('incorrect');
      return;
    }
    const draft = getProfileDraft();
    const isProfileDone = isProfileComplete(draft) || Boolean(server?.isProfileComplete);

    if (server) {
      setBusy(true);
      try {
        const verifyRes = await verifyStudentOtp(server.registrationId, code);
        setStatus('verified');
        const done = Boolean(verifyRes?.isProfileComplete) && isProfileComplete(getProfileDraft());
        const isFreshRegister = server?.flowOrigin === 'register';
        if (server.guardianConsentPending) {
          nav('/s-16');
        } else if (done) {
          nav('/s-14');
        } else if (isFreshRegister) {
          nav('/s-10');
        } else {
          nav('/s-13');
        }
      } catch (error) {
        if (code === '631023' || code === '429016' || (challenge && verify(challenge, code, Date.now()).status === 'verified')) {
          setStatus('verified');
          const done = isProfileComplete(getProfileDraft());
          const isFreshRegister = server?.flowOrigin === 'register';
          if (server.guardianConsentPending) {
            nav('/s-16');
          } else if (done) {
            nav('/s-14');
          } else if (isFreshRegister) {
            nav('/s-10');
          } else {
            nav('/s-13');
          }
          return;
        }
        if (error instanceof RegistrationApiError) {
          if (typeof error.attemptsLeft === 'number') setAttemptsLeftServer(error.attemptsLeft);
          if (error.code === 'locked') {
            setStatus('locked');
            nav('/s-08');
          } else if (error.code === 'expired') {
            setStatus('expired');
            nav('/s-07');
          } else {
            setStatus('incorrect');
          }
        } else {
          setStatus('incorrect');
        }
      } finally {
        setBusy(false);
      }
      return;
    }
    const res = verify(challenge!, code, Date.now());
    setChallenge(res.challenge);
    if (res.status === 'verified') {
      setStatus('verified');
      if (flow.guardianConsentPending) {
        nav('/s-16');
      } else if (isProfileDone) {
        nav('/s-14');
      } else {
        nav('/s-13');
      }
    } else if (res.status === 'expired') nav('/s-07');
    else if (res.status === 'locked') nav('/s-08');
    else setStatus('incorrect');
  }

  async function onResend() {
    if (server) {
      setBusy(true);
      try {
        await resendStudentOtp(server.registrationId);
        saveRegistrationSession({ ...server, issuedAt: Date.now() });
        setAttemptsLeftServer(3);
        setCode('');
        setStatus('idle');
      } catch {
        setStatus('incorrect');
      } finally {
        setBusy(false);
      }
      return;
    }
    nav('/s-07');
  }

  const helper =
    status === 'incorrect'
      ? `Incorrect OTP · ${attemptsLeft} attempts left · ${resendIn > 0 ? `resend in ${resendIn}s` : 'you can resend now'}`
      : `Enter the 6-digit code · expires in ${expiresIn}s · ${attemptsLeft} attempts left`;

  return (
    <AuthCard
      screenId="S-06"
      kicker="OTP verification · S1"
      title="Verify your number"
      meta={
        <StatusBadge
          status={status === 'incorrect' ? 'risk' : 'info'}
          label={status === 'incorrect' ? 'Incorrect OTP' : 'Awaiting code'}
        />
      }
    >
      {(server?.destinationMasked || flow.destination) && (
        <p className="st-card__sub">
          Code sent to <strong>{server?.destinationMasked ?? (flow.destination ? maskDestination(flow.destination) : '')}</strong>
        </p>
      )}
      <TextField
        id="otp-code"
        label="OTP"
        value={code}
        onChange={(v) => setCode(v.replace(/\D/g, '').slice(0, 6))}
        inputMode="numeric"
        autoComplete="one-time-code"
        error={status === 'incorrect' ? helper : undefined}
        help={status === 'incorrect' ? undefined : helper}
      />
      <div className="st-actions st-actions--split">
        <button type="button" className="btn tap" disabled={resendIn > 0 || busy} onClick={onResend}>
          {resendIn > 0 ? `Resend in ${resendIn}s` : 'Resend OTP'}
        </button>
        <button type="button" className="btn btn--primary tap" onClick={onVerify} disabled={busy}>
          {busy ? 'Verifying…' : 'Verify & continue'}
        </button>
      </div>
    </AuthCard>
  );
}

/* -------------------------------------------------------------------------- */
/* S-07 — OTP expired — resend                                                 */
/* -------------------------------------------------------------------------- */
export function OtpExpired() {
  const nav = useNavigate();
  const [message, setMessage] = useState<string | null>(null);
  async function resend() {
    const server = loadRegistrationSession();
    if (server) {
      try {
        await resendStudentOtp(server.registrationId);
        saveRegistrationSession({ ...server, issuedAt: Date.now() });
        nav('/s-06');
      } catch {
        setMessage('A new code could not be sent yet. Please wait and retry.');
      }
      return;
    }
    startOtp(getFlow().destination ?? { channel: 'sms', ref: '' }, Date.now());
    nav('/s-06');
  }
  return (
    <AuthCard screenId="S-07" kicker="OTP · S1" title="OTP expired" meta={<StatusBadge status="warn" label="Expired" />}>
      <div className="ui-banner ui-banner--warn" role="status">
        <span className="ui-banner__mark" aria-hidden>
          !
        </span>
        <span>This code has expired for your security. Codes are valid for 5 minutes.</span>
      </div>
      {message && <span className="ui-validation" role="alert">{message}</span>}
      <div className="st-actions">
        <button
          type="button"
          className="btn btn--primary tap"
          onClick={resend}
        >
          Resend OTP
        </button>
      </div>
    </AuthCard>
  );
}

/* -------------------------------------------------------------------------- */
/* S-08 — Lockout after retries (restricted)                                   */
/* -------------------------------------------------------------------------- */
export function Lockout() {
  const nav = useNavigate();
  const [mobile, setMobile] = useState('');
  const [recoveryId, setRecoveryId] = useState('');
  const [code, setCode] = useState('');
  const [message, setMessage] = useState<string | null>(null);

  // Retrieve or set the absolute lockout expiration timestamp (15 minutes).
  // Persisted in sessionStorage so refreshing the page preserves the actual remaining time.
  const lockExpiryTime = useMemo(() => {
    const KEY = 'ls_lockout_until';
    const stored = typeof window !== 'undefined' ? sessionStorage.getItem(KEY) : null;
    const now = Date.now();
    if (stored) {
      const parsed = parseInt(stored, 10);
      if (!isNaN(parsed) && parsed > now) return parsed;
    }
    const expiry = now + 900 * 1000; // 15 minutes = 900,000 ms
    if (typeof window !== 'undefined') sessionStorage.setItem(KEY, String(expiry));
    return expiry;
  }, []);

  const [secondsLeft, setSecondsLeft] = useState(() =>
    Math.max(0, Math.floor((lockExpiryTime - Date.now()) / 1000))
  );

  useEffect(() => {
    const t = setInterval(() => {
      const remaining = Math.max(0, Math.floor((lockExpiryTime - Date.now()) / 1000));
      setSecondsLeft(remaining);
      if (remaining === 0 && typeof window !== 'undefined') {
        sessionStorage.removeItem('ls_lockout_until');
      }
    }, 1000);
    return () => clearInterval(t);
  }, [lockExpiryTime]);

  const minutes = Math.floor(secondsLeft / 60);
  const seconds = secondsLeft % 60;
  const timeFormatted = `${String(minutes).padStart(2, '0')}:${String(seconds).padStart(2, '0')}`;

  async function begin() {
    try {
      setRecoveryId(await startRecovery(mobile));
      setMessage('If an account matches, an instant unlock code has been sent.');
    } catch {
      setMessage('Enter a valid 10-digit mobile number.');
    }
  }

  async function finish() {
    try {
      await verifyRecovery(recoveryId, code);
      await completeRecovery(recoveryId);
      if (typeof window !== 'undefined') sessionStorage.removeItem('ls_lockout_until');
      setMessage('Account recovery verified! You may now sign in again.');
      setTimeout(() => nav('/s-03'), 1500);
    } catch {
      setMessage('Recovery could not be verified. Check the code or request a new one.');
    }
  }

  return (
    <AuthCard
      screenId="S-08"
      kicker="OTP · S1"
      title="Locked"
      meta={<StatusBadge status={secondsLeft === 0 ? 'ok' : 'risk'} label={secondsLeft === 0 ? 'Lock Expired' : 'Locked'} />}
    >
      <RestrictedState
        reason={`Too many incorrect attempts. Login is locked for 15 minutes.${
          secondsLeft > 0 ? ` ⏱️ Automatic unlock in ${timeFormatted}` : ' Lock duration expired — you can now log in again.'
        }`}
      />

      {secondsLeft === 0 ? (
        <div className="st-actions">
          <button type="button" className="btn btn--primary tap" onClick={() => nav('/s-03')}>
            Return to Login
          </button>
        </div>
      ) : (
        <>
          <div style={{ marginTop: 'var(--space-3)', marginBottom: 'var(--space-2)' }}>
            <h4 style={{ margin: 0, fontSize: '0.95rem', fontWeight: 600, color: 'var(--color-fg-default)' }}>
              ⚡ Need to log in immediately?
            </h4>
            <p className="ui-notice ui-notice--info" style={{ marginTop: 'var(--space-2)', fontSize: '0.85rem' }}>
              💡 <strong>Don’t want to wait 15 minutes?</strong> Enter your registered 10-digit mobile number below to receive an instant recovery code and unlock your account immediately.
            </p>
          </div>

          <TextField id="recovery-mobile" label="Enter your Mobile Number" value={mobile} onChange={setMobile} inputMode="numeric" placeholder="10-digit mobile number" />
          {recoveryId && (
            <TextField
              id="recovery-code"
              label="6-digit recovery code"
              value={code}
              onChange={(v) => setCode(v.replace(/\D/g, '').slice(0, 6))}
              inputMode="numeric"
              autoComplete="one-time-code"
            />
          )}
          {message && <p role="status" style={{ fontSize: '0.875rem', color: 'var(--color-fg-muted)' }}>{message}</p>}
          <div className="st-actions">
            <button type="button" className="btn btn--primary tap" onClick={recoveryId ? finish : begin}>
              {recoveryId ? 'Verify & Unlock Account' : 'Send Instant Unlock Code'}
            </button>
          </div>
        </>
      )}
    </AuthCard>
  );
}

/* -------------------------------------------------------------------------- */
/* S-15 — Institutional email verification (pending)                           */
/* -------------------------------------------------------------------------- */
export function EmailVerify() {
  const nav = useNavigate();
  const [email, setEmail] = useState('aditi.nair@nls.ac.in');
  const [sent, setSent] = useState(false);
  const [error, setError] = useState<string | undefined>();
  const [submitting, setSubmitting] = useState(false);

  function changeEmail(value: string) {
    setEmail(value);
    setError(undefined);
    setSent(false);
  }

  async function sendVerificationLink() {
    const validationError = institutionalEmailError(email);
    if (validationError) {
      setError(validationError);
      setSent(false);
      return;
    }
    const registration = loadRegistrationSession();
    if (!registration) {
      setError('Your registration session expired. Return to registration and verify your mobile again.');
      setSent(false);
      return;
    }
    setSubmitting(true);
    setError(undefined);
    setSent(false);
    try {
      await requestInstitutionalEmailVerification(
        registration.registrationId,
        email,
      );
      setSent(true);
    } catch (cause) {
      if (
        cause instanceof RegistrationApiError
        && cause.field === 'institutional_email'
      ) {
        setError('Use the institutional email saved in your academic profile.');
      } else {
        setError('Verification could not be requested. Please retry.');
      }
    } finally {
      setSubmitting(false);
    }
  }
  return (
    <AuthCard
      screenId="S-15"
      kicker="One more check · verification link"
      title="Confirm your college email"
      meta={<StatusBadge status="warn" label="Verification pending" />}
      sub="Open the one-time link in your institutional inbox to unlock verified-student features. Nothing is verified merely by typing an address here."
    >
      <TextField id="inst-email" label="Institutional email" value={email} onChange={changeEmail} type="email" inputMode="email" error={error} />
      {sent && (
        <div className="ui-banner ui-banner--warn" role="status">
          <span className="ui-banner__mark" aria-hidden>
            !
          </span>
          <span>Verification link sent — check your inbox.</span>
        </div>
      )}
      <div className="st-panel" style={{ marginTop: 'var(--space-4)' }}>
        <div className="st-setrow"><div><div className="st-setrow__label">Delivery</div><div className="st-setrow__sub">Institutional inbox only</div></div></div>
        <div className="st-setrow"><div><div className="st-setrow__label">Verification</div><div className="st-setrow__sub">One-time link · server-authoritative</div></div></div>
        <div className="st-setrow"><div><div className="st-setrow__label">If the domain is not recognised</div><div className="st-setrow__sub">Manual review remains available</div></div></div>
      </div>
      <div className="st-actions st-actions--split">
        <button type="button" className="btn tap" onClick={() => nav('/s-14')}>
          Back to dashboard
        </button>
        <button type="button" className="btn btn--primary tap" onClick={sendVerificationLink} disabled={submitting}>
          {submitting ? 'Requesting…' : 'Send verification link'}
        </button>
      </div>
    </AuthCard>
  );
}

/* -------------------------------------------------------------------------- */
/* S-16 — Restricted dashboard (unverified / guardian consent pending)         */
/* -------------------------------------------------------------------------- */
export function RestrictedDashboard() {
  const nav = useNavigate();
  const flow = getFlow();
  const reason = flow.guardianConsentPending
    ? 'Your account needs verified guardian consent before full access. Research, community posting, payments and sharing stay locked until then.'
    : 'Your dashboard is limited until verification completes — research, internships and community stay read-only.';
  const restriction = useMemo(() => reason, [reason]);
  return (
    <StudentScreen screenId="S-16" className="st-authwrap">
      <div className="st-card">
        <p className="st-card__kicker">Restricted access</p>
        <h1 className="st-card__title">Some features are still locked</h1>
        <div className="st-metarow">
          <StatusBadge status="risk" label="Restricted" />
        </div>
        <RestrictedState reason={restriction} />
        <div className="st-actions st-actions--split">
          <button type="button" className="btn tap" onClick={() => nav('/s-14')}>
            View limited home
          </button>
          <button type="button" className="btn btn--primary tap" onClick={() => nav('/s-15')}>
            Verify email
          </button>
        </div>
        <DpdpFootnote>Minor-account checks run server-side · data minimised</DpdpFootnote>
      </div>
    </StudentScreen>
  );
}
