// Local synthetic producer regression; not hosted conformance or independent QA.
import {before,after,it} from 'node:test';
import assert from 'node:assert/strict';
import {preview} from 'vite';
import {chromium} from 'playwright';
import {readFile,mkdtemp,mkdir,writeFile} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import {resolve} from 'node:path';
import {mockS35Application,classifyS35Errors,verifyS35Requests} from './nyay66-s35-fixtures.mjs';
import {S35_STATES,S35_VIEWPORTS} from './nyay66-s35-reference.mjs';
import {loadContinuation} from './nyay66-continuation.mjs';
import {loadS35Cache} from './nyay66-s35-import.mjs';
import {captureS35Rows} from './nyay66-s35-live.mjs';
import {finalizeEnforcement} from './nyay66-enforcement.mjs';
let server,browser,origin;
before(async()=>{server=await preview({preview:{host:'127.0.0.1',port:0,strictPort:false},logLevel:'error'});origin=`http://127.0.0.1:${server.httpServer.address().port}`;browser=await chromium.launch();});
after(async()=>{await browser?.close();await new Promise(done=>server?.httpServer.close(done));});
for(const state of S35_STATES)for(const vp of S35_VIEWPORTS)it(`${state} ${vp.id}: genuine requests and server authority`,{timeout:30_000},async()=>{
 const context=await browser.newContext({viewport:{width:vp.width,height:vp.height},locale:'en-IN',timezoneId:'Asia/Kolkata',reducedMotion:'reduce',serviceWorkers:'block'}),page=await context.newPage();page.setDefaultTimeout(7000);
 const errors=[],messages=[],responses=[],failed=[];
 const onFailed=r=>failed.push({method:r.method(),url:r.url(),errorText:r.failure()?.errorText});
 page.on('requestfailed',onFailed);page.on('pageerror',()=>errors.push('PAGE_ERROR'));page.on('console',m=>{if(m.type()==='error')messages.push({url:m.location().url,text:m.text()});});page.on('response',r=>{if(r.status()>=400)responses.push({method:r.request().method(),url:r.url(),status:r.status()});});
 try{
  const proof=await mockS35Application(page,state,origin,errors);assert.deepEqual(errors,[]);assert.deepEqual(classifyS35Errors(state,origin,messages,responses,failed,proof.expectedHttpErrors).errors,[]);
  assert(verifyS35Requests(state,proof.apiRequests));assert(['live-route','live-capability-gap','live-route-destination'].includes(proof.evidenceKind));assert(proof.syntheticServer);assert.equal(proof.navigationFrozen,false);assert.equal(proof.artificialDelay,false);
  assert.equal(proof.realBackendTested,false);assert.equal(proof.realMediaProviderTested,false);
  assert(proof.routeProof.requestSequenceVerified);assert(proof.routeProof.responseScenarioVerified);assert(proof.viewportFraming.focusPreserved);

 }catch(e){console.log(JSON.stringify({state,viewport:vp.id,errors,messages,responses,failed,text:(await page.locator('body').innerText()).slice(-5000)}));throw e;}finally{page.off('requestfailed',onFailed);await context.close();}
});
it('112 rows, two cold captures; missing/tampered references fail closed',{timeout:1_800_000},async()=>{
 const root=resolve('..'),policy=JSON.parse(await readFile('scripts/nyay66-policy.json')),control=JSON.parse(await readFile(resolve('test-baselines/nyay66',policy.cache,'manifest.json'))),reference=await loadS35Cache(root,policy.s35,await loadContinuation(root),control.fonts);
 const out=await mkdtemp(resolve(process.env.NYAY66_DIAGNOSTIC_ROOT||tmpdir(),'nyay104-s35-product-capture-test-'));console.log(`S-35 local diagnostics (not hosted parity): ${out}`);const dirs=['first','second','tampered','missing'].map(n=>resolve(out,n));await Promise.all(dirs.map(d=>mkdir(d)));
 const failures=rs=>rs.filter(r=>!r.executed||!r.measured||r.errors.length).map(r=>({state:r.state,viewport:r.viewport,failure:r.failure,errors:r.errors,diagnostics:r.consoleDiagnostics}));
 const first=await captureS35Rows({browser,origin,out:dirs[0],reference});await writeFile(resolve(out,'first-results.json'),JSON.stringify(first,null,2));assert.equal(first.length,112);assert.deepEqual(failures(first),[]);
 const result=finalizeEnforcement(first,{enforced:[],exceptions:[]},[],{s35:true});assert.deepEqual(result.failures,[]);assert(result.rows.every(r=>r.verdict!=='CAPTURE-FAILED'&&r.exceptionsApplied.length===0));
 for(const r of result.rows)if(r.accessibility.some(v=>['serious','critical'].includes(v.impact)))assert.equal(r.verdict,'NONCONFORMANT');
 const second=await captureS35Rows({browser,origin,out:dirs[1],reference});await writeFile(resolve(out,'second-results.json'),JSON.stringify(second,null,2));assert.deepEqual(failures(second),[]);
 const identities=rs=>rs.map(r=>({state:r.state,viewport:r.viewport,liveSha256:r.liveSha256,surface:r.liveSurface}));assert.deepEqual(identities(first),identities(second),'No selection by approval hash');
 const tampered={...reference,manifest:{...reference.manifest,rows:reference.manifest.rows.map(r=>({...r,sha256:'0'.repeat(64)}))}},rejected=await captureS35Rows({browser,origin,out:dirs[2],reference:tampered});assert(rejected.every(r=>r.verdict==='CAPTURE-FAILED'&&!r.measured&&r.failure==='S35_REFERENCE_BYTES_MISMATCH'));
 const missing=await captureS35Rows({browser,origin,out:dirs[3],reference:{...reference,manifest:{...reference.manifest,rows:[]}}});assert(missing.every(r=>r.verdict==='CAPTURE-FAILED'&&!r.measured&&r.failure==='S35_REFERENCE_MISSING'));
});
