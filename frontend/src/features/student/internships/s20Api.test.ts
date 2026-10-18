import { afterEach, describe, expect, it, vi } from 'vitest';
import { browseInternships, readBrowseSaved, changeBrowseSaved, filterBrowsePage } from './s20Api';

afterEach(() => vi.unstubAllGlobals());
const wire = { id: 'fixture-role', organisation_id: 'org', role: 'Research intern', organisation: 'Synthetic chambers', location: 'Delhi', stipend_monthly_paise: 1200000, verification_status: 'verified', application_deadline: '2027-07-08', eligibility: 'Student', tags: [], description: 'Research', source: { name: 'Synthetic source', url: null, retrieved_at: null, verified_at: null } };
const reply = (body: unknown, status = 200) => new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } });
describe('S-20 contract: only backend-supported catalogue queries', () => {
  it('sends only page/page_size/verified_only and preserves dates, paise and provenance', async () => {
    const fetch = vi.fn().mockResolvedValue(reply({ items: [wire], page: 2, page_size: 20, total: 21 })); vi.stubGlobal('fetch', fetch);
    const result = await browseInternships({ page: 2, verifiedOnly: true });
    const url = new URL(fetch.mock.calls[0][0]);
    expect(url.pathname).toBe('/api/v1/internships');
    expect(Object.fromEntries(url.searchParams)).toEqual({ page: '2', page_size: '20', verified_only: 'true' });
    expect(result.items[0]).toMatchObject({ id: wire.id, deadline: '8 Jul 2027', stipendMonthlyPaise: 1200000, verificationStatus: 'verified' });
    expect((fetch.mock.calls[0][1] as RequestInit).credentials).toBe('include');
  });
  it.each([{}, { items: [], total: 1, page: 1, page_size: 20 }, { items: [wire, wire], total: 2, page: 1, page_size: 20 }, { items: [{ ...wire, stipend_monthly_paise: -1 }], total: 1, page: 1, page_size: 20 }, { items: [{ ...wire, verification_status: 'approved' }], total: 1, page: 1, page_size: 20 }])('fails closed for malformed catalogue data: %j', async body => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(reply(body)));
    await expect(browseInternships({ page: 1, verifiedOnly: false })).rejects.toMatchObject({ code: 'invalid_response' });
  });
  it('retains typed failures, not an empty result', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(reply({ detail: { code: 'unavailable' } }, 503)));
    await expect(browseInternships({ page: 1, verifiedOnly: false })).rejects.toMatchObject({ status: 503, code: 'unavailable' });
  });
  it('allows genuine empty catalogue and saved responses', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValueOnce(reply({ items: [], total: 0, page: 1, page_size: 20 })).mockResolvedValueOnce(reply({ items: [] })));
    expect((await browseInternships({ page: 1, verifiedOnly: false })).items).toEqual([]);
    expect(await readBrowseSaved()).toEqual([]);
  });
  it.each([{ saved: true, listing_id: 'another' }, { saved: false, listing_id: wire.id }, {}, { saved: 'true', listing_id: wire.id }])('does not report save success for invalid confirmation: %j', async body => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(reply(body)));
    await expect(changeBrowseSaved(wire.id, true)).rejects.toMatchObject({ code: 'invalid_response' });
  });
  it('uses PUT/DELETE, exact slug and server-confirmed state', async () => {
    const fetch = vi.fn().mockResolvedValueOnce(reply({ saved: true, listing_id: wire.id })).mockResolvedValueOnce(reply({ saved: false, listing_id: wire.id })); vi.stubGlobal('fetch', fetch);
    await expect(changeBrowseSaved(wire.id, true)).resolves.toBe(true);
    await expect(changeBrowseSaved(wire.id, false)).resolves.toBe(false);
    expect(fetch.mock.calls.map(c => c[1].method)).toEqual(['PUT', 'DELETE']);
    expect(new URL(fetch.mock.calls[0][0]).pathname).toBe('/api/v1/student/internships/fixture-role/saved');
  });
  it('filters only supplied page items, including null/zero stipends, without network calls', async () => {
    const fetch = vi.fn().mockResolvedValue(reply({ items: [wire, { ...wire, id: 'unpaid', stipend_monthly_paise: 0 }, { ...wire, id: 'unknown', stipend_monthly_paise: null }], total: 23, page: 1, page_size: 20 })); vi.stubGlobal('fetch', fetch);
    const { items } = await browseInternships({ page: 1, verifiedOnly: false });
    expect(filterBrowsePage(items, 'Delhi', 'paid').map(i => i.id)).toEqual([wire.id]);
    expect(filterBrowsePage(items, '', 'unpaid').map(i => i.id)).toEqual(['unpaid', 'unknown']);
    expect(filterBrowsePage(items, 'not on page', 'any')).toEqual([]);
    expect(fetch).toHaveBeenCalledTimes(1);
  });
});
