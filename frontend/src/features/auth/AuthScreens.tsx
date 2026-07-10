import { useMemo, useState } from 'react';
import { TextField, SelectField, Checkbox, DpdpFootnote } from '../student/components';
import {
  StatusBadge, GuardrailNotice, PrivacyNotice, RestrictedState, ValidationState, EmptyState,
} from '../../components/ui/primitives';
import {
  validateLawyerProfile, EMPTY_LAWYER_PROFILE, createStubEnrolmentSource, runEnrolmentCheck,
  recordManualOverride, canAccessLawyerFeatures, lawyerGateReason,
  LAWYER_VERIFICATION_STATUS_LABELS, STATE_BAR_COUNCILS, ENROLMENT_STATUS_ONLY_NOTICE,
  BCI_PROFILE_DISPLAY_ENABLED, type LawyerProfile, type VerificationRecord,
} from './lib/lawyerVerify';
import {
  validateStudentVerify, EMPTY_STUDENT_VERIFY, decideStudentVerification, minorContextFromDob,
  proFeaturesUnlocked, studentGateReason,
  STUDENT_VERIFICATION_STATUS_LABELS, VERIFY_METHOD_LABELS, DPDP_MINIMISATION_NOTICE,
  type VerifyMethod, type StudentVerifyInput, type StudentVerificationRecord,
} from './lib/studentVerify';
import {
  DEFAULT_SESSION_POLICY, issueSession, requiresReauth, markReauthenticated,
  FRESH_ATTEMPTS, isLockedOut, registerFailure, registerSuccess, revokeDevice,
  securityEvent, biometricCapability, SECURITY_EVENT_LABELS,
  type DeviceRecord, type SecurityAuditEvent, type Session,
} from './lib/session';

/** Auth-module screen scaffold (Phase 0 has no v3.2 design; reuses student CSS). */
function AuthScreen({ eyebrow, title, sub, children }: { eyebrow: string; title: string; sub?: string; children: React.ReactNode }) {
  return (
    <section className="st-screen st-stack">
      <div className="st-set__head">
        <p className="st-eyebrow">{eyebrow}</p>
        <h1 className="st-h1">{title}</h1>
        {sub && <p className="st-metatag" style={{ marginTop: 4 }}>{sub}</p>}
      </div>
      {children}
    </section>
  );
}

const chip = (k: 'ok' | 'warn' | 'risk' | 'info') => k;
const statusChip = (s: string) => (s === 'verified' ? chip('ok') : s === 'rejected' ? chip('risk') : s === 'manual_review' ? chip('warn') : chip('info'));

/* -------------------------------------------------------------------------- */
/* P0.1 (SAATHI-2) — Lawyer authentication & BCI verification                  */
/* -------------------------------------------------------------------------- */
export function LawyerVerify() {
  const [p, setP] = useState<LawyerProfile>(EMPTY_LAWYER_PROFILE);
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [consent, setConsent] = useState(false);
  const [rec, setRec] = useState<VerificationRecord | null>(null);
  const [reason, setReason] = useState('');
  const source = useMemo(() => createStubEnrolmentSource(), []);
  const set = (k: keyof LawyerProfile) => (v: string) => setP((s) => ({ ...s, [k]: v }));

  function runCheck() {
    const e = validateLawyerProfile(p);
    setErrors(e);
    if (Object.keys(e).length || !consent) return;
    setRec(runEnrolmentCheck(p, source, new Date().toISOString()));
  }
  function override() {
    if (!rec) return;
    setRec(recordManualOverride(rec, { authorised: true, reason, reviewer: 'admin:compliance' }, new Date().toISOString()));
  }

  const unlocked = canAccessLawyerFeatures(rec);
  const gate = lawyerGateReason(rec);

  return (
    <AuthScreen eyebrow="Authentication · P0.1" title="Lawyer verification" sub="Bar Council enrolment verification">
      <section className="st-panel">
        <h2 className="st-panel__title">Enrolment details</h2>
        <TextField id="lw-name" label="Full name (as enrolled)" value={p.fullName} onChange={set('fullName')} error={errors.fullName} autoComplete="name" />
        <TextField id="lw-enrol" label="Enrolment number" value={p.enrolmentNumber} onChange={set('enrolmentNumber')} error={errors.enrolmentNumber} help="Format: STATE/NUMBER/YEAR, e.g. D/1234/2015." />
        <SelectField id="lw-council" label="State Bar Council" value={p.stateBarCouncil} onChange={set('stateBarCouncil')} options={STATE_BAR_COUNCILS} error={errors.stateBarCouncil} />
        <Checkbox id="lw-consent" checked={consent} onChange={setConsent} label={<>I accept the Terms and Privacy Policy.</>} />
        {!consent && Object.keys(errors).length === 0 && rec === null && <ValidationState message="Accept the Terms and Privacy Policy to verify." />}
        <div className="st-actions">
          <button type="button" className="btn btn--primary tap" onClick={runCheck} disabled={!consent} aria-disabled={!consent}>Run verification</button>
        </div>
        <GuardrailNotice>{ENROLMENT_STATUS_ONLY_NOTICE}</GuardrailNotice>
      </section>

      {rec && (
        <section className="st-panel" aria-label="Verification result">
          <div className="st-panel__head">
            <h2 className="st-panel__title">Verification</h2>
            <StatusBadge status={statusChip(rec.status)} label={LAWYER_VERIFICATION_STATUS_LABELS[rec.status]} />
          </div>
          <p className="st-item__meta">Checked by {rec.checker}{rec.overrideReason ? ` · override: ${rec.overrideReason}` : ''}</p>
          {!unlocked && (rec.status === 'rejected' || rec.status === 'manual_review') && (
            <>
              <TextField id="lw-ovr" label="Authorised reviewer override reason" value={reason} onChange={setReason} help="Recorded to the immutable audit log. Human reviewers only — automation cannot clear a verification." />
              <div className="st-actions">
                <button type="button" className="btn tap" disabled={!reason.trim()} aria-disabled={!reason.trim()} onClick={override}>Record authorised override</button>
              </div>
            </>
          )}
        </section>
      )}

      <section className="st-panel" aria-label="Lawyer dashboard">
        <h2 className="st-panel__title">Lawyer dashboard</h2>
        {unlocked
          ? <EmptyState title="Verified — lawyer features unlocked" hint="Case initiation, drafting and billing are now available." />
          : <RestrictedState reason={gate ?? 'Verification required.'} />}
      </section>

      <PrivacyNotice>Profile display of enrolment details is {BCI_PROFILE_DISPLAY_ENABLED ? 'enabled' : 'disabled by default pending legal review (LCR-002)'}.</PrivacyNotice>
      <DpdpFootnote>Verification status, checker, timestamp and any override reason are written to an immutable audit log</DpdpFootnote>
    </AuthScreen>
  );
}

/* -------------------------------------------------------------------------- */
/* P0.2 (SAATHI-3) — Student authentication & institutional verification       */
/* -------------------------------------------------------------------------- */
export function StudentVerify() {
  const [v, setV] = useState<StudentVerifyInput>(EMPTY_STUDENT_VERIFY);
  const [dob, setDob] = useState('');
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [rec, setRec] = useState<StudentVerificationRecord | null>(null);
  const set = (k: keyof StudentVerifyInput) => (val: string) => setV((s) => ({ ...s, [k]: val }));
  const now = new Date().toISOString();
  const minorCtx = useMemo(() => (dob ? minorContextFromDob(dob, now) : { isMinor: false, guardianConsent: null }), [dob, now]);

  function verify() {
    const e = validateStudentVerify(v);
    setErrors(e);
    if (Object.keys(e).length) return;
    setRec(decideStudentVerification(v, now));
  }
  const state = { verification: rec, minor: minorCtx };
  const pro = proFeaturesUnlocked(state);
  const gate = studentGateReason(state);

  return (
    <AuthScreen eyebrow="Authentication · P0.2" title="Student verification" sub="Institutional email or college ID">
      <section className="st-panel">
        <span className="st-field__label" id="sv-method">Verification method</span>
        <div className="st-chips" role="group" aria-labelledby="sv-method" style={{ marginBottom: 'var(--space-3)' }}>
          {(['institutional_email', 'college_id'] as VerifyMethod[]).map((m) => (
            <button key={m} type="button" className="st-chip" aria-pressed={v.method === m} onClick={() => setV((s) => ({ ...s, method: m }))}>
              {VERIFY_METHOD_LABELS[m]}
            </button>
          ))}
        </div>
        {v.method === 'institutional_email' ? (
          <TextField id="sv-email" label="Institutional email" value={v.institutionalEmail} onChange={set('institutionalEmail')} error={errors.institutionalEmail} type="email" inputMode="email" help="A .ac.in / .edu address auto-verifies." />
        ) : (
          <>
            <TextField id="sv-college" label="College / university" value={v.collegeName} onChange={set('collegeName')} error={errors.collegeName} />
            <TextField id="sv-id" label="College ID reference" value={v.idDocumentRef} onChange={set('idDocumentRef')} error={errors.idDocumentRef} help="Uploaded securely; routed to manual review. We store an access-controlled reference, not the file in the URL." />
          </>
        )}
        <TextField id="sv-dob" label="Date of birth" value={dob} onChange={setDob} type="date" optional="for age-gate" help="Under-18 accounts require guardian consent before full activation." />
        <div className="st-actions">
          <button type="button" className="btn btn--primary tap" onClick={verify}>Verify student status</button>
        </div>
        <PrivacyNotice>{DPDP_MINIMISATION_NOTICE}</PrivacyNotice>
      </section>

      {(rec || dob) && (
        <section className="st-panel" aria-label="Account state">
          <div className="st-panel__head">
            <h2 className="st-panel__title">Account state</h2>
            {rec && <StatusBadge status={statusChip(rec.status)} label={STUDENT_VERIFICATION_STATUS_LABELS[rec.status]} />}
          </div>
          {minorCtx.isMinor && <StatusBadge status={chip('warn')} label="Minor — guardian consent required" />}
          {pro
            ? <EmptyState title="Verified — Student Pro unlocked" hint="Student features and pricing are now available." />
            : <RestrictedState reason={gate ?? 'Verification required.'} />}
          {rec?.status === 'manual_review' && (
            <p className="st-item__meta">Your college ID is queued for manual review; it is shown to reviewers over a secure, access-controlled channel.</p>
          )}
        </section>
      )}
      <DpdpFootnote>DPDP notice/consent is logged before processing; minor rules stay conservative pending counsel</DpdpFootnote>
    </AuthScreen>
  );
}

/* -------------------------------------------------------------------------- */
/* P0.3 (SAATHI-4) — Session, device & account security                        */
/* -------------------------------------------------------------------------- */
const SAMPLE_DEVICES: DeviceRecord[] = [
  { deviceId: 'd1', label: 'This device · Chrome', lastSeen: Date.now(), current: true, revoked: false },
  { deviceId: 'd2', label: 'Pixel 8 · App', lastSeen: Date.now() - 86_400_000, current: false, revoked: false },
];

export function AccountSecurity() {
  const [session, setSession] = useState<Session>(() => issueSession('u1', 'd1', Date.now() - DEFAULT_SESSION_POLICY.reauthWithinMs - 1000));
  const [devices, setDevices] = useState<DeviceRecord[]>(SAMPLE_DEVICES);
  const [attempts, setAttempts] = useState(FRESH_ATTEMPTS);
  const [events, setEvents] = useState<SecurityAuditEvent[]>([]);
  const [reauthOpen, setReauthOpen] = useState(false);
  const now = Date.now();
  const bio = biometricCapability(false); // web shell → unavailable

  const record = (e: SecurityAuditEvent) => setEvents((prev) => [e, ...prev].slice(0, 6));

  function failLogin() {
    const next = registerFailure(attempts, now);
    setAttempts(next);
    record(securityEvent('login_failed', 'u1', 'd1', now));
    if (isLockedOut(next, now)) record(securityEvent('lockout', 'u1', 'd1', now));
  }
  function succeedLogin() {
    setAttempts(registerSuccess());
    setSession(issueSession('u1', 'd1', now));
    record(securityEvent('login', 'u1', 'd1', now));
  }
  function attemptSensitive() {
    if (requiresReauth(session, now)) { setReauthOpen(true); return; }
    record(securityEvent('password_reset', 'u1', 'd1', now));
  }
  function confirmReauth() {
    setSession((s) => markReauthenticated(s, Date.now()));
    setReauthOpen(false);
    record(securityEvent('reauth', 'u1', 'd1', Date.now()));
    record(securityEvent('password_reset', 'u1', 'd1', Date.now()));
  }
  function revoke(id: string) {
    setDevices((d) => revokeDevice(d, id));
    record(securityEvent('device_revoked', 'u1', id, now));
  }

  const locked = isLockedOut(attempts, now);

  return (
    <AuthScreen eyebrow="Authentication · P0.3" title="Session & account security" sub="Sessions, devices, recovery">
      <section className="st-panel">
        <div className="st-panel__head">
          <h2 className="st-panel__title">Sign-in protection</h2>
          <StatusBadge status={locked ? chip('risk') : chip('ok')} label={locked ? 'Locked' : `${attempts.failures} failed`} />
        </div>
        <p className="st-item__meta">Rate limiting locks the account after {DEFAULT_SESSION_POLICY.maxFailedAttempts} failed attempts to resist brute force.</p>
        <div className="st-actions st-actions--split">
          <button type="button" className="btn tap" onClick={failLogin} disabled={locked} aria-disabled={locked}>Simulate failed sign-in</button>
          <button type="button" className="btn tap" onClick={succeedLogin}>Successful sign-in</button>
        </div>
      </section>

      <section className="st-panel">
        <h2 className="st-panel__title">Sensitive action</h2>
        <p className="st-item__meta">Sensitive actions require recent authentication (re-auth within {Math.round(DEFAULT_SESSION_POLICY.reauthWithinMs / 60000)} min).</p>
        <div className="st-actions">
          <button type="button" className="btn tap" onClick={attemptSensitive}>Change password</button>
        </div>
        {reauthOpen && (
          <div className="ui-banner ui-banner--warn" role="status">
            <span className="ui-banner__mark" aria-hidden>!</span>
            <span>Re-authentication required.&nbsp;</span>
            <button type="button" className="btn tap" onClick={confirmReauth}>Re-authenticate</button>
          </div>
        )}
        <p className="st-field__help">Biometric / native re-auth: {bio === 'available' ? 'available' : 'unavailable in this shell'}.</p>
      </section>

      <section className="st-panel">
        <h2 className="st-panel__title">Devices</h2>
        <ul className="st-list">
          {devices.map((d) => (
            <li className="st-item" key={d.deviceId}>
              <div>
                <div>{d.label}</div>
                <div className="st-item__meta">{d.current ? 'Current session' : 'Other device'}</div>
              </div>
              {d.revoked
                ? <StatusBadge status={chip('info')} label="Signed out" />
                : <button type="button" className="btn tap" onClick={() => revoke(d.deviceId)}>Sign out</button>}
            </li>
          ))}
        </ul>
      </section>

      <section className="st-panel" aria-label="Security activity">
        <h2 className="st-panel__title">Recent security activity</h2>
        {events.length === 0
          ? <EmptyState title="No recent events" hint="Sign-in, reset and device changes appear here." />
          : (
            <ul className="st-list">
              {events.map((e, i) => (
                <li className="st-item" key={i}>
                  <div>{SECURITY_EVENT_LABELS[e.type]}</div>
                  <span className="st-item__meta">{new Date(e.timestamp).toLocaleTimeString('en-IN')}</span>
                </li>
              ))}
            </ul>
          )}
      </section>
      <DpdpFootnote>Security events are audited; no raw tokens, OTPs or passwords are stored or logged</DpdpFootnote>
    </AuthScreen>
  );
}
