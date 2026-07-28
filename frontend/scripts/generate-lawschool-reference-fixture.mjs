/**
 * SAATHI-121 — regenerate the Option C+ reference harness fixtures from the
 * shared deterministic fixture contract (lawschool_fixture_contract.json).
 *
 * The approved reference frame
 * (docs/design/lawschool_reference/option_c_plus/OPTION_C_PLUS_GUIDED_CONFIDENCE.html)
 * is a single-file bundle: its LSKIT seed script is stored as a gzip+base64
 * resource in the `__bundler/manifest` script block and the page markup as a
 * JSON string in the `__bundler/template` block. This generator:
 *   1. renders a new LSKIT module (SEED / LABELS / FACTS / FACTS29 / FIXTURE)
 *      from the contract — school ids ARE the backend catalog slugs, fact
 *      rows/values byte-match the backend seed, and
 *      window.LSKIT.FIXTURE.checksum embeds the contract checksum so the E2E
 *      harness can refuse to capture against a stale reference;
 *   2. patches the template's hard-coded state ids (compare set, saved /
 *      followed defaults, detail id) from the contract with ANCHORED,
 *      COUNT-VERIFIED replacements (the script aborts if an anchor is absent);
 *   3. writes a readable copy (OPTION_C_PLUS_LSKIT_GENERATED.js), patches
 *      QA_HARNESS_C_PLUS.html expectations, and rewrites SHA256SUMS.txt.
 *
 * Deterministic: node scripts/generate-lawschool-reference-fixture.mjs
 * always produces identical bytes for an identical contract.
 */
import fs from 'node:fs';
import path from 'node:path';
import crypto from 'node:crypto';
import { fileURLToPath } from 'node:url';
import {
  contract, contractChecksum, catalogSlugsByName, factRowsFor, programmesFor,
} from './lawschool_fixture_contract.mjs';

const HERE = path.dirname(fileURLToPath(import.meta.url));
const REF_DIR = path.resolve(HERE, '..', '..', 'docs', 'design', 'lawschool_reference', 'option_c_plus');
const HTML = path.join(REF_DIR, 'OPTION_C_PLUS_GUIDED_CONFIDENCE.html');
const QA_HARNESS = path.join(REF_DIR, 'QA_HARNESS_C_PLUS.html');

const checksum = contractChecksum();
const feeInr = (n) => `₹${n.toLocaleString('en-IN')}`;
const TYPE_LABELS = {
  national_law_university: 'National Law University · state-established',
  deemed: 'Deemed university',
  private: 'Private university',
  government: 'Government law college',
};

function rowsFor(slug) {
  const s = contract.catalog.find((x) => x.slug === slug);
  const facts = Object.fromEntries(factRowsFor(slug).map((r) => [r.key, r.value]));
  return {
    state: s.state,
    type: TYPE_LABELS[s.institutionType],
    accr: s.accreditation,
    exam: s.entranceExam,
    fees: `${feeInr(s.feesMin)}–${feeInr(s.feesMax)}/yr`,
    nirf: `#${s.nirfRank}`,
    progs: programmesFor(slug).map((p) => `${p.degree} (${p.durationYears} yrs)`).join(' · '),
    ...facts,
  };
}

const seedEntries = contract.catalog.map((s) => ({
  id: s.slug,
  short: s.short,
  name: s.name,
  city: s.city,
  state: s.state,
  region: s.region,
  est: s.established,
  type: s.institutionType,
  exam: s.entranceExam,
  seats: s.seats,
  feeMin: s.feesMin,
  feeMax: s.feesMax,
  hostel: true,
  nirf: `#${s.nirfRank}`,
  clinics: s.legalAidClinics,
  moots: s.mootTeams,
  rows: rowsFor(s.slug),
}));

/* Row schemas: FACTS drives S-28 ("The essentials", matches the developed
 * S-28 rows: exam/fees/nirf/progs + the six seeded fact rows); FACTS29 drives
 * S-29 fact cards (developed compare columns + the same six fact rows). */
const FACTS28_DEFS = [
  ['exam', 'Entrance exam'], ['fees', 'Fee band (sample)'], ['nirf', 'NIRF rank (sample)'],
  ['progs', 'Programmes'],
  ['established', 'established'], ['location', 'location'], ['intake', 'intake'],
  ['hostel', 'hostel'], ['legal_aid_clinics', 'legal_aid_clinics'], ['moot_teams', 'moot_teams'],
];
const FACTS29_DEFS = [
  ['state', 'State'], ['type', 'Institution type'], ['accr', 'Accreditation'],
  ['exam', 'Entrance exam'], ['fees', 'Fees (per year)'], ['nirf', 'NIRF rank'],
  ['progs', 'Programmes'],
  ['established', 'established'], ['location', 'location'], ['intake', 'intake'],
  ['hostel', 'hostel'], ['legal_aid_clinics', 'legal_aid_clinics'], ['moot_teams', 'moot_teams'],
];

const examLabels = Object.fromEntries(contract.catalog.map((s) => [s.entranceExam, s.entranceExam]));

const FIXTURE = {
  version: contract.version,
  checksum,
  catalogSlugsByName: catalogSlugsByName(),
  perPage: contract.s27.pageSize,
  s27Visible: contract.s27.visibleSlugs,
  s28Slug: contract.s28.slug,
  s29Slugs: contract.s29.slugs,
  s30Saved: contract.s30.saved,
  s30Followed: contract.s30.followed,
  factKeys: contract.factKeys,
};

const lskit = `/* LSKIT — GENERATED from frontend/scripts/lawschool_fixture_contract.json
 * by frontend/scripts/generate-lawschool-reference-fixture.mjs — DO NOT EDIT
 * BY HAND. Shared deterministic fixture for S-27..S-30: school ids are the
 * backend catalog slugs and every fact row byte-matches the backend seed
 * (law_school_service.seed_law_schools). contract checksum: ${checksum} */
window.LSKIT=(function(){
var SEED=${JSON.stringify(seedEntries, null, 1)};
var LABELS={
 type:${JSON.stringify(TYPE_LABELS)},
 exam:${JSON.stringify(examLabels)},
 progs:{ba_llb:'B.A. LL.B. (Hons.)',llm:'LL.M.'},
 hostel:{true:'On-campus hostel',false:'No on-campus hostel'}
};
var VERIFIED=${JSON.stringify(contract.verifiedDate)};
var FIXTURE=${JSON.stringify(FIXTURE, null, 1)};
function fmtDate(iso){var d=new Date(iso+'T00:00:00');var M=['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec'];return d.getDate()+' '+M[d.getMonth()]+' '+d.getFullYear();}
function lakh(n){return '₹'+(n/100000).toFixed(1).replace(/\\.0$/,'')+' L';}
function fee(s){return lakh(s.feeMin)+'–'+lakh(s.feeMax)+' / yr';}
var COPY={
 verified:'Verified '+fmtDate(VERIFIED),
 sample:'Sample data · prototype',
 source:'Source: institution website · sample verification '+fmtDate(VERIFIED)+' · prototype data, not production facts',
 responsible:'Verify every fact on the institution\\u2019s official website before acting on it. This directory shows sample prototype data with source and freshness context; it is not admission guidance.',
 nirfNote:'Rank shown only where NIRF (Law) publishes it · sample rank for prototype',
 unavailable:'Not available · not yet verified from an official source',
 signedOutSave:'Sign in to save or follow law schools. Your lists are private to your account.',
 signedOut30:'Sign in to see your saved and followed law schools. Lists are private and are never shown to other users.',
 forbidden:'This feature isn\\u2019t available for your current account type. No student data is shown or shared.',
 refusalTitle:'Comparison is limited to 4 schools',
 refusalBody:'Remove one school to add another. Nothing was changed by this attempt.',
 refusalWire:'{ "error": "COMPARE_LIMIT_EXCEEDED", "max_allowed": 4 }',
 dup:'Already in your comparison — each school can appear once.',
 belowMin:'Pick at least 2 schools to compare — comparison needs a minimum of two.',
 netFail:'We couldn\\u2019t reach the directory service. Your selections were not changed.',
 commitFail:'The comparison couldn\\u2019t be created. No partial comparison was saved.',
 validation:'Search accepts letters, numbers and spaces only (2–60 characters).',
 empty:'No law schools match these filters yet. Clear a filter or widen your search.',
 zeroFacts:'No verified facts are available for this institution yet. We only show facts with a source and verification date.',
 unknown:'We couldn\\u2019t find that law school. It may have been removed or the link is out of date.',
 missingId:'This link is incomplete — no school was specified.',
 dpdp:'Saved and followed lists are stored against your account under the DPDP Act, 2023 — export or delete them anytime in Privacy.'
};
function rowFact(defs){return defs.map(function(d){return {k:d[0],label:d[1],get:function(s){return String(s.rows[d[0]]);}};});}
var FACTS=rowFact(${JSON.stringify(FACTS28_DEFS)});
var FACTS29=rowFact(${JSON.stringify(FACTS29_DEFS)});
var STATES=[
 ['s27-default','S-27','Initial / default (12 results)'],['s27-search','S-27','Search result'],['s27-filtered','S-27','Filtered result'],['s27-sorted','S-27','Sorted + selected-sort indication'],['s27-page','S-27','Pagination (page 2)'],['s27-empty','S-27','Empty result'],['s27-loading','S-27','Loading / skeleton'],['s27-validation','S-27','Typed validation error'],['s27-fail','S-27','Provider failure + Retry'],['s27-tray0','S-27','Comparison tray · 0 selected'],['s27-tray1','S-27','Comparison tray · 1 selected'],['s27-tray2','S-27','Comparison tray · 2 selected'],['s27-tray4','S-27','Comparison tray · 4 selected'],['s27-refusal','S-27','Fifth-school refusal (typed error)'],['s27-dup','S-27','Duplicate-school feedback'],['s27-url','S-27','Refreshed URL-state restoration'],
 ['s28-detail','S-28','Full verified detail'],['s28-loading','S-28','Loading'],['s28-missing','S-28','Missing ID'],['s28-unknown','S-28','Unknown school'],['s28-zero','S-28','Zero facts'],['s28-saved','S-28','Save → Saved'],['s28-follow','S-28','Follow → Following'],['s28-signedout','S-28','Signed-out action'],['s28-forbidden','S-28','Wrong-role / forbidden'],['s28-fail','S-28','Fetch failure + Retry'],['s28-restored','S-28','Refresh with state restored'],
 ['s29-2','S-29','Compare 2'],['s29-4','S-29','Compare 4'],['s29-min','S-29','Below-minimum'],['s29-dup','S-29','Duplicate blocked'],['s29-refusal','S-29','Fifth-school refusal'],['s29-loading','S-29','Loading'],['s29-fail','S-29','Commit failure · no partial result'],['s29-anon','S-29','Anonymous / sign-in'],['s29-url','S-29','URL refresh / replay'],['s29-narrow','S-29','Narrow-screen comparison'],
 ['s30-both','S-30','Saved + followed populated'],['s30-saved','S-30','Saved only'],['s30-followed','S-30','Followed only'],['s30-empty','S-30','Both empty'],['s30-loading','S-30','Loading'],['s30-fail','S-30','List-fetch failure + Retry'],['s30-signedout','S-30','Signed-out'],['s30-forbidden','S-30','Wrong-role / forbidden'],['s30-removing','S-30','Unsave / unfollow in progress'],['s30-idempotent','S-30','Idempotent empty after removal'],['s30-restored','S-30','Refreshed / restored session']
];
function store(prefix){
 function get(k,d){try{var v=localStorage.getItem(prefix+k);return v===null?d:JSON.parse(v);}catch(e){return d;}}
 function set(k,v){try{localStorage.setItem(prefix+k,JSON.stringify(v));}catch(e){}}
 return {get:get,set:set};
}
function initTheme(st,apply){
 var t=st.get('theme',null);
 if(!t)t=(window.matchMedia&&matchMedia('(prefers-color-scheme: dark)').matches)?'dark':'light';
 apply(t);
 return {get:function(){return document.documentElement.getAttribute('data-theme');},
  set:function(t2){apply(t2);st.set('theme',t2);},
  toggle:function(){this.set(this.get()==='dark'?'light':'dark');}};
}
function qs(h){var o={};(h.split('?')[1]||'').split('&').forEach(function(p){if(!p)return;var kv=p.split('=');o[decodeURIComponent(kv[0])]=decodeURIComponent(kv[1]||'');});return o;}
function qstr(o){var a=[];for(var k in o){if(o[k]!==''&&o[k]!=null)a.push(encodeURIComponent(k)+'='+encodeURIComponent(o[k]));}return a.length?'?'+a.join('&'):'';}
function esc(s){return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;');}
function announce(msg){var l=document.getElementById('live');if(l){l.textContent='';setTimeout(function(){l.textContent=msg;},30);}}
function byId(id){for(var i=0;i<SEED.length;i++)if(SEED[i].id===id)return SEED[i];return null;}
return {SEED:SEED,LABELS:LABELS,COPY:COPY,FACTS:FACTS,FACTS29:FACTS29,FIXTURE:FIXTURE,STATES:STATES,VERIFIED:VERIFIED,
 fmtDate:fmtDate,lakh:lakh,fee:fee,store:store,initTheme:initTheme,qs:qs,qstr:qstr,esc:esc,announce:announce,byId:byId};
})();
`;

/* ------------------------- patch the bundled HTML -------------------------- */

function replaceCounted(source, from, to, expected, label) {
  let count = 0;
  let out = source;
  while (out.includes(from)) { out = out.replace(from, to); count += 1; }
  /* idempotent re-runs: the anchor is gone but the target is already present */
  if (count === 0 && out.includes(to)) return out;
  if (count !== expected) {
    throw new Error(`anchor "${label}" matched ${count} times, expected ${expected}`);
  }
  return out;
}

/* --------------------------- HTML-safe JSON --------------------------------
 * ROOT FIX (SAATHI-121 / QA F1): JSON.parse of the template/manifest payload
 * un-escapes any embedded "<\u002Fscript" back to a literal "</script>", and a
 * plain JSON.stringify writes it back literally. An HTML parser then terminates
 * the OUTER <script type="__bundler/*"> element at the first embedded literal
 * close tag, the unpacker never runs and window.__opt never boots. Every JSON
 * payload written into a <script> element MUST therefore re-escape
 * "</script" -> "<\u002Fscript" (and "<!--" -> "\u003C!--" so script-data
 * escaped-state parsing can never engage). Both replacements happen inside
 * JSON string literals where "\u002F" / "\u003C" are exact-equivalent
 * escapes, so JSON.parse round-trips byte-identically. */
function htmlSafeJson(value) {
  return JSON.stringify(value)
    .split('</script').join('<\\u002Fscript')
    .split('<!--').join('\\u003C!--');
}

const lines = fs.readFileSync(HTML, 'utf8').split('\n');
const manifestOpen = lines.findIndex((l) => l.includes('<script type="__bundler/manifest">'));
const templateOpen = lines.findIndex((l) => l.includes('<script type="__bundler/template">'));
if (manifestOpen < 0 || templateOpen < 0) throw new Error('bundler blocks not found');

const manifest = JSON.parse(lines[manifestOpen + 1]);
const jsKey = Object.keys(manifest).find((k) => manifest[k].mime === 'application/javascript');
if (!jsKey) throw new Error('LSKIT javascript resource not found in manifest');
/* Uncompressed base64: identical LSKIT source bytes -> identical bundle bytes
 * on every Node/zlib version (gzip output is zlib-build dependent). The
 * unpacker treats compressed:false entries as raw bytes. */
manifest[jsKey] = {
  ...manifest[jsKey],
  compressed: false,
  data: Buffer.from(lskit, 'utf8').toString('base64'),
};
lines[manifestOpen + 1] = htmlSafeJson(manifest);

let tpl = JSON.parse(lines[templateOpen + 1]);
const [c1, c2, c3, c4] = contract.s29.slugs;
const q = (arr) => `[${arr.map((s) => `'${s}'`).join(',')}]`;
/* Anchored, count-verified template patches (order matters: longest first). */
tpl = replaceCounted(tpl, "S.cmp=['nlsiu','nalsar','nlud','gnlu'];", `S.cmp=${q([c1, c2, c3, c4])};`, 2, 's27-tray4/s29-4 compare set');
tpl = replaceCounted(tpl, "S.cmp=['nlsiu','nalsar'];", `S.cmp=${q([c1, c2])};`, 2, 's27-tray2/s29-2 compare pair');
tpl = replaceCounted(tpl, "S.saved=['nlsiu','gnlu'];S.followed=['nlud','nalsar'];", `S.saved=${q(contract.s30.saved)};S.followed=${q(contract.s30.followed)};`, 1, 's30-both lists');
tpl = replaceCounted(tpl, "st.get('saved',['nlsiu','gnlu'])", `st.get('saved',${q(contract.s30.saved)})`, 1, 'saved default');
tpl = replaceCounted(tpl, "st.get('followed',['nlud','nalsar'])", `st.get('followed',${q(contract.s30.followed)})`, 1, 'followed default');
tpl = replaceCounted(tpl, "S.removing='saved:nlsiu';", `S.removing='saved:${contract.s30.saved[0]}';`, 1, 's30-removing id');
tpl = replaceCounted(tpl, 'var rows=F.map(', 'var rows=(K.FACTS29||F).map(', 1, 'r29 row schema');
/* Remaining single-quoted short-id tokens → contract slugs. */
for (const [from, to] of [
  ["'nlsiu'", `'${contract.s28.slug}'`],
  ["'dsnlu'", "'rgnul-patiala'"],
]) {
  tpl = tpl.split(from).join(to);
}
for (const short of ['nalsar', 'nlud', 'gnlu', 'nujs']) {
  if (tpl.includes(`'${short}'`)) throw new Error(`unpatched short id token '${short}' remains in template`);
}
lines[templateOpen + 1] = htmlSafeJson(tpl);
fs.writeFileSync(HTML, lines.join('\n'));

/* Structural boot-safety assertion: the outer document must keep EXACTLY one
 * literal close tag per <script> element and the JSON payload segments must
 * contain zero literal "</script" / "<!--" tokens (else the bundle cannot
 * boot; see F1). Throws — the generator refuses to emit a broken bundle. */
{
  const finalHtml = fs.readFileSync(HTML, 'utf8');
  const finalLines = finalHtml.split('\n');
  const count = (hay, needle) => hay.split(needle).length - 1;
  const closeTags = count(finalHtml, '</script');
  /* Outer script ELEMENTS open at line starts; '<script' tokens inside JS
   * string literals or JSON payloads are not element opens. */
  const blockOpens = finalLines.filter((l) => /^\s*<script[\s>]/.test(l)).length;
  const payloads = [
    ['__bundler/manifest payload', finalLines[manifestOpen + 1]],
    ['__bundler/template payload', finalLines[templateOpen + 1]],
  ];
  for (const [label, payload] of payloads) {
    for (const tok of ['</script', '<!--']) {
      const n = count(payload, tok);
      if (n !== 0) throw new Error(`boot-safety: ${n} literal ${JSON.stringify(tok)} token(s) inside ${label} — bundle would terminate early and never boot`);
    }
  }
  const EXPECTED_SCRIPT_BLOCKS = 5; /* unpacker + manifest + ext_resources + page_order + template */
  if (blockOpens !== EXPECTED_SCRIPT_BLOCKS || closeTags !== EXPECTED_SCRIPT_BLOCKS) {
    throw new Error(`boot-safety: expected ${EXPECTED_SCRIPT_BLOCKS} outer <script> blocks with exactly one close tag each; saw opens=${blockOpens} closeTags=${closeTags}`);
  }
}

/* readable LSKIT copy for review/diffing */
fs.writeFileSync(path.join(REF_DIR, 'OPTION_C_PLUS_LSKIT_GENERATED.js'), lskit);

/* QA reviewer harness expectations (S-29 card count + probe ids). */
let qa = fs.readFileSync(QA_HARNESS, 'utf8');
const n29 = FACTS29_DEFS.length;
qa = replaceCounted(qa, "K.byId('nlsiu'),b=K.byId('nalsar')", `K.byId('${c1}'),b=K.byId('${c2}')`, 1, 'qa harness probe ids');
qa = replaceCounted(qa, 'K.FACTS.filter', '(K.FACTS29||K.FACTS).filter', 1, 'qa harness FACTS29');
qa = replaceCounted(qa, '11 fact cards', `${n29} fact cards`, 1, 'qa harness card count copy');
qa = replaceCounted(qa, 'all===11', `all===${n29}`, 1, 'qa harness card count assert');
fs.writeFileSync(QA_HARNESS, qa);

/* SHA256SUMS.txt over the reference package */
const sums = fs.readdirSync(REF_DIR)
  .filter((f) => f !== 'SHA256SUMS.txt')
  .sort()
  .map((f) => `${crypto.createHash('sha256').update(fs.readFileSync(path.join(REF_DIR, f))).digest('hex')}  ${f}`)
  .join('\n');
fs.writeFileSync(path.join(REF_DIR, 'SHA256SUMS.txt'), `${sums}\n`);

console.log(JSON.stringify({
  contractChecksum: checksum,
  seedSchools: seedEntries.length,
  s27Visible: FIXTURE.s27Visible,
  s29Slugs: FIXTURE.s29Slugs,
  s30: { saved: FIXTURE.s30Saved, followed: FIXTURE.s30Followed },
  facts28Rows: FACTS28_DEFS.length,
  facts29Rows: FACTS29_DEFS.length,
}, null, 2));
