// Diagnostic reproducibility proof; not a substitute for hosted Linux
// exact-image approval. Never choose a capture by comparing an approval hash.
import {it} from 'node:test';
import assert from 'node:assert/strict';
import {preview} from 'vite';
import {chromium} from 'playwright';
import {mockS19Application} from './nyay66-s19-fixtures.mjs';
import {inspectSurface} from './nyay66-dom.mjs';
import {withS19RasterBrowser} from './nyay66-s19-raster.mjs';

const rows=[
  {state:'delete-reauth-rejected',viewport:'mobile390',width:390,height:844},
  {state:'delete-typed',viewport:'mobile390',width:390,height:844},
  {state:'delete-confirm',viewport:'desktop',width:1440,height:1024},
  {state:'export-failed',viewport:'desktop',width:1440,height:1024},
];
for(const {state,viewport,width,height} of rows)it(`${viewport} ${state} capture repeats exactly despite font-delivery timing, without image selection`,{timeout:120_000},async()=>{
  const server=await preview({preview:{host:'127.0.0.1',port:0,strictPort:false},logLevel:'error'});
  const origin=`http://127.0.0.1:${server.httpServer.address().port}`;
  let shared,firstBytes,firstSurface,captures=0;
  try{
    shared=await chromium.launch();
    // Fixed matrix. Every capture participates; no convergence retries,
    // discarded first screenshots, repaint, DOM rewrite or pixel processing.
    for(const delay of [0,50,200,500,1000,1500])for(let repeat=0;repeat<2;repeat++){
      await withS19RasterBrowser(shared,state,viewport,async browser=>{
        const context=await browser.newContext({viewport:{width,height},deviceScaleFactor:1,locale:'en-IN',timezoneId:'Asia/Kolkata',colorScheme:'light',reducedMotion:'reduce',serviceWorkers:'block'});
        try{
          const page=await context.newPage();page.setDefaultTimeout(15000);
          // Test the transport race only. The product bytes remain unchanged.
          const originalRoute=page.route.bind(page);
          page.route=(pattern,handler)=>originalRoute(pattern,async route=>{
            if(new URL(route.request().url()).pathname.endsWith('.woff2'))await new Promise(resolve=>setTimeout(resolve,delay));
            return handler(route);
          });
          const errors=[];
          await mockS19Application(page,state,origin,errors);
          await page.evaluate(async()=>{await document.fonts.ready;await Promise.all([...document.images].map(i=>i.decode()));await new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve)));});
          const surface=await page.evaluate(inspectSurface),bytes=await page.screenshot({animations:'disabled',fullPage:false});
          assert.deepEqual(errors,[]);assert.equal(surface.overflow,0);
          firstBytes??=bytes;firstSurface??=surface;
          assert.deepEqual(surface,firstSurface,`geometry changed at font delay ${delay}, repeat ${repeat}`);
          // Compare every byte without asking node:assert to format a huge
          // binary diff when a capture differs; the equality rule is unchanged.
          assert.ok(bytes.equals(firstBytes),`raw PNG changed at font delay ${delay}, repeat ${repeat}`);
          captures++;
        }finally{await context.close();}
      });
    }
    assert.equal(captures,12);
  }finally{await shared?.close();await new Promise(resolve=>server.httpServer.close(resolve));}
});
