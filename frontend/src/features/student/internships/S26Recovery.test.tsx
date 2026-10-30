import { renderToStaticMarkup } from 'react-dom/server';
import { createRef } from 'react';
import { describe, expect, it } from 'vitest';
import { S26RecoveryView, type S26RecoveryViewProps } from './S26RecoveryView';

const props = (): S26RecoveryViewProps => ({
  focus: createRef(), phase: 'empty', count: 0, refreshing: false,
  statusCode: null, offline: false, attempt: 0,
  onNavigate: () => undefined, onRetry: async () => undefined,
});
const render = (extra: Partial<S26RecoveryViewProps> = {}) => renderToStaticMarkup(<S26RecoveryView {...props()} {...extra}/>);
describe('S-26 server-authoritative Revision L recovery', () => {
  it('owns one main with sibling context and inert notices', () => {
    const html = render();
    expect(html.match(/<main/g)).toHaveLength(1);
    expect(html).toContain('</main><aside');
    expect(html).toContain('Saved internships.');
    expect(html).toContain('<span>Privacy Notice</span>');
    expect(html).toContain('data-screen="S-26"');
    expect(html).not.toContain('9:41');
  });
  it('claims empty only after a successful empty response', () => {
    expect(render()).toContain('No saved internships yet.');
    expect(render()).toContain('Browse internships');
    for (const phase of ['loading', 'error', 'nonempty', 'anonymous', 'forbidden', 'unavailable'] as const) {
      expect(render({ phase, count: 3 })).not.toContain('No saved internships yet.');
    }
  });
  it('uses actual response length, singular and plural, not the prototype count', () => {
    expect(render({ phase: 'nonempty', count: 1 })).toContain('You have 1 saved internship.');
    expect(render({ phase: 'nonempty', count: 7 })).toContain('You have 7 saved internships.');
    expect(render({ phase: 'nonempty', count: 7 })).toContain('Open saved internships');
    expect(render({ phase: 'nonempty', count: 7 })).not.toContain('You have 3');
  });
  it('reports genuine HTTP failures only and retains a focusable pending Retry', () => {
    const html = render({ phase: 'error', statusCode: 503, refreshing: true });
    expect(html).toContain('Could not check your saved list.');
    expect(html).toContain('HTTP 503');
    expect(html).toContain('role="alert" tabindex="-1"');
    expect(html).toContain('aria-disabled="true"');
    expect(html).toContain('aria-busy="true"');
    expect(html).not.toMatch(/ disabled(?:=|>)/);
    expect(render({ phase: 'error', statusCode: null })).not.toContain('HTTP ');
    expect(render({ phase: 'error', offline: true })).toContain('No request was sent.');
  });
  it('offers no false account data or writes to unauthorised visitors', () => {
    expect(render({ phase: 'anonymous' })).toContain('Go to sign in');
    expect(render({ phase: 'forbidden' })).toContain('Student account required');
    expect(render({ phase: 'forbidden' })).not.toContain('Go to sign in');
    for (const phase of ['empty', 'loading', 'error', 'nonempty'] as const) {
      expect(render({ phase })).not.toMatch(/>Apply<|>Remove<|Still saved|Nothing was removed/);
    }
  });
});
