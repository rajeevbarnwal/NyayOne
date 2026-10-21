import { readFileSync } from 'node:fs';
import { describe, expect, it } from 'vitest';
const source = name => readFileSync(new URL(`../${name}`, import.meta.url), 'utf8');
describe('approved S-25 browser expectation alignment', () => {
  it('keeps real HTTP persistence, account identity and removal assertions on compact cards', () => {
    const text = source('saathi60-internship-real-e2e.mjs');
    expect(text.match(/name: 'Judicial research assistant Chambers of Sr\. Adv\. R\. Menon', exact: true/g)).toHaveLength(2);
    expect(text).toContain("name: 'Remove Judicial research assistant from saved', exact: true");
    expect(text).toContain('saved:fresh-browser-context');
    expect(text).toContain("responseMatches(response, 'DELETE', '/api/v1/student/internships/menon/saved')");
    expect(text).toContain('await finishedResponse(removeDelete)');
  });
  it('retains the foundation identity and exact DELETE checks on article cards', () => {
    const text = source('v34-s11-s26-e2e.mjs');
    expect(text).toContain("getByRole('article').filter({ hasText: 'Judicial research assistant' })");
    expect(text).toContain("completedSavedMenon[0]?.status === 200 && completedSavedMenon[0]?.finishedError === null");
    expect(text).toContain("!functionalSavedIds.has('menon') && functionalSavedIds.has('cam')");
    expect(text).toContain("isExactApiResponse(response, 'DELETE', '/api/v1/student/internships/menon/saved')");
  });
  it('preserves the S-21 delayed snapshot and return-context proofs with the title control', () => {
    const text = source('s21-detail.browser-contract.mjs');
    expect(text).toContain('`${item.role} ${item.organisation}`');
    expect(text).toContain("'no persistence before confirmation'");
    expect(text).toContain("assert.equal(new URL(page.url()).searchParams.get('from'), 's25')");
    expect(text).toContain("assert.equal(new URL(page.url()).pathname, '/s-25')");
    expect(text).toContain('await s.heldRead()');
    expect(text).toContain("assert.deepEqual(s.mutations, [saved ? 'DELETE' : 'PUT'])");
  });
});
