// Approved design-source intake only. No raster baseline or product pass is claimed.
import {readFile} from 'node:fs/promises';
import {resolve} from 'node:path';
import {createHash} from 'node:crypto';
import {execFileSync} from 'node:child_process';
export const CONTINUATION_ARCHIVE_SHA256='0476ec549b3776cc33af52692f71a4029404443f4f02f5b0485b02d5f38cf964';
const DIRECTORY='frontend/test-baselines/nyay66/v3.2.1.08';
const ARCHIVE=`${DIRECTORY}/NYAYONE_S01_S35_v3.2.1.08.zip`;
const PREFIX='NYAYONE_S01_S35_v3.2.1.08/';
const COUNTS={'S-18':10,'S-19':26,'S-20':10,'S-21':8,'S-25':6,'S-26':4,'S-27':11,'S-28':7,'S-29':6,'S-30':8,'S-31':8,'S-32':11,'S-33':14,'S-34':6,'S-35':56};
const VIEWPORTS=[{id:'mobile390',width:390,height:844},{id:'desktop',width:1440,height:1024}];
const sha=bytes=>createHash('sha256').update(bytes).digest('hex');
export function designAssets(html){
  const marker='<script type="text/plain" id="src-cont">',start=html.indexOf(marker);
  if(start<0)throw Error('CONTINUATION_SOURCE_MISSING');
  const source=html.slice(start+marker.length,html.indexOf('</script>',start+marker.length)).split('<\uE000').join('<');
  const fonts=[...source.matchAll(/@font-face\s*\{([^}]+)\}/g)].map(([,css])=>({
    family:css.match(/font-family:\s*([^;]+)/)?.[1],weight:css.match(/font-weight:\s*([^;]+)/)?.[1],
    sha256:sha(Buffer.from(css.match(/base64,([^)'"\s]+)/)?.[1]||'','base64')),
  }));
  const logos=[...source.matchAll(/\b([A-Z_]+)\s*=\s*`(<svg[\s\S]*?<\/svg>)`/g)].map(([,name,svg])=>({name,sha256:sha(svg)}));
  if(!fonts.length||logos.length!==4)throw Error('CONTINUATION_ASSETS_MISSING');
  return {sourceSha256:sha(source),fontFaces:fonts,logoDefinitions:logos};
}
export function validateContinuation(data,archive){
  if(data?.schema!==1||data.version!=='v3.2.1.08'||data.archive!==ARCHIVE||data.archiveSha256!==CONTINUATION_ARCHIVE_SHA256||sha(archive)!==CONTINUATION_ARCHIVE_SHA256)throw Error('CONTINUATION_ARCHIVE_MISMATCH');
  if(JSON.stringify(data.viewports)!==JSON.stringify(VIEWPORTS)||data.pngBaselinesImported!==false||data.designApproval!=='NYAY-90:16011')throw Error('CONTINUATION_SCOPE_MISMATCH');
  if(!Array.isArray(data.screens)||data.screens.length!==15||JSON.stringify(data.screens.map(s=>s.screen))!==JSON.stringify(Object.keys(COUNTS)))throw Error('CONTINUATION_SCREEN_INVENTORY');
  for(const s of data.screens){
    if(typeof s.route!=='string'||!s.route.startsWith(s.screen.toLowerCase().replace('s-','/s-'))||!Array.isArray(s.states)||s.states.length!==COUNTS[s.screen]||new Set(s.states.map(x=>x[0])).size!==s.states.length||s.states.some(x=>!Array.isArray(x)||x.length!==2||x.some(v=>typeof v!=='string'||!v)))throw Error('CONTINUATION_STATE_INVENTORY');
  }
  if(data.inventory?.scope!=='approved-design-source-only'||!Array.isArray(data.inventory.fonts)||!data.inventory.fonts.length||data.inventory.logo?.kind!=='inline-svg')throw Error('CONTINUATION_ASSET_INVENTORY');
  return data;
}
export async function loadContinuation(root){
  const data=JSON.parse(await readFile(resolve(root,DIRECTORY,'manifest.json'),'utf8'));
  const archivePath=resolve(root,ARCHIVE),bytes=await readFile(archivePath);
  validateContinuation(data,bytes);
  // Read approved regular archive bytes without executing any shipped helper or
  // extracting paths into the workspace. SHA verification precedes ZIP parsing.
  const member=name=>execFileSync('unzip',['-p',archivePath,PREFIX+name],{maxBuffer:10*1024*1024});
  const sums=member('SHA256SUMS.txt').toString().trim().split(/\r?\n/);
  if(sums.length!==22)throw Error('CONTINUATION_MANIFEST_COUNT');
  for(const line of sums){
    const match=/^([a-f0-9]{64})\s+\*?(.+)$/.exec(line);
    if(!match||match[2].startsWith('/')||match[2].split('/').some(x=>x==='..')||sha(member(match[2]))!==match[1])throw Error('CONTINUATION_MEMBER_MISMATCH');
  }
  const states=JSON.parse(member('source/continuation-states.json'));
  if(JSON.stringify(Object.fromEntries(data.screens.map(s=>[s.screen,s.states])))!==JSON.stringify(states))throw Error('CONTINUATION_STATE_SOURCE_MISMATCH');
  const html=member('NYAYONE_S01_S35_v3.2.1.08.html');
  if(sha(html)!==data.htmlSha256)throw Error('CONTINUATION_HTML_MISMATCH');
  if(JSON.stringify(designAssets(html.toString()))!==JSON.stringify(data.inventory.embeddedResources))throw Error('CONTINUATION_ASSET_SOURCE_MISMATCH');
  return data;
}
export function continuationRows(data){
  return data.screens.flatMap(s=>data.viewports.flatMap(vp=>s.states.map(([state,description])=>({
    screen:s.screen,state:`${s.screen}-${state}`,designState:state,description,route:s.route,viewport:vp.id,theme:'light',
    verdict:'DESIGN-GAP',executed:false,measured:false,designApproved:true,blocking:false,
    reason:'Approved design source; hosted PNG baseline and product fixture not measured. Not a pass.',
    sourceVersion:data.version,sourceArchiveSha256:data.archiveSha256,
  }))));
}
export function appendContinuation(report,data,{s18=false}={}){
  let rows=continuationRows(data);const ids=new Set(data.screens.map(s=>s.screen));
  if(report.rows.some(r=>r.theme==='light'&&ids.has(r.screen)&&!(s18&&r.screen==='S-18')))throw Error('CONTINUATION_ALREADY_REPORTED');
  let measuredLightRows=0;
  if(s18){
    const expected=new Set(rows.filter(r=>r.screen==='S-18'&&r.designState!=='option-manual').map(r=>`${r.state}:${r.viewport}`));
    const found=report.rows.filter(r=>r.theme==='light'&&r.screen==='S-18');
    for(const row of found)if(!expected.delete(`${row.state}:${row.viewport}`))throw Error('S18_MEASURED_COVERAGE_INCOMPLETE');
    if(expected.size)throw Error('S18_MEASURED_COVERAGE_INCOMPLETE');
    measuredLightRows=found.filter(r=>r.executed===true&&r.measured===true&&r.verdict!=='CAPTURE-FAILED').length;
    rows=rows.filter(r=>r.screen!=='S-18'||r.designState==='option-manual');
  }
  // Existing finalizer's verdict, failures, 74 required rows and blocking result
  // are preserved verbatim. These source-only rows cannot authorize promotion.
  return {...report,rows:[...report.rows,...rows],continuation:{version:data.version,archiveSha256:data.archiveSha256,
    designApproval:data.designApproval,screens:15,states:191,unmeasuredLightRows:382-measuredLightRows,pngBaselinesImported:false,
    ...(s18?{rasterizedScreens:['S-18'],importedReferenceRows:18,measuredLightRows}: {})}};
}
