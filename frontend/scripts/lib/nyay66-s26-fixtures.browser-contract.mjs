// Real Chromium + synthetic APIs. Local results are diagnostics, not hosted parity.
import {before,after,it} from 'node:test';
import assert from 'node:assert/strict';
import {preview} from 'vite';
import {chromium} from 'playwright';
import {readFile,mkdtemp,mkdir} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import {resolve} from 'node:path';
import {mockS26Application,classifyS26Errors,verifyS26Requests} from './nyay66-s26-fixtures.mjs';
import {S26_STATES,S26_VIEWPORTS} from './nyay66-s26-reference.mjs';
import {loadContinuation} from './nyay66-continuation.mjs';
import {loadS26Cache} from './nyay66-s26-import.mjs';
import {captureS26Rows} from './nyay66-s26-live.mjs';
import {finalizeEnforcement} from './nyay66-enforcement.mjs';
let server,browser,origin;
before(async()=>{server=await preview({preview:{host:'127.0.0.1',port:0,strictPort:false},logLevel:'error'});origin=`http://127.0.0.1:${server.httpServer.address().port}`;browser=await chromium.launch();});
after(async()=>{await browser?.close();await new Promise(done=>server?.httpServer.close(done));});
for(const state of S26_STATES)for(const vp of S26_VIEWPORTS)it(`${state} ${vp.id}: genuine route/query and exact API diagnostics`,{timeout:30_000},async()=>{
  const context=await browser.newContext({viewport:{width:vp.width,height:vp.height},locale:'en-IN',timezoneId:'Asia/Kolkata',reducedMotion:'reduce',serviceWorkers:'block'});
  const page=await context.newPage();page.setDefaultTimeout(7000);
  const errors=[],messages=[],responses=[],failed=[];
  const onFailed=r=>failed.push({method:r.method(),url:r.url(),errorText:r.failure()?.errorText});
  page.on('requestfailed',onFailed);page.on('pageerror',()=>errors.push('PAGE_ERROR'));
  page.on('console',m=>{if(m.type()==='error')messages.push({url:m.location().url,text:m.text()});});
  page.on('response',r=>{if(r.status()>=400)responses.push({method:r.request().method(),url:r.url(),status:r.status()});});
  try{
    const proof=await mockS26Application(page,state,origin,errors);
    assert.deepEqual(errors,[]);assert.deepEqual(classifyS26Errors(state,origin,messages,responses,failed,proof.expectedHttpErrors).errors,[]);
    assert.equal(verifyS26Requests(state,proof.apiRequests),true);assert.equal(proof.evidenceKind,'live-route');
    assert.equal(proof.syntheticServer,true);assert.equal(proof.navigationFrozen,false);assert.equal(proof.artificialDelay,false);
    assert.equal(new URL(page.url()).pathname,'/s-26');assert.equal(new URL(page.url()).search,'');
    assert.equal(proof.routeProof.serverConfirmationVerified,true);
    assert.equal(await page.getByText('No saved internships yet.',{exact:true}).count(),state==='empty'?1:0);
    if(state==='loading')assert.equal(proof.pendingResponse.method,'GET');
    if(state==='error'){
      assert.equal(await page.getByText('HTTP 500',{exact:true}).count(),1);
      assert.equal(await page.evaluate(()=>document.activeElement?.getAttribute('role')),'alert');
    }
    assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),true);
  }finally{page.off('requestfailed',onFailed);await context.close();}
});
it('eight measured rows, two cold captures, exact reproducibility and reference tamper rejection',{timeout:300_000},async()=>{
  const root=resolve('..'),policy=JSON.parse(await readFile('scripts/nyay66-policy.json'));
  const control=JSON.parse(await readFile(resolve('test-baselines/nyay66',policy.cache,'manifest.json')));
  const reference=await loadS26Cache(root,policy.s26,await loadContinuation(root),control.fonts);
  const out=await mkdtemp(resolve(tmpdir(),'nyay95-s26-product-capture-test-'));
  console.log(`S-26 local diagnostic captures (not hosted parity): ${out}`);
  const dirs=['first','second','tampered','missing'].map(n=>resolve(out,n));await Promise.all(dirs.map(d=>mkdir(d)));
  const failures=rs=>rs.filter(r=>!r.executed||!r.measured||r.errors.length).map(r=>({state:r.state,viewport:r.viewport,failure:r.failure,errors:r.errors,diagnostics:r.consoleDiagnostics}));
  const first=await captureS26Rows({browser,origin,out:dirs[0],reference});assert.equal(first.length,8);assert.deepEqual(failures(first),[]);
  assert(first.every(r=>r.evidenceKind==='live-route'&&r.syntheticServer));
  assert(first.every(r=>!r.accessibility.some(v=>['serious','critical'].includes(v.impact))));
  const result=finalizeEnforcement(first,{enforced:[],exceptions:[]},[],{r2:true,s18:true,s19:true,s20:true,s21:true,s25:true,s26:true});
  assert.deepEqual(result.failures,[]);assert(result.rows.every(r=>r.verdict!=='CAPTURE-FAILED'&&r.exceptionsApplied.length===0));
  const second=await captureS26Rows({browser,origin,out:dirs[1],reference});assert.deepEqual(failures(second),[]);
  const identities=rs=>rs.map(r=>({state:r.state,viewport:r.viewport,liveSha256:r.liveSha256,surface:r.liveSurface}));
  assert.deepEqual(identities(first),identities(second),'Compare cold captures; never select by an approval hash');
  const tampered={...reference,manifest:{...reference.manifest,rows:reference.manifest.rows.map(r=>({...r,sha256:'0'.repeat(64)}))}};
  const rejected=await captureS26Rows({browser,origin,out:dirs[2],reference:tampered});
  assert(rejected.every(r=>r.verdict==='CAPTURE-FAILED'&&!r.measured&&r.failure==='S26_REFERENCE_BYTES_MISMATCH'));
  const missing=await captureS26Rows({browser,origin,out:dirs[3],reference:{...reference,manifest:{...reference.manifest,rows:[]}}});
  assert(missing.every(r=>r.verdict==='CAPTURE-FAILED'&&!r.measured&&r.failure==='S26_REFERENCE_MISSING'));
});
