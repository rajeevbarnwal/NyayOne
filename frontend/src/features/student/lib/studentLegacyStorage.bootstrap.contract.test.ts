import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import { describe, expect, it } from 'vitest';

describe('NYAY-18 production storage bootstrap', () => {
  it('retires legacy session storage before React can mount a private route', () => {
    const main = readFileSync(join(process.cwd(), 'src/main.tsx'), 'utf8');
    const purge = main.indexOf('purgeLegacyStudentSessionStorageAtBootstrap();');
    const render = main.indexOf('ReactDOM.createRoot');

    expect(main).toContain("from './features/student/lib/studentLegacyStorage'");
    expect(purge).toBeGreaterThanOrEqual(0);
    expect(render).toBeGreaterThan(purge);
  });
});
