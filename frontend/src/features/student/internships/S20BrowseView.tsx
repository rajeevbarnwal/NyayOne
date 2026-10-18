import { useRef, type ReactNode } from 'react';
import { NyayOneRevLLockup } from '../auth/NyayOneRevLIcon';
import type { InternshipListing, StipendFilter } from '../lib/internships';
import './S20Browse.css';

export interface S20BrowseViewProps {
  phase: 'loading' | 'results' | 'error' | 'offline'; items: InternshipListing[]; total: number; page: number;
  query: string; stipend: StipendFilter; verifiedOnly: boolean;
  saved: string[]; savedPhase: 'loading' | 'ready' | 'error' | 'anonymous' | 'forbidden' | 'unavailable';
  pendingId: string | null; saveError: { id: string; message: string } | null; notice: string; statusCode: number | null;
  onNavigate: (path: string) => void; onQuery: (q: string) => void; onStipend: (v: StipendFilter) => void;
  onVerified: () => void; onPage: (page: number) => void; onClear: () => void;
  onRetry: () => Promise<unknown>; onRetrySaved: () => Promise<unknown>; onSave: (listing: InternshipListing) => Promise<unknown>;
}
function Icon({ name, size = 20 }: { name: string; size?: number }) {
  // Exact frozen continuation primitives; the honest profile fallback is not
  // replaced with the prototype's synthetic AN identity.
  return <svg width={size} height={size} viewBox="0 0 24 24" aria-hidden="true" focusable="false">
    {name === 'brief' ? <><rect x="3.5" y="7" width="17" height="12.5" rx="2.5" fill="currentColor" opacity=".16"/><rect x="3.5" y="7" width="17" height="12.5" rx="2.5" fill="none" stroke="currentColor" strokeWidth="1.9"/><path d="M9 7V5.5A1.5 1.5 0 0 1 10.5 4h3A1.5 1.5 0 0 1 15 5.5V7M3.5 12h17" fill="none" stroke="currentColor" strokeWidth="1.9"/></>
      : name === 'bookmark-filled' ? <path d="M7 4h10v17l-5-3.5L7 21z" fill="currentColor"/>
        : name === 'bookmark' ? <><path d="M7 4h10v17l-5-3.5L7 21z" fill="currentColor" opacity=".16"/><path d="M7 4h10v17l-5-3.5L7 21z" fill="none" stroke="currentColor" strokeWidth="1.9" strokeLinejoin="round"/></>
          : name === 'search' ? <><circle cx="11" cy="11" r="6.5" fill="currentColor" opacity=".14"/><circle cx="11" cy="11" r="6.5" fill="none" stroke="currentColor" strokeWidth="1.9"/><path d="m16 16 4.5 4.5" stroke="currentColor" strokeWidth="1.9" strokeLinecap="round"/></>
            : name === 'back' ? <><circle cx="12" cy="12" r="9" fill="currentColor" opacity=".14"/><path d="M13.8 7.8 9.6 12l4.2 4.2" fill="none" stroke="currentColor" strokeWidth="1.9" strokeLinecap="round" strokeLinejoin="round"/></>
              : name === 'refresh' ? <><path d="M5 12a7 7 0 0 1 12-4.6" fill="none" stroke="currentColor" strokeWidth="1.9" strokeLinecap="round"/><path d="M17.6 3.8v4h-4" fill="none" stroke="currentColor" strokeWidth="1.9" strokeLinecap="round" strokeLinejoin="round"/><path d="M19 12a7 7 0 0 1-12 4.6" fill="none" stroke="currentColor" strokeWidth="1.9" strokeLinecap="round"/><path d="M6.4 20.2v-4h4" fill="none" stroke="currentColor" strokeWidth="1.9" strokeLinecap="round" strokeLinejoin="round"/><circle cx="12" cy="12" r="9" fill="currentColor" opacity=".08"/></>
                : name === 'person' ? <g fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round"><circle cx="12" cy="8" r="4"/><path d="M4 21v-2a8 8 0 0 1 16 0v2"/></g>
                  : name === 'offline' ? <><path d="M2 8.5a15 15 0 0 1 20 0M5.5 12a10 10 0 0 1 13 0M9 15.5a5 5 0 0 1 6 0" fill="none" stroke="currentColor" strokeWidth="1.9" strokeLinecap="round"/><circle cx="12" cy="19" r="1.3" fill="currentColor"/><path d="M4 4l16 16" stroke="currentColor" strokeWidth="1.9" strokeLinecap="round"/></>
                    : <><path d="M12 4 21 20H3z" fill="currentColor" opacity=".16"/><path d="M12 4 21 20H3z" fill="none" stroke="currentColor" strokeWidth="1.9" strokeLinejoin="round"/><path d="M12 10v4.5M12 17.2v.3" stroke="currentColor" strokeWidth="2" strokeLinecap="round"/></>}
  </svg>;
}
function ActionIcon({ name, colored = true }: { name: string; colored?: boolean }) {
  const icon = <span className="s20-action-icon" aria-hidden="true"><Icon name={name} size={18}/></span>;
  return colored ? <span className="s20-action-color">{icon}</span> : icon;
}
export function S20BrowseView(p: S20BrowseViewProps) {
  const root = useRef<HTMLDivElement>(null);
  // Action-owned focus only. Background fetches never focus a notice. Pending
  // save buttons remain mounted/focusable; aria-disabled + controller lock gate
  // activation. A user who tabs elsewhere retains ownership of their focus.
  async function perform(action: () => Promise<unknown>, button: HTMLButtonElement, target: string) {
    const host = root.current;
    await action();
    requestAnimationFrame(() => {
      if (!host?.isConnected || (document.activeElement !== button && document.activeElement !== document.body)) return;
      const next = host.querySelector<HTMLElement>(target);
      (next ?? (button.isConnected ? button : host.querySelector<HTMLElement>('h1')))?.focus({ preventScroll: true });
    });
  }
  const savedLink = <button type="button" className="s20-btn" onClick={() => p.onNavigate('/s-25')}><ActionIcon name="bookmark"/>Saved internships</button>;
  const resultMode = p.phase === 'results';
  const partial = p.savedPhase === 'error';
  const showSearch = resultMode && (p.total > 0 || p.verifiedOnly);
  const activeCount = Number(p.verifiedOnly) + Number(p.stipend !== 'any');
  const empty = (title: string, hint: string, actions?: ReactNode, error = false, icon = 'brief') => <section className="s20-empty" role={error ? 'alert' : undefined} tabIndex={-1}>
    <span className={`s20-state-icon ${error ? 's20-risk' : 's20-indigo'}`}><Icon name={error ? p.phase === 'offline' ? 'offline' : 'warn' : icon}/></span>
    <h2>{title}</h2><p>{hint}</p>{error && <span className="s20-code">{p.phase === 'offline' ? 'No connection' : p.statusCode && p.statusCode !== 200 ? `HTTP ${p.statusCode}` : 'Response unavailable'}</span>}
    {actions && <div className="s20-actions">{actions}</div>}
  </section>;
  return <div className="v321-internships" data-screen="S-20" data-v34-screen="S-20" data-s20-state={p.phase} ref={root}>
    <header className="s20-header">
      <img className="s20-mark" src="/brand/nyayone-mark.svg" alt="NyayOne" width="30" height="30"/>
      <span className="s20-mobile-title">Internships</span><div className="s20-lockup"><NyayOneRevLLockup/></div>
      <nav aria-label="Site"><button onClick={() => p.onNavigate('/s-14')}>Home</button><span>Research</span><span>Calendar</span><span aria-current="page">Careers</span><button onClick={() => p.onNavigate('/s-17')}>Profile</button></nav>
      <button className="s20-avatar" aria-label="Your Profile" onClick={() => p.onNavigate('/s-17')}><span><Icon name="person"/></span></button>
    </header>
    <div className="s20-layout">
      <main id="main-content">
        <div><h1 tabIndex={-1}><span className="s20-heading-icon"><Icon name="brief"/></span>Browse internships.</h1><p className="s20-sub">{showSearch ? 'Save the ones you like. Open one to read the full brief.' : 'Save the ones you like; open one to read the full brief.'}</p></div>
        <div className="s20-related">{savedLink}</div>
        {showSearch && <div className="s20-field"><label htmlFor="s20-query">Search this page</label><div className="s20-search"><Icon name="search" size={18}/><input id="s20-query" type="search" value={p.query} onChange={e => p.onQuery(e.target.value)} placeholder="Search role, city, stipend…" aria-describedby="s20-search-help"/></div><div className="s20-help" id="s20-search-help">Filters the listings already loaded on this page.</div></div>}
        <details className="s20-filters"><summary><span>Filters</span><small>{activeCount ? `${activeCount} active` : 'None active'}</small><Icon name="back" size={18}/></summary>
          <div className="s20-filter-body"><div className="s20-field"><span id="s20-stipend-label">Stipend (this page)</span><div role="group" aria-labelledby="s20-stipend-label" className="s20-segment">
            {(['any', 'paid', 'unpaid'] as const).map((value, i) => <button key={value} type="button" aria-pressed={p.stipend === value} onClick={() => p.onStipend(value)}>{['Any', 'Paid', 'Unpaid or not stated'][i]}</button>)}
          </div></div><div className="s20-field"><span className="s20-listing-label">Listing check (server)</span><button type="button" className="s20-filter-tag" aria-pressed={p.verifiedOnly} onClick={p.onVerified}>Verified listings only</button></div>
          </div>
        </details>
        {p.phase === 'loading' && <div role="status" aria-label="Loading internship listings" className="s20-skeletons">{[1, 2, 3].map(i => <div key={i}/>)}</div>}
        {(p.phase === 'error' || p.phase === 'offline') && empty(p.phase === 'offline' ? 'You are offline.' : 'Listings did not load.', p.phase === 'offline' ? 'Listings need a connection.' : 'Nothing you saved is affected.', <button className="s20-btn s20-primary" onClick={e => void perform(p.onRetry, e.currentTarget, '.s20-empty[role="alert"], h1')}><ActionIcon name="refresh" colored={false}/>Retry</button>, true)}
        {resultMode && partial && <section className="s20-note" role="alert" tabIndex={-1}><Icon name="warn" size={18}/><div><b>Your saved list did not load.</b><p>Save marks are hidden until it loads.</p><button className="s20-btn" onClick={e => void perform(p.onRetrySaved, e.currentTarget, '.s20-note, h1')}><ActionIcon name="refresh"/>Retry saved list</button></div></section>}
        {resultMode && ['anonymous', 'forbidden', 'unavailable'].includes(p.savedPhase) && <section className="s20-note"><div><b>{p.savedPhase === 'forbidden' ? 'Student account required' : p.savedPhase === 'unavailable' ? 'Session unavailable' : 'Sign in to save internships'}</b><p>Browsing is public. Saving requires your student account.</p>{p.savedPhase !== 'forbidden' && <button className="s20-btn" onClick={() => p.onNavigate('/s-03')}>Sign in</button>}</div></section>}
        {resultMode && !p.items.length && (p.total === 0 ? (p.verifiedOnly
          ? empty('No verified listings right now.', 'The server returned no verified listings. Turn the check off to see all listings.', <button className="s20-btn" onClick={e => void perform(async () => p.onVerified(), e.currentTarget, 'h1')}><ActionIcon name="back"/>Show all listings</button>)
          : empty('No internships are listed right now.', 'This page updates when organisations publish listings.', savedLink))
          : empty('No matching listings', 'Try clearing filters or a different search.', <button className="s20-btn" onClick={e => void perform(async () => p.onClear(), e.currentTarget, 'h1')}><ActionIcon name="refresh"/>Clear search and filters</button>, false, 'search'))}
        {resultMode && p.items.length > 0 && <><p className="s20-count" role="status">{p.items.length} listing{p.items.length === 1 ? '' : 's'} on this page</p>
          <div className="s20-results">{p.items.map(item => {
            const known = p.savedPhase === 'ready'; const selected = known && p.saved.includes(item.id);
            return <article className="s20-result" key={item.id}>
              <button className="s20-title" onClick={() => p.onNavigate(`/s-21?listing=${encodeURIComponent(item.id)}`)}><span>{item.role}</span><small>{item.org}</small></button>
              <button type="button" className="s20-save" aria-label={`${selected ? 'Remove' : 'Save'} ${item.role}${selected ? ' from saved' : ''}${!known ? ' (saved state unavailable)' : ''}`} aria-pressed={known ? selected : undefined} disabled={!known} aria-disabled={known && p.pendingId !== null} aria-busy={p.pendingId === item.id || undefined} onClick={e => { if (!p.pendingId) void perform(() => p.onSave(item), e.currentTarget, `[data-save-error="${item.id}"]`); }}><Icon name={selected ? 'bookmark-filled' : 'bookmark'}/></button>
              <div className="s20-meta"><p>{item.location} · {item.stipendMonthlyPaise === null ? <i>Stipend not stated</i> : `${(item.stipendMonthlyPaise / 100).toLocaleString('en-IN', { style: 'currency', currency: 'INR', maximumFractionDigits: 0 })} per month`}</p><p>Apply by {item.deadline}</p>
                <div className="s20-chips"><span className={`s20-chip ${item.verificationStatus === 'verified' ? 's20-verified' : ''}`}>{item.verificationStatus === 'verified' && <span aria-hidden="true"/>}{item.verificationStatus === 'verified' ? 'Verified listing' : 'Unverified listing'}</span></div>
                {p.saveError?.id === item.id && <p className="s20-save-error" role="alert" tabIndex={-1} data-save-error={item.id}>{p.saveError.message}</p>}
              </div>
            </article>;
          })}</div><p className="s20-disclaimer">Listings are supplied by the organisations named. NyayOne is not affiliated with them.</p></>}
        {resultMode && p.total > 20 && <nav className="s20-pager" aria-label="Internship pages"><button className="s20-btn" disabled={p.page <= 1} onClick={() => p.onPage(p.page - 1)}>Previous page</button><span>Page {p.page} of {Math.ceil(p.total / 20)}</span><button className="s20-btn" disabled={p.page * 20 >= p.total} onClick={() => p.onPage(p.page + 1)}>Next page</button></nav>}
        <p className="s20-announcement" role="status" aria-live="polite">{p.notice}</p>
      </main>
      <aside aria-label="Internship context"><section className="s20-card"><div className="s20-eyebrow" id="S-20-saved">Saved</div><p>{p.savedPhase === 'ready' ? `${p.saved.length} saved listings` : 'Saved count unavailable'}</p>{savedLink}</section><section className="s20-card"><div className="s20-eyebrow" id="S-20-verification">About verification</div><p>Verified means NyayOne checked the listing with the organisation named. It does not change who can apply.</p></section></aside>
    </div><footer><span>Privacy Notice</span><span>·</span><span>Terms</span><span>·</span><span>Accessibility</span></footer>
  </div>;
}
