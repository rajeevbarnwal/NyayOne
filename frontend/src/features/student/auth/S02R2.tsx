import { useNavigate } from 'react-router-dom';
import { NyayOneRevLLockup } from './NyayOneRevLIcon';
import './S02R2.css';

/** Presentation preference only, never identity, account creation or consent. */
export function completeR2Onboarding(navigate: (path: string) => void, store?: Pick<Storage, 'setItem'>) {
  try { (store ?? window.localStorage).setItem('nyayone.r2.onboarding-seen', 'true'); }
  catch { /* Onboarding is optional even when storage is unavailable. */ }
  navigate('/s-03');
}

function OnboardingIcon({ name }: { name: 'grid' | 'brief' | 'book' | 'login' }) {
  return <svg viewBox="0 0 24 24" aria-hidden="true">
    {name === 'grid' && <><rect x="4" y="4" width="7" height="7" rx="1.8" fill="currentColor" opacity=".2"/><rect x="13" y="4" width="7" height="7" rx="1.8" fill="none" stroke="currentColor" strokeWidth="1.9"/><rect x="4" y="13" width="7" height="7" rx="1.8" fill="none" stroke="currentColor" strokeWidth="1.9"/><rect x="13" y="13" width="7" height="7" rx="1.8" fill="currentColor" opacity=".45"/></>}
    {name === 'brief' && <><rect x="3.5" y="7" width="17" height="12.5" rx="2.5" fill="currentColor" opacity=".16"/><rect x="3.5" y="7" width="17" height="12.5" rx="2.5" fill="none" stroke="currentColor" strokeWidth="1.9"/><path d="M9 7V5.5A1.5 1.5 0 0 1 10.5 4h3A1.5 1.5 0 0 1 15 5.5V7M3.5 12h17" fill="none" stroke="currentColor" strokeWidth="1.9"/></>}
    {name === 'book' && <><path d="M5 4.5h6a2 2 0 0 1 2 2V20a2 2 0 0 0-2-1.5H5z" fill="currentColor" opacity=".16"/><path d="M5 4.5h6a2 2 0 0 1 2 2V20a2 2 0 0 0-2-1.5H5zM19 4.5h-6a0 0 0 0 0 0 0V20a2 2 0 0 1 2-1.5h4z" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinejoin="round"/></>}
    {name === 'login' && <><path d="M10 4.5h6.5A1.5 1.5 0 0 1 18 6v12a1.5 1.5 0 0 1-1.5 1.5H10" fill="none" stroke="currentColor" strokeWidth="1.9" strokeLinecap="round"/><circle cx="10" cy="12" r="7.5" fill="currentColor" opacity=".12"/><path d="M3.5 12H13M10 8.5 13.5 12 10 15.5" fill="none" stroke="currentColor" strokeWidth="1.9" strokeLinecap="round" strokeLinejoin="round"/></>}
  </svg>;
}

function NotesIllustration() {
  return <svg className="s02-r2__motif" viewBox="0 0 300 200" role="img" aria-label="A page of case notes with one passage cited">
    <rect x="40" y="30" width="172" height="148" rx="14" fill="#FFFFFF" stroke="#D8D5E6" strokeWidth="2" transform="rotate(-5 126 104)"/>
    <rect x="74" y="16" width="190" height="168" rx="14" fill="#FFFFFF" stroke="#D8D5E6" strokeWidth="2"/>
    <rect x="94" y="38" width="2.5" height="128" rx="1.25" fill="#C89A3A" opacity=".5"/>
    <rect x="112" y="40" width="88" height="7" rx="3.5" fill="#2E3A8C" opacity=".85"/>
    {[[64,116,.5],[78,134,.45],[92,104,.5],[142,126,.45],[156,88,.5]].map(([y,width,opacity]) => <rect key={y} x="112" y={y} width={width} height="4" rx="2" fill="#B9B5CF" opacity={opacity}/>)}
    <rect x="106" y="104" width="132" height="26" rx="6" fill="#2E3A8C" opacity=".09"/>
    <rect x="112" y="110" width="112" height="4" rx="2" fill="#2E3A8C" opacity=".42"/>
    <rect x="112" y="121" width="90" height="2.5" rx="1.25" fill="#2E3A8C" opacity=".55"/>
    <circle cx="243" cy="108" r="11" fill="#2E3A8C"/>
    <text x="243" y="112.5" textAnchor="middle" fontFamily="Spline Sans Mono, monospace" fontSize="11" fontWeight="600" fill="#FFFFFF">1</text>
    <rect x="112" y="170" width="34" height="2.5" rx="1.25" fill="#C89A3A" opacity=".85"/>
    <path d="M236 16h20v40l-10-8-10 8z" fill="#C89A3A" opacity=".9"/>
  </svg>;
}

const POINTS = [
  { icon: 'grid', title: 'Your record, together', copy: 'Academics, interests and verified details in one profile you control.' },
  { icon: 'brief', title: 'Opportunities that fit', copy: 'Internships and clerkships filtered to your year, subjects and city.' },
  { icon: 'book', title: 'Read with the source', copy: 'Case digests keep the citation attached to every note you save.' },
] as const;

export function S02R2() {
  const navigate = useNavigate();
  const finish = () => completeR2Onboarding(navigate);
  return <section className="s02-r2" data-screen="S-02" data-nyayone-design="3.2.1-r2" aria-label="Welcome to NyayOne">
    <div className="s02-r2__brand">
      <div className="s02-r2__ring" aria-hidden="true"><svg viewBox="0 0 320 360"><rect x="16" y="20" width="272" height="324" rx="20" fill="none" stroke="currentColor" strokeWidth="2" opacity=".55"/><rect x="40" y="24" width="2.5" height="312" rx="1.25" fill="currentColor" opacity=".45"/>{Array.from({ length: 9 }, (_, i) => <rect key={i} x="40" y={54+i*30} width={220-(i%3)*42} height="5" rx="2.5" fill="currentColor" opacity=".5"/>)}</svg></div>
      <div className="s02-r2__lockup"><NyayOneRevLLockup reversed/></div>
      <div className="s02-r2__brandcopy">
        <div className="s02-r2__mobile"><h1>Keep your law-school record in one place.</h1><p>Profile, opportunities and case notes, together.</p></div>
        <div className="s02-r2__desktop"><div className="s02-r2__eyebrow">A legal workspace for students</div><h1>Learn the law.<br/>Build your path.</h1><p>One record of your academics, interests and verified details.</p><div className="s02-r2__benefits">{POINTS.map(point => <div key={point.icon}><i aria-hidden="true"/>{point.title}</div>)}</div></div>
      </div>
      <div className="s02-r2__legal"><span>Privacy Notice</span><span aria-hidden="true">·</span><span>Terms</span></div>
    </div>
    <div className="s02-r2__body"><div className="s02-r2__stack">
      <div className="s02-r2__illustration"><NotesIllustration/></div>
      <div><div className="s02-r2__eyebrow">Welcome to NyayOne</div><h1 className="s02-r2__title">Law school asks a lot.<br/>Keep it in one place.</h1></div>
      <div className="s02-r2__points">{POINTS.map(point => <div className="s02-r2__point" key={point.icon}><span className={`s02-r2__tile s02-r2__tile--${point.icon}`} aria-hidden="true"><OnboardingIcon name={point.icon}/></span><div><h2>{point.title}</h2><p>{point.copy}</p></div></div>)}</div>
      <div className="s02-r2__actions"><button type="button" className="s02-r2__continue" onClick={finish}><span aria-hidden="true"><OnboardingIcon name="login"/></span>Continue</button><button type="button" className="s02-r2__skip" onClick={finish}>Skip for now</button></div>
      <p className="s02-r2__footnote">Continue to NyayOne. No account is created at this step.</p>
      <div className="s02-r2__sr" role="status" aria-live="polite"/>
    </div></div>
  </section>;
}
