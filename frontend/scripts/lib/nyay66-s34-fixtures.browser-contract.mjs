// Local synthetic producer regression; not hosted conformance or independent QA.
import {before,after,it} from 'node:test';
import assert from 'node:assert/strict';
import {preview} from 'vite';
import {chromium} from 'playwright';
import {readFile,mkdtemp,mkdir,writeFile} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import {resolve} from 'node:path';
import {mockS34Application,classifyS34Errors,verifyS34Requests,frameS34Viewport} from './nyay66-s34-fixtures.mjs';
import {S34_STATES,S34_VIEWPORTS} from './nyay66-s34-reference.mjs';
import {loadContinuation} from './nyay66-continuation.mjs';
import {loadS34Cache} from './nyay66-s34-import.mjs';
import {captureS34Rows} from './nyay66-s34-live.mjs';
import {finalizeEnforcement} from './nyay66-enforcement.mjs';
let server,browser,origin;
before(async()=>{server=await preview({preview:{host:'127.0.0.1',port:0,strictPort:false},logLevel:'error'});origin=`http://127.0.0.1:${server.httpServer.address().port}`;browser=await chromium.launch();});
after(async()=>{await browser?.close();await new Promise(done=>server?.httpServer.close(done));});
for(const state of S34_STATES)for(const vp of S34_VIEWPORTS)it(`${state} ${vp.id}: genuine requests and server authority`,{timeout:30_000},async()=>{
 const context=await browser.newContext({viewport:{width:vp.width,height:vp.height},locale:'en-IN',timezoneId:'Asia/Kolkata',reducedMotion:'reduce',serviceWorkers:'block'}),page=await context.newPage();page.setDefaultTimeout(7000);
 const errors=[],messages=[],responses=[],failed=[];
 const onFailed=r=>failed.push({method:r.method(),url:r.url(),errorText:r.failure()?.errorText});
 page.on('requestfailed',onFailed);page.on('pageerror',()=>errors.push('PAGE_ERROR'));page.on('console',m=>{if(m.type()==='error')messages.push({url:m.location().url,text:m.text()});});page.on('response',r=>{if(r.status()>=400)responses.push({method:r.request().method(),url:r.url(),status:r.status()});});
 try{
  const proof=await mockS34Application(page,state,origin,errors);assert.deepEqual(errors,[]);assert.deepEqual(classifyS34Errors(state,origin,messages,responses,failed,proof.expectedHttpErrors).errors,[]);
  assert(verifyS34Requests(state,proof.apiRequests));assert.equal(proof.evidenceKind,'live-route');assert(proof.syntheticServer);assert.equal(proof.navigationFrozen,false);assert.equal(proof.artificialDelay,false);
  for(const flag of ['requestSequenceVerified','serverConfirmationVerified','sessionIdentityVerified','noInventedPaymentOrJoin'])assert.equal(proof.routeProof[flag],true);
  assert.equal(new URL(page.url()).pathname,'/s-34');assert.deepEqual(proof.sessionProof.scroll,[0,0]);assert(proof.viewportFraming.focusPreserved);assert.equal(proof.viewportFraming.domModified,false);
  assert.equal(proof.pendingResponses.length,state==='loading'?1:0);
  assert.equal(proof.sessionProof.manage,state==='confirmed'?`/s-35?session=${proof.sessionProof.id}&view=detail`:null);
  if(['missing','error'].includes(state)){assert.equal(responses[0].status,state==='missing'?404:503);assert.equal(proof.sessionProof.focusRole,'alert');}

 }finally{page.off('requestfailed',onFailed);await context.close();}
});
it('camera preserves DOM, focus, route and request history',async()=>{
 const context=await browser.newContext({viewport:{width:390,height:844},timezoneId:'Asia/Kolkata'}),page=await context.newPage();
 try{const p=await mockS34Application(page,'confirmed',origin,[]),html=await page.locator('.s34-session').evaluate(e=>e.outerHTML),url=page.url(),requests=JSON.stringify(p.apiRequests);await page.evaluate(()=>window.scrollTo(0,document.documentElement.scrollHeight));const f=await frameS34Viewport(page,'confirmed');assert(f.focusPreserved);assert.deepEqual(f.after,[0,0]);assert.equal(await page.locator('.s34-session').evaluate(e=>e.outerHTML),html);assert.equal(page.url(),url);assert.equal(JSON.stringify(p.apiRequests),requests);await page.setContent('<main>Unrelated</main>');await assert.rejects(frameS34Viewport(page,'confirmed'),/S34_FRAME_SCOPE/);}finally{await context.close();}
});
it('12 rows, two cold captures; missing/tampered references fail closed',{timeout:600_000},async()=>{
 const root=resolve('..'),policy=JSON.parse(await readFile('scripts/nyay66-policy.json')),control=JSON.parse(await readFile(resolve('test-baselines/nyay66',policy.cache,'manifest.json'))),reference=await loadS34Cache(root,policy.s34,await loadContinuation(root),control.fonts);
 const out=await mkdtemp(resolve(tmpdir(),'nyay103-s34-product-capture-test-'));console.log(`S-34 local diagnostics (not hosted parity): ${out}`);const dirs=['first','second','tampered','missing'].map(n=>resolve(out,n));await Promise.all(dirs.map(d=>mkdir(d)));
 const failures=rs=>rs.filter(r=>!r.executed||!r.measured||r.errors.length).map(r=>({state:r.state,viewport:r.viewport,failure:r.failure,errors:r.errors,diagnostics:r.consoleDiagnostics}));
 const first=await captureS34Rows({browser,origin,out:dirs[0],reference});await writeFile(resolve(out,'first-results.json'),JSON.stringify(first,null,2));assert.equal(first.length,12);assert.deepEqual(failures(first),[]);
 const result=finalizeEnforcement(first,{enforced:[],exceptions:[]},[],{s34:true});assert.deepEqual(result.failures,[]);assert(result.rows.every(r=>r.verdict!=='CAPTURE-FAILED'&&r.exceptionsApplied.length===0));
 for(const r of result.rows)if(r.accessibility.some(v=>['serious','critical'].includes(v.impact)))assert.equal(r.verdict,'NONCONFORMANT');
 const second=await captureS34Rows({browser,origin,out:dirs[1],reference});await writeFile(resolve(out,'second-results.json'),JSON.stringify(second,null,2));assert.deepEqual(failures(second),[]);
 const identities=rs=>rs.map(r=>({state:r.state,viewport:r.viewport,liveSha256:r.liveSha256,surface:r.liveSurface}));assert.deepEqual(identities(first),identities(second),'No selection by approval hash');
 const tampered={...reference,manifest:{...reference.manifest,rows:reference.manifest.rows.map(r=>({...r,sha256:'0'.repeat(64)}))}},rejected=await captureS34Rows({browser,origin,out:dirs[2],reference:tampered});assert(rejected.every(r=>r.verdict==='CAPTURE-FAILED'&&!r.measured&&r.failure==='S34_REFERENCE_BYTES_MISMATCH'));
 const missing=await captureS34Rows({browser,origin,out:dirs[3],reference:{...reference,manifest:{...reference.manifest,rows:[]}}});assert(missing.every(r=>r.verdict==='CAPTURE-FAILED'&&!r.measured&&r.failure==='S34_REFERENCE_MISSING'));
});
