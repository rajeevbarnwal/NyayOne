import {createHash} from 'node:crypto';
import pixelmatch from 'pixelmatch';
import {coverage,VIEWPORTS} from './nyay66-conformance.mjs';
import {R2_VIEWPORTS} from './nyay66-r2.mjs';
export const LIMITS={pixelRatio:0.001,mean:0.25,geometry:1};
export const canonical=value=>JSON.stringify(value,(_,item)=>item&&typeof item==='object'&&!Array.isArray(item)?Object.fromEntries(Object.entries(item).sort(([a],[b])=>a.localeCompare(b))):item);
export const digest=value=>createHash('sha256').update(value).digest('hex');
export function enforcePins(expected,actual){
  for(const key of ['chromium','playwright','platform','sourceSha256','fonts'])if(!expected[key]||canonical(expected[key])!==canonical(actual[key]))throw Error(`PIN_MISMATCH:${key}`);
  return true;
}
export function validateProgression(before,after,options){
  const allowed=coverage('light',options).filter(x=>x.status!=='DESIGN-GAP').map(x=>x.screen);
  if(!Array.isArray(before)||!Array.isArray(after)||new Set(after).size!==after.length||before.some(x=>!after.includes(x))||after.some(x=>!allowed.includes(x)))throw Error('ENFORCEMENT_REGRESSION');
  return true;
}
export function pixelMetrics(a,b,masks){
  if(a.width!==b.width||a.height!==b.height)throw Error('DIMENSION_MISMATCH');
  const left=Buffer.from(a.data),right=Buffer.from(b.data),excluded=new Set();
  for(const box of masks){
    if(!['x','y','width','height'].every(k=>Number.isFinite(box[k]))||box.width<=0||box.height<=0||box.x<0||box.y<0||box.x+box.width>a.width+1||box.y+box.height>a.height+1)throw Error('INVALID_MASK');
    for(let y=Math.floor(box.y);y<Math.min(a.height,Math.ceil(box.y+box.height));y++)for(let x=Math.floor(box.x);x<Math.min(a.width,Math.ceil(box.x+box.width));x++)excluded.add(y*a.width+x);
  }
  if(excluded.size>a.width*a.height*0.05)throw Error('MASK_COVERAGE_EXCEEDED');
  let sum=0;
  for(let p=0;p<a.width*a.height;p++){
    if(excluded.has(p)){left.fill(255,p*4,p*4+4);right.fill(255,p*4,p*4+4);}
    else for(let c=0;c<3;c++)sum+=Math.abs(left[p*4+c]-right[p*4+c]);
  }
  const pixels=a.width*a.height-excluded.size;
  const diff=Buffer.alloc(left.length);
  const mismatch=pixelmatch(left,right,diff,a.width,a.height,{threshold:0.1,includeAA:false});
  return {mismatchRatio:mismatch/pixels,meanAbsDiff:sum/(pixels*3),excludedPixels:excluded.size,pass:mismatch/pixels<=LIMITS.pixelRatio&&sum/(pixels*3)<=LIMITS.mean,diff};
}
const geometry=(a,b)=>a&&b&&['x','y','width','height'].every(k=>Number.isFinite(a[k])&&Number.isFinite(b[k])&&Math.abs(a[k]-b[k])<=LIMITS.geometry);
export function compareStructure(a,b,expectedClocks){
  const errors=[];
  if(a.text!==b.text)errors.push('text');
  const identity=controls=>controls.map(({role,name,disabled})=>({role,name,disabled}));
  if(canonical(identity(a.controls))!==canonical(identity(b.controls)))errors.push('controls');
  if(canonical(a.headings.map(x=>x.text))!==canonical(b.headings.map(x=>x.text)))errors.push('headings');
  if(a.controls.length!==b.controls.length||a.controls.some((x,i)=>!geometry(x.box,b.controls[i]?.box))||a.headings.length!==b.headings.length||a.headings.some((x,i)=>!geometry(x.box,b.headings[i]?.box)))errors.push('geometry');
  if(a.masks.length!==expectedClocks||b.masks.length!==expectedClocks||[...a.masks,...b.masks].some(x=>x.kind!=='otp-clock'||!/^\d{2}:[0-5]\d$/.test(x.text))||a.masks.some((x,i)=>!geometry(x.box,b.masks[i]?.box)))errors.push('dynamic-regions');
  if(b.overflow!==0)errors.push('overflow');
  return errors;
}
// PR comments are fetched using GitHub's authenticated read API by the job.
// No key provisioning or independent signed-receipt mechanism is involved.
export function approveException(entry,comments,options){
  const available=coverage('light',options).find(x=>x.screen===entry?.screen&&x.status!=='DESIGN-GAP');
  const viewports=available?.source==='r2'?['mobile390','mobile360','desktop']:['mobile390','desktop'];
  if(!entry||!available||!Number.isSafeInteger(entry.approvalPr)||entry.approvalPr<=0||!viewports.includes(entry.viewport)||entry.theme!=='light'||!['referenceSha256','liveSha256'].every(k=>/^[a-f0-9]{64}$/.test(entry[k]))||!Array.isArray(entry.checks)||!entry.checks.length||entry.checks.some(x=>!['pixels','text','controls','headings','geometry'].includes(x)))return false;
  const hash=digest(canonical(entry));
  if(comments===null)return hash;
  return Array.isArray(comments)&&comments.some(comment=>Number.isSafeInteger(comment.id)&&comment.id>0&&comment.approvalPr===entry.approvalPr&&comment.user?.login==='rajeevbarnwal'&&comment.body?.trim()===`NYAY66-EXCEPTION ${hash}`);
}

// Derive the required state/viewport inventory from the same approved coverage
// registry as capture, not from the rows that happened to be emitted.
export function lightRowInventory(options){
  return coverage('light',options).filter(item=>item.status!=='DESIGN-GAP').flatMap(item=>
    (item.source==='r2'?R2_VIEWPORTS:VIEWPORTS).flatMap(vp=>item.views.map(view=>({
      screen:item.screen,
      // S-06's existing live fixture records its source view as row.state.
      state:item.screen==='S-06'?view:['r2','s18'].includes(item.source)?`${item.screen}-${view.slice(4)}`:item.screen==='S-10'&&view==='s10b'?'S-10-academic':item.screen,
      viewport:vp.id,theme:'light',
    }))));
}
const rowKey=row=>`${row.screen}:${row.state}:${row.viewport}`;
const hashField=value=>typeof value==='string'&&/^[a-f0-9]{64}$/.test(value);

export function finalizeEnforcement(rows,config,comments,options){
  validateProgression([],config.enforced,options);
  if(!Array.isArray(config.exceptions)||config.exceptions.some(entry=>!approveException(entry,comments,options)))throw Error('OWNER_EXCEPTION_APPROVAL_MISSING');
  if(!Array.isArray(rows))throw Error('INVALID_CAPTURE_ROWS');
  const inventory=lightRowInventory(options),known=new Set(inventory.map(rowKey));
  const required=inventory.filter(row=>config.enforced.includes(row.screen));
  const seen=new Set(),failures=[];
  const evaluated=rows.map(original=>{
    const row={...original};
    if(row.theme==='light'){
      const key=rowKey(row);
      if(!known.has(key))failures.push(`UNKNOWN_LIGHT_ROW:${key}`);
      if(seen.has(key))failures.push(`DUPLICATE_LIGHT_ROW:${key}`);
      seen.add(key);
      if(row.executed===true&&row.verdict!=='CAPTURE-FAILED'){
        const proof=hashField(row.referenceSha256)&&hashField(row.liveSha256)
          &&typeof row.metrics?.pass==='boolean'&&Array.isArray(row.regions)
          &&row.regions.every(region=>typeof region.pass==='boolean')
          &&Array.isArray(row.structure)&&Array.isArray(row.accessibility)&&Array.isArray(row.errors);
        const resolved=row.state==='S-01-resolved';
        const route=row.liveRouteBehavior;
        const componentProof=!resolved||(row.evidenceKind==='component-visual'&&row.coverageApproval==='NYAY-77:15493'
          &&route?.executed===true&&route.from==='/s-01'&&route.to==='/s-07'&&route.syntheticServer===true
          &&route.artificialDelay===false&&route.navigationFrozen===false);
        const sessionProof=row.state!=='S-18-session'||(row.evidenceKind==='component-visual'&&row.coverageApproval==='NYAY-88:16029'
          &&route?.executed===true&&route.from==='/s-18'&&route.to==='/s-03'&&route.syntheticServer===true
          &&route.artificialDelay===false&&route.navigationFrozen===false);
        if(!proof||!componentProof||!sessionProof){row.verdict='CAPTURE-FAILED';row.failure='MEASURED_PROOF_INCOMPLETE';}
        else{
          const violations=[...row.structure,...(!row.metrics.pass||row.regions.some(region=>!region.pass)?['pixels']:[]),
            ...(row.accessibility.some(v=>['serious','critical'].includes(v.impact))?['accessibility']:[])];
          const approved=config.exceptions.filter(entry=>entry.screen===row.screen&&entry.viewport===row.viewport&&entry.theme===row.theme
            &&entry.referenceSha256===row.referenceSha256&&entry.liveSha256===row.liveSha256);
          row.exceptionsApplied=approved;
          row.remaining=violations.filter(check=>!approved.some(entry=>entry.checks.includes(check)));
          row.verdict=row.errors.length?'CAPTURE-FAILED':row.remaining.length?'NONCONFORMANT':approved.length?'PARITY-WITH-DISCLOSED-DELTA':'PARITY';
        }
      }
    }
    const passing=row.executed===true&&['PARITY','PARITY-WITH-DISCLOSED-DELTA'].includes(row.verdict);
    row.blocking=row.verdict==='CAPTURE-FAILED'||row.theme==='light'&&config.enforced.includes(row.screen)&&!passing;
    return row;
  });
  for(const row of required)if(!seen.has(rowKey(row)))failures.push(`MISSING_LIGHT_ROW:${rowKey(row)}`);
  return {rows:evaluated,expectedLightRows:required.length,failures,blocking:failures.length>0||evaluated.some(row=>row.blocking)};
}
