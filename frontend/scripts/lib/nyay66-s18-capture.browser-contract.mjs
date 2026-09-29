// Local browser regression only, not an imported/hosted baseline. Writes no PNGs.
import {before,after,describe,it} from 'node:test';
import assert from 'node:assert/strict';
import http from 'node:http';
import {fileURLToPath} from 'node:url';
import {chromium} from 'playwright';
import {digest} from './nyay66-enforcement.mjs';
import {S18_STATES,S18_VIEWPORTS,loadS18Source,verifyS18PNG} from './nyay66-s18-reference.mjs';
import {captureS18Sample,removeS18ReviewerClipping} from './nyay66-s18-capture.mjs';
let browser,server,origin;
before(async()=>{
  const {html}=await loadS18Source(fileURLToPath(new URL('../../../',import.meta.url)));
  server=http.createServer((req,res)=>{res.setHeader('Content-Type','text/html');res.end(html);});
  await new Promise(done=>server.listen(0,'127.0.0.1',done));origin=`http://127.0.0.1:${server.address().port}`;
  browser=await chromium.launch();
});
after(async()=>{await browser?.close();if(server)await new Promise(done=>server.close(done));});
describe('S-18 approved-source capture configuration (local diagnostic regression)',{timeout:180000},()=>{
  it('normalizes only the reviewer radius and preserves every descendant style and viewport size',async()=>{
    const page=await browser.newPage();
    try{
      await page.setContent('<body data-bare="1"><div class="vp" style="border-radius:8px;width:390px;height:844px;overflow:auto"><main style="padding:16px;border-radius:22px;color:rgb(1,2,3)"><button style="height:48px">Keep me</button></main></div></body>');
      const before=await page.locator('.vp').innerHTML();
      await page.evaluate(removeS18ReviewerClipping);
      assert.equal(await page.locator('.vp').innerHTML(),before);
      assert.deepEqual(await page.locator('.vp').evaluate(e=>[e.clientWidth,e.clientHeight,getComputedStyle(e).overflow,getComputedStyle(e).borderRadius]),[390,844,'auto','0px']);
      await page.locator('body').evaluate(e=>e.removeAttribute('data-bare'));
      await assert.rejects(page.evaluate(removeS18ReviewerClipping),/S18_REVIEWER_NOT_BARE/);
    }finally{await page.close();}
  });
  for(const state of S18_STATES)for(const vp of S18_VIEWPORTS)it(`${state} / ${vp.id}: exact viewport, no frame clipping, 3 stable fresh-context samples`,async()=>{
    const hashes=[];
    for(let sample=0;sample<3;sample++){
      const context=await browser.newContext({viewport:{width:vp.width,height:vp.height},deviceScaleFactor:1,locale:'en-IN',timezoneId:'Asia/Kolkata',colorScheme:'light',reducedMotion:'reduce',serviceWorkers:'block'});
      try{
        const page=await context.newPage(),errors=[];
        page.on('pageerror',()=>errors.push('pageerror'));
        page.on('console',m=>{if(m.type()==='error')errors.push('console-error');});
        await context.route('**/*',route=>{const url=route.request().url();if(url===origin+'/'||url.startsWith('data:')||url.startsWith('blob:'))return route.continue();errors.push('outbound-request');return route.abort();});
        const result=await captureS18Sample(page,origin,state,vp),hash=digest(result.bytes);
        verifyS18PNG({sha256:hash,dimensions:[vp.width,vp.height]},result.bytes);
        assert.equal(result.surface.dimensions[0],vp.width);
        assert.ok(result.surface.dimensions[1]>=vp.height);
        assert.equal(result.surface.overflow,0);
        assert.deepEqual(result.reviewerFrame,{x:0,y:0,borderRadius:'0px'});
        assert.deepEqual(errors,[]);hashes.push(hash);
      }finally{await context.close();}
    }
    assert.equal(new Set(hashes).size,1,'three reference samples must be byte-identical');
  });
});
