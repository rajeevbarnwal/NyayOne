import { profileAvatarLabel } from '../components';
import type { CSSProperties } from 'react';
import { useNavigate } from 'react-router-dom';
import { NyayOneRevLIcon, NyayOneRevLLockup } from '../auth/NyayOneRevLIcon';
import type { ProfileSection, StudentProfileProjection } from '../lib/profileApi';
import { profileResumeDestination } from './profileHooks';

const SECTIONS: ProfileSection[] = ['personal', 'academic', 'interests'];
const LABELS: Record<ProfileSection, string> = { personal: 'Personal', academic: 'Academic', interests: 'Interests' };

function ResumePlayIcon({ heading = false }: { heading?: boolean }) {
  return <span className={heading ? 'v321-profile__heading-icon v321-profile-resume__heading-icon' : 'v321-revl-icon'} aria-hidden="true"><svg width={heading ? 20 : 18} height={heading ? 20 : 18} viewBox="0 0 24 24" aria-hidden="true"><circle cx="12" cy="12" r="9" fill="currentColor" opacity=".14" /><circle cx="12" cy="12" r="9" fill="none" stroke="currentColor" strokeWidth="1.9" /><path d="M10 8.5 16 12l-6 3.5z" fill="currentColor" /></svg></span>;
}

/** Revision L S-13 presentation. All progress and destinations come from the server projection. */
export function ProfileResumeView({ projection }: { projection: StudentProfileProjection }) {
  const nav = useNavigate();
  const { firstName, middleName, lastName } = projection.profile.personal;
  const fullName = [firstName, middleName, lastName].filter(Boolean).join(' ');
  const initials = [firstName, lastName].map(name => [...name.trim()][0] ?? '').join('').toUpperCase();
  const remaining = SECTIONS.filter(section => !projection.completedSections.includes(section));
  const saved = SECTIONS.filter(section => projection.completedSections.includes(section));
  const current = projection.nextIncompleteSection;
  const resume = () => nav(profileResumeDestination(projection));
  return <section className="v321-profile" data-screen="S-13" aria-labelledby="S-13-title">
    <header className="v321-profile__header">
      <span className="v321-profile__desktop-brand"><NyayOneRevLLockup /></span>
      <span className="v321-profile__mobile-brand"><img src="/brand/nyayone-mark.svg" alt="NyayOne" draggable="false" /><b>Welcome back</b></span>
      <nav aria-label="Site" className="v321-profile__nav">
        <button type="button" onClick={() => nav('/s-14')}>Home</button>
        {['Research', 'Calendar', 'Careers'].map(label => <button type="button" key={label} disabled>{label}</button>)}
        <button type="button" onClick={() => nav('/s-17')}>Profile</button>
      </nav>
      <button type="button" className="v321-profile__avatar" aria-label={profileAvatarLabel(fullName, initials)} onClick={() => nav('/s-17')}><span>{initials || 'P'}</span></button>
    </header>
    <div className="v321-profile__layout">
      <div className="v321-profile-resume">
        <h1 className="v321-profile__title" id="S-13-title"><ResumePlayIcon heading />{projection.isComplete ? 'Your setup is complete' : 'Pick up where you left off.'}</h1>
        {!projection.isComplete && <section className="v321-profile-resume__card" aria-label="Profile completion">
          <span className="v321-profile-resume__ring" role="progressbar" aria-label="Profile setup progress" aria-valuemin={0} aria-valuemax={100} aria-valuenow={projection.completionPercent} data-testid="profile-completion-percent" style={{ '--resume-progress': `${projection.completionPercent}%` } as CSSProperties}><b>{projection.completionPercent}%</b></span>
          <div className="v321-profile-resume__summary"><b>Complete Your Profile</b><p>{remaining.map(section => LABELS[section]).join(' · ')} remaining{remaining.length === 1 && remaining[0] === 'interests' ? ' · about 1 minute.' : '.'}</p></div>
          <button type="button" className="v321-profile__button v321-profile-resume__finish" onClick={resume}><span className="v321-profile-resume__icon"><NyayOneRevLIcon name="checkc" /></span>Finish</button>
        </section>}
        <div className="v321-profile__actions v321-profile-resume__actions">
          <button type="button" className="v321-profile__button v321-profile__button--primary" onClick={resume}><ResumePlayIcon />{current ? 'Resume Setup' : 'Open dashboard'}</button>
          <button type="button" className="v321-profile__button" onClick={() => nav('/s-14')}><span className="v321-profile-resume__icon"><NyayOneRevLIcon name="home" /></span>Not Now</button>
        </div>
        <div className="v321-profile-resume__row v321-profile-resume__row--saved"><span>Saved</span><b>{saved.map(section => LABELS[section]).join(' · ') || 'None yet'}</b></div>
        <div className="v321-profile-resume__row" data-next-section={current ?? undefined}><span>Remaining</span><b>{remaining.map(section => `${LABELS[section]} (step ${SECTIONS.indexOf(section) + 1})`).join(' · ') || 'None'}</b></div>
      </div>
      <section className="v321-profile__aside" aria-label="About profile setup">
        <div className="v321-profile__card"><div className="v321-profile__eyebrow">Why complete your profile?</div><p>Internship matches, moot records and mentor suggestions all key off your college, year and interests. Two minutes now, better matches all year.</p></div>
        <div className="v321-profile__card"><div className="v321-profile__eyebrow">Privacy</div><p>Every field is private by default. Gold appears only when something is verified.</p></div>
      </section>
    </div>
  </section>;
}
