/* Runtime path resolution for every executable in this package.

   No tool in this package may carry a hard-coded machine path. Independent QA
   found absolute session-scratch defaults baked into five tools, which makes the package
   unreproducible anywhere else: the tool silently pointed at a checkout that
   does not exist and failed with an opaque module-resolution error.

   Rules enforced here:
     1. the repository root is discovered at RUNTIME (`git rev-parse --show-toplevel`,
        falling back to a structural walk up from `import.meta.url`);
     2. optional inputs resolve to repository-relative defaults;
     3. anything that cannot be derived MUST be supplied by CLI flag or env var
        and, if absent, raises a TYPED, fail-fast error naming both.
   A tool that cannot locate its inputs must stop loudly, never guess. */
import { existsSync, statSync } from 'node:fs';
import { dirname, join, resolve, sep } from 'node:path';
import { fileURLToPath } from 'node:url';
import { execFileSync } from 'node:child_process';

export class TypedPathError extends Error {
  constructor(code, message, detail) {
    super(code + ': ' + message);
    this.name = 'TypedPathError';
    this.code = code;
    this.detail = detail || null;
  }
}

/* The package root, derived structurally from this module's own URL. */
export const PACKAGE_ROOT = resolve(dirname(fileURLToPath(import.meta.url)), '..');

/* Repository root: git first (authoritative), then a structural walk. */
export function repoRoot(from) {
  const start = from || PACKAGE_ROOT;
  try {
    const top = execFileSync('git', ['-C', start, 'rev-parse', '--show-toplevel'],
      { encoding: 'utf8', stdio: ['ignore', 'pipe', 'ignore'] }).trim();
    if (top && existsSync(top)) return top;
  } catch { /* not a git checkout (an exported copy) — fall through */ }
  /* Structural fallback: <repo>/docs/design/tutoring/option_c2_reference_v1 */
  let dir = start;
  for (let i = 0; i < 12; i++) {
    if (existsSync(join(dir, '.git')) ||
        (existsSync(join(dir, 'frontend')) && existsSync(join(dir, 'docs')))) return dir;
    const up = dirname(dir);
    if (up === dir) break;
    dir = up;
  }
  const parts = PACKAGE_ROOT.split(sep);
  const anchor = parts.lastIndexOf('docs');
  if (anchor > 0) return parts.slice(0, anchor).join(sep) || sep;
  throw new TypedPathError('REPO_ROOT_NOT_RESOLVABLE',
    'could not derive the repository root from ' + start,
    { packageRoot: PACKAGE_ROOT });
}

/* Playwright. Order: explicit CLI flag, PLAYWRIGHT_MODULE, repo-relative,
   package-relative. Never a machine-specific literal. */
export function resolvePlaywright(cliValue) {
  const candidates = [];
  if (cliValue) candidates.push({ src: '--playwright', p: resolve(cliValue) });
  if (process.env.PLAYWRIGHT_MODULE) candidates.push({ src: 'PLAYWRIGHT_MODULE', p: resolve(process.env.PLAYWRIGHT_MODULE) });
  let root = null;
  try { root = repoRoot(); } catch { /* reported below if nothing else matches */ }
  if (root) candidates.push({ src: '<repo>/frontend/node_modules', p: join(root, 'frontend', 'node_modules', 'playwright', 'index.mjs') });
  candidates.push({ src: '<package>/../../../../frontend/node_modules',
                    p: resolve(PACKAGE_ROOT, '..', '..', '..', '..', 'frontend', 'node_modules', 'playwright', 'index.mjs') });
  const hit = candidates.find(c => existsSync(c.p));
  if (hit) return hit.p;
  throw new TypedPathError('PLAYWRIGHT_NOT_RESOLVABLE',
    'playwright/index.mjs was not found. Pass --playwright <path> or set PLAYWRIGHT_MODULE, ' +
    'or install playwright under <repo>/frontend.',
    { tried: candidates.map(c => c.src) });
}

/* A repository-relative input: default derived from the repo root, but the file
   must exist or the tool stops with a typed error. */
export function resolveRepoPath(cliValue, envName, repoRelative, code, what) {
  const fromEnv = envName ? process.env[envName] : null;
  const chosen = cliValue ? resolve(cliValue)
                : fromEnv ? resolve(fromEnv)
                : join(repoRoot(), repoRelative);
  if (!existsSync(chosen)) {
    throw new TypedPathError(code,
      what + ' was not found at ' + (cliValue || fromEnv ? 'the path you supplied' : 'its repository-relative default') +
      '. Supply it explicitly' + (envName ? ' via CLI flag or ' + envName : ' via CLI flag') + '.',
      { resolved: chosen, repoRelativeDefault: repoRelative });
  }
  return chosen;
}

/* A required directory that has NO sensible default: must be supplied. */
export function requireDirectory(cliValue, envName, code, what) {
  const chosen = cliValue || (envName ? process.env[envName] : null);
  if (!chosen) {
    throw new TypedPathError(code,
      what + ' is required and has no default. Pass it as an argument' +
      (envName ? ' or set ' + envName : '') + '.', { envVar: envName || null });
  }
  const abs = resolve(chosen);
  if (!existsSync(abs) || !statSync(abs).isDirectory()) {
    throw new TypedPathError(code, what + ' is not an existing directory.', { resolved: abs });
  }
  return abs;
}

/* Uniform fail-fast wrapper: a typed error exits 2 with a single readable line. */
export function failFast(fn) {
  try { return fn(); } catch (e) {
    if (e instanceof TypedPathError) {
      console.error('TYPED ERROR ' + e.code + ' — ' + e.message +
        (e.detail ? ' ' + JSON.stringify(e.detail) : ''));
      process.exit(2);
    }
    throw e;
  }
}
