// Local browser diagnostic, not pinned hosted conformance or independent QA.
import {before,after,it} from 'node:test';
import assert from 'node:assert/strict';
import {preview} from 'vite';
import {chromium} from 'playwright';
import {mkdir,readFile,writeFile,mkdtemp,rm} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import {resolve} from 'node:path';
import {S19_MEASURED_STATES} from './nyay66-s19-coverage.mjs';
import {S19_VIEWPORTS,loadS19Source} from './nyay66-s19-reference.mjs';
import {loadS19Cache} from './nyay66-s19-import.mjs';
import {captureS19Rows} from './nyay66-s19-live.mjs';
import {finalizeEnforcement} from './nyay66-enforcement.mjs';
let server,browser,origin;
before(async()=>{server=await preview({preview:{host:'127.0.0.1',port:0,strictPort:false},logLevel:'error'});origin=`http://127.0.0.1:${server.httpServer.address().port}`;browser=await chromium.launch();});
after(async()=>{await browser?.close();await new Promise(done=>server?.httpServer.close(done));});
it('all 50 S-19 rows execute actual product fixtures with honest source labels',{timeout:240_000},async()=>{
  const root=resolve('..'),policy=JSON.parse(await readFile('scripts/nyay66-policy.json'));
  const control=JSON.parse(await readFile(resolve('test-baselines/nyay66',policy.cache,'manifest.json'))),{data}=await loadS19Source(root);
  const reference=await loadS19Cache(root,policy.s19,data,control.fonts);
  const requested=process.env.NYAY91_FIXTURE_DIAGNOSTIC;
  const out=requested||await mkdtemp(resolve(tmpdir(),'nyay91-s19-measurement-test-'));
  if(requested)await mkdir(out,{recursive:true});
  try{
    const rows=await captureS19Rows({browser,origin,out,reference});
    if(requested)await writeFile(resolve(out,'measurement-diagnostic.json'),JSON.stringify({limitation:'Local macOS synthetic APIs versus hosted PNGs. Not a hosted conformance verdict or exception proposal.',rows},null,2)+'\n');
    assert.equal(rows.length,50);
    assert.deepEqual(rows.map(r=>`${r.designState}:${r.viewport}`),S19_MEASURED_STATES.flatMap(s=>S19_VIEWPORTS.map(v=>`${s}:${v.id}`)));
    assert.deepEqual(rows.filter(r=>!r.executed||!r.measured||r.errors.length).map(r=>({state:r.state,viewport:r.viewport,failure:r.failure,errors:r.errors})),[]);
    assert.equal(rows.filter(r=>r.evidenceKind==='component-visual').length,2);
    assert.equal(rows.filter(r=>r.evidenceKind==='live-redirect-destination').length,2);
    assert.equal(rows.filter(r=>r.evidenceKind==='live-route').length,46);
    for(const row of rows)for(const request of row.apiRequests||[])for(const field of ['mobile','code']){
      if(request.body?.[field]!==undefined)assert.equal(request.body[field],`[synthetic-${field}-redacted]`);
    }
    assert.deepEqual(rows.flatMap(r=>r.accessibility.filter(v=>['serious','critical'].includes(v.impact)).map(v=>({state:r.state,viewport:r.viewport,...v}))),[]);
    const evaluated=finalizeEnforcement(rows,{enforced:[],exceptions:[]},[],{r2:true,s18:true,s19:true});
    assert.equal(evaluated.blocking,false);assert.equal(evaluated.rows.some(r=>r.verdict==='CAPTURE-FAILED'),false);
  }finally{if(!requested)await rm(out,{recursive:true,force:true});}
});
