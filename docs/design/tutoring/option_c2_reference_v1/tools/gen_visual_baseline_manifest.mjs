/* Regenerates (or VERIFIES) the per-file byte count and SHA-256 recorded in
   VISUAL_BASELINE_MANIFEST.json.

   Until now nothing regenerated this manifest. When a legitimate design fix
   changed a capture, the manifest kept the OLD hash and nothing failed — a
   visual baseline that silently disagrees with the files it indexes is worse
   than no baseline at all. `--verify` makes that drift an error.

   Usage:
     node tools/gen_visual_baseline_manifest.mjs            # rewrite bytes + sha256 in place
     node tools/gen_visual_baseline_manifest.mjs --verify   # exit non-zero on ANY drift

   Only `bytes` and `sha256` are touched: every other field (state, screen,
   viewport, theme, rationale, ordering) is product metadata and is preserved. */
import { readFileSync, writeFileSync, existsSync } from 'node:fs';
import { createHash } from 'node:crypto';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

const PKG = join(dirname(fileURLToPath(import.meta.url)), '..');
const FILE = join(PKG, 'VISUAL_BASELINE_MANIFEST.json');
const VERIFY = process.argv.includes('--verify');

const manifest = JSON.parse(readFileSync(FILE, 'utf8'));
if (!Array.isArray(manifest.baselines) || manifest.baselines.length === 0) {
  console.error('TYPED ERROR MANIFEST_EMPTY — VISUAL_BASELINE_MANIFEST.json lists no baselines');
  process.exit(2);
}

const drift = [], missing = [];
for (const b of manifest.baselines) {
  const abs = join(PKG, b.file);
  if (!existsSync(abs)) { missing.push(b.file); continue; }
  const buf = readFileSync(abs);
  const sha256 = createHash('sha256').update(buf).digest('hex');
  if (b.sha256 !== sha256 || b.bytes !== buf.length) {
    drift.push({ file: b.file, was: { bytes: b.bytes, sha256: b.sha256 }, now: { bytes: buf.length, sha256 } });
    if (!VERIFY) { b.bytes = buf.length; b.sha256 = sha256; }
  }
}

if (missing.length) {
  console.error('TYPED ERROR BASELINE_FILE_MISSING — ' + missing.join(', '));
  process.exit(2);
}
if (VERIFY) {
  for (const d of drift) console.error('DRIFT ' + d.file + ' bytes ' + d.was.bytes + '->' + d.now.bytes);
  console.log((manifest.baselines.length - drift.length) + '/' + manifest.baselines.length +
              ' baselines match their recorded SHA-256');
  process.exit(drift.length ? 1 : 0);
}
writeFileSync(FILE, JSON.stringify(manifest, null, 2) + '\n');
for (const d of drift) console.log('updated ' + d.file);
console.log('VISUAL_BASELINE_MANIFEST.json: ' + manifest.baselines.length + ' baselines, ' + drift.length + ' updated');
