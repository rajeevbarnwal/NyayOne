import { profileAvatarLabel } from '../components';
import type { CSSProperties, ReactNode } from 'react';
import { useNavigate } from 'react-router-dom';
import { NyayOneRevLIcon, NyayOneRevLLockup } from '../auth/NyayOneRevLIcon';
import { COLLEGE_OPTIONS, YEAR_OPTIONS, labelFor, toCanonicalCollege, toCanonicalYear } from '../lib/catalog';
import { profileSectionRoute, type InstitutionalEmailStatus, type StudentProfileProjection } from '../lib/profileApi';
import { profileResumeDestination } from './profileHooks';

const EMAIL_LABEL: Record<InstitutionalEmailStatus, string> = {
  not_provided: 'Email Not Provided', pending: 'Email Verification Pending', verified: 'Email Verified',
  rejected: 'Email Verification Rejected', expired: 'Email Verification Expired', revoked: 'Email Verification Revoked',
};

/** S-17 presentation only. Profile, email status and access authority stay server-owned. */
export function ProfileSummaryFrame({ projection, children }: { projection?: StudentProfileProjection; children: ReactNode }) {
  const nav = useNavigate();
  const personal = projection?.profile.personal;
  const fullName = personal ? [personal.firstName, personal.middleName, personal.lastName].filter(Boolean).join(' ') : '';
  const initials = personal ? [personal.firstName, personal.lastName].map(name => [...name.trim()][0] ?? '').join('').toUpperCase() : '';
  return <section className="v321-profile" data-screen="S-17" aria-labelledby="S-17-title">
    <header className="v321-profile__header">
      <span className="v321-profile__desktop-brand"><NyayOneRevLLockup /></span>
      <span className="v321-profile__mobile-brand"><img src="/brand/nyayone-mark.svg" alt="NyayOne" draggable="false" /><b>Profile</b></span>
      <nav aria-label="Site" className="v321-profile__nav">
        <button type="button" onClick={() => nav('/s-14')}>Home</button>
        {['Research', 'Calendar', 'Careers'].map(label => <button type="button" key={label} disabled>{label}</button>)}
        <button type="button" onClick={() => nav('/s-17')}>Profile</button>
      </nav>
      <button type="button" className="v321-profile__avatar" aria-label={profileAvatarLabel(fullName, initials)} onClick={() => nav('/s-17')}><span>{initials || 'P'}</span></button>
    </header>
    <div className="v321-profile__layout">
      <div className="v321-profile-summary">{children}</div>
      <section className="v321-profile__aside" aria-label="About profile setup">
        <div className="v321-profile__card"><div className="v321-profile__eyebrow">Why complete your profile?</div><p>Internship matches, moot records and mentor suggestions all key off your college, year and interests. Two minutes now, better matches all year.</p></div>
        <div className="v321-profile__card"><div className="v321-profile__eyebrow">Privacy</div><p>Every field is private by default. Gold appears only when something is verified.</p></div>
      </section>
    </div>
  </section>;
}

export function ProfileSummaryView({ projection, emailManagement, children }: {
  projection: StudentProfileProjection; emailManagement: ReactNode; children: ReactNode;
}) {
  const nav = useNavigate();
  const { personal, academic, interests } = projection.profile;
  const fullName = [personal.firstName, personal.middleName, personal.lastName].filter(Boolean).join(' ');
  const college = labelFor(COLLEGE_OPTIONS, toCanonicalCollege(academic.college));
  const year = labelFor(YEAR_OPTIONS, toCanonicalYear(academic.yearOfStudy));
  const sectionLabels = { personal: 'Personal', academic: 'Academic', interests: 'Interests' };
  const remaining = (['personal', 'academic', 'interests'] as const).filter(section => !projection.completedSections.includes(section));
  const rows: Array<[string, string, boolean?]> = [
    ['Mobile', 'Not available', true],
    ['Institutional Email', academic.institutionalEmail || 'Not provided'],
    ['City', personal.city || 'Not provided'],
    ['Interests', interests.interests.join(' · ') || 'Not provided'],
    ['Enrolment', academic.enrolmentNumber ? `${academic.enrolmentNumber} · private` : 'Not provided', true],
    ['Preferred language', personal.preferredLanguage ?? 'Not provided'],
    ['Guardian status', projection.guardian.status.replace(/_/gu, ' ')],
    ['Access', projection.accessMode],
  ];
  return <ProfileSummaryFrame projection={projection}>
    <div className="v321-profile-summary__identity">
      <span className="v321-profile-summary__seal" aria-hidden="true"><img src="/brand/nyayone-mark.svg" alt="" draggable="false" /></span>
      <div className="v321-profile-summary__name"><h1 id="S-17-title">{fullName || 'Your profile'}</h1><p>{[college, year].filter(Boolean).join(' · ') || 'Academic details not provided'}</p></div>
      <span className="v321-profile-summary__spacer" aria-hidden="true" />
      <button type="button" className="v321-profile-summary__edit" aria-label={projection.isComplete ? 'Edit profile' : 'Continue profile'} onClick={() => nav(profileSectionRoute(projection.nextIncompleteSection ?? 'personal'))}><svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.9" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><path d="M4 20l4-1L19.5 7.5a2 2 0 0 0-3-3L5 16z" /></svg></button>
    </div>
    <div className="v321-profile-summary__chips">
      <span className={`v321-profile-summary__chip v321-profile-summary__chip--${projection.institutionalEmailStatus === 'verified' ? 'verified' : 'pending'}`}><i aria-hidden="true" />{EMAIL_LABEL[projection.institutionalEmailStatus]}</span>
      <span className="v321-profile-summary__chip v321-profile-summary__chip--completion"><i aria-hidden="true" />Profile {projection.completionPercent}%</span>
    </div>
    {!projection.isComplete && <section className="v321-profile-summary__completion" data-testid="profile-completion-card" aria-label="Profile completion">
      <span className="v321-profile-summary__ring" role="progressbar" aria-label="Profile setup progress" aria-valuemin={0} aria-valuemax={100} aria-valuenow={projection.completionPercent} data-testid="profile-completion-percent" style={{ '--profile-progress': `${projection.completionPercent}%` } as CSSProperties}><b>{projection.completionPercent}%</b></span>
      <div className="v321-profile-summary__remaining"><b>Complete Your Profile</b><p>{remaining.map(section => sectionLabels[section]).join(' · ')} remaining{remaining.length === 1 && remaining[0] === 'interests' ? ' · about 1 minute.' : '.'}</p></div>
      <button type="button" className="v321-profile__button v321-profile-summary__finish" onClick={() => nav(profileResumeDestination(projection))}><span className="v321-profile-summary__finish-icon" aria-hidden="true"><NyayOneRevLIcon name="checkc" /></span>Finish</button>
    </section>}
    <dl className="v321-profile-summary__details">
      {rows.map(([label, value, mono]) => <div className="v321-profile-summary__row" key={label}><dt>{label}</dt><dd className={mono ? 'is-mono' : undefined}>{value}{label === 'Institutional Email' && emailManagement}</dd></div>)}
    </dl>
    {children}
    <div className="v321-profile-summary__privacy"><div><b>Privacy &amp; settings</b><p>Review your privacy preferences and account settings.</p></div><button type="button" className="v321-profile__button" aria-label="Privacy Centre" onClick={() => nav('/s-19')}><span className="v321-profile-summary__privacy-icon" aria-hidden="true"><span className="v321-profile-summary__glyph"><svg width="18" height="18" viewBox="0 0 24 24" aria-hidden="true"><path d="M12 3.5 5 6v5.2c0 4.4 3 7.4 7 9.3 4-1.9 7-4.9 7-9.3V6z" fill="currentColor" opacity=".14" /><path d="M12 3.5 5 6v5.2c0 4.4 3 7.4 7 9.3 4-1.9 7-4.9 7-9.3V6z" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinejoin="round" /><path d="m9.2 11.8 2 2 3.6-3.8" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" /></svg></span></span>Privacy Centre</button></div>
  </ProfileSummaryFrame>;
}
