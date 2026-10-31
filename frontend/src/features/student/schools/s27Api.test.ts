import { afterEach, describe, expect, it, vi } from 'vitest';
import { readSchoolSearch, schoolSearchQuery } from './s27Api';

afterEach(() => vi.unstubAllGlobals());
const school = { id: 'synthetic-law-school', slug: 'synthetic-law-school', name: 'Synthetic Law School', state: 'Delhi', institution_type: 'government', accreditation: 'BCI approved', entrance_exam: 'CLAT', fees_min: 150000, fees_max: 300000, nirf_rank: null };
const page = { items: [school], total: 1, page: 1, page_size: 20, compare_max: 4 };
const response = (body: unknown, status = 200) => new Response(JSON.stringify(body), { status });
describe('S-27 server search authority', () => {
  it('sends only supported parameters, including zero fees, without altering invalid values before server validation', () => {
    const query = schoolSearchQuery(new URLSearchParams('q=Delhi&state=Delhi&institution_type=unsupported&degree=LLM&accreditation=BCI+approved&entrance_exam=CLAT&fees_max=0&sort=unsupported&page=2&page_size=4&region=North&saved=true'));
    expect(Object.fromEntries(query)).toEqual({ q: 'Delhi', state: 'Delhi', institution_type: 'unsupported', degree: 'LLM', accreditation: 'BCI approved', entrance_exam: 'CLAT', fees_max: '0', sort: 'unsupported', page: '2', page_size: '4' });
  });
  it('keeps the existing default server page size and sort', () => {
    expect(Object.fromEntries(schoolSearchQuery(new URLSearchParams()))).toEqual({ sort: 'name', page: '1', page_size: '20' });
  });
  it('reads summaries only, preserving whole-INR fees, null rank and the server comparison limit', async () => {
    const fetch = vi.fn().mockResolvedValue(response(page)); vi.stubGlobal('fetch', fetch);
    const controller = new AbortController();
    const result = await readSchoolSearch(new URLSearchParams(), controller.signal);
    expect(result).toMatchObject({ total: 1, page: 1, pageSize: 20, compareMax: 4, items: [{ feesMin: 150000, feesMax: 300000, nirfRank: null }] });
    expect(fetch).toHaveBeenCalledTimes(1);
    expect(new URL(fetch.mock.calls[0][0]).pathname).toBe('/api/v1/law-schools');
    expect(fetch.mock.calls[0][1]).toMatchObject({ method: 'GET', signal: controller.signal });
  });
  it.each([{}, { ...page, items: [school, school] }, { ...page, items: [], total: 1 }, { ...page, total: '1' }, { ...page, compare_max: 1 }, { ...page, page: 2 }, { ...page, page_size: 50 }, { ...page, items: [{ ...school, fees_min: -1 }] }, { ...page, items: [{ ...school, fees_max: 1 }] }, { ...page, items: [{ ...school, nirf_rank: 'unknown' }] }, { ...page, items: [{ ...school, name: '' }] }])('rejects malformed or contradictory success instead of claiming no results: %j', async body => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(response(body)));
    await expect(readSchoolSearch(new URLSearchParams())).rejects.toMatchObject({ code: 'invalid_response' });
  });
  it.each([
    { accreditation: null }, { entrance_exam: null }, { fees_min: null }, { fees_max: null },
    { accreditation: null, entrance_exam: null, fees_min: null, fees_max: null, nirf_rank: null },
    { fees_min: 0, fees_max: 0 }, { fees_min: null, fees_max: 0 }, { fees_min: 0, fees_max: null },
  ])('QA-S27-01 accepts schema-nullable fields without dropping other schools or inventing zero: %j', async fields => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(response({ ...page, total: 2, items: [school, { ...school, id: 'unknown-school', ...fields }] })));
    const result = await readSchoolSearch(new URLSearchParams());
    expect(result.items).toHaveLength(2);
    const wire = { ...school, ...fields };
    expect(result.items[1]).toMatchObject({ accreditation: wire.accreditation, entranceExam: wire.entrance_exam, feesMin: wire.fees_min, feesMax: wire.fees_max, nirfRank: wire.nirf_rank });
  });
  it.each([{ fees_min: undefined }, { fees_max: undefined }, { accreditation: undefined }, { entrance_exam: undefined }, { fees_min: '0' }, { fees_max: -1 }, { accreditation: 42 }, { entrance_exam: [] }])('QA-S27-01 still rejects missing or malformed fields: %j', async fields => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(response({ ...page, items: [{ ...school, ...fields }] })));
    await expect(readSchoolSearch(new URLSearchParams())).rejects.toMatchObject({ code: 'invalid_response' });
  });
  it('allows a real empty page beyond the last page without inventing a global zero count', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(response({ ...page, items: [], total: 1, page: 2 })));
    await expect(readSchoolSearch(new URLSearchParams('page=2'))).resolves.toMatchObject({ total: 1, page: 2, items: [] });
  });
  it.each([422, 429, 500, 503])('retains genuine HTTP %s and backend code', async status => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(response({ detail: { code: 'unsupported_sort' } }, status)));
    await expect(readSchoolSearch(new URLSearchParams())).rejects.toMatchObject({ status, code: 'unsupported_sort' });
  });
  it('retains network failure without fabricating HTTP 500', async () => {
    vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new TypeError('Network unavailable')));
    await expect(readSchoolSearch(new URLSearchParams())).rejects.toThrow(TypeError);
  });
});
