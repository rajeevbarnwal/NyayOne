import {S35_STATES,S35_VIEWPORTS} from './nyay66-s35-reference.mjs';
import {inspectSurface} from './nyay66-dom.mjs';

// The approved library's bare mode removes reviewer chrome; its desktop .vp
// retains an 8px device-frame radius. Only that reviewer radius is normalized.
// No application descendant, token, spacing, text or control is rewritten.
export function removeS35ReviewerClipping(){
  const viewport=document.querySelector('.vp');
  if(!viewport||document.body.dataset.bare!=='1')throw Error('S35_REVIEWER_NOT_BARE');
  viewport.style.borderRadius='0px';
}
export async function captureS35Sample(page,origin,state,viewport){
  if(!S35_STATES.includes(state)||!S35_VIEWPORTS.some(v=>JSON.stringify(v)===JSON.stringify(viewport)))throw Error('S35_CAPTURE_SCOPE');
  const reviewJourney=['review-moderation','review-edit','review-window-closed','review-delete-confirm','review-deleted','review-delete-failed'].includes(state);
  await page.goto(`${origin}/#/S-35?state=${reviewJourney?'review':state}&dev=${viewport.preset}&cap=1`);
  await page.waitForFunction(()=>window.__lib?.dbg().pending===false&&window.__lib.dbg().applying===0);
  const handle=await page.locator('iframe[data-src="cont"]').elementHandle();
  const frame=await handle.contentFrame();
  if(!frame)throw Error('S35_CAPTURE_FRAME_MISSING');
  // The frozen library writes its eligible sample session into review URLs and
  // drops dev there. Verify the source-defined rewrite, then verify real geometry.
  async function waitForState(expected){
    await frame.waitForFunction(({state,preset})=>{
      const [route,query]=location.hash.split('?'),p=new URLSearchParams(query);
      return document.body.dataset.bare==='1'&&route==='#/s-35'&&p.get('state')===state
        &&(p.get('dev')===preset||(/^review/.test(state)&&p.get('session')==='se-2207'));
    },{state:expected,preset:viewport.preset});
  }
  await waitForState(reviewJourney?'review':state);
  if(reviewJourney){
    // Genuine prototype actions, never direct fixture/DOM mutation: review
    // edit/delete states deliberately have no record until one is created.
    await frame.locator('[data-star="4"]').click();
    await frame.locator('#rvt').fill('The session clarified the next steps for my moot preparation.');
    await frame.locator('[data-rvcreate5]').click();
    await waitForState('review-moderation');
    const target=state==='review-deleted'?'review-delete-confirm':state;
    await frame.evaluate(({target,preset,closed})=>{
      location.hash=`#/s-35?state=${target}&session=se-2207&dev=${preset}${closed?'&now=2026-08-25T07:00:00Z':''}`;
    },{target,preset:viewport.preset,closed:state==='review-window-closed'});
    await waitForState(target);
    if(state==='review-deleted'){await frame.locator('[data-rvdel6]').click();await waitForState(state);}
    const expectedText={ 'review-moderation':'Review saved. Moderation pending.', 'review-edit':'Your review',
      'review-window-closed':'The edit window has closed.', 'review-delete-confirm':'Delete this review?',
      'review-deleted':'Review deleted.', 'review-delete-failed':'We could not delete your review.' };
    await frame.getByText(expectedText[state],{exact:true}).waitFor();
  }
  await frame.evaluate(removeS35ReviewerClipping);
  await frame.evaluate(async()=>{await document.fonts.ready;await Promise.all([...document.images].map(i=>i.decode()));await new Promise(done=>requestAnimationFrame(()=>requestAnimationFrame(done)));});
  const geometry=await frame.locator('.vp').evaluate(el=>{const b=el.getBoundingClientRect();return {width:b.width,height:b.height,x:b.x,y:b.y,borderRadius:getComputedStyle(el).borderRadius};});
  if(geometry.width!==viewport.width||geometry.height<viewport.height||geometry.x!==0||geometry.y!==0||geometry.borderRadius!=='0px'
    ||page.viewportSize()?.width!==viewport.width||page.viewportSize()?.height!==viewport.height)throw Error('S35_CAPTURE_VIEWPORT_MISMATCH');
  const surface=await frame.evaluate(inspectSurface,{reference:true});
  const fontStack=await frame.evaluate(()=>({viewport:getComputedStyle(document.querySelector('.vp')).fontFamily,
    faces:[...document.fonts].map(f=>({family:f.family,weight:f.weight,style:f.style,status:f.status}))}));
  // Capture the declared browser viewport, just like the live gate. Some design
  // states extend below the fold; never shrink/reflow them to fit. Surface
  // metadata retains its full content height, distinct from PNG dimensions.
  const bytes=await page.screenshot({animations:'disabled',fullPage:false});
  return {bytes,surface,fontStack,reviewerFrame:{x:geometry.x,y:geometry.y,borderRadius:geometry.borderRadius}};
}
