import {describe,it,expect} from 'vitest';
import {readFileSync,mkdtempSync,writeFileSync,rmSync} from 'node:fs';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import {execFileSync} from 'node:child_process';
import {fileURLToPath} from 'node:url';
import {PNG} from 'pngjs';
import {digest} from './nyay66-enforcement.mjs';
import {loadS18Source,S18_STATES,S18_VIEWPORTS,S18_PINS} from './nyay66-s18-reference.mjs';
import {verifyS18Archive,loadS18Cache} from './nyay66-s18-import.mjs';
const root=fileURLToPath(new URL('../../../',import.meta.url));
const {data}=await loadS18Source(root);
const policy=JSON.parse(readFileSync(join(root,'frontend/scripts/nyay66-policy.json')));
const fonts=JSON.parse(readFileSync(join(root,'frontend/test-baselines/nyay66',policy.cache,'manifest.json'))).fonts;
const sourceHead='a'.repeat(40),controlHead='b'.repeat(40);
const pngs=new Map(S18_VIEWPORTS.map(vp=>[vp.id,PNG.sync.write(new PNG({width:vp.width,height:vp.height}))]));
function archiveFixture(change=()=>{}){
  const dir=mkdtempSync(join(tmpdir(),'nyay-s18-import-test-'));
  const files=new Map(),rows=[];
  for(const state of S18_STATES)for(const vp of S18_VIEWPORTS){
    const bytes=pngs.get(vp.id),sha256=digest(bytes),file=`s18-${state}-${vp.id}-0.png`;
    files.set(file,bytes);rows.push({view:`s18-${state}`,viewport:vp.id,file,sha256,sampleHashes:Array(3).fill(sha256),dimensions:[vp.width,vp.height],
      surface:{controls:[],headings:[],masks:[],text:'synthetic',overflow:0,dimensions:[vp.width,vp.height]},fontStack:{viewport:'Public Sans',faces:[]},reviewerFrame:{borderRadius:'0px',x:0,y:0}});
  }
  const manifest={schema:1,purpose:'UNIMPORTED_REFERENCE_CALIBRATION',screen:'S-18',theme:'light',approval:data.designApproval,sourceArchiveSha256:data.archiveSha256,sourceSha256:data.htmlSha256,embeddedResources:data.inventory.embeddedResources,producerHead:sourceHead,controlHead,...S18_PINS,fonts,deferredStates:['option-manual'],rows};
  change(manifest,files);
  files.set('manifest.json',Buffer.from(JSON.stringify(manifest)));
  files.set('runtime-pins.json',Buffer.from(JSON.stringify({purpose:'REFERENCE_GENERATION_ONLY_NOT_IMPORT_APPROVAL',sourceHead,reference:'s18-v32108',...S18_PINS,node:'v22.21.1',fonts})));
  files.set('SHA256SUMS',Buffer.from([...files].map(([name,bytes])=>`${digest(bytes)}  ${name}`).join('\n')+'\n'));
  for(const [name,bytes] of files)writeFileSync(join(dir,name),bytes);
  const path=join(dir,'calibration.zip');execFileSync('zip',['-q',path,...files.keys()],{cwd:dir});
  return {dir,path,expected:{archiveSha256:digest(readFileSync(path)),sourceHead,controlHead},files};
}
describe('S-18 archive import fails closed before writing',()=>{
  it('verifies the ZIP itself, every PNG, runtime pins and exact 18-row inventory',async()=>{
    const f=archiveFixture();try{const got=await verifyS18Archive(f.path,f.expected,data,fonts);expect(got.manifest.rows).toHaveLength(18);expect(got.files.size).toBe(21);expect(got.archiveSha256).toBe(f.expected.archiveSha256);}finally{rmSync(f.dir,{recursive:true,force:true});}
  });
  it('rejects a tampered archive even if the caller supplies the formerly valid digest',async()=>{
    const f=archiveFixture();try{writeFileSync(f.path,Buffer.concat([readFileSync(f.path),Buffer.from('tampered')]));await expect(verifyS18Archive(f.path,f.expected,data,fonts)).rejects.toThrow('S18_ARCHIVE_DIGEST_MISMATCH');}finally{rmSync(f.dir,{recursive:true,force:true});}
  });
  it('rejects a tampered PNG even when ZIP digest and checksum list have been recomputed',async()=>{
    const f=archiveFixture((_m,files)=>{const [name,bytes]=files.entries().next().value;const altered=Buffer.from(bytes);altered[30]^=1;files.set(name,altered);});
    try{await expect(verifyS18Archive(f.path,f.expected,data,fonts)).rejects.toThrow('S18_REFERENCE_BYTES_MISMATCH');}finally{rmSync(f.dir,{recursive:true,force:true});}
  });
  it('rejects missing states, different producer/control heads and changed pins',async()=>{
    for(const change of [m=>m.rows.pop(),m=>m.producerHead='c'.repeat(40),m=>m.controlHead='c'.repeat(40),m=>m.chromium='wrong',m=>m.fonts={}]){
      const f=archiveFixture(change);try{await expect(verifyS18Archive(f.path,f.expected,data,fonts)).rejects.toThrow();}finally{rmSync(f.dir,{recursive:true,force:true});}
    }
  });
  it('requires an explicit safe cache binding; an absent cache does not fabricate coverage',async()=>{
    expect(await loadS18Cache(root,undefined,data,fonts)).toBe(null);
    await expect(loadS18Cache(root,{cache:'../escape'},data,fonts)).rejects.toThrow('S18_INVALID_CACHE_BINDING');
  });
  it('rechecks the actual owner-generated cache at use, including all 18 PNG digests',async()=>{
    const got=await loadS18Cache(root,{cache:'s18-v32108-chromium-149.0.7827.55-36565721312',manifestSha256:'38aa36b79f8dc7cc9bbdbdbc9b1ce26626f34a52cc253f3e317d59a9ff2ba5e9',provenanceSha256:'788ccd74f7f3b49576bbb59e5b2fd445aa246bf76c963742bfbd6e33f9e49ea3'},data,fonts);
    expect(got.manifest.rows).toHaveLength(18);
    expect(got.provenance.runId).toBe('36565721312');
    expect(got.manifest.producerHead).toBe('132fedbbd1bcc5a22c3d7d0281499c77d029df33');
    expect(got.manifest.controlHead).toBe('33d7851cfddd30139066b708b3e8db9ddc8733b2');
  });
});
