// Developer producer tests only: synthetic APIs and local Chromium, not hosted parity or independent QA.
import {before,after,it} from 'node:test';
import assert from 'node:assert/strict';
import {preview} from 'vite';
import {chromium} from 'playwright';
import {readFile,mkdtemp,mkdir,writeFile} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import {resolve} from 'node:path';
import {mockS30Application,classifyS30Errors,verifyS30Requests,S30_PATHS} from './nyay66-s30-fixtures.mjs';
import {S30_STATES,S30_VIEWPORTS} from './nyay66-s30-reference.mjs';
import {loadContinuation} from './nyay66-continuation.mjs';
import {loadS30Cache} from './nyay66-s30-import.mjs';
import {captureS30Rows} from './nyay66-s30-live.mjs';
import {finalizeEnforcement} from './nyay66-enforcement.mjs';
let server,browser,origin;
before(async()=>{server=await preview({preview:{host:'127.0.0.1',port:0,strictPort:false},logLevel:'error'});origin=`http://127.0.0.1:${server.httpServer.address().port}`;browser=await chromium.launch();});
after(async()=>{await browser?.close();await new Promise(done=>server?.httpServer.close(done));});
for(const state of S30_STATES)for(const vp of S30_VIEWPORTS)it(`${state} ${vp.id}: actual route, independent lists and confirmed membership`,{timeout:30_000},async()=>{
  const context=await browser.newContext({viewport:{width:vp.width,height:vp.height},locale:'en-IN',timezoneId:'Asia/Kolkata',reducedMotion:'reduce',serviceWorkers:'block'});
  const page=await context.newPage();page.setDefaultTimeout(7000);
  const errors=[],messages=[],responses=[],failed=[];
  const onFailed=r=>failed.push({method:r.method(),url:r.url(),errorText:r.failure()?.errorText});
  page.on('requestfailed',onFailed);page.on('pageerror',()=>errors.push('PAGE_ERROR'));
  page.on('console',m=>{if(m.type()==='error')messages.push({url:m.location().url,text:m.text()});});
  page.on('response',r=>{if(r.status()>=400)responses.push({method:r.request().method(),url:r.url(),status:r.status()});});
  try{
    const proof=await mockS30Application(page,state,origin,errors);
    assert.deepEqual(errors,[]);assert.deepEqual(classifyS30Errors(state,origin,messages,responses,failed,proof.expectedHttpErrors).errors,[]);
    assert.equal(verifyS30Requests(state,proof.apiRequests),true);assert.equal(proof.evidenceKind,'live-route');
    assert.equal(proof.syntheticServer,true);assert.equal(proof.navigationFrozen,false);assert.equal(proof.artificialDelay,false);
    assert.equal(page.url(),origin+'/s-30');assert.equal(proof.routeProof.requestSequenceVerified,true);
    assert.equal(proof.routeProof.serverConfirmationVerified,true);assert.equal(proof.routeProof.membershipVerified,true);
    const snapshot=proof.membershipProof;
    if(state==='loading'){assert.equal(proof.pendingResponses.length,2);assert.equal(snapshot.cards.length,0);assert.equal(snapshot.announcement,'');}
    if(state==='item-pending'){
      assert.equal(proof.pendingResponses[0].method,'DELETE');assert.equal(snapshot.cards.length,2);
      assert.equal(snapshot.removals[0].busy,'true');assert.equal(snapshot.announcement,'');
      await page.locator('[data-s30-remove]').first().press('Enter');
      assert.equal(proof.apiRequests.filter(r=>r.method==='DELETE').length,1,'pending activation cannot submit twice');
    }
    if(state==='item-error'){
      assert.equal(snapshot.cards.length,2);assert.match(snapshot.alert,/last known list/);assert.equal(snapshot.focusRole,'alert');
      await page.locator('[data-s30-remove]').first().press('Enter');
      assert.equal(proof.apiRequests.filter(r=>r.method==='DELETE').length,1,'uncertain mutation remains reload-gated');
    }
    if(state==='error'){
      assert.equal(snapshot.http,'HTTP 500');assert.equal(snapshot.focusRole,'alert');
      await page.getByRole('tab',{name:'Following (2)',exact:true}).click();
      assert.equal(await page.locator('[data-s30-remove]').count(),2,'other list remains independently available');
      assert.equal(proof.apiRequests.filter(r=>r.path===S30_PATHS.followed).length,1);
    }
    if(state==='both'){
      const saved=page.getByRole('tab',{name:'Saved (2)',exact:true});await saved.focus();await saved.press('ArrowRight');
      assert.equal(await page.getByRole('tab',{name:'Following (2)',exact:true}).getAttribute('aria-selected'),'true');
      assert.equal(await page.getByText('Update notifications: on',{exact:true}).count(),1);
      assert.equal(await page.getByText('Update notifications: off',{exact:true}).count(),1);
      assert.equal(proof.apiRequests.length,3,'tab switch must not infer or mutate membership');
    }
    assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),true);
  }finally{page.off('requestfailed',onFailed);await context.close();}
});
it('16 measured rows, two cold captures, exact reproducibility and missing/tampered reference rejection',{timeout:600_000},async()=>{
  const root=resolve('..'),policy=JSON.parse(await readFile('scripts/nyay66-policy.json'));
  const control=JSON.parse(await readFile(resolve('test-baselines/nyay66',policy.cache,'manifest.json')));
  const reference=await loadS30Cache(root,policy.s30,await loadContinuation(root),control.fonts);
  const out=await mkdtemp(resolve(tmpdir(),'nyay99-s30-product-capture-test-'));
  console.log(`S-30 local diagnostic captures (not hosted parity): ${out}`);
  const dirs=['first','second','tampered','missing'].map(n=>resolve(out,n));await Promise.all(dirs.map(d=>mkdir(d)));
  const failures=rs=>rs.filter(r=>!r.executed||!r.measured||r.errors.length).map(r=>({state:r.state,viewport:r.viewport,failure:r.failure,errors:r.errors,diagnostics:r.consoleDiagnostics}));
  const first=await captureS30Rows({browser,origin,out:dirs[0],reference});await writeFile(resolve(out,'first-results.json'),JSON.stringify(first,null,2));assert.equal(first.length,16);assert.deepEqual(failures(first),[]);
  assert(first.every(r=>r.evidenceKind==='live-route'&&r.syntheticServer));
  const result=finalizeEnforcement(first,{enforced:[],exceptions:[]},[],{r2:true,s18:true,s19:true,s20:true,s21:true,s25:true,s26:true,s27:true,s28:true,s29:true,s30:true});
  assert.deepEqual(result.failures,[]);assert(result.rows.every(r=>r.verdict!=='CAPTURE-FAILED'&&r.exceptionsApplied.length===0));
  for(const r of result.rows)if(r.accessibility.some(v=>['serious','critical'].includes(v.impact)))assert.equal(r.verdict,'NONCONFORMANT');
  const second=await captureS30Rows({browser,origin,out:dirs[1],reference});await writeFile(resolve(out,'second-results.json'),JSON.stringify(second,null,2));assert.deepEqual(failures(second),[]);
  const identities=rs=>rs.map(r=>({state:r.state,viewport:r.viewport,liveSha256:r.liveSha256,surface:r.liveSurface}));
  assert.deepEqual(identities(first),identities(second),'Compare cold captures; never select by an approval hash');
  const tampered={...reference,manifest:{...reference.manifest,rows:reference.manifest.rows.map(r=>({...r,sha256:'0'.repeat(64)}))}};
  const rejected=await captureS30Rows({browser,origin,out:dirs[2],reference:tampered});
  assert(rejected.every(r=>r.verdict==='CAPTURE-FAILED'&&!r.measured&&r.failure==='S30_REFERENCE_BYTES_MISMATCH'));
  const missing=await captureS30Rows({browser,origin,out:dirs[3],reference:{...reference,manifest:{...reference.manifest,rows:[]}}});
  assert(missing.every(r=>r.verdict==='CAPTURE-FAILED'&&!r.measured&&r.failure==='S30_REFERENCE_MISSING'));
});
