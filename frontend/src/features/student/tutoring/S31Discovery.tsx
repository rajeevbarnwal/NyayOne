import { useEffect, useLayoutEffect, useMemo, useRef, useState, type FormEvent } from 'react';
import { Link, useNavigate, useSearchParams } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import { useAuth, useStudentSession } from '../../../app/authContext';
import { NyayOneRevLLockup } from '../auth/NyayOneRevLIcon';
import { Icon } from '../internships/S20BrowseView';
import { TutoringApiError, TUTOR_SORTS } from '../lib/tutoringApi';
import { readMentors, mentorQuery, type MentorPage, type MentorSummary } from './s31Api';
import './S31Discovery.css';

const SORTS: Record<string, string> = { rating_desc: 'Highest rated', rating_asc: 'Lowest rated', experience_desc: 'Most experienced', experience_asc: 'Least experienced', name_asc: 'Name A to Z', newest: 'Recently added' };
class OfflineSearch extends Error {}
type Action = { trigger: HTMLElement; key: string; move: boolean };
function People({ size = 20 }: { size?: number }) { return <svg width={size} height={size} viewBox="0 0 24 24" aria-hidden="true" focusable="false"><circle cx="9" cy="9" r="3.2" fill="currentColor" opacity=".16"/><circle cx="9" cy="9" r="3.2" fill="none" stroke="currentColor" strokeWidth="1.8"/><path d="M3.5 19a5.5 5.5 0 0 1 11 0M15.5 6.2a3.2 3.2 0 0 1 0 5.9M20.5 19a5.2 5.2 0 0 0-3.6-4.9" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round"/></svg>; }
function FiltersIcon() { return <svg width="18" height="18" viewBox="0 0 24 24" aria-hidden="true" focusable="false"><path d="M4 6h16M7 12h10M10 18h4" fill="none" stroke="currentColor" strokeWidth="1.9" strokeLinecap="round"/></svg>; }
function RateClock() { return <svg width="18" height="18" viewBox="0 0 24 24" aria-hidden="true" focusable="false"><circle cx="12" cy="12" r="8.5" fill="currentColor" opacity=".14"/><circle cx="12" cy="12" r="8.5" fill="none" stroke="currentColor" strokeWidth="1.9"/><path d="M12 7.5V12l3 2" fill="none" stroke="currentColor" strokeWidth="1.9" strokeLinecap="round" strokeLinejoin="round"/></svg>; }
function initials(name: string) { return name.trim().split(/\s+/u).slice(0, 2).map(n => Array.from(n)[0]).join('').toLocaleUpperCase() || '?'; }
function price(t: MentorSummary) { return new Intl.NumberFormat('en-IN', { style: 'currency', currency: t.currency, minimumFractionDigits: t.session_price_paise % 100 ? 2 : 0, maximumFractionDigits: 2 }).format(t.session_price_paise / 100); }
export function S31Discovery() {
  const auth = useAuth();
  return <Discovery key={`${auth.userId}:${auth.roles.join(',')}`}/>;
}
function Discovery() {
  const auth = useAuth(), session = useStudentSession(), nav = useNavigate(), [sp, setSp] = useSearchParams();
  const request = useMemo(() => mentorQuery(sp), [sp]), requestKey = request.toString();
  const [draft, setDraft] = useState(() => new URLSearchParams(request)), [retrying, setRetrying] = useState(false), [offline, setOffline] = useState(false), [attempt, setAttempt] = useState(0), [now, setNow] = useState(Date.now());
  const root = useRef<HTMLDivElement>(null), action = useRef<Action | null>(null), first = useRef(true), lock = useRef(false), mounted = useRef(true), lastPage = useRef<MentorPage | null>(null), lastError = useRef<unknown>(null), pageLock = useRef<string | null>(null);
  const authorized = session.phase === 'authenticated' && auth.isAuthenticated && auth.roles.includes('student');
  const query = useQuery({ queryKey: ['s31-tutors', auth.userId, requestKey], queryFn: ({ signal }) => {
    if (!navigator.onLine) throw new OfflineSearch();
    return readMentors(request, signal);
  }, enabled: authorized, retry: false, staleTime: 0, networkMode: 'always', refetchOnWindowFocus: false, refetchOnReconnect: false });
  if (query.isSuccess) lastPage.current = query.data;
  if (query.error) lastError.current = query.error;
  const busy = query.isFetching || retrying, error = query.error ?? (retrying ? lastError.current : null);
  const unavailable = session.phase === 'unavailable', denied = session.phase === 'anonymous' || session.phase === 'authenticated' && !authorized;
  const failure = !!error || offline || unavailable || denied, loading = !failure && (query.isPending || busy || session.phase === 'pending');
  const data = !failure && !loading && authorized ? query.data : undefined;
  const pager = data ?? lastPage.current, offset = Number(request.get('offset')), limit = Number(request.get('limit'));
  const status = error instanceof TutoringApiError && error.status >= 400 && error.status <= 599 ? error.status : null;
  const offlineError = offline || error instanceof OfflineSearch;
  const waitSeconds = error instanceof TutoringApiError && status === 429 && Number.isFinite(error.retryAfterSeconds) ? Math.max(0, error.retryAfterSeconds!) : 0;
  const waitUntil = query.errorUpdatedAt + waitSeconds * 1000, remaining = waitSeconds > 0 ? Math.max(0, Math.ceil((waitUntil - now) / 1000)) : 0;
  const cooldown = status === 429 && remaining > 0;
  useEffect(() => { setDraft(new URLSearchParams(requestKey)); }, [requestKey]);
  useEffect(() => { mounted.current = true; return () => { mounted.current = false; }; }, []);
  useEffect(() => { if (!waitSeconds) return; setNow(Date.now()); const id = setInterval(() => setNow(Date.now()), 250); return () => clearInterval(id); }, [waitSeconds, query.errorUpdatedAt]);
  useLayoutEffect(() => {
    const host = root.current; if (!host) return;
    if (pageLock.current === requestKey && !busy) pageLock.current = null;
    const alert = host.querySelector<HTMLElement>('[role="alert"]');
    if (first.current && !loading && !busy) { first.current = false; if (alert && document.activeElement === document.body) alert.focus({ preventScroll: true }); }
    const owned = action.current; if (!owned || owned.key !== requestKey) return;
    if (document.activeElement !== owned.trigger && document.activeElement !== document.body) { action.current = null; return; }
    if (busy || loading) return;
    action.current = null;
    if (alert || owned.move || !owned.trigger.isConnected) (alert ?? host.querySelector<HTMLElement>('#s31-results-summary') ?? host.querySelector<HTMLElement>('h1'))?.focus({ preventScroll: true });
  });
  function edit(key: string, value: string) { setDraft(old => { const d = new URLSearchParams(old); if (value) d.set(key, value); else d.delete(key); return d; }); }
  function change(next: URLSearchParams, trigger: HTMLElement, move: boolean) {
    if (cooldown) return;
    const key = mentorQuery(next).toString(); if (key === requestKey || pageLock.current === key) return;
    action.current = { trigger, key, move }; trigger.focus({ preventScroll: true }); setOffline(false); lastError.current = null; pageLock.current = key; setSp(next);
  }
  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); const trigger = document.activeElement instanceof HTMLElement ? document.activeElement : root.current!.querySelector<HTMLElement>('h1')!;
    const next = new URLSearchParams(draft); next.delete('offset'); change(next, trigger, false);
  }
  function clear(trigger: HTMLElement) { const next = new URLSearchParams(); setDraft(next); if (mentorQuery(next).toString() === requestKey) void retry(trigger); else change(next, trigger, true); }
  async function retry(trigger: HTMLElement) {
    if (lock.current || busy || cooldown) return;
    lock.current = true; action.current = { trigger, key: requestKey, move: true }; trigger.focus({ preventScroll: true }); setAttempt(n => n + 1);
    if (!navigator.onLine) { setOffline(true); lock.current = false; return; }
    setOffline(false); setRetrying(true);
    try { if (unavailable) await session.refresh(); else await query.refetch({ cancelRefetch: false }); }
    finally { lock.current = false; if (mounted.current) setRetrying(false); }
  }
  const filterCount = ['q', 'subject', 'level', 'min_rating', 'min_experience_years', 'verified_only'].filter(k => request.has(k) && request.get(k) !== 'false').length;
  const sorts = query.data?.allowed_sorts ?? [...TUTOR_SORTS];
  function select(key: string, label: string, options: string[][]) { const value = draft.get(key) ?? ''; return <div className="s20-field"><label htmlFor={`s31-${key}`}>{label}</label><select id={`s31-${key}`} value={value} onChange={e => edit(key, e.target.value)}>{!options.some(([v]) => v === value) && <option value={value}>{value || 'Any'}</option>}{options.map(([v, l]) => <option key={v} value={v}>{l}</option>)}</select></div>; }
  const retryIcon = <span className="s20-action-icon"><Icon name="refresh" size={18}/></span>;
  const sessions = <Link className="s20-btn" to="/s-35"><span className="s20-action-color"><span className="s20-action-icon"><svg width="18" height="18" viewBox="0 0 24 24" aria-hidden="true" focusable="false"><rect x="4" y="5.5" width="16" height="15" rx="3" fill="currentColor" opacity=".14"/><rect x="4" y="5.5" width="16" height="15" rx="3" fill="none" stroke="currentColor" strokeWidth="1.9"/><path d="M8 3.5v4M16 3.5v4M4 10.5h16" stroke="currentColor" strokeWidth="1.9" strokeLinecap="round"/></svg></span></span>My sessions</Link>;
  return <div ref={root} className="v321-internships s31-discovery" data-screen="S-31" data-v34-screen="S-31" onFocusCapture={e => { first.current = false; if (action.current && e.target !== action.current.trigger) action.current = null; }}>
    <header className="s20-header"><img className="s20-mark" src="/brand/nyayone-mark.svg" alt="NyayOne" width="30" height="30"/><span className="s20-mobile-title">Mentors</span><div className="s20-lockup"><NyayOneRevLLockup/></div><nav aria-label="Site"><button onClick={() => nav('/s-14')}>Home</button><span>Research</span><span>Calendar</span><span>Careers</span><button onClick={() => nav('/s-17')}>Profile</button></nav><button className="s20-avatar" aria-label="Your Profile" onClick={() => nav('/s-17')}><span><Icon name="person"/></span></button></header>
    <div className="s20-layout"><main id="main-content">
      <div><h1 tabIndex={-1}><span className="s20-heading-icon"><People/></span>Find a mentor.</h1><p className="s20-sub">Paid sessions with advocates and senior students. A verified label means NyayOne checked that claim.</p></div>
      <nav className="s20-related" aria-label="Related">{sessions}</nav>
      <form className="s31-search-form" role="search" onSubmit={submit}>
        <div className="s20-field"><label htmlFor="s31-q">Search mentors</label><div className="s20-search"><Icon name="search" size={18}/><input id="s31-q" type="search" maxLength={120} value={draft.get('q') ?? ''} placeholder="Search" onChange={e => edit('q', e.target.value)}/><button className="s31-search-submit" type="submit" aria-label="Search mentors" aria-disabled={cooldown}><Icon name="search" size={18}/></button></div></div>
        <details className="s20-filters"><summary><span>Filters and sort</span><small>{filterCount ? `${filterCount} active · ` : ''}{SORTS[request.get('sort')!] ?? 'Unsupported sort'}</small><Icon name="back" size={18}/></summary><div className="s20-filter-body">
          {(['subject', 'level'] as const).map(key => <div className="s20-field" key={key}><label htmlFor={`s31-${key}`}>{key === 'subject' ? 'Subject' : 'Level'}</label><input id={`s31-${key}`} maxLength={key === 'subject' ? 80 : 40} value={draft.get(key) ?? ''} onChange={e => edit(key, e.target.value)}/></div>)}
          {select('min_rating', 'Minimum rating', [['', 'Any rating'], ['4', '4 and above'], ['4.5', '4.5 and above']])}{select('min_experience_years', 'Minimum experience', [['', 'Any'], ['2', '2 years'], ['5', '5 years']])}
          <label className="s31-check"><input type="checkbox" aria-label="Verified mentors only" checked={['true', '1'].includes(draft.get('verified_only') ?? '')} onChange={e => edit('verified_only', e.target.checked ? 'true' : '')}/><span><b>Verified mentors only</b><small>Sent to the server</small></span></label>
          {select('sort', 'Sort by', sorts.map(s => [s, SORTS[s] ?? s]))}<button type="submit" className="s20-btn s20-primary" aria-disabled={cooldown}><span className="s20-action-icon"><Icon name="search" size={18}/></span>Show mentors</button>
        </div></details>
      </form>
      {loading && <div className="s20-skeletons" role="status" aria-label="Loading mentors"><div/><div/><div/></div>}
      {failure && <section className={`s20-empty${status === 429 ? ' s31-rate' : ''}`} role="alert" tabIndex={-1}>
        {status === 429 ? <RateClock/> : <span className="s20-state-icon s20-risk"><Icon name={offlineError ? 'offline' : 'warn'}/></span>}<div className="s31-error-body"><h2>{busy ? 'Checking mentor search.' : unavailable ? 'Account access could not be checked.' : denied ? 'Sign in to find a mentor.' : offlineError ? 'You are offline.' : status === 429 ? 'Too many searches in a short time.' : 'Mentors did not load.'}</h2>
        <p key={`${attempt}:${query.errorUpdatedAt}`}>{busy ? 'A request is in progress.' : offlineError ? 'No request was sent. Reconnect and retry.' : status === 429 ? remaining ? `Try again in ${remaining} seconds.` : 'Wait a moment, then try again.' : status === 422 ? 'Check your filters or clear them and try again.' : 'Your booked sessions are unaffected.'}</p>
        {!offlineError && !busy && status !== null && <div className="s20-code">HTTP {status}{status === 429 ? ' · rate_limit_exceeded' : ''}</div>}
        <div className="s20-actions">{denied ? <Link className="s20-btn s20-primary" to="/s-03">Sign in</Link> : <button className={`s20-btn${status === 429 ? '' : ' s20-primary'}`} data-s31-retry aria-disabled={busy || cooldown} aria-busy={busy || undefined} onClick={e => void retry(e.currentTarget)}>{status === 429 ? <span className="s20-action-color">{retryIcon}</span> : retryIcon}{status === 429 ? 'Try again' : 'Retry'}</button>}{status === 422 && <button className="s20-btn" aria-disabled={busy} onClick={e => { if (!busy) clear(e.currentTarget); }}>Clear filters</button>}</div>
      </div></section>}
      {data && <><p className="s20-count" id="s31-results-summary" tabIndex={-1} role="status">{data.total} {data.total === 1 ? 'mentor' : 'mentors'} · page {Math.floor(data.offset / data.limit) + 1} of {Math.max(1, Math.ceil(data.total / data.limit))} · {SORTS[data.sort]?.toLowerCase() ?? data.sort}</p>
        {data.items.length ? <div className="s20-results">{data.items.map(t => <article className="s20-result s31-tutor" key={t.id}><div className="s31-identity"><span className="s31-portrait" aria-hidden="true">{initials(t.display_name)}</span><Link className="s20-title" to={`/s-32?tutor=${encodeURIComponent(t.id)}`}><span>{t.display_name}</span><small>{t.headline || 'Headline not provided'}</small></Link></div><div className="s20-meta"><p data-experience-years={t.experience_years}>{t.experience_years} {t.experience_years === 1 ? 'year' : 'years'} · {t.rating_count === 0 || t.rating_avg === null ? 'No ratings yet' : `${t.rating_avg} from ${t.rating_count} ${t.rating_count === 1 ? 'rating' : 'ratings'}`}</p><p>{price(t)} per session</p><div className="s20-chips">{t.verified_identity && <span className="s20-chip s20-verified"><span className="s20-chip-dot"/>Identity verified</span>}{t.verified_credentials && <span className="s20-chip s20-verified"><span className="s20-chip-dot"/>Credentials verified</span>}{!t.verified_identity && <span className="s20-chip">Identity not verified</span>}{!t.verified_credentials && <span className="s20-chip">Credentials not verified</span>}</div></div></article>)}</div> : <section className="s20-empty"><span className="s20-state-icon"><Icon name="search"/></span><h2>{data.total > 0 ? 'No mentors on this page.' : 'No mentors match.'}</h2><p>Try another subject or remove a filter.</p><div className="s20-actions"><button className="s20-btn s20-primary" onClick={e => clear(e.currentTarget)}><span className="s20-action-icon"><FiltersIcon/></span>Clear filters</button></div></section>}</>}
      {pager && authorized && <nav className="s20-pager" aria-label="Mentor list pages"><button className="s20-btn" aria-label="Previous page" aria-disabled={busy || offset <= 0 || cooldown} onClick={e => { if (busy || offset <= 0 || cooldown || pageLock.current) return; const next = new URLSearchParams(sp); next.set('offset', String(Math.max(0, offset - limit))); change(next, e.currentTarget, true); }}><span className="s20-action-icon s20-indigo"><Icon name="back" size={18}/></span>Previous</button><span>Page {Math.floor(offset / limit) + 1} of {Math.max(1, Math.ceil(pager.total / pager.limit))}</span><button className="s20-btn" aria-label="Next page" aria-disabled={busy || failure || !pager.has_more || cooldown} onClick={e => { if (busy || failure || !pager.has_more || cooldown || pageLock.current) return; const next = new URLSearchParams(sp); next.set('offset', String(offset + limit)); change(next, e.currentTarget, true); }}>Next</button></nav>}
    </main><aside aria-label="Mentor discovery context"><section className="s20-card"><h2 className="s20-eyebrow">Your sessions</h2><p>Booked sessions and their status.</p>{sessions}</section></aside></div><footer><span>Privacy Notice</span><span>·</span><span>Terms</span><span>·</span><span>Accessibility</span></footer>
  </div>;
}
