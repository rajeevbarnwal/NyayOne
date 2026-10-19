import { readFileSync } from 'node:fs';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { browseInternships, readBrowseSaved } from '../../src/features/student/internships/s20Api';

const source = readFileSync(new URL('../v34-s11-s26-e2e.mjs', import.meta.url), 'utf8');
const origin = 'http://localhost:1131';
const search = '?page=1&page_size=20&verified_only=false';
const matcherSource = source.slice(source.indexOf('function isExactApiResponse('), source.indexOf('\nasync function finishResponse('));
const matches = new Function('canonicalApiOrigin', `${matcherSource}; return isExactApiResponse;`)(origin);
const response = (suffix, method = 'GET', host = origin) => ({ url: () => `${host}/api/v1/internships${suffix}`, request: () => ({ method: () => method }) });
const fixtureSource = source.slice(source.indexOf('const internshipListings = '), source.indexOf('\nasync function installApiContract('));
const listings = new Function(`${fixtureSource}; return internshipListings;`)();
afterEach(() => vi.unstubAllGlobals());

describe('S-20 foundation producer contract', () => {
  it('recognizes the exact supported S-20 catalogue query instead of timing out', () => {
    expect(matches(response(search), 'GET', '/api/v1/internships', search)).toBe(true);
  });
  it.each(['', '?page=2&page_size=20&verified_only=false', '?page=1&page_size=20&verified_only=true', '?page=1&page_size=10&verified_only=false', `${search}&q=Delhi`, `${search}&page=1`, `${search}#unexpected`])('rejects an absent, changed or extra catalogue query: %s', query => {
    expect(matches(response(query), 'GET', '/api/v1/internships', search)).toBe(false);
  });
  it('keeps exact origin/method/path checks and query-free defaults for other callers', () => {
    expect(matches(response(search, 'POST'), 'GET', '/api/v1/internships', search)).toBe(false);
    expect(matches(response(search, 'GET', 'https://other.example'), 'GET', '/api/v1/internships', search)).toBe(false);
    expect(matches(response(`/cam${search}`), 'GET', '/api/v1/internships', search)).toBe(false);
    expect(matches(response(''), 'GET', '/api/v1/internships')).toBe(true);
    expect(matches(response(search), 'GET', '/api/v1/internships')).toBe(false);
  });
  it('arms both S-20 catalogue listeners with the exact query without changing other listeners', () => {
    expect(source.match(/isExactApiResponse\(response, 'GET', '\/api\/v1\/internships', '\?page=1&page_size=20&verified_only=false'\)/g)).toHaveLength(2);
    expect(source).toContain('completed.length === internshipResponses.length');
    expect(source).toContain('completedBrowseResponses.length === 2');
    expect(source).toContain('item.status === 200 && item.finishedError === null');
  });
  it('supplies schema-complete catalogue and saved-list fixtures accepted by the strict S-20 adapter', async () => {
    const fetch = vi.fn()
      .mockResolvedValueOnce(new Response(JSON.stringify({ items: listings, total: listings.length, page: 1, page_size: 20 })))
      .mockResolvedValueOnce(new Response(JSON.stringify({ items: [listings[0]] })));
    vi.stubGlobal('fetch', fetch);
    const page = await browseInternships({ page: 1, verifiedOnly: false });
    expect(page.items.map(item => item.id)).toEqual(['cam', 'menon', 'vidhi']);
    expect(page.items.every(item => typeof item.organisationId === 'string' && item.organisationId.length > 0)).toBe(true);
    expect((await readBrowseSaved()).map(item => item.id)).toEqual(['cam']);
  });
});
