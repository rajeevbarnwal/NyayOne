import { useEffect, useMemo, useState, type CSSProperties } from 'react';
import { useNavigate } from 'react-router-dom';
import { StudentScreen, DpdpFootnote } from '../components';
import { EmptyState, LoadingState, ErrorState, ValidationState, StatusBadge } from '../../../components/ui/primitives';
import {
  CalendarService, calendarLoaders, runLoaders, aggregate, filterEvents, deriveStatus,
  retryFailed, resolveDeepLink, toPreview, localDateKey, localTime, validateDateRange,
  validatePersonalEvent, PersonalEventError, getSavedViewMode, saveViewMode, resolveEventBadge,
  SOURCE_LABELS, CALENDAR_SOURCE_TYPES, CALENDAR_SOURCE_NOTE,
  TIMEZONE_OPTIONS, PERSONAL_EVENT_TYPES, PERSONAL_EVENT_TYPE_LABELS,
  type CalendarFilters, type SourceResult, type CalendarSourceType, type PersonalEventType,
  type CalendarEvent, type CalendarViewMode,
} from '../lib/calendar';
import { formatDateDDMMYYYY } from '../../../lib/dateTime';
import '../../../styles/calendar.css';

const STUDENT_ID = 'self';
const WEEKDAYS = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'];

/** Map a source type to the prototype's four marker/legend categories (shape+colour). */
type MarkerCat = 'exam' | 'moot' | 'intern' | 'draft';
const CAT_FOR: Record<CalendarSourceType, MarkerCat> = {
  exam: 'exam', community: 'moot', moot: 'moot', reminder: 'moot', internship: 'intern', tutoring: 'intern', clinical: 'draft',
};
const LEGEND: ReadonlyArray<{ cat: MarkerCat; label: string }> = [
  { cat: 'exam', label: 'Exam prep' }, { cat: 'moot', label: 'Community / moot' },
  { cat: 'intern', label: 'Internship / tutoring' }, { cat: 'draft', label: 'Clinical / other' },
];
function markerDotStyle(cat: MarkerCat): CSSProperties {
  if (cat === 'exam') return { background: 'var(--info)', borderRadius: '50%' };
  if (cat === 'moot') return { background: 'var(--accent)', transform: 'rotate(45deg)' };
  if (cat === 'intern') return { background: 'var(--warn)' };
  return { background: 'var(--text2)', clipPath: 'polygon(50% 0,100% 100%,0 100%)' };
}

/** Shared v3.2 six-tab calendar feature navigation (same on S-90 and S-91). */
function CalSubnav({ active }: { active: 'month' | 'add' }) {
  const nav = useNavigate();
  return (
    <div className="subnav" role="tablist" aria-label="Calendar views">
      <button className={active === 'month' ? 'on' : ''} aria-selected={active === 'month'} onClick={() => nav('/s-90')} data-testid="cal-tab-month">Month</button>
      <button className={active === 'add' ? 'on' : ''} aria-selected={active === 'add'} onClick={() => nav('/s-91')} data-testid="cal-add">Add event</button>
      <button onClick={() => nav('/s-91')}>Event</button>
      <button onClick={() => nav('/s-92')}>Conflict</button>
      <button onClick={() => nav('/s-93')}>Reminders</button>
      <button onClick={() => nav('/s-93')} data-testid="cal-export">Export</button>
    </div>
  );
}

/* -------------------------------------------------------------------------- */
/* S-90 — Unified calendar (month grid) — v3.2 structural parity               */
/* -------------------------------------------------------------------------- */
export function CalendarMonth() {
  const nav = useNavigate();
  const svc = useMemo(() => new CalendarService(STUDENT_ID), []);
  const loaders = useMemo(() => calendarLoaders(svc, STUDENT_ID), [svc]);
  const [results, setResults] = useState<readonly SourceResult[] | null>(null);
  const [filters, setFilters] = useState<CalendarFilters>(() => svc.getFilters());
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [showFilters, setShowFilters] = useState(false);
  const [viewMode, setViewModeState] = useState<CalendarViewMode>(() => getSavedViewMode());

  function changeViewMode(mode: CalendarViewMode) {
    setViewModeState(saveViewMode(mode));
  }

  useEffect(() => { setResults(runLoaders(loaders)); }, [loaders]);

  const agg = useMemo(() => (results ? aggregate(results) : null), [results]);
  const status = results ? deriveStatus(results) : 'loading';
  const dateError = validateDateRange(filters.from, filters.to);
  const visible = useMemo(
    () => (agg ? filterEvents(agg.events, dateError ? { ...filters, from: null, to: null } : filters) : []),
    [agg, filters, dateError],
  );

  function persist(next: CalendarFilters) { setFilters(svc.setFilters(next)); }
  function toggleSource(s: CalendarSourceType) {
    const has = filters.sources.includes(s);
    persist({ ...filters, sources: has ? filters.sources.filter((x) => x !== s) : [...filters.sources, s] });
  }
  function retry() { if (results) setResults(retryFailed(results, loaders)); }

  // Month grid for the current month, in the selected timezone.
  const now = new Date();
  const year = now.getFullYear();
  const month = now.getMonth();
  const monthLabel = new Intl.DateTimeFormat('en-GB', { month: 'long', year: 'numeric', timeZone: filters.timezone }).format(now);
  const todayKey = localDateKey(now.toISOString(), filters.timezone);
  const daysInMonth = new Date(year, month + 1, 0).getDate();
  const lead = (new Date(year, month, 1).getDay() + 6) % 7; // Mon=0
  const mm = String(month + 1).padStart(2, '0');
  const byDay = useMemo(() => {
    const m = new Map<number, CalendarEvent[]>();
    for (const e of visible) {
      const key = localDateKey(e.startsAt, filters.timezone); // yyyy-mm-dd
      if (key.slice(0, 7) !== `${year}-${mm}`) continue;
      const d = Number(key.slice(8, 10));
      m.set(d, [...(m.get(d) ?? []), e]);
    }
    return m;
  }, [visible, filters.timezone, year, mm]);

  const upcoming = useMemo(
    () => [...visible].filter((e) => e.startsAt >= now.toISOString()).slice(0, 3),
    [visible],
  );
  const selected = selectedId && agg ? resolveDeepLink(agg.events, selectedId, STUDENT_ID) : null;

  return (
    <StudentScreen screenId="S-90" className="calv-screen">
      <div className="calv" data-testid="cal-feature-region" data-qa-crop="calendar-feature">
        <CalSubnav active="month" />
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', flexWrap: 'wrap', gap: 8, margin: '8px 0 12px' }}>
          <h1 className="lede" style={{ margin: 0 }}>Unified Calendar</h1>
          <div className="st-tabsrow" role="tablist" aria-label="Calendar View Mode">
            <button type="button" className={`chip ${viewMode === 'month' ? 'on active' : ''}`} aria-selected={viewMode === 'month'} onClick={() => changeViewMode('month')} data-testid="cal-view-month">Month</button>
            <button type="button" className={`chip ${viewMode === 'week' ? 'on active' : ''}`} aria-selected={viewMode === 'week'} onClick={() => changeViewMode('week')} data-testid="cal-view-week">Week</button>
            <button type="button" className={`chip ${viewMode === 'day' ? 'on active' : ''}`} aria-selected={viewMode === 'day'} onClick={() => changeViewMode('day')} data-testid="cal-view-day">Day</button>
          </div>
        </div>

        {showFilters && (
          <section className="card filters" id="cal-filters" aria-label="Filters">
            <div className="ph"><span className="t">Filter by source &amp; date</span></div>
            <div className="st-tabsrow" role="group" aria-label="Filter by source">
              {CALENDAR_SOURCE_TYPES.map((s) => (
                <button key={s} type="button" className="chip" aria-pressed={filters.sources.includes(s)}
                  onClick={() => toggleSource(s)} data-testid={`cal-source-${s}`}><span className="g" />{SOURCE_LABELS[s]}</button>
              ))}
            </div>
            <div className="cols2" style={{ marginTop: 12 }}>
              <div><label className="lbl" htmlFor="cal-from">From date</label>
                <input id="cal-from" className="field" type="date" value={filters.from ?? ''} data-testid="cal-from"
                  aria-invalid={dateError ? true : undefined} aria-describedby={dateError ? 'cal-date-err' : undefined}
                  onChange={(e) => persist({ ...filters, from: e.target.value || null })} /></div>
              <div><label className="lbl" htmlFor="cal-to">To date</label>
                <input id="cal-to" className="field" type="date" value={filters.to ?? ''} data-testid="cal-to"
                  aria-invalid={dateError ? true : undefined} aria-describedby={dateError ? 'cal-date-err' : undefined}
                  onChange={(e) => persist({ ...filters, to: e.target.value || null })} /></div>
            </div>
            <div style={{ marginTop: 12 }}><label className="lbl" htmlFor="cal-tz">Timezone</label>
              <select id="cal-tz" className="field" value={filters.timezone} data-testid="cal-tz"
                onChange={(e) => persist({ ...filters, timezone: e.target.value })}>
                {TIMEZONE_OPTIONS.map((tz) => <option key={tz} value={tz}>{tz}</option>)}
              </select></div>
            {dateError && <div id="cal-date-err"><ValidationState fieldId="cal-date" message={dateError === 'from_after_to' ? 'From date must be on or before To date — showing all dates until fixed.' : 'Enter a valid date.'} /></div>}
            <div style={{ marginTop: 12 }}><button type="button" className="btn" onClick={() => persist({ ...filters, from: null, to: null })} data-testid="cal-clear">Clear dates</button></div>
          </section>
        )}

        <div className="legend" aria-hidden="true">
          {LEGEND.map((l) => <span key={l.cat}><span className="d" style={markerDotStyle(l.cat)} />{l.label}</span>)}
        </div>

        {status === 'loading' && <LoadingState label="Loading your calendar…" />}
        {status === 'error' && <ErrorState title="No calendar sources are responding" detail="Your events are safe. Retry to reload." onRetry={retry} />}
        {agg && status === 'partial' && (
          <div className="ui-notice ui-notice--warn" role="status" style={{ marginBottom: 14 }}>
            <span>Some sources didn’t load ({agg.failedSources.map((s) => SOURCE_LABELS[s]).join(', ')}). Showing everything else.</span>
            <button type="button" className="btn" style={{ marginLeft: 'auto' }} onClick={retry} data-testid="cal-retry">Retry failed sources</button>
          </div>
        )}

        {agg && status !== 'loading' && status !== 'error' && (
          <div className="two-b">
            <div>
              <div className="ph">
                <span className="t">{viewMode === 'month' ? monthLabel : viewMode === 'week' ? `7-Day Week (${monthLabel})` : `Day View (${formatDateDDMMYYYY(now)})`}</span>
                <span style={{ display: 'inline-flex', alignItems: 'center', gap: 10 }}>
                  <span className="a" data-testid="cal-count">{visible.length} events</span>
                  <button type="button" className="chip" aria-expanded={showFilters} aria-controls="cal-filters" onClick={() => setShowFilters((v) => !v)} data-testid="cal-filters-toggle"><span className="g" />Filter</button>
                </span>
              </div>

              {viewMode === 'month' && (
                <div className="cal" role="grid" aria-label={`Calendar ${monthLabel}`}>
                  {WEEKDAYS.map((w) => <div className="hd" key={w}>{w}</div>)}
                  {Array.from({ length: lead }, (_, i) => <div className="cell dim" key={`lead-${i}`} aria-hidden="true"><span className="dn" /></div>)}
                  {Array.from({ length: daysInMonth }, (_, i) => {
                    const d = i + 1;
                    const dd = String(d).padStart(2, '0');
                    const isToday = `${year}-${mm}-${dd}` === todayKey;
                    const items = byDay.get(d) ?? [];
                    return (
                      <div className={`cell${isToday ? ' today' : ''}`} key={d} role="gridcell">
                        <span className="dn">{d}</span>
                        {items.slice(0, 2).map((e) => {
                          const p = toPreview(e);
                          return (
                            <button key={p.id} type="button" className={`ev ${CAT_FOR[p.sourceType]}`} data-testid={`cal-open-${p.id}`}
                              onClick={() => setSelectedId(p.id)} title={p.title}>
                              <span className="d" />{localTime(p.startsAt, filters.timezone)} {p.title.length > 8 ? `${p.title.slice(0, 8)}…` : p.title}
                            </button>
                          );
                        })}
                      </div>
                    );
                  })}
                </div>
              )}

              {viewMode === 'week' && (
                <div className="st-list" style={{ marginTop: 12 }}>
                  {Array.from({ length: 7 }, (_, i) => {
                    const d = i + 1;
                    const items = byDay.get(d) ?? [];
                    return (
                      <div key={i} className="st-item" style={{ flexDirection: 'column', alignItems: 'flex-start', padding: '10px 12px' }}>
                        <div style={{ fontWeight: 600, fontSize: '0.85rem', color: 'var(--color-fg-default)' }}>
                          {WEEKDAYS[i]} {d} {monthLabel}
                        </div>
                        {items.length === 0 ? (
                          <div style={{ fontSize: '0.8rem', color: 'var(--color-fg-muted)', marginTop: 4 }}>No events scheduled</div>
                        ) : (
                          items.map((e) => {
                            const p = toPreview(e);
                            const badge = resolveEventBadge(e);
                            return (
                              <button key={p.id} type="button" className="btn tap" style={{ marginTop: 4, width: '100%', justifyContent: 'space-between', padding: '6px 10px', fontSize: '0.8rem' }} onClick={() => setSelectedId(p.id)}>
                                <span>{localTime(p.startsAt, filters.timezone)} · {p.title}</span>
                                <StatusBadge status={badge.status} label={badge.label} />
                              </button>
                            );
                          })
                        )}
                      </div>
                    );
                  })}
                </div>
              )}

              {viewMode === 'day' && (
                <div className="st-list" style={{ marginTop: 12 }}>
                  {(byDay.get(now.getDate()) ?? visible.slice(0, 5)).length === 0 ? (
                    <EmptyState title="Nothing scheduled for today" hint="No events scheduled for today in your selected timezone." />
                  ) : (
                    (byDay.get(now.getDate()) ?? visible.slice(0, 5)).map((e) => {
                      const p = toPreview(e);
                      const badge = resolveEventBadge(e);
                      return (
                        <div key={p.id} className="st-item" style={{ justifyContent: 'space-between', padding: '10px 12px' }}>
                          <div>
                            <div style={{ fontWeight: 600, fontSize: '0.9rem' }}>{p.title}</div>
                            <div className="st-item__meta">{SOURCE_LABELS[e.sourceType]} · {formatDateDDMMYYYY(localDateKey(e.startsAt, filters.timezone))} · {localTime(e.startsAt, filters.timezone)}</div>
                          </div>
                          <StatusBadge status={badge.status} label={badge.label} />
                        </div>
                      );
                    })
                  )}
                </div>
              )}

              {visible.length === 0 && <div style={{ marginTop: 12 }}><EmptyState title="Nothing scheduled" hint="Adjust filters, or add a personal event." /></div>}
            </div>

            <div className="col">
              <div className="card tint">
                <div className="ph"><span className="t">A platform primitive</span></div>
                <p style={{ margin: 0, fontSize: '12.5px', lineHeight: 1.5 }}>Exams, moots, internships, clinical hours, community events and your own reminders — one calendar, not many.</p>
              </div>
              <div className="card">
                <div className="ph"><span className="t">Reminders · next</span><span className="a">Add</span></div>
                {upcoming.length === 0 ? (
                  <p className="rem__m" style={{ padding: '10px 0' }}>Nothing coming up in view.</p>
                ) : upcoming.map((e) => {
                  const p = toPreview(e);
                  return (
                    <div className="rem" key={p.id}>
                      <span className={`ev ${CAT_FOR[p.sourceType]}`} style={{ padding: 5, width: 'auto' }}><span className="d" /></span>
                      <div style={{ flex: 1 }}>
                        <div className="rem__t">{p.title}</div>
                        <div className="rem__m">{localDateKey(p.startsAt, filters.timezone)} · {localTime(p.startsAt, filters.timezone)}</div>
                      </div>
                    </div>
                  );
                })}
              </div>
              <div className="dpdp">{CALENDAR_SOURCE_NOTE}</div>
            </div>
          </div>
        )}

        {selectedId && (
          <section className="card" aria-label="Event detail" data-testid="cal-detail" style={{ marginTop: 16 }}>
            {selected && selected.ok ? (
              <>
                <div className="ph"><span className="t">{SOURCE_LABELS[selected.event.sourceType]}</span></div>
                <div className="rem__t" style={{ fontSize: '15px' }}>{toPreview(selected.event).title}</div>
                <div className="rem__m" style={{ marginTop: 4 }}>{localDateKey(selected.event.startsAt, filters.timezone)} · {localTime(selected.event.startsAt, filters.timezone)}–{localTime(selected.event.endsAt, filters.timezone)} · {filters.timezone}</div>
                <div className="st-actions st-actions--split" style={{ marginTop: 14 }}>
                  <button type="button" className="btn" onClick={() => setSelectedId(null)}>Close</button>
                  <button type="button" className="btn solid" onClick={() => nav(selected.event.sourceUrl)} data-testid="cal-goto">Go to source</button>
                </div>
              </>
            ) : (
              // Missing and unauthorized render identically — never reveal existence (TC-285-06).
              <>
                <EmptyState title="This item isn’t available" hint="It may have been removed, or it isn’t yours to view." />
                <div className="st-actions"><button type="button" className="btn" onClick={() => setSelectedId(null)}>Back to calendar</button></div>
              </>
            )}
          </section>
        )}
      </div>
    </StudentScreen>
  );
}

/* -------------------------------------------------------------------------- */
/* S-91 — Add event (compact card) — v3.2 structural parity                    */
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
    <StudentScreen screenId="S-91" className="calv-screen">
      <div className="calv" data-testid="cal-feature-region" data-qa-crop="calendar-feature">
        <CalSubnav active="add" />
        <h1 className="lede">Add event</h1>
        <p className="stand ident">Add a personal event to your unified calendar.</p>
        <div className="cardw">
          <div className="card">
            <div className="ph"><span className="t">New event</span></div>
            <label className="lbl" htmlFor="ev-title" style={{ marginBottom: 7 }}>Title</label>
            <input id="ev-title" className="field" value={form.title} data-testid="ev-title"
              placeholder="e.g. Judiciary mock" aria-invalid={error ? true : undefined}
              onChange={(e) => set('title')(e.target.value)} />
            <div style={{ height: 14 }} />
            <div className="cols2">
              <div><label className="lbl" htmlFor="ev-date" style={{ marginBottom: 6 }}>Date</label>
                <input id="ev-date" className="field" type="date" value={form.date} data-testid="ev-date" onChange={(e) => set('date')(e.target.value)} /></div>
              <div><label className="lbl" htmlFor="ev-time" style={{ marginBottom: 6 }}>Time</label>
                <input id="ev-time" className="field" type="time" value={form.time} data-testid="ev-time" onChange={(e) => set('time')(e.target.value)} /></div>
            </div>
            <div className="lbl" style={{ margin: '11px 0 7px' }} id="ev-type-label">Type</div>
            <div className="type-chips" style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }} role="group" aria-labelledby="ev-type-label">
              {/* Canonical S-91 manual types per Product decision 12314: Study, Deadline,
                  Meeting, Reminder, Other — rendered as REAL text (accessible name),
                  not CSS-capitalized. Enum values (study/deadline/…) and ev-type-* testids
                  stay lowercase for the persistence contract. */}
              {PERSONAL_EVENT_TYPES.map((t) => (
                <button key={t} type="button" className="chip" aria-pressed={form.type === t}
                  data-testid={`ev-type-${t}`} onClick={() => setForm((s) => ({ ...s, type: t }))}>
                  <span className="g" />{PERSONAL_EVENT_TYPE_LABELS[t]}
                </button>
              ))}
            </div>
            {error && <div style={{ marginTop: 11 }}><ValidationState fieldId="ev" message={error} /></div>}
            <div className="st-actions st-actions--split" style={{ marginTop: 14 }}>
              <button type="button" className="btn" onClick={() => nav('/s-90')} data-testid="ev-cancel">Cancel</button>
              <button type="button" className="btn solid block" onClick={add} data-testid="ev-add" style={{ maxWidth: 220 }}>Add to calendar</button>
            </div>
          </div>
        </div>
        <DpdpFootnote>Personal events are stored on your device scope and shown in {tz}; external calendar sync is not enabled.</DpdpFootnote>
      </div>
    </StudentScreen>
  );
}
