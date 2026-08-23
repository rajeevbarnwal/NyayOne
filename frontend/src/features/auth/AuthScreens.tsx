import { useEffect, useMemo, useState } from 'react';
import { TextField, SelectField, Checkbox, DpdpFootnote, InfoTooltip } from '../student/components';
import {
  isValidMobile, MOBILE_ERROR,
  isRegistrableDob, DOB_ERROR, todayLocalISO,
  buildStudentRegistrationCommand,
} from '../student/lib/registration';
import { StatusBadge, GuardrailNotice, PrivacyNotice, RestrictedState, ValidationState, EmptyState } from '../../components/ui/primitives';
import { Workbench, type WorkbenchStep, type Requirement, type LedgerEntry } from './Workbench';
import {
  createChallenge, verify as otpVerify, resend as otpResend, isLocked, secondsUntilExpiry, secondsUntilResend,
  maskDestination, type OtpChallenge,
} from '../student/lib/otp';
import { STUB_OTP_CODE } from '../student/lib/authFlow';
import {
  RegistrationApiError,
  clearRegistrationSession,
  getOtpFlowState,
  registerStudent,
  resendStudentOtp,
  verifyStudentOtp,
} from '../student/lib/registrationApi';
import { useOtpFlowState } from '../student/lib/useOtpFlowState';
import { PRIVACY_NOTICE_VERSION, TERMS_VERSION } from '../student/lib/consent';
import {
  nextPhase, redactChallenge, AUTH_PHASE_LABELS, type AuthPhase, type AuthRole, type AuthSnapshot,
} from './lib/authLifecycle';
import { saveAuthSnapshot, loadAuthSnapshot, clearAuthSnapshot } from './lib/authPersistence';
import {
  validateLawyerProfile, EMPTY_LAWYER_PROFILE, createStubEnrolmentSource, runEnrolmentCheck,
  canAccessLawyerFeatures, lawyerGateReason, LAWYER_VERIFICATION_STATUS_LABELS, STATE_BAR_COUNCILS,
  ENROLMENT_STATUS_ONLY_NOTICE, BCI_PROFILE_DISPLAY_ENABLED, type LawyerProfile, type VerificationRecord,
} from './lib/lawyerVerify';
import {
  validateStudentVerify, EMPTY_STUDENT_VERIFY, decideStudentVerification, minorContextFromDob,
  proFeaturesUnlocked, studentGateReason, STUDENT_VERIFICATION_STATUS_LABELS, VERIFY_METHOD_LABELS,
  DPDP_MINIMISATION_NOTICE, type VerifyMethod, type StudentVerifyInput, type StudentVerificationRecord,
} from './lib/studentVerify';
import { guardianConsentSatisfied, type GuardianConsent } from '../student/lib/consent';
import {
  DEFAULT_SESSION_POLICY, issueSession, refreshSession, revokeSession, requiresReauth, markReauthenticated,
  revokeDevice, revokeAllOtherDevices, expiryWarning, isUnusualLogin, FRESH_ATTEMPTS, isLockedOut, registerFailure,
  registerSuccess, securityEvent, biometricCapability, SECURITY_EVENT_LABELS, type DeviceRecord, type SecurityAuditEvent, type Session,
} from './lib/session';

const chip = (k: 'ok' | 'warn' | 'risk' | 'info') => k;
const nowISO = () => new Date().toISOString();
const statusChip = (s: string) => (s === 'verified' ? chip('ok') : s === 'rejected' ? chip('risk') : s === 'manual_review' ? chip('warn') : chip('info'));

/** Compute rail step states from an ordered list + the active step key. */
function stepStates(order: readonly { key: string; label: string }[], activeIdx: number): WorkbenchStep[] {
  return order.map((s, i) => ({ key: s.key, label: s.label, state: i < activeIdx ? 'done' : i === activeIdx ? 'active' : 'todo' }));
}

/* -------------------------------------------------------------------------- */
/* P0.1 (SAATHI-2) — Lawyer authentication & BCI verification (full lifecycle) */
/* -------------------------------------------------------------------------- */
const LAWYER_STEPS = [
  { key: 'register', label: 'Register' },
  { key: 'otp', label: 'Verify OTP' },
  { key: 'consent', label: 'DPDP consent' },
  { key: 'bci', label: 'Bar Council' },
  { key: 'result', label: 'Verification' },
];
const phaseToLawyerStep: Record<AuthPhase, number> = {
  entry: 0, register: 0, otp_sent: 1, otp_entry: 1, consent: 2, details: 3, pending: 4, manual_review: 4, rejected: 4, verified: 4,
};

export function LawyerVerify() {
  return <AuthWorkbench role="lawyer" />;
}
export function StudentVerify() {
  return <AuthWorkbench role="student" />;
}

/** Shared workbench-driven lifecycle for both roles (branches on role). */
function AuthWorkbench({ role }: { role: AuthRole }) {
  const isLawyer = role === 'lawyer';
  const restored = useMemo(() => loadAuthSnapshot(role), [role]);
  const [phase, setPhase] = useState<AuthPhase>(restored?.phase ?? 'register');
  const [name, setName] = useState('');
  const [firstName, setFirstName] = useState('');
  const [middleName, setMiddleName] = useState('');
  const [lastName, setLastName] = useState('');
  const [mobile, setMobile] = useState('');
  const [challenge, setChallenge] = useState<OtpChallenge | null>(
    restored?.challenge ? { ...restored.challenge, code: STUB_OTP_CODE } : null,
  );
  const [otpInput, setOtpInput] = useState('');
  const [otpMsg, setOtpMsg] = useState<string | null>(null);
  const [destMasked, setDestMasked] = useState<string | null>(restored?.destinationMasked ?? null);
  const [consent, setConsent] = useState(false);
  const [consentAt, setConsentAt] = useState<string | null>(restored?.consentAt ?? null);
  const [ledger, setLedger] = useState<LedgerEntry[]>([]);
  const now = Date.now();

  // Lawyer verification
  const [profile, setProfile] = useState<LawyerProfile>(EMPTY_LAWYER_PROFILE);
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [rec, setRec] = useState<VerificationRecord | null>(null);
  const enrolSrc = useMemo(() => createStubEnrolmentSource(), []);

  // Student verification
  const [sv, setSv] = useState<StudentVerifyInput>(EMPTY_STUDENT_VERIFY);
  const [dob, setDob] = useState('');
  const [srec, setSrec] = useState<StudentVerificationRecord | null>(null);
  const [guardian] = useState<GuardianConsent | null>(null);
  const otpFlow = useOtpFlowState();
  const [busy, setBusy] = useState(false);

  const minorCtx = useMemo(() => (dob ? minorContextFromDob(dob, nowISO(), guardian) : { isMinor: false, guardianConsent: guardian }), [dob, guardian]);

  // Persist a redacted snapshot whenever lifecycle state changes.
  useEffect(() => {
    const snap: AuthSnapshot = {
      role, phase, destinationMasked: destMasked,
      challenge: challenge ? redactChallenge(challenge) : null,
      consentAt, updatedAt: Date.now(),
    };
    saveAuthSnapshot(snap);
  }, [role, phase, destMasked, challenge, consentAt]);

  const pushLedger = (label: string) => setLedger((l) => [...l, { label, meta: new Date().toLocaleTimeString('en-IN') }]);
  const go = (event: Parameters<typeof nextPhase>[1]) => setPhase((p) => nextPhase(p, event));

  async function sendOtp() {
    if (isLawyer) {
      // Lawyer keeps a single full name; shared exact-10 mobile contract.
      if (!isValidMobile(mobile)) { setErrors({ mobile: MOBILE_ERROR }); return; }
    } else {
      // Student: build the canonical typed registration command (split name +
      // exact-10 mobile). A rejected validation yields NO command and blocks OTP.
      const built = buildStudentRegistrationCommand({ firstName, middleName, lastName, mobile });
      if (!built.ok) {
        const e: Record<string, string> = {};
        for (const [k, v] of Object.entries(built.errors)) if (v) e[k] = v;
        setErrors(e);
        return;
      }
      if (!dob || !isRegistrableDob(dob)) {
        setErrors({ dob: !dob ? 'Enter your date of birth to confirm eligibility.' : DOB_ERROR });
        return;
      }
      if (!consent) {
        setErrors({ consent: 'Accept the Privacy Notice before an OTP is sent.' });
        return;
      }
      setName(built.command.fullName);
      setBusy(true);
      try {
        await registerStudent({
          firstName: built.command.firstName,
          middleName: built.command.middleName,
          lastName: built.command.lastName,
          mobile,
          dob,
          termsAccepted: true,
          termsVersion: TERMS_VERSION,
          privacyNoticeAcknowledged: true,
          privacyNoticeVersion: PRIVACY_NOTICE_VERSION,
        });
        const flow = await getOtpFlowState();
        otpFlow.adopt(flow);
        setDestMasked(flow.destinationMasked);
        setOtpMsg(null);
        pushLedger('OTP dispatched');
        setPhase('otp_entry');
      } catch {
        setErrors({ submit: 'Registration or code delivery could not be completed. Check your details or try again later.' });
      } finally {
        setBusy(false);
      }
      return;
    }
    setErrors({});
    const ch = createChallenge(STUB_OTP_CODE, Date.now());
    setChallenge(ch);
    setDestMasked(maskDestination({ channel: 'sms', ref: mobile }));
    setOtpMsg(null);
    pushLedger('OTP dispatched');
    setPhase('otp_entry');
  }
  async function submitOtp() {
    if (!isLawyer && otpFlow.state?.status === 'pending' && otpFlow.state.purpose === 'signup') {
      setBusy(true);
      try {
        otpFlow.adopt(await verifyStudentOtp(otpInput));
        setOtpMsg(null);
        pushLedger('OTP verified');
        setPhase('consent');
      } catch (error) {
        if (error instanceof RegistrationApiError) {
          if (error.otpState) otpFlow.adopt(error.otpState);
          if (['locked', 'otp_locked'].includes(error.code)) {
            setOtpMsg(error.otpState?.lockedForSeconds === null || error.otpState?.lockedForSeconds === undefined
              ? 'Too many attempts — temporarily locked.'
              : `Too many attempts — locked for ${error.otpState.lockedForSeconds} seconds.`);
          } else if (['expired', 'otp_expired'].includes(error.code)) setOtpMsg('Code expired. Resend a new code.');
          else setOtpMsg(`Incorrect OTP. ${error.otpState?.attemptsLeft ?? '—'} attempt(s) left.`);
        } else setOtpMsg('OTP verification is unavailable. Please retry.');
      } finally {
        setBusy(false);
      }
      return;
    }
    if (!challenge) return;
    const r = otpVerify(challenge, otpInput, Date.now());
    setChallenge(r.challenge);
    if (r.status === 'verified') { setOtpMsg(null); pushLedger('OTP verified'); setPhase('consent'); return; }
    if (r.status === 'locked') setOtpMsg('Too many attempts — locked. Resend after the cooldown.');
    else if (r.status === 'expired') setOtpMsg('Code expired. Resend a new code.');
    else setOtpMsg(`Incorrect OTP. ${r.challenge.attemptsLeft} attempt(s) left.`);
  }
  async function resendOtp() {
    if (!isLawyer && otpFlow.state?.status === 'pending' && otpFlow.state.purpose === 'signup') {
      setBusy(true);
      try {
        otpFlow.adopt(await resendStudentOtp());
        setOtpMsg(null);
        setOtpInput('');
        pushLedger('OTP resent');
      } catch (error) {
        if (error instanceof RegistrationApiError && error.otpState) otpFlow.adopt(error.otpState);
        setOtpMsg('A new code cannot be sent yet. Wait for the cooldown and retry.');
      } finally {
        setBusy(false);
      }
      return;
    }
    if (!challenge) return;
    setChallenge(otpResend(challenge, STUB_OTP_CODE, Date.now()));
    setOtpMsg(null); setOtpInput('');
    pushLedger('OTP resent');
  }
  function giveConsent() {
    if (!consent) return;
    setConsentAt(nowISO());
    pushLedger('DPDP consent recorded');
    setPhase('details');
  }
  function runLawyerCheck() {
    const e = validateLawyerProfile(profile);
    setErrors(e);
    if (Object.keys(e).length) return;
    const r = runEnrolmentCheck(profile, enrolSrc, nowISO());
    setRec(r);
    pushLedger(`Enrolment check: ${r.status}`);
    setPhase(nextPhase('details', r.status === 'verified' ? 'result_verified' : r.status === 'manual_review' ? 'result_manual' : 'result_rejected'));
  }
  function runStudentCheck() {
    const e = validateStudentVerify(sv);
    // P0.2 age gate: DOB must be a real calendar date and not in the (local)
    // future — enforced at the domain submit boundary before verification runs.
    if (!dob) e.dob = 'Enter your date of birth to confirm eligibility.';
    else if (!isRegistrableDob(dob)) e.dob = DOB_ERROR;
    setErrors(e);
    if (Object.keys(e).length) return;
    const r = decideStudentVerification(sv, nowISO());
    setSrec(r);
    pushLedger(`Student check: ${r.status}`);
    setPhase(nextPhase('details', r.status === 'verified' ? 'result_verified' : r.status === 'manual_review' ? 'result_manual' : 'result_rejected'));
  }
  function resetFlow() {
    clearAuthSnapshot(role);
    clearRegistrationSession();
    setPhase('register'); setChallenge(null); setOtpInput(''); setOtpMsg(null); setDestMasked(null);
    setConsent(false); setConsentAt(null); setRec(null); setSrec(null); setLedger([]);
    setProfile(EMPTY_LAWYER_PROFILE); setSv(EMPTY_STUDENT_VERIFY); setDob('');
  }

  // --- derived ---
  const steps = isLawyer
    ? stepStates(LAWYER_STEPS, phaseToLawyerStep[phase])
    : stepStates([
        { key: 'register', label: 'Register' }, { key: 'otp', label: 'Verify OTP' }, { key: 'consent', label: 'DPDP consent' },
        { key: 'verify', label: 'Student proof' }, { key: 'result', label: 'Access' },
      ], phaseToLawyerStep[phase]);

  const requirements: Requirement[] = isLawyer
    ? [
        { label: 'Mobile OTP verified', done: ['consent', 'details', 'pending', 'manual_review', 'rejected', 'verified'].includes(phase) },
        { label: 'DPDP consent recorded', done: !!consentAt },
        { label: 'Bar Council enrolment submitted', done: !!rec },
        { label: 'Enrolment status verified', done: canAccessLawyerFeatures(rec) },
      ]
    : [
        { label: 'Mobile OTP verified', done: ['consent', 'details', 'pending', 'manual_review', 'rejected', 'verified'].includes(phase) },
        { label: 'DPDP consent recorded', done: !!consentAt },
        { label: 'Student status verified', done: srec?.status === 'verified' },
        { label: 'Guardian consent (if minor)', done: !minorCtx.isMinor || guardianConsentSatisfied(guardian) },
      ];

  const policy = (
    <PrivacyNotice>
      {isLawyer
        ? <>Enrolment-status verification only — no competence, endorsement or outcome claims. Profile display is {BCI_PROFILE_DISPLAY_ENABLED ? 'enabled' : 'disabled by default pending legal review (LCR-002)'}. Data processed within India.</>
        : <>{DPDP_MINIMISATION_NOTICE} Minor accounts stay restricted until guardian consent is verified.</>}
    </PrivacyNotice>
  );

  return (
    <section className="st-screen st-stack" data-screen={isLawyer ? 'P0.1' : 'P0.2'}>
      <div className="st-set__head">
        <p className="st-eyebrow">Authentication · {isLawyer ? 'P0.1' : 'P0.2'}</p>
        <h1 className="st-h1">{isLawyer ? 'Lawyer verification' : 'Student verification'}</h1>
        <p className="st-metatag" style={{ marginTop: 4 }}>State: {AUTH_PHASE_LABELS[phase]}</p>
      </div>
      <Workbench
        brand="NyayOne"
        role={isLawyer ? 'Advocate verification' : 'Student verification'}
        steps={steps}
        requirements={requirements}
        ledger={ledger}
        policy={policy}
      >
        {/* REGISTER */}
        {phase === 'register' && (
          <div className="st-stack">
            <h2 className="st-panel__title">Register</h2>
            {isLawyer ? (
              <TextField id="reg-name" label="Full name" value={name} onChange={setName} autoComplete="name" />
            ) : (
              <fieldset className="st-namegroup">
                <legend className="st-namegroup__legend">
                  Name
                  <InfoTooltip
                    label="Information about name and guardian consent"
                    text="Under-18 accounts need verified guardian consent before full access · collected under data minimisation · DPDP Act, 2023."
                  />
                </legend>
                <TextField id="reg-first-name" label="First name" value={firstName} onChange={setFirstName} error={errors.firstName} autoComplete="given-name" />
                <TextField id="reg-middle-name" label="Middle name" optional="optional" value={middleName} onChange={setMiddleName} error={errors.middleName} autoComplete="additional-name" />
                <TextField id="reg-last-name" label="Last name" value={lastName} onChange={setLastName} error={errors.lastName} autoComplete="family-name" />
              </fieldset>
            )}
            <TextField id="reg-mobile" label="Mobile number" value={mobile} onChange={setMobile} error={errors.mobile} type="text" inputMode="numeric" autoComplete="tel" help="We send a one-time code by SMS." />
            {!isLawyer && (
              <>
                <TextField id="reg-dob" label="Date of birth" value={dob} onChange={setDob} type="date" max={todayLocalISO()} error={errors.dob} />
                <SelectField id="reg-college" label="College / university" value={sv.collegeName} onChange={(v) => setSv((s) => ({ ...s, collegeName: v }))} options={['NLSIU', 'NALSAR', 'NLU Delhi', 'Other']} />
                <Checkbox id="reg-consent" checked={consent} onChange={setConsent} label="I accept the Privacy Notice and processing for registration." />
                {errors.consent && <ValidationState message={errors.consent} />}
              </>
            )}
            {errors.submit && <ValidationState message={errors.submit} />}
            <div className="st-actions"><button type="button" className="btn btn--primary tap" onClick={sendOtp} disabled={busy}>{busy ? 'Sending…' : 'Send OTP'}</button></div>
          </div>
        )}

        {/* OTP ENTRY (covers sent / entry / invalid / expired / lockout) */}
        {(phase === 'otp_sent' || phase === 'otp_entry') && (
          challenge || (!isLawyer && otpFlow.state?.status === 'pending' && otpFlow.state.purpose === 'signup')
        ) && (
          <div className="st-stack">
            <h2 className="st-panel__title">Verify OTP</h2>
            <p className="st-item__meta">
              Code sent to {destMasked}. {challenge
                ? (isLocked(challenge, now) ? 'Locked.' : `Expires in ${secondsUntilExpiry(challenge, now)}s.`)
                : `Expires in ${otpFlow.state?.expiresInSeconds ?? 0}s.`}
            </p>
            <TextField id="otp-input" label="6-digit code" value={otpInput} onChange={setOtpInput} inputMode="numeric" autoComplete="one-time-code" help="Enter the one-time code sent by SMS. A wrong code shows the invalid/lockout states." />
            {otpMsg && <ValidationState message={otpMsg} />}
            {challenge && isLocked(challenge, now) && <StatusBadge status={chip('risk')} label="Locked — too many attempts" />}
            <div className="st-actions st-actions--split">
              <button type="button" className="btn btn--primary tap" onClick={submitOtp} disabled={busy || (!!challenge && isLocked(challenge, now)) || (!isLawyer && (otpFlow.state?.lockedForSeconds ?? 0) > 0)}>Verify</button>
              <button type="button" className="btn tap" onClick={resendOtp} disabled={busy || (!!challenge && secondsUntilResend(challenge, now) > 0) || (!isLawyer && !otpFlow.state?.resendAllowed)}>
                {challenge && secondsUntilResend(challenge, now) > 0
                  ? `Resend in ${secondsUntilResend(challenge, now)}s`
                  : !isLawyer && !otpFlow.state?.resendAllowed
                    ? `Resend in ${otpFlow.state?.resendInSeconds ?? 0}s`
                    : 'Resend code'}
              </button>
            </div>
          </div>
        )}

        {/* CONSENT (explicit affirmative, recorded) */}
        {phase === 'consent' && (
          <div className="st-stack">
            <h2 className="st-panel__title">Data-protection consent</h2>
            <PrivacyNotice>We process your data under the DPDP Act, 2023, only to verify your {isLawyer ? 'enrolment' : 'student'} status. Data is processed within India.</PrivacyNotice>
            <Checkbox id="dpdp" checked={consent} onChange={setConsent} label={<>I have read and accept the Privacy Notice and consent to processing for verification.</>} />
            {!consent && <ValidationState message="Affirmative consent is required before we process your details." />}
            <div className="st-actions"><button type="button" className="btn btn--primary tap" onClick={giveConsent} disabled={!consent} aria-disabled={!consent}>Record consent &amp; continue</button></div>
          </div>
        )}

        {/* DETAILS — lawyer BCI */}
        {phase === 'details' && isLawyer && (
          <div className="st-stack">
            <h2 className="st-panel__title">Bar Council enrolment</h2>
            <TextField id="lw-name" label="Full name (as enrolled)" value={profile.fullName} onChange={(v) => setProfile((s) => ({ ...s, fullName: v }))} error={errors.fullName} />
            <TextField id="lw-enrol" label="Enrolment number" value={profile.enrolmentNumber} onChange={(v) => setProfile((s) => ({ ...s, enrolmentNumber: v }))} error={errors.enrolmentNumber} help="Format STATE/NUMBER/YEAR, e.g. D/1234/2015." />
            <SelectField id="lw-council" label="State Bar Council" value={profile.stateBarCouncil} onChange={(v) => setProfile((s) => ({ ...s, stateBarCouncil: v }))} options={STATE_BAR_COUNCILS} error={errors.stateBarCouncil} />
            <GuardrailNotice>{ENROLMENT_STATUS_ONLY_NOTICE}</GuardrailNotice>
            <div className="st-actions"><button type="button" className="btn btn--primary tap" onClick={runLawyerCheck}>Submit for verification</button></div>
          </div>
        )}

        {/* DETAILS — student proof */}
        {phase === 'details' && !isLawyer && (
          <div className="st-stack">
            <h2 className="st-panel__title">Student proof</h2>
            <div className="st-chips" role="group" aria-label="Verification method" style={{ marginBottom: 'var(--space-3)' }}>
              {(['institutional_email', 'college_id'] as VerifyMethod[]).map((m) => (
                <button key={m} type="button" className="st-chip" aria-pressed={sv.method === m} onClick={() => setSv((s) => ({ ...s, method: m }))}>{VERIFY_METHOD_LABELS[m]}</button>
              ))}
            </div>
            {sv.method === 'institutional_email'
              ? <TextField id="sv-email" label="Institutional email" value={sv.institutionalEmail} onChange={(v) => setSv((s) => ({ ...s, institutionalEmail: v }))} error={errors.institutionalEmail} type="email" inputMode="email" help="A .ac.in / .edu address verifies automatically." />
              : <TextField id="sv-id" label="College ID reference" value={sv.idDocumentRef} onChange={(v) => setSv((s) => ({ ...s, idDocumentRef: v }))} error={errors.idDocumentRef} help="Stored as an access-controlled reference (never in a URL); routed to manual review." />}
            <TextField id="sv-dob" label="Date of birth" value={dob} onChange={setDob} type="date" max={todayLocalISO()} error={errors.dob} optional="age gate" help="Under-18 accounts require guardian consent." />
            {minorCtx.isMinor && (
              <div className="ui-banner ui-banner--warn" role="status">
                <span className="ui-banner__mark" aria-hidden>!</span>
                <span>Minor detected — guardian consent must be completed through the verified guardian channel. A student cannot approve or decline it.</span>
              </div>
            )}
            <PrivacyNotice>{DPDP_MINIMISATION_NOTICE}</PrivacyNotice>
            <div className="st-actions"><button type="button" className="btn btn--primary tap" onClick={runStudentCheck}>Submit for verification</button></div>
          </div>
        )}

        {/* RESULT STATES */}
        {['pending', 'manual_review', 'rejected', 'verified'].includes(phase) && (
          <div className="st-stack">
            <div className="st-panel__head">
              <h2 className="st-panel__title">Verification</h2>
              <StatusBadge status={statusChip(phase)} label={isLawyer && rec ? LAWYER_VERIFICATION_STATUS_LABELS[rec.status] : !isLawyer && srec ? STUDENT_VERIFICATION_STATUS_LABELS[srec.status] : AUTH_PHASE_LABELS[phase]} />
            </div>

            {isLawyer ? <LawyerResult phase={phase} rec={rec} unlocked={canAccessLawyerFeatures(rec)} gate={lawyerGateReason(rec)}
              onRetry={() => go('retry')} />
              : <StudentResult phase={phase} srec={srec} minor={minorCtx.isMinor} guardianOk={guardianConsentSatisfied(guardian)}
                pro={proFeaturesUnlocked({ verification: srec, minor: minorCtx })}
                gate={studentGateReason({ verification: srec, minor: minorCtx })} onRetry={() => go('retry')} />}

            <div className="st-actions"><button type="button" className="btn tap" onClick={resetFlow}>Start over</button></div>
          </div>
        )}
      </Workbench>
      <DpdpFootnote>OTP flow state persists across refresh without storing the code; verification status, checker, timestamp and any override reason are audited</DpdpFootnote>
    </section>
  );
}

function LawyerResult({ phase, rec, unlocked, gate, onRetry }: {
  phase: AuthPhase; rec: VerificationRecord | null; unlocked: boolean; gate: string | null;
  onRetry: () => void;
}) {
  return (
    <>
      {rec && <p className="st-item__meta">Checked by {rec.checker}{rec.overrideReason ? ` · override: ${rec.overrideReason}` : ''}</p>}
      {phase === 'manual_review' && <p>Your enrolment is in manual review by our compliance team. Lawyer features unlock once a reviewer confirms it.</p>}
      {phase === 'rejected' && (
        <>
          <p>We could not verify this enrolment. Re-check the number or contact the compliance team for an independent review.</p>
          <div className="st-actions"><button type="button" className="btn tap" onClick={onRetry}>Re-check enrolment</button></div>
        </>
      )}
      <section className="st-panel" aria-label="Lawyer workspace" style={{ marginTop: 'var(--space-3)' }}>
        <h3 className="st-panel__title">Lawyer workspace</h3>
        {unlocked ? <EmptyState title="Verified — lawyer features unlocked" hint="Case initiation, drafting and billing are available." /> : <RestrictedState reason={gate ?? 'Verification required.'} />}
      </section>
    </>
  );
}

function StudentResult({ phase, srec, minor, guardianOk, pro, gate, onRetry }: {
  phase: AuthPhase; srec: StudentVerificationRecord | null; minor: boolean; guardianOk: boolean; pro: boolean; gate: string | null; onRetry: () => void;
}) {
  return (
    <>
      {srec && <p className="st-item__meta">Method: {srec.method} · checked by {srec.checker}</p>}
      {phase === 'manual_review' && <p>Your college ID is in manual review over a secure, access-controlled channel. Free access continues while you wait.</p>}
      {phase === 'rejected' && (
        <>
          <p>We could not verify your student status. Try your institutional email, or re-upload a clearer college ID.</p>
          <div className="st-actions"><button type="button" className="btn tap" onClick={onRetry}>Try again</button></div>
        </>
      )}
      {minor && !guardianOk && <StatusBadge status={chip('warn')} label="Minor — guardian consent pending" />}
      <section className="st-panel" aria-label="Student access" style={{ marginTop: 'var(--space-3)' }}>
        <h3 className="st-panel__title">Student access</h3>
        {pro ? <EmptyState title="Verified — Student Pro unlocked" hint="Student features and pricing are available." /> : <RestrictedState reason={gate ?? 'Verification required.'} />}
      </section>
    </>
  );
}

/* -------------------------------------------------------------------------- */
/* P0.3 (SAATHI-4) — Session, device & account security (full workflows)       */
/* -------------------------------------------------------------------------- */
const SAMPLE_DEVICES: DeviceRecord[] = [
  { deviceId: 'd1', label: 'This device · Chrome', lastSeen: Date.now(), current: true, revoked: false },
  { deviceId: 'd2', label: 'Pixel 8 · App', lastSeen: Date.now() - 86_400_000, current: false, revoked: false },
];

type SecurityView = 'overview' | 'reset';

export function AccountSecurity() {
  const [session, setSession] = useState<Session>(() => issueSession('u1', 'd1', Date.now() - DEFAULT_SESSION_POLICY.reauthWithinMs - 1000));
  const [devices, setDevices] = useState<DeviceRecord[]>(SAMPLE_DEVICES);
  const [attempts, setAttempts] = useState(FRESH_ATTEMPTS);
  const [resetAttempts, setResetAttempts] = useState(FRESH_ATTEMPTS);
  const [events, setEvents] = useState<SecurityAuditEvent[]>([]);
  const [reauthOpen, setReauthOpen] = useState(false);
  const [view, setView] = useState<SecurityView>('overview');
  const [resetChallenge, setResetChallenge] = useState<OtpChallenge | null>(null);
  const [resetInput, setResetInput] = useState('');
  const [resetMsg, setResetMsg] = useState<string | null>(null);
  const [refreshMsg, setRefreshMsg] = useState<string | null>(null);
  const now = Date.now();
  const bio = biometricCapability(false);
  const record = (e: SecurityAuditEvent) => setEvents((p) => [e, ...p].slice(0, 8));

  function failLogin() {
    const next = registerFailure(attempts, now); setAttempts(next);
    record(securityEvent('login_failed', 'u1', 'd1', now));
    if (isLockedOut(next, now)) record(securityEvent('lockout', 'u1', 'd1', now));
  }
  function succeedLogin() {
    setAttempts(registerSuccess()); setSession(issueSession('u1', 'd1', now)); record(securityEvent('login', 'u1', 'd1', now));
    if (isUnusualLogin('d-new', devices)) record(securityEvent('login', 'u1', 'd-new', now)); // unusual-login notice (adapter)
  }
  function doRefresh(ok: boolean) {
    if (ok) { const r = refreshSession(session, now); if (r) { setSession(r); setRefreshMsg('Session refreshed.'); record(securityEvent('session_refresh', 'u1', 'd1', now)); } }
    else { setSession(revokeSession(session)); setRefreshMsg('Refresh failed — please sign in again.'); }
  }
  function logoutCurrent() { setSession(revokeSession(session)); record(securityEvent('logout', 'u1', 'd1', now)); }
  function logoutAll() { setDevices((d) => revokeAllOtherDevices(d)); setSession(revokeSession(session)); record(securityEvent('logout', 'u1', 'all', now)); }
  function revoke(id: string) { setDevices((d) => revokeDevice(d, id)); record(securityEvent('device_revoked', 'u1', id, now)); }
  function attemptSensitive() { if (requiresReauth(session, now)) { setReauthOpen(true); return; } record(securityEvent('password_reset', 'u1', 'd1', now)); }
  function confirmReauth() { setSession((s) => markReauthenticated(s, Date.now())); setReauthOpen(false); record(securityEvent('reauth', 'u1', 'd1', Date.now())); }
  function startReset() { setResetChallenge(createChallenge(STUB_OTP_CODE, Date.now())); setResetInput(''); setResetMsg(null); setView('reset'); }
  function submitReset() {
    if (!resetChallenge) return;
    if (isLockedOut(resetAttempts, now)) { setResetMsg('Locked — too many attempts.'); return; }
    const r = otpVerify(resetChallenge, resetInput, Date.now()); setResetChallenge(r.challenge);
    if (r.status === 'verified') { setResetMsg('Recovery successful — set a new password.'); record(securityEvent('password_reset', 'u1', 'd1', now)); }
    else if (r.status === 'expired') setResetMsg('Reset code expired.');
    else { const na = registerFailure(resetAttempts, now); setResetAttempts(na); setResetMsg(isLockedOut(na, now) ? 'Locked — too many attempts.' : 'Invalid reset code.'); }
  }

  const active = session.revoked ? false : now < session.expiresAt;
  const warn = expiryWarning(session, now);
  const steps: WorkbenchStep[] = [
    { key: 'session', label: 'Session', state: view === 'overview' ? 'active' : 'done' },
    { key: 'devices', label: 'Devices', state: 'todo' },
    { key: 'recovery', label: 'Recovery', state: view === 'reset' ? 'active' : 'todo' },
  ];
  const requirements: Requirement[] = [
    { label: 'Active session', done: active },
    { label: 'Re-auth for sensitive actions', done: !requiresReauth(session, now) },
    { label: 'Rate-limit protection', done: true },
  ];
  const ledger: LedgerEntry[] = events.map((e) => ({ label: SECURITY_EVENT_LABELS[e.type], meta: `${e.deviceId} · ${new Date(e.timestamp).toLocaleTimeString('en-IN')}` }));

  return (
    <section className="st-screen st-stack" data-screen="P0.3">
      <div className="st-set__head">
        <p className="st-eyebrow">Authentication · P0.3</p>
        <h1 className="st-h1">Session &amp; account security</h1>
      </div>
      <Workbench brand="NyayOne" role="Security console" steps={steps} requirements={requirements} ledger={ledger}
        policy={<PrivacyNotice>Sessions and device records are server-authoritative and audited. No raw passwords, OTPs or tokens are stored or logged. Notifications go through adapters only.</PrivacyNotice>}>
        {view === 'overview' ? (
          <div className="st-stack">
            <section className="st-panel">
              <div className="st-panel__head"><h2 className="st-panel__title">Active session</h2>
                <StatusBadge status={active ? (warn ? chip('warn') : chip('ok')) : chip('risk')} label={active ? (warn ? 'Expiring soon' : 'Active') : 'Signed out'} /></div>
              {warn && active && <ValidationState message="Your session expires soon. Refresh to stay signed in." />}
              {refreshMsg && <p className="st-item__meta">{refreshMsg}</p>}
              <div className="st-actions st-actions--split">
                <button type="button" className="btn tap" onClick={() => doRefresh(true)}>Refresh session</button>
                <button type="button" className="btn tap" onClick={() => doRefresh(false)}>Simulate refresh failure</button>
                <button type="button" className="btn tap" onClick={logoutCurrent}>Log out</button>
                <button type="button" className="btn tap" onClick={logoutAll}>Log out all devices</button>
              </div>
            </section>

            <section className="st-panel">
              <h2 className="st-panel__title">Sign-in protection</h2>
              <p className="st-item__meta">Locks after {DEFAULT_SESSION_POLICY.maxFailedAttempts} failed attempts. {isLockedOut(attempts, now) ? 'Currently locked.' : `${attempts.failures} failed.`}</p>
              <div className="st-actions st-actions--split">
                <button type="button" className="btn tap" onClick={failLogin} disabled={isLockedOut(attempts, now)} aria-disabled={isLockedOut(attempts, now)}>Simulate failed sign-in</button>
                <button type="button" className="btn tap" onClick={succeedLogin}>Successful sign-in</button>
              </div>
            </section>

            <section className="st-panel">
              <h2 className="st-panel__title">Sensitive action</h2>
              <p className="st-item__meta">Requires re-auth within {Math.round(DEFAULT_SESSION_POLICY.reauthWithinMs / 60000)} min.</p>
              <div className="st-actions"><button type="button" className="btn tap" onClick={attemptSensitive}>Change password</button></div>
              {reauthOpen && (
                <div className="ui-banner ui-banner--warn" role="status"><span className="ui-banner__mark" aria-hidden>!</span><span>Re-authentication required.&nbsp;</span>
                  <button type="button" className="btn tap" onClick={confirmReauth}>Re-authenticate</button></div>
              )}
              <p className="st-field__help">Biometric / native re-auth: {bio === 'available' ? 'available' : 'unavailable in this shell'}.</p>
            </section>

            <section className="st-panel">
              <h2 className="st-panel__title">Devices</h2>
              <ul className="st-list">
                {devices.map((d) => (
                  <li className="st-item" key={d.deviceId}>
                    <div><div>{d.label}</div><div className="st-item__meta">{d.current ? 'Current session' : 'Other device'}</div></div>
                    {d.revoked ? <StatusBadge status={chip('info')} label="Signed out" /> : <button type="button" className="btn tap" onClick={() => revoke(d.deviceId)}>Sign out</button>}
                  </li>
                ))}
              </ul>
            </section>

            <div className="st-actions"><button type="button" className="btn tap" onClick={startReset}>Forgot password / reset</button></div>
          </div>
        ) : (
          <div className="st-stack">
            <h2 className="st-panel__title">Password reset</h2>
            <p className="st-item__meta">{resetChallenge ? (isLockedOut(resetAttempts, now) ? 'Locked.' : `Code expires in ${secondsUntilExpiry(resetChallenge, now)}s.`) : ''}</p>
            <TextField id="reset-otp" label="Reset code" value={resetInput} onChange={setResetInput} inputMode="numeric" />
            {resetMsg && <ValidationState message={resetMsg} />}
            <div className="st-actions st-actions--split">
              <button type="button" className="btn btn--primary tap" onClick={submitReset} disabled={isLockedOut(resetAttempts, now)} aria-disabled={isLockedOut(resetAttempts, now)}>Verify reset code</button>
              <button type="button" className="btn tap" onClick={() => setView('overview')}>Back to session</button>
            </div>
          </div>
        )}
      </Workbench>
      <DpdpFootnote>Login, failure, reset, refresh, logout, revocation, re-auth and lockout are audited; recovery uses rate-limited OTP</DpdpFootnote>
    </section>
  );
}
