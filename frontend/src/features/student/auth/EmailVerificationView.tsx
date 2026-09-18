import type { ReactNode } from 'react';
import { useNavigate } from 'react-router-dom';
import type { StudentProfileProjection } from '../lib/profileApi';
import { NyayOneRevLIcon, NyayOneRevLLockup } from './NyayOneRevLIcon';

function VerificationIcon({ name, size = 18 }: { name: 'mail' | 'cap'; size?: number }) {
  return <svg width={size} height={size} viewBox="0 0 24 24" aria-hidden="true">
    {name === 'mail' ? <><rect x="3" y="5.5" width="18" height="13" rx="2.5" fill="currentColor" opacity=".14" /><rect x="3" y="5.5" width="18" height="13" rx="2.5" fill="none" stroke="currentColor" strokeWidth="1.9" /><path d="m4.5 8 7.5 5 7.5-5" fill="none" stroke="currentColor" strokeWidth="1.9" strokeLinecap="round" strokeLinejoin="round" /></> : <><path d="M12 4 22 9l-10 5L2 9z" fill="currentColor" opacity=".18" /><path d="M12 4 22 9l-10 5L2 9z" fill="none" stroke="currentColor" strokeWidth="1.9" strokeLinejoin="round" /><path d="M6 11.5V16c0 1.6 2.7 3 6 3s6-1.4 6-3v-4.5M22 9v5" fill="none" stroke="currentColor" strokeWidth="1.9" strokeLinecap="round" /></>}
  </svg>;
}

/** S-15 presentation only. The controller owns all profile/request authority. */
export function EmailVerificationFrame({ projection, children }: { projection?: StudentProfileProjection; children: ReactNode }) {
  const nav = useNavigate();
  const personal = projection?.profile.personal;
  const fullName = personal ? [personal.firstName, personal.middleName, personal.lastName].filter(Boolean).join(' ') : '';
  const initials = personal ? [personal.firstName, personal.lastName].map(name => [...name.trim()][0] ?? '').join('').toUpperCase() : '';
  return <section className="v321-profile" data-screen="S-15" aria-labelledby="S-15-title">
    <header className="v321-profile__header">
      <span className="v321-profile__desktop-brand"><NyayOneRevLLockup /></span>
      <span className="v321-profile__mobile-brand"><img src="/brand/nyayone-mark.svg" alt="NyayOne" draggable="false" /><b>Verification</b></span>
      <nav aria-label="Site" className="v321-profile__nav">
        <button type="button" onClick={() => nav('/s-14')}>Home</button>
        {['Research', 'Calendar', 'Careers'].map(label => <button type="button" key={label} disabled>{label}</button>)}
        <button type="button" onClick={() => nav('/s-17')}>Profile</button>
      </nav>
      <button type="button" className="v321-profile__avatar" aria-label={fullName ? `Your Profile · ${fullName}` : 'Your Profile'} onClick={() => nav('/s-17')}><span>{initials || 'P'}</span></button>
    </header>
    <div className="v321-profile__layout">
      <div className="v321-verification">
        <h1 className="v321-profile__title" id="S-15-title"><span className="v321-profile__heading-icon v321-verification__heading-icon" aria-hidden="true"><VerificationIcon name="mail" size={20} /></span>Verify your institutional email.</h1>
        {children}
      </div>
      <section className="v321-profile__aside" aria-label="About profile setup">
        <div className="v321-profile__card"><div className="v321-profile__eyebrow">Why complete your profile?</div><p>Internship matches, moot records and mentor suggestions all key off your college, year and interests. Two minutes now, better matches all year.</p></div>
        <div className="v321-profile__card"><div className="v321-profile__eyebrow">Privacy</div><p>Every field is private by default. Gold appears only when something is verified.</p></div>
      </section>
    </div>
  </section>;
}

export function EmailVerificationView({ projection, pending, errorMessage, requestSucceeded, request }: {
  projection: StudentProfileProjection; pending: boolean; errorMessage: string | null; requestSucceeded: boolean; request: () => void;
}) {
  const nav = useNavigate();
  const email = projection.profile.academic.institutionalEmail;
  const status = projection.institutionalEmailStatus;
  const verified = status === 'verified';
  const labels = { not_provided: 'Not provided', pending: 'Verification Pending', rejected: 'Verification rejected', verified: 'Verified', expired: 'Verification expired', revoked: 'Verification revoked' };
  return <EmailVerificationFrame projection={projection}>
    <dl className="v321-verification__field"><dt className="v321-verification__label"><span className="v321-revl-icon" aria-hidden="true"><VerificationIcon name="mail" /></span>Institutional Email</dt><dd className="v321-verification__saved">{email ?? 'Not provided'}</dd></dl>
    <div className={`v321-verification__status${verified ? ' is-verified' : ''}`}><span aria-hidden="true" />{labels[status]}</div>
    <div className="v321-verification__note"><NyayOneRevLIcon name="shield" framed={false} /><span>This status comes only from the server. Typing or saving an address never marks it verified.</span></div>
    {errorMessage && <div className="v321-verification__error" role="alert">{errorMessage}</div>}
    {requestSucceeded && <p className="v321-verification__message" role="status">Verification review request recorded. Verification remains pending until an authorized review succeeds.</p>}
    <div className="v321-profile__actions">
      {!email
        ? <button type="button" className="v321-profile__button v321-profile__button--primary" onClick={() => nav('/s-10?section=academic')}><NyayOneRevLIcon name="pen" />Add institutional email</button>
        : <button type="button" className="v321-profile__button v321-profile__button--primary" disabled={verified || pending} onClick={request}><NyayOneRevLIcon name="checkc" />{verified ? 'Already verified' : pending ? 'Recording request…' : 'Request verification review'}</button>}
      <button type="button" className="v321-profile__button" onClick={() => nav('/s-14')}><NyayOneRevLIcon name="home" />Back to dashboard</button>
    </div>
    <details className="v321-verification__disclosure"><summary><span className="v321-revl-icon" aria-hidden="true"><VerificationIcon name="cap" /></span>Unrecognised college domain?</summary><div>A request never grants verification; only an authorized review can do that. Verification uses the saved institutional email. No client action can grant verified status.</div></details>
  </EmailVerificationFrame>;
}
