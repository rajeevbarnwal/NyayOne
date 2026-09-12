// S-01 behavioral regression rehearsal against the actual production build.
// Synthetic server projections only; not a visual-parity or real-backend claim.
import assert from 'node:assert/strict';
import http from 'node:http';
import {readFile} from 'node:fs/promises';
import {resolve,extname} from 'node:path';
import {chromium} from 'playwright';
import {actor} from './lib/nyay66-fixtures.mjs';
const dist=resolve('dist');
const server=http.createServer(async(req,res)=>{
  try{
    const path=new URL(req.url,'http://localhost').pathname;
    const file=resolve(dist,'.'+(extname(path)?path:'/index.html'));
    if(!file.startsWith(dist+'/'))throw Error('outside dist');
    res.setHeader('content-type',({'.html':'text/html','.js':'text/javascript','.css':'text/css','.woff2':'font/woff2','.svg':'image/svg+xml'})[extname(file)]||'application/octet-stream');
    res.end(await readFile(file));
  }catch{res.writeHead(404).end();}
});
await new Promise(done=>server.listen(0,'127.0.0.1',done));
const origin=`http://127.0.0.1:${server.address().port}`;
let browser,passed=0;
try{
  browser=await chromium.launch();
  for(const test of ['anonymous-unseen','anonymous-r2-seen','anonymous-legacy-marker','authenticated','malformed-retry','timeout']){
    const context=await browser.newContext();
    const page=await context.newPage();page.setDefaultTimeout(10000);
    let requests=0,malformed=test==='malformed-retry';
    await page.addInitScript(test=>{
      if(test==='anonymous-r2-seen')localStorage.setItem('nyayone.r2.onboarding-seen','true');
      if(test==='anonymous-legacy-marker')localStorage.setItem('ls-onboarding-seen','true');
    },test);
    await page.route('**/*',route=>{
      const url=new URL(route.request().url());
      if(url.origin!==origin)throw Error('OUTBOUND_REQUEST');
      if(url.pathname==='/api/v1/auth/student/session'){
        requests++;
        if(test==='timeout')return;
        const body=malformed?{}:{authenticated:test==='authenticated',actor:test==='authenticated'?actor:null};
        return route.fulfill({status:200,contentType:'application/json',body:JSON.stringify(body)});
      }
      // Hold the destination's independent profile request, not the boot screen.
      if(url.pathname==='/api/v1/student/profile')return;
      if(url.pathname.endsWith('/login/channels'))return route.fulfill({status:200,contentType:'application/json',body:'{"channels":[{"channel":"mobile","enabled":true},{"channel":"email","enabled":true}]}'});
      return route.continue();
    });
    try{
      if(test==='timeout')await page.clock.install();
      await page.goto(origin+'/s-01');
      if(test==='timeout'){
        await page.getByRole('progressbar').waitFor();assert.equal(new URL(page.url()).pathname,'/s-01');
        await page.clock.runFor(10001);
        await page.getByRole('button',{name:'Try again'}).waitFor();
        const before=requests;await page.clock.runFor(30000);assert.equal(requests,before);
        assert.equal(new URL(page.url()).pathname,'/s-01');
      }else if(malformed){
        await page.getByRole('heading',{name:'We could not reach NyayOne.'}).waitFor();
        assert.equal(new URL(page.url()).pathname,'/s-01');const before=requests;malformed=false;
        await page.getByRole('button',{name:'Try again'}).focus();
        await page.keyboard.press('Enter');await page.waitForURL('**/s-02');assert.equal(requests,before+1);
      }else await page.waitForURL('**/'+(test==='authenticated'?'s-07':test==='anonymous-r2-seen'?'s-03':'s-02'));
      passed++;console.log(`PASS ${test}`);
    }finally{await context.close();}
  }
  console.log(JSON.stringify({suite:'NYAY-77 S-01 production-build behavioral rehearsal',passed,expected:6,syntheticServer:true,visualParityClaim:false}));
}finally{await browser?.close();server.closeAllConnections();await new Promise(done=>server.close(done));}
