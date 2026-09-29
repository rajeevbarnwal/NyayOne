import {before,after,it} from 'node:test';
import assert from 'node:assert/strict';
import {preview} from 'vite';
import {chromium} from 'playwright';
import {mkdir,writeFile,readFile,mkdtemp,rm} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import {resolve} from 'node:path';
import {createRequire} from 'node:module';
import {mockS18Application,classifyS18Errors} from './nyay66-s18-fixtures.mjs';
import {S18_STATES,S18_VIEWPORTS} from './nyay66-s18-reference.mjs';
import {loadS18Source} from './nyay66-s18-reference.mjs';
import {loadS18Cache} from './nyay66-s18-import.mjs';
import {captureS18Rows} from './nyay66-s18-live.mjs';
import {finalizeEnforcement} from './nyay66-enforcement.mjs';
const require=createRequire(import.meta.url);
let server,browser,origin;
before(async()=>{server=await preview({preview:{host:'127.0.0.1',port:0,strictPort:false},logLevel:'error'});origin=`http://127.0.0.1:${server.httpServer.address().port}`;browser=await chromium.launch();});
after(async()=>{await browser?.close();await new Promise(done=>server?.httpServer.close(done));});
for(const state of S18_STATES)for(const vp of S18_VIEWPORTS)it(`S-18 ${state} ${vp.id} truthful live-route fixture`,{timeout:40_000},async()=>{
  const context=await browser.newContext({viewport:{width:vp.width,height:vp.height},locale:'en-IN',timezoneId:'Asia/Kolkata',reducedMotion:'reduce'});
  const page=await context.newPage(),errors=[],consoleErrors=[],httpResponses=[];page.setDefaultTimeout(10_000);
  const failed=()=>errors.push('NETWORK_ERROR');page.on('requestfailed',failed);
  page.on('pageerror',()=>errors.push('PAGE_ERROR'));page.on('console',m=>{if(m.type()==='error')consoleErrors.push({text:m.text(),url:m.location().url});});
  page.on('response',r=>{if(r.status()>=400)httpResponses.push({method:r.request().method(),url:r.url(),status:r.status()});});
  try{
    const evidence=await mockS18Application(page,state,origin,errors);
    await page.evaluate(async()=>{await document.fonts.ready;await Promise.all([...document.images].map(i=>i.decode()));});
    assert.deepEqual(errors,[]);
    const diagnostics=classifyS18Errors(state,origin,consoleErrors,httpResponses,evidence.expectedHttpErrors);
    assert.deepEqual(diagnostics.errors,[]);
    if(state==='session'){assert.equal(evidence.evidenceKind,'component-visual');assert.equal(evidence.coverageApproval,'NYAY-88:16029');assert.deepEqual(evidence.liveRouteBehavior,{executed:true,from:'/s-18',to:'/s-03',syntheticServer:true,artificialDelay:false,navigationFrozen:false});}
    else{assert.equal(await page.locator('[data-screen="S-18"]').getAttribute('data-settings-state'),state);}
    await page.addScriptTag({content:await readFile(require.resolve('axe-core/axe.min.js'),'utf8')});
    const accessibility=await page.evaluate(async()=> (await window.axe.run(document)).violations.map(v=>({id:v.id,impact:v.impact,nodes:v.nodes.length})));
    assert.deepEqual(accessibility.filter(v=>['serious','critical'].includes(v.impact)),[]);
    if(process.env.NYAY88_FIXTURE_DIAGNOSTIC){
      const dir=process.env.NYAY88_FIXTURE_DIAGNOSTIC;await mkdir(dir,{recursive:true});
      await writeFile(resolve(dir,`s18-${state}-${vp.id}.json`),JSON.stringify({limitation:'Local macOS synthetic fixture diagnostic, not hosted conformance',evidence,diagnostics,accessibility},null,2)+'\n');
      await page.screenshot({path:resolve(dir,`s18-${state}-${vp.id}.png`),animations:'disabled'});
    }
  }finally{page.off('requestfailed',failed);await context.close();}
});
it('all 18 rows execute the additive measurement producer; local output is diagnostic, not hosted conformance',{timeout:120_000},async()=>{
  const root=resolve('..'),policy=JSON.parse(await readFile('scripts/nyay66-policy.json'));
  const control=JSON.parse(await readFile(resolve('test-baselines/nyay66',policy.cache,'manifest.json'))),{data}=await loadS18Source(root);
  const reference=await loadS18Cache(root,policy.s18,data,control.fonts);
  const out=await mkdtemp(resolve(tmpdir(),'nyay88-s18-measurement-test-'));
  try{
    const rows=await captureS18Rows({browser,origin,out,reference});
    assert.equal(rows.length,18);
    assert.deepEqual(rows.filter(r=>!r.executed||!r.measured||r.errors.length).map(r=>({state:r.state,viewport:r.viewport,failure:r.failure,errors:r.errors})),[]);
    assert.equal(rows.filter(r=>r.evidenceKind==='component-visual').length,2);
    const evaluated=finalizeEnforcement(rows,{enforced:[],exceptions:[]},[],{r2:true,s18:true});
    assert.equal(evaluated.blocking,false);assert.equal(evaluated.rows.some(r=>r.verdict==='CAPTURE-FAILED'),false);
    if(process.env.NYAY88_FIXTURE_DIAGNOSTIC)await writeFile(resolve(process.env.NYAY88_FIXTURE_DIAGNOSTIC,'measurement-diagnostic.json'),JSON.stringify({limitation:'Local macOS versus hosted references; NOT a hosted conformance verdict or exception proposal',rows:evaluated.rows.map(r=>({state:r.state,viewport:r.viewport,evidenceKind:r.evidenceKind,metrics:r.metrics,structure:r.structure,accessibility:r.accessibility}))},null,2)+'\n');
  }finally{await rm(out,{recursive:true,force:true});}
});
