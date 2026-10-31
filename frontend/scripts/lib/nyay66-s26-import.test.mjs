import {s27Proposals,withoutS27ProposalsForTest} from './nyay66-s27-exceptions.test-fixture.mjs';
import {s26Proposals,withoutS26ProposalsForTest} from './nyay66-s26-exceptions.test-fixture.mjs';
import {describe,it,expect} from 'vitest';
import {readFileSync,mkdtempSync,writeFileSync,rmSync,mkdirSync,symlinkSync} from 'node:fs';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import {execFileSync} from 'node:child_process';
import {fileURLToPath} from 'node:url';
import {PNG} from 'pngjs';
import {digest} from './nyay66-enforcement.mjs';
import {loadS26Source,S26_STATES,S26_VIEWPORTS,S26_PINS} from './nyay66-s26-reference.mjs';
import {verifyS26Archive,loadS26Cache} from './nyay66-s26-import.mjs';
import {continuationRows} from './nyay66-continuation.mjs';
const root=fileURLToPath(new URL('../../../',import.meta.url));
const {data}=await loadS26Source(root);
const policy=JSON.parse(readFileSync(join(root,'frontend/scripts/nyay66-policy.json')));
const fonts=JSON.parse(readFileSync(join(root,'frontend/test-baselines/nyay66',policy.cache,'manifest.json'))).fonts;
const sourceHead='a'.repeat(40),controlHead='b'.repeat(40);
const pngs=new Map(S26_VIEWPORTS.map(vp=>[vp.id,PNG.sync.write(new PNG({width:vp.width,height:vp.height}))]));
function archiveFixture(change=()=>{}){
  const dir=mkdtempSync(join(tmpdir(),'nyay-s26-import-test-'));
  const files=new Map(),rows=[];
  for(const state of S26_STATES)for(const vp of S26_VIEWPORTS){
    const bytes=pngs.get(vp.id),sha256=digest(bytes),file=`s26-${state}-${vp.id}-0.png`;
    files.set(file,bytes);rows.push({view:`s26-${state}`,viewport:vp.id,file,sha256,sampleHashes:Array(3).fill(sha256),dimensions:[vp.width,vp.height],
      surface:{controls:[],headings:[],masks:[],text:'synthetic',overflow:0,dimensions:[vp.width,vp.height]},fontStack:{viewport:'Public Sans',faces:[]},reviewerFrame:{borderRadius:'0px',x:0,y:0}});
  }
  const manifest={schema:1,purpose:'UNIMPORTED_REFERENCE_CALIBRATION',screen:'S-26',theme:'light',approval:data.designApproval,sourceArchiveSha256:data.archiveSha256,sourceSha256:data.htmlSha256,embeddedResources:data.inventory.embeddedResources,producerHead:sourceHead,controlHead,...S26_PINS,fonts,deferredStates:[],rows};
  const pins={purpose:'REFERENCE_GENERATION_ONLY_NOT_IMPORT_APPROVAL',sourceHead,reference:'s26-v32108',...S26_PINS,node:'v22.21.1',fonts};
  change(manifest,files,pins);
  files.set('manifest.json',Buffer.from(JSON.stringify(manifest)));
  files.set('runtime-pins.json',Buffer.from(JSON.stringify(pins)));
  files.set('SHA256SUMS',Buffer.from([...files].map(([name,bytes])=>`${digest(bytes)}  ${name}`).join('\n')+'\n'));
  for(const [name,bytes] of files)writeFileSync(join(dir,name),bytes);
  const path=join(dir,'calibration.zip');execFileSync('zip',['-q',path,...files.keys()],{cwd:dir});
  return {dir,path,expected:{archiveSha256:digest(readFileSync(path)),sourceHead,controlHead},files};
}
describe('S-26 archive import fails closed before writing',()=>{
  it('verifies the archive bytes, all 8 PNGs and the three-sample rehearsal inventory',async()=>{
    const f=archiveFixture();try{const got=await verifyS26Archive(f.path,f.expected,data,fonts);expect(got.manifest.rows).toHaveLength(8);expect(got.files.size).toBe(11);expect(got.archiveSha256).toBe(f.expected.archiveSha256);}finally{rmSync(f.dir,{recursive:true,force:true});}
  });
  it('rejects a tampered archive with its formerly valid digest',async()=>{
    const f=archiveFixture();try{writeFileSync(f.path,Buffer.concat([readFileSync(f.path),Buffer.from('tampered')]));await expect(verifyS26Archive(f.path,f.expected,data,fonts)).rejects.toThrow('S26_ARCHIVE_DIGEST_MISMATCH');}finally{rmSync(f.dir,{recursive:true,force:true});}
  });
  it('rejects a tampered PNG even with a recomputed archive and checksum list',async()=>{
    const f=archiveFixture((_m,files)=>{const [name,bytes]=files.entries().next().value;const altered=Buffer.from(bytes);altered[30]^=1;files.set(name,altered);});
    try{await expect(verifyS26Archive(f.path,f.expected,data,fonts)).rejects.toThrow('S26_REFERENCE_BYTES_MISMATCH');}finally{rmSync(f.dir,{recursive:true,force:true});}
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
    const f=archiveFixture(change);try{await expect(verifyS26Archive(f.path,f.expected,data,fonts)).rejects.toThrow();}finally{rmSync(f.dir,{recursive:true,force:true});}
  });
  it('requires an explicit safe cache binding without fabricating coverage',async()=>{
    expect(await loadS26Cache(root,undefined,data,fonts)).toBe(null);
    await expect(loadS26Cache(root,{cache:'../escape'},data,fonts)).rejects.toThrow('S26_INVALID_CACHE_BINDING');
  });
  it('rejects unexpected members and nonregular archive inputs',async()=>{
    const extra=archiveFixture((_m,files)=>files.set('unexpected.txt',Buffer.from('not an approved member')));
    try{await expect(verifyS26Archive(extra.path,extra.expected,data,fonts)).rejects.toThrow('S26_ARCHIVE_MEMBER_INVENTORY');}finally{rmSync(extra.dir,{recursive:true,force:true});}
    const f=archiveFixture();try{const link=join(f.dir,'linked.zip');symlinkSync(f.path,link);await expect(verifyS26Archive(link,f.expected,data,fonts)).rejects.toThrow('S26_NONREGULAR_INPUT');}finally{rmSync(f.dir,{recursive:true,force:true});}
  });
  it('revalidates cached bytes without promoting references to product measurements',async()=>{
    const f=archiveFixture();try{
      const cache='synthetic-s26',dir=join(f.dir,'frontend/test-baselines/nyay66',cache);mkdirSync(dir,{recursive:true});
      for(const [name,bytes] of f.files)writeFileSync(join(dir,name),bytes);
      const provenance=Buffer.from(JSON.stringify({...f.expected,runId:'1',artifactId:'2',referenceRows:8,manualRows:0}));
      writeFileSync(join(dir,'provenance.json'),provenance);
      const config={cache,manifestSha256:digest(f.files.get('manifest.json')),provenanceSha256:digest(provenance)};
      const got=await loadS26Cache(f.dir,config,data,fonts);
      expect(got.manifest.rows).toHaveLength(8);
      expect(got.manifest.rows.every(row=>row.measured===undefined&&row.executed===undefined&&row.verdict===undefined)).toBe(true);
      writeFileSync(join(dir,got.manifest.rows.at(-1).file),Buffer.from('tampered after import'));
      await expect(loadS26Cache(f.dir,config,data,fonts)).rejects.toThrow('S26_ARTIFACT_CHECKSUM_MISMATCH');
    }finally{rmSync(f.dir,{recursive:true,force:true});}
  });
  it.each(['current','s26-proposed','s27-proposed'])('pins the exact owner-dispatched cache while preserving every historical policy record (%s)',async(mode)=>{
    const currentPolicy=structuredClone(policy);
    if(mode==='s26-proposed')currentPolicy.exceptions=[...currentPolicy.exceptions.filter(e=>e.screen!=='S-26'),...structuredClone(s26Proposals)];
    if(mode==='s27-proposed')currentPolicy.exceptions=[...currentPolicy.exceptions.filter(e=>e.screen!=='S-27'),...structuredClone(s27Proposals)];
    const got=await loadS26Cache(root,policy.s26,data,fonts);
    expect(got).not.toBe(null);expect(got.manifest.rows).toHaveLength(8);
    expect(got.provenance).toEqual({"status":"CANDIDATE_PENDING_OWNER_INTEGRITY_APPROVAL","runId":"41029103233","artifactId":"12965330816","archiveSha256":"a58def51694350f9d631a3680d50dfb75477340395737af86bbd06dfc00272f8","sourceHead":"d7a9d5bb7ffba20360305bd25ad3c6adb3049a61","controlHead":"d7a9d5bb7ffba20360305bd25ad3c6adb3049a61","manifestSha256":"d03d6c01f946c5f63105f2da437560347b0f52f799af6d5d6be32a2f5a4673c8","referenceRows":8,"manualRows":0});
    expect(policy.s26).toEqual({"cache":"s26-v32108-chromium-149.0.7827.55-41029103233","manifestSha256":"d03d6c01f946c5f63105f2da437560347b0f52f799af6d5d6be32a2f5a4673c8","provenanceSha256":"9c7a0f3ac61c0cf71639719943229eb0cc0e69df4455dee1144a20d2bfd358ba"});
    expect(got.manifest.rows.map(({view,viewport,sha256,dimensions})=>({view,viewport,sha256,dimensions}))).toEqual([{"view":"s26-empty","viewport":"mobile390","sha256":"b81eb5c57ffcc65e4a2fda31d6fc2d31d4468206cd5b1ec2a890256826dc1e47","dimensions":[390,844]},{"view":"s26-empty","viewport":"desktop","sha256":"d89600b9a4782aec657e804f84d51c36b4b9693ce255ab1547aeebc265b5deb8","dimensions":[1440,1024]},{"view":"s26-loading","viewport":"mobile390","sha256":"ed2b61e1b7a9e7285e7c70e706168e167399d2c14c7b94b69f481cfb33ff39d7","dimensions":[390,844]},{"view":"s26-loading","viewport":"desktop","sha256":"ea051ce92916242113ec91b5e0c943ba52a94a44dda4e8b7d6d560e0e243b9cc","dimensions":[1440,1024]},{"view":"s26-error","viewport":"mobile390","sha256":"6fb62d2be1fc718571cc81116d4dc6189b483446ada1b5823dba703c7fb07819","dimensions":[390,844]},{"view":"s26-error","viewport":"desktop","sha256":"65955518a671527152a9681c3cd7acd3b8da21db60b56af81b7ac8edd010f811","dimensions":[1440,1024]},{"view":"s26-nonempty","viewport":"mobile390","sha256":"3ca72ade05bb63ffac43129918b6652149885df2d34c28c216e2181e6d10e9d6","dimensions":[390,844]},{"view":"s26-nonempty","viewport":"desktop","sha256":"796a11d4e162f60ee6e36ace1514c620aa4d63e8100325bef554f0eae8769e52","dimensions":[1440,1024]}]);
    const before=JSON.parse(execFileSync('git',['show','d7a9d5bb7ffba20360305bd25ad3c6adb3049a61:frontend/scripts/nyay66-policy.json'],{cwd:root}));
    currentPolicy.exceptions=withoutS26ProposalsForTest(withoutS27ProposalsForTest(currentPolicy.exceptions));
    expect(currentPolicy.exceptions).toHaveLength(160);
    expect(JSON.stringify(currentPolicy.exceptions)).toBe(JSON.stringify(before.exceptions));
    const current=structuredClone(currentPolicy);delete current.s26;delete current.s27;delete current.integrityApproval;delete before.integrityApproval;
    expect(current).toEqual(before);
    const rows=continuationRows(data).filter(r=>r.screen==='S-26');
    expect(rows).toHaveLength(8);
    expect(rows.every(r=>r.verdict==='DESIGN-GAP'&&r.executed===false&&r.measured===false)).toBe(true);
  });
});
