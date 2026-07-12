import { useEffect, useMemo, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { StudentScreen, DpdpFootnote } from '../components';
import { StatusBadge, EmptyState, LoadingState, ErrorState } from '../../../components/ui/primitives';
import {
  CalendarService, runLoaders, sampleLoaders, aggregate, filterEvents, deriveStatus,
  retryFailed, resolveDeepLink, toPreview, localDateKey, localTime,
  SOURCE_LABELS, CALENDAR_SOURCE_TYPES, CALENDAR_SOURCE_NOTE, DEFAULT_TZ,
  type CalendarFilters, type SourceResult, type CalendarSourceType,
} from '../lib/calendar';

/** Current student scope. Auth wiring is a shared concern; the calendar service
 *  is user-scoped via this id and the fixtures are owned by the same student. */
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
/* S-90 — Unified calendar (month/agenda) + source filters (SAATHI-286)        */
/* -------------------------------------------------------------------------- */
export function CalendarMonth() {
  const nav = useNavigate();
  const svc = useMemo(() => new CalendarService(STUDENT_ID), []);
  const loaders = useMemo(() => sampleLoaders(STUDENT_ID), []);
  const [results, setResults] = useState<readonly SourceResult[] | null>(null); // null = loading
  const [filters, setFilters] = useState<CalendarFilters>(() => svc.getFilters());
  const [selectedId, setSelectedId] = useState<string | null>(null);

  // Initial source load (loading → success/partial/error).
  useEffect(() => { setResults(runLoaders(loaders)); }, [loaders]);

  const agg = useMemo(() => (results ? aggregate(results) : null), [results]);
  const status = results ? deriveStatus(results) : 'loading';
  const visible = useMemo(
    () => (agg ? filterEvents(agg.events, filters) : []),
    [agg, filters],
  );

  function toggleSource(s: CalendarSourceType) {
    const has = filters.sources.includes(s);
    const next: CalendarFilters = {
      ...filters,
      sources: has ? filters.sources.filter((x) => x !== s) : [...filters.sources, s],
    };
    setFilters(svc.setFilters(next)); // persisted, user-scoped (TC-285-02)
  }

  function retry() {
    if (results) setResults(retryFailed(results, loaders)); // retry only failed (TC-285-05)
  }

  // Group visible events by local calendar day in the selected timezone (TC-285-04).
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

        <div className="st-tabsrow" role="group" aria-label="Filter by source">
          {CALENDAR_SOURCE_TYPES.map((s) => (
            <button
              key={s}
              type="button"
              className="st-chip"
              aria-pressed={filters.sources.length === 0 ? false : filters.sources.includes(s)}
              onClick={() => toggleSource(s)}
              data-testid={`cal-source-${s}`}
            >
              {SOURCE_LABELS[s]}
            </button>
          ))}
        </div>

        {status === 'loading' && <LoadingState label="Loading your calendar…" />}

        {status === 'error' && (
          <ErrorState title="No calendar sources are responding" detail="Your events are safe. Retry to reload." onRetry={retry} />
        )}

        {agg && status === 'partial' && (
          <div className="ui-notice ui-notice--warn" role="status">
            <span>
              Some sources didn’t load ({agg.failedSources.map((s) => SOURCE_LABELS[s]).join(', ')}). Showing everything else.
            </span>
            <button type="button" className="btn tap" style={{ marginLeft: 'auto' }} onClick={retry} data-testid="cal-retry">
              Retry failed sources
            </button>
          </div>
        )}

        {agg && status !== 'loading' && status !== 'error' && (
          <section className="st-panel" aria-label="Agenda">
            <div className="st-panel__head">
              <h2 className="st-panel__title">Agenda</h2>
              <span className="st-metatag" data-testid="cal-count">{visible.length} shown</span>
            </div>

            {visible.length === 0 ? (
              <EmptyState title="Nothing scheduled" hint="Adjust source filters or check back after you save items in other modules." />
            ) : (
              groups.map(([day, items]) => (
                <div key={day} style={{ marginBottom: 'var(--space-4)' }}>
                  <p className="st-metatag" style={{ marginBottom: 6 }}>{day}</p>
                  <ul className="st-list">
                    {items.map((e) => {
                      const p = toPreview(e); // privacy-safe fields only (TC-285-07)
                      return (
                        <li className="st-item" key={p.id}>
                          <div>
                            {p.title}
                            <div className="st-item__meta">
                              {SOURCE_LABELS[p.sourceType]} · {localTime(p.startsAt, filters.timezone)}–{localTime(p.endsAt, filters.timezone)}
                            </div>
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
                <p className="st-item__meta">
                  {localDateKey(selected.event.startsAt, filters.timezone)} · {localTime(selected.event.startsAt, filters.timezone)}–{localTime(selected.event.endsAt, filters.timezone)} · {filters.timezone}
                </p>
                <div className="st-actions st-actions--split">
                  <button type="button" className="btn tap" onClick={() => setSelectedId(null)}>Close</button>
                  <button type="button" className="btn btn--primary tap" onClick={() => nav(selected.event.sourceUrl)}>Go to source</button>
                </div>
              </>
            ) : (
              // Missing/forbidden render identically — never reveal whether the record exists (TC-285-06).
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
/* S-91 — Add to calendar (aggregation is read-only; manual add is future)     */
/* -------------------------------------------------------------------------- */
export function CalendarAdd() {
  const nav = useNavigate();
  return (
    <StudentScreen screenId="S-91">
      <div className="st-stack">
        <ModuleHead eyebrow="Calendar · S19" title="Add to calendar" sub="aggregated from your activity" />
        <section className="st-panel">
          <div className="ui-notice ui-notice--info" role="note">
            <span>
              Your calendar aggregates items you create in other modules (internships, exam prep, clinical hours,
              community). Manual one-off events and external calendar sync are planned and not enabled yet.
            </span>
          </div>
          <div className="st-actions">
            <button type="button" className="btn btn--primary tap" onClick={() => nav('/s-90')}>Back to calendar</button>
          </div>
        </section>
        <DpdpFootnote>Times display in your timezone ({DEFAULT_TZ}); external calendar sync is not enabled.</DpdpFootnote>
      </div>
    </StudentScreen>
  );
}
