import http from 'node:http';
import {readFile,readdir,mkdir,writeFile} from 'node:fs/promises';
import {resolve,dirname,extname} from 'node:path';
import {fileURLToPath} from 'node:url';
import {execFileSync} from 'node:child_process';
import {createRequire} from 'node:module';
import {chromium} from 'playwright';
import {PNG} from 'pngjs';
import {coverage,SOURCE_SHA256,VIEWPORTS} from './lib/nyay66-conformance.mjs';
import {inspectSurface} from './lib/nyay66-dom.mjs';
import {mockApplication} from './lib/nyay66-fixtures.mjs';
import {loadR2,R2_SOURCE_SHA256,R2_VIEWPORTS,R2_LIVE_STATES,pendingStateRow,verifyR2PNG,mockR2Application} from './lib/nyay66-r2.mjs';
import {enforcePins,digest,pixelMetrics,compareStructure,approveException,validateProgression,LIMITS,canonical} from './lib/nyay66-enforcement.mjs';
const require=createRequire(import.meta.url),root=resolve(dirname(fileURLToPath(import.meta.url)),'../..');
const config=JSON.parse(await readFile(resolve(root,'frontend/scripts/nyay66-policy.json')));
if(config.ownerToleranceApproval!=='NYAY-66:15382'||canonical(config.tolerances)!==canonical(LIMITS))throw Error('TOLERANCE_APPROVAL_MISMATCH');
const cache=resolve(root,'frontend/test-baselines/nyay66',config.cache);
const manifestBytes=await readFile(resolve(cache,'manifest.json'));
if(digest(manifestBytes)!==config.manifestSha256)throw Error('REFERENCE_MANIFEST_MISMATCH');
const manifest=JSON.parse(manifestBytes);
if(manifest.sourceSha256!==SOURCE_SHA256)throw Error('REFERENCE_SOURCE_MISMATCH');
const r2=await loadR2(root,config.r2);
const coverageOptions={r2:!!r2};
const out=resolve(process.env.NYAY66_OUTPUT||resolve(root,'frontend/artifacts/nyay66-live'));
await mkdir(dirname(out),{recursive:true});await mkdir(out);
const repository=resolve(process.env.NYAY66_REPO||root);
const head=execFileSync('git',['rev-parse','HEAD'],{cwd:repository,encoding:'utf8'}).trim();
if(process.env.NYAY66_BASE){
  let previous;
  try{previous=JSON.parse(execFileSync('git',['show',`${process.env.NYAY66_BASE}:frontend/scripts/nyay66-policy.json`],{cwd:repository,encoding:'utf8',stdio:['ignore','pipe','pipe']}));}
  catch(error){if(execFileSync('git',['ls-tree','--name-only',process.env.NYAY66_BASE,'frontend/scripts/nyay66-policy.json'],{cwd:repository,encoding:'utf8'}).trim())throw error;previous={enforced:[]};}
  validateProgression(previous.enforced,config.enforced,coverageOptions);
}else throw Error('COMPARISON_BASE_REQUIRED');
if(!process.env.NYAY66_AUTHORIZATION)throw Error('INTEGRITY_APPROVAL_REQUIRED');
const authorization=JSON.parse(await readFile(process.env.NYAY66_AUTHORIZATION));
if(authorization.head!==head||authorization.base!==process.env.NYAY66_BASE||authorization.bundleSha256!==config.integrityApproval?.bundleSha256)throw Error('AUTHORIZATION_HEAD_MISMATCH');
const comments=authorization.comments;
if(config.exceptions.some(entry=>!approveException(entry,comments,coverageOptions)))throw Error('OWNER_EXCEPTION_APPROVAL_MISSING');
const fonts={};
for(const name of (await readdir(resolve(root,'frontend/public/fonts'))).filter(x=>x.endsWith('.woff2')).sort())fonts[name]=digest(await readFile(resolve(root,'frontend/public/fonts',name)));
const dist=resolve(process.env.NYAY66_DIST||resolve(root,'frontend/dist'));
const server=http.createServer(async(req,res)=>{
  try{
    const path=decodeURIComponent(new URL(req.url,'http://localhost').pathname);
    let file=resolve(dist,'.'+path);
    if(!file.startsWith(dist+'/'))file=resolve(dist,'index.html');
    if(!extname(file))file=resolve(dist,'index.html');
    const body=await readFile(file);
    res.setHeader('Content-Type',({'.html':'text/html','.js':'text/javascript','.css':'text/css','.svg':'image/svg+xml','.png':'image/png','.woff2':'font/woff2'})[extname(file)]||'application/octet-stream');res.end(body);
  }catch{res.writeHead(404).end();}
});
await new Promise(done=>server.listen(0,'127.0.0.1',done));
const origin=`http://127.0.0.1:${server.address().port}`;
let browser;
const report={head,generatedUTC:new Date().toISOString(),referenceCache:config.cache,referenceManifestSha256:config.manifestSha256,referenceGenerationExecuted:false,rows:[],enforced:config.enforced,approvedToleranceRecord:'NYAY-66:15382'};
if(r2)report.r2Reference={cache:config.r2.cache,manifestSha256:config.r2.manifestSha256,sourceSha256:R2_SOURCE_SHA256,approval:r2.manifest.approval};
const crop=(png,box)=>{
  const x=Math.max(0,Math.floor(box.x)),y=Math.max(0,Math.floor(box.y));
  const width=Math.min(png.width-x,Math.ceil(box.width)),height=Math.min(png.height-y,Math.ceil(box.height));
  if(width<=0||height<=0)throw Error('REGION_OUTSIDE_VIEWPORT');
  const out=new PNG({width,height});PNG.bitblt(png,out,x,y,width,height,0,0);return out;
};
try{
  browser=await chromium.launch();
  enforcePins(manifest,{chromium:browser.version(),playwright:require('playwright/package.json').version,platform:`${process.platform}-${process.arch}`,sourceSha256:digest(await readFile(resolve(root,'docs/design/nyayone-option-3.2.1/NYAYONE_OPTION3_2_1_REVL_SOURCE.html'))),fonts});
  if(r2)enforcePins(r2.manifest,{chromium:browser.version(),playwright:require('playwright/package.json').version,platform:`${process.platform}-${process.arch}`,sourceSha256:R2_SOURCE_SHA256,fonts});
  for(const item of coverage('light',coverageOptions))for(const vp of item.source==='r2'?R2_VIEWPORTS:VIEWPORTS){
    if(item.status==='DESIGN-GAP'){report.rows.push({screen:item.screen,viewport:vp.id,theme:'light',verdict:'DESIGN-GAP',executed:false});continue;}
    for(const view of item.views){
      const isR2=item.source==='r2';
      const id=isR2?`${item.screen}-${view.slice(4)}`:item.screen==='S-10'&&view==='s10b'?'S-10-academic':item.screen;
      if(isR2&&!R2_LIVE_STATES.includes(view)){
        const row=pendingStateRow(item.screen,id,vp.id,config.enforced);
        row.referenceSha256=r2.manifest.rows.find(x=>x.view===view&&x.viewport===vp.id).sha256;
        report.rows.push(row);console.log(JSON.stringify(row));continue;
      }
      const name=`${id}-${vp.id}`;const errors=[];
      const row={screen:item.screen,state:id,viewport:vp.id,theme:'light',executed:false,errors};
      let context;
      try{
        const reference=(isR2?r2.manifest:manifest).rows.find(x=>x.view===view&&x.viewport===vp.id);
        if(!reference)throw Error('REFERENCE_MISSING');
        const referenceBytes=await readFile(resolve(isR2?r2.cache:cache,reference.file));
        if(digest(referenceBytes)!==reference.sha256)throw Error('REFERENCE_BYTES_MISMATCH');
        if(isR2)verifyR2PNG(reference,referenceBytes);
        context=await browser.newContext({viewport:{width:vp.width,height:vp.height},deviceScaleFactor:1,locale:'en-IN',timezoneId:'Asia/Kolkata',colorScheme:'light',reducedMotion:'reduce',serviceWorkers:'block'});
        const page=await context.newPage();page.setDefaultTimeout(20000);
        page.on('pageerror',()=>errors.push('PAGE_ERROR'));
        page.on('console',msg=>{if(msg.type()==='error')errors.push('CONSOLE_ERROR');});
        if(isR2)await mockR2Application(page,view,origin,errors);
        else await mockApplication(page,id,origin,errors);
        await page.evaluate(async()=>{await document.fonts.ready;await Promise.all([...document.images].map(img=>img.decode()));await new Promise(done=>requestAnimationFrame(()=>requestAnimationFrame(done)));});
        const surface=await page.evaluate(inspectSurface,{clocks:view==='s05'});
        const bytes=await page.screenshot({animations:'disabled'});
        await writeFile(resolve(out,`${name}-live.png`),bytes);
        await writeFile(resolve(out,`${name}-reference.png`),referenceBytes);
        const actual=PNG.sync.read(bytes),expected=PNG.sync.read(referenceBytes);
        const structure=compareStructure(reference.surface,surface,view==='s05'?2:0);
        const masks=structure.includes('dynamic-regions')?[]:[...reference.surface.masks,...surface.masks].map(x=>x.box);
        const metrics=pixelMetrics(expected,actual,masks);
        const diff=new PNG({width:actual.width,height:actual.height});diff.data=metrics.diff;
        await writeFile(resolve(out,`${name}-diff.png`),PNG.sync.write(diff));delete metrics.diff;
        const regions=[];
        for(const [i,control] of [...reference.surface.controls,...reference.surface.headings].entries()){
          try{const m=pixelMetrics(crop(expected,control.box),crop(actual,control.box),[]);delete m.diff;regions.push({index:i,...m});}catch{regions.push({index:i,pass:false});}
        }
        await page.addScriptTag({path:require.resolve('axe-core/axe.min.js')});
        const accessibility=await page.evaluate(async()=>{const result=await window.axe.run(document);return result.violations.map(v=>({id:v.id,impact:v.impact,nodes:v.nodes.length}));});
        const violations=[...structure,...(!metrics.pass||regions.some(x=>!x.pass)?['pixels']:[]),...(accessibility.some(v=>['serious','critical'].includes(v.impact))?['accessibility']:[])];
        const approved=config.exceptions.filter(e=>e.screen===item.screen&&e.viewport===vp.id&&e.theme==='light'&&e.referenceSha256===reference.sha256&&e.liveSha256===digest(bytes));
        const remaining=violations.filter(v=>!approved.some(e=>e.checks.includes(v)));
        Object.assign(row,{executed:true,referenceSha256:reference.sha256,liveSha256:digest(bytes),metrics,regions,structure,referenceSurface:reference.surface,liveSurface:surface,accessibility,exceptionsApplied:approved,remaining});
        row.verdict=errors.length?'CAPTURE-FAILED':remaining.length?'NONCONFORMANT':approved.length?'PARITY-WITH-DISCLOSED-DELTA':'PARITY';
      }catch(error){row.verdict='CAPTURE-FAILED';row.failure=error.message?.split('\n')[0].replace(/https?:\/\/\S+/g,'[origin]').slice(0,160);}
      finally{if(context)await context.close();}
      row.blocking=row.verdict==='CAPTURE-FAILED'||config.enforced.includes(item.screen)&&!row.verdict.startsWith('PARITY');
      report.rows.push(row);console.log(JSON.stringify({screen:id,viewport:vp.id,verdict:row.verdict,blocking:row.blocking}));
    }
  }
  report.rows.push(...coverage('dark').flatMap(item=>VIEWPORTS.map(vp=>({screen:item.screen,viewport:vp.id,theme:'dark',verdict:'DESIGN-GAP',executed:false}))));
  report.blocking=report.rows.some(row=>row.blocking);
  await writeFile(resolve(out,'report.json'),JSON.stringify(report,null,2)+'\n');
  const links=report.rows.filter(r=>r.executed).map(r=>`<section><h2>${r.state} · ${r.viewport} · ${r.verdict}</h2><p>Reference | live | diff — ${head}</p><div>${['reference','live','diff'].map(kind=>`<img alt="${kind}" src="${r.state}-${r.viewport}-${kind}.png">`).join('')}</div></section>`).join('');
  await writeFile(resolve(out,'comparison.html'),`<!doctype html><meta charset="utf-8"><title>NYAY-66 comparison</title><style>body{font:16px sans-serif;background:#102033;color:white}div{display:flex;gap:10px}img{width:32%;object-fit:contain;align-self:start}section{margin-bottom:40px}</style><h1>NYAY-66 exact-head comparison</h1><p>${head}; unapproved differences remain NONCONFORMANT, not waived.</p>${links}`);
  const files=(await readdir(out)).sort();
  await writeFile(resolve(out,'SHA256SUMS'),(await Promise.all(files.map(async file=>`${digest(await readFile(resolve(out,file)))}  ${file}`))).join('\n')+'\n');
  if(report.blocking)process.exitCode=1;
}finally{if(browser)await browser.close();await new Promise(done=>server.close(done));}
