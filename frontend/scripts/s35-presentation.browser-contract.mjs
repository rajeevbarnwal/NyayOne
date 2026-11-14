// S-35-only developer regression evidence; synthetic browser/API, not independent QA.
import {before,after,it} from 'node:test';
import assert from 'node:assert/strict';
import {preview} from 'vite';
import {chromium} from 'playwright';
import {mockS35Application} from './lib/nyay66-s35-fixtures.mjs';
let server,browser,origin;
before(async()=>{server=await preview({preview:{host:'127.0.0.1',port:0},logLevel:'error'});origin=`http://127.0.0.1:${server.httpServer.address().port}`;browser=await chromium.launch();});
after(async()=>{await browser?.close();await new Promise(r=>server?.httpServer.close(r));});
async function scene(state,width,run){const c=await browser.newContext({viewport:{width,height:844},locale:'en-IN',timezoneId:'Asia/Kolkata',reducedMotion:'reduce'}),p=await c.newPage();p.setDefaultTimeout(6000);const errors=[];try{await mockS35Application(p,state,origin,errors);assert.deepEqual(errors,[]);await run(p);assert.equal(await p.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),true);}finally{await c.close();}}
for(const width of [320,390,1440]){
 it(`Revision L controls and calendar heading win the legacy cascade at ${width}`,()=>scene('detail',width,async p=>{
  const b=p.locator('.tt-btn--jade').first();assert.equal(await b.evaluate(e=>getComputedStyle(e).backgroundColor),'rgb(46, 58, 140)');assert.equal(await b.evaluate(e=>getComputedStyle(e).borderRadius),'12px');assert.equal(await b.evaluate(e=>getComputedStyle(e).fontWeight),'700');
  assert.equal(await p.locator('.tt-dock').evaluate(e=>getComputedStyle(e).position),'static');assert.equal(await p.locator('h1 .s35-heading-icon').count(),1);
 }));
 it(`Review uses a white card and five accessible 48px star targets at ${width}`,()=>scene('review',width,async p=>{
  assert.equal(await p.locator('.s35-review').evaluate(e=>getComputedStyle(e).backgroundColor),'rgb(255, 255, 255)');assert.equal(await p.locator('.s35-rating svg').count(),5);
  for(const r of await p.getByRole('radio').all()){const label=r.locator('..');assert.ok((await label.boundingBox()).width>=48);assert.ok((await label.boundingBox()).height>=48);}
 }));
 it(`Selected slot status does not wrap into vertical letters at ${width}`,()=>scene('reschedule',width,async p=>{const chip=p.locator('.tt-slotbtn[aria-checked=true] .tt-chip');assert.equal(await chip.evaluate(e=>getComputedStyle(e).whiteSpace),'nowrap');assert.ok((await chip.boundingBox()).height<40);}));
 it(`Room has one main, a usable video grid and light Revision L controls at ${width}`,()=>scene('room',width,async p=>{
  for(const name of ['.tt-nm','.tt-nm2'])assert.equal(await p.locator(name).first().evaluate(e=>getComputedStyle(e).color),'rgb(239, 237, 246)');assert.equal(await p.locator('main').count(),1);assert.equal(await p.locator('.tt-live').evaluate(e=>getComputedStyle(e).display),'grid');assert.ok((await p.locator('.tt-stage').boundingBox()).height>=220);assert.equal(await p.locator('.tt-live').evaluate(e=>getComputedStyle(e).backgroundColor),'rgb(239, 237, 246)');assert.equal(await p.locator('h1').count(),1);
 }));
}
it('S-35 warning notices use white Revision L cards, with a gold warning edge',()=>scene('reschedule-conflict',390,async p=>{const b=p.locator('.tt-banner');assert.equal(await b.evaluate(e=>getComputedStyle(e).backgroundColor),'rgb(255, 255, 255)');assert.equal(await b.evaluate(e=>getComputedStyle(e).borderLeftWidth),'4px');}));
