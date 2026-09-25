import { useEffect, useRef } from 'react';
import type { StudentSessionPhase } from '../../../app/authContext';
import { NyayOneRevLIcon, NyayOneRevLLockup } from './NyayOneRevLIcon';
import './S01R2.css';

/** Boolean presentation preference only: never identity, consent or session authority.
 * S-02's subsequent screen PR will write this after showing onboarding.
 * Old LegalSaathi markers are intentionally not read or migrated.
 */
export function readR2OnboardingSeen(store?: Pick<Storage, 'getItem'>): boolean {
  try { return (store ?? window.localStorage).getItem('nyayone.r2.onboarding-seen') === 'true'; }
  catch { return false; }
}

/** R2 presentation only. Session authority and automatic navigation stay in V34Splash. */
export function S01R2({ phase, retry }: { phase: StudentSessionPhase; retry: () => void }) {
  const failed = phase === 'unavailable';
  const resolved = phase === 'authenticated';
  const retryRef = useRef<HTMLButtonElement>(null);
  const retryRequested = useRef(false);
  useEffect(() => {
    if (failed && retryRequested.current) {
      retryRequested.current = false;
      retryRef.current?.focus();
    }
  }, [failed]);
  return <section className="s01-r2" data-screen="S-01" data-nyayone-design="3.2.1-r2" aria-label="NyayOne session check">
    <div className="s01-r2__body">
      {failed ? <>
        <span className="s01-r2__tile s01-r2__tile--error" aria-hidden="true">
          <svg viewBox="0 0 24 24" focusable="false">
            <circle cx="9" cy="9" r="3.2" fill="currentColor" opacity=".16"/>
            <circle cx="9" cy="9" r="3.2" fill="none" stroke="currentColor" strokeWidth="1.8"/>
            <path d="M3.5 19a5.5 5.5 0 0 1 11 0" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round"/>
            <path d="M17 8.5l4 1.6v2.6c0 2.3-1.7 4-4 5.1-.9-.4-1.7-1-2.4-1.6" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinejoin="round"/>
          </svg>
        </span>
        <div role="alert"><h1>We could not reach NyayOne.</h1><p>Check your connection and try again. Nothing on your account has changed.</p></div>
        <button ref={retryRef} type="button" onClick={() => { retryRequested.current = true; retry(); }}><NyayOneRevLIcon name="refresh"/>Try again</button>
      </> : <>
        {resolved
          ? <span className="s01-r2__tile s01-r2__tile--success" aria-hidden="true"><NyayOneRevLIcon name="checkc" framed={false}/></span>
          : <span className="s01-r2__lockup"><NyayOneRevLLockup/></span>}
        <div className="s01-r2__status" role="status">{resolved ? 'Session confirmed. Opening your workspace…' : 'Checking your session…'}</div>
        <div className="s01-r2__bar" role="progressbar" aria-label={resolved ? 'Opening your workspace' : 'Checking your session'} aria-busy="true"><i/></div>
      </>}
    </div>
  </section>;
}
