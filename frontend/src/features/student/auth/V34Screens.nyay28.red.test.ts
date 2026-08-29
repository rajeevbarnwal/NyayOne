import { createElement, type ComponentType } from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { MemoryRouter } from 'react-router-dom';
import { describe, expect, it } from 'vitest';

import {
  V34AuthGate,
  V34Login,
  V34LoginOtp,
  V34OtpVerify,
  V34Register,
} from './V34Screens';

type ThemeProps = Readonly<{ theme?: 'light' | 'dark' }>;

function renderDark(Component: ComponentType): string {
  const ThemedComponent = Component as ComponentType<ThemeProps>;
  return renderToStaticMarkup(
    createElement(
      MemoryRouter,
      null,
      createElement(ThemedComponent, { theme: 'dark' }),
    ),
  );
}

function topbarMarkup(html: string): string {
  const topbar = html.match(/<header class="v321-topbar">(?<markup>[\s\S]*?)<\/header>/u);
  expect(topbar, 'missing Revision L desktop topbar').not.toBeNull();
  return topbar?.groups?.markup ?? '';
}

function srgbChannel(value: number): number {
  const normalized = value / 255;
  return normalized <= 0.04045
    ? normalized / 12.92
    : ((normalized + 0.055) / 1.055) ** 2.4;
}

function relativeLuminance(hex: string): number {
  const channels = hex.match(/[0-9a-f]{2}/giu);
  if (!channels || channels.length !== 3) throw new Error(`invalid colour: ${hex}`);
  const [red, green, blue] = channels.map((channel) => srgbChannel(Number.parseInt(channel, 16)));
  return (0.2126 * red) + (0.7152 * green) + (0.0722 * blue);
}

function contrastRatio(foreground: string, background: string): number {
  const lighter = Math.max(relativeLuminance(foreground), relativeLuminance(background));
  const darker = Math.min(relativeLuminance(foreground), relativeLuminance(background));
  return (lighter + 0.05) / (darker + 0.05);
}

describe('NYAY-28 accessibility advisory contracts', () => {
  it('F-01 uses the reversed Revision L lockup on every dark-theme desktop auth screen', () => {
    expect(contrastRatio('#efedf6', '#20243b')).toBeGreaterThanOrEqual(4.5);
    expect(contrastRatio('#9aa0cc', '#20243b')).toBeGreaterThanOrEqual(4.5);

    const screens = [
      ['S-03', V34AuthGate],
      ['S-04', V34Login],
      ['S-05', V34LoginOtp],
      ['S-08', V34Register],
      ['S-09', V34OtpVerify],
    ] as const;

    for (const [screen, Component] of screens) {
      const topbar = topbarMarkup(renderDark(Component));
      expect.soft(topbar, `${screen} reversed primary`).toContain('fill="#efedf6"');
      expect.soft(topbar, `${screen} reversed wordmark`).toContain('fill="#9aa0cc"');
      expect.soft(topbar, `${screen} light wordmark excluded`).not.toContain('fill="#14161a"');
      expect.soft(topbar, `${screen} light muted ink excluded`).not.toContain('fill="#5c5f7a"');
    }
  });

  it('F-02 never names the benefits div without a naming-permitted role', () => {
    const html = renderDark(V34AuthGate);
    const openingTag = html.match(
      /<div class="v321-brandpanel__benefits"(?<attributes>[^>]*)>/u,
    );

    expect(openingTag, 'missing v321-brandpanel__benefits container').not.toBeNull();
    const attributes = openingTag?.groups?.attributes ?? '';
    const hasAccessibleName = /\baria-label=/u.test(attributes);
    const hasNamingPermittedRole = /\brole="(?:list|group)"/u.test(attributes);

    expect(hasAccessibleName && !hasNamingPermittedRole).toBe(false);
  });
});
