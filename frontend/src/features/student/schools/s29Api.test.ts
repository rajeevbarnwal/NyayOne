import { afterEach, describe, expect, it, vi } from 'vitest';
import { readComparison, comparisonIds, comparisonValue, comparisonDetailPath } from './s29Api';
const school = (id: string) => ({ id, name: `School ${id}`, slug: id, state: 'Delhi', institution_type: 'government', accreditation: null, entrance_exam: null, fees_min: null, fees_max: null, nirf_rank: null, programmes: [], facts: [] });
const valid = () => ({ comparison_id: 'cmp-server-1', compare_max: 4, items: [school('a'), school('b')] });
const reply = (body: unknown, status = 200) => new Response(JSON.stringify(body), { status });
afterEach(() => vi.unstubAllGlobals());
describe('S-29 comparison authority', () => {
  it('POSTs only selected IDs, carries cancellation and preserves server comparison identity/limits', async () => {
    const fetch = vi.fn().mockResolvedValue(reply(valid())); vi.stubGlobal('fetch', fetch);
    const signal = new AbortController().signal;
    const result = await readComparison(['a','b'], signal);
    expect(result).toMatchObject({ comparisonId: 'cmp-server-1', compareMax: 4, items: [{ id: 'a', feesMin: null }, { id: 'b' }] });
    expect(new URL(fetch.mock.calls[0][0]).pathname).toBe('/api/v1/law-schools/compare');
    expect(fetch.mock.calls[0][1]).toMatchObject({ method: 'POST', signal });
    expect(JSON.parse(fetch.mock.calls[0][1].body)).toEqual({ school_ids: ['a','b'] });
  });
  it.each([{}, { ...valid(), comparison_id: null }, { ...valid(), compare_max: 1 }, { ...valid(), items: [school('b'), school('a')] }, { ...valid(), items: [school('a')] }, { ...valid(), items: [school('a'), school('a')] }, { ...valid(), items: [{ ...school('a'), fees_min: -1 },school('b')] }, { ...valid(), items: [{ ...school('a'), fees_min: 5, fees_max: 1 },school('b')] }, { ...valid(), items: [{ ...school('a'), facts: null },school('b')] }])('rejects malformed or contradictory success %j', async body => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(reply(body)));
    await expect(readComparison(['a','b'])).rejects.toMatchObject({ code: 'invalid_response', status: 200 });
  });
  it.each([401,403,404,422,429,503])('preserves genuine HTTP %s and verbatim server error details', async status => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(reply({ detail: { code: 'COMPARE_LIMIT_EXCEEDED', max_allowed: 3, reason: 'server decision' } }, status)));
    await expect(readComparison(['a','b'])).rejects.toMatchObject({ status, code: 'COMPARE_LIMIT_EXCEEDED', extra: { max_allowed: 3, reason: 'server decision' } });
  });
  it('keeps URL selection stable, deduplicates legacy IDs, and never resurrects an explicitly emptied selection', () => {
    expect(comparisonIds(null, [{id:'a',name:'A'},{id:'b',name:'B'}])).toEqual(['a','b']);
    expect(comparisonIds('', [{id:'a',name:'A'}])).toEqual([]);
    expect(comparisonIds('a,b,a,,c', [])).toEqual(['a','b','c']);
  });
  it('shows missing data as Not provided, preserves real zero, and never invents a verification label', async () => {
    const data={...valid(),items:[{...school('a'),fees_min:0,fees_max:0},school('b')]};
    vi.stubGlobal('fetch',vi.fn().mockResolvedValue(reply(data))); const item=(await readComparison(['a','b'])).items[0];
    expect(comparisonValue(item,'fees')).toBe('₹0 per year');
    for(const key of ['nirf_rank','accreditation','entrance_exam','hostel','programmes'])expect(comparisonValue(item,key)).toBe('Not provided');
  });
  it('encodes detail destination with complete comparison return context', () => {
    const url=new URL(comparisonDetailPath('a/b',['a/b','c']),'https://example.test');
    expect(url.pathname).toBe('/s-28'); expect(url.searchParams.get('id')).toBe('a/b');
    expect(url.searchParams.get('from')).toBe('s29');expect(url.searchParams.get('ids')).toBe('a/b,c');
  });
  it('uses the frozen institution labels while retaining unknown server values verbatim', async () => {
    vi.stubGlobal('fetch',vi.fn().mockResolvedValue(reply(valid())));const item=(await readComparison(['a','b'])).items[0];
    for(const [institutionType,label] of Object.entries({national_law_university:'National Law University',government:'Government law college',private:'Private university',deemed:'Deemed university',other_type:'other_type'}))expect(comparisonValue({...item,institutionType},'institution_type')).toBe(label);
  });
});
