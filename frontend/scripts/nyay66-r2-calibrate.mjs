// Explicit reference-only capture/import. Never called by per-PR live capture.
import http from 'node:http';
import {readFile,writeFile,mkdir,readdir} from 'node:fs/promises';
import {resolve} from 'node:path';
import {execFileSync} from 'node:child_process';
import {createRequire} from 'node:module';
import {chromium} from 'playwright';
import {R2_SOURCE_PATH,R2_SOURCE_SHA256,R2_STATES,R2_VIEWPORTS,validateR2Manifest,verifyR2PNG} from './lib/nyay66-r2.mjs';
import {inspectSurface} from './lib/nyay66-dom.mjs';
import {digest} from './lib/nyay66-enforcement.mjs';
const require=createRequire(import.meta.url),root=resolve('..'),out=resolve(process.argv[2]||'artifacts/nyay66-r2-calibration');
const source=await readFile(resolve(root,R2_SOURCE_PATH));
if(digest(source)!==R2_SOURCE_SHA256)throw Error('R2_SOURCE_BYTES_MISMATCH');
await mkdir(out,{recursive:false});
const server=http.createServer((req,res)=>{if(req.url!=='/'){res.writeHead(404).end();return;}res.setHeader('Content-Type','text/html');res.end(source);});
await new Promise(done=>server.listen(0,'127.0.0.1',done));
const origin=`http://127.0.0.1:${server.address().port}`;
const fonts={};for(const file of (await readdir('public/fonts')).filter(x=>x.endsWith('.woff2')).sort())fonts[file]=digest(await readFile(resolve('public/fonts',file)));
const manifest={schema:1,purpose:'UNIMPORTED_REFERENCE_CALIBRATION',approval:'NYAY-50:15422',theme:'light',sourceSha256:R2_SOURCE_SHA256,producerHead:execFileSync('git',['rev-parse','HEAD'],{encoding:'utf8'}).trim(),generatedUTC:new Date().toISOString(),platform:`${process.platform}-${process.arch}`,playwright:require('playwright/package.json').version,fonts,rows:[]};
let browser;
try{
  browser=await chromium.launch({args:['--no-sandbox']});manifest.chromium=browser.version();
  if(manifest.platform!=='linux-x64'||manifest.chromium!=='149.0.7827.55'||manifest.playwright!=='1.61.1')throw Error('R2_CALIBRATION_PIN_MISMATCH');
  for(const state of R2_STATES)for(const vp of R2_VIEWPORTS){
    const samples=[];let surface,first,fontStack;
    for(let index=0;index<3;index++){
      const context=await browser.newContext({viewport:{width:1920,height:1600},deviceScaleFactor:1,locale:'en-IN',timezoneId:'Asia/Kolkata',colorScheme:'light',reducedMotion:'reduce',serviceWorkers:'block'});
      try{
        const page=await context.newPage(),errors=[];
        page.on('pageerror',()=>errors.push('PAGE_ERROR'));
        page.on('console',m=>{if(m.type()==='error')errors.push('CONSOLE_ERROR');});
        await page.route('**/*',route=>{const url=route.request().url();if(url===origin+'/'||url.startsWith('blob:')||url.startsWith('data:'))return route.continue();errors.push('OUTBOUND_REQUEST');return route.abort();});
        await page.goto(origin);await page.waitForFunction(()=>window.SCREENS&&document.querySelector('.vp'));
        await page.evaluate(({state,vp,inventory})=>{
          const actual=Object.entries(window.SCREENS).flatMap(([view,entry])=>entry.states.map(([s])=>`${view}-${s}`));
          if(JSON.stringify(actual)!==JSON.stringify(inventory))throw Error('R2_REGISTRY_DRIFT');
          window.S.screen=state.view;window.S.st[state.view]=state.state;window.S.dev=vp.preset;window.build();
          // Remove only reviewer zoom/clipping; leave the .vp design untouched.
          const viewport=document.querySelector('.vp');
          for(let node=viewport.parentElement;node&&node!==document.body;node=node.parentElement){node.style.transform='none';node.style.overflow='visible';node.style.width=vp.width+'px';node.style.height='auto';}
        },{state,vp,inventory:R2_STATES.map(x=>x.id)});
        await page.evaluate(async()=>{await document.fonts.ready;await Promise.all([...document.images].map(x=>x.decode()));await new Promise(done=>requestAnimationFrame(()=>requestAnimationFrame(done)));});
        if(errors.length)throw Error(errors.join(','));
        const bytes=await page.locator('.vp').screenshot({animations:'disabled'});samples.push(digest(bytes));
        if(index===0){first=bytes;surface=await page.evaluate(inspectSurface,{reference:true});fontStack=await page.evaluate(()=>({viewport:getComputedStyle(document.querySelector('.vp')).fontFamily,faces:[...document.fonts].map(f=>({family:f.family,weight:f.weight,style:f.style,status:f.status}))}));}
      }finally{await context.close();}
    }
    if(new Set(samples).size!==1)throw Error(`R2_REFERENCE_VARIANCE:${state.id}:${vp.id}`);
    const row={view:state.id,viewport:vp.id,file:`${state.id}-${vp.id}-0.png`,sha256:samples[0],sampleHashes:samples,dimensions:[vp.width,vp.height],surface,fontStack};
    verifyR2PNG(row,first);await writeFile(resolve(out,row.file),first);manifest.rows.push(row);
    console.log(`${state.id} ${vp.id}: 3/3 byte-identical`);
  }
  validateR2Manifest(manifest);await writeFile(resolve(out,'manifest.json'),JSON.stringify(manifest,null,2)+'\n');
  const files=(await readdir(out)).sort();await writeFile(resolve(out,'SHA256SUMS'),(await Promise.all(files.map(async f=>`${digest(await readFile(resolve(out,f)))}  ${f}`))).join('\n')+'\n');
  console.log(`R2_IMPORT_OK 42 panels manifest ${digest(await readFile(resolve(out,'manifest.json')))}`);
}finally{if(browser)await browser.close();await new Promise(done=>server.close(done));}
