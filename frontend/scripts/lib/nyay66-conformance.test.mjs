import { describe, expect, it } from 'vitest';
import { PNG } from 'pngjs';
import {createHash} from 'node:crypto';
import {mkdtemp,mkdir,readFile,writeFile,rm} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import {resolve,dirname} from 'node:path';
import {fileURLToPath} from 'node:url';
import * as r2 from './nyay66-r2.mjs';
import {
  SOURCE_SHA256, VIEWS, VIEWPORTS, coverage, comparePixels,
  validateCalibration, classifyObservation,
} from './nyay66-conformance.mjs';

const image = () => new PNG({ width: 2, height: 2, fill: true });
describe('R2 additive reference coverage', () => {
  it('covers exactly 14 approved light states and 42 reference panels', () => {
    expect(r2.R2_STATES).toHaveLength(14);
    expect(r2.R2_VIEWPORTS).toHaveLength(3);
    expect(coverage('light', {r2:true}).filter(x=>x.source==='r2').map(x=>[x.screen,x.views.length])).toEqual([['S-01',3],['S-02',2],['S-06',9]]);
    expect(coverage('dark', {r2:true}).every(x=>x.status==='DESIGN-GAP')).toBe(true);
    expect(coverage().filter(x=>x.status==='DESIGN-GAP')).toHaveLength(3);
  });
  it('never claims unimplemented state fixtures were executed or conformant', () => {
    expect(r2.pendingStateRow('S-06','s06-success','desktop',[])).toMatchObject({executed:false,verdict:'NOT-YET-MEASURED',blocking:false});
    expect(r2.pendingStateRow('S-06','s06-success','desktop',['S-06']).blocking).toBe(true);
  });
  const manifest=()=>({schema:1,sourceSha256:r2.R2_SOURCE_SHA256,approval:'NYAY-50:15422',theme:'light',chromium:'149.0.7827.55',playwright:'1.61.1',platform:'linux-x64',fonts:{},rows:r2.R2_STATES.flatMap(view=>r2.R2_VIEWPORTS.map(v=>({view:view.id,viewport:v.id,file:`${view.id}-${v.id}-0.png`,sha256:'a'.repeat(64),dimensions:[v.width,v.height],surface:{controls:[],headings:[],text:'reference',masks:[],dimensions:[v.width,v.height]}})))});
  it('accepts only complete independently pinned R2 manifest',()=>expect(r2.validateR2Manifest(manifest())).toBe(true));
  for(const [name,mutate] of [
    ['source',m=>m.sourceSha256='a'.repeat(64)],['approval',m=>m.approval='self'],['dark',m=>m.theme='dark'],
    ['missing',m=>m.rows.pop()],['duplicate',m=>m.rows[1]=m.rows[0]],['path escape',m=>m.rows[0].file='../outside.png'],
    ['hash',m=>m.rows[0].sha256='invalid'],['dimensions',m=>m.rows[0].dimensions=[1,1]],['surface',m=>delete m.rows[0].surface],
  ]) it(`refuses R2 ${name}`,()=>{const m=manifest();mutate(m);expect(()=>r2.validateR2Manifest(m)).toThrow();});
  it('rejects PNG replacement on use, including coherent wrong file dimensions',()=>{
    const bytes=PNG.sync.write(image());
    expect(()=>r2.verifyR2PNG({sha256:'a'.repeat(64),dimensions:[2,2]},bytes)).toThrow();
    const sha256=createHash('sha256').update(bytes).digest('hex');
    expect(()=>r2.verifyR2PNG({sha256,dimensions:[3,2]},bytes)).toThrow('R2_REFERENCE_DIMENSION_MISMATCH');
  });
  it('refuses source/cache substitution and verifies every imported PNG, including pending states',async()=>{
    const root=await mkdtemp(resolve(tmpdir(),'nyay50-loader-test-'));
    const sha=bytes=>createHash('sha256').update(bytes).digest('hex');
    try{
      expect(await r2.loadR2(root,null)).toBe(null);
      for(const cache of ['../outside','..','.','/absolute'])await expect(r2.loadR2(root,{cache,manifestSha256:'a'.repeat(64)})).rejects.toThrow('R2_INVALID_CACHE_BINDING');
      const source=resolve(root,r2.R2_SOURCE_PATH);await mkdir(dirname(source),{recursive:true});await writeFile(source,'tampered');
      const config={cache:'test-r2',manifestSha256:'a'.repeat(64)};
      await expect(r2.loadR2(root,config)).rejects.toThrow('R2_SOURCE_BYTES_MISMATCH');
      const repository=resolve(dirname(fileURLToPath(import.meta.url)),'../../..');
      await writeFile(source,await readFile(resolve(repository,r2.R2_SOURCE_PATH)));
      const cache=resolve(root,'frontend/test-baselines/nyay66/test-r2');await mkdir(cache,{recursive:true});
      const m=manifest();
      const images=new Map(r2.R2_VIEWPORTS.map(v=>[v.id,PNG.sync.write(new PNG({width:v.width,height:v.height,fill:true}))]));
      for(const row of m.rows){const bytes=images.get(row.viewport);row.sha256=sha(bytes);await writeFile(resolve(cache,row.file),bytes);}
      const json=JSON.stringify(m);await writeFile(resolve(cache,'manifest.json'),json);
      await expect(r2.loadR2(root,config)).rejects.toThrow('R2_MANIFEST_BYTES_MISMATCH');config.manifestSha256=sha(json);
      expect((await r2.loadR2(root,config)).manifest.rows).toHaveLength(42);
      const pending=m.rows.find(row=>row.view==='s06-success');await writeFile(resolve(cache,pending.file),'changed');
      await expect(r2.loadR2(root,config)).rejects.toThrow('R2_REFERENCE_BYTES_MISMATCH');
    }finally{await rm(root,{recursive:true,force:true});}
  });
  it('refuses unimplemented recovery and unknown fixtures instead of manufacturing coverage',async()=>{
    for(const state of ['s06-success','s99-other'])await expect(r2.mockR2Application({},state,'http://localhost',[])).rejects.toThrow('R2_LIVE_STATE_NOT_IMPLEMENTED');
  });
  it('captures the real S-01 unavailable path from a malformed synthetic session response',async()=>{
    let handler;const visits=[],waits=[];
    const page={route:async(_,fn)=>{handler=fn;},goto:async path=>visits.push(path),locator:selector=>({waitFor:async()=>waits.push(selector)}),getByRole:(role,options)=>({waitFor:async()=>waits.push([role,options])})};
    const evidence=await r2.mockR2Application(page,'s01-error','http://localhost',[]);
    let response;await handler({request:()=>({url:()=> 'http://localhost/api/v1/auth/student/session'}),fulfill:async value=>{response=value;}});
    expect(response.status).toBe(200);expect(JSON.parse(response.body)).toEqual({invalid:'synthetic-session-projection'});
    expect(visits).toEqual(['http://localhost/s-01']);expect(waits).toContainEqual(['heading',{name:'We could not reach NyayOne.',exact:true}]);
    expect(evidence).toEqual({evidenceKind:'live-route'});
  });
  it('separates resolved component visuals from an executed automatic production redirect',async()=>{
    let handler;const actions=[];
    const page={route:async(_,fn)=>{handler=fn;},goto:async path=>actions.push(['goto',path]),waitForURL:async path=>actions.push(['url',path]),locator:selector=>({waitFor:async options=>actions.push(['locator',selector,options])}),getByText:(text,options)=>({waitFor:async()=>actions.push(['text',text,options])})};
    const evidence=await r2.mockR2Application(page,'s01-resolved','http://localhost',[]);
    let response;await handler({request:()=>({url:()=> 'http://localhost/api/v1/auth/student/session'}),fulfill:async value=>{response=value;}});
    expect(JSON.parse(response.body).authenticated).toBe(true);
    expect(actions.slice(0,3)).toEqual([['goto','http://localhost/s-01'],['url','**/s-07'],['locator','[data-screen="S-01"]',{state:'detached'}]]);
    expect(actions[3]).toEqual(['goto','http://localhost/__nyay66-components/scripts/nyay66-s01-component.html']);
    expect(evidence).toEqual({evidenceKind:'component-visual',coverageApproval:'NYAY-77:15493',liveRouteBehavior:{executed:true,from:'/s-01',to:'/s-07',syntheticServer:true,artificialDelay:false,navigationFrozen:false}});
    // No evaluate/addInitScript/clock methods: navigation must not be suppressed.
  });
  it('cannot capture the resolved component when the live redirect fails',async()=>{
    const visits=[];
    const page={route:async()=>{},goto:async path=>visits.push(path),waitForURL:async()=>{throw Error('REDIRECT_FAILED');}};
    await expect(r2.mockR2Application(page,'s01-resolved','http://localhost',[])).rejects.toThrow('REDIRECT_FAILED');
    expect(visits).toEqual(['http://localhost/s-01']);
  });
  it('does not manufacture success when the resolved component build is absent',async()=>{
    const page={route:async()=>{},goto:async()=>{},waitForURL:async()=>{},locator:selector=>({waitFor:async()=>{if(selector.includes('component-only'))throw Error('COMPONENT_MISSING');}})};
    await expect(r2.mockR2Application(page,'s01-resolved','http://localhost',[])).rejects.toThrow('COMPONENT_MISSING');
  });
  it('builds the actual resolved component only in isolated CI, never the normal production entry',async()=>{
    const repository=resolve(dirname(fileURLToPath(import.meta.url)),'../../..');
    const text=path=>readFile(resolve(repository,path),'utf8');
    const fixture=await text('frontend/scripts/nyay66-s01-component.tsx');
    expect(fixture).toContain("import { S01R2 } from '../src/features/student/auth/S01R2'");
    expect(fixture).toContain('phase="authenticated"');expect(fixture).not.toContain('setTimeout');expect(fixture).not.toContain('dangerouslySetInnerHTML');
    // The trusted evaluator export deliberately excludes candidate app files.
    // Normal-build output exclusion is additionally checked in the build rehearsal.
    expect(JSON.parse(await text('frontend/package.json')).scripts.build).not.toContain('nyay66-s01-component');
    const workflow=await text('.github/workflows/nyay66-conformance.yml');
    const container=workflow.split('      - name: Build candidate in a credential-free disposable container\n')[1].split('      - name:')[0];
    expect(container).toContain('npm run build; if [ -f scripts/nyay66-s01-component-build.mjs ]; then node scripts/nyay66-s01-component-build.mjs; fi;');
    for(const rail of ['--read-only','--cap-drop ALL','--security-opt no-new-privileges','dst=/input,readonly','dst=/dependencies,readonly'])expect(container).toContain(rail);
    expect(container).not.toContain('GH_TOKEN');
    const evaluator=await text('frontend/scripts/nyay66-live.mjs');
    expect(evaluator).toContain('component visual (not a stable live-route capture)');
    expect(evaluator).toContain('Object.assign(row,await mockR2Application');
  });
  it('blocks cross-origin and unmatched requests in pending splash fixtures',async()=>{
    let handler;const page={route:async(_,fn)=>{handler=fn;},goto:async()=>{},locator:()=>({waitFor:async()=>{}})};
    const errors=[];await r2.mockR2Application(page,'s01-checking','http://localhost',errors);
    let aborted=0,continued=0;
    const route=url=>({request:()=>({url:()=>url}),abort:()=>{aborted++;},continue:()=>{continued++;}});
    handler(route('http://outside/api/v1/auth/student/session'));
    handler(route('http://localhost/api/v1/unexpected'));
    handler(route('http://localhost/api/v1/auth/student/session'));
    handler(route('http://localhost/asset.js'));
    expect(errors).toEqual(['OUTBOUND_REQUEST','UNMATCHED_API']);expect(aborted).toBe(2);expect(continued).toBe(1);
  });
});
const report = () => ({
  sourceSha256: SOURCE_SHA256, head: 'a'.repeat(40), purpose: 'REFERENCE_CALIBRATION_ONLY',
  rows: VIEWS.flatMap(view => VIEWPORTS.map(viewport => ({
    view, viewport: viewport.id, executed: true, sampleHashes: ['b'.repeat(64), 'b'.repeat(64), 'b'.repeat(64)],
    dimensions: [viewport.width, viewport.height], runtimeErrors: 0, blockedRequests: 0,
    deltas: [{ meanAbsDiff: 0, mismatchRatio: 0 }, { meanAbsDiff: 0, mismatchRatio: 0 }],
  }))),
});

describe('NYAY-66 calibration integrity', () => {
  it('covers 17 canonical routes plus popup without inventing gap references', () => {
    expect(VIEWS).toHaveLength(15);
    expect(coverage()).toHaveLength(18);
    expect(coverage().filter(row => row.status === 'DESIGN-GAP').map(row => row.screen)).toEqual(['S-01', 'S-02', 'S-06']);
    expect(coverage().find(row => row.screen === 'S-10').views).toEqual(['s10a', 's10b']);
    expect(coverage().find(row => row.screen === 'S-07-popup').views).toEqual(['s14p']);
    expect(coverage('dark').every(row => row.status === 'DESIGN-GAP')).toBe(true);
  });
  it('accepts complete executed calibration, never calling it application parity', () => {
    expect(validateCalibration(report())).toEqual([]);
    expect(coverage().some(row => row.status === 'PARITY')).toBe(false);
  });
  for (const [name, mutate] of [
    ['source mismatch', r => { r.sourceSha256 = '0'.repeat(64); }],
    ['invalid head', r => { r.head = 'main'; }],
    ['missing panel', r => r.rows.pop()],
    ['duplicate panel', r => { r.rows[1] = r.rows[0]; }],
    ['unknown view', r => { r.rows[0].view = 's01'; }],
    ['unexecuted row', r => { r.rows[0].executed = false; }],
    ['empty capture hash', r => { r.rows[0].sampleHashes[0] = ''; }],
    ['missing sample', r => r.rows[0].sampleHashes.pop()],
    ['missing comparison', r => r.rows[0].deltas.pop()],
    ['wrong dimensions', r => { r.rows[0].dimensions[0] = 1; }],
    ['runtime error', r => { r.rows[0].runtimeErrors = 1; }],
    ['outbound request', r => { r.rows[0].blockedRequests = 1; }],
    ['boolean count', r => { r.rows[0].runtimeErrors = false; }],
    ['NaN metric', r => { r.rows[0].deltas[0].meanAbsDiff = NaN; }],
    ['negative metric', r => { r.rows[0].deltas[0].mismatchRatio = -1; }],
    ['oversized ratio', r => { r.rows[0].deltas[0].mismatchRatio = 2; }],
    ['parity mislabelling', r => { r.purpose = 'LIVE_PARITY'; }],
  ]) it(`refuses ${name}`, () => {
    const value = report(); mutate(value); expect(validateCalibration(value).length).toBeGreaterThan(0);
  });
  it('computes exact RGB difference and detects a single changed pixel', () => {
    const a = image(), b = image(); b.data[0] = 255;
    expect(comparePixels(a, a)).toEqual({ meanAbsDiff: 0, mismatchRatio: 0 });
    expect(comparePixels(a, b)).toEqual({ meanAbsDiff: 21.25, mismatchRatio: 0.25 });
  });
  it('rejects size mismatch rather than resize the oracle', () => {
    expect(() => comparePixels(image(), new PNG({ width: 3, height: 2 }))).toThrow('DIMENSION_MISMATCH');
  });
});

describe('NYAY-66 progressive verdicts', () => {
  const good = { reference: true, executed: true, pixels: true, structure: true, accessibility: true };
  it('cannot enforce without numeric owner approval', () => {
    expect(() => classifyObservation(good, { enforced: true, toleranceApproval: null })).toThrow('TOLERANCE_APPROVAL_REQUIRED');
  });
  it('does not mark a design gap as pass', () => {
    expect(classifyObservation({ ...good, reference: false }, {})).toEqual({ verdict: 'DESIGN-GAP', blocking: false });
  });
  it('reports pending calibration without claiming parity', () => {
    expect(classifyObservation(good, {})).toEqual({ verdict: 'CALIBRATION-PENDING', blocking: false });
  });
  it('blocks a regression in an enforced screen', () => {
    expect(classifyObservation({ ...good, pixels: false }, { enforced: true, toleranceApproval: 'owner:15380' })).toEqual({ verdict: 'REGRESSION', blocking: true });
  });
  it('reports unfixed screens without masking them as successful evidence', () => {
    expect(classifyObservation({ ...good, pixels: false }, { toleranceApproval: 'owner:15380' })).toEqual({ verdict: 'NONCONFORMANT', blocking: false });
  });
  for (const field of ['executed', 'pixels', 'structure', 'accessibility']) {
    it(`cannot pass an absent ${field} proof`, () => {
      const row = { ...good }; delete row[field];
      expect(classifyObservation(row, { enforced: true, toleranceApproval: 'owner:15380' }).blocking).toBe(true);
    });
  }
});
