import { renderToStaticMarkup } from 'react-dom/server';
import { MemoryRouter } from 'react-router-dom';
import { describe, expect, it, vi } from 'vitest';
import { V34Onboarding } from './V34Screens';
import { completeR2Onboarding } from './S02R2';

describe('NYAY-80 S-02 approved R2 onboarding', () => {
  it('renders one introduction with the approved copy and two exit actions', () => {
    const html = renderToStaticMarkup(<MemoryRouter><V34Onboarding /></MemoryRouter>);
    for (const text of ['Welcome to NyayOne', 'Law school asks a lot.', 'Keep it in one place.', 'Your record, together', 'Opportunities that fit', 'Read with the source', 'Continue', 'Skip for now', 'Continue to NyayOne. No account is created at this step.']) expect(html).toContain(text);
    expect(html.match(/<button\b/g)).toHaveLength(2);
    expect(html).not.toContain('Next slide');
    expect(html).not.toContain('<input');
    expect(html).not.toContain('data-kbfocus');
  });
  it('writes only the versioned presentation preference before routing to S-03', () => {
    const events: unknown[] = [];
    completeR2Onboarding(path => events.push(path), { setItem: (key, value) => events.push([key, value]) });
    expect(events).toEqual([['nyayone.r2.onboarding-seen', 'true'], '/s-03']);
  });
  it('does not trap users when browser storage is unavailable', () => {
    const navigate = vi.fn();
    completeR2Onboarding(navigate, { setItem: () => { throw new Error('storage unavailable'); } });
    expect(navigate).toHaveBeenCalledExactlyOnceWith('/s-03');
  });
});
