import { useLayoutEffect, useRef, useState, type RefObject } from 'react';
import { NyayOneRevLLockup } from '../auth/NyayOneRevLIcon';
import type { InternshipListing } from '../lib/internships';
import { Icon } from './S20BrowseView';
import './S25Saved.css';

export type S25Focus = { anchor?: HTMLElement } | null;
type Action = { trigger: HTMLElement; anchor: HTMLElement; index: number };
export interface S25SavedViewProps {
  focus: RefObject<S25Focus>;
  phase: 'loading' | 'list' | 'empty' | 'error' | 'anonymous' | 'forbidden' | 'unavailable';
  items: InternshipListing[]; pendingId: string | null; refreshing: boolean;
  failure: string; notice: string; uncertain: boolean; statusCode: number | null;
  onNavigate: (path: string) => void; onRemove: (item: InternshipListing) => Promise<unknown>; onRetry: () => Promise<unknown>;
}
export function S25SavedView(p: S25SavedViewProps) {
  const root = useRef<HTMLDivElement>(null), action = useRef<Action | null>(null);
  const [completed, setCompleted] = useState<Action | null>(null);
  const initial = useRef(true);
  useLayoutEffect(() => {
    const host = root.current;
    return () => { if (host?.contains(document.activeElement)) p.focus.current = {}; };
  }, [p.focus]);
  useLayoutEffect(() => {
    const host = root.current; if (!host) return;
    const error = host.querySelector<HTMLElement>('[role="alert"]'), heading = host.querySelector<HTMLElement>('h1');
    const handoff = p.focus.current;
    if (handoff) {
      if (document.activeElement === document.body || document.activeElement === handoff.anchor) {
        const target = error ?? heading; target?.focus({ preventScroll: true }); handoff.anchor = target ?? undefined;
        if (p.phase !== 'loading') p.focus.current = null;
      } else p.focus.current = null;
    }
    if (initial.current && p.phase !== 'loading') {
      initial.current = false;
      if (error && document.activeElement === document.body) error.focus({ preventScroll: true });
    }
    const owned = action.current;
    if (!owned) return;
    if (![owned.trigger, owned.anchor, document.body].includes(document.activeElement as HTMLElement)) { action.current = null; return; }
    if (completed !== owned || p.pendingId || p.refreshing || p.phase === 'loading') return;
    const controls = [...host.querySelectorAll<HTMLElement>('[data-remove-id]')];
    const next = controls[Math.min(owned.index, controls.length - 1)];
    (error ?? (owned.trigger.isConnected ? owned.trigger : next ?? heading))?.focus({ preventScroll: true });
    action.current = null;
  });
  async function perform(run: () => Promise<unknown>, trigger: HTMLElement, index = 0, retry = false) {
    if (action.current || p.pendingId || p.refreshing) return;
    // A no-data retry replaces its card with loading skeletons. Move to the
    // persistent heading before dispatch, not after its button is detached.
    const anchor = retry ? root.current?.querySelector<HTMLElement>('h1') ?? trigger : trigger;
    const owned = { trigger, anchor, index: retry ? -1 : index }; action.current = owned; anchor.focus({ preventScroll: true });
    try { await run(); } finally { setCompleted(owned); }
  }
  const browse = <button className="s20-btn" onClick={() => p.onNavigate('/s-20')}><span className="s20-action-icon s20-indigo"><Icon name="brief"/></span>Browse internships</button>;
  const access = ['anonymous', 'forbidden', 'unavailable'].includes(p.phase);
  const blocked = !!p.pendingId || p.refreshing || p.uncertain;
  return <div className="v321-internships s25-saved" data-screen="S-25" data-v34-screen="S-25" ref={root}>
    <header className="s20-header"><img className="s20-mark" src="/brand/nyayone-mark.svg" alt="NyayOne" width="30" height="30"/><span className="s20-mobile-title">Saved</span><div className="s20-lockup"><NyayOneRevLLockup/></div>
      <nav aria-label="Site"><button onClick={() => p.onNavigate('/s-14')}>Home</button><span>Research</span><span>Calendar</span><span aria-current="page">Careers</span><button onClick={() => p.onNavigate('/s-17')}>Profile</button></nav>
      <button className="s20-avatar" aria-label="Your Profile" onClick={() => p.onNavigate('/s-17')}><span><Icon name="person"/></span></button>
    </header>
    <div className="s20-layout"><main id="main-content">
      <div><h1 tabIndex={-1}><span className="s20-heading-icon"><Icon name="bookmark"/></span>Saved internships.</h1><p className="s20-sub">Listings in your saved list.</p></div>
      <div className="s20-related">{browse}</div>
      {p.phase === 'loading' && <div className="s20-skeletons" role="status" aria-label="Loading saved internships">{[1, 2, 3].map(i => <div key={i}/>)}</div>}
      {access && <section className="s20-empty" role="alert" tabIndex={-1}><h2>{p.phase === 'anonymous' ? 'Sign in to view saved internships' : p.phase === 'forbidden' ? 'Student account required' : 'Saved internships unavailable'}</h2>
        <p>{p.phase === 'forbidden' ? 'Saved internships are available only to student accounts.' : 'Your private saved list is tied to your student account. Sign in to confirm access.'}</p>
        {p.phase !== 'forbidden' && <button className="s20-btn s20-primary" onClick={() => p.onNavigate('/s-03')}>Go to sign in</button>}
      </section>}
      {p.phase === 'error' && <section className="s20-empty" role="alert" tabIndex={-1}><span className="s20-state-icon s20-risk"><Icon name="warn"/></span><h2>Your saved list did not load.</h2><p>No saved-list claim is made until the server confirms it.</p>
        {p.statusCode !== null && <div className="s20-code">HTTP {p.statusCode}</div>}
        <button className="s20-btn s20-primary" aria-disabled={p.refreshing} aria-busy={p.refreshing || undefined} onClick={e => void perform(p.onRetry, e.currentTarget, 0, true)}><span className="s20-action-icon"><Icon name="refresh"/></span>Retry</button>
      </section>}
      {p.failure && !access && <section className="s20-note" role="alert" tabIndex={-1}><Icon name="warn"/><div><b>{p.failure}</b>
        {p.uncertain && <><p>Any listings below are the last known list, not a confirmation of saved state.</p><button className="s20-btn" aria-disabled={p.refreshing} aria-busy={p.refreshing || undefined} onClick={e => void perform(p.onRetry, e.currentTarget, 0, true)}><span className="s20-action-icon"><Icon name="refresh"/></span>Reload saved list</button></>}
      </div></section>}
      {p.phase === 'empty' && !p.uncertain && <section className="s20-empty"><span className="s20-state-icon s20-indigo"><Icon name="bookmark"/></span><h2>No saved internships yet.</h2><p>Saved listings appear here with their closing dates.</p><div className="s20-actions">{browse}</div></section>}
      {p.phase === 'list' && <>
        <p className="s20-count" role="status">{p.items.length} {p.uncertain ? 'in the last known list' : 'saved'}</p>
        <div className="s20-results">{p.items.map((item, index) => <article key={item.id} className="s20-result">
          <button className="s20-title" onClick={() => p.onNavigate(`/s-21?listing=${encodeURIComponent(item.id)}&from=s25`)}><span>{item.role}</span><small>{item.org}</small></button>
          <button type="button" className="s20-save" data-remove-id={item.id} aria-label={`Remove ${item.role} from saved`} aria-pressed={p.uncertain ? undefined : true} aria-disabled={blocked} aria-busy={p.pendingId === item.id || undefined}
            onClick={e => { if (!blocked) void perform(() => p.onRemove(item), e.currentTarget, index); }}><Icon name="bookmark-filled"/></button>
          <div className="s20-meta"><p>{item.location} · {item.stipendMonthlyPaise === null ? 'Stipend not stated' : `${(item.stipendMonthlyPaise / 100).toLocaleString('en-IN', { style: 'currency', currency: 'INR', minimumFractionDigits: item.stipendMonthlyPaise % 100 ? 2 : 0, maximumFractionDigits: 2 })} per month`}</p><p>Apply by {item.deadline}</p></div>
        </article>)}</div>
      </>}
      <p className="s20-disclaimer">Private to your account · organisations are not notified</p>
      <p className="s20-announcement" role="status" aria-live="polite">{p.notice}</p>
    </main><aside aria-label="Saved internships context"><section className="s20-card"><div className="s20-eyebrow">Browse more</div><p>Withdrawn or unavailable listings are omitted by the catalogue.</p>{browse}</section></aside></div>
    <footer><span>Privacy Notice</span><span>·</span><span>Terms</span><span>·</span><span>Accessibility</span></footer>
  </div>;
}
