/**
 * SAATHI-398/402 — request_id normalization regression probe.
 *
 * Mirrors the pipeline ruby filter (Logs/logstash/pipeline/logstash.conf,
 * id "normalize-request-id") in JS so the normalization CONTRACT can be checked
 * natively without Docker. It asserts that missing / JSON-null / empty / array
 * inputs all coerce to the SCALAR string "none" (never the array ["none"]) and
 * that a real id is preserved as a scalar string.
 *
 * The exact Logstash 8.15.3 config test (running the pipeline in the container
 * against Logs/logstash/test/request_id_probe.jsonl) runs in the Docker QA env.
 */
function normalizeRequestId(event) {
  let v = event.request_id; // undefined when the key is missing
  if (Array.isArray(v)) v = v[0];
  if (v === null || v === undefined || String(v).trim() === '') return 'none';
  return String(v);
}

const cases = [
  { name: 'missing', event: { level: 'info' }, expect: 'none' },
  { name: 'json-null', event: { request_id: null }, expect: 'none' },
  { name: 'empty', event: { request_id: '' }, expect: 'none' },
  { name: 'array-empty', event: { request_id: [] }, expect: 'none' },
  { name: 'array-null', event: { request_id: [null] }, expect: 'none' },
  { name: 'existing', event: { request_id: 'req-abc-123' }, expect: 'req-abc-123' },
];

let pass = 0;
const fails = [];
for (const c of cases) {
  const out = normalizeRequestId(c.event);
  const scalar = typeof out === 'string' && !Array.isArray(out);
  if (out === c.expect && scalar) pass += 1;
  else fails.push(`${c.name}: got ${JSON.stringify(out)} expected "${c.expect}" (scalar=${scalar})`);
}
// Explicit guard: the output must never be the array ["none"].
const arrayGuard = !Array.isArray(normalizeRequestId({ request_id: null }));
if (!arrayGuard) fails.push('array-guard: output was ["none"]');

console.log(`request_id probe: ${pass}/${cases.length} cases pass; array-guard=${arrayGuard}`);
if (fails.length) { console.log(fails.join('\n')); process.exit(1); }
