import { useEffect, useMemo, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { StudentScreen, TextField, DpdpFootnote } from '../components';
import { StatusBadge, EmptyState, LoadingState, ErrorState, ValidationState } from '../../../components/ui/primitives';
import {
  CalendarService, calendarLoaders, runLoaders, aggregate, filterEvents, deriveStatus,
  retryFailed, resolveDeepLink, toPreview, localDateKey, localTime, validateDateRange,
  validatePersonalEvent, PersonalEventError,
  SOURCE_LABELS, CALENDAR_SOURCE_TYPES, CALENDAR_SOURCE_NOTE,
  TIMEZONE_OPTIONS, PERSONAL_EVENT_TYPES,
  type CalendarFilters, type SourceResult, type CalendarSourceType, type PersonalEventType,
} from '../lib/calendar';

/** Current student scope; the calendar service is user-scoped via this id. */
const STUDENT_ID = 'self';

function ModuleHead({ eyebrow, title, sub }: { eyebrow: string; title: string; sub?: string }) {
  return (
    <div>
      <p className="st-eyebrow">{eyebrow}</p>
      <h1 className="st-h1">{title}</h1>
      {sub && <p className="st-metatag" style={{ marginTop: 4 }}>{sub}</p>}
    </div>
  );
}

/* -------------------------------------------------------------------------- */
/* S-90 — Unified calendar (agenda) + source/date/timezone filters             */
/* -------------------------------------------------------------------------- */
export function CalendarMonth() {
  const nav = useNavigate();
  const svc = useMemo(() => new CalendarService(STUDENT_ID), []);
  const loaders = useMemo(() => calendarLoaders(svc, STUDENT_ID), [svc]);
  const [results, setResults] = useState<readonly SourceResult[] | null>(null); // null = loading
  const [filters, setFilters] = useState<CalendarFilters>(() => svc.getFilters());
  const [selectedId, setSelectedId] = useState<string | null>(null);

  useEffect(() => { setResults(runLoaders(loaders)); }, [loaders]);

  const agg = useMemo(() => (results ? aggregate(results) : null), [results]);
  const status = results ? deriveStatus(results) : 'loading';
  const dateError = validateDateRange(filters.from, filters.to);
  const visible = useMemo(
    () => (agg && !dateError ? filterEvents(agg.events, filters) : agg ? filterEvents(agg.events, { ...filters, from: null, to: null }) : []),
    [agg, filters, dateError],
  );

  function persist(next: CalendarFilters) { setFilters(svc.setFilters(next)); }
  function toggleSource(s: CalendarSourceType) {
    const has = filters.sources.includes(s);
    persist({ ...filters, sources: has ? filters.sources.filter((x) => x !== s) : [...filters.sources, s] });
  }
  function clearDates() { persist({ ...filters, from: null, to: null }); }
  function retry() { if (results) setResults(retryFailed(results, loaders)); }

  const groups = useMemo(() => {
    const m = new Map<string, typeof visible>();
    for (const e of visible) {
      const day = localDateKey(e.startsAt, filters.timezone);
      m.set(day, [...(m.get(day) ?? []), e]);
    }
    return [...m.entries()].sort(([a], [b]) => (a < b ? -1 : 1));
  }, [visible, filters.timezone]);

  const selected = selectedId && agg ? resolveDeepLink(agg.events, selectedId, STUDENT_ID) : null;

  return (
    <StudentScreen screenId="S-90">
      <div className="st-stack">
        <ModuleHead eyebrow="Calendar · S19" title="Your calendar" sub={`timezone ${filters.timezone}`} />

        <section className="st-panel" aria-label="Filters">
          <div className="st-tabsrow" role="group" aria-label="Filter by source">
            {CALENDAR_SOURCE_TYPES.map((s) => (
              <button key={s} type="button" className="st-chip"
                aria-pressed={filters.sources.includes(s)} onClick={() => toggleSource(s)}
                data-testid={`cal-source-${s}`}>
                {SOURCE_LABELS[s]}
              </button>
            ))}
          </div>
          <div className="st-grid" style={{ marginTop: 'var(--space-3)' }}>
            <label className="st-field" htmlFor="cal-from"><span className="st-field__label">From date</span>
              <input id="cal-from" className="st-input" type="date" value={filters.from ?? ''} data-testid="cal-from"
                aria-invalid={dateError ? true : undefined} aria-describedby={dateError ? 'cal-date-err' : undefined}
                onChange={(e) => persist({ ...filters, from: e.target.value || null })} /></label>
            <label className="st-field" htmlFor="cal-to"><span className="st-field__label">To date <span className="st-field__opt">· inclusive</span></span>
              <input id="cal-to" className="st-input" type="date" value={filters.to ?? ''} data-testid="cal-to"
                aria-invalid={dateError ? true : undefined} aria-describedby={dateError ? 'cal-date-err' : undefined}
                onChange={(e) => persist({ ...filters, to: e.target.value || null })} /></label>
            <label className="st-field" htmlFor="cal-tz"><span className="st-field__label">Timezone</span>
              <select id="cal-tz" className="st-select" value={filters.timezone} data-testid="cal-tz"
                onChange={(e) => persist({ ...filters, timezone: e.target.value })}>
                {TIMEZONE_OPTIONS.map((tz) => <option key={tz} value={tz}>{tz}</option>)}
              </select></label>
          </div>
          {dateError && <ValidationState fieldId="cal-date" message={dateError === 'from_after_to' ? 'From date must be on or before To date — showing all dates until fixed.' : 'Enter a valid date.'} />}
          <div className="st-actions"><button type="button" className="btn tap" onClick={clearDates} data-testid="cal-clear">Clear dates</button></div>
        </section>

        {status === 'loading' && <LoadingState label="Loading your calendar…" />}
        {status === 'error' && <ErrorState title="No calendar sources are responding" detail="Your events are safe. Retry to reload." onRetry={retry} />}
        {agg && status === 'partial' && (
          <div className="ui-notice ui-notice--warn" role="status">
            <span>Some sources didn’t load ({agg.failedSources.map((s) => SOURCE_LABELS[s]).join(', ')}). Showing everything else.</span>
            <button type="button" className="btn tap" style={{ marginLeft: 'auto' }} onClick={retry} data-testid="cal-retry">Retry failed sources</button>
          </div>
        )}

        {agg && status !== 'loading' && status !== 'error' && (
          <section className="st-panel" aria-label="Agenda">
            <div className="st-panel__head">
              <h2 className="st-panel__title">Agenda</h2>
              <span className="st-metatag" data-testid="cal-count">{visible.length} shown</span>
            </div>
            {visible.length === 0 ? (
              <EmptyState title="Nothing scheduled" hint="Adjust filters, or add a personal event." />
            ) : (
              groups.map(([day, items]) => (
                <div key={day} style={{ marginBottom: 'var(--space-4)' }}>
                  <p className="st-metatag" style={{ marginBottom: 6 }}>{day}</p>
                  <ul className="st-list">
                    {items.map((e) => {
                      const p = toPreview(e);
                      return (
                        <li className="st-item" key={p.id}>
                          <div>{p.title}
                            <div className="st-item__meta">{SOURCE_LABELS[p.sourceType]} · {localTime(p.startsAt, filters.timezone)}–{localTime(p.endsAt, filters.timezone)}</div>
                          </div>
                          <div className="st-actions">
                            <StatusBadge status={p.status === 'deadline' ? 'warn' : p.status === 'done' ? 'ok' : 'info'} label={p.status} />
                            <button type="button" className="btn tap" onClick={() => setSelectedId(p.id)} data-testid={`cal-open-${p.id}`}>Open</button>
                          </div>
                        </li>
                      );
                    })}
                  </ul>
                </div>
              ))
            )}
            <div className="st-actions"><button type="button" className="btn btn--primary tap" onClick={() => nav('/s-91')} data-testid="cal-add">Add personal event</button></div>
          </section>
        )}

        {selectedId && (
          <section className="st-panel" aria-label="Event detail" data-testid="cal-detail">
            {selected && selected.ok ? (
              <>
                <div className="st-panel__head">
                  <h2 className="st-panel__title">{toPreview(selected.event).title}</h2>
                  <StatusBadge status="info" label={SOURCE_LABELS[selected.event.sourceType]} />
                </div>
                <p className="st-item__meta">{localDateKey(selected.event.startsAt, filters.timezone)} · {localTime(selected.event.startsAt, filters.timezone)}–{localTime(selected.event.endsAt, filters.timezone)} · {filters.timezone}</p>
                <div className="st-actions st-actions--split">
                  <button type="button" className="btn tap" onClick={() => setSelectedId(null)}>Close</button>
                  <button type="button" className="btn btn--primary tap" onClick={() => nav(selected.event.sourceUrl)} data-testid="cal-goto">Go to source</button>
                </div>
              </>
            ) : (
              // Missing and unauthorized render identically — never reveal existence (TC-285-06).
              <>
                <EmptyState title="This item isn’t available" hint="It may have been removed, or it isn’t yours to view." />
                <div className="st-actions"><button type="button" className="btn tap" onClick={() => setSelectedId(null)}>Back to agenda</button></div>
              </>
            )}
          </section>
        )}

        <DpdpFootnote>{CALENDAR_SOURCE_NOTE}</DpdpFootnote>
      </div>
    </StudentScreen>
  );
}

/* -------------------------------------------------------------------------- */
/* S-91 — Add personal event (persisted through the calendar service)          */
/* -------------------------------------------------------------------------- */
export function CalendarAdd() {
  const nav = useNavigate();
  const svc = useMemo(() => new CalendarService(STUDENT_ID), []);
  const tz = useMemo(() => svc.getFilters().timezone, [svc]);
  const [form, setForm] = useState({ title: '', date: '', time: '', type: 'study' as PersonalEventType });
  const [error, setError] = useState<string | null>(null);
  const set = (k: keyof typeof form) => (v: string) => setForm((s) => ({ ...s, [k]: v }));

  function add() {
    try {
      validatePersonalEvent({ ...form, timezone: tz });
      svc.addPersonalEvent({ ...form, timezone: tz }, new Date().toISOString());
      nav('/s-90');
    } catch (e) {
      const code = e instanceof PersonalEventError ? e.code : 'invalid';
      setError(
        code === 'title_required' ? 'Enter a title.'
          : code === 'invalid_date' ? 'Choose a valid date.'
          : code === 'invalid_time' ? 'Choose a valid time.'
          : code === 'invalid_type' ? 'Choose an event type.'
          : 'Please check the details.',
      );
    }
  }

  return (
    <StudentScreen screenId="S-91">
      <div className="st-stack">
        <ModuleHead eyebrow="Calendar · S19" title="Add to calendar" sub={`recorded in ${tz}`} />
        <section className="st-panel">
          <h2 className="st-panel__title">New personal event</h2>
          <TextField id="ev-title" label="Title" value={form.title} onChange={set('title')} help="Shown on your calendar. Avoid private identifiers." />
          <label className="st-field" htmlFor="ev-date"><span className="st-field__label">Date</span>
            <input id="ev-date" className="st-input" type="date" value={form.date} data-testid="ev-date" onChange={(e) => set('date')(e.target.value)} /></label>
          <label className="st-field" htmlFor="ev-time"><span className="st-field__label">Time</span>
            <input id="ev-time" className="st-input" type="time" value={form.time} data-testid="ev-time" onChange={(e) => set('time')(e.target.value)} /></label>
          <label className="st-field" htmlFor="ev-type"><span className="st-field__label">Type</span>
            <select id="ev-type" className="st-select" value={form.type} data-testid="ev-type" onChange={(e) => setForm((s) => ({ ...s, type: e.target.value as PersonalEventType }))}>
              {PERSONAL_EVENT_TYPES.map((t) => <option key={t} value={t}>{t}</option>)}
            </select></label>
          {error && <ValidationState fieldId="ev" message={error} />}
          <div className="st-actions st-actions--split">
            <button type="button" className="btn tap" onClick={() => nav('/s-90')} data-testid="ev-cancel">Cancel</button>
            <button type="button" className="btn btn--primary tap" onClick={add} data-testid="ev-add">Add to calendar</button>
          </div>
        </section>
        <DpdpFootnote>Personal events are stored on your device scope and shown in {tz}; external calendar sync is not enabled.</DpdpFootnote>
      </div>
    </StudentScreen>
  );
}
