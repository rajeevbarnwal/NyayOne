// Local presentation regressions against frozen source; not hosted parity or QA.
import {before,after,it} from 'node:test';
import assert from 'node:assert/strict';
import http from 'node:http';
import {preview} from 'vite';
import {chromium} from 'playwright';
import {loadS34Source,S34_VIEWPORTS} from './lib/nyay66-s34-reference.mjs';
import {captureS34Sample} from './lib/nyay66-s34-capture.mjs';
import {mockS34Application} from './lib/nyay66-s34-fixtures.mjs';
let browser,reference,live,referenceOrigin,liveOrigin;
before(async()=>{const {html}=await loadS34Source(process.cwd()+'/..');reference=http.createServer((q,r)=>{r.setHeader('content-type','text/html');r.end(html)});await new Promise(r=>reference.listen(0,'127.0.0.1',r));referenceOrigin=`http://127.0.0.1:${reference.address().port}`;live=await preview({preview:{host:'127.0.0.1',port:0},logLevel:'error'});liveOrigin=`http://127.0.0.1:${live.httpServer.address().port}`;browser=await chromium.launch()});
after(async()=>{await browser?.close();await new Promise(r=>reference?.close(r));await new Promise(r=>live?.httpServer.close(r))});
function inspect(){
 const css=(e,keys)=>e?Object.fromEntries(keys.map(k=>[k,getComputedStyle(e)[k]])):null;
 const shape=e=>e?[...e.children].map(c=>({tag:c.tagName,attrs:[...c.attributes].map(a=>[a.name,a.value]).sort(),children:shape(c)})):null;
 const rect=e=>{const b=e.getBoundingClientRect();return {width:b.width,height:b.height}};
 const notice=document.querySelector('.note,.s34-notice'),chip=document.querySelector('.chip,.s34-chip'),facts=document.querySelector('.kvs,.s34-facts');
 const primary=[...document.querySelectorAll('main button,main a')].filter(e=>['Manage session','My sessions'].includes(e.textContent.trim())).at(-1);
 return {notice:{shape:shape(notice?.querySelector(':scope > svg')),title:css(notice?.querySelector('b,h2'),['color','fontSize','fontWeight','lineHeight']),border:css(notice,['borderLeftColor','borderRadius','padding','gap'])},
 chip:{box:rect(chip),styles:css(chip,['backgroundColor','color','borderColor','padding','gap']),dot:css(chip?.querySelector('.d,.s34-dot'),['width','height','backgroundColor','borderRadius','transform'])},
 facts:css(facts,['backgroundColor','borderColor','borderWidth','borderRadius','padding']),code:css(document.querySelector('main .mono,.s34-code'),['fontSize','fontWeight','color','fontFamily']),primary:rect(primary)};
}
for(const state of ['confirmed','pending-provider','cancelled'])for(const vp of S34_VIEWPORTS)it(`S34 frozen presentation ${state} ${vp.id}`,async()=>{
 const c=await browser.newContext({viewport:{width:vp.width,height:vp.height},locale:'en-IN',timezoneId:'Asia/Kolkata'}),p=await c.newPage();
 try{await captureS34Sample(p,referenceOrigin,state,vp);const f=await(await p.locator('iframe[data-src="cont"]').elementHandle()).contentFrame(),expected=await f.evaluate(inspect);await mockS34Application(p,state,liveOrigin,[]);const actual=await p.evaluate(inspect),errors=[];
 for(const key of ['notice','chip','facts','code','primary'])try{assert.deepEqual(actual[key],expected[key])}catch(e){errors.push(key+': '+e.message)}
 assert.equal(await p.getByRole('button',{name:'Refresh session',exact:true}).count(),1);
 for(const e of await p.locator('main a:visible,main button:visible').all())assert.ok((await e.boundingBox()).height>=48);
 assert.equal(await p.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),true);
 if(errors.length)throw Error(errors.join('\n'));
 }finally{await c.close()}
});
