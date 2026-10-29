// S-25-only additive capture. Imported PNGs are never treated as product proof.
import {writeFile,readFile} from 'node:fs/promises';
import {resolve} from 'node:path';
import {createRequire} from 'node:module';
import {PNG} from 'pngjs';
import {digest,pixelMetrics,compareStructure} from './nyay66-enforcement.mjs';
import {inspectSurface} from './nyay66-dom.mjs';
import {S25_VIEWPORTS,verifyS25PNG} from './nyay66-s25-reference.mjs';
import {S25_MEASURED_STATES} from './nyay66-s25-coverage.mjs';
import {mockS25Application,classifyS25Errors} from './nyay66-s25-fixtures.mjs';
import {withS25RasterBrowser} from './nyay66-s25-raster.mjs';
const require=createRequire(import.meta.url);
function crop(png,box){
  const x=Math.max(0,Math.floor(box.x)),y=Math.max(0,Math.floor(box.y));
  const width=Math.min(png.width-x,Math.ceil(box.width)),height=Math.min(png.height-y,Math.ceil(box.height));
  if(width<=0||height<=0)throw Error('REGION_OUTSIDE_VIEWPORT');
  const out=new PNG({width,height});PNG.bitblt(png,out,x,y,width,height,0,0);return out;
}
export async function captureS25Rows({browser,origin,out,reference}){
  const rows=[];
  for(const state of S25_MEASURED_STATES)for(const vp of S25_VIEWPORTS){
    rows.push(await withS25RasterBrowser(browser,isolated=>captureS25Row({browser:isolated,origin,out,reference,state,vp})));
  }
  return rows;
}
async function captureS25Row({browser,origin,out,reference,state,vp}){
    const name=`S-25-${state}-${vp.id}`,errors=[];
    const row={screen:'S-25',state:`S-25-${state}`,designState:state,viewport:vp.id,theme:'light',source:'s25',executed:false,measured:false,errors,
      captureRaster:{browser:'isolated-per-row-chromium',version:browser.version(),partialRaster:false,pixelPostprocessing:false,approvalHashSelection:false}};
    let context,page;const consoleErrors=[],httpResponses=[],failedRequests=[];
    const failed=r=>failedRequests.push({method:r.method(),url:r.url(),errorText:r.failure()?.errorText});
    try{
      const ref=reference.manifest.rows.find(r=>r.view===`s25-${state}`&&r.viewport===vp.id);
      if(!ref)throw Error('S25_REFERENCE_MISSING');
      const referenceBytes=await readFile(resolve(reference.cache,ref.file));verifyS25PNG(ref,referenceBytes);
      context=await browser.newContext({viewport:{width:vp.width,height:vp.height},deviceScaleFactor:1,locale:'en-IN',timezoneId:'Asia/Kolkata',colorScheme:'light',reducedMotion:'reduce',serviceWorkers:'block'});
      page=await context.newPage();page.setDefaultTimeout(10000);
      page.on('requestfailed',failed);page.on('pageerror',()=>errors.push('PAGE_ERROR'));
      page.on('console',m=>{if(m.type()==='error')consoleErrors.push({text:m.text(),url:m.location().url});});
      page.on('response',r=>{if(r.status()>=400)httpResponses.push({method:r.request().method(),url:r.url(),status:r.status()});});
      Object.assign(row,await mockS25Application(page,state,origin,errors));
      await page.evaluate(async()=>{await document.fonts.ready;await Promise.all([...document.images].map(i=>i.decode()));await new Promise(done=>requestAnimationFrame(()=>requestAnimationFrame(done)));});
      const surface=await page.evaluate(inspectSurface),bytes=await page.screenshot({animations:'disabled',fullPage:false});
      const actual=PNG.sync.read(bytes),expected=PNG.sync.read(referenceBytes),structure=compareStructure(ref.surface,surface,0);
      const metrics=pixelMetrics(expected,actual,[]),diff=new PNG({width:actual.width,height:actual.height});diff.data=metrics.diff;delete metrics.diff;
      const regions=[];
      for(const [i,control] of [...ref.surface.controls,...ref.surface.headings].entries()){
        try{const m=pixelMetrics(crop(expected,control.box),crop(actual,control.box),[]);delete m.diff;regions.push({index:i,...m});}catch{regions.push({index:i,pass:false});}
      }
      await writeFile(resolve(out,`${name}-reference.png`),referenceBytes);await writeFile(resolve(out,`${name}-live.png`),bytes);await writeFile(resolve(out,`${name}-diff.png`),PNG.sync.write(diff));
      await page.addScriptTag({path:require.resolve('axe-core/axe.min.js')});
      const accessibility=await page.evaluate(async()=> (await window.axe.run(document)).violations.map(v=>({id:v.id,impact:v.impact,nodes:v.nodes.length})));
      Object.assign(row,{executed:true,measured:true,referenceSha256:ref.sha256,liveSha256:digest(bytes),metrics,regions,structure,referenceSurface:ref.surface,liveSurface:surface,accessibility,verdict:'PENDING-EVALUATION'});
    }catch(error){row.verdict='CAPTURE-FAILED';row.failure=error.message?.split('\n')[0].replace(/https?:\/\/\S+/g,'[origin]').slice(0,180);}
    finally{if(page)page.off('requestfailed',failed);if(context)await context.close();}
    row.consoleDiagnostics=classifyS25Errors(state,origin,consoleErrors,httpResponses,failedRequests,row.expectedHttpErrors||[]);
    errors.push(...row.consoleDiagnostics.errors);
    if(errors.length){row.verdict='CAPTURE-FAILED';row.measured=false;}
    return row;
}
