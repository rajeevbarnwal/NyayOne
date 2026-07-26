import { afterEach, describe, expect, it, vi } from 'vitest';
import {
  searchLawSchools,
  getLawSchoolDetail,
  compareLawSchools,
  saveLawSchool,
  unsaveLawSchool,
  followLawSchool,
  unfollowLawSchool,
  buildSearchQuery,
  LawSchoolsApiError,
  COMPARE_LIMIT_EXCEEDED,
  COMPARE_MIN_NOT_MET,
  DUPLICATE_SCHOOL,
  SCHOOL_NOT_FOUND,
} from './lawSchoolsApi';

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

const SUMMARY_WIRE = {
  id: 'b7f9d0e2-0000-4000-8000-000000000001',
  name: 'National Law School of India University',
  slug: 'nlsiu-bengaluru',
  state: 'Karnataka',
  institution_type: 'NLU',
  accreditation: 'NAAC A++',
  entrance_exam: 'CLAT',
  fees_min: 250000,
  fees_max: 320000,
  nirf_rank: 1,
};

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  });
}

describe('law-school search API (SAATHI-63 / S-27)', () => {
  it('builds the documented snake_case query string', () => {
    const qs = buildSearchQuery({
      q: 'law',
      state: 'Karnataka',
      institutionType: 'NLU',
      degree: 'LLB',
      accreditation: 'NAAC A++',
      entranceExam: 'CLAT',
      feesMax: 300000,
      sort: 'nirf_rank',
      page: 2,
      pageSize: 20,
    });
    const parsed = new URLSearchParams(qs);
    expect(parsed.get('q')).toBe('law');
    expect(parsed.get('institution_type')).toBe('NLU');
    expect(parsed.get('entrance_exam')).toBe('CLAT');
    expect(parsed.get('fees_max')).toBe('300000');
    expect(parsed.get('sort')).toBe('nirf_rank');
    expect(parsed.get('page')).toBe('2');
    expect(parsed.get('page_size')).toBe('20');
  });

  it('maps the paged result including the server compare_max', async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse({
      items: [SUMMARY_WIRE],
      total: 1,
      page: 1,
      page_size: 20,
      compare_max: 4,
    }));
    vi.stubGlobal('fetch', fetchMock);

    const result = await searchLawSchools({ q: 'national' });
    expect(result.compareMax).toBe(4);
    expect(result.total).toBe(1);
    expect(result.items[0]).toEqual(expect.objectContaining({
      id: SUMMARY_WIRE.id,
      institutionType: 'NLU',
      entranceExam: 'CLAT',
      feesMin: 250000,
      feesMax: 320000,
      nirfRank: 1,
    }));
    const [url] = fetchMock.mock.calls[0] as [string];
    expect(url).toContain('/api/v1/law-schools?');
    expect(url).toContain('q=national');
  });
});

describe('law-school detail API (S-28)', () => {
  it('maps programmes, sourced facts and saved/followed flags', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(jsonResponse({
      ...SUMMARY_WIRE,
      programmes: [{ degree: 'BA LLB (Hons.)', duration_years: 5 }],
      facts: [{
        key: 'Hostel',
        value: 'On campus',
        source_name: 'NLSIU prospectus 2026',
        source_url: 'https://nls.ac.in/prospectus',
        retrieved_at: '2026-07-01',
      }],
      saved: true,
      followed: false,
    })));

    const detail = await getLawSchoolDetail(SUMMARY_WIRE.id);
    expect(detail.programmes).toEqual([{ degree: 'BA LLB (Hons.)', durationYears: 5 }]);
    expect(detail.facts[0]).toEqual({
      key: 'Hostel',
      value: 'On campus',
      sourceName: 'NLSIU prospectus 2026',
      sourceUrl: 'https://nls.ac.in/prospectus',
      retrievedAt: '2026-07-01',
    });
    expect(detail.saved).toBe(true);
    expect(detail.followed).toBe(false);
  });

  it('surfaces the typed school_not_found error', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(jsonResponse(
      { detail: { code: SCHOOL_NOT_FOUND } },
      404,
    )));
    await expect(getLawSchoolDetail('missing')).rejects.toEqual(
      expect.objectContaining({ status: 404, code: SCHOOL_NOT_FOUND }),
    );
  });
});

describe('law-school compare API (S-29)', () => {
  it('posts school_ids and maps aligned rows', async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse({
      compare_max: 4,
      items: [
        { ...SUMMARY_WIRE, programmes: [{ degree: 'LLB', duration_years: 3 }], facts: [] },
        { ...SUMMARY_WIRE, id: 'second', name: 'NALSAR', programmes: [], facts: [] },
      ],
    }));
    vi.stubGlobal('fetch', fetchMock);

    const result = await compareLawSchools([SUMMARY_WIRE.id, 'second']);
    expect(result.compareMax).toBe(4);
    expect(result.items).toHaveLength(2);
    expect(result.items[0].programmes).toEqual([{ degree: 'LLB', durationYears: 3 }]);
    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toContain('/api/v1/law-schools/compare');
    expect(JSON.parse(String(init.body))).toEqual({ school_ids: [SUMMARY_WIRE.id, 'second'] });
  });

  it('surfaces COMPARE_LIMIT_EXCEEDED with the server max_allowed', async () => {
    vi.stubGlobal('fetch', vi.fn().mockImplementation(() => Promise.resolve(jsonResponse(
      { detail: { code: COMPARE_LIMIT_EXCEEDED, max_allowed: 4 } },
      422,
    ))));
    const attempt = compareLawSchools(['a', 'b', 'c', 'd', 'e']);
    await expect(attempt).rejects.toBeInstanceOf(LawSchoolsApiError);
    await expect(compareLawSchools(['a', 'b', 'c', 'd', 'e'])).rejects.toEqual(
      expect.objectContaining({ status: 422, code: COMPARE_LIMIT_EXCEEDED, maxAllowed: 4 }),
    );
  });

  it('surfaces COMPARE_MIN_NOT_MET with min_required', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(jsonResponse(
      { detail: { code: COMPARE_MIN_NOT_MET, min_required: 2 } },
      422,
    )));
    await expect(compareLawSchools(['a'])).rejects.toEqual(
      expect.objectContaining({ code: COMPARE_MIN_NOT_MET, minRequired: 2 }),
    );
  });

  it('surfaces DUPLICATE_SCHOOL', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(jsonResponse(
      { detail: { code: DUPLICATE_SCHOOL } },
      422,
    )));
    await expect(compareLawSchools(['a', 'a'])).rejects.toEqual(
      expect.objectContaining({ status: 422, code: DUPLICATE_SCHOOL }),
    );
  });
});

describe('save & follow API (S-28/S-30)', () => {
  it('PUT saved is idempotent — repeat calls return the same server truth', async () => {
    const fetchMock = vi.fn().mockImplementation(() => Promise.resolve(jsonResponse({ saved: true })));
    vi.stubGlobal('fetch', fetchMock);

    expect(await saveLawSchool('school-1')).toEqual({ saved: true });
    expect(await saveLawSchool('school-1')).toEqual({ saved: true });
    for (const call of fetchMock.mock.calls as Array<[string, RequestInit]>) {
      expect(call[0]).toContain('/api/v1/student/law-schools/school-1/saved');
      expect(call[1].method).toBe('PUT');
    }
  });

  it('DELETE saved returns saved:false', async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse({ saved: false }));
    vi.stubGlobal('fetch', fetchMock);
    expect(await unsaveLawSchool('school-1')).toEqual({ saved: false });
    const [, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(init.method).toBe('DELETE');
  });

  it('PUT follow sends notify_opt_in and maps the response', async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse({ followed: true, notify_opt_in: true }));
    vi.stubGlobal('fetch', fetchMock);

    expect(await followLawSchool('school-1', true)).toEqual({ followed: true, notifyOptIn: true });
    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toContain('/api/v1/student/law-schools/school-1/follow');
    expect(JSON.parse(String(init.body))).toEqual({ notify_opt_in: true });
  });

  it('DELETE follow returns followed:false', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(jsonResponse({ followed: false, notify_opt_in: false })));
    expect(await unfollowLawSchool('school-1')).toEqual({ followed: false, notifyOptIn: false });
  });
});
