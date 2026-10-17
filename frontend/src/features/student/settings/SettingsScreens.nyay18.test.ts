import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import { describe, expect, it } from 'vitest';

describe('S-19 responsive control accessibility', () => {
  it('keeps visible consent and data controls outside collapsed disclosures at every width', () => {
    const source = readFileSync(
      join(process.cwd(), 'src/features/student/settings/PrivacySettingsView.tsx'),
      'utf8',
    );
    // Revision L replaces the legacy responsive disclosures with visible cards.
    // Keep the original accessibility requirement; no CSS-only disclosure opening.
    expect(source).not.toContain('<details');
    expect(source).not.toContain('<summary');
    expect(source).toContain('aria-labelledby="S-19-consents"');
    expect(source).toContain('aria-labelledby="S-19-data"');
    expect(source).toContain('role="switch"');
    expect(source).toContain('onClick={() => exportAction(props.onExport)}');
    expect(source).toContain('onClick={props.onDeleteOpen}');
  });
});
