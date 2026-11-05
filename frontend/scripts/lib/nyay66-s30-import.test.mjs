import {describe,it,expect} from 'vitest';
import {readFileSync,mkdtempSync,writeFileSync,rmSync,mkdirSync,symlinkSync} from 'node:fs';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import {execFileSync} from 'node:child_process';
import {fileURLToPath} from 'node:url';
import {PNG} from 'pngjs';
import {digest} from './nyay66-enforcement.mjs';
import {continuationRows} from './nyay66-continuation.mjs';
import {loadS30Source,S30_STATES,S30_VIEWPORTS,S30_PINS} from './nyay66-s30-reference.mjs';
import {verifyS30Archive,loadS30Cache} from './nyay66-s30-import.mjs';
import {withoutS30ProposalsForTest,withoutS30PolicyBytesForTest} from './nyay66-s30-exceptions.test-fixture.mjs';
const root=fileURLToPath(new URL('../../../',import.meta.url));
const {data}=await loadS30Source(root);
const policy=JSON.parse(readFileSync(join(root,'frontend/scripts/nyay66-policy.json')));
const fonts=JSON.parse(readFileSync(join(root,'frontend/test-baselines/nyay66',policy.cache,'manifest.json'))).fonts;
const sourceHead='a'.repeat(40),controlHead='b'.repeat(40);
const pngs=new Map(S30_VIEWPORTS.map(vp=>[vp.id,PNG.sync.write(new PNG({width:vp.width,height:vp.height}))]));
function archiveFixture(change=()=>{}){
  const dir=mkdtempSync(join(tmpdir(),'nyay-s30-import-test-'));
  const files=new Map(),rows=[];
  for(const state of S30_STATES)for(const vp of S30_VIEWPORTS){
    const bytes=pngs.get(vp.id),sha256=digest(bytes),file=`s30-${state}-${vp.id}-0.png`;
    files.set(file,bytes);rows.push({view:`s30-${state}`,viewport:vp.id,file,sha256,sampleHashes:Array(3).fill(sha256),dimensions:[vp.width,vp.height],
      surface:{controls:[],headings:[],masks:[],text:'synthetic',overflow:0,dimensions:[vp.width,vp.height]},fontStack:{viewport:'Public Sans',faces:[]},reviewerFrame:{borderRadius:'0px',x:0,y:0}});
  }
  const manifest={schema:1,purpose:'UNIMPORTED_REFERENCE_CALIBRATION',screen:'S-30',theme:'light',approval:data.designApproval,sourceArchiveSha256:data.archiveSha256,sourceSha256:data.htmlSha256,embeddedResources:data.inventory.embeddedResources,producerHead:sourceHead,controlHead,...S30_PINS,fonts,deferredStates:[],rows};
  const pins={purpose:'REFERENCE_GENERATION_ONLY_NOT_IMPORT_APPROVAL',sourceHead,reference:'s30-v32108',...S30_PINS,node:'v22.21.1',fonts};
  change(manifest,files,pins);
  files.set('manifest.json',Buffer.from(JSON.stringify(manifest)));
  files.set('runtime-pins.json',Buffer.from(JSON.stringify(pins)));
  files.set('SHA256SUMS',Buffer.from([...files].map(([name,bytes])=>`${digest(bytes)}  ${name}`).join('\n')+'\n'));
  for(const [name,bytes] of files)writeFileSync(join(dir,name),bytes);
  const path=join(dir,'calibration.zip');execFileSync('zip',['-q',path,...files.keys()],{cwd:dir});
  return {dir,path,expected:{archiveSha256:digest(readFileSync(path)),sourceHead,controlHead},files};
}
describe('S-30 archive import fails closed before writing',()=>{
  it('verifies the archive bytes, all 16 PNGs and the three-sample rehearsal inventory',async()=>{
    const f=archiveFixture();try{const got=await verifyS30Archive(f.path,f.expected,data,fonts);expect(got.manifest.rows).toHaveLength(16);expect(got.files.size).toBe(19);expect(got.archiveSha256).toBe(f.expected.archiveSha256);}finally{rmSync(f.dir,{recursive:true,force:true});}
  });
  it('rejects a tampered archive with its formerly valid digest',async()=>{
    const f=archiveFixture();try{writeFileSync(f.path,Buffer.concat([readFileSync(f.path),Buffer.from('tampered')]));await expect(verifyS30Archive(f.path,f.expected,data,fonts)).rejects.toThrow('S30_ARCHIVE_DIGEST_MISMATCH');}finally{rmSync(f.dir,{recursive:true,force:true});}
  });
  it('rejects a tampered PNG even with a recomputed archive and checksum list',async()=>{
    const f=archiveFixture((_m,files)=>{const [name,bytes]=files.entries().next().value;const altered=Buffer.from(bytes);altered[30]^=1;files.set(name,altered);});
    try{await expect(verifyS30Archive(f.path,f.expected,data,fonts)).rejects.toThrow('S30_REFERENCE_BYTES_MISMATCH');}finally{rmSync(f.dir,{recursive:true,force:true});}
  });
  it.each([
    ['missing row',m=>m.rows.pop()],['duplicate row',m=>{m.rows[1]=structuredClone(m.rows[0]);}],
    ['unstable sample',m=>{m.rows[0].sampleHashes[1]='c'.repeat(64);}],
    ['source head',m=>{m.producerHead='c'.repeat(40);}],['control head',m=>{m.controlHead='c'.repeat(40);}],
    ['browser pin',m=>{m.chromium='wrong';}],['font pin',m=>{m.fonts={};}],
    ['runtime source',(_m,_f,p)=>{p.sourceHead='c'.repeat(40);}],
    ['runtime reference',(_m,_f,p)=>{p.reference='s21-v32108';}],
    ['runtime node',(_m,_f,p)=>{p.node='v0.0.0';}],
    ['runtime purpose',(_m,_f,p)=>{p.purpose='MEASURED';}],
  ])('rejects changed %s',async(_label,change)=>{
    const f=archiveFixture(change);try{await expect(verifyS30Archive(f.path,f.expected,data,fonts)).rejects.toThrow();}finally{rmSync(f.dir,{recursive:true,force:true});}
  });
  it('requires an explicit safe cache binding without fabricating coverage',async()=>{
    expect(await loadS30Cache(root,undefined,data,fonts)).toBe(null);
    await expect(loadS30Cache(root,{cache:'../escape'},data,fonts)).rejects.toThrow('S30_INVALID_CACHE_BINDING');
  });
  it('rejects unexpected members and nonregular archive inputs',async()=>{
    const extra=archiveFixture((_m,files)=>files.set('unexpected.txt',Buffer.from('not an approved member')));
    try{await expect(verifyS30Archive(extra.path,extra.expected,data,fonts)).rejects.toThrow('S30_ARCHIVE_MEMBER_INVENTORY');}finally{rmSync(extra.dir,{recursive:true,force:true});}
    const f=archiveFixture();try{const link=join(f.dir,'linked.zip');symlinkSync(f.path,link);await expect(verifyS30Archive(link,f.expected,data,fonts)).rejects.toThrow('S30_NONREGULAR_INPUT');}finally{rmSync(f.dir,{recursive:true,force:true});}
  });
  it('revalidates cached bytes without promoting references to product measurements',async()=>{
    const f=archiveFixture();try{
      const cache='synthetic-s30',dir=join(f.dir,'frontend/test-baselines/nyay66',cache);mkdirSync(dir,{recursive:true});
      for(const [name,bytes] of f.files)writeFileSync(join(dir,name),bytes);
      const provenance=Buffer.from(JSON.stringify({...f.expected,runId:'1',artifactId:'2',referenceRows:16,manualRows:0}));
      writeFileSync(join(dir,'provenance.json'),provenance);
      const config={cache,manifestSha256:digest(f.files.get('manifest.json')),provenanceSha256:digest(provenance)};
      const got=await loadS30Cache(f.dir,config,data,fonts);
      expect(got.manifest.rows).toHaveLength(16);
      expect(got.manifest.rows.every(row=>row.measured===undefined&&row.executed===undefined&&row.verdict===undefined)).toBe(true);
      writeFileSync(join(dir,got.manifest.rows.at(-1).file),Buffer.from('tampered after import'));
      await expect(loadS30Cache(f.dir,config,data,fonts)).rejects.toThrow('S30_ARTIFACT_CHECKSUM_MISMATCH');
    }finally{rmSync(f.dir,{recursive:true,force:true});}
  });
  it('pins all 16 S-30 references and exact owner-dispatch provenance without changing historical policy or promoting coverage',async()=>{
    const got=await loadS30Cache(root,policy.s30,data,fonts);
    expect(got).not.toBe(null);expect(got.manifest.rows).toHaveLength(16);
    expect(got.provenance).toEqual({"status":"CANDIDATE_PENDING_OWNER_INTEGRITY_APPROVAL","runId":"41593102467","artifactId":"13210754166","archiveSha256":"15ace992480796c9fbc1189ef834b649b28d748db9e7fd0a16ed0386a4967551","sourceHead":"af6798e3098dc4fb0bf689481a6855caf1571e2b","controlHead":"af6798e3098dc4fb0bf689481a6855caf1571e2b","manifestSha256":"f0d18bfc11a72774c2f4ddb923ed98a8f3d24c8e0beaeebbb8a12cc604079aa2","referenceRows":16,"manualRows":0});
    expect(policy.s30).toEqual({"cache":"s30-v32108-chromium-149.0.7827.55-41593102467","manifestSha256":"f0d18bfc11a72774c2f4ddb923ed98a8f3d24c8e0beaeebbb8a12cc604079aa2","provenanceSha256":"62f4b3ce31ad66bab4d4d79c980a64929264b0f9f6a572d5deba62c23b82d9e6"});
    expect(got.manifest.rows.map(({view,viewport,sha256,dimensions})=>({view,viewport,sha256,dimensions}))).toEqual([{"view":"s30-loading","viewport":"mobile390","sha256":"23d66ad669d8756b75e7412cfeb7b0cd72a2b8c27ace2d592a913ebcb974a07e","dimensions":[390,844]},{"view":"s30-loading","viewport":"desktop","sha256":"6f72ce9d760d02d90763add5a978cf9e2205b8a92cce0d1e5d8be8ea9a3c61bb","dimensions":[1440,1024]},{"view":"s30-both","viewport":"mobile390","sha256":"39c19f9df857c89d8a5d292782e91c758637f5f34108155f1ab264a84f2353bb","dimensions":[390,844]},{"view":"s30-both","viewport":"desktop","sha256":"7e165340a4aa52a222107106e4725a25f3fa1492321f495f153d7bc0f4aa0f4a","dimensions":[1440,1024]},{"view":"s30-following-tab","viewport":"mobile390","sha256":"82f87541a1a108dadf87b6da42f33efe682ad986ebfa83b5e01293e76495ad8a","dimensions":[390,844]},{"view":"s30-following-tab","viewport":"desktop","sha256":"b319a63c02e597e326c3dc03590316b2b2444022e2b0b6711ce9dade0750ff61","dimensions":[1440,1024]},{"view":"s30-saved-empty","viewport":"mobile390","sha256":"0d0a4856491c33eb769082625deba42f527b54817f4342fea726e5b7cb5409ba","dimensions":[390,844]},{"view":"s30-saved-empty","viewport":"desktop","sha256":"c84cf43a5fe11331f88a739f5fd1fbb2250762d3100c4542c8d0c9809d376fa7","dimensions":[1440,1024]},{"view":"s30-followed-empty","viewport":"mobile390","sha256":"19651a5a910ad7a45b7ef299569f5ba376a2e62ae1bebe2612d10165f614b512","dimensions":[390,844]},{"view":"s30-followed-empty","viewport":"desktop","sha256":"7df33a3a9b42ce6f7e88b9ae6fb479dc60a0fc6a5063148ce2778a3f1449f5cb","dimensions":[1440,1024]},{"view":"s30-item-pending","viewport":"mobile390","sha256":"84149f98d9330ad31ababebb42cbdcc9501840b1c7f3c4c5e5a21dd4af8f7a95","dimensions":[390,844]},{"view":"s30-item-pending","viewport":"desktop","sha256":"c4dcff6df30d70353f93709c78e908474f5636420a67e416ca7522aa72883851","dimensions":[1440,1024]},{"view":"s30-item-error","viewport":"mobile390","sha256":"8ea883b8fe4b0e86f4b6833871fbb9d8da0d9e736daa37fc266d6b77d11b8783","dimensions":[390,844]},{"view":"s30-item-error","viewport":"desktop","sha256":"7befb7a06627c660a0edc5a8f06f6d80a6033cb6081bc3764e77f5aad22a75ca","dimensions":[1440,1024]},{"view":"s30-error","viewport":"mobile390","sha256":"ab1f0e895a621ef31f99f946273d8770ab0c5ac6016f745028e5e61ddf5f39b1","dimensions":[390,844]},{"view":"s30-error","viewport":"desktop","sha256":"d7b12117d878a15b0a5c1b00d88c3e0ceb1c2146ce2fe042f1a6f4d06300b8ac","dimensions":[1440,1024]}]);
    const beforeBytes=execFileSync('git',['show','af6798e3098dc4fb0bf689481a6855caf1571e2b:frontend/scripts/nyay66-policy.json'],{cwd:root,encoding:'utf8'});
    const currentBytes=withoutS30PolicyBytesForTest(readFileSync(join(root,'frontend/scripts/nyay66-policy.json'),'utf8'));
    const before=JSON.parse(beforeBytes),current=structuredClone(policy);
    current.exceptions=withoutS30ProposalsForTest(current.exceptions);
    expect(current.exceptions).toHaveLength(216);
    expect(currentBytes.slice(currentBytes.indexOf('  "exceptions": ['))).toBe(beforeBytes.slice(beforeBytes.indexOf('  "exceptions": [')));
    expect(current.s31).toEqual({"cache":"s31-v32108-chromium-149.0.7827.55-41795771621","manifestSha256":"d16430a6a405418f506085111e4486741ba0d46aa25e7ad32fcc937d3f1778d9","provenanceSha256":"cef8aedce696d134f8cdbff97a024bdd7d412a5a5441e14c809f31533326ae07"});delete current.s31;delete current.s30;delete current.integrityApproval;delete before.integrityApproval;
    expect(current).toEqual(before);
    const rows=continuationRows(data).filter(r=>r.screen==='S-30');
    expect(rows).toHaveLength(16);
    expect(rows.every(r=>r.verdict==='DESIGN-GAP'&&r.executed===false&&r.measured===false)).toBe(true);
  });
});
