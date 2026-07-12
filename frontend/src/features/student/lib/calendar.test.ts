import { describe, expect, it } from 'vitest';
import { InMemoryKvStore } from '../../../lib/kvStore';
import {
  aggregate, runAdapter, normalizeEvent, sortEvents, filterEvents,
  localDateKey, localTime, toPreview, previewLeaksRestricted, resolveDeepLink,
  eventId, CalendarError, CalendarService, defaultFilters, sampleSourceResults,
  SAMPLE_INTERNSHIP_EVENTS, SAMPLE_EXAM_EVENTS, SAMPLE_CLINICAL_EVENTS,
  type RawSourceRecord,
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
    expect(localTime(instant, 'Asia/Kolkata')).toBe('00:00');
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

  it('TC-285-06: deep link resolves a valid event and returns null for missing/unauthorized', () => {
    const { events } = aggregate(sampleSourceResults());
    expect(resolveDeepLink(events, 'internship:cam-deadline')?.title).toBe('CAM application deadline');
    expect(resolveDeepLink(events, 'internship:does-not-exist')).toBeNull();
    expect(resolveDeepLink(events, 'exam:cam-deadline')).toBeNull(); // wrong source namespace
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
});
