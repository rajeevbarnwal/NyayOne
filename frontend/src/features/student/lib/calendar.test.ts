import { describe, expect, it } from 'vitest';
import { InMemoryKvStore } from '../../../lib/kvStore';
import {
  aggregate, runAdapter, normalizeEvent, sortEvents, filterEvents,
  localDateKey, localTime, resolveEventBadge, getSavedViewMode, saveViewMode, toPreview, previewLeaksRestricted, resolveDeepLink,
  eventId, CalendarError, CalendarService, defaultFilters, sampleSourceResults,
  runLoaders, retryFailed, deriveStatus, calendarLoaders,
  validateDateRange, validatePersonalEvent, PersonalEventError, zonedToUtcIso, SOURCE_ROUTE,
  SAMPLE_INTERNSHIP_EVENTS, SAMPLE_EXAM_EVENTS, SAMPLE_CLINICAL_EVENTS,
  type RawSourceRecord, type SourceLoader, type PersonalEventInput,
} from './calendar';

const raw = (id: string, startsAt: string, url = '/x'): RawSourceRecord => ({ sourceId: id, title: `t-${id}`, startsAt, sourceUrl: url });

describe('SAATHI-285/287 calendar aggregation contract', () => {
  it('TC-285-01: aggregates >=2 source adapters and sorts chronologically', () => {
    const results = [
      runAdapter('exam', () => [raw('a', '2026-07-19T04:30:00Z', '/exam/a')]),
      runAdapter('internship', () => [raw('b', '2026-07-18T04:30:00Z', '/internships/b')]),
    ];
    const { events, okSources } = aggregate(results);
    expect(okSources).toEqual(['exam', 'internship']);
    expect(events.map((e) => e.sourceType)).toEqual(['internship', 'exam']); // 18th before 19th
    expect(events[0].id).toBe(eventId('internship', 'b'));
  });

  it('TC-285-01: stable secondary sort by id when starts_at ties', () => {
    const same = '2026-07-19T04:30:00Z';
    const evs = sortEvents([
      normalizeEvent('exam', raw('z', same, '/exam/z')),
      normalizeEvent('internship', raw('a', same, '/internships/a')),
    ]);
    expect(evs.map((e) => e.id)).toEqual(['exam:z', 'internship:a']);
  });

  it('TC-285-02: filters by source and date; CalendarService persists across reload', () => {
    const store = new InMemoryKvStore();
    const svc = new CalendarService('stu-1', store);
    const { events } = aggregate(sampleSourceResults());
    // CAM deadline is 2026-07-20T18:30Z = 2026-07-21 00:00 IST, so the IST day is the 21st.
    svc.setFilters({ sources: ['internship'], from: '2026-07-21', to: '2026-07-21', timezone: 'Asia/Kolkata' });
    // Simulate a fresh page load: brand-new service over the same store.
    const reloaded = new CalendarService('stu-1', store);
    const f = reloaded.getFilters();
    expect(f.sources).toEqual(['internship']);
    const out = filterEvents(events, f);
    expect(out.every((e) => e.sourceType === 'internship')).toBe(true);
    expect(out.every((e) => localDateKey(e.startsAt, f.timezone) === '2026-07-21')).toBe(true);
    expect(out.length).toBe(1); // only the CAM deadline lands on 2026-07-21 IST
    expect(out[0].id).toBe('internship:cam-deadline');
  });

  it('TC-285-02: filters are user-scoped (no cross-user bleed)', () => {
    const store = new InMemoryKvStore();
    new CalendarService('stu-1', store).setFilters({ ...defaultFilters(), sources: ['exam'] });
    expect(new CalendarService('stu-2', store).getFilters().sources).toEqual([]);
  });

  it('TC-285-03: dedupes repeated source records but keeps distinct events', () => {
    const dup = raw('a', '2026-07-19T04:30:00Z', '/exam/a');
    const res = aggregate([runAdapter('exam', () => [dup, dup, raw('b', '2026-07-20T04:30:00Z', '/exam/b')])]);
    expect(res.events.map((e) => e.id)).toEqual(['exam:a', 'exam:b']);
  });

  it('TC-285-04: timezone boundary — same instant is a different local day across zones', () => {
    const instant = '2026-07-20T18:30:00Z'; // 20th 18:30 UTC = 21st 00:00 IST
    expect(localDateKey(instant, 'Asia/Kolkata')).toBe('2026-07-21');
    expect(localDateKey(instant, 'UTC')).toBe('2026-07-20');
    expect(localTime(instant, 'Asia/Kolkata')).toBe('12:00 AM');
  });

  it('TC-285-05: partial-source failure isolates the bad source; healthy ones survive', () => {
    const results = [
      runAdapter('exam', () => SAMPLE_EXAM_EVENTS),
      runAdapter('internship', () => { throw new Error('source down'); }),
      runAdapter('clinical', () => SAMPLE_CLINICAL_EVENTS),
    ];
    const agg = aggregate(results);
    expect(agg.failedSources).toEqual(['internship']);
    expect(agg.okSources).toEqual(['exam', 'clinical']);
    expect(agg.events.length).toBe(SAMPLE_EXAM_EVENTS.length + SAMPLE_CLINICAL_EVENTS.length);
  });

  it('TC-285-05: empty sources aggregate to an empty, non-throwing result', () => {
    const agg = aggregate([runAdapter('exam', () => [])]);
    expect(agg.events).toEqual([]);
    expect(agg.okSources).toEqual(['exam']);
  });

  it('TC-285-06: ownership-aware deep link — owner ok, missing→not_found, cross-user→forbidden, public→ok', () => {
    const { events } = aggregate(sampleSourceResults('stu-1'));
    const ok = resolveDeepLink(events, 'internship:cam-deadline', 'stu-1');
    expect(ok.ok).toBe(true);
    if (ok.ok) expect(ok.event.title).toBe('CAM application deadline');
    const miss = resolveDeepLink(events, 'internship:does-not-exist', 'stu-1');
    expect(miss.ok).toBe(false);
    if (!miss.ok) expect(miss.reason).toBe('not_found');
    // TRUE cross-user: stu-2 knows the id but does not own this personal event
    const cross = resolveDeepLink(events, 'internship:cam-deadline', 'stu-2');
    expect(cross.ok).toBe(false);
    if (!cross.ok) expect(cross.reason).toBe('forbidden');
    // public event resolves for any requester
    const pub = resolveDeepLink(events, 'community:ama-constitution', 'stu-2');
    expect(pub.ok).toBe(true);
  });

  it('TC-285-06: wrong source namespace is not found (kept as a separate check)', () => {
    const { events } = aggregate(sampleSourceResults('stu-1'));
    const r = resolveDeepLink(events, 'exam:cam-deadline', 'stu-1');
    expect(r.ok).toBe(false);
    if (!r.ok) expect(r.reason).toBe('not_found');
  });

  it('TC-285-07: previews carry no restricted keys and no external/private URLs', () => {
    const { events } = aggregate(sampleSourceResults());
    for (const e of events) {
      const p = toPreview(e);
      expect(previewLeaksRestricted(p)).toBe(false);
      expect(Object.keys(p)).not.toContain('sourceUrl');
      expect(Object.keys(p)).not.toContain('privacyClassification');
      expect(e.sourceUrl.startsWith('/')).toBe(true);
      expect(/^https?:/i.test(e.sourceUrl)).toBe(false);
    }
  });

  it('TC-285-07: clinical event title excludes verifier/evidence identifiers', () => {
    const [ev] = SAMPLE_CLINICAL_EVENTS.map((r) => normalizeEvent('clinical', r));
    expect(ev.title).not.toMatch(/@|evidence|verifier/i);
  });

  it('rejects external/non-app source_url with a typed error', () => {
    expect(() => normalizeEvent('exam', { sourceId: 'x', title: 't', startsAt: '2026-07-19T04:30:00Z', sourceUrl: 'https://evil.example/x' }))
      .toThrowError(CalendarError);
  });

  it('rejects invalid datetime with a typed error', () => {
    expect(() => normalizeEvent('exam', { sourceId: 'x', title: 't', startsAt: 'not-a-date', sourceUrl: '/x' }))
      .toThrowError(CalendarError);
  });

  it('normalizes end<start default and derives stable id', () => {
    const e = normalizeEvent('internship', SAMPLE_INTERNSHIP_EVENTS[0] as RawSourceRecord);
    expect(e.id).toBe('internship:cam-deadline');
    expect(e.endsAt).toBe(e.startsAt); // no endsAt provided → equals start
    expect(e.timezone).toBe('Asia/Kolkata');
  });

  // --- remediation: strict validation (independent QA defect) ---------------
  it('remediation: invalid endsAt is rejected, NOT silently replaced', () => {
    let code = '';
    try { normalizeEvent('exam', { sourceId: 'x', title: 't', startsAt: '2026-07-19T04:30:00Z', endsAt: 'not-a-date', sourceUrl: '/x' }); }
    catch (e) { code = (e as CalendarError).code; }
    expect(code).toBe('invalid_datetime');
  });

  it('remediation: end-before-start is rejected', () => {
    let code = '';
    try { normalizeEvent('exam', { sourceId: 'x', title: 't', startsAt: '2026-07-19T06:30:00Z', endsAt: '2026-07-19T04:30:00Z', sourceUrl: '/x' }); }
    catch (e) { code = (e as CalendarError).code; }
    expect(code).toBe('end_before_start');
  });

  it('remediation: invalid IANA timezone is rejected', () => {
    let code = '';
    try { normalizeEvent('exam', { sourceId: 'x', title: 't', startsAt: '2026-07-19T04:30:00Z', timezone: 'Mars/Phobos', sourceUrl: '/x' }); }
    catch (e) { code = (e as CalendarError).code; }
    expect(code).toBe('invalid_timezone');
  });

  it('remediation: invalid updatedAt is rejected (no silent fallback)', () => {
    expect(() => normalizeEvent('exam', { sourceId: 'x', title: 't', startsAt: '2026-07-19T04:30:00Z', updatedAt: 'nope', sourceUrl: '/x' }))
      .toThrowError(CalendarError);
  });

  it('remediation TC-285-07: identifier-bearing title is redacted before any preview', () => {
    const e = normalizeEvent('clinical', { sourceId: 'x', title: 'Call verifier ravi@example.com re ev-99177 +91 98765 43210', startsAt: '2026-07-19T04:30:00Z', sourceUrl: '/clinical/log' }, 'stu-1');
    expect(e.title).not.toMatch(/@|ravi@example|ev-99177/);
    expect(e.title).toContain('[redacted]');
    expect(/@/.test(toPreview(e).title)).toBe(false);
    // legitimate non-sensitive titles are preserved verbatim
    expect(normalizeEvent('exam', { sourceId: 'm', title: 'CLAT mock test 3', startsAt: '2026-07-19T04:30:00Z', sourceUrl: '/exam/mock' }).title).toBe('CLAT mock test 3');
  });

  // --- remediation TC-285-05: explicit state + retry-only-failed ------------
  it('remediation TC-285-05: loading→partial→success by retrying only failed sources', () => {
    let down = true;
    const loaders: SourceLoader[] = [
      { sourceType: 'exam', load: () => SAMPLE_EXAM_EVENTS },
      { sourceType: 'internship', load: () => { if (down) throw new Error('source down'); return SAMPLE_INTERNSHIP_EVENTS; } },
    ];
    expect(deriveStatus([], { loading: true })).toBe('loading');
    const first = runLoaders(loaders);
    expect(deriveStatus(first)).toBe('partial');
    const firstAgg = aggregate(first);
    expect(firstAgg.failedSources).toEqual(['internship']);
    expect(firstAgg.events.length).toBe(SAMPLE_EXAM_EVENTS.length); // healthy survived
    down = false;
    const retried = retryFailed(first, loaders);
    expect(deriveStatus(retried)).toBe('success');
    const retriedAgg = aggregate(retried);
    expect(retriedAgg.failedSources).toEqual([]);
    expect(retriedAgg.events.length).toBe(SAMPLE_EXAM_EVENTS.length + SAMPLE_INTERNSHIP_EVENTS.length);
  });

  it('remediation TC-285-05: retry preserves the healthy source result object (not re-run)', () => {
    const loaders: SourceLoader[] = [
      { sourceType: 'exam', load: () => SAMPLE_EXAM_EVENTS },
      { sourceType: 'internship', load: () => { throw new Error('down'); } },
    ];
    const first = runLoaders(loaders);
    const examBefore = first.find((r) => r.sourceType === 'exam');
    const retried = retryFailed(first, loaders);
    expect(retried.find((r) => r.sourceType === 'exam')).toBe(examBefore); // same object
    expect(deriveStatus(retried)).toBe('partial'); // internship still failing
  });

  it('remediation TC-285-05: all sources failing derives error state', () => {
    const loaders: SourceLoader[] = [{ sourceType: 'exam', load: () => { throw new Error('x'); } }];
    expect(deriveStatus(runLoaders(loaders))).toBe('error');
  });

  // --- SAATHI-286 remediation ------------------------------------------------
  it('SOURCE_ROUTE maps every source type to a canonical /s-NN route and normalizes', () => {
    for (const s of ['internship', 'exam', 'clinical', 'community', 'tutoring', 'moot', 'reminder'] as const) {
      expect(/^\/s-\d{2}$/.test(SOURCE_ROUTE[s])).toBe(true);
      // a fixture using the route normalizes without throwing (in-app URL accepted)
      const e = normalizeEvent(s, { sourceId: 'x', title: 't', startsAt: '2026-07-19T04:30:00Z', sourceUrl: SOURCE_ROUTE[s] });
      expect(e.sourceUrl).toBe(SOURCE_ROUTE[s]);
    }
  });

  // --- SAATHI-287 remediation (re REQA aac57de: TC-285-06 semantic route) -----
  it('SOURCE_ROUTE points each source at its canonical semantic screen — not just any /s-NN', () => {
    // Deep links must resolve to the correct owning workflow, not merely a registered route.
    expect(SOURCE_ROUTE.tutoring).toBe('/s-31'); // S6 tutor workflow S-31..S-34 (was /s-22)
    expect(SOURCE_ROUTE.internship).toBe('/s-20');
    expect(SOURCE_ROUTE.exam).toBe('/s-55');
    expect(SOURCE_ROUTE.clinical).toBe('/s-61');
    expect(SOURCE_ROUTE.community).toBe('/s-50');
    // No source may still point at retired indicative routes.
    expect(Object.values(SOURCE_ROUTE)).not.toContain('/s-22');
    expect(Object.values(SOURCE_ROUTE)).not.toContain('/s-94');
  });

  it('validateDateRange: open ranges ok; from>to → from_after_to; malformed → invalid_date', () => {
    expect(validateDateRange(null, null)).toBeNull();
    expect(validateDateRange('2026-07-20', null)).toBeNull();
    expect(validateDateRange('2026-07-21', '2026-07-20')).toBe('from_after_to');
    expect(validateDateRange('20-07-2026', null)).toBe('invalid_date');
  });

  it('zonedToUtcIso: wall time in a tz round-trips to the same local day/time', () => {
    const iso = zonedToUtcIso('2026-07-20', '09:30', 'Asia/Kolkata');
    expect(localDateKey(iso, 'Asia/Kolkata')).toBe('2026-07-20');
    expect(localTime(iso, 'Asia/Kolkata')).toBe('09:30 AM');
    // and lands on the previous UTC day (IST = UTC+5:30)
    expect(localDateKey(iso, 'UTC')).toBe('2026-07-20');
    expect(localTime(iso, 'UTC')).toBe('04:00 AM');
  });

  it('validatePersonalEvent: typed errors for each invalid field', () => {
    const base: PersonalEventInput = { title: 'Study', date: '2026-07-20', time: '09:30', type: 'study', timezone: 'Asia/Kolkata' };
    const code = (i: PersonalEventInput) => { try { validatePersonalEvent(i); return 'ok'; } catch (e) { return (e as PersonalEventError).code; } };
    expect(code(base)).toBe('ok');
    expect(code({ ...base, title: '  ' })).toBe('title_required');
    expect(code({ ...base, date: '2026/07/20' })).toBe('invalid_date');
    expect(code({ ...base, time: '9am' })).toBe('invalid_time');
    expect(code({ ...base, timezone: 'Mars/Phobos' })).toBe('invalid_timezone');
  });

  it('addPersonalEvent: persists through the service, appears via calendarLoaders, survives reload', () => {
    const store = new InMemoryKvStore();
    const svc = new CalendarService('stu-1', store);
    svc.addPersonalEvent({ title: 'Revise contracts', date: '2026-07-20', time: '09:30', type: 'study', timezone: 'Asia/Kolkata' }, '2026-07-12T00:00:00Z');
    // aggregate via the full loader set for a FRESH service over the same store (reload)
    const reloaded = new CalendarService('stu-1', store);
    const { events } = aggregate(runLoaders(calendarLoaders(reloaded, 'stu-1')));
    const mine = events.filter((e) => e.sourceType === 'reminder' && e.title === 'Revise contracts');
    expect(mine.length).toBe(1);
    expect(mine[0].ownerId).toBe('stu-1');
    expect(localTime(mine[0].startsAt, 'Asia/Kolkata')).toBe('09:30 AM');
  });

  it('addPersonalEvent: invalid input throws and persists nothing', () => {
    const store = new InMemoryKvStore();
    const svc = new CalendarService('stu-1', store);
    expect(() => svc.addPersonalEvent({ title: '', date: '2026-07-20', time: '09:30', type: 'study', timezone: 'Asia/Kolkata' }, 't0')).toThrowError(PersonalEventError);
    expect(svc.listPersonalRaw().length).toBe(0);
  });

  it('personal events are user-scoped (not visible to another student)', () => {
    const store = new InMemoryKvStore();
    new CalendarService('stu-1', store).addPersonalEvent({ title: 'Mine', date: '2026-07-20', time: '09:30', type: 'study', timezone: 'UTC' }, '2026-07-12T00:00:00Z');
    expect(new CalendarService('stu-2', store).listPersonalRaw().length).toBe(0);
  });

  it('resolveEventBadge: evaluates past deadlines as Deadline passed (risk) and future as Deadline (warn)', () => {
    const now = new Date('2026-07-29T12:00:00Z');
    const pastEvent = normalizeEvent('internship', { sourceId: 'p1', title: 'Past Deadline', startsAt: '2026-07-20T18:30:00Z', status: 'deadline', sourceUrl: '/s-20' });
    const futureEvent = normalizeEvent('internship', { sourceId: 'f1', title: 'Future Deadline', startsAt: '2026-08-05T18:30:00Z', status: 'deadline', sourceUrl: '/s-20' });

    expect(resolveEventBadge(pastEvent, now)).toEqual({ label: 'Deadline passed', status: 'risk' });
    expect(resolveEventBadge(futureEvent, now)).toEqual({ label: 'Deadline', status: 'warn' });
  });

  it('persists and restores calendar view mode preference (month, week, day)', () => {
    expect(getSavedViewMode()).toBe('month');
    saveViewMode('day');
    expect(getSavedViewMode()).toBe('day');
    saveViewMode('week');
    expect(getSavedViewMode()).toBe('week');
    saveViewMode('month');
    expect(getSavedViewMode()).toBe('month');
  });
});
