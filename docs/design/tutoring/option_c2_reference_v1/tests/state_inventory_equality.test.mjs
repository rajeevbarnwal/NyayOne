/* Executable set-equality test for the 82-state inventory.
   Run: node docs/design/tutoring/option_c2_reference_v1/tests/state_inventory_equality.test.mjs
   Fails (exit 1) on: missing, duplicate, renamed, extra, screen drift,
   attribute gaps, unknown layout family, or fixture checksum drift. */
import { createRequire } from 'node:module';
import { readFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';
const require = createRequire(import.meta.url);
const pkg = join(dirname(fileURLToPath(import.meta.url)), '..');
globalThis.C2Fixtures = require(join(pkg, 'reference/fixtures.js'));
const St = require(join(pkg, 'reference/states.js'));
const inv = JSON.parse(readFileSync(join(pkg, 'STATE_INVENTORY.json'), 'utf8'));
const md = readFileSync(join(pkg, 'sources/STATE_INVENTORY_SOURCE.md'), 'utf8');

const fails = [], notes = [];
function check(name, ok, detail) { (ok ? notes : fails).push(`${ok ? 'PASS' : 'FAIL'} ${name}${detail ? ' — ' + detail : ''}`); }

/* --- parse the approved source --- */
const rows = [...md.matchAll(/^\|\s*(\d+)\s*\|\s*`([^`]+)`\s*\|\s*(S-3\d)\s*\|\s*(.*?)\s*\|/gm)]
  .map(m => ({ index: +m[1], id: m[2], screen: m[3], label: m[4] }));
const declared = (md.match(/\*\*(\d+) named states\*\*/) || [])[1];

check('source declares 82 named states', declared === '82', `declared=${declared}`);
check('source table row count is 82', rows.length === 82, `rows=${rows.length}`);

const srcIds = rows.map(r => r.id);
const invIds = inv.states.map(s => s.id);
const jsIds = St.IDS;

/* --- duplicates --- */
const dupSrc = srcIds.filter((v, i) => srcIds.indexOf(v) !== i);
const dupInv = invIds.filter((v, i) => invIds.indexOf(v) !== i);
check('no duplicate ids in the approved source', dupSrc.length === 0, dupSrc.join(','));
check('no duplicate ids in STATE_INVENTORY.json', dupInv.length === 0, dupInv.join(','));

/* --- set equality (missing / extra / renamed) --- */
const missing = srcIds.filter(id => !invIds.includes(id));
const extra = invIds.filter(id => !srcIds.includes(id));
check('no missing states (source \\ inventory)', missing.length === 0, missing.join(','));
check('no extra states (inventory \\ source)', extra.length === 0, extra.join(','));
check('state count is exactly 82', invIds.length === 82, `count=${invIds.length}`);
check('states.js and STATE_INVENTORY.json agree', JSON.stringify(jsIds) === JSON.stringify(invIds));

/* --- renamed: index, screen and label must match the approved source --- */
const byId = Object.fromEntries(inv.states.map(s => [s.id, s]));
const norm = t => t.replace(/[–—]/g, '-').replace(/★/g, 'stars').replace(/≥/g, '>=').replace(/\s+/g, ' ').trim();
const renamed = rows.filter(r => byId[r.id] && norm(byId[r.id].label) !== norm(r.label));
const screenDrift = rows.filter(r => byId[r.id] && byId[r.id].screen !== r.screen);
const orderDrift = rows.filter(r => byId[r.id] && byId[r.id].index !== r.index);
check('no renamed state labels', renamed.length === 0, renamed.map(r => r.id).join(','));
check('no canonical-screen drift', screenDrift.length === 0, screenDrift.map(r => r.id).join(','));
check('inventory order matches the approved source', orderDrift.length === 0, orderDrift.map(r => r.id).join(','));

/* --- S-32 must be represented --- */
const s32 = invIds.filter(id => byId[id].screen === 'S-32');
check('S-32 states present', s32.length >= 2, s32.join(','));

/* --- 13 required attributes on every state --- */
const ATTRS = inv.requiredAttributes;
check('13 required attributes declared', ATTRS.length === 13, `declared=${ATTRS.length}`);
const gaps = [];
for (const s of inv.states) for (const a of ATTRS)
  if (s[a] === undefined || s[a] === null || String(s[a]).trim() === '') gaps.push(`${s.id}.${a}`);
check('every state carries all 13 attributes', gaps.length === 0, gaps.slice(0, 8).join(','));

/* --- layout families must be known and complete --- */
const badFam = inv.states.filter(s => !inv.layoutFamilies.includes(s.layoutFamily));
check('every state maps to a known layout family', badFam.length === 0, badFam.map(s => s.id).join(','));
const usedFam = [...new Set(inv.states.map(s => s.layoutFamily))].sort();
check('every declared layout family is used', usedFam.length === inv.layoutFamilies.length, usedFam.join(','));

/* --- provenance labels are from the closed vocabulary --- */
const VOCAB = ['PRODUCT_APPROVED', 'BROWSER_MEASURED', 'PROPOSED', 'PENDING_PRIORITY2_CONTRACT', 'OUT_OF_SCOPE'];
const badProv = inv.states.filter(s => !VOCAB.some(v => String(s.provenance).startsWith(v)));
check('every provenance label is from the closed vocabulary', badProv.length === 0, badProv.map(s => s.id).join(','));

/* --- fixture checksum --- */
check('fixture checksum matches the frozen contract', inv.fixtureChecksum === globalThis.C2Fixtures.CHECKSUM,
  `${inv.fixtureChecksum} vs ${globalThis.C2Fixtures.CHECKSUM}`);

for (const n of notes) console.log(n);
for (const f of fails) console.error(f);
console.log(`\n${notes.length} passed, ${fails.length} failed (82-state set equality)`);
process.exit(fails.length ? 1 : 0);
