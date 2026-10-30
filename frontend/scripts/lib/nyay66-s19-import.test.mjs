import {s26Proposals,withoutS26ProposalsForTest} from './nyay66-s26-exceptions.test-fixture.mjs';
import {describe,it,expect} from 'vitest';
import {s25Proposals,withoutS25ProposalsForTest} from './nyay66-s25-exceptions.test-fixture.mjs';
import {readFileSync,mkdtempSync,writeFileSync,rmSync,mkdirSync,symlinkSync} from 'node:fs';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import {execFileSync} from 'node:child_process';
import {fileURLToPath} from 'node:url';
import {PNG} from 'pngjs';
import {digest} from './nyay66-enforcement.mjs';
import {loadS19Source,S19_STATES,S19_VIEWPORTS,S19_PINS} from './nyay66-s19-reference.mjs';
import {verifyS19Archive,loadS19Cache} from './nyay66-s19-import.mjs';
import {s21Proposals,withoutS21ProposalsForTest} from './nyay66-s21-exceptions.test-fixture.mjs';
const root=fileURLToPath(new URL('../../../',import.meta.url));
const {data}=await loadS19Source(root);
const policy=JSON.parse(readFileSync(join(root,'frontend/scripts/nyay66-policy.json')));
const fonts=JSON.parse(readFileSync(join(root,'frontend/test-baselines/nyay66',policy.cache,'manifest.json'))).fonts;
const sourceHead='a'.repeat(40),controlHead='b'.repeat(40);
const pngs=new Map(S19_VIEWPORTS.map(vp=>[vp.id,PNG.sync.write(new PNG({width:vp.width,height:vp.height}))]));
function archiveFixture(change=()=>{}){
  const dir=mkdtempSync(join(tmpdir(),'nyay-s19-import-test-'));
  const files=new Map(),rows=[];
  for(const state of S19_STATES)for(const vp of S19_VIEWPORTS){
    const bytes=pngs.get(vp.id),sha256=digest(bytes),file=`s19-${state}-${vp.id}-0.png`;
    files.set(file,bytes);rows.push({view:`s19-${state}`,viewport:vp.id,file,sha256,sampleHashes:Array(3).fill(sha256),dimensions:[vp.width,vp.height],
      surface:{controls:[],headings:[],masks:[],text:'synthetic',overflow:0,dimensions:[vp.width,vp.height]},fontStack:{viewport:'Public Sans',faces:[]},reviewerFrame:{borderRadius:'0px',x:0,y:0}});
  }
  const manifest={schema:1,purpose:'UNIMPORTED_REFERENCE_CALIBRATION',screen:'S-19',theme:'light',approval:data.designApproval,sourceArchiveSha256:data.archiveSha256,sourceSha256:data.htmlSha256,embeddedResources:data.inventory.embeddedResources,producerHead:sourceHead,controlHead,...S19_PINS,fonts,deferredStates:[],rows};
  change(manifest,files);
  files.set('manifest.json',Buffer.from(JSON.stringify(manifest)));
  files.set('runtime-pins.json',Buffer.from(JSON.stringify({purpose:'REFERENCE_GENERATION_ONLY_NOT_IMPORT_APPROVAL',sourceHead,reference:'s19-v32108',...S19_PINS,node:'v22.21.1',fonts})));
  files.set('SHA256SUMS',Buffer.from([...files].map(([name,bytes])=>`${digest(bytes)}  ${name}`).join('\n')+'\n'));
  for(const [name,bytes] of files)writeFileSync(join(dir,name),bytes);
  const path=join(dir,'calibration.zip');execFileSync('zip',['-q',path,...files.keys()],{cwd:dir});
  return {dir,path,expected:{archiveSha256:digest(readFileSync(path)),sourceHead,controlHead},files};
}
describe('S-19 archive import fails closed before writing',()=>{
  it('verifies the ZIP itself, every PNG, runtime pins and exact 52-row inventory',async()=>{
    const f=archiveFixture();try{const got=await verifyS19Archive(f.path,f.expected,data,fonts);expect(got.manifest.rows).toHaveLength(52);expect(got.files.size).toBe(55);expect(got.archiveSha256).toBe(f.expected.archiveSha256);}finally{rmSync(f.dir,{recursive:true,force:true});}
  });
  it('rejects a tampered archive even if the caller supplies the formerly valid digest',async()=>{
    const f=archiveFixture();try{writeFileSync(f.path,Buffer.concat([readFileSync(f.path),Buffer.from('tampered')]));await expect(verifyS19Archive(f.path,f.expected,data,fonts)).rejects.toThrow('S19_ARCHIVE_DIGEST_MISMATCH');}finally{rmSync(f.dir,{recursive:true,force:true});}
  });
  it('rejects a tampered PNG even when ZIP digest and checksum list have been recomputed',async()=>{
    const f=archiveFixture((_m,files)=>{const [name,bytes]=files.entries().next().value;const altered=Buffer.from(bytes);altered[30]^=1;files.set(name,altered);});
    try{await expect(verifyS19Archive(f.path,f.expected,data,fonts)).rejects.toThrow('S19_REFERENCE_BYTES_MISMATCH');}finally{rmSync(f.dir,{recursive:true,force:true});}
  });
  it('rejects missing states, different producer/control heads and changed pins',async()=>{
    for(const change of [m=>m.rows.pop(),m=>m.producerHead='c'.repeat(40),m=>m.controlHead='c'.repeat(40),m=>m.chromium='wrong',m=>m.fonts={}]){
      const f=archiveFixture(change);try{await expect(verifyS19Archive(f.path,f.expected,data,fonts)).rejects.toThrow();}finally{rmSync(f.dir,{recursive:true,force:true});}
    }
  });
  it('requires an explicit safe cache binding; an absent cache does not fabricate coverage',async()=>{
    expect(await loadS19Cache(root,undefined,data,fonts)).toBe(null);
    await expect(loadS19Cache(root,{cache:'../escape'},data,fonts)).rejects.toThrow('S19_INVALID_CACHE_BINDING');
  });
  it.each(['current','proposed','s25-proposed','s26-proposed'])('revalidates the owner-dispatched 52-PNG cache and its exact provenance (%s exceptions)',async(mode)=>{
    expect(policy.s19).toEqual({cache:'s19-v32108-chromium-149.0.7827.55-39029544967',manifestSha256:'b3e1637089633cef983824d0fd65341e73de1497f0fa77f8ca515d6cb305f32c',provenanceSha256:'5d999acbbfae032d266047221c62ee8add9b488062412a3f878595ec01431bbf'});
    const got=await loadS19Cache(root,policy.s19,data,fonts);
    expect(got.manifest.rows).toHaveLength(52);
    expect(got.provenance.runId).toBe('39029544967');
    expect(got.provenance.artifactId).toBe('12099474372');
    expect(got.provenance.archiveSha256).toBe('42e208402d032613183474711c629efb4488a6613b4450f1e93d139d9dcf9030');
    expect(got.manifest.producerHead).toBe('32573e0333baa5bea6098e8399b4a7108770fac0');
    expect(got.manifest.controlHead).toBe('3d0e1201ea672c6f96b7a86703def2d3bffa69f5');
    const before=JSON.parse(execFileSync('git',['show','3d0e1201ea672c6f96b7a86703def2d3bffa69f5:frontend/scripts/nyay66-policy.json'],{cwd:root}));
    const current=structuredClone(policy),previous=structuredClone(before);
    // The additive S-26 cache is pinned by nyay66-s26-import.test.mjs.
    delete current.s19;delete current.s20;delete current.s21;delete current.s25;delete current.s26;delete current.integrityApproval;delete previous.integrityApproval;
    // S-25's exact cache/provenance is pinned by nyay66-s25-import.test.mjs;
    // only that additive field is excluded from this older policy snapshot.
    // S-21's additive cache is pinned by its exact-provenance import test;
    // every historical setting and exception below remains compared unchanged.
    // The additive S-20 cache has its own exact-provenance test, which also
    // compares every pre-existing setting against the post-S-19 main policy.
    // Additive S-19/S-20 exceptions have their own coverage/approval contracts;
    // the live gate still requires exact owner comments. Compare only the
    // exceptions present at this pre-S-19 snapshot, preserving their bytes/order.
    if(mode==='proposed')current.exceptions=[...current.exceptions.filter(e=>e.screen!=='S-21'),...structuredClone(s21Proposals)];
    if(mode==='s25-proposed')current.exceptions=[...current.exceptions.filter(e=>e.screen!=='S-25'),...structuredClone(s25Proposals)];
    if(mode==='s26-proposed')current.exceptions=[...current.exceptions.filter(e=>e.screen!=='S-26'),...structuredClone(s26Proposals)];
    current.exceptions=withoutS25ProposalsForTest(withoutS26ProposalsForTest(current.exceptions));
    current.exceptions=withoutS21ProposalsForTest(current.exceptions).filter(e=>!['S-19','S-20'].includes(e.screen));
    expect(JSON.stringify(current.exceptions)).toBe(JSON.stringify(previous.exceptions));
    expect(current).toEqual(previous);
  });
  it('rejects unexpected archive members and nonregular archive inputs',async()=>{
    const extra=archiveFixture((_m,files)=>files.set('unexpected.txt',Buffer.from('not an approved member')));
    try{await expect(verifyS19Archive(extra.path,extra.expected,data,fonts)).rejects.toThrow('S19_ARCHIVE_MEMBER_INVENTORY');}finally{rmSync(extra.dir,{recursive:true,force:true});}
    const f=archiveFixture();
    try{
      const link=join(f.dir,'linked.zip');symlinkSync(f.path,link);
      await expect(verifyS19Archive(link,f.expected,data,fonts)).rejects.toThrow('S19_NONREGULAR_INPUT');
    }finally{rmSync(f.dir,{recursive:true,force:true});}
  });
  it('rechecks every cached PNG at use and never promotes imported references to measured rows',async()=>{
    const f=archiveFixture();
    try{
      const cache='synthetic-s19',dir=join(f.dir,'frontend/test-baselines/nyay66',cache);mkdirSync(dir,{recursive:true});
      for(const [name,bytes] of f.files)writeFileSync(join(dir,name),bytes);
      const provenance=Buffer.from(JSON.stringify({...f.expected,runId:'1',artifactId:'2',referenceRows:52,manualRows:2}));
      writeFileSync(join(dir,'provenance.json'),provenance);
      const config={cache,manifestSha256:digest(f.files.get('manifest.json')),provenanceSha256:digest(provenance)};
      const got=await loadS19Cache(f.dir,config,data,fonts);
      expect(got.manifest.rows).toHaveLength(52);
      expect(got.manifest.rows.every(row=>row.measured===undefined&&row.executed===undefined&&row.verdict===undefined)).toBe(true);
      const png=got.manifest.rows.at(-1).file;writeFileSync(join(dir,png),Buffer.from('tampered after import'));
      await expect(loadS19Cache(f.dir,config,data,fonts)).rejects.toThrow('S19_ARTIFACT_CHECKSUM_MISMATCH');
    }finally{rmSync(f.dir,{recursive:true,force:true});}
  });
});
