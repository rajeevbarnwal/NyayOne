import { afterEach, describe, expect, it, vi } from 'vitest';
import { readSchoolDetail, writeSchoolSaved, writeSchoolFollow, safeSource, schoolReturn } from './s28Api';
const school = { id: 'school-1', slug: 'school-1', name: 'Synthetic law school', state: 'Delhi', institution_type: 'government', accreditation: null, entrance_exam: null, fees_min: null, fees_max: null, nirf_rank: null, programmes: [{ degree: 'LLB', duration_years: 3 }], facts: [{ key: 'hostel', value: 'Available', source_name: null, source_url: null, retrieved_at: null }], saved: false, followed: true };
const reply = (body: unknown, status = 200) => new Response(JSON.stringify(body), { status });
afterEach(() => vi.unstubAllGlobals());
describe('S-28 detail authority', () => {
  it('preserves nullable facts and does not fabricate notification consent absent from detail', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(reply(school)));
    const result = await readSchoolDetail('school-1');
    expect(result).toMatchObject({ feesMin: null, accreditation: null, followed: true, notifyOptIn: null, facts: [{ sourceName: null, retrievedAt: null }] });
  });
  it.each([{}, { ...school, id: 'other' }, { ...school, saved: 'false' }, { ...school, followed: undefined }, { ...school, facts: null }, { ...school, programmes: [{ degree: 'LLB', duration_years: -1 }] }, { ...school, facts: [{ ...school.facts[0], source_name: 42 }] }, { ...school, fees_min: 3, fees_max: 1 }])('rejects incomplete/contradictory success: %j', async body => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(reply(body)));
    await expect(readSchoolDetail('school-1')).rejects.toMatchObject({ code: 'invalid_response' });
  });
  it('uses exact GET path and cancellation signal', async () => {
    const fetch = vi.fn().mockResolvedValue(reply({ ...school, id: 'school/a' })); vi.stubGlobal('fetch', fetch);
    const signal = new AbortController().signal; await readSchoolDetail('school/a', signal);
    expect(new URL(fetch.mock.calls[0][0]).pathname).toBe('/api/v1/law-schools/school%2Fa');
    expect(fetch.mock.calls[0][1]).toMatchObject({ method: 'GET', signal });
  });
  it.each([true, false])('requires server-confirmed saved=%s', async saved => {
    const fetch = vi.fn().mockResolvedValue(reply({ saved })); vi.stubGlobal('fetch', fetch);
    await expect(writeSchoolSaved('school-1', saved)).resolves.toEqual({ saved });
    expect(fetch.mock.calls[0][1].method).toBe(saved ? 'PUT' : 'DELETE');
    fetch.mockResolvedValue(reply({ saved: !saved })); await expect(writeSchoolSaved('school-1', saved)).rejects.toMatchObject({ code: 'invalid_response' });
  });
  it('following and notification consent are independent and explicit', async () => {
    const fetch = vi.fn().mockResolvedValue(reply({ followed: true, notify_opt_in: false })); vi.stubGlobal('fetch', fetch);
    await expect(writeSchoolFollow('school-1', true, false)).resolves.toEqual({ followed: true, notifyOptIn: false });
    expect(JSON.parse(fetch.mock.calls[0][1].body)).toEqual({ notify_opt_in: false });
    fetch.mockResolvedValue(reply({ followed: true, notify_opt_in: true })); await writeSchoolFollow('school-1', true, true);
    expect(JSON.parse(fetch.mock.calls[1][1].body)).toEqual({ notify_opt_in: true });
    fetch.mockResolvedValue(reply({ followed: false, notify_opt_in: false })); await writeSchoolFollow('school-1', false, false);
    expect(fetch.mock.calls[2][1].method).toBe('DELETE');
  });
  it.each([{}, { followed: true }, { followed: true, notify_opt_in: 'false' }, { followed: true, notify_opt_in: true }])('does not accept a misleading follow acknowledgment: %j', async body => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(reply(body)));
    await expect(writeSchoolFollow('school-1', true, false)).rejects.toMatchObject({ code: 'invalid_response' });
  });
  it.each([401, 403, 404, 422, 429, 503])('preserves real HTTP %s without turning it into a network error', async status => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(reply({ detail: { code: 'school_not_found' } }, status)));
    await expect(readSchoolDetail('school-1')).rejects.toMatchObject({ status, code: 'school_not_found' });
  });
  it.each(['javascript:alert(1)', 'data:text/html,x', '//evil.example', 'https://user:pass@example.test', 'not a url'])('does not activate unsafe source: %s', source => expect(safeSource(source)).toBeNull());
  it('preserves real HTTPS source and exposes host', () => expect(safeSource('https://example.test/facts')).toEqual({ url: 'https://example.test/facts', host: 'example.test' }));
  it('allows only the three local return destinations, never arbitrary navigation', () => {
    expect(schoolReturn(new URLSearchParams('ret=state%3DDelhi%26page%3D2'))).toEqual({ label: 'Find a law school', path: '/s-27?state=Delhi&page=2' });
    expect(schoolReturn(new URLSearchParams('from=s29&ids=a,b'))).toEqual({ label: 'Comparison', path: '/s-29?ids=a%2Cb' });
    expect(schoolReturn(new URLSearchParams('from=s30'))).toEqual({ label: 'Saved and followed', path: '/s-30' });
    expect(schoolReturn(new URLSearchParams('from=https://evil.test&ret=https://evil.test'))).toEqual({ label: 'Find a law school', path: '/s-27' });
  });
});
