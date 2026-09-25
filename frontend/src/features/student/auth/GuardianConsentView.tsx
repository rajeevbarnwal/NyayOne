import { profileAvatarLabel } from '../components';
import type { ReactNode } from 'react';
import { useNavigate } from 'react-router-dom';
import { profileSectionRoute, type StudentProfileProjection } from '../lib/profileApi';
import { NyayOneRevLIcon, NyayOneRevLLockup } from './NyayOneRevLIcon';

function GuardianIcon({ size = 18 }: { size?: number }) {
  return <svg width={size} height={size} viewBox="0 0 24 24" aria-hidden="true"><circle cx="9" cy="9" r="3.2" fill="currentColor" opacity=".16" /><circle cx="9" cy="9" r="3.2" fill="none" stroke="currentColor" strokeWidth="1.8" /><path d="M3.5 19a5.5 5.5 0 0 1 11 0" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" /><path d="M17 8.5l4 1.6v2.6c0 2.3-1.7 4-4 5.1-.9-.4-1.7-1-2.4-1.6" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" /></svg>;
}

/** S-16 presentation only: the server projection remains the sole access authority. */
export function GuardianConsentFrame({ projection, title, children }: { projection?: StudentProfileProjection; title: string; children: ReactNode }) {
  const nav = useNavigate();
  const personal = projection?.profile.personal;
  const fullName = personal ? [personal.firstName, personal.middleName, personal.lastName].filter(Boolean).join(' ') : '';
  const initials = personal ? [personal.firstName, personal.lastName].map(name => [...name.trim()][0] ?? '').join('').toUpperCase() : '';
  return <section className="v321-profile" data-screen="S-16" aria-labelledby="S-16-title">
    <header className="v321-profile__header">
      <span className="v321-profile__desktop-brand"><NyayOneRevLLockup /></span>
      <span className="v321-profile__mobile-brand"><img src="/brand/nyayone-mark.svg" alt="NyayOne" draggable="false" /><b>Guardian consent</b></span>
      <nav aria-label="Site" className="v321-profile__nav">
        <button type="button" onClick={() => nav('/s-14')}>Home</button>
        {['Research', 'Calendar', 'Careers'].map(label => <button type="button" key={label} disabled>{label}</button>)}
        <button type="button" onClick={() => nav('/s-17')}>Profile</button>
      </nav>
      <button type="button" className="v321-profile__avatar" aria-label={profileAvatarLabel(fullName, initials)} onClick={() => nav('/s-17')}><span>{initials || 'P'}</span></button>
    </header>
    <div className="v321-profile__layout">
      <div className="v321-guardian">
        <h1 className="v321-profile__title" id="S-16-title"><span className="v321-profile__heading-icon v321-guardian__heading-icon" aria-hidden="true"><GuardianIcon size={20} /></span>{title}</h1>
        {children}
      </div>
      <section className="v321-profile__aside" aria-label="About profile setup">
        <div className="v321-profile__card"><div className="v321-profile__eyebrow">Why complete your profile?</div><p>Internship matches, moot records and mentor suggestions all key off your college, year and interests. Two minutes now, better matches all year.</p></div>
        <div className="v321-profile__card"><div className="v321-profile__eyebrow">Privacy</div><p>Every field is private by default. Gold appears only when something is verified.</p></div>
      </section>
    </div>
  </section>;
}

export function GuardianConsentView({ projection }: { projection: StudentProfileProjection }) {
  const nav = useNavigate();
  const guardianPending = projection.guardian.required && projection.guardian.status !== 'verified';
  const labels = { not_required: 'Limited access', required_pending: 'Consent required', rejected: 'Consent rejected', revoked: 'Consent revoked', verified: 'Guardian consent verified' };
  return <GuardianConsentFrame projection={projection} title={guardianPending ? 'A guardian’s consent is needed first.' : 'Your account has limited access.'}>
    <p className="v321-guardian__intro">{guardianPending ? 'Guardian consent is required before community and sharing access can be enabled. No client action can mark consent verified.' : 'Your server-issued profile currently has limited access.'}</p>
    {guardianPending && <>
      <dl className="v321-guardian__field"><dt><NyayOneRevLIcon name="users" />Guardian’s Name</dt><dd>Not available</dd></dl>
      <dl className="v321-guardian__field"><dt><NyayOneRevLIcon name="sim" />Guardian’s Mobile</dt><dd>Not available</dd></dl>
      <p className="v321-guardian__help">Guardian contact details and consent requests are not available here. Access changes only after server verification.</p>
    </>}
    <div className={`v321-guardian__status${projection.guardian.status === 'verified' ? ' is-verified' : ''}`}><span aria-hidden="true" />{labels[projection.guardian.status]}</div>
    <div className="v321-profile__actions">
      <button type="button" className="v321-profile__button v321-profile__button--primary" onClick={() => nav(profileSectionRoute(projection.nextIncompleteSection))}><NyayOneRevLIcon name="pen" />Continue profile</button>
      <button type="button" className="v321-profile__button" onClick={() => nav('/s-14')}><NyayOneRevLIcon name="home" />View limited home</button>
    </div>
    <p className="v321-guardian__help">Disabled capabilities: {projection.disabledCapabilities.join(', ') || 'none'}.</p>
    <p className="v321-guardian__help">Minor-account checks run server-side · data minimised</p>
  </GuardianConsentFrame>;
}
