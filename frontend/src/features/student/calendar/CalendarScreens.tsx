import { useEffect, useMemo, useState, type CSSProperties, type ReactNode } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useNavigate, useSearchParams } from 'react-router-dom';
import { useAuth } from '../../../app/authContext';
import {
  EmptyState,
  ErrorState,
  LoadingState,
  PrivacyNotice,
  RestrictedState,
  StatusBadge,
  ValidationState,
} from '../../../components/ui/primitives';
import { DpdpFootnote, StudentScreen } from '../components';
import {
  CALENDAR_SOURCE_TYPES,
  PERSONAL_EVENT_TYPES,
  PERSONAL_EVENT_TYPE_LABELS,
  SOURCE_LABELS,
  TIMEZONE_OPTIONS,
  localDateKey,
  localTime,
  isStrictCalendarDate,
  validateDateRange,
  zonedToUtcIso,
  type CalendarSourceType,
  type PersonalEventType,
} from '../lib/calendar';
import {
  calendarErrorCopy,
  checkCalendarConflicts,
  createCalendarEvent,
  createCalendarExport,
  deleteCalendarEvent,
  getCalendarEvent,
  getCalendarViewPreferences,
  listCalendarEvents,
  listCalendarExports,
  listCalendarReminderPreferences,
  revokeCalendarExport,
  rotateCalendarExport,
  updateCalendarEvent,
  updateCalendarConflict,
  updateCalendarReminderPreference,
  updateCalendarViewPreferences,
  type CalendarEventRecord,
  type CalendarReminderPreference,
  type CalendarViewPreferences,
  type ReminderLeadMinutes,
} from '../lib/calendarApi';
import '../../../styles/calendar.css';

const WEEKDAYS = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'];
const REMINDER_LEADS: readonly ReminderLeadMinutes[] = [0, 10, 30, 60, 120, 1440];

type MarkerCat = 'exam' | 'moot' | 'intern' | 'draft';
const CAT_FOR: Record<CalendarSourceType, MarkerCat> = {
  exam: 'exam', community: 'moot', moot: 'moot', reminder: 'moot',
  internship: 'intern', tutoring: 'intern', clinical: 'draft',
};
const LEGEND: ReadonlyArray<{ cat: MarkerCat; label: string }> = [
  { cat: 'exam', label: 'Exam prep' },
  { cat: 'moot', label: 'Community / moot' },
  { cat: 'intern', label: 'Internship / tutoring' },
  { cat: 'draft', label: 'Clinical / other' },
];

function markerDotStyle(cat: MarkerCat): CSSProperties {
  if (cat === 'exam') return { background: 'var(--info)', borderRadius: '50%' };
  if (cat === 'moot') return { background: 'var(--accent)', transform: 'rotate(45deg)' };
  if (cat === 'intern') return { background: 'var(--warn)' };
  return { background: 'var(--text2)', clipPath: 'polygon(50% 0,100% 100%,0 100%)' };
}

type CalendarTab = 'month' | 'add' | 'conflict' | 'reminders' | 'export';

function CalSubnav({ active }: { active?: CalendarTab }) {
  const nav = useNavigate();
  const tabs: ReadonlyArray<[CalendarTab, string, string]> = [
    ['month', 'Month', '/s-90'],
    ['add', 'Add event', '/s-91'],
    ['conflict', 'Conflict', '/s-92'],
    ['reminders', 'Reminders', '/s-93?tab=reminders'],
    ['export', 'Export', '/s-93?tab=export'],
  ];
  return (
    <nav className="subnav" aria-label="Calendar views">
      {tabs.map(([key, label, route]) => (
        <button key={key} type="button" className={active === key ? 'on' : ''}
          aria-current={active === key ? 'page' : undefined}
          onClick={() => nav(route)} data-testid={`cal-tab-${key}`}>{label}</button>
      ))}
    </nav>
  );
}

function AuthBoundary({ screenId, children }: { screenId: string; children: ReactNode }) {
  const auth = useAuth();
  if (auth.isAuthenticated && auth.roles.includes('student')) return <>{children}</>;
  return (
    <StudentScreen screenId={screenId} className="calv-screen">
      <div className="calv" data-wave5-ready="restricted">
        <RestrictedState reason="Sign in with your student account to use the unified calendar." />
      </div>
    </StudentScreen>
  );
}

function eventDateCopy(event: Pick<CalendarEventRecord, 'startsAt' | 'endsAt'>, timezone: string): string {
  return `${localDateKey(event.startsAt, timezone)} · ${localTime(event.startsAt, timezone)}–${localTime(event.endsAt, timezone)}`;
}

function sourceMarker(source: CalendarSourceType) {
  const cat = CAT_FOR[source];
  return <span className={`ev ${cat}`} aria-hidden style={{ padding: 5, width: 'auto' }}><span className="d" /></span>;
}

function readyState(pending: boolean, error: unknown): 'loading' | 'error' | 'ready' {
  return pending ? 'loading' : error ? 'error' : 'ready';
}

export function calendarEventReadyState({
  hasEvent,
  detailPending,
  detailFetching,
  savePending,
  removePending,
  error,
}: {
  hasEvent: boolean;
  detailPending: boolean;
  detailFetching: boolean;
  savePending: boolean;
  removePending: boolean;
  error: unknown;
}): 'loading' | 'error' | 'ready' {
  return readyState(
    (hasEvent && (detailPending || detailFetching)) || savePending || removePending,
    error,
  );
}

export function failedSourceRetryFilters(
  failedSources: readonly CalendarSourceType[],
  filters: Pick<CalendarViewPreferences, 'fromDate' | 'toDate' | 'timezone'>,
) {
  return {
    sourceTypes: [...failedSources],
    fromDate: filters.fromDate,
    toDate: filters.toDate,
    timezone: filters.timezone,
  };
}

export function reconcileFailedSourceRetry(
  current: { items: CalendarEventRecord[]; total: number; failedSources: CalendarSourceType[] },
  retried: { items: CalendarEventRecord[]; total: number; failedSources: CalendarSourceType[] },
  requestedSources: readonly CalendarSourceType[],
) {
  const requested = new Set(requestedSources);
  const items = [
    ...current.items.filter((item) => !requested.has(item.sourceType)),
    ...retried.items,
  ].sort((left, right) => left.startsAt.localeCompare(right.startsAt) || left.id.localeCompare(right.id));
  return {
    items,
    total: items.length,
    failedSources: retried.failedSources.filter((source) => requested.has(source)),
  };
}

/* S-90 — server-authoritative unified month view. */
export function CalendarMonth() {
  return <AuthBoundary screenId="S-90"><CalendarMonthAuthenticated /></AuthBoundary>;
}

function CalendarMonthAuthenticated() {
  const nav = useNavigate();
  const client = useQueryClient();
  const [showFilters, setShowFilters] = useState(false);
  const [filterMessage, setFilterMessage] = useState('');
  const preferences = useQuery({
    queryKey: ['calendar', 'view-preferences'],
    queryFn: getCalendarViewPreferences,
    retry: false,
  });
  const filters = preferences.data;
  const selectedSources = filters?.sourceTypes.length ? filters.sourceTypes : [...CALENDAR_SOURCE_TYPES];
  const events = useQuery({
    queryKey: ['calendar', 'events', selectedSources, filters?.fromDate, filters?.toDate, filters?.timezone],
    queryFn: () => listCalendarEvents({
      sourceTypes: selectedSources,
      fromDate: filters?.fromDate,
      toDate: filters?.toDate,
      timezone: filters?.timezone,
    }),
    enabled: Boolean(filters),
    retry: false,
  });
  const retryFailedSources = useMutation({
    mutationFn: async (failedSources: CalendarSourceType[]) => ({
      requestedSources: failedSources,
      result: await listCalendarEvents(failedSourceRetryFilters(failedSources, {
        fromDate: filters?.fromDate ?? null,
        toDate: filters?.toDate ?? null,
        timezone: filters?.timezone ?? 'Asia/Kolkata',
      })),
    }),
    onSuccess: ({ requestedSources, result }) => {
      client.setQueryData(
        ['calendar', 'events', selectedSources, filters?.fromDate, filters?.toDate, filters?.timezone],
        (current: { items: CalendarEventRecord[]; total: number; failedSources: CalendarSourceType[] } | undefined) => (
          current ? reconcileFailedSourceRetry(current, result, requestedSources) : result
        ),
      );
    },
  });
  const savePreferences = useMutation({
    mutationFn: updateCalendarViewPreferences,
    onSuccess: (next) => client.setQueryData(['calendar', 'view-preferences'], next),
    onError: () => { void preferences.refetch(); },
  });

  const error = preferences.error ?? events.error ?? savePreferences.error;
  const pending = preferences.isPending || (Boolean(filters) && events.isPending);
  const timezone = filters?.timezone ?? 'Asia/Kolkata';
  const now = new Date();
  const zonedToday = localDateKey(now.toISOString(), timezone);
  const year = Number(zonedToday.slice(0, 4));
  const month = Number(zonedToday.slice(5, 7)) - 1;
  const monthLabel = new Intl.DateTimeFormat('en-GB', { month: 'long', year: 'numeric', timeZone: timezone }).format(now);
  const todayKey = zonedToday;
  const daysInMonth = new Date(year, month + 1, 0).getDate();
  const lead = (new Date(year, month, 1).getDay() + 6) % 7;
  const mm = String(month + 1).padStart(2, '0');
  const visible = events.data?.items ?? [];
  const byDay = useMemo(() => {
    const result = new Map<number, CalendarEventRecord[]>();
    for (const event of visible) {
      const key = localDateKey(event.startsAt, timezone);
      if (key.slice(0, 7) !== `${year}-${mm}`) continue;
      const day = Number(key.slice(8, 10));
      result.set(day, [...(result.get(day) ?? []), event]);
    }
    return result;
  }, [visible, timezone, year, mm]);
  const upcoming = visible.filter((event) => event.startsAt >= now.toISOString()).slice(0, 3);
  const dateError = filters ? validateDateRange(filters.fromDate, filters.toDate) : null;

  const updateFilters = (changes: Partial<CalendarViewPreferences>) => {
    if (!filters || savePreferences.isPending) return;
    savePreferences.mutate({
      viewMode: changes.viewMode ?? filters.viewMode,
      sourceTypes: changes.sourceTypes ?? filters.sourceTypes,
      fromDate: Object.prototype.hasOwnProperty.call(changes, 'fromDate') ? changes.fromDate ?? null : filters.fromDate,
      toDate: Object.prototype.hasOwnProperty.call(changes, 'toDate') ? changes.toDate ?? null : filters.toDate,
      timezone: changes.timezone ?? filters.timezone,
      expectedVersion: filters.version,
    });
  };

  const toggleSource = (source: CalendarSourceType) => {
    if (!filters) return;
    const selected = selectedSources.includes(source);
    if (selected && selectedSources.length === 1) {
      setFilterMessage('Keep at least one calendar source selected.');
      return;
    }
    setFilterMessage('');
    updateFilters({ sourceTypes: selected ? selectedSources.filter((item) => item !== source) : [...selectedSources, source] });
  };

  return (
    <StudentScreen screenId="S-90" className="calv-screen">
      <main className="calv" data-testid="cal-feature-region" data-qa-crop="calendar-feature"
        data-wave5-ready={readyState(pending, error)}>
        <CalSubnav active="month" />
        <h1 className="lede">Unified Calendar <span className="m">· S-90</span></h1>
        <p className="stand">Every LegalSaathi module writes to one private, server-authoritative calendar.</p>

        {showFilters && filters && (
          <section className="card filters" id="cal-filters" aria-label="Calendar filters">
            <div className="ph"><span className="t">Filter by source &amp; date</span></div>
            <div className="st-tabsrow" role="group" aria-label="Filter by source">
              {CALENDAR_SOURCE_TYPES.map((source) => (
                <button key={source} type="button" className="chip"
                  aria-pressed={selectedSources.includes(source)} onClick={() => toggleSource(source)}
                  disabled={savePreferences.isPending} data-testid={`cal-source-${source}`}>
                  <span className="g" />{SOURCE_LABELS[source]}
                </button>
              ))}
            </div>
            {filterMessage && <ValidationState fieldId="cal-source" message={filterMessage} />}
            <div className="cols2 cal-filter-dates">
              <div><label className="lbl" htmlFor="cal-from">From date</label>
                <input id="cal-from" className="field" type="date" value={filters.fromDate ?? ''}
                  aria-invalid={Boolean(dateError)} onChange={(event) => updateFilters({ fromDate: event.target.value || null })} /></div>
              <div><label className="lbl" htmlFor="cal-to">To date</label>
                <input id="cal-to" className="field" type="date" value={filters.toDate ?? ''}
                  aria-invalid={Boolean(dateError)} onChange={(event) => updateFilters({ toDate: event.target.value || null })} /></div>
            </div>
            <label className="lbl cal-filter-tz" htmlFor="cal-tz">Timezone</label>
            <select id="cal-tz" className="field" value={filters.timezone}
              onChange={(event) => updateFilters({ timezone: event.target.value })}>
              {TIMEZONE_OPTIONS.map((zone) => <option key={zone}>{zone}</option>)}
            </select>
            {dateError && <ValidationState fieldId="cal-date" message="From date must be on or before To date." />}
            <button type="button" className="btn cal-clear" onClick={() => updateFilters({ fromDate: null, toDate: null })}>Clear dates</button>
          </section>
        )}

        <div className="legend" aria-label="Calendar event legend">
          {LEGEND.map((item) => <span key={item.cat}><span className="d" style={markerDotStyle(item.cat)} />{item.label}</span>)}
        </div>

        {pending && <LoadingState label="Loading your private calendar…" />}
        {error && <ErrorState title="Calendar unavailable" detail={calendarErrorCopy(error)} onRetry={() => { void preferences.refetch(); void events.refetch(); }} />}
        {!pending && !error && events.data && (
          <>
            {events.data.failedSources.length > 0 && (
              <div className="ui-notice ui-notice--warn" role="status">
                Some sources did not load: {events.data.failedSources.map((source) => SOURCE_LABELS[source]).join(', ')}.
                <button type="button" className="btn" disabled={retryFailedSources.isPending}
                  onClick={() => retryFailedSources.mutate(events.data.failedSources)}>
                  {retryFailedSources.isPending ? 'Retrying failed sources…' : 'Retry failed sources'}
                </button>
                {retryFailedSources.error && <span>Failed-source retry was not completed.</span>}
              </div>
            )}
            <div className="two-b">
              <section>
                <div className="ph">
                  <span className="t">{monthLabel}</span>
                  <span className="cal-heading-actions"><span className="a">{events.data.total} events</span>
                    <button type="button" className="chip" aria-expanded={showFilters} aria-controls="cal-filters"
                      onClick={() => setShowFilters((value) => !value)}><span className="g" />Filter</button></span>
                </div>
                <div className="cal" role="group" aria-label={`Calendar ${monthLabel}`}>
                  {WEEKDAYS.map((weekday) => <div className="hd" key={weekday}>{weekday}</div>)}
                  {Array.from({ length: lead }, (_, index) => <div className="cell dim" key={`lead-${index}`} aria-hidden />)}
                  {Array.from({ length: daysInMonth }, (_, index) => {
                    const day = index + 1;
                    const key = `${year}-${mm}-${String(day).padStart(2, '0')}`;
                    const items = byDay.get(day) ?? [];
                    return (
                      <div className={`cell${key === todayKey ? ' today' : ''}`} key={day}>
                        <span className="dn">{day}</span>
                        {items.slice(0, 2).map((item) => (
                          <button key={item.id} type="button" className={`ev ${CAT_FOR[item.sourceType]}`}
                            title={item.title} onClick={() => nav(`/s-91?event=${encodeURIComponent(item.id)}`)}>
                            <span className="d" />{localTime(item.startsAt, timezone)} {item.title.length > 8 ? `${item.title.slice(0, 8)}…` : item.title}
                          </button>
                        ))}
                      </div>
                    );
                  })}
                </div>
                {visible.length === 0 && <EmptyState title="Nothing scheduled" hint="Adjust the filters or add a personal event." action={<button className="btn" onClick={() => nav('/s-91')}>Add event</button>} />}
              </section>
              <aside className="col">
                <div className="card tint"><div className="ph"><span className="t">One calendar</span></div>
                  <p className="cal-copy">Exams, moots, internships, clinical hours, tutoring and your own reminders—without copying private source records into browser storage.</p></div>
                <div className="card"><div className="ph"><span className="t">Coming up</span><button className="btn" onClick={() => nav('/s-91')}>Add</button></div>
                  {upcoming.length === 0 ? <p className="rem__m">Nothing coming up in this view.</p> : upcoming.map((item) => (
                    <button type="button" className="rem cal-event-row" key={item.id} onClick={() => nav(`/s-91?event=${encodeURIComponent(item.id)}`)}>
                      {sourceMarker(item.sourceType)}<span><span className="rem__t">{item.title}</span><span className="rem__m">{eventDateCopy(item, timezone)}</span></span>
                    </button>
                  ))}
                </div>
              </aside>
            </div>
          </>
        )}
        <DpdpFootnote>Calendar preferences and personal events are stored against your authenticated account, not in browser storage.</DpdpFootnote>
      </main>
    </StudentScreen>
  );
}

interface EventFormState { title: string; date: string; time: string; type: PersonalEventType; timezone: string }
const EMPTY_EVENT: EventFormState = { title: '', date: '', time: '', type: 'reminder', timezone: 'Asia/Kolkata' };

function formFromEvent(event: CalendarEventRecord): EventFormState {
  return {
    title: event.title,
    date: localDateKey(event.startsAt, event.timezone),
    time: localTime(event.startsAt, event.timezone),
    type: event.eventKind ?? (event.status === 'deadline' ? 'deadline' : 'reminder'),
    timezone: event.timezone,
  };
}

function eventPayload(form: EventFormState) {
  const title = form.title.trim();
  if (!title) throw new Error('Enter a title.');
  if (title.length > 160) throw new Error('Use 160 characters or fewer for the title.');
  if (!isStrictCalendarDate(form.date)) throw new Error('Choose a real calendar date.');
  if (!/^\d{2}:\d{2}$/.test(form.time)) throw new Error('Choose a valid time.');
  let startsAt: string;
  try { startsAt = zonedToUtcIso(form.date, form.time, form.timezone); }
  catch { throw new Error('That local time does not exist in the selected timezone.'); }
  const endsAt = new Date(new Date(startsAt).getTime() + 60 * 60 * 1000).toISOString();
  return {
    title,
    startsAt,
    endsAt,
    timezone: form.timezone,
    status: form.type === 'deadline' ? 'deadline' as const : 'scheduled' as const,
    privacyClassification: 'personal' as const,
    eventKind: form.type,
  };
}

/* S-91 — personal event create, detail, edit and delete. */
export function CalendarAdd() {
  return <AuthBoundary screenId="S-91"><CalendarEventScreen /></AuthBoundary>;
}

function CalendarEventScreen() {
  const nav = useNavigate();
  const client = useQueryClient();
  const [params] = useSearchParams();
  const eventId = params.get('event');
  const [editing, setEditing] = useState(false);
  const [form, setForm] = useState<EventFormState>(EMPTY_EVENT);
  const [message, setMessage] = useState('');
  const detail = useQuery({
    queryKey: ['calendar', 'event', eventId],
    queryFn: () => getCalendarEvent(eventId!),
    enabled: Boolean(eventId),
    retry: false,
  });
  useEffect(() => {
    if (detail.data) setForm(formFromEvent(detail.data));
  }, [detail.data]);

  const save = useMutation({
    mutationFn: async () => {
      const payload = eventPayload(form);
      return eventId && detail.data
        ? updateCalendarEvent(eventId, { ...payload, expectedVersion: detail.data.version })
        : createCalendarEvent(payload);
    },
    onSuccess: async (event) => {
      setMessage('');
      await client.invalidateQueries({ queryKey: ['calendar'] });
      setEditing(false);
      nav(`/s-91?event=${encodeURIComponent(event.id)}`, { replace: true });
    },
    onError: (error) => setMessage(calendarErrorCopy(error)),
  });
  const remove = useMutation({
    mutationFn: () => deleteCalendarEvent(eventId!),
    onSuccess: async () => {
      await client.invalidateQueries({ queryKey: ['calendar'] });
      nav('/s-90', { replace: true });
    },
    onError: (error) => setMessage(calendarErrorCopy(error)),
  });

  const showForm = !eventId || editing;
  const ready = calendarEventReadyState({
    hasEvent: Boolean(eventId),
    detailPending: detail.isPending,
    detailFetching: detail.isFetching,
    savePending: save.isPending,
    removePending: remove.isPending,
    error: detail.error,
  });
  const set = <K extends keyof EventFormState>(key: K, value: EventFormState[K]) => {
    setForm((current) => ({ ...current, [key]: value }));
    setMessage('');
  };
  const submit = () => {
    try { eventPayload(form); save.mutate(); }
    catch (error) { setMessage(error instanceof Error ? error.message : 'Check the event details.'); }
  };

  return (
    <StudentScreen screenId="S-91" className="calv-screen">
      <main className="calv" data-testid="cal-feature-region" data-qa-crop="calendar-feature" data-wave5-ready={ready}>
        <CalSubnav active={eventId ? undefined : 'add'} />
        <h1 className="lede">{eventId ? 'Event details' : 'Add event'} <span className="m">· S-91</span></h1>
        <p className="stand ident">{eventId ? 'Open the source, or manage a personal event you created.' : 'Add a private personal event to your unified calendar.'}</p>

        {eventId && detail.isPending && <LoadingState label="Loading event…" />}
        {eventId && detail.error && <ErrorState title="This item isn’t available" detail={calendarErrorCopy(detail.error)} onRetry={() => void detail.refetch()} />}
        {eventId && detail.data && !editing && (
          <section className="card cardw" aria-label="Event detail">
            <div className="ph"><span className="t">{SOURCE_LABELS[detail.data.sourceType]}</span><StatusBadge status="info" label={detail.data.status} /></div>
            <h2 className="cal-event-title">{detail.data.title}</h2>
            <p className="rem__m">{eventDateCopy(detail.data, detail.data.timezone)} · {detail.data.timezone}</p>
            {detail.data.eventKind && <p className="cal-field-help">Type: {PERSONAL_EVENT_TYPE_LABELS[detail.data.eventKind]}</p>}
            <PrivacyNotice>{detail.data.privacyClassification === 'restricted' ? 'Restricted event details remain visible only to your account.' : 'This event belongs to your private calendar.'}</PrivacyNotice>
            <div className="st-actions st-actions--split cal-detail-actions">
              <button type="button" className="btn" onClick={() => nav('/s-90')}>Back</button>
              {detail.data.eventKind !== null ? <>
                <button type="button" className="btn" onClick={() => setEditing(true)}>Edit</button>
                <button type="button" className="btn cal-danger" disabled={remove.isPending} onClick={() => remove.mutate()}>{remove.isPending ? 'Deleting…' : 'Delete'}</button>
              </> : <button type="button" className="btn solid" onClick={() => nav(detail.data.sourceUrl)}>Go to source</button>}
            </div>
          </section>
        )}

        {showForm && (
          <section className="card cardw" aria-label={eventId ? 'Edit personal event' : 'New personal event'}>
            <div className="ph"><span className="t">{eventId ? 'Edit personal event' : 'New event'}</span></div>
            <label className="lbl" htmlFor="ev-title">Title</label>
            <input id="ev-title" className="field" value={form.title} maxLength={160} data-testid="ev-title"
              aria-invalid={Boolean(message)} onChange={(event) => set('title', event.target.value)} />
            <span className="cal-field-help">{form.title.length} / 160</span>
            <div className="cols2 cal-form-row">
              <div><label className="lbl" htmlFor="ev-date">Date</label><input id="ev-date" className="field" type="date" value={form.date} data-testid="ev-date" onChange={(event) => set('date', event.target.value)} /></div>
              <div><label className="lbl" htmlFor="ev-time">Time</label><input id="ev-time" className="field" type="time" value={form.time} data-testid="ev-time" onChange={(event) => set('time', event.target.value)} /></div>
            </div>
            <label className="lbl cal-filter-tz" htmlFor="ev-timezone">Timezone</label>
            <select id="ev-timezone" className="field" value={form.timezone} onChange={(event) => set('timezone', event.target.value)}>
              {TIMEZONE_OPTIONS.map((zone) => <option key={zone}>{zone}</option>)}
            </select>
            <div className="lbl cal-type-label" id="ev-type-label">Type</div>
            <div className="type-chips" role="group" aria-labelledby="ev-type-label">
              {PERSONAL_EVENT_TYPES.map((type) => (
                <button key={type} type="button" className="chip" aria-pressed={form.type === type}
                  data-testid={`ev-type-${type}`} onClick={() => set('type', type)}><span className="g" />{PERSONAL_EVENT_TYPE_LABELS[type]}</button>
              ))}
            </div>
            {message && <ValidationState fieldId="ev" message={message} />}
            <div className="st-actions st-actions--split cal-detail-actions">
              <button type="button" className="btn" onClick={() => eventId ? setEditing(false) : nav('/s-90')}>Cancel</button>
              <button type="button" className="btn solid" disabled={save.isPending} onClick={submit} data-testid="ev-add">{save.isPending ? 'Saving…' : eventId ? 'Save changes' : 'Add to calendar'}</button>
            </div>
          </section>
        )}
        <DpdpFootnote>Personal events are written to your authenticated account. LegalSaathi does not store them in localStorage.</DpdpFootnote>
      </main>
    </StudentScreen>
  );
}

/* S-92 — real server conflict detection. */
export function CalendarConflictScreen() {
  return <AuthBoundary screenId="S-92"><CalendarConflictAuthenticated /></AuthBoundary>;
}

function CalendarConflictAuthenticated() {
  const nav = useNavigate();
  const client = useQueryClient();
  const [message, setMessage] = useState('');
  const conflicts = useQuery({
    queryKey: ['calendar', 'conflicts'],
    queryFn: () => checkCalendarConflicts(undefined, true),
    retry: false,
  });
  const update = useMutation({
    mutationFn: ({ id, status, version }: { id: string; status: 'dismissed' | 'resolved'; version: number }) =>
      updateCalendarConflict(id, status, version),
    onSuccess: async (_, variables) => {
      setMessage(variables.status === 'resolved' ? 'Conflict marked resolved.' : 'Conflict dismissed.');
      await client.invalidateQueries({ queryKey: ['calendar', 'conflicts'] });
    },
    onError: (error) => setMessage(calendarErrorCopy(error)),
  });
  return (
    <StudentScreen screenId="S-92" className="calv-screen">
      <main className="calv" data-wave5-ready={readyState(conflicts.isPending, conflicts.error)}>
        <CalSubnav active="conflict" />
        <h1 className="lede">Schedule conflicts <span className="m">· S-92</span></h1>
        <p className="stand ident">Overlapping events are compared as half-open intervals, so back-to-back events remain valid.</p>
        {conflicts.isPending && <LoadingState label="Checking your schedule…" />}
        {conflicts.error && <ErrorState title="Conflict check unavailable" detail={calendarErrorCopy(conflicts.error)} onRetry={() => void conflicts.refetch()} />}
        {conflicts.data?.total === 0 && <EmptyState title="No conflicts found" hint="Your current events do not overlap." action={<button className="btn" onClick={() => nav('/s-90')}>View calendar</button>} />}
        {conflicts.data && conflicts.data.total > 0 && (
          <div className="cal-conflict-list" aria-label={`${conflicts.data.total} calendar conflicts`}>
            {conflicts.data.items.map((conflict) => (
              <section className="card cal-conflict" key={conflict.id}>
                <div className="ph"><span className="t">Conflict detected</span><StatusBadge status="warn" label={conflict.status} /></div>
                {[conflict.left, conflict.right].map((event) => (
                  <button key={event.id} type="button" className="rem cal-event-row" onClick={() => nav(`/s-91?event=${encodeURIComponent(event.id)}`)}>
                    {sourceMarker(event.sourceType)}<span><span className="rem__t">{event.title}</span><span className="rem__m">{eventDateCopy(event, event.timezone)} · {SOURCE_LABELS[event.sourceType]}</span></span>
                  </button>
                ))}
                <div className="st-actions cal-detail-actions">
                  <button type="button" className="btn" disabled={update.isPending || conflict.status === 'dismissed'}
                    onClick={() => update.mutate({ id: conflict.id, status: 'dismissed', version: conflict.version })}>Dismiss</button>
                  <button type="button" className="btn solid" disabled={update.isPending || conflict.status === 'resolved'}
                    onClick={() => update.mutate({ id: conflict.id, status: 'resolved', version: conflict.version })}>Mark resolved</button>
                </div>
              </section>
            ))}
          </div>
        )}
        {message && <p className="cal-field-help" role="status">{message}</p>}
        <DpdpFootnote>Conflict checks compare only event timing and privacy-safe previews. Source records remain in their owning modules.</DpdpFootnote>
      </main>
    </StudentScreen>
  );
}

function minutesToTime(value: number): string {
  return `${String(Math.floor(value / 60)).padStart(2, '0')}:${String(value % 60).padStart(2, '0')}`;
}

function timeToMinutes(value: string): number {
  const [hours, minutes] = value.split(':').map(Number);
  return hours * 60 + minutes;
}

function leadCopy(value: number): string {
  if (value === 0) return 'At event time';
  if (value === 1440) return '1 day before';
  if (value >= 60) return `${value / 60} hour${value === 60 ? '' : 's'} before`;
  return `${value} minutes before`;
}

export async function copyPrivateFeedUrl(
  feedUrl: string,
  clipboard: Pick<Clipboard, 'writeText'>,
): Promise<{ copied: boolean; retainedFeedUrl: string | null }> {
  try {
    await clipboard.writeText(feedUrl);
    return { copied: true, retainedFeedUrl: null };
  } catch {
    return { copied: false, retainedFeedUrl: feedUrl };
  }
}

function ReminderRow({ preference }: { preference: CalendarReminderPreference }) {
  const client = useQueryClient();
  const [message, setMessage] = useState('');
  const [draft, setDraft] = useState(preference);
  const [expanded, setExpanded] = useState(false);
  const controlsId = `cal-reminder-controls-${preference.id}`;
  useEffect(() => setDraft(preference), [preference]);
  const update = useMutation({
    mutationFn: (next: Partial<CalendarReminderPreference>) => updateCalendarReminderPreference({
      sourceType: draft.sourceType,
      channel: draft.channel,
      enabled: next.enabled ?? draft.enabled,
      leadMinutes: next.leadMinutes ?? draft.leadMinutes,
      quietStartMin: next.quietStartMin ?? draft.quietStartMin,
      quietEndMin: next.quietEndMin ?? draft.quietEndMin,
      timezone: next.timezone ?? draft.timezone,
      expectedVersion: draft.version,
    }),
    onMutate: (next) => {
      // A controlled checkbox/select must reflect the user's choice in the
      // same interaction frame. Waiting for a refetch makes the native control
      // snap back to its stale server prop while the request is in flight.
      setDraft((current) => ({ ...current, ...next }));
    },
    onSuccess: (saved) => {
      setDraft(saved);
      client.setQueryData<CalendarReminderPreference[]>(['calendar', 'reminder-preferences'], (current) =>
        current?.map((item) => item.id === saved.id ? saved : item));
      setMessage('Saved.');
    },
    onError: (error) => {
      setDraft(preference);
      setMessage(calendarErrorCopy(error));
      void client.invalidateQueries({ queryKey: ['calendar', 'reminder-preferences'] });
    },
  });
  return (
    <section className="card cal-reminder-row" data-expanded={expanded}
      data-testid={`cal-reminder-${preference.sourceType}-${preference.channel}`}>
      <div className="ph"><span className="t">{SOURCE_LABELS[preference.sourceType]} · {preference.channel.replace(/_/g, ' ')}</span>
        <span className="cal-reminder-heading-actions">
          <StatusBadge status={draft.enabled ? 'ok' : 'info'} label={draft.enabled ? 'Enabled' : 'Off'} />
          <button type="button" className="btn cal-reminder-disclosure" aria-expanded={expanded}
            aria-controls={controlsId}
            aria-label={`${expanded ? 'Close' : 'Configure'} ${SOURCE_LABELS[preference.sourceType]} ${preference.channel.replace(/_/g, ' ')} reminder`}
            onClick={() => setExpanded((current) => !current)}>
            {expanded ? 'Close' : 'Configure'}<span aria-hidden="true">{expanded ? '↑' : '↓'}</span>
          </button>
        </span></div>
      <div className="cal-reminder-controls" id={controlsId}>
        <label className="cal-toggle"><input type="checkbox" checked={draft.enabled} disabled={update.isPending}
          onChange={(event) => update.mutate({ enabled: event.target.checked })} /><span>Send this reminder</span></label>
        <label><span className="lbl">Lead time</span><select className="field" value={draft.leadMinutes} disabled={!draft.enabled || update.isPending}
          onChange={(event) => update.mutate({ leadMinutes: Number(event.target.value) as ReminderLeadMinutes })}>
          {REMINDER_LEADS.map((lead) => <option key={lead} value={lead}>{leadCopy(lead)}</option>)}</select></label>
        <label><span className="lbl">Quiet hours start</span><input className="field" type="time" value={minutesToTime(draft.quietStartMin)}
          disabled={!draft.enabled || update.isPending} onChange={(event) => update.mutate({ quietStartMin: timeToMinutes(event.target.value) })} /></label>
        <label><span className="lbl">Quiet hours end</span><input className="field" type="time" value={minutesToTime(draft.quietEndMin)}
          disabled={!draft.enabled || update.isPending} onChange={(event) => update.mutate({ quietEndMin: timeToMinutes(event.target.value) })} /></label>
        <label><span className="lbl">Timezone</span><select className="field" value={draft.timezone}
          disabled={!draft.enabled || update.isPending} onChange={(event) => update.mutate({ timezone: event.target.value })}>
          {TIMEZONE_OPTIONS.map((zone) => <option key={zone}>{zone}</option>)}</select></label>
      </div>
      {message && <p className="cal-field-help" role="status">{message}</p>}
    </section>
  );
}

/* S-93 — reminder preferences and private iCalendar export lifecycle. */
export function CalendarPreferencesScreen() {
  return <AuthBoundary screenId="S-93"><CalendarPreferencesAuthenticated /></AuthBoundary>;
}

function CalendarPreferencesAuthenticated() {
  const [params, setParams] = useSearchParams();
  const tab = params.get('tab') === 'export' ? 'export' : 'reminders';
  const client = useQueryClient();
  const [oneTimeFeedUrl, setOneTimeFeedUrl] = useState<string | null>(null);
  const [message, setMessage] = useState('');
  const reminders = useQuery({
    queryKey: ['calendar', 'reminder-preferences'],
    queryFn: listCalendarReminderPreferences,
    enabled: tab === 'reminders',
    retry: false,
  });
  const exportsQuery = useQuery({
    queryKey: ['calendar', 'exports'],
    queryFn: listCalendarExports,
    enabled: tab === 'export',
    retry: false,
  });
  const viewPreferences = useQuery({
    queryKey: ['calendar', 'view-preferences'],
    queryFn: getCalendarViewPreferences,
    enabled: tab === 'export',
    retry: false,
  });
  const activeExport = exportsQuery.data?.items.find((item) => item.status === 'active' && !item.revokedAt);
  const latestInactiveExport = exportsQuery.data?.items.find((item) => item.status !== 'active' || Boolean(item.revokedAt));
  const suggestedExportTimezone = activeExport?.timezone ?? viewPreferences.data?.timezone ?? 'Asia/Kolkata';
  const [exportTimezone, setExportTimezone] = useState(suggestedExportTimezone);
  useEffect(() => setExportTimezone(suggestedExportTimezone), [suggestedExportTimezone]);
  const createExport = useMutation({
    mutationFn: () => createCalendarExport(exportTimezone),
    onSuccess: async (created) => {
      setOneTimeFeedUrl(created.oneTimeFeedUrl);
      setMessage(created.oneTimeFeedUrl ? 'Private feed created. Copy it now; LegalSaathi will not show it again.' : 'Feed metadata created, but no reusable secret was returned.');
      await client.invalidateQueries({ queryKey: ['calendar', 'exports'] });
    },
    onError: (error) => setMessage(calendarErrorCopy(error)),
  });
  const rotate = useMutation({
    // POST /exports performs the old-capability revocation and replacement
    // creation in one backend transaction. Never issue DELETE then POST here.
    mutationFn: () => rotateCalendarExport(exportTimezone),
    onMutate: () => {
      setOneTimeFeedUrl(null);
      setMessage('Rotating the private feed…');
    },
    onSuccess: async (created) => {
      setOneTimeFeedUrl(created.oneTimeFeedUrl);
      setMessage(created.oneTimeFeedUrl
        ? 'Previous feed atomically rotated. Copy the replacement now; LegalSaathi will not show it again.'
        : 'Feed rotation completed, but no replacement secret was returned. Refresh before retrying.');
      await client.invalidateQueries({ queryKey: ['calendar', 'exports'] });
    },
    onError: async (error) => {
      setMessage(`Feed rotation failed; your existing feed remains active. ${calendarErrorCopy(error)}`);
      await client.invalidateQueries({ queryKey: ['calendar', 'exports'] });
    },
  });
  const revoke = useMutation({
    mutationFn: revokeCalendarExport,
    onSuccess: async () => {
      setOneTimeFeedUrl(null);
      setMessage('Private feed revoked. Calendar apps can no longer refresh it.');
      await client.invalidateQueries({ queryKey: ['calendar', 'exports'] });
    },
    onError: (error) => setMessage(calendarErrorCopy(error)),
  });
  const copyOnce = async () => {
    if (!oneTimeFeedUrl) return;
    const outcome = await copyPrivateFeedUrl(oneTimeFeedUrl, navigator.clipboard);
    setOneTimeFeedUrl(outcome.retainedFeedUrl);
    if (outcome.copied) {
      setMessage('Copied. The one-time URL has been cleared from this page.');
    } else {
      setMessage('Copy was blocked by the browser. The one-time URL is still available on this page; allow clipboard access and retry.');
    }
  };
  const pending = tab === 'reminders' ? reminders.isPending : exportsQuery.isPending || viewPreferences.isPending;
  const error = tab === 'reminders' ? reminders.error : exportsQuery.error ?? viewPreferences.error;

  return (
    <StudentScreen screenId="S-93" className="calv-screen">
      <main className="calv" data-wave5-ready={readyState(pending, error)}>
        <CalSubnav active={tab} />
        <h1 className="lede">{tab === 'reminders' ? 'Reminder preferences' : 'Calendar export'} <span className="m">· S-93</span></h1>
        <p className="stand ident">{tab === 'reminders' ? 'Choose privacy-safe reminders and quiet hours for each source.' : 'Create a revocable, read-only iCalendar feed for your own calendar app.'}</p>
        <nav className="cal-mode-tabs" aria-label="Calendar settings">
          <button type="button" aria-current={tab === 'reminders' ? 'page' : undefined} className={`btn${tab === 'reminders' ? ' solid' : ''}`} onClick={() => setParams({ tab: 'reminders' })}>Reminders</button>
          <button type="button" aria-current={tab === 'export' ? 'page' : undefined} className={`btn${tab === 'export' ? ' solid' : ''}`} onClick={() => setParams({ tab: 'export' })}>Export</button>
        </nav>
        {pending && <LoadingState label={tab === 'reminders' ? 'Loading reminder preferences…' : 'Loading export status…'} />}
        {error && (
          <ErrorState
            title="Calendar settings unavailable"
            detail={calendarErrorCopy(error)}
            onRetry={() => {
              if (tab === 'reminders') {
                void reminders.refetch();
                return;
              }
              void exportsQuery.refetch();
              void viewPreferences.refetch();
            }}
          />
        )}

        {tab === 'reminders' && reminders.data && (
          reminders.data.length === 0
            ? <EmptyState title="No reminder channels configured" hint="Your account has no server-managed reminder preferences yet." />
            : <div className="cal-preference-list">{reminders.data.map((preference) => <ReminderRow key={preference.id} preference={preference} />)}</div>
        )}

        {tab === 'export' && exportsQuery.data && (
          <section className="card cardw cal-export-card">
            <div className="ph"><span className="t">Private iCalendar feed</span><StatusBadge status={activeExport ? 'ok' : 'info'} label={activeExport ? 'Active' : 'Not active'} /></div>
            <PrivacyNotice>Anyone holding this private URL can read the feed until it expires or you revoke it. Add it only to a calendar account you control. Recording raw feed URLs in logs or browser storage is prohibited.</PrivacyNotice>
            <label className="lbl" htmlFor="cal-export-timezone">Export timezone</label>
            <select id="cal-export-timezone" className="field" value={exportTimezone}
              disabled={createExport.isPending || rotate.isPending} onChange={(event) => setExportTimezone(event.target.value)}>
              {TIMEZONE_OPTIONS.map((zone) => <option key={zone}>{zone}</option>)}
            </select>
            {activeExport ? <>
              <p className="rem__m">Expires {new Date(activeExport.expiresAt).toLocaleString()} · {activeExport.timezone}</p>
              <div className="st-actions">
                <button type="button" className="btn solid" disabled={rotate.isPending || revoke.isPending}
                  onClick={() => rotate.mutate()}>{rotate.isPending ? 'Rotating…' : 'Rotate feed'}</button>
                <button type="button" className="btn cal-danger" disabled={revoke.isPending || rotate.isPending}
                  onClick={() => revoke.mutate(activeExport.id)}>{revoke.isPending ? 'Revoking…' : 'Revoke feed'}</button>
              </div>
            </> : <>
              {latestInactiveExport && <p className="rem__m">Previous feed: {latestInactiveExport.revokedAt ? 'revoked' : latestInactiveExport.status}. You may create a replacement.</p>}
              <button type="button" className="btn solid" disabled={createExport.isPending || !viewPreferences.data} onClick={() => createExport.mutate()}>{createExport.isPending ? 'Creating…' : 'Create private feed'}</button>
            </>}
            {oneTimeFeedUrl && (
              <div className="cal-one-time" role="status">
                <strong>One-time secret ready</strong>
                <span>For privacy, the URL is not displayed or stored. Copy it directly to your clipboard now.</span>
                <button type="button" className="btn solid" onClick={copyOnce}>Copy private feed URL</button>
              </div>
            )}
            {message && <p className="cal-field-help" role="status">{message}</p>}
          </section>
        )}
        <DpdpFootnote>Reminder previews omit sensitive event details. Export secrets are returned once, never persisted in browser storage, and can be revoked.</DpdpFootnote>
      </main>
    </StudentScreen>
  );
}
