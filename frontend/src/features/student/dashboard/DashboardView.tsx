import { profileAvatarLabel } from '../components';
import type { CSSProperties, ReactNode, RefObject } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { NyayOneRevLIcon, NyayOneRevLLockup } from '../auth/NyayOneRevLIcon';
import { availableModules } from '../lib/dashboard';
import type { ProfileSection, StudentProfileProjection } from '../lib/profileApi';
import { profileResumeDestination } from '../profile/profileHooks';

function DashboardIcon({ name }: { name: 'brief' | 'moot' | 'book' | 'users' }) {
  if (name === 'users') return <NyayOneRevLIcon name="users" />;
  const line = { fill: 'none', stroke: 'currentColor', strokeWidth: 1.9 };
  return <svg width="15" height="15" viewBox="0 0 24 24" aria-hidden="true">
    {name === 'brief' && <><rect x="3.5" y="7" width="17" height="12.5" rx="2.5" fill="currentColor" opacity=".16" /><rect x="3.5" y="7" width="17" height="12.5" rx="2.5" {...line} /><path d="M9 7V5.5A1.5 1.5 0 0 1 10.5 4h3A1.5 1.5 0 0 1 15 5.5V7M3.5 12h17" {...line} /></>}
    {name === 'moot' && <><rect x="9.3" y="3.5" width="5.4" height="10.5" rx="2.7" fill="currentColor" opacity=".2" /><rect x="9.3" y="3.5" width="5.4" height="10.5" rx="2.7" {...line} /><path d="M6 11.5a6 6 0 0 0 12 0M12 17.5V20" {...line} strokeLinecap="round" /></>}
    {name === 'book' && <><path d="M5 4.5h6a2 2 0 0 1 2 2V20a2 2 0 0 0-2-1.5H5z" fill="currentColor" opacity=".16" /><path d="M5 4.5h6a2 2 0 0 1 2 2V20a2 2 0 0 0-2-1.5H5zM19 4.5h-6a0 0 0 0 0 0 0V20a2 2 0 0 1 2-1.5h4z" {...line} strokeWidth="1.8" strokeLinejoin="round" /></>}
  </svg>;
}

export function DashboardFrame({ projection, children }: { projection?: StudentProfileProjection; children: ReactNode }) {
  const nav = useNavigate();
  const personal = projection?.profile.personal;
  const fullName = personal ? [personal.firstName, personal.middleName, personal.lastName].filter(Boolean).join(' ') : '';
  const initials = personal ? [personal.firstName, personal.lastName].map(name => [...name.trim()][0] ?? '').join('').toUpperCase() : '';
  return <section className="v321-profile" data-screen="S-14" aria-labelledby="S-14-title">
    <header className="v321-profile__header">
      <span className="v321-profile__desktop-brand"><NyayOneRevLLockup /></span>
      <span className="v321-profile__mobile-brand"><img src="/brand/nyayone-mark.svg" alt="NyayOne" draggable="false" /><b>NyayOne</b></span>
      <nav aria-label="Site" className="v321-profile__nav">
        <button type="button" aria-current="page" onClick={() => nav('/s-14')}>Home</button>
        <button type="button" disabled>Research</button>
        <button type="button" onClick={() => nav('/s-90')}>Calendar</button>
        <button type="button" onClick={() => nav('/s-20')}>Careers</button>
        <button type="button" onClick={() => nav('/s-17')}>Profile</button>
      </nav>
      <button type="button" className="v321-profile__avatar" aria-label={profileAvatarLabel(fullName, initials)} onClick={() => nav('/s-17')}><span>{initials || 'P'}</span></button>
    </header>
    <div className="v321-profile__layout">
      <div className="v321-dashboard">{children}</div>
      <section className="v321-profile__aside" aria-label="About profile setup">
        <div className="v321-profile__card"><div className="v321-profile__eyebrow">Why complete your profile?</div><p>Internship matches, moot records and mentor suggestions all key off your college, year and interests. Two minutes now, better matches all year.</p></div>
        <div className="v321-profile__card"><div className="v321-profile__eyebrow">Privacy</div><p>Every field is private by default. Gold appears only when something is verified.</p></div>
      </section>
    </div>
  </section>;
}

const SECTION_LABELS: Record<ProfileSection, string> = { personal: 'Personal', academic: 'Academic', interests: 'Interests' };

/** Revision L presentation; identity, completion, verification and release authority remain live. */
export function DashboardOverview({ projection, dateLabel, headingRef }: {
  projection: StudentProfileProjection;
  dateLabel: string;
  headingRef: RefObject<HTMLHeadingElement | null>;
}) {
  const nav = useNavigate();
  const remaining = (['personal', 'academic', 'interests'] as const).filter(section => !projection.completedSections.includes(section));
  const internships = availableModules().find(module => module.id === 'internships');
  return <>
    <div className="st-eyebrow v321-profile__eyebrow v321-dashboard__date">{dateLabel} · Home</div>
    <h1 className="v321-profile__title" id="S-14-title" ref={headingRef} tabIndex={-1}>Your legal journey, in one place.</h1>
    <p className="v321-dashboard__intro">Continue your law-school record: internships, moots, research and mentors.</p>
    {projection.accessMode === 'limited' && <div className="v321-dashboard__note"><NyayOneRevLIcon name="shield" /><span><b>Limited access.</b> Community and sharing stay off until guardian consent is recorded. <Link to="/s-16">Guardian Consent</Link></span></div>}
    {!projection.isComplete && <section className="v321-dashboard__completion" data-testid="profile-completion-card" aria-label="Profile completion">
      <span className="v321-dashboard__ring" role="progressbar" aria-label="Profile setup progress" aria-valuemin={0} aria-valuemax={100} aria-valuenow={projection.completionPercent} data-testid="profile-completion-percent" style={{ '--dashboard-progress': `${projection.completionPercent}%` } as CSSProperties}><b>{projection.completionPercent}%</b></span>
      <div className="v321-dashboard__summary"><b>Complete Your Profile</b><p>{remaining.map(section => SECTION_LABELS[section]).join(' · ')} remaining{remaining.length === 1 && remaining[0] === 'interests' ? ' · about 1 minute.' : '.'}</p></div>
      <Link className="v321-profile__button v321-dashboard__finish" to={profileResumeDestination(projection)}><NyayOneRevLIcon name="checkc" />Finish</Link>
    </section>}
    <div className="v321-dashboard__tiles">
      <button type="button" disabled={!internships} className="v321-dashboard__tile" onClick={() => { if (internships) nav(internships.route); }}><span className="v321-dashboard__tile-title" role="heading" aria-level={2}><span className="v321-dashboard__tile-icon" aria-hidden="true"><DashboardIcon name="brief" /></span>Internships</span><span>Explore internships and track your applications.</span><small>{internships ? 'Open internships' : 'Coming soon'}</small></button>
      <button type="button" disabled className="v321-dashboard__tile"><span className="v321-dashboard__tile-title" role="heading" aria-level={2}><span className="v321-dashboard__tile-icon v321-dashboard__tile-icon--moot" aria-hidden="true"><DashboardIcon name="moot" /></span>Moot Court</span><span>Moot preparation and records.</span><small>Coming soon</small></button>
      <button type="button" disabled className="v321-dashboard__tile"><span className="v321-dashboard__tile-title" role="heading" aria-level={2}><span className="v321-dashboard__tile-icon v321-dashboard__tile-icon--book" aria-hidden="true"><DashboardIcon name="book" /></span>Research</span><span>Research tools for your law-school work.</span><small>Coming soon</small></button>
      <button type="button" disabled className="v321-dashboard__tile"><span className="v321-dashboard__tile-title" role="heading" aria-level={2}><span className="v321-dashboard__tile-icon v321-dashboard__tile-icon--users" aria-hidden="true"><DashboardIcon name="users" /></span>Mentors</span><span>Mentor discovery and guidance.</span><small>Coming soon</small></button>
    </div>
    <div className="v321-dashboard__note v321-dashboard__verification">
      <NyayOneRevLIcon framed={false} name={projection.institutionalEmailStatus === 'verified' ? 'checkc' : 'shield'} />
      <span>{projection.institutionalEmailStatus === 'verified' ? 'Institutional email verified.' : 'Institutional email not verified yet, so some listings stay locked.'}</span>
      {projection.institutionalEmailStatus !== 'verified' && <Link className="v321-profile__button v321-dashboard__verify" to="/s-15"><NyayOneRevLIcon name="badge" />Verify Now</Link>}
    </div>
  </>;
}
