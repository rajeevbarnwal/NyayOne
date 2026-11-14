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

// Check readable surfaces independently of synthetic media or axe's image-background limits.
function contrast(a,b){const lum=c=>c.match(/[\d.]+/g).slice(0,3).map(Number).map(v=>{v/=255;return v<=.04045?v/12.92:((v+.055)/1.055)**2.4;}).reduce((s,v,i)=>s+v*[.2126,.7152,.0722][i],0);const x=lum(a),y=lum(b);return (Math.max(x,y)+.05)/(Math.min(x,y)+.05);}
for(const width of [320,390,1440]){
 it(`Prejoin uses the frozen indigo preview and heading treatment at ${width}`,()=>scene('prejoin',width,async p=>{
  assert.equal(await p.locator('h1 .s35-heading-icon').count(),1);
  const preview=p.locator('.tt-preview');assert.equal(await preview.evaluate(e=>getComputedStyle(e).backgroundColor),'rgb(28, 36, 84)');
  assert.equal(await preview.evaluate(e=>getComputedStyle(e).borderRadius),'14px');assert.equal((await preview.boundingBox()).height,170);
  const off=p.locator('.tt-preview__off');assert.equal(await off.evaluate(e=>getComputedStyle(e).color),'rgb(239, 237, 246)');assert.equal(await off.locator('svg').evaluate(e=>getComputedStyle(e).width),'28px');
 }));
 it(`Review fields and actions retain frozen styling and usable targets at ${width}`,()=>scene('review',width,async p=>{
  assert.equal(await p.locator('.s35-review h2 .s35-heading-icon').count(),1);
  assert.equal(await p.locator('textarea').evaluate(e=>getComputedStyle(e).backgroundColor),'rgb(255, 255, 255)');
  assert.equal(await p.locator('legend').evaluate(e=>getComputedStyle(e).fontWeight),'700');assert.equal(await p.locator('.s35-review label[for]').evaluate(e=>getComputedStyle(e).fontSize),'12px');
  assert.equal(await p.getByRole('button',{name:'Submit review',exact:true}).locator('svg').count(),1);
 }));
 it(`Review delete confirmation separates full-width actions at ${width}`,()=>scene('review-delete-confirm',width,async p=>{
  const section=p.getByRole('region',{name:'Delete review confirmation'}),buttons=section.getByRole('button');
  const a=await buttons.nth(0).boundingBox(),b=await buttons.nth(1).boundingBox();assert.ok(b.y>=a.y+a.height+9);assert.equal(a.width,b.width);assert.equal(await buttons.locator('svg').count(),2);
 }));
 for(const state of ['list-empty','list-error','detail-error'])it(`S-35 ${state} has a centered white recovery card at ${width}`,()=>scene(state,width,async p=>{
  const card=p.locator('.s35-state-card');assert.equal(await card.count(),1);assert.equal(await card.evaluate(e=>getComputedStyle(e).backgroundColor),'rgb(255, 255, 255)');assert.equal(await card.evaluate(e=>getComputedStyle(e).textAlign),'center');
  const action=card.locator('.tt-btn');assert.equal(await action.evaluate(e=>getComputedStyle(e).backgroundColor),'rgb(46, 58, 140)');assert.ok((await action.boundingBox()).height>=48);
 }));
}
for(const state of ['room','room-connecting','room-reconnecting','room-failed','room-token-expired'])it(`Room ${state} text has readable opaque surfaces independent of video`,()=>scene(state,390,async p=>{
 const elements=p.locator('.tt-rbanner .tt-banner__t,.tt-rbanner .tt-banner__d,.tt-tstate');assert.ok(await elements.count());
 for(const el of await elements.all()){
  const c=await el.evaluate(e=>({fg:getComputedStyle(e).color,bg:getComputedStyle(e.closest('.tt-rbanner,.tt-tstate')).backgroundColor}));
  assert.ok(!c.bg.startsWith('rgba'),JSON.stringify(c));assert.ok(contrast(c.fg,c.bg)>=4.5,JSON.stringify(c));
 }
}));
