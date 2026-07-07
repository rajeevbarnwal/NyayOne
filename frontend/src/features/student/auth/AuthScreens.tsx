import { useEffect, useMemo, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { AuthCard, TextField, Checkbox, DpdpFootnote, StudentScreen } from '../components';
import { RestrictedState, PendingVerificationState, LoadingState, StatusBadge } from '../../../components/ui/primitives';
import {
  isValidOtpFormat,
  verify,
  secondsUntilResend,
  secondsUntilExpiry,
  maskDestination,
  type OtpChannel,
} from '../lib/otp';
import { startOtp, getFlow, setChallenge, setMinor, STUB_OTP_CODE } from '../lib/authFlow';
import { isMinor, registrationConsentComplete, CONSENT_VERSION, type RegistrationConsent } from '../lib/consent';
import { isReviewerMode } from '../../../components/shell/TraceabilityBanner';

/* -------------------------------------------------------------------------- */
/* S-01 — Splash / session check (loading)                                     */
/* -------------------------------------------------------------------------- */
export function Splash() {
  const nav = useNavigate();
  return (
    <AuthCard screenId="S-01" kicker="Student module · S1" title="LegalSaathi" brand>
      <LoadingState label="Checking your session…" />
      <div className="st-actions">
        <button type="button" className="btn btn--primary tap" onClick={() => nav('/s-03')}>
          Continue
        </button>
      </div>
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
  const [mobile, setMobile] = useState('');
  const [error, setError] = useState<string | undefined>();

  function sendOtp() {
    const digits = mobile.replace(/\D/g, '');
    if (digits.length < 10) {
      setError('Enter a valid 10-digit mobile number.');
      return;
    }
    setError(undefined);
    startOtp({ channel: 'sms' as OtpChannel, ref: digits }, Date.now());
    setMinor(false, false);
    nav('/s-06');
  }

  return (
    <AuthCard screenId="S-03" kicker="Student module · S1" title="LegalSaathi" brand>
      <div className="st-tabs" role="tablist" aria-label="Login or register">
        <button role="tab" aria-selected={tab === 'login'} className="st-tab" onClick={() => setTab('login')}>
          Login
        </button>
        <button role="tab" aria-selected={tab === 'register'} className="st-tab" onClick={() => nav('/s-05')}>
          Register as student
        </button>
      </div>

      {tab === 'login' && (
        <>
          <TextField
            id="login-mobile"
            label="Mobile number"
            value={mobile}
            onChange={setMobile}
            type="tel"
            inputMode="tel"
            autoComplete="tel"
            placeholder="+91 ‑ 10 digit mobile"
            error={error}
            help="We’ll send a 6-digit OTP · 3 attempts"
          />
          <div className="st-actions">
            <button type="button" className="btn btn--primary tap" onClick={sendOtp}>
              Send OTP
            </button>
            <button type="button" className="btn tap" onClick={() => nav('/s-04')}>
              Language
            </button>
          </div>
          <div style={{ marginTop: 'var(--space-4)' }}>
            <PendingVerificationState kind="student" />
          </div>
        </>
      )}
      <DpdpFootnote>Privacy notice shown before registration · no PII in analytics</DpdpFootnote>
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
export function Register() {
  const nav = useNavigate();
  const [name, setName] = useState('');
  const [mobile, setMobile] = useState('');
  const [dob, setDob] = useState('');
  const [terms, setTerms] = useState(false);
  const [privacy, setPrivacy] = useState(false);
  const [lawDecl, setLawDecl] = useState(false);
  const [errors, setErrors] = useState<Record<string, string>>({});

  function submit() {
    const nowISO = new Date().toISOString();
    const e: Record<string, string> = {};
    if (!name.trim()) e.name = 'Enter your full name.';
    if (mobile.replace(/\D/g, '').length < 10) e.mobile = 'Enter a valid 10-digit mobile number.';
    if (!dob) e.dob = 'Enter your date of birth to confirm eligibility.';
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
    startOtp({ channel: 'sms' as OtpChannel, ref: mobile.replace(/\D/g, '') }, Date.now());
    setMinor(minor, minor); // guardian consent pending until verified server-side
    // Minors continue through OTP but land in a restricted state (S-16) until
    // guardian consent is verified. All enforcement is server-side.
    nav('/s-06');
  }

  return (
    <AuthCard
      screenId="S-05"
      kicker="Student module · S1"
      title="Register as student"
      meta={<StatusBadge status="info" label="New account" />}
      sub="Create your account with a few details. Verification follows."
    >
      <TextField id="reg-name" label="Full name" value={name} onChange={setName} error={errors.name} autoComplete="name" />
      <TextField
        id="reg-mobile"
        label="Mobile number"
        value={mobile}
        onChange={setMobile}
        type="tel"
        inputMode="tel"
        autoComplete="tel"
        error={errors.mobile}
      />
      <TextField
        id="reg-dob"
        label="Date of birth"
        value={dob}
        onChange={setDob}
        type="date"
        error={errors.dob}
        help="Used only to confirm eligibility · not shown publicly"
      />
      <Checkbox id="reg-terms" checked={terms} onChange={setTerms} label="I accept the Terms of Use." />
      <Checkbox id="reg-privacy" checked={privacy} onChange={setPrivacy} label="I have read the Privacy notice (DPDP Act, 2023)." />
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
      <div className="st-actions">
        <button type="button" className="btn btn--primary tap" onClick={submit}>
          Create account &amp; send OTP
        </button>
      </div>
      <DpdpFootnote>
        Under-18 accounts need verified guardian consent before full access · collected under data minimisation
      </DpdpFootnote>
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
  const [status, setStatus] = useState<'idle' | 'incorrect' | 'verified'>('idle');
  const flow = getFlow();
  const challenge = flow.challenge;

  // Live 1s ticker for the countdowns.
  useEffect(() => {
    const t = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(t);
  }, []);

  const attemptsLeft = challenge?.attemptsLeft ?? 0;
  const resendIn = challenge ? secondsUntilResend(challenge, now) : 0;
  const expiresIn = challenge ? secondsUntilExpiry(challenge, now) : 0;

  function onVerify() {
    if (!challenge) return;
    if (!isValidOtpFormat(code)) {
      setStatus('incorrect');
      return;
    }
    const res = verify(challenge, code, Date.now());
    setChallenge(res.challenge);
    if (res.status === 'verified') {
      setStatus('verified');
      // Minors route to the restricted state until guardian consent clears.
      nav(flow.guardianConsentPending ? '/s-16' : '/s-09');
    } else if (res.status === 'expired') {
      nav('/s-07');
    } else if (res.status === 'locked') {
      nav('/s-08');
    } else {
      setStatus('incorrect');
    }
  }

  const helper =
    status === 'incorrect'
      ? `Incorrect code · ${attemptsLeft} attempts left · ${resendIn > 0 ? `resend in ${resendIn}s` : 'you can resend now'}`
      : `Enter the 6-digit code · expires in ${expiresIn}s · ${attemptsLeft} attempts left`;

  return (
    <AuthCard
      screenId="S-06"
      kicker="OTP verification · S1"
      title="Verify your number"
      meta={
        <StatusBadge
          status={status === 'incorrect' ? 'risk' : 'info'}
          label={status === 'incorrect' ? 'Incorrect code' : 'Awaiting code'}
        />
      }
    >
      {flow.destination && (
        <p className="st-card__sub">
          Code sent to <strong>{maskDestination(flow.destination)}</strong>
        </p>
      )}
      <div className="st-otp" aria-hidden>
        {Array.from({ length: 6 }).map((_, k) => (
          <span key={k}>{code[k] ?? '•'}</span>
        ))}
      </div>
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
      {isReviewerMode() && (
        <p className="st-field__help">Reviewer stub code: {STUB_OTP_CODE}</p>
      )}
      <div className="st-actions st-actions--split">
        <button type="button" className="btn tap" disabled={resendIn > 0} onClick={() => nav('/s-07')}>
          {resendIn > 0 ? `Resend in ${resendIn}s` : 'Resend OTP'}
        </button>
        <button type="button" className="btn btn--primary tap" onClick={onVerify}>
          Verify &amp; continue
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
  return (
    <AuthCard screenId="S-07" kicker="OTP · S1" title="OTP expired" meta={<StatusBadge status="warn" label="Expired" />}>
      <div className="ui-banner ui-banner--warn" role="status">
        <span className="ui-banner__mark" aria-hidden>
          !
        </span>
        <span>This code has expired for your security. Codes are valid for 5 minutes.</span>
      </div>
      <div className="st-actions">
        <button
          type="button"
          className="btn btn--primary tap"
          onClick={() => {
            startOtp(getFlow().destination ?? { channel: 'sms', ref: '' }, Date.now());
            nav('/s-06');
          }}
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
  return (
    <AuthCard screenId="S-08" kicker="OTP · S1" title="Locked" meta={<StatusBadge status="risk" label="Locked" />}>
      <RestrictedState reason="Too many incorrect attempts. Login is locked for 15 minutes." />
      <div className="st-actions">
        <button type="button" className="btn tap" onClick={() => nav('/s-15')}>
          Reset via email
        </button>
      </div>
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
  return (
    <AuthCard
      screenId="S-15"
      kicker="Verification"
      title="Institutional email · NLU verification"
      meta={<StatusBadge status="warn" label="Verification pending" />}
      sub="Confirm from your NLU inbox to unlock verified-student features. Manual review if the domain is unrecognised."
    >
      <TextField id="inst-email" label="Institutional email" value={email} onChange={setEmail} type="email" inputMode="email" />
      {sent && (
        <div className="ui-banner ui-banner--warn" role="status">
          <span className="ui-banner__mark" aria-hidden>
            !
          </span>
          <span>Verification link sent — check your inbox.</span>
        </div>
      )}
      <div className="st-actions st-actions--split">
        <button type="button" className="btn tap" onClick={() => nav('/s-14')}>
          Back to dashboard
        </button>
        <button type="button" className="btn btn--primary tap" onClick={() => setSent(true)}>
          Send verification link
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
        <h1 className="st-card__title">Restricted</h1>
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
