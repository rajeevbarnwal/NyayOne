// Real Chromium + synthetic APIs. Local runs are diagnostics, not hosted parity.
import {before,after,it} from 'node:test';
import assert from 'node:assert/strict';
import {preview} from 'vite';
import {chromium} from 'playwright';
import {readFile,mkdtemp,rm,mkdir} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import {resolve} from 'node:path';
import {mockS21Application,classifyS21Errors,verifyS21Requests} from './nyay66-s21-fixtures.mjs';
import {S21_STATES,S21_VIEWPORTS} from './nyay66-s21-reference.mjs';
import {loadContinuation} from './nyay66-continuation.mjs';
import {loadS21Cache} from './nyay66-s21-import.mjs';
import {captureS21Rows} from './nyay66-s21-live.mjs';
import {finalizeEnforcement} from './nyay66-enforcement.mjs';
let server,browser,origin;
before(async()=>{server=await preview({preview:{host:'127.0.0.1',port:0,strictPort:false},logLevel:'error'});origin=`http://127.0.0.1:${server.httpServer.address().port}`;browser=await chromium.launch();});
after(async()=>{await browser?.close();await new Promise(done=>server?.httpServer.close(done));});
for(const state of S21_STATES)for(const vp of S21_VIEWPORTS)it(`${state} ${vp.id}: live route, genuine actions, exact API diagnostics`,{timeout:30_000},async()=>{
  const context=await browser.newContext({viewport:{width:vp.width,height:vp.height},locale:'en-IN',timezoneId:'Asia/Kolkata',reducedMotion:'reduce',serviceWorkers:'block'});
  const page=await context.newPage();page.setDefaultTimeout(7000);
  const errors=[],messages=[],responses=[],failed=[];
  const onFailed=r=>failed.push({method:r.method(),url:r.url(),errorText:r.failure()?.errorText});
  page.on('requestfailed',onFailed);page.on('pageerror',()=>errors.push('PAGE_ERROR'));
  page.on('console',m=>{if(m.type()==='error')messages.push({url:m.location().url,text:m.text()});});
  page.on('response',r=>{if(r.status()>=400)responses.push({method:r.request().method(),url:r.url(),status:r.status()});});
  try{
    const proof=await mockS21Application(page,state,origin,errors);
    assert.deepEqual(errors,[]);assert.deepEqual(classifyS21Errors(state,origin,messages,responses,failed,proof.expectedHttpErrors).errors,[]);
    assert.equal(verifyS21Requests(state,proof.apiRequests),true);assert.equal(proof.evidenceKind,'live-route');
    assert.equal(proof.syntheticServer,true);assert.equal(proof.navigationFrozen,false);assert.equal(proof.artificialDelay,false);
    assert.equal(new URL(page.url()).pathname,'/s-21');assert.equal(new URL(page.url()).search,'?listing=arbitration-intern');
    if(!['loading','missing','error'].includes(state))assert.equal(await page.getByRole('button',{name:'Apply',exact:true}).getAttribute('aria-disabled'),'true');
    if(state==='save-pending'){
      assert.equal(proof.pendingResponse.method,'PUT');assert.equal(await page.getByRole('button',{name:'Saving',exact:true}).getAttribute('aria-busy'),'true');
      assert.equal(await page.getByText('Saved privately to your account.',{exact:false}).count(),0);
    }
    if(state==='saved')assert.equal(await page.getByRole('button',{name:'Saved',exact:true}).getAttribute('aria-pressed'),'true');
    if(state==='session'){
      assert.equal(proof.sessionInvalidation.observedAnonymous,true);assert.equal(proof.sessionInvalidation.responseCode,'authentication_required');
      assert.equal(await page.getByRole('button',{name:'Sign in again',exact:true}).count(),1);
    }
    assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),true);
  }finally{page.off('requestfailed',onFailed);await context.close();}
});
it('16 measured rows, two cold runs, raw-image reproducibility and tampered-reference rejection',{timeout:300_000},async()=>{
  const root=resolve('..'),policy=JSON.parse(await readFile('scripts/nyay66-policy.json'));
  const control=JSON.parse(await readFile(resolve('test-baselines/nyay66',policy.cache,'manifest.json')));
  const reference=await loadS21Cache(root,policy.s21,await loadContinuation(root),control.fonts);
  const out=await mkdtemp(resolve(tmpdir(),'nyay93-s21-product-capture-test-'));
  let passed=false;
  try{
    const dirs=['first','second','tampered'].map(name=>resolve(out,name));await Promise.all(dirs.map(dir=>mkdir(dir)));
    const first=await captureS21Rows({browser,origin,out:dirs[0],reference});assert.equal(first.length,16);
    const failures=rs=>rs.filter(r=>!r.executed||!r.measured||r.errors.length).map(r=>({state:r.state,viewport:r.viewport,failure:r.failure,errors:r.errors,diagnostics:r.consoleDiagnostics}));
    assert.deepEqual(failures(first),[]);
    assert.equal(first.every(r=>r.evidenceKind==='live-route'&&r.syntheticServer),true);
    assert.equal(first.every(r=>!r.accessibility.some(v=>['serious','critical'].includes(v.impact))),true);
    const result=finalizeEnforcement(first,{enforced:[],exceptions:[]},[],{r2:true,s18:true,s19:true,s20:true,s21:true});
    assert.deepEqual(result.failures,[]);assert.equal(result.rows.some(r=>r.verdict==='CAPTURE-FAILED'),false);
    assert.equal(result.rows.every(r=>r.exceptionsApplied.length===0),true);
    const second=await captureS21Rows({browser,origin,out:dirs[1],reference});assert.deepEqual(failures(second),[]);
    const identities=rs=>rs.map(r=>({state:r.state,viewport:r.viewport,liveSha256:r.liveSha256,surface:r.liveSurface}));
    const mismatches=identities(first).flatMap((row,i)=>JSON.stringify(row)===JSON.stringify(identities(second)[i])?[]:[{state:row.state,viewport:row.viewport,first:row.liveSha256,second:second[i].liveSha256,surfaceEqual:JSON.stringify(row.surface)===JSON.stringify(second[i].liveSurface)}]);
    assert.deepEqual(mismatches,[],'Compare independent cold captures; never select by an approval hash');
    const tampered={...reference,manifest:{...reference.manifest,rows:reference.manifest.rows.map(r=>({...r,sha256:'0'.repeat(64)}))}};
    const rejected=await captureS21Rows({browser,origin,out:dirs[2],reference:tampered});
    assert.equal(rejected.every(r=>r.verdict==='CAPTURE-FAILED'&&!r.measured&&r.failure==='S21_REFERENCE_BYTES_MISMATCH'),true);
    passed=true;
  }finally{if(passed)await rm(out,{recursive:true,force:true});else console.error(`S-21 local diagnostic captures retained at ${out}`);}
});
