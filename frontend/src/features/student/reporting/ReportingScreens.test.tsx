import { describe, expect, it } from 'vitest';
import { renderToStaticMarkup } from 'react-dom/server';
import type { ReactElement } from 'react';
import { MemoryRouter } from 'react-router-dom';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { InternshipReportCreate, InternshipReportStatus } from './ReportingScreens';

function render(path: string, component: ReactElement): string {
  const client = new QueryClient({ defaultOptions: { queries: { enabled: false, retry: false } } });
  return renderToStaticMarkup(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={[path]}>{component}</MemoryRouter>
    </QueryClientProvider>,
  );
}

describe('SAATHI-269 S-86/S-87 private reporting screens', () => {
  it('renders every required private-report field and strict temporal/file constraints', () => {
    const html = render('/s-86', <InternshipReportCreate />);
    expect(html).toContain('data-screen="S-86"');
    expect(html).toContain('Organisation name');
    expect(html).toContain('Listing or application reference');
    expect(html).toContain('maxLength="160"');
    expect(html).toContain('maxLength="120"');
    expect(html.match(/type="date"/g)).toHaveLength(2);
    expect(html).toContain('max="');
    expect(html).toContain('maxLength="5000"');
    expect(html).toContain('multiple=""');
    expect(html).toContain('.pdf,.png,.jpg,.jpeg');
    expect(html).toContain('internship-report-v1');
  });

  it('renders exactly ten categories and both approved privacy modes', () => {
    const html = render('/s-86', <InternshipReportCreate />);
    expect(html.match(/<input id="ir-category-[a-z_]+"/g)).toHaveLength(10);
    expect(html).toContain('value="anonymous"');
    expect(html).toContain('value="private_to_platform"');
    expect(html).toContain('aria-label="About reporting privacy"');
  });

  it('contains no public risk-label or public allegation action', () => {
    const html = render('/s-86', <InternshipReportCreate />);
    expect(html).toContain('Public organisation risk labels are disabled');
    expect(html).not.toMatch(/<(?:button|a)[^>]*>[^<]*(?:publish report|publish allegation|public score)/i);
  });

  it('renders reporter-only status without requiring public projection data', () => {
    const html = render('/s-87', <InternshipReportStatus />);
    expect(html).toContain('data-screen="S-87"');
    expect(html).toContain('Only the signed-in reporter');
    expect(html).toContain('Select a private report');
    expect(html).not.toMatch(/organisation rating|risk percentage|public label/i);
  });
});
