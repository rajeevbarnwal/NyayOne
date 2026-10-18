// S-19-only additive capture. Reference ingestion never counts as measurement.
import {writeFile,readFile} from 'node:fs/promises';
import {resolve} from 'node:path';
import {createRequire} from 'node:module';
import {PNG} from 'pngjs';
import {digest,pixelMetrics,compareStructure} from './nyay66-enforcement.mjs';
import {inspectSurface} from './nyay66-dom.mjs';
import {S19_VIEWPORTS,verifyS19PNG} from './nyay66-s19-reference.mjs';
import {S19_MEASURED_STATES} from './nyay66-s19-coverage.mjs';
import {mockS19Application,classifyS19Errors} from './nyay66-s19-fixtures.mjs';
const require=createRequire(import.meta.url);
function crop(png,box){
  const x=Math.max(0,Math.floor(box.x)),y=Math.max(0,Math.floor(box.y));
  const width=Math.min(png.width-x,Math.ceil(box.width)),height=Math.min(png.height-y,Math.ceil(box.height));
  if(width<=0||height<=0)throw Error('REGION_OUTSIDE_VIEWPORT');
  const out=new PNG({width,height});PNG.bitblt(png,out,x,y,width,height,0,0);return out;
}
export async function captureS19Rows({browser,origin,out,reference}){
  const rows=[];
  for(const state of S19_MEASURED_STATES)for(const vp of S19_VIEWPORTS){
    const name=`S-19-${state}-${vp.id}`,errors=[];
    const row={screen:'S-19',state:`S-19-${state}`,designState:state,viewport:vp.id,theme:'light',source:'s19',executed:false,measured:false,errors};
    let context,page;const consoleErrors=[],httpResponses=[],failed=()=>errors.push('NETWORK_ERROR');
    try{
      const ref=reference.manifest.rows.find(r=>r.view===`s19-${state}`&&r.viewport===vp.id);
      if(!ref)throw Error('S19_REFERENCE_MISSING');
      const referenceBytes=await readFile(resolve(reference.cache,ref.file));verifyS19PNG(ref,referenceBytes);
      context=await browser.newContext({viewport:{width:vp.width,height:vp.height},deviceScaleFactor:1,locale:'en-IN',timezoneId:'Asia/Kolkata',colorScheme:'light',reducedMotion:'reduce',serviceWorkers:'block'});
      page=await context.newPage();page.setDefaultTimeout(10000);
      page.on('requestfailed',failed);page.on('pageerror',()=>errors.push('PAGE_ERROR'));
      page.on('console',m=>{if(m.type()==='error')consoleErrors.push({text:m.text(),url:m.location().url});});
      page.on('response',r=>{if(r.status()>=400)httpResponses.push({method:r.request().method(),url:r.url(),status:r.status()});});
      Object.assign(row,await mockS19Application(page,state,origin,errors));
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
    row.consoleDiagnostics=classifyS19Errors(state,origin,consoleErrors,httpResponses,row.expectedHttpErrors||[]);
    errors.push(...row.consoleDiagnostics.errors);
    if(errors.length){row.verdict='CAPTURE-FAILED';row.measured=false;}
    rows.push(row);
    if(process.env.NYAY91_FIXTURE_DIAGNOSTIC)console.log(JSON.stringify({state,viewport:vp.id,executed:row.executed,errors:row.errors,failure:row.failure}));
  }
  return rows;
}
