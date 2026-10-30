import { useEffect, useLayoutEffect, useRef, useState, type ChangeEvent } from 'react';
import { useQuery } from '@tanstack/react-query';
import { Link, useNavigate, useSearchParams } from 'react-router-dom';
import { useStudentSession } from '../../../app/authContext';
import { NyayOneRevLLockup } from '../auth/NyayOneRevLIcon';
import { Icon } from '../internships/S20BrowseView';
import { LawSchoolsApiError, type LawSchoolSummary } from '../lib/lawSchoolsApi';
import { inrAmount } from './lawschoolFormat.mjs';
import { readSchoolSearch, schoolSearchQuery } from './s27Api';
import './S27Search.css';

export interface SchoolSelection { id: string; name: string }
type SelectionStore = { readSelection: () => SchoolSelection[]; writeSelection: (items: SchoolSelection[]) => SchoolSelection[] };
type FocusAction = { trigger: HTMLElement; anchor?: HTMLElement; move: boolean; key: string };
class OfflineSchoolSearch extends Error {}
const TYPES = [['national_law_university', 'National Law University'], ['government', 'Government law college'], ['private', 'Private university'], ['deemed', 'Deemed university']];
const ORDERS = [['name', 'Name, A to Z'], ['fees', 'Lowest fees first'], ['nirf_rank', 'NIRF rank, ranked schools first']];
const STATES = ['Andaman and Nicobar Islands', 'Andhra Pradesh', 'Arunachal Pradesh', 'Assam', 'Bihar', 'Chandigarh', 'Chhattisgarh', 'Dadra and Nagar Haveli and Daman and Diu', 'Delhi', 'Goa', 'Gujarat', 'Haryana', 'Himachal Pradesh', 'Jammu and Kashmir', 'Jharkhand', 'Karnataka', 'Kerala', 'Ladakh', 'Lakshadweep', 'Madhya Pradesh', 'Maharashtra', 'Manipur', 'Meghalaya', 'Mizoram', 'Nagaland', 'Odisha', 'Puducherry', 'Punjab', 'Rajasthan', 'Sikkim', 'Tamil Nadu', 'Telangana', 'Tripura', 'Uttar Pradesh', 'Uttarakhand', 'West Bengal'];
const FILTERS = ['state', 'institution_type', 'degree', 'accreditation', 'entrance_exam', 'fees_max'];
const pairs = (values: string[]) => values.map(value => [value, value]);
function SchoolIcon({ compare = false, size = 20 }: { compare?: boolean; size?: number }) {
  return <svg width={size} height={size} viewBox="0 0 24 24" aria-hidden="true" focusable="false">{compare
    ? <>{[3.5, 13.5].map(x => <g key={x}><rect x={x} y="5" width="7" height="14" rx="2" fill="currentColor" opacity=".16"/><rect x={x} y="5" width="7" height="14" rx="2" fill="none" stroke="currentColor" strokeWidth="1.9"/></g>)}</>
    : <><path d="M3 9.5 12 5l9 4.5-9 4.5z" fill="currentColor" opacity=".16"/><path d="M3 9.5 12 5l9 4.5-9 4.5z" fill="none" stroke="currentColor" strokeWidth="1.9" strokeLinejoin="round"/><path d="M6.5 11.5v4.5c0 1.5 2.5 3 5.5 3s5.5-1.5 5.5-3v-4.5M21 9.5v5" fill="none" stroke="currentColor" strokeWidth="1.9" strokeLinecap="round"/></>}</svg>;
}
export function S27SearchScreen({ readSelection, writeSelection }: SelectionStore) {
  const session = useStudentSession(), nav = useNavigate(), [sp, setSp] = useSearchParams();
  const requestKey = schoolSearchQuery(sp).toString(), root = useRef<HTMLDivElement>(null);
  const [input, setInput] = useState(sp.get('q') ?? ''), [tray, setTray] = useState(readSelection), [notice, setNotice] = useState('');
  const [offlineRetry, setOffline] = useState(false), [retrying, setRetrying] = useState(false), [attempt, setAttempt] = useState(0);
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null), lock = useRef(false), mounted = useRef(true);
  const focus = useRef<FocusAction | null>(null), first = useRef(true), previousError = useRef<unknown>(null);
  const query = useQuery({ queryKey: ['s27-schools', requestKey], queryFn: ({ signal }) => {
    if (!navigator.onLine) throw new OfflineSchoolSearch('Search needs a connection.');
    return readSchoolSearch(new URLSearchParams(requestKey), signal);
  },
    enabled: session.phase !== 'pending', retry: false, staleTime: 0, networkMode: 'always', refetchOnWindowFocus: false, refetchOnReconnect: false, refetchOnMount: 'always' });
  const lastPage = useRef(query.data);
  if (query.data) lastPage.current = query.data;
  if (query.isError) previousError.current = query.error;
  const busy = session.phase === 'pending' || query.isFetching || retrying;
  const error = query.error ?? (retrying ? previousError.current : null);
  const offline = offlineRetry || error instanceof OfflineSchoolSearch, failed = !!error || offline;
  const waiting = !failed && (busy || query.isPending);
  const data = !waiting && !failed ? query.data : undefined;
  // During an explicit retry or page change keep the existing pagination DOM
  // mounted. Its controls are aria-disabled, never detached or natively disabled.
  const pager = data ?? lastPage.current, page = Number(sp.get('page') ?? '1');
  const pageCount = pager ? Math.max(1, Math.ceil(pager.total / pager.pageSize)) : 1;
  const compareMax = data?.compareMax; // A stale limit cannot authorize new selections.
  const status = error instanceof LawSchoolsApiError && error.status >= 400 && error.status <= 599 ? error.status : null;
  const invalid = status === 422, order = ORDERS.find(([value]) => value === (sp.get('sort') ?? 'name'))?.[1] ?? 'Unsupported order';
  const filterCount = FILTERS.filter(key => sp.has(key)).length;
  useEffect(() => { mounted.current = true; return () => { mounted.current = false; if (timer.current) clearTimeout(timer.current); }; }, []);
  useEffect(() => { setInput(sp.get('q') ?? ''); if (timer.current) clearTimeout(timer.current); }, [sp]);
  useLayoutEffect(() => {
    const host = root.current; if (!host) return;
    const alert = host.querySelector<HTMLElement>('[role="alert"]');
    if (first.current && !busy && !query.isPending) {
      first.current = false;
      if (alert && document.activeElement === document.body) alert.focus({ preventScroll: true });
    }
    const action = focus.current; if (!action || action.key !== requestKey) return;
    const active = document.activeElement;
    if (active !== action.trigger && active !== action.anchor && active !== document.body) { focus.current = null; return; }
    if (waiting || busy) {
      if (!action.trigger.isConnected && active === document.body) {
        const anchor = host.querySelector<HTMLElement>('h1'); if (anchor) { action.anchor = anchor; anchor.focus({ preventScroll: true }); }
      }
      return;
    }
    focus.current = null;
    if (alert || action.move || !action.trigger.isConnected) (alert ?? host.querySelector<HTMLElement>('#s27-results-summary') ?? host.querySelector<HTMLElement>('h1'))?.focus({ preventScroll: true });
  });
  function change(values: Record<string, string>, trigger: HTMLElement, move = false) {
    if (timer.current) clearTimeout(timer.current);
    const next = new URLSearchParams(sp);
    for (const [key, value] of Object.entries(values)) { if (value) next.set(key, value); else next.delete(key); }
    if (!('page' in values)) next.delete('page');
    const nextKey = schoolSearchQuery(next).toString(); if (requestKey === nextKey) return;
    focus.current = { trigger, move, key: nextKey }; setOffline(false); previousError.current = null; setSp(next);
  }
  function clear(trigger: HTMLElement) {
    const values: Record<string, string> = { q: '', sort: '', page: '', page_size: '' }; FILTERS.forEach(key => { values[key] = ''; });
    if (requestKey === schoolSearchQuery(new URLSearchParams()).toString()) { void retry(trigger); return; }
    change(values, trigger, true);
  }
  async function retry(trigger: HTMLElement) {
    if (lock.current || busy) return;
    lock.current = true; focus.current = { trigger, move: true, key: requestKey }; trigger.focus({ preventScroll: true }); setAttempt(n => n + 1);
    if (!navigator.onLine) { setOffline(true); lock.current = false; return; }
    setOffline(false); setRetrying(true);
    try { await query.refetch({ cancelRefetch: false }); }
    finally { lock.current = false; if (mounted.current) setRetrying(false); }
  }
  function search(value: string, trigger: HTMLElement) {
    setInput(value); if (timer.current) clearTimeout(timer.current);
    timer.current = setTimeout(() => change({ q: value }, trigger), 300);
  }
  function toggle(school: SchoolSelection, trigger: HTMLElement) {
    const current = readSelection(), exists = current.some(item => item.id === school.id);
    if (!exists && (compareMax === undefined || current.length >= compareMax)) return;
    const next = exists ? current.filter(item => item.id !== school.id) : [...current, { id: school.id, name: school.name }];
    setTray(writeSelection(next)); setNotice(`${school.name} ${exists ? 'removed from' : 'added to'} comparison.`);
    if (exists && !trigger.matches('.s20-save')) root.current?.querySelector<HTMLElement>('h1')?.focus({ preventScroll: true });
  }
  function filter(key: string, label: string, options: string[][], help?: string) {
    const value = sp.get(key) ?? (key === 'sort' ? 'name' : '');
    const choices = key === 'sort' ? options : [['', 'Any'], ...options];
    return <div className="s27-field"><label htmlFor={`s27-${key}`}>{label}</label><select id={`s27-${key}`} value={value}
      aria-describedby={help ? `s27-${key}-help` : undefined} onChange={(event: ChangeEvent<HTMLSelectElement>) => change({ [key]: event.target.value, q: input }, event.currentTarget)}>
      {!choices.some(([v]) => v === value) && <option value={value}>{value}</option>}{choices.map(([v, name]) => <option key={v} value={v}>{name}</option>)}
    </select>{help && <span className="s20-help" id={`s27-${key}-help`}>{help}</span>}</div>;
  }
  const canCompare = compareMax !== undefined && tray.length >= 2 && tray.length <= compareMax;
  function openComparison() { if (canCompare) nav(`/s-29?ids=${encodeURIComponent(tray.map(item => item.id).join(','))}&ret=${encodeURIComponent(sp.toString())}`); }
  function comparison(where: string) { return tray.length ? <>
    <div className="s27-tray" role="region" aria-label="Comparison"><span role="status">{tray.length}{compareMax !== undefined ? ` of ${compareMax}` : ''} selected</span>
      <button className="s20-btn s20-primary" aria-disabled={!canCompare} aria-describedby={`s27-compare-help-${where}`} onClick={openComparison}><SchoolIcon compare size={18}/>Compare</button></div>
    <details className="s20-filters"><summary><span>Selected schools</span><Icon name="back" size={18}/></summary><div className="s20-filter-body"><ul className="s27-selected">{tray.map(item => <li key={item.id}><span>{item.name}</span><button aria-label={`Remove ${item.name} from selected schools`} onClick={event => toggle(item, event.currentTarget)}><Icon name="cross" size={18}/></button></li>)}</ul>
      <p className="s20-help" id={`s27-compare-help-${where}`}>{compareMax === undefined ? 'Reload the results to confirm the comparison limit.' : tray.length < 2 ? 'Choose at least one more school.' : tray.length > compareMax ? `Remove schools to meet the current limit of ${compareMax}.` : 'Compare your selected schools.'}</p></div></details>
  </> : <p>Choose at least two schools to compare{compareMax !== undefined ? `, up to ${compareMax}` : ''}.</p>; }
  function card(school: LawSchoolSummary) {
    const selected = tray.some(item => item.id === school.id), blocked = !selected && (compareMax === undefined || tray.length >= compareMax);
    return <article className="s20-result" key={school.id}>
      <Link className="s20-title" to={`/s-28?id=${encodeURIComponent(school.id)}&ret=${encodeURIComponent(sp.toString())}`}><span>{school.name}</span><small>{TYPES.find(([value]) => value === school.institutionType)?.[1] ?? school.institutionType} · {school.state}</small></Link>
      <button className="s20-save" aria-pressed={selected} aria-disabled={blocked} aria-label={`${selected ? 'Remove' : 'Add'} ${school.name} ${selected ? 'from' : 'to'} comparison`} onClick={event => toggle(school, event.currentTarget)}><SchoolIcon compare/></button>
      <div className="s20-meta"><p>{inrAmount(school.feesMin)}{school.feesMax !== school.feesMin ? ` to ${inrAmount(school.feesMax)}` : ''} per year · {school.entranceExam || 'Entrance exam not provided'}</p></div>
    </article>;
  }
  return <div className="v321-internships s27-search" data-screen="S-27" data-v34-screen="S-27" ref={root}
    onFocusCapture={event => { first.current = false; const action = focus.current; if (action && event.target !== action.trigger && event.target !== action.anchor) focus.current = null; }}
    onBlurCapture={event => { const action = focus.current; if (action && event.relatedTarget === null && event.target.isConnected && (event.target === action.trigger || event.target === action.anchor)) focus.current = null; }}>
    <header className="s20-header"><img className="s20-mark" src="/brand/nyayone-mark.svg" alt="NyayOne" width="30" height="30"/><span className="s20-mobile-title">Law schools</span><div className="s20-lockup"><NyayOneRevLLockup/></div>
      <nav aria-label="Site"><button onClick={() => nav('/s-14')}>Home</button><span>Research</span><span>Calendar</span><span>Careers</span><button onClick={() => nav('/s-17')}>Profile</button></nav><button className="s20-avatar" aria-label="Your Profile" onClick={() => nav('/s-17')}><span><Icon name="person"/></span></button></header>
    <div className="s20-layout"><main id="main-content"><div><h1 tabIndex={-1}><span className="s20-heading-icon"><SchoolIcon/></span>Find a law school.</h1><p className="s20-sub">Search what institutions publish. Nothing here is a ranking.</p></div>
      <nav className="s20-related" aria-label="Related">{canCompare && <button className="s20-btn s20-primary" onClick={openComparison}><SchoolIcon compare size={18}/>Compare</button>}<Link className="s20-btn" to="/s-30"><span className="s20-action-icon s20-action-color"><Icon name="bookmark" size={18}/></span>Saved and followed</Link></nav>
      <form onSubmit={event => { event.preventDefault(); const field = root.current?.querySelector<HTMLInputElement>('#s27-search'); if (field) change({ q: input }, field); }}>
        <label className="s27-search-label" htmlFor="s27-search">Search law schools</label><div className="s20-search"><Icon name="search" size={18}/><input id="s27-search" type="search" placeholder="School name" value={input} onChange={event => search(event.target.value, event.currentTarget)}/></div>
      </form>
      <details className="s20-filters"><summary><span>Filters</span><small>{filterCount ? `${filterCount} active` : 'None active'} · {order}</small><Icon name="back" size={18}/></summary><div className="s20-filter-body"><div className="s27-grid">
        {filter('sort', 'Order', ORDERS)}{filter('state', 'State', pairs(STATES))}{filter('institution_type', 'Institution type', TYPES)}
        {filter('degree', 'Degree', pairs(['BA LLB (Hons)', 'BBA LLB', 'LLB', 'LLM']))}{filter('accreditation', 'Accreditation', pairs(['BCI approved', 'NAAC A++', 'NAAC A+', 'NAAC A']))}
        {filter('entrance_exam', 'Entrance exam', pairs(['CLAT', 'AILET', 'LSAT-India', 'MH CET Law', 'Own exam', 'State CET', 'Institution test']))}
        {filter('fees_max', 'Max fees (₹ per year)', [['150000', 'Up to ₹1,50,000'], ['300000', 'Up to ₹3,00,000'], ['500000', 'Up to ₹5,00,000']], 'Matches schools whose published starting fee is within this amount.')}
      </div>{filterCount > 0 && <button className="s20-btn" onClick={event => clear(event.currentTarget)}>Clear filters</button>}</div></details>
      {waiting && <div className="s20-skeletons" role="status" aria-label="Loading law schools">{[1, 2, 3].map(i => <div key={i}/>)}</div>}
      {failed && <section className="s20-empty" role="alert" tabIndex={-1}><span className="s20-state-icon s20-risk"><Icon name={offline ? 'offline' : 'warn'}/></span>
        <h2>{invalid ? 'The server did not accept a filter.' : offline ? 'You are offline.' : 'Schools did not load.'}</h2>
        <p key={attempt}>{invalid ? 'Reset the filters and try again.' : offline ? 'No request was sent. Reconnect and retry.' : 'Your saved and followed schools are unaffected.'}</p>
        {!offline && status !== null && <div className="s20-code">HTTP {status}{invalid && error instanceof LawSchoolsApiError && ['unsupported_sort', 'unsupported_institution_type'].includes(error.code) ? ` · ${error.code}` : ''}</div>}
        <div className="s20-actions"><button className="s20-btn s20-primary" aria-disabled={busy} aria-busy={busy || undefined} onClick={event => { if (!busy) { if (invalid) clear(event.currentTarget); else void retry(event.currentTarget); } }}><span className="s20-action-icon"><Icon name="refresh" size={18}/></span>{invalid ? 'Reset filters' : 'Retry'}</button></div></section>}
      {data && <><p className="s20-count" id="s27-results-summary" role="status" tabIndex={-1}>{data.total} school{data.total === 1 ? '' : 's'}{pageCount > 1 ? ` · page ${data.page} of ${pageCount}` : ''} · {order.toLowerCase()}</p>
        {data.items.length ? <div className="s20-results">{data.items.map(card)}</div> : <section className="s20-empty"><span className="s20-state-icon"><Icon name="search"/></span><h2>{data.total > 0 ? 'No schools on this page.' : 'No schools match.'}</h2><p>{data.total > 0 ? 'Go to an earlier page to see the available schools.' : 'Try a different search or clear a filter.'}</p><div className="s20-actions"><button className="s20-btn" onClick={event => clear(event.currentTarget)}>Clear filters</button></div></section>}</>}
      {pager && pageCount > 1 && <nav className="s20-pager" aria-label="School list pages"><button className="s20-btn" aria-label="Previous page" aria-disabled={busy || page <= 1} onClick={event => { if (!busy && page > 1) change({ page: String(page - 1) }, event.currentTarget, true); }}>Previous</button><span>{busy ? 'Loading page…' : `Page ${page} of ${pageCount}`}</span><button className="s20-btn" aria-label="Next page" aria-disabled={busy || page >= pageCount} onClick={event => { if (!busy && page < pageCount) change({ page: String(page + 1) }, event.currentTarget, true); }}>Next</button></nav>}
      <div className="s27-mobile-comparison">{tray.length > 0 && comparison('mobile')}</div>
      <p className="s20-disclaimer">Figures come from what each institution publishes. Open a school to see each figure’s source and retrieval date.</p>
      <span className="s20-announcement" role="status">{notice}</span>
    </main><aside aria-label="Law school context"><section className="s20-card s27-comparison"><div className="s20-eyebrow">Comparison</div>{comparison('desktop')}</section>
      <section className="s20-card"><div className="s20-eyebrow">Saved and followed</div><p>Your saved and followed schools are private to your account.</p><Link className="s20-btn" to="/s-30"><Icon name="bookmark" size={18}/>Saved and followed</Link></section></aside></div>
    <footer><span>Privacy Notice</span><span>·</span><span>Terms</span><span>·</span><span>Accessibility</span></footer>
  </div>;
}
