// Real Chromium + synthetic APIs. Local diagnostics are not hosted parity or independent QA.
import {before,after,it} from 'node:test';
import assert from 'node:assert/strict';
import {preview} from 'vite';
import {chromium} from 'playwright';
import {readFile,mkdtemp,mkdir,writeFile} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import {resolve} from 'node:path';
import {mockS28Application,classifyS28Errors,verifyS28Requests,S28_ROUTE} from './nyay66-s28-fixtures.mjs';
import {S28_STATES,S28_VIEWPORTS} from './nyay66-s28-reference.mjs';
import {loadContinuation} from './nyay66-continuation.mjs';
import {loadS28Cache} from './nyay66-s28-import.mjs';
import {captureS28Rows} from './nyay66-s28-live.mjs';
import {finalizeEnforcement} from './nyay66-enforcement.mjs';
let server,browser,origin;
before(async()=>{server=await preview({preview:{host:'127.0.0.1',port:0,strictPort:false},logLevel:'error'});origin=`http://127.0.0.1:${server.httpServer.address().port}`;browser=await chromium.launch();});
after(async()=>{await browser?.close();await new Promise(done=>server?.httpServer.close(done));});
for(const state of S28_STATES)for(const vp of S28_VIEWPORTS)it(`${state} ${vp.id}: genuine route, exact API diagnostics and confirmation semantics`,{timeout:30_000},async()=>{
  const context=await browser.newContext({viewport:{width:vp.width,height:vp.height},locale:'en-IN',timezoneId:'Asia/Kolkata',reducedMotion:'reduce',serviceWorkers:'block'});
  const page=await context.newPage();page.setDefaultTimeout(7000);
  const errors=[],messages=[],responses=[],failed=[];
  const onFailed=r=>failed.push({method:r.method(),url:r.url(),errorText:r.failure()?.errorText});
  page.on('requestfailed',onFailed);page.on('pageerror',()=>errors.push('PAGE_ERROR'));
  page.on('console',m=>{if(m.type()==='error')messages.push({url:m.location().url,text:m.text()});});
  page.on('response',r=>{if(r.status()>=400)responses.push({method:r.request().method(),url:r.url(),status:r.status()});});
  try{
    const proof=await mockS28Application(page,state,origin,errors);
    assert.deepEqual(errors,[]);assert.deepEqual(classifyS28Errors(state,origin,messages,responses,failed,proof.expectedHttpErrors).errors,[]);
    assert.equal(verifyS28Requests(state,proof.apiRequests),true);assert.equal(proof.evidenceKind,'live-route');
    assert.equal(proof.syntheticServer,true);assert.equal(proof.navigationFrozen,false);assert.equal(proof.artificialDelay,false);
    assert.equal(page.url(),origin+S28_ROUTE);assert.equal(proof.routeProof.requestSequenceVerified,true);assert.equal(proof.routeProof.serverConfirmationVerified,true);
    if(state==='loading')assert.equal(proof.pendingResponse.method,'GET');
    if(state==='save-pending'){
      assert.equal(proof.pendingResponse.method,'PUT');assert.equal(proof.detailProof.save.pressed,'false');
      assert.equal(proof.detailProof.save.busy,'true');assert.equal(proof.detailProof.announcement,'');
      assert.equal(proof.apiRequests.filter(r=>r.method==='PUT').length,1);
    }
    if(state==='following'){
      assert.equal(proof.followConfirmation.noSuccessBeforeResponse,true);
      assert.equal(proof.detailProof.follow.pressed,'true');assert.equal(proof.detailProof.notification.checked,false);
      assert.deepEqual(proof.apiRequests.at(-1).body,{notify_opt_in:false});
    }
    if(['complete','save-pending','follow-error'].includes(state)){
      assert.equal(proof.detailProof.notification,null);
      assert.equal(proof.detailProof.unknownNotification,true);
    }
    if(['missing','error','follow-error'].includes(state)){
      assert.equal(await page.evaluate(()=>document.activeElement?.getAttribute('role')),'alert');
      if(state!=='follow-error')assert.equal(await page.getByText(`HTTP ${state==='missing'?404:500}`,{exact:true}).count(),1);
      else {assert.equal(proof.detailProof.follow.pressed,'true');assert.equal(proof.detailProof.follow.disabled,'true');assert.equal(proof.detailProof.announcement,'');}
    }
    assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),true);
  }finally{page.off('requestfailed',onFailed);await context.close();}
});
it('14 measured rows, two cold captures, exact reproducibility and reference tamper rejection',{timeout:600_000},async()=>{
  const root=resolve('..'),policy=JSON.parse(await readFile('scripts/nyay66-policy.json'));
  const control=JSON.parse(await readFile(resolve('test-baselines/nyay66',policy.cache,'manifest.json')));
  const reference=await loadS28Cache(root,policy.s28,await loadContinuation(root),control.fonts);
  const out=await mkdtemp(resolve(tmpdir(),'nyay97-s28-product-capture-test-'));
  console.log(`S-28 local diagnostic captures (not hosted parity): ${out}`);
  const dirs=['first','second','tampered','missing'].map(n=>resolve(out,n));await Promise.all(dirs.map(d=>mkdir(d)));
  const failures=rs=>rs.filter(r=>!r.executed||!r.measured||r.errors.length).map(r=>({state:r.state,viewport:r.viewport,failure:r.failure,errors:r.errors,diagnostics:r.consoleDiagnostics}));
  const first=await captureS28Rows({browser,origin,out:dirs[0],reference});await writeFile(resolve(out,'first-results.json'),JSON.stringify(first,null,2));assert.equal(first.length,14);assert.deepEqual(failures(first),[]);
  assert(first.every(r=>r.evidenceKind==='live-route'&&r.syntheticServer));
  const result=finalizeEnforcement(first,{enforced:[],exceptions:[]},[],{r2:true,s18:true,s19:true,s20:true,s21:true,s25:true,s26:true,s27:true,s28:true});
  assert.deepEqual(result.failures,[]);assert(result.rows.every(r=>r.verdict!=='CAPTURE-FAILED'&&r.exceptionsApplied.length===0));
  // This verifies the producer, not visual approval: genuine measured defects
  // remain NONCONFORMANT under the unchanged evaluator and are never waived.
  for(const r of result.rows)if(r.accessibility.some(v=>['serious','critical'].includes(v.impact)))assert.equal(r.verdict,'NONCONFORMANT');
  const second=await captureS28Rows({browser,origin,out:dirs[1],reference});await writeFile(resolve(out,'second-results.json'),JSON.stringify(second,null,2));assert.deepEqual(failures(second),[]);
  const identities=rs=>rs.map(r=>({state:r.state,viewport:r.viewport,liveSha256:r.liveSha256,surface:r.liveSurface}));
  assert.deepEqual(identities(first),identities(second),'Compare cold captures; never select by an approval hash');
  const tampered={...reference,manifest:{...reference.manifest,rows:reference.manifest.rows.map(r=>({...r,sha256:'0'.repeat(64)}))}};
  const rejected=await captureS28Rows({browser,origin,out:dirs[2],reference:tampered});
  assert(rejected.every(r=>r.verdict==='CAPTURE-FAILED'&&!r.measured&&r.failure==='S28_REFERENCE_BYTES_MISMATCH'));
  const missing=await captureS28Rows({browser,origin,out:dirs[3],reference:{...reference,manifest:{...reference.manifest,rows:[]}}});
  assert(missing.every(r=>r.verdict==='CAPTURE-FAILED'&&!r.measured&&r.failure==='S28_REFERENCE_MISSING'));
});
