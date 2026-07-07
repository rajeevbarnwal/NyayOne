import { describe, expect, it } from 'vitest';
import {
  orderTracks,
  sourcePillText,
  syllabusFor,
  hasVisibleSourceMetadata,
  SOURCE_VERSION,
  SAMPLE_ITEMS_LABEL,
} from './exam';

describe('exam track selection + source-versioning (SAATHI-147)', () => {
  it('orders tracks per persona', () => {
    expect(orderTracks('clat')[0]).toBe('CLAT');
    expect(orderTracks('graduate')[0]).toBe('AIBE');
    expect(orderTracks('judiciary')[0]).toBe('Judiciary');
  });
  it('renders the source-versioned pill', () => {
    expect(sourcePillText()).toBe(`SOURCE-VERSIONED · ${SOURCE_VERSION} · verify current notification`);
    expect(syllabusFor('CLAT').sourceLabel).toContain('SOURCE-VERSIONED');
    expect(syllabusFor('CLAT').meta.pattern).toContain('CLAT 2026');
  });
  it('requires visible source metadata before an official-looking claim', () => {
    expect(hasVisibleSourceMetadata({ sourceVersion: SOURCE_VERSION, sampleLabel: SAMPLE_ITEMS_LABEL })).toBe(true);
    expect(hasVisibleSourceMetadata({ sourceVersion: SOURCE_VERSION })).toBe(false);
    expect(hasVisibleSourceMetadata({ sampleLabel: SAMPLE_ITEMS_LABEL })).toBe(false);
  });
});
