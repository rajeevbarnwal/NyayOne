// Real Chromium + synthetic APIs. Local diagnostics are not hosted parity or independent QA.
import {before,after,it} from 'node:test';
import assert from 'node:assert/strict';
import {preview} from 'vite';
import {chromium} from 'playwright';
import {readFile,mkdtemp,mkdir,writeFile} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import {resolve} from 'node:path';
import {mockS29Application,classifyS29Errors,verifyS29Requests,s29Route,s29Ids} from './nyay66-s29-fixtures.mjs';
import {S29_STATES,S29_VIEWPORTS} from './nyay66-s29-reference.mjs';
import {loadContinuation} from './nyay66-continuation.mjs';
import {loadS29Cache} from './nyay66-s29-import.mjs';
import {captureS29Rows} from './nyay66-s29-live.mjs';
import {finalizeEnforcement} from './nyay66-enforcement.mjs';
let server,browser,origin;
before(async()=>{server=await preview({preview:{host:'127.0.0.1',port:0,strictPort:false},logLevel:'error'});origin=`http://127.0.0.1:${server.httpServer.address().port}`;browser=await chromium.launch();});
after(async()=>{await browser?.close();await new Promise(done=>server?.httpServer.close(done));});
for(const state of S29_STATES)for(const vp of S29_VIEWPORTS)it(`${state} ${vp.id}: genuine route, exact API and selection proof`,{timeout:30_000},async()=>{
  const context=await browser.newContext({viewport:{width:vp.width,height:vp.height},locale:'en-IN',timezoneId:'Asia/Kolkata',reducedMotion:'reduce',serviceWorkers:'block'});
  const page=await context.newPage();page.setDefaultTimeout(7000);
  const errors=[],messages=[],responses=[],failed=[];
  const onFailed=r=>failed.push({method:r.method(),url:r.url(),errorText:r.failure()?.errorText});
  page.on('requestfailed',onFailed);page.on('pageerror',()=>errors.push('PAGE_ERROR'));
  page.on('console',m=>{if(m.type()==='error')messages.push({url:m.location().url,text:m.text()});});
  page.on('response',r=>{if(r.status()>=400)responses.push({method:r.request().method(),url:r.url(),status:r.status()});});
  try{
    const proof=await mockS29Application(page,state,origin,errors);
    assert.deepEqual(errors,[]);assert.deepEqual(classifyS29Errors(state,origin,messages,responses,failed,proof.expectedHttpErrors).errors,[]);
    assert.equal(verifyS29Requests(state,proof.apiRequests),true);assert.equal(proof.evidenceKind,'live-route');
    assert.equal(proof.syntheticServer,true);assert.equal(proof.navigationFrozen,false);assert.equal(proof.artificialDelay,false);
    assert.equal(page.url(),origin+s29Route(state));assert.equal(proof.routeProof.requestSequenceVerified,true);
    assert.equal(proof.routeProof.serverConfirmationVerified,true);assert.equal(proof.routeProof.selectionVerified,true);
    if(state==='loading'){assert.equal(proof.pendingResponse.method,'POST');assert.equal(proof.comparisonProof.tables,0);assert.equal(proof.comparisonProof.comparisonId,null);}
    if(state==='too-few'){
      assert.equal(proof.comparisonProof.tables,0);assert.equal(proof.comparisonProof.http,'');assert.equal(proof.apiRequests.length,1);
      assert.match(proof.coverageLimitation,/client-side minimum/);assert.equal(proof.comparisonProof.focusRole,'alert');
    }
    if(state==='error'){assert.equal(proof.comparisonProof.http,'HTTP 500');assert.equal(proof.comparisonProof.errorCode,'http_500');assert.equal(proof.comparisonProof.focusRole,'alert');}
    if(['complete','three','incomplete'].includes(state)){
      assert.deepEqual(proof.apiRequests[1].body,{school_ids:s29Ids(state)});assert.equal(proof.comparisonProof.differencesOnly,'false');
      if(state==='three'&&vp.id==='mobile390'){
        assert.equal(await page.getByRole('radio').count(),3);const before=proof.apiRequests.length;
        await page.getByRole('radio').nth(0).focus();await page.getByRole('radio').nth(0).press('ArrowRight');
        assert.equal(await page.getByRole('radio').nth(1).isChecked(),true);assert.equal(proof.apiRequests.length,before);
        assert.equal(new URL(page.url()).searchParams.get('ids'),s29Ids(state).join(','));
        assert.equal(await page.locator('thead').first().locator('a').count(),2);
      }
      if(state==='three'&&vp.id==='desktop')assert.equal(await page.locator('thead').first().locator('a').count(),3);
      if(state==='incomplete')assert.ok(proof.comparisonProof.notProvided>0);
    }
    assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),true);
  }finally{page.off('requestfailed',onFailed);await context.close();}
});
it('12 measured rows, two cold captures, exact reproducibility and reference tamper rejection',{timeout:600_000},async()=>{
  const root=resolve('..'),policy=JSON.parse(await readFile('scripts/nyay66-policy.json'));
  const control=JSON.parse(await readFile(resolve('test-baselines/nyay66',policy.cache,'manifest.json')));
  const reference=await loadS29Cache(root,policy.s29,await loadContinuation(root),control.fonts);
  const out=await mkdtemp(resolve(tmpdir(),'nyay98-s29-product-capture-test-'));
  console.log(`S-29 local diagnostic captures (not hosted parity): ${out}`);
  const dirs=['first','second','tampered','missing'].map(n=>resolve(out,n));await Promise.all(dirs.map(d=>mkdir(d)));
  const failures=rs=>rs.filter(r=>!r.executed||!r.measured||r.errors.length).map(r=>({state:r.state,viewport:r.viewport,failure:r.failure,errors:r.errors,diagnostics:r.consoleDiagnostics}));
  const first=await captureS29Rows({browser,origin,out:dirs[0],reference});await writeFile(resolve(out,'first-results.json'),JSON.stringify(first,null,2));assert.equal(first.length,12);assert.deepEqual(failures(first),[]);
  assert(first.every(r=>r.evidenceKind==='live-route'&&r.syntheticServer));
  const result=finalizeEnforcement(first,{enforced:[],exceptions:[]},[],{r2:true,s18:true,s19:true,s20:true,s21:true,s25:true,s26:true,s27:true,s28:true,s29:true});
  assert.deepEqual(result.failures,[]);assert(result.rows.every(r=>r.verdict!=='CAPTURE-FAILED'&&r.exceptionsApplied.length===0));
  // This verifies the producer, not visual approval: genuine measured defects
  // remain NONCONFORMANT under the unchanged evaluator and are never waived.
  for(const r of result.rows)if(r.accessibility.some(v=>['serious','critical'].includes(v.impact)))assert.equal(r.verdict,'NONCONFORMANT');
  const second=await captureS29Rows({browser,origin,out:dirs[1],reference});await writeFile(resolve(out,'second-results.json'),JSON.stringify(second,null,2));assert.deepEqual(failures(second),[]);
  const identities=rs=>rs.map(r=>({state:r.state,viewport:r.viewport,liveSha256:r.liveSha256,surface:r.liveSurface}));
  assert.deepEqual(identities(first),identities(second),'Compare cold captures; never select by an approval hash');
  const tampered={...reference,manifest:{...reference.manifest,rows:reference.manifest.rows.map(r=>({...r,sha256:'0'.repeat(64)}))}};
  const rejected=await captureS29Rows({browser,origin,out:dirs[2],reference:tampered});
  assert(rejected.every(r=>r.verdict==='CAPTURE-FAILED'&&!r.measured&&r.failure==='S29_REFERENCE_BYTES_MISMATCH'));
  const missing=await captureS29Rows({browser,origin,out:dirs[3],reference:{...reference,manifest:{...reference.manifest,rows:[]}}});
  assert(missing.every(r=>r.verdict==='CAPTURE-FAILED'&&!r.measured&&r.failure==='S29_REFERENCE_MISSING'));
});
