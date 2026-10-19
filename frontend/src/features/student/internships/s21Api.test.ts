import { afterEach, describe, expect, it, vi } from 'vitest';
import { readInternshipDetail, safeSourceUrl, validDetailId } from './s21Api';
afterEach(() => vi.unstubAllGlobals());
const wire = { id: 'test-role', organisation_id: 'org', role: 'Research', organisation: 'Synthetic', location: 'Delhi', application_deadline: '2027-07-08', stipend_monthly_paise: null, verification_status: 'unverified', eligibility: 'Students', description: 'Research support', tags: [], source: { name: 'Synthetic source', url: null, retrieved_at: null, verified_at: null } };
describe('S-21 detail contract', () => {
  it('reads only the selected slug with the supplied cancellation signal', async () => {
    const fetch = vi.fn().mockResolvedValue(new Response(JSON.stringify(wire))); vi.stubGlobal('fetch', fetch);
    const abort = new AbortController();
    expect(await readInternshipDetail(wire.id, abort.signal)).toMatchObject({ id: wire.id, role: wire.role, stipendMonthlyPaise: null, deadline: '8 Jul 2027' });
    expect(new URL(fetch.mock.calls[0][0]).pathname).toBe('/api/v1/internships/test-role');
    expect(fetch.mock.calls[0][1].signal).toBeDefined();
  });
  it.each(['', '../role', 'a/b', 'UPPER', 'a'.repeat(65), 'a--b'])('rejects malformed route identity %s before dispatch', async id => {
    const fetch = vi.fn(); vi.stubGlobal('fetch', fetch);
    expect(validDetailId(id)).toBe(false);
    await expect(readInternshipDetail(id)).rejects.toMatchObject({ code: 'invalid_listing' });
    expect(fetch).not.toHaveBeenCalled();
  });
  it.each([{}, { ...wire, id: 'different' }, { ...wire, stipend_monthly_paise: -1 }, { ...wire, application_deadline: '2027-02-30' }, { ...wire, tags: [null] }, { ...wire, verification_status: 'approved' }])('rejects malformed successful response %j', async value => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response(JSON.stringify(value))));
    await expect(readInternshipDetail(wire.id)).rejects.toMatchObject({ code: 'invalid_response' });
  });
  it('keeps typed missing/error states, never sample data', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response(JSON.stringify({ detail: { code: 'internship_listing_not_found' } }), { status: 404 })));
    await expect(readInternshipDetail(wire.id)).rejects.toMatchObject({ status: 404, code: 'internship_listing_not_found' });
  });
  it.each(['javascript:alert(1)', 'data:text/html,test', 'https://user:password@example.test', null, '/relative'])('does not activate unsafe source URL %s', value => expect(safeSourceUrl(value)).toBeNull());
  it('retains an ordinary public source link', () => expect(safeSourceUrl('https://example.test/role')).toBe('https://example.test/role'));
});
