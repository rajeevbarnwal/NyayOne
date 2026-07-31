/* Deterministic SHA256SUMS.txt for the whole package.
   Run twice: the output is byte-identical (the file excludes itself, the walk is
   sorted by POSIX path, and no timestamp or absolute path is written). */
import { readFileSync, writeFileSync, readdirSync, statSync } from 'node:fs';
import { createHash } from 'node:crypto';
import { dirname, join, relative, sep } from 'node:path';
import { fileURLToPath } from 'node:url';
const PKG = join(dirname(fileURLToPath(import.meta.url)), '..');
const SELF = 'SHA256SUMS.txt';

function walk(dir, acc = []) {
  for (const name of readdirSync(dir).sort()) {
    const full = join(dir, name);
    const st = statSync(full);
    if (st.isDirectory()) walk(full, acc);
    else acc.push(relative(PKG, full).split(sep).join('/'));
  }
  return acc;
}
const files = walk(PKG).filter(f => f !== SELF && !f.endsWith('.DS_Store')).sort();
const lines = files.map(f => createHash('sha256').update(readFileSync(join(PKG, f))).digest('hex') + '  ' + f);
writeFileSync(join(PKG, SELF), lines.join('\n') + '\n');
console.log(`${files.length} files hashed into ${SELF}`);
