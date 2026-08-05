import { afterEach, describe, expect, it, vi } from 'vitest';
import {
  InternshipsApiError,
  getInternship,
  listInternships,
  listSavedInternships,
  saveInternship,
  unsaveInternship,
} from './internshipsApi';

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

function response(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } });
}

const LISTING = {
  id: 'menon',
  role: 'Judicial research assistant',
  organisation: 'Chambers of Sr. Adv. R. Menon',
  location: 'Delhi HC',
  stipend_monthly_paise: 1_500_000,
  verification_status: 'unverified',
  application_deadline: '2027-07-08',
  eligibility: '2nd year+ · rolling',
  tags: ['Research', 'Delhi'],
  description: 'Judicial research support.',
  source: { name: 'Sample fixture', url: null, retrieved_at: null, verified_at: null },
} as const;

describe('internship catalogue and saved-list API', () => {
  it('maps integer-paise and structured provenance without an actor header', async () => {
    const fetchMock = vi.fn().mockResolvedValue(response({ items: [LISTING], total: 1, page: 1, page_size: 20 }));
    vi.stubGlobal('fetch', fetchMock);

    const result = await listInternships();

    expect(result).toEqual({
      items: [expect.objectContaining({
        id: 'menon', org: LISTING.organisation, stipendMonthlyPaise: 1_500_000,
        verificationStatus: 'unverified', deadline: '8 Jul', source: expect.objectContaining({ name: 'Sample fixture' }),
      })],
      total: 1,
      page: 1,
      pageSize: 20,
    });
    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(new URL(url).pathname).toBe('/api/v1/internships');
    expect(init.credentials).toBe('include');
    expect(new Headers(init.headers).has('X-Actor-Claims')).toBe(false);
  });

  it('encodes the exact selected slug and does not fall back to another listing', async () => {
    const fetchMock = vi.fn().mockResolvedValue(response(LISTING));
    vi.stubGlobal('fetch', fetchMock);

    await expect(getInternship('menon/appeal')).resolves.toEqual(expect.objectContaining({ id: 'menon' }));

    expect(new URL(String(fetchMock.mock.calls[0][0])).pathname).toBe('/api/v1/internships/menon%2Fappeal');
  });

  it('uses account-scoped saved endpoints and exact mutation methods', async () => {
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(response({ items: [LISTING] }))
      .mockResolvedValueOnce(response({ saved: true, listing_id: 'menon' }))
      .mockResolvedValueOnce(response({ saved: false, listing_id: 'menon' }));
    vi.stubGlobal('fetch', fetchMock);

    await expect(listSavedInternships()).resolves.toEqual([expect.objectContaining({ id: 'menon' })]);
    await expect(saveInternship('menon')).resolves.toEqual({ saved: true, listingId: 'menon' });
    await expect(unsaveInternship('menon')).resolves.toEqual({ saved: false, listingId: 'menon' });

    expect(new URL(String(fetchMock.mock.calls[0][0])).pathname).toBe('/api/v1/student/internships/saved');
    expect((fetchMock.mock.calls[1][1] as RequestInit).method).toBe('PUT');
    expect((fetchMock.mock.calls[2][1] as RequestInit).method).toBe('DELETE');
    expect(new URL(String(fetchMock.mock.calls[1][0])).pathname).toBe('/api/v1/student/internships/menon/saved');
  });

  it('retains typed non-enumerating auth/not-found failures', async () => {
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(response({ detail: { code: 'authentication_required' } }, 401))
      .mockResolvedValueOnce(response({ detail: { code: 'internship_not_found' } }, 404));
    vi.stubGlobal('fetch', fetchMock);

    await expect(listSavedInternships()).rejects.toEqual(expect.objectContaining<Partial<InternshipsApiError>>({ status: 401, code: 'authentication_required' }));
    await expect(getInternship('unknown')).rejects.toEqual(expect.objectContaining<Partial<InternshipsApiError>>({ status: 404, code: 'internship_not_found' }));
  });
});
