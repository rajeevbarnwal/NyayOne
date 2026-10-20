import { useLayoutEffect, useRef, type RefObject } from 'react';
import { NyayOneRevLLockup } from '../auth/NyayOneRevLIcon';
import { listingSourceLabel, type InternshipListing } from '../lib/internships';
import { PublicRiskLabelPanel } from '../reporting/RiskLabelScreens';
import { Icon } from './S20BrowseView';
import { safeSourceUrl } from './s21Api';
import './S21Detail.css';

export type S21Focus = { owned: boolean; anchor?: HTMLElement } | null;
export interface S21DetailViewProps {
  focus: RefObject<S21Focus>;
  phase: 'incomplete' | 'missing' | 'error' | 'loading' | 'detail'; item: InternshipListing | null;
  savedState: 'loading' | 'saved' | 'unsaved' | 'error' | 'uncertain' | 'anonymous' | 'forbidden' | 'unavailable';
  busy: boolean; failure: string; notice: string; fromSaved: boolean;
  statusCode?: number | null;
  onNavigate: (path: string) => void; onToggle: () => Promise<unknown>; onRetry: () => Promise<unknown>; onRetrySaved: () => Promise<unknown>;
}
const dateLabel = (date: string | null) => {
  const parsed = date ? new Date(date) : null;
  return parsed && Number.isFinite(parsed.getTime()) ? parsed.toLocaleDateString('en-IN', { day: 'numeric', month: 'short', year: 'numeric', timeZone: 'UTC' }) : 'not provided';
};
function DetailIcon({ name, size = 18 }: { name: string; size?: number }) {
  // Frozen continuation primitives, local to S-21: do not alter shared icons.
  if (!['send', 'login', 'lock'].includes(name)) return <Icon name={name} size={size}/>;
  return <svg className={`s21-icon--${name}`} width={size} height={size} viewBox="0 0 24 24" aria-hidden="true" focusable="false">
    {name === 'send' ? <><path d="M4 11 20 4l-4.5 16-4-6.5z" fill="currentColor" opacity=".16"/><path d="M4 11 20 4l-4.5 16-4-6.5zM11.5 13.5 20 4" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinejoin="round"/></>
      : name === 'login' ? <><path d="M10 4.5h6.5A1.5 1.5 0 0 1 18 6v12a1.5 1.5 0 0 1-1.5 1.5H10" fill="none" stroke="currentColor" strokeWidth="1.9" strokeLinecap="round"/><circle cx="10" cy="12" r="7.5" fill="currentColor" opacity=".12"/><path d="M3.5 12H13M10 8.5 13.5 12 10 15.5" fill="none" stroke="currentColor" strokeWidth="1.9" strokeLinecap="round" strokeLinejoin="round"/></>
        : <><rect x="5" y="10.5" width="14" height="10" rx="2.5" fill="currentColor" opacity=".16"/><rect x="5" y="10.5" width="14" height="10" rx="2.5" fill="none" stroke="currentColor" strokeWidth="1.9"/><path d="M8 10.5V8a4 4 0 0 1 8 0v2.5" fill="none" stroke="currentColor" strokeWidth="1.9"/></>}
  </svg>;
}
function ActionIcon({ name, color }: { name: string; color?: 'indigo' | 'gold' }) {
  const icon = <span className="s20-action-icon" aria-hidden="true"><DetailIcon name={name}/></span>;
  return color ? <span className={`s21-action-${color}`}>{icon}</span> : icon;
}
export function S21DetailView(p: S21DetailViewProps) {
  const root = useRef<HTMLDivElement>(null);
  const action = useRef<{ anchor: HTMLElement; trigger: HTMLElement; done: boolean } | null>(null);
  const restore = useRef<() => void>(() => undefined);
  useLayoutEffect(() => {
    const host = root.current;
    return () => { if (host?.contains(document.activeElement)) p.focus.current = { owned: true }; };
  }, [p.focus]);
  useLayoutEffect(() => {
    // Carry only owned focus through the session-transition remount. Keep the
    // temporary heading anchor until authority settles, then focus its notice.
    // User movement cancels this handoff; unrelated alerts never acquire it.
    const handoff = p.focus.current;
    if (handoff?.owned) {
      if (document.activeElement === document.body || document.activeElement === handoff.anchor) {
        const target = root.current?.querySelector<HTMLElement>('[role="alert"]') ?? root.current?.querySelector<HTMLElement>('h1');
        target?.focus({ preventScroll: true });
        handoff.anchor = target ?? undefined;
        if (p.phase !== 'loading' && p.savedState !== 'loading') p.focus.current = null;
      } else p.focus.current = null;
    }
    restore.current = () => {
      const owned = action.current, host = root.current;
      if (!owned || !host?.isConnected) return;
      if (![owned.anchor, owned.trigger, document.body].includes(document.activeElement as HTMLElement)) { action.current = null; return; }
      if (!owned.done || p.phase === 'loading') return;
      const error = host.querySelector<HTMLElement>('[role="alert"]');
      (error ?? (owned.trigger.isConnected ? owned.trigger : host.querySelector<HTMLElement>('h1')))?.focus({ preventScroll: true });
      action.current = null;
    };
    restore.current();
  });
  async function perform(run: () => Promise<unknown>, trigger: HTMLElement, anchorPending = false) {
    if (action.current) return;
    const anchor = anchorPending ? root.current?.querySelector<HTMLElement>('h1') ?? trigger : trigger;
    const owned = { trigger, anchor, done: false }; action.current = owned;
    anchor.focus({ preventScroll: true });
    try { await run(); } finally { owned.done = true; requestAnimationFrame(() => restore.current()); }
  }
  const item = p.phase === 'detail' ? p.item : null;
  const known = ['saved', 'unsaved'].includes(p.savedState);
  const sourceUrl = safeSourceUrl(item?.source.url ?? null);
  const savedError = ['error', 'uncertain', 'unavailable', 'anonymous', 'forbidden'].includes(p.savedState);
  const saveDisabled = !known || p.busy;
  const sessionNotice = ['anonymous', 'unavailable', 'forbidden'].includes(p.savedState);
  const title = item ? `${item.role}${/[.!?]$/.test(item.role) ? '' : '.'}` : 'Internship.';
  return <div className="v321-internships s21-detail" data-screen="S-21" data-v34-screen="S-21" ref={root}>
    <header className="s20-header"><img className="s20-mark" src="/brand/nyayone-mark.svg" alt="NyayOne" width="30" height="30"/><span className="s20-mobile-title">Internship</span><div className="s20-lockup"><NyayOneRevLLockup/></div>
      <nav aria-label="Site"><button onClick={() => p.onNavigate('/s-14')}>Home</button><span>Research</span><span>Calendar</span><span aria-current="page">Careers</span><button onClick={() => p.onNavigate('/s-17')}>Profile</button></nav>
      <button className="s20-avatar" aria-label="Your Profile" onClick={() => p.onNavigate('/s-17')}><span><Icon name="person"/></span></button>
    </header>
    <div className="s20-layout"><main id="main-content">
      <button className="s20-btn s21-back" aria-label={p.fromSaved ? 'Back to saved internships' : 'Back to internships'} onClick={() => p.onNavigate(p.fromSaved ? '/s-25' : '/s-20')}><ActionIcon name="back"/>{p.fromSaved ? 'Saved internships' : 'Internships'}</button>
      <div><h1 tabIndex={-1}><span className="s20-heading-icon"><Icon name="brief"/></span>{title}</h1>{item && <p className="s20-sub">{item.org} · {item.location}</p>}</div>
      {p.phase === 'loading' && <div role="status" aria-label="Loading internship" className="s20-skeletons">{[1, 2, 3].map(i => <div key={i}/>)}</div>}
      {['incomplete', 'missing', 'error'].includes(p.phase) && <section className="s20-empty" role="alert" tabIndex={-1}><span className="s20-state-icon s20-risk"><Icon name="warn"/></span>
        <h2>{p.phase === 'incomplete' ? 'Listing unavailable' : p.phase === 'missing' ? 'This listing is no longer available.' : 'The listing did not load.'}</h2>
        <p>{p.phase === 'incomplete' ? 'This listing link is incomplete. Return to internships and select a listing.' : p.phase === 'missing' ? 'It was removed or the link is out of date.' : 'Try again in a moment.'}</p>
        {p.statusCode != null && <div className="s20-code">HTTP {p.statusCode}</div>}
        <div className="s20-actions">{p.phase === 'error' ? <button className="s20-btn s20-primary" onClick={e => void perform(p.onRetry, e.currentTarget, true)}><ActionIcon name="refresh"/>Retry</button> : <button className="s20-btn s20-primary" onClick={() => p.onNavigate('/s-20')}><ActionIcon name="brief"/>Browse internships</button>}</div>
      </section>}
      {item && <>
        <div className="s20-chips"><span className={`s20-chip ${item.verificationStatus === 'verified' ? 's20-verified' : ''}`}><span className="s20-chip-dot" aria-hidden="true"/><span>{item.verificationStatus === 'verified' ? 'Verified listing' : 'Unverified listing'}</span></span>{item.tags.map((t, i) => <span className="s20-chip s21-tag" key={`${i}:${t}`}><span className="s20-chip-dot" aria-hidden="true"/><span>{t}</span></span>)}</div>
        {(p.failure || savedError) && <section className={`s20-note ${sessionNotice ? 's21-session' : 's21-save-error'}`} role="alert" tabIndex={-1}><DetailIcon name={sessionNotice ? 'lock' : 'warn'}/><div><b>{p.failure || (p.savedState === 'anonymous' ? 'Sign in to save listings.' : p.savedState === 'forbidden' ? 'Student account required.' : 'Your saved state is unavailable.')}</b>
          <p>{p.savedState === 'anonymous' ? 'Saving requires your student account.' : p.savedState === 'forbidden' ? 'Saved internships are available only to student accounts.' : 'No saved or unsaved claim is made until the server confirms it.'}</p>
          {['anonymous', 'unavailable'].includes(p.savedState) ? <button className="s20-btn" onClick={() => p.onNavigate('/s-03')}><ActionIcon name="login" color="indigo"/>Sign in again</button> : p.savedState !== 'forbidden' && <button className="s20-btn" onClick={e => void perform(p.onRetrySaved, e.currentTarget, true)}><ActionIcon name="refresh" color="indigo"/>Reload saved state</button>}
        </div></section>}
        <div className="s21-kvs"><div><span>Stipend</span><b>{item.stipendMonthlyPaise === null ? 'Not stated' : `${(item.stipendMonthlyPaise / 100).toLocaleString('en-IN', { style: 'currency', currency: 'INR', maximumFractionDigits: 0 })} per month`}</b></div><div><span>Apply by</span><b>{item.deadline}</b></div><div><span>Eligibility</span><b>{item.eligibility || 'Not provided'}</b></div></div>
        <section className="s21-card" aria-labelledby="s21-about"><h2 id="s21-about" className="s21-eyebrow">About this internship</h2><p>{item.description || 'Description not provided.'}</p><p className="s21-source">{listingSourceLabel(item)}<br/>Retrieved {dateLabel(item.source.retrievedAt)}; {item.source.verifiedAt ? `verified ${dateLabel(item.source.verifiedAt)}` : 'not verified'}</p></section>
        {sourceUrl && <div className="s21-source-row"><a href={sourceUrl} target="_blank" rel="noopener noreferrer" className="s20-btn"><ActionIcon name="send"/>Open source listing<span className="s21-sr"> (opens {item.source.name || new URL(sourceUrl).host} in a new tab)</span></a></div>}
        <div className="s21-actions"><button type="button" className="s20-btn" aria-pressed={known ? p.savedState === 'saved' : undefined} aria-disabled={saveDisabled} aria-busy={p.busy || undefined} onClick={e => { if (!saveDisabled) void perform(p.onToggle, e.currentTarget); }}><ActionIcon name={p.savedState === 'saved' ? 'bookmark-filled' : 'bookmark'} color={p.savedState === 'saved' ? 'gold' : 'indigo'}/>{p.busy ? 'Saving' : p.savedState === 'saved' ? 'Saved' : known ? 'Save listing' : 'Saved state unavailable'}</button>
          <button className="s20-btn s20-primary" aria-disabled="true" aria-describedby="s21-apply-explanation" onClick={() => undefined}><ActionIcon name="send"/>Apply</button></div>
        <p className="s21-explanation" id="s21-apply-explanation">Apply is not available yet. Save the listing and check back.</p>
        <PublicRiskLabelPanel organisationId={item.organisationId} organisationName={item.org} compact/>
      </>}
      <p className="s20-announcement" role="status" aria-live="polite">{p.notice}</p>
    </main><aside aria-label="Internship context"><section className="s20-card"><div className="s20-eyebrow">Applying</div><p>The application step has no server endpoint yet, so Apply stays disabled until an owner decides how applications are handled.</p></section></aside></div>
    <footer><span>Privacy Notice</span><span>·</span><span>Terms</span><span>·</span><span>Accessibility</span></footer>
  </div>;
}
