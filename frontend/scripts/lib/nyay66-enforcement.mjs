import {createHash} from 'node:crypto';
import pixelmatch from 'pixelmatch';
import {coverage} from './nyay66-conformance.mjs';
export const LIMITS={pixelRatio:0.001,mean:0.25,geometry:1};
export const canonical=value=>JSON.stringify(value,(_,item)=>item&&typeof item==='object'&&!Array.isArray(item)?Object.fromEntries(Object.entries(item).sort(([a],[b])=>a.localeCompare(b))):item);
export const digest=value=>createHash('sha256').update(value).digest('hex');
export function enforcePins(expected,actual){
  for(const key of ['chromium','playwright','platform','sourceSha256','fonts'])if(!expected[key]||canonical(expected[key])!==canonical(actual[key]))throw Error(`PIN_MISMATCH:${key}`);
  return true;
}
export function validateProgression(before,after){
  const allowed=coverage().filter(x=>x.status!=='DESIGN-GAP').map(x=>x.screen);
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
export function approveException(entry,comments){
  if(!entry||!coverage().some(x=>x.screen===entry.screen&&x.status!=='DESIGN-GAP')||!['mobile390','desktop'].includes(entry.viewport)||entry.theme!=='light'||!['referenceSha256','liveSha256'].every(k=>/^[a-f0-9]{64}$/.test(entry[k]))||!Array.isArray(entry.checks)||!entry.checks.length||entry.checks.some(x=>!['pixels','text','controls','headings','geometry'].includes(x)))return false;
  const hash=digest(canonical(entry));
  if(comments===null)return hash;
  return Array.isArray(comments)&&comments.some(comment=>comment.user?.login==='rajeevbarnwal'&&comment.body?.trim()===`NYAY66-EXCEPTION ${hash}`);
}
