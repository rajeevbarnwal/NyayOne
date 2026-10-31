// Diagnostic reproducibility proof; not a substitute for hosted Linux
// exact-image approval. Never choose a capture by comparing an approval hash.
// Match CI setup: VITE_API_BASE_URL= npm run build, then
// VITE_API_BASE_URL= node scripts/nyay66-s01-component-build.mjs.
import {it} from 'node:test';
import assert from 'node:assert/strict';
import {createHash} from 'node:crypto';
import {writeFile} from 'node:fs/promises';
import {preview} from 'vite';
import {chromium} from 'playwright';
import {PNG} from 'pngjs';
import {mockS19Application} from './nyay66-s19-fixtures.mjs';
import {inspectSurface} from './nyay66-dom.mjs';
import {withS19RasterBrowser} from './nyay66-s19-raster.mjs';
import {S19_MEASURED_STATES} from './nyay66-s19-coverage.mjs';
import {S19_VIEWPORTS} from './nyay66-s19-reference.mjs';

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

it('full S-19 sequence preserves every raw image across repetition, reversed order and delayed fonts',{timeout:600_000},async()=>{
  const server=await preview({preview:{host:'127.0.0.1',port:0,strictPort:false},logLevel:'error'});
  const origin=`http://127.0.0.1:${server.httpServer.address().port}`;
  const matrix=S19_MEASURED_STATES.flatMap(state=>S19_VIEWPORTS.map(vp=>({state,...vp})));
  const rounds=[
    {name:'initial',delay:0,rows:matrix},
    {name:'repeat',delay:0,rows:matrix},
    {name:'reverse-delayed',delay:200,rows:[...matrix].reverse()},
    {name:'rotate-delayed',delay:500,rows:[...matrix.slice(17),...matrix.slice(0,17)]},
  ];
  const initial=new Map(),records=[],mismatches=[];let shared;
  const sha=bytes=>createHash('sha256').update(bytes).digest('hex');
  try{
    shared=await chromium.launch();
    for(const round of rounds){
      for(const {state,id:viewport,width,height} of round.rows){
        await withS19RasterBrowser(shared,state,viewport,async browser=>{
          const context=await browser.newContext({viewport:{width,height},deviceScaleFactor:1,locale:'en-IN',timezoneId:'Asia/Kolkata',colorScheme:'light',reducedMotion:'reduce',serviceWorkers:'block'});
          try{
            const page=await context.newPage();page.setDefaultTimeout(15000);
            const originalRoute=page.route.bind(page);
            page.route=(pattern,handler)=>originalRoute(pattern,async route=>{
              if(new URL(route.request().url()).pathname.endsWith('.woff2'))await new Promise(resolve=>setTimeout(resolve,round.delay));
              return handler(route);
            });
            const errors=[];
            const evidence=await mockS19Application(page,state,origin,errors);
            await page.evaluate(async()=>{await document.fonts.ready;await Promise.all([...document.images].map(i=>i.decode()));await new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve)));});
            const surface=await page.evaluate(inspectSurface),bytes=await page.screenshot({animations:'disabled',fullPage:false});
            const scroll=await page.evaluate(()=>({x:scrollX,y:scrollY}));
            assert.deepEqual(errors,[]);assert.equal(surface.overflow,0);
            const key=`${state}:${viewport}`;
            if(!initial.has(key))initial.set(key,{bytes,surface,scroll});
            const first=initial.get(key),sameGeometry=JSON.stringify(surface)===JSON.stringify(first.surface);
            const record={round:round.name,state,viewport,fontDelay:round.delay,sha256:sha(bytes),sameGeometry,sameBytes:bytes.equals(first.bytes),evidenceKind:evidence.evidenceKind};
            records.push(record);
            if(!record.sameBytes||!sameGeometry){
              const a=PNG.sync.read(first.bytes),b=PNG.sync.read(bytes);let pixels=0,channels=0,maxDelta=0;
              for(let i=0;i<a.data.length;i+=4){let changed=false;for(let j=0;j<4;j++){const d=Math.abs(a.data[i+j]-b.data[i+j]);if(d){changed=true;channels++;maxDelta=Math.max(maxDelta,d);}}if(changed)pixels++;}
              mismatches.push({...record,firstSha256:sha(first.bytes),pixels,channels,maxDelta,firstScroll:first.scroll,scroll,firstSurface:first.surface,surface});
            }
          }finally{await context.close();}
        });
      }
      console.log(JSON.stringify({s19SequenceRound:round.name,captures:records.length,mismatches:mismatches.length}));
    }
    assert.equal(initial.size,50);assert.equal(records.length,200);
    if(process.env.NYAY66_S19_SEQUENCE_PROOF)await writeFile(process.env.NYAY66_S19_SEQUENCE_PROOF,JSON.stringify({limitation:'Local browser diagnostic with synthetic APIs; not hosted conformance or independent QA. Every capture participates; no hash selection or retry.',chromium:shared.version(),records,mismatches},null,2)+'\n');
    assert.deepEqual(mismatches,[],'S-19 raw images changed across the fixed sequence matrix');
  }finally{await shared?.close();await new Promise(resolve=>server.httpServer.close(resolve));}
});
