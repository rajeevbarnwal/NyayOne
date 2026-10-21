import {S25_STATES,S25_VIEWPORTS} from './nyay66-s25-reference.mjs';
import {inspectSurface} from './nyay66-dom.mjs';

// The approved library's bare mode removes reviewer chrome; its desktop .vp
// retains an 8px device-frame radius. Only that reviewer radius is normalized.
// No application descendant, token, spacing, text or control is rewritten.
export function removeS25ReviewerClipping(){
  const viewport=document.querySelector('.vp');
  if(!viewport||document.body.dataset.bare!=='1')throw Error('S25_REVIEWER_NOT_BARE');
  viewport.style.borderRadius='0px';
}
export async function captureS25Sample(page,origin,state,viewport){
  if(!S25_STATES.includes(state)||!S25_VIEWPORTS.some(v=>JSON.stringify(v)===JSON.stringify(viewport)))throw Error('S25_CAPTURE_SCOPE');
  await page.goto(`${origin}/#/S-25?state=${state}&dev=${viewport.preset}&cap=1`);
  await page.waitForFunction(()=>window.__lib?.dbg().pending===false&&window.__lib.dbg().applying===0);
  const handle=await page.locator('iframe[data-src="cont"]').elementHandle();
  const frame=await handle.contentFrame();
  if(!frame)throw Error('S25_CAPTURE_FRAME_MISSING');
  await frame.waitForFunction(({state,preset})=>document.body.dataset.bare==='1'&&location.hash===`#/s-25?state=${state}&dev=${preset}`,{state,preset:viewport.preset});
  await frame.evaluate(removeS25ReviewerClipping);
  await frame.evaluate(async()=>{await document.fonts.ready;await Promise.all([...document.images].map(i=>i.decode()));await new Promise(done=>requestAnimationFrame(()=>requestAnimationFrame(done)));});
  const geometry=await frame.locator('.vp').evaluate(el=>{const b=el.getBoundingClientRect();return {width:b.width,height:b.height,x:b.x,y:b.y,borderRadius:getComputedStyle(el).borderRadius};});
  if(geometry.width!==viewport.width||geometry.height<viewport.height||geometry.x!==0||geometry.y!==0||geometry.borderRadius!=='0px'
    ||page.viewportSize()?.width!==viewport.width||page.viewportSize()?.height!==viewport.height)throw Error('S25_CAPTURE_VIEWPORT_MISMATCH');
  const surface=await frame.evaluate(inspectSurface,{reference:true});
  const fontStack=await frame.evaluate(()=>({viewport:getComputedStyle(document.querySelector('.vp')).fontFamily,
    faces:[...document.fonts].map(f=>({family:f.family,weight:f.weight,style:f.style,status:f.status}))}));
  // Capture the declared browser viewport, just like the live gate. Some design
  // states extend below the fold; never shrink/reflow them to fit. Surface
  // metadata retains its full content height, distinct from PNG dimensions.
  const bytes=await page.screenshot({animations:'disabled',fullPage:false});
  return {bytes,surface,fontStack,reviewerFrame:{x:geometry.x,y:geometry.y,borderRadius:geometry.borderRadius}};
}
