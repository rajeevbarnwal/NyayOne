import { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { AuthCard, TextField, Checkbox, DpdpFootnote, InfoTooltip } from '../components';
import {
  isValidMobile, MOBILE_ERROR,
  isRegistrableDob, DOB_ERROR, todayLocalISO,
  validateNameParts, nameErrorMessage, namePartsToPayload,
} from '../lib/registration';
import { ErrorState, RestrictedState, PendingVerificationState, LoadingState, StatusBadge, ValidationState } from '../../../components/ui/primitives';
import { isValidOtpInput } from '../lib/otpInput';
import {
  registrationConsentComplete,
  CONSENT_VERSION,
  PRIVACY_NOTICE_VERSION,
  TERMS_VERSION,
  type RegistrationConsent,
} from '../lib/consent';
import { useAuth } from '../../../app/authContext';
import {
  RegistrationApiError,
  getStudentSession,
  registerStudent,
  resendStudentOtp,
  startLoginOtp,
  startRecovery,
  verifyLoginOtp,
  verifyRecovery,
  verifyStudentOtp,
  completeRecovery,
} from '../lib/registrationApi';
import { useOtpFlowState } from '../lib/useOtpFlowState';
import { profileErrorMessage } from '../lib/profileApi';
import {
  useRequestInstitutionalEmailVerification,
  useStudentProfileProjection,
} from '../profile/profileHooks';
import { resolvedProfileReauthResumeRoute } from '../profile/profileReauthHandoff';
import { EmailVerificationFrame, EmailVerificationView } from './EmailVerificationView';
import { GuardianConsentFrame, GuardianConsentView } from './GuardianConsentView';

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
    <AuthCard screenId="S-01" kicker="Student module · S1" title="NyayOne" brand>
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
  const [mobile, setMobile] = useState('');
  const [error, setError] = useState<string | undefined>();
  const [busy, setBusy] = useState(false);

  async function sendOtp() {
    const digits = mobile.replace(/\D/g, '');
    if (digits.length !== 10) {
      setError('Enter a valid 10-digit mobile number.');
      return;
    }
    setError(undefined);
    setBusy(true);
    try {
      await startLoginOtp(digits);
      nav('/s-06');
    } catch {
      setError('A one-time code could not be requested. Please retry.');
    } finally {
      setBusy(false);
    }
  }

  return (
    <AuthCard screenId="S-03" kicker="Student module · S1" title="NyayOne" brand>
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
            help="We’ll send a 6-digit OTP. The server controls the attempt limit."
          />
          <div className="st-actions">
            <button type="button" className="btn btn--primary tap" onClick={sendOtp} disabled={busy}>
              {busy ? 'Sending…' : 'Send OTP'}
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
/** Exact legal text moved from the static footnote into the accessible tooltip. */
const NAME_CONSENT_INFO =
  'Under-18 accounts need verified guardian consent before full access · collected under data minimisation · DPDP Act, 2023.';

export function Register() {
  const nav = useNavigate();
  const [firstName, setFirstName] = useState('');
  const [middleName, setMiddleName] = useState('');
  const [lastName, setLastName] = useState('');
  const [mobile, setMobile] = useState('');
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

    const payload = namePartsToPayload(parts);
    setSubmitting(true);
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
      nav('/s-06');
    } catch {
      setErrors({
        submit: 'Registration or code delivery could not be completed. Check your details or try again later.',
      });
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
          label="First name"
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
          label="Last name"
          value={lastName}
          onChange={setLastName}
          error={errors.lastName}
          autoComplete="family-name"
        />
      </fieldset>
      <TextField
        id="reg-mobile"
        label="Mobile number"
        value={mobile}
        onChange={setMobile}
        type="text"
        inputMode="numeric"
        autoComplete="tel"
        error={errors.mobile}
        help="10-digit mobile number"
      />
      <TextField
        id="reg-dob"
        label="Date of birth"
        value={dob}
        onChange={setDob}
        type="date"
        max={todayLocalISO()}
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
  const [code, setCode] = useState('');
  const [status, setStatus] = useState<'idle' | 'incorrect' | 'verified' | 'locked' | 'expired'>('idle');
  const [busy, setBusy] = useState(false);
  const otpFlow = useOtpFlowState();
  const flow = otpFlow.state;
  const attemptsLeft = flow?.attemptsLeft;
  const resendIn = flow?.resendInSeconds ?? 0;
  const expiresIn = flow?.expiresInSeconds ?? 0;

  useEffect(() => {
    if (!otpFlow.loadError) return;
    setCode('');
    setStatus('idle');
    setBusy(false);
  }, [otpFlow.loadError]);

  function captureFailure(error: unknown) {
    if (error instanceof RegistrationApiError && error.otpState) {
      otpFlow.adopt(error.otpState);
    }
    if (error instanceof RegistrationApiError && ['locked', 'otp_locked'].includes(error.code)) {
      setStatus('locked');
    } else if (error instanceof RegistrationApiError && ['expired', 'otp_expired'].includes(error.code)) {
      setStatus('expired');
    } else {
      setStatus('incorrect');
    }
  }

  async function onVerify() {
    if (!isValidOtpInput(code)) {
      setStatus('incorrect');
      return;
    }
    if (flow?.status !== 'pending' || (flow.purpose !== 'signup' && flow.purpose !== 'login')) {
      setStatus('expired');
      return;
    }
    setBusy(true);
    const purpose = flow.purpose;
    try {
      const result = purpose === 'signup'
        ? await verifyStudentOtp(code)
        : await verifyLoginOtp(code);
      otpFlow.adopt(result);
      setStatus('verified');
      if (purpose === 'login') {
        nav(resolvedProfileReauthResumeRoute() ?? '/s-14', { replace: true });
      } else {
        const actor = await getStudentSession();
        nav(actor?.is_minor ? '/s-16' : '/s-09');
      }
    } catch (error) {
      captureFailure(error);
    } finally {
      setBusy(false);
    }
  }

  async function onResend() {
    if (flow?.status !== 'pending' || !flow.resendAllowed) return;
    setBusy(true);
    try {
      otpFlow.adopt(await resendStudentOtp());
      setCode('');
      setStatus('idle');
    } catch (error) {
      captureFailure(error);
    } finally {
      setBusy(false);
    }
  }

  const helper =
    status === 'locked'
      ? `Verification is locked${flow?.lockedForSeconds === null || flow?.lockedForSeconds === undefined ? '' : ` for ${flow.lockedForSeconds}s`}.`
      : status === 'expired'
        ? 'This code is no longer available. Request a new code when the server allows it.'
        : status === 'incorrect'
          ? `Incorrect OTP · ${attemptsLeft ?? '—'} attempts left · ${flow?.resendAllowed ? 'you can resend now' : `resend in ${resendIn}s`}`
          : `Enter the 6-digit code · expires in ${expiresIn}s · ${attemptsLeft ?? '—'} attempts left`;

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
      {flow?.destinationMasked && (
        <p className="st-card__sub">
          Code sent to <strong>{flow.destinationMasked}</strong>
        </p>
      )}
      {otpFlow.loading && <LoadingState label="Restoring verification state…" />}
      {otpFlow.loadError && <ValidationState message="Verification state is unavailable. Retry before continuing." />}
      <TextField
        id="otp-code"
        label="OTP"
        value={code}
        onChange={(v) => setCode(v.replace(/\D/g, '').slice(0, 6))}
        inputMode="numeric"
        autoComplete="one-time-code"
        error={status === 'incorrect' || status === 'locked' || status === 'expired' ? helper : undefined}
        help={status === 'incorrect' || status === 'locked' || status === 'expired' ? undefined : helper}
      />
      <div className="st-actions st-actions--split">
        <button type="button" className="btn tap" disabled={!flow?.resendAllowed || busy} onClick={onResend}>
          {flow?.resendAllowed ? 'Resend OTP' : `Resend in ${resendIn}s`}
        </button>
        <button type="button" className="btn btn--primary tap" onClick={onVerify} disabled={busy || flow?.status !== 'pending' || (flow.lockedForSeconds ?? 0) > 0}>
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
  const otpFlow = useOtpFlowState();
  async function resend() {
    if (otpFlow.state?.status !== 'pending' || !otpFlow.state.resendAllowed) return;
    try {
      otpFlow.adopt(await resendStudentOtp());
      nav('/s-06');
    } catch (error) {
      if (error instanceof RegistrationApiError && error.otpState) {
        otpFlow.adopt(error.otpState);
      }
      setMessage('A new code could not be sent yet. Follow the server countdown and retry.');
    }
  }
  return (
    <AuthCard screenId="S-07" kicker="OTP · S1" title="OTP expired" meta={<StatusBadge status="warn" label="Expired" />}>
      <div className="ui-banner ui-banner--warn" role="status">
        <span className="ui-banner__mark" aria-hidden>
          !
        </span>
        <span>This code has expired for your security. The server controls each code’s lifetime.</span>
      </div>
      {message && <span className="ui-validation" role="alert">{message}</span>}
      <div className="st-actions">
        <button
          type="button"
          className="btn btn--primary tap"
          onClick={resend}
          disabled={!otpFlow.state?.resendAllowed}
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
  const [mobile, setMobile] = useState('');
  const [code, setCode] = useState('');
  const [message, setMessage] = useState<string | null>(null);
  const otpFlow = useOtpFlowState();
  const recoveryPending = otpFlow.state?.status === 'pending'
    && otpFlow.state.purpose === 'recovery';
  useEffect(() => {
    if (!otpFlow.loadError) return;
    setCode('');
    setMessage('Recovery state is unavailable. Wait for a successful server state check.');
  }, [otpFlow.loadError]);
  async function begin() {
    try {
      otpFlow.adopt(await startRecovery(mobile));
      setMessage('If an account matches, a recovery code has been sent.');
    } catch {
      setMessage('Enter a valid 10-digit mobile number.');
    }
  }
  async function finish() {
    try {
      otpFlow.adopt(await verifyRecovery(code));
      otpFlow.adopt(await completeRecovery());
      setMessage('Recovery verified. You may now sign in again.');
    } catch (error) {
      if (error instanceof RegistrationApiError && error.otpState) {
        otpFlow.adopt(error.otpState);
      }
      setMessage('Recovery could not be verified. Check the code or request a new one.');
    }
  }
  return (
    <AuthCard screenId="S-08" kicker="OTP · S1" title="Locked" meta={<StatusBadge status="risk" label="Locked" />}>
      <RestrictedState reason={otpFlow.state?.lockedForSeconds === null || otpFlow.state?.lockedForSeconds === undefined
        ? 'Too many incorrect attempts. Verification is temporarily locked.'
        : `Too many incorrect attempts. Verification is locked for ${otpFlow.state.lockedForSeconds} seconds.`} />
      <TextField id="recovery-mobile" label="Mobile number" value={mobile} onChange={setMobile} inputMode="numeric" />
      {recoveryPending && <TextField id="recovery-code" label="6-digit recovery code" value={code} onChange={(v) => setCode(v.replace(/\D/g, '').slice(0, 6))} inputMode="numeric" autoComplete="one-time-code" />}
      {otpFlow.loadError && <ValidationState message="Recovery state is unavailable. Retry after the server state check recovers." />}
      {message && <p role="status">{message}</p>}
      <div className="st-actions">
        <button type="button" className="btn tap" disabled={otpFlow.loadError} onClick={recoveryPending ? finish : begin}>
          {recoveryPending ? 'Verify recovery code' : 'Start account recovery'}
        </button>
      </div>
    </AuthCard>
  );
}

/* -------------------------------------------------------------------------- */
/* S-15 — Institutional email verification (pending)                           */
/* -------------------------------------------------------------------------- */
export function EmailVerify() {
  const profile = useStudentProfileProjection();
  const requestVerification = useRequestInstitutionalEmailVerification();
  if (!profile.data) {
    return <EmailVerificationFrame>{profile.isPending ? <LoadingState label="Loading verification status…" /> : <ErrorState title="Could not load verification status" detail={profileErrorMessage(profile.error)} onRetry={() => { void profile.refetch(); }} />}</EmailVerificationFrame>;
  }
  return <EmailVerificationView projection={profile.data} pending={requestVerification.isPending}
    errorMessage={requestVerification.error ? profileErrorMessage(requestVerification.error) : null}
    requestSucceeded={requestVerification.isSuccess} request={() => requestVerification.mutate()} />;
}

/* -------------------------------------------------------------------------- */
/* S-16 — Restricted dashboard (unverified / guardian consent pending)         */
/* -------------------------------------------------------------------------- */
export function RestrictedDashboard() {
  const nav = useNavigate();
  const profile = useStudentProfileProjection();
  useEffect(() => {
    if (profile.data?.accessMode === 'full') nav('/s-14', { replace: true });
  }, [nav, profile.data]);
  if (!profile.data || profile.data.accessMode === 'full') {
    return <GuardianConsentFrame title="Checking account access.">{profile.isPending || profile.data ? <LoadingState label="Checking access…" /> : <ErrorState title="Could not check access" detail={profileErrorMessage(profile.error)} onRetry={() => { void profile.refetch(); }} />}</GuardianConsentFrame>;
  }
  return <GuardianConsentView projection={profile.data} />;
}
