import { renderToStaticMarkup } from 'react-dom/server';
import { createRef } from 'react';
import { describe, expect, it } from 'vitest';
import { S25SavedView, type S25SavedViewProps } from './S25SavedView';
import type { InternshipListing } from '../lib/internships';

const item: InternshipListing = {
  id: 'synthetic', role: 'Research intern', org: 'Synthetic chambers', location: 'Delhi',
  stipendMonthlyPaise: 123456, verificationStatus: 'unverified', deadline: '30 Oct',
  eligibility: '', tags: [], description: '', source: { name: 'Fixture', url: null, retrievedAt: null, verifiedAt: null },
};
const props = (): S25SavedViewProps => ({
  focus: createRef(), phase: 'list', items: [item], pendingId: null, refreshing: false,
  failure: '', notice: '', uncertain: false, statusCode: null,
  onNavigate: () => undefined, onRetry: async () => undefined, onRemove: async () => undefined,
});
const render = (overrides: Partial<S25SavedViewProps> = {}) => renderToStaticMarkup(<S25SavedView {...props()} {...overrides}/>);
describe('S-25 server-backed Revision L composition', () => {
  it('owns one main, sibling context, inert legal notices and compact linked cards', () => {
    const html = render();
    expect(html.match(/<main/g)).toHaveLength(1);
    expect(html).toContain('</main><aside');
    expect(html).toContain('Saved internships.');
    expect(html).toContain('Research intern');
    expect(html).toContain('Synthetic chambers');
    expect(html).toContain('Remove Research intern from saved');
    expect(html).not.toContain('>View<');
    expect(html).toContain('<span>Privacy Notice</span>');
    expect(html).toContain('Private to your account · organisations are not notified');
  });
  it('preserves paise and distinguishes an unstated stipend from zero', () => {
    expect(render()).toContain('₹1,234.56');
    expect(render({ items: [{ ...item, stipendMonthlyPaise: 0 }] })).toContain('₹0');
    expect(render({ items: [{ ...item, stipendMonthlyPaise: null }] })).toContain('Stipend not stated');
  });
  it('renders server order without substituting examples or inventing application actions', () => {
    const html = render({ items: [{ ...item, id: 'z', role: 'Z first' }, { ...item, id: 'a', role: 'A second' }] });
    expect(html.indexOf('Z first')).toBeLessThan(html.indexOf('A second'));
    expect(html).not.toContain('>Apply</button>');
    expect(html).not.toContain('/s-22');
  });
  it('does not turn loading, session failure or failed GET into an empty list', () => {
    for (const phase of ['loading', 'error', 'anonymous', 'forbidden', 'unavailable'] as const) {
      const html = render({ phase, items: [] });
      expect(html).not.toContain('No saved internships yet');
      expect(html).not.toContain('Remove Research');
    }
    expect(render({ phase: 'empty', items: [] })).toContain('No saved internships yet.');
  });
  it('keeps pending controls focusable while refusing additional activations', () => {
    const html = render({ pendingId: item.id });
    expect(html).toContain('aria-disabled="true"');
    expect(html).toContain('aria-busy="true"');
    expect(html).not.toMatch(/ disabled(?:=|>)/);
    expect(html).toContain('Research intern');
  });
  it('does not assert saved truth or success after an uncertain mutation', () => {
    const html = render({ uncertain: true, failure: 'Could not confirm removal. Reload your saved list.' });
    expect(html).toContain('role="alert" tabindex="-1"');
    expect(html).toContain('Reload saved list');
    expect(html).not.toContain('aria-pressed="true"');
    expect(html).not.toContain('Still saved');
    expect(html).not.toContain('Nothing was removed');
  });
  it('reports only genuine HTTP statuses and never a fabricated transport status', () => {
    expect(render({ phase: 'error', statusCode: 503 })).toContain('HTTP 503');
    expect(render({ phase: 'error', statusCode: null })).not.toContain('HTTP ');
  });
  it('uses the frozen italic treatment only for an unstated stipend', () => {
    expect(render({ items: [{ ...item, stipendMonthlyPaise: null }] })).toContain('<i>Stipend not stated</i>');
    expect(render()).not.toContain('<i>');
    expect(render({ items: [{ ...item, stipendMonthlyPaise: 0 }] })).not.toContain('<i>');
  });
  it('makes only the empty-state Browse action primary', () => {
    const html = render({ phase: 'empty', items: [] });
    const buttons = html.match(/<button class="s20-btn[\s\S]*?<\/button>/g) ?? [];
    expect(buttons).toHaveLength(3);
    expect(buttons.filter(button => button.includes('class="s20-btn s20-primary"'))).toHaveLength(1);
    expect(buttons[1]).toContain('class="s20-btn s20-primary"');
    expect(buttons[1]).not.toContain('s20-indigo');
    expect(render()).not.toContain('class="s20-btn s20-primary"');
  });
  it('sizes action glyphs at 18px without changing 20px state/bookmark glyphs', () => {
    for (const overrides of [{}, { phase: 'empty', items: [] }, { phase: 'error', statusCode: 503 }, { uncertain: true, failure: 'Could not confirm removal.' }] satisfies Partial<S25SavedViewProps>[]) {
      const html = render(overrides);
      const icons = html.match(/<span class="s20-action-icon[^"]*"><svg[^>]*>/g) ?? [];
      expect(icons.length).toBeGreaterThan(0);
      for (const icon of icons) expect(icon).toContain('width="18" height="18"');
      expect(html).toContain('<span class="s20-heading-icon"><svg width="20" height="20"');
    }
  });
  it('retains the error Retry action inside the frozen action-row wrapper', () => {
    const html = render({ phase: 'error', statusCode: 503 });
    expect(html).toContain('<div class="s20-actions"><button class="s20-btn s20-primary"');
    expect(html).toContain('aria-disabled="false"');
    expect(html).toContain('>Retry</button></div>');
  });
});
