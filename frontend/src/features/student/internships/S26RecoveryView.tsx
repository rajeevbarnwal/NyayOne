import { useCallback, useLayoutEffect, useRef, useState, type RefObject } from 'react';
import { NyayOneRevLLockup } from '../auth/NyayOneRevLIcon';
import { Icon } from './S20BrowseView';
import './S26Recovery.css';

export type S26Focus = { anchor?: HTMLElement } | null;
type Action = { trigger: HTMLElement };
export interface S26RecoveryViewProps {
  focus: RefObject<S26Focus>;
  phase: 'empty' | 'loading' | 'error' | 'nonempty' | 'anonymous' | 'forbidden' | 'unavailable';
  count: number; refreshing: boolean; statusCode: number | null; offline: boolean; attempt: number;
  onNavigate: (path: string) => void; onRetry: () => Promise<unknown>;
}
export function S26RecoveryView(p: S26RecoveryViewProps) {
  const root = useRef<HTMLDivElement>(null), action = useRef<Action | null>(null), initial = useRef(true);
  const [completed, setCompleted] = useState<Action | null>(null);
  // React detaches this ref before removing the result button. Transfer only
  // focus actually owned by that disappearing control; a background refresh
  // must not acquire ownership when focus is elsewhere (or voluntarily blurred).
  const resultAction = useCallback((node: HTMLButtonElement | null) => {
    if (!node) return;
    return () => { if (document.activeElement === node) p.focus.current = {}; };
  }, [p.focus]);
  useLayoutEffect(() => {
    const host = root.current;
    return () => { if (host?.contains(document.activeElement)) p.focus.current = {}; };
  }, [p.focus]);
  useLayoutEffect(() => {
    const host = root.current; if (!host) return;
    const alert = host.querySelector<HTMLElement>('[role="alert"]'), heading = host.querySelector<HTMLElement>('h1');
    const handoff = p.focus.current;
    if (handoff) {
      if (document.activeElement === document.body || document.activeElement === handoff.anchor) {
        const target = alert ?? heading; target?.focus({ preventScroll: true }); handoff.anchor = target ?? undefined;
        if (p.phase !== 'loading') p.focus.current = null;
      } else p.focus.current = null;
    }
    if (initial.current && p.phase !== 'loading') {
      initial.current = false;
      if (alert && document.activeElement === document.body) alert.focus({ preventScroll: true });
    }
    const owned = action.current; if (!owned) return;
    if (document.activeElement !== owned.trigger && document.activeElement !== document.body) { action.current = null; return; }
    if (completed !== owned || p.refreshing) return;
    (alert ?? heading)?.focus({ preventScroll: true }); action.current = null;
  });
  async function retry(trigger: HTMLElement) {
    if (action.current || p.refreshing) return;
    const owned = { trigger }; action.current = owned; trigger.focus({ preventScroll: true });
    try { await p.onRetry(); } finally { setCompleted(owned); }
  }
  const access = ['anonymous', 'forbidden', 'unavailable'].includes(p.phase);
  return <div className="v321-internships s26-recovery" data-screen="S-26" data-v34-screen="S-26" ref={root}
    onBlurCapture={e => {
      // A voluntary move (including blur to the body) relinquishes the temporary
      // loading anchor, so a later network result cannot take focus back.
      if (p.focus.current?.anchor === e.target) p.focus.current = null;
    }}>
    <header className="s20-header"><img className="s20-mark" src="/brand/nyayone-mark.svg" alt="NyayOne" width="30" height="30"/><span className="s20-mobile-title">Saved</span><div className="s20-lockup"><NyayOneRevLLockup/></div>
      <nav aria-label="Site"><button onClick={() => p.onNavigate('/s-14')}>Home</button><span>Research</span><span>Calendar</span><span aria-current="page">Careers</span><button onClick={() => p.onNavigate('/s-17')}>Profile</button></nav>
      <button className="s20-avatar" aria-label="Your Profile" onClick={() => p.onNavigate('/s-17')}><span><Icon name="person"/></span></button>
    </header>
    <div className="s20-layout"><main id="main-content">
      <h1 tabIndex={-1}><span className="s20-heading-icon"><Icon name="bookmark"/></span>Saved internships.</h1>
      {p.phase === 'loading' && <div className="s20-skeletons" role="status" aria-label="Loading saved internships">{[1, 2].map(i => <div key={i}/>)}</div>}
      {access && <section className="s20-empty" role="alert" tabIndex={-1}><h2>{p.phase === 'anonymous' ? 'Sign in to view saved internships' : p.phase === 'forbidden' ? 'Student account required' : 'Saved internships unavailable'}</h2>
        <p>{p.phase === 'forbidden' ? 'Saved internships are available only to student accounts.' : 'Your private saved list is tied to your student account. Sign in to confirm access.'}</p>
        {p.phase !== 'forbidden' && <button className="s20-btn s20-primary" onClick={() => p.onNavigate('/s-03')}>Go to sign in</button>}
      </section>}
      {p.phase === 'error' && <section className="s20-empty" role="alert" tabIndex={-1}>
        <span className="s20-state-icon s20-risk"><Icon name="warn"/></span><h2>Could not check your saved list.</h2>
        <p key={p.attempt}>{p.offline ? 'You are offline. No request was sent. Reconnect and retry.' : 'No empty state is shown until the server answers.'}</p>
        {!p.offline && p.statusCode !== null && <div className="s20-code">HTTP {p.statusCode}</div>}
        <div className="s20-actions"><button className="s20-btn s20-primary" aria-disabled={p.refreshing} aria-busy={p.refreshing || undefined} onClick={e => void retry(e.currentTarget)}><span className="s20-action-icon"><Icon name="refresh" size={18}/></span>Retry</button></div>
      </section>}
      {(p.phase === 'empty' || p.phase === 'nonempty') && <section className="s20-empty">
        <span className={`s20-state-icon ${p.phase === 'empty' ? 's20-indigo' : 's26-positive'}`}><Icon name="bookmark"/></span>
        <h2>{p.phase === 'empty' ? 'No saved internships yet.' : `You have ${p.count} saved internship${p.count === 1 ? '' : 's'}.`}</h2>
        <p>{p.phase === 'empty' ? 'Saved listings appear here with their closing dates.' : 'Your list is not empty. Open it to continue.'}</p>
        <div className="s20-actions"><button ref={resultAction} className="s20-btn s20-primary" onClick={() => p.onNavigate(p.phase === 'empty' ? '/s-20' : '/s-25')}><span className="s20-action-icon"><Icon name={p.phase === 'empty' ? 'brief' : 'bookmark'} size={18}/></span>{p.phase === 'empty' ? 'Browse internships' : 'Open saved internships'}</button></div>
      </section>}
    </main><aside aria-label="Saved internships recovery context"><section className="s20-card"><div className="s20-eyebrow">When this appears</div><p>Shown only when the saved query really returned nothing. Loading and failure never pretend to be empty.</p></section></aside></div>
    <footer><span>Privacy Notice</span><span>·</span><span>Terms</span><span>·</span><span>Accessibility</span></footer>
  </div>;
}
