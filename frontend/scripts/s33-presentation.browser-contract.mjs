// Developer presentation regression against the immutable approved prototype.
// This does not import images, change gate verdicts, or claim independent QA.
import {before,after,it} from 'node:test';
import assert from 'node:assert/strict';
import http from 'node:http';
import {preview} from 'vite';
import {chromium} from 'playwright';
import {loadS33Source,S33_VIEWPORTS} from './lib/nyay66-s33-reference.mjs';
import {captureS33Sample} from './lib/nyay66-s33-capture.mjs';
import {mockS33Application} from './lib/nyay66-s33-fixtures.mjs';
let browser,reference,live,referenceOrigin,liveOrigin;
before(async()=>{const {html}=await loadS33Source(process.cwd()+'/..');reference=http.createServer((q,r)=>{r.setHeader('content-type','text/html');r.end(html);});await new Promise(r=>reference.listen(0,'127.0.0.1',r));referenceOrigin=`http://127.0.0.1:${reference.address().port}`;live=await preview({preview:{host:'127.0.0.1',port:0},logLevel:'error'});liveOrigin=`http://127.0.0.1:${live.httpServer.address().port}`;browser=await chromium.launch();});
after(async()=>{await browser?.close();await new Promise(r=>reference?.close(r));await new Promise(r=>live?.httpServer.close(r));});
function inspect(){
 const shape=e=>e?[...e.children].map(c=>({tag:c.tagName,attrs:[...c.attributes].map(a=>[a.name,a.value]).sort(),children:shape(c)})):null;
 const h=document.querySelector('h1'),notice=document.querySelector('.note,.s33-notice'),buttons=[...document.querySelectorAll('main button,main a')];
 const typography=e=>e?Object.fromEntries(['fontSize','fontWeight','lineHeight','color','letterSpacing'].map(k=>[k,getComputedStyle(e)[k]])):null;
 const rect=e=>{const b=e?.getBoundingClientRect();return b?{width:b.width,height:b.height}:null;};
 return {heading:{shape:shape(h?.querySelector('svg')),size:h?.querySelector('svg')?.getAttribute('width'),height:rect(h)?.height},
 back:rect(buttons.find(e=>e.textContent.trim()==='Mentor')),
 actions:buttons.map(e=>({text:e.textContent.trim(),shape:shape(e.querySelector('svg')),width:rect(e)?.width,height:rect(e)?.height})),
 amount:typography(document.querySelector('.amt,.s33-amount')),code:typography(document.querySelector('main .mono,.s33-summary .s20-code')),
 notice:notice?{shape:shape(notice.querySelector(':scope > svg')),border:getComputedStyle(notice).borderLeftColor}:null,
 chip:!!document.querySelector('.chip.w .d,.s33-held .s33-held-dot')};
}
for(const state of ['hold-creating','hold-active','slot-conflict','hold-expired','order-pending','payment-failed','creating-session','payment-unverified','confirmed','rate-limited','network','hold-60min','hold-other-mentor'])for(const vp of S33_VIEWPORTS)it(`S33 presentation ${state} ${vp.id}`,async()=>{
 const c=await browser.newContext({viewport:{width:vp.width,height:vp.height},locale:'en-IN',timezoneId:'Asia/Kolkata'}),p=await c.newPage();
 p.on('pageerror',e=>console.error(e));
 try{await captureS33Sample(p,referenceOrigin,state,vp);const f=await (await p.locator('iframe[data-src="cont"]').elementHandle()).contentFrame(),expected=await f.evaluate(inspect);const captureErrors=[];try{await mockS33Application(p,state,liveOrigin,captureErrors);}catch(e){console.error({state,captureErrors,text:await p.locator('body').innerText()});throw e;}const actual=await p.evaluate(inspect),errors=[];
 const check=(label,fn)=>{try{fn();}catch(e){errors.push(new Error(label+': '+e.message));}};
 check('heading primitive and baseline',()=>assert.deepEqual(actual.heading,expected.heading));
 check('amount typography',()=>assert.deepEqual(actual.amount,expected.amount));
 check('booking IDs typography',()=>assert.deepEqual(actual.code,expected.code));
 check('back-link geometry',()=>assert.deepEqual(actual.back,expected.back));
 check('notice icon and semantic color',()=>assert.deepEqual(actual.notice,expected.notice));
 if(expected.chip)check('held status diamond',()=>assert.equal(actual.chip,true));
 for(const a of actual.actions){
  const counterpart=expected.actions.find(e=>e.text===a.text)||(a.text==='Create payment order'?expected.actions.find(e=>e.text==='Pay with the payment provider'):null);
  if(counterpart)check(a.text+' icon',()=>assert.deepEqual(a.shape,counterpart.shape));
  check(a.text+' touch target',()=>assert.ok(a.height>=48));
  if(a.text==='Create payment order')check('payment action full width',()=>assert.equal(a.width,counterpart.width));
 }
 assert.equal(await p.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),true);
 if(errors.length)throw new AggregateError(errors,errors.map(e=>e.message).join('\n'));
 }finally{await c.close();}
});
