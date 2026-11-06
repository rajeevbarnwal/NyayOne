// Local synthetic producer regression; not hosted conformance or independent QA.
import {before,after,it} from 'node:test';
import assert from 'node:assert/strict';
import {preview} from 'vite';
import {chromium} from 'playwright';
import {readFile,mkdtemp,mkdir,writeFile} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import {resolve} from 'node:path';
import {mockS33Application,classifyS33Errors,verifyS33Requests,frameS33Viewport} from './nyay66-s33-fixtures.mjs';
import {S33_STATES,S33_VIEWPORTS} from './nyay66-s33-reference.mjs';
import {loadContinuation} from './nyay66-continuation.mjs';
import {loadS33Cache} from './nyay66-s33-import.mjs';
import {captureS33Rows} from './nyay66-s33-live.mjs';
import {finalizeEnforcement} from './nyay66-enforcement.mjs';
let server,browser,origin;
before(async()=>{server=await preview({preview:{host:'127.0.0.1',port:0,strictPort:false},logLevel:'error'});origin=`http://127.0.0.1:${server.httpServer.address().port}`;browser=await chromium.launch();});
after(async()=>{await browser?.close();await new Promise(done=>server?.httpServer.close(done));});
for(const state of S33_STATES)for(const vp of S33_VIEWPORTS)it(`${state} ${vp.id}: genuine requests and server authority`,{timeout:30_000},async()=>{
 const context=await browser.newContext({viewport:{width:vp.width,height:vp.height},locale:'en-IN',timezoneId:'Asia/Kolkata',reducedMotion:'reduce',serviceWorkers:'block'}),page=await context.newPage();page.setDefaultTimeout(7000);
 const errors=[],messages=[],responses=[],failed=[];
 const onFailed=r=>failed.push({method:r.method(),url:r.url(),errorText:r.failure()?.errorText});
 page.on('requestfailed',onFailed);page.on('pageerror',()=>errors.push('PAGE_ERROR'));page.on('console',m=>{if(m.type()==='error')messages.push({url:m.location().url,text:m.text()});});page.on('response',r=>{if(r.status()>=400)responses.push({method:r.request().method(),url:r.url(),status:r.status()});});
 try{
  const proof=await mockS33Application(page,state,origin,errors);assert.deepEqual(errors,[]);assert.deepEqual(classifyS33Errors(state,origin,messages,responses,failed,proof.expectedHttpErrors).errors,[]);
  assert(verifyS33Requests(state,proof.apiRequests));assert.equal(proof.evidenceKind,state==='session'?'live-redirect-destination':'live-route');assert(proof.syntheticServer);assert.equal(proof.navigationFrozen,false);assert.equal(proof.artificialDelay,false);
  for(const flag of ['requestSequenceVerified','serverConfirmationVerified','holdAuthorityVerified','paymentAuthorityVerified'])assert.equal(proof.routeProof[flag],true);
  assert.equal(new URL(page.url()).pathname,state==='session'?'/s-03':'/s-33');const s=proof.bookingProof;assert.deepEqual(s.scroll,[0,0]);assert(proof.viewportFraming.focusPreserved);assert.equal(proof.viewportFraming.domModified,false);
  assert.equal(proof.pendingResponses.length,['hold-creating','creating-session'].includes(state)?1:0);assert.equal(!!s.confirmed,state==='confirmed');
  if(state==='hold-60min')assert.equal(s.facts[2],'60 min');if(state==='hold-other-mentor')assert.equal(s.facts[0],'Adv. Arjun Menon');
  if(state==='payment-unverified')assert.equal(responses[0].status,400);if(state==='session'){assert(proof.routeProof.sessionCleared);assert.equal(proof.routeProof.httpStatus,401);assert.equal(s.bookingVisible,false);}
  if(state==='rate-limited')assert.equal(s.retryDisabled,'true');if(state==='hold-expired')assert.equal(proof.apiRequests.at(-1).method,'GET');
 }finally{page.off('requestfailed',onFailed);await context.close();}
});
it('camera preserves DOM, focus, route and request history',async()=>{
 const context=await browser.newContext({viewport:{width:390,height:844},timezoneId:'Asia/Kolkata'}),page=await context.newPage();
 try{const p=await mockS33Application(page,'hold-active',origin,[]),html=await page.locator('.s33-booking').evaluate(e=>e.outerHTML),url=page.url(),requests=JSON.stringify(p.apiRequests);await page.evaluate(()=>window.scrollTo(0,document.documentElement.scrollHeight));const f=await frameS33Viewport(page,'hold-active');assert(f.focusPreserved);assert.deepEqual(f.after,[0,0]);assert.equal(await page.locator('.s33-booking').evaluate(e=>e.outerHTML),html);assert.equal(page.url(),url);assert.equal(JSON.stringify(p.apiRequests),requests);await page.setContent('<main>Unrelated</main>');await assert.rejects(frameS33Viewport(page,'hold-active'),/S33_FRAME_SCOPE/);}finally{await context.close();}
});
it('28 rows, two cold captures; missing/tampered references fail closed',{timeout:600_000},async()=>{
 const root=resolve('..'),policy=JSON.parse(await readFile('scripts/nyay66-policy.json')),control=JSON.parse(await readFile(resolve('test-baselines/nyay66',policy.cache,'manifest.json'))),reference=await loadS33Cache(root,policy.s33,await loadContinuation(root),control.fonts);
 const out=await mkdtemp(resolve(tmpdir(),'nyay102-s33-product-capture-test-'));console.log(`S-33 local diagnostics (not hosted parity): ${out}`);const dirs=['first','second','tampered','missing'].map(n=>resolve(out,n));await Promise.all(dirs.map(d=>mkdir(d)));
 const failures=rs=>rs.filter(r=>!r.executed||!r.measured||r.errors.length).map(r=>({state:r.state,viewport:r.viewport,failure:r.failure,errors:r.errors,diagnostics:r.consoleDiagnostics}));
 const first=await captureS33Rows({browser,origin,out:dirs[0],reference});await writeFile(resolve(out,'first-results.json'),JSON.stringify(first,null,2));assert.equal(first.length,28);assert.deepEqual(failures(first),[]);
 const result=finalizeEnforcement(first,{enforced:[],exceptions:[]},[],{s33:true});assert.deepEqual(result.failures,[]);assert(result.rows.every(r=>r.verdict!=='CAPTURE-FAILED'&&r.exceptionsApplied.length===0));
 for(const r of result.rows)if(r.accessibility.some(v=>['serious','critical'].includes(v.impact)))assert.equal(r.verdict,'NONCONFORMANT');
 const second=await captureS33Rows({browser,origin,out:dirs[1],reference});await writeFile(resolve(out,'second-results.json'),JSON.stringify(second,null,2));assert.deepEqual(failures(second),[]);
 const identities=rs=>rs.map(r=>({state:r.state,viewport:r.viewport,liveSha256:r.liveSha256,surface:r.liveSurface}));assert.deepEqual(identities(first),identities(second),'No selection by approval hash');
 const tampered={...reference,manifest:{...reference.manifest,rows:reference.manifest.rows.map(r=>({...r,sha256:'0'.repeat(64)}))}},rejected=await captureS33Rows({browser,origin,out:dirs[2],reference:tampered});assert(rejected.every(r=>r.verdict==='CAPTURE-FAILED'&&!r.measured&&r.failure==='S33_REFERENCE_BYTES_MISMATCH'));
 const missing=await captureS33Rows({browser,origin,out:dirs[3],reference:{...reference,manifest:{...reference.manifest,rows:[]}}});assert(missing.every(r=>r.verdict==='CAPTURE-FAILED'&&!r.measured&&r.failure==='S33_REFERENCE_MISSING'));
});
