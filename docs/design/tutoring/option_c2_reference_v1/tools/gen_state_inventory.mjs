/* Generates STATE_INVENTORY.json from reference/states.js. Deterministic. */
import { createRequire } from 'node:module';
import { writeFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';
const require = createRequire(import.meta.url);
const here = dirname(fileURLToPath(import.meta.url));
const pkg = join(here, '..');
globalThis.C2Fixtures = require(join(pkg, 'reference/fixtures.js'));
const St = require(join(pkg, 'reference/states.js'));
const ATTRS = ['id','screen','trigger','requiredInfoActions','category','serverAuthoritativeRule','typedError',
  'recovery','fixtureId','layoutFamily','a11yObligations','persistence','provenance'];
const out = {
  schema: 'legalsaathi.tutoring.state-inventory/1',
  package: 'docs/design/tutoring/option_c2_reference_v1',
  generatedFrom: 'reference/states.js',
  sourceOfTruth: 'sources/STATE_INVENTORY_SOURCE.md (82 named states, PRODUCT_APPROVED)',
  requiredAttributes: ATTRS,
  fixtureChecksum: globalThis.C2Fixtures.CHECKSUM,
  stateCount: St.STATES.length,
  layoutFamilies: St.FAMILIES,
  states: St.STATES.map(s => {
    const o = { index: s.index, label: s.label };
    for (const a of ATTRS) o[a] = s[a];
    return o;
  })
};
writeFileSync(join(pkg, 'STATE_INVENTORY.json'), JSON.stringify(out, null, 2) + '\n');
console.log('STATE_INVENTORY.json written:', out.stateCount, 'states,', ATTRS.length, 'attributes each');
