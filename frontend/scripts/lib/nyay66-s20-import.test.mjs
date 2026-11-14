import {s19TypedPolicyForTest} from './nyay66-s19-typed-reapproval.test-fixture.mjs';
import {s27Proposals,withoutS27ProposalsForTest} from './nyay66-s27-exceptions.test-fixture.mjs';
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
import {loadS20Source,S20_STATES,S20_VIEWPORTS,S20_PINS} from './nyay66-s20-reference.mjs';
import {verifyS20Archive,loadS20Cache} from './nyay66-s20-import.mjs';
import {normalizeS19RasterForTest} from './nyay66-s19-reapproval.test-fixture.mjs';
import {s21Proposals,withoutS21ProposalsForTest} from './nyay66-s21-exceptions.test-fixture.mjs';
const root=fileURLToPath(new URL('../../../',import.meta.url));
const {data}=await loadS20Source(root);
const policy=s19TypedPolicyForTest(JSON.parse(readFileSync(join(root,'frontend/scripts/nyay66-policy.json'))));
const fonts=JSON.parse(readFileSync(join(root,'frontend/test-baselines/nyay66',policy.cache,'manifest.json'))).fonts;
const sourceHead='a'.repeat(40),controlHead='b'.repeat(40);
const pngs=new Map(S20_VIEWPORTS.map(vp=>[vp.id,PNG.sync.write(new PNG({width:vp.width,height:vp.height}))]));
function archiveFixture(change=()=>{}){
  const dir=mkdtempSync(join(tmpdir(),'nyay-s20-import-test-'));
  const files=new Map(),rows=[];
  for(const state of S20_STATES)for(const vp of S20_VIEWPORTS){
    const bytes=pngs.get(vp.id),sha256=digest(bytes),file=`s20-${state}-${vp.id}-0.png`;
    files.set(file,bytes);rows.push({view:`s20-${state}`,viewport:vp.id,file,sha256,sampleHashes:Array(3).fill(sha256),dimensions:[vp.width,vp.height],
      surface:{controls:[],headings:[],masks:[],text:'synthetic',overflow:0,dimensions:[vp.width,vp.height]},fontStack:{viewport:'Public Sans',faces:[]},reviewerFrame:{borderRadius:'0px',x:0,y:0}});
  }
  const manifest={schema:1,purpose:'UNIMPORTED_REFERENCE_CALIBRATION',screen:'S-20',theme:'light',approval:data.designApproval,sourceArchiveSha256:data.archiveSha256,sourceSha256:data.htmlSha256,embeddedResources:data.inventory.embeddedResources,producerHead:sourceHead,controlHead,...S20_PINS,fonts,deferredStates:[],rows};
  change(manifest,files);
  files.set('manifest.json',Buffer.from(JSON.stringify(manifest)));
  files.set('runtime-pins.json',Buffer.from(JSON.stringify({purpose:'REFERENCE_GENERATION_ONLY_NOT_IMPORT_APPROVAL',sourceHead,reference:'s20-v32108',...S20_PINS,node:'v22.21.1',fonts})));
  files.set('SHA256SUMS',Buffer.from([...files].map(([name,bytes])=>`${digest(bytes)}  ${name}`).join('\n')+'\n'));
  for(const [name,bytes] of files)writeFileSync(join(dir,name),bytes);
  const path=join(dir,'calibration.zip');execFileSync('zip',['-q',path,...files.keys()],{cwd:dir});
  return {dir,path,expected:{archiveSha256:digest(readFileSync(path)),sourceHead,controlHead},files};
}
describe('S-20 archive import fails closed before writing',()=>{
  it('verifies the archive bytes, all PNGs and the exact 20-row rehearsal inventory',async()=>{
    const f=archiveFixture();try{const got=await verifyS20Archive(f.path,f.expected,data,fonts);expect(got.manifest.rows).toHaveLength(20);expect(got.files.size).toBe(23);expect(got.archiveSha256).toBe(f.expected.archiveSha256);}finally{rmSync(f.dir,{recursive:true,force:true});}
  });
  it('rejects a tampered archive with the formerly valid caller digest',async()=>{
    const f=archiveFixture();try{writeFileSync(f.path,Buffer.concat([readFileSync(f.path),Buffer.from('tampered')]));await expect(verifyS20Archive(f.path,f.expected,data,fonts)).rejects.toThrow('S20_ARCHIVE_DIGEST_MISMATCH');}finally{rmSync(f.dir,{recursive:true,force:true});}
  });
  it('rejects a tampered PNG even with recomputed archive and checksum-list digests',async()=>{
    const f=archiveFixture((_m,files)=>{const [name,bytes]=files.entries().next().value;const altered=Buffer.from(bytes);altered[30]^=1;files.set(name,altered);});
    try{await expect(verifyS20Archive(f.path,f.expected,data,fonts)).rejects.toThrow('S20_REFERENCE_BYTES_MISMATCH');}finally{rmSync(f.dir,{recursive:true,force:true});}
  });
  it('rejects missing states, unstable samples, changed heads and runtime/font pins',async()=>{
    for(const change of [m=>m.rows.pop(),m=>m.rows[0].sampleHashes[1]='c'.repeat(64),m=>m.producerHead='c'.repeat(40),m=>m.controlHead='c'.repeat(40),m=>m.chromium='wrong',m=>m.fonts={}]){
      const f=archiveFixture(change);try{await expect(verifyS20Archive(f.path,f.expected,data,fonts)).rejects.toThrow();}finally{rmSync(f.dir,{recursive:true,force:true});}
    }
  });
  it('requires an explicit safe cache binding without fabricating coverage',async()=>{
    expect(await loadS20Cache(root,undefined,data,fonts)).toBe(null);
    await expect(loadS20Cache(root,{cache:'../escape'},data,fonts)).rejects.toThrow('S20_INVALID_CACHE_BINDING');
  });
  it('rejects unexpected members and nonregular archive inputs',async()=>{
    const extra=archiveFixture((_m,files)=>files.set('unexpected.txt',Buffer.from('not an approved member')));
    try{await expect(verifyS20Archive(extra.path,extra.expected,data,fonts)).rejects.toThrow('S20_ARCHIVE_MEMBER_INVENTORY');}finally{rmSync(extra.dir,{recursive:true,force:true});}
    const f=archiveFixture();try{const link=join(f.dir,'linked.zip');symlinkSync(f.path,link);await expect(verifyS20Archive(link,f.expected,data,fonts)).rejects.toThrow('S20_NONREGULAR_INPUT');}finally{rmSync(f.dir,{recursive:true,force:true});}
  });
  it('revalidates cached bytes without promoting references to product measurements',async()=>{
    const f=archiveFixture();try{
      const cache='synthetic-s20',dir=join(f.dir,'frontend/test-baselines/nyay66',cache);mkdirSync(dir,{recursive:true});
      for(const [name,bytes] of f.files)writeFileSync(join(dir,name),bytes);
      const provenance=Buffer.from(JSON.stringify({...f.expected,runId:'1',artifactId:'2',referenceRows:20,manualRows:0}));
      writeFileSync(join(dir,'provenance.json'),provenance);
      const config={cache,manifestSha256:digest(f.files.get('manifest.json')),provenanceSha256:digest(provenance)};
      const got=await loadS20Cache(f.dir,config,data,fonts);
      expect(got.manifest.rows).toHaveLength(20);
      expect(got.manifest.rows.every(row=>row.measured===undefined&&row.executed===undefined&&row.verdict===undefined)).toBe(true);
      writeFileSync(join(dir,got.manifest.rows.at(-1).file),Buffer.from('tampered after import'));
      await expect(loadS20Cache(f.dir,config,data,fonts)).rejects.toThrow('S20_ARTIFACT_CHECKSUM_MISMATCH');
    }finally{rmSync(f.dir,{recursive:true,force:true});}
  });
  it.each(['current','proposed','s25-proposed','s26-proposed','s27-proposed'])('pins the owner-dispatched cache and preserves every pre-existing policy setting (%s exceptions)',async(mode)=>{
    const got=await loadS20Cache(root,policy.s20,data,fonts);
    expect(got).not.toBe(null);expect(got.manifest.rows).toHaveLength(20);
    expect(got.provenance).toMatchObject({status:'CANDIDATE_PENDING_OWNER_INTEGRITY_APPROVAL',runId:'39111251228',artifactId:'12130567685',archiveSha256:'60d568c31d8f32dc0ac6708bd5a0601ff4ea51a31006d538bdfa80c915143cdc',sourceHead:'c5879f839e78b1c5792760e2577f511fd49cec28',controlHead:'48eeac1973053eb2fd8e4080091dd345bf08db69',referenceRows:20,manualRows:0});
    expect(got.manifestSha256).toBe('e121bff73a920ce1a563cc77317a6bbfe7a1970f131b8442cd61a4123f6b47d9');
    const before=JSON.parse(execFileSync('git',['show','48eeac1973053eb2fd8e4080091dd345bf08db69:frontend/scripts/nyay66-policy.json'],{cwd:root}));
    // The additive S-26/S-27 caches are pinned by their exact-provenance import tests.
    const current=structuredClone(policy);delete current.s20;delete current.s21;delete current.s25;delete current.s26;delete current.s27;expect(current.s29).toEqual({"cache":"s29-v32108-chromium-149.0.7827.55-41352544483","manifestSha256":"207f0d96ed928beee038f02d193a5febe3e3eae58d5f0b80a5a6af540cd6334c","provenanceSha256":"5de0808e4f1baa04f9696dd2613d04012ded898c4223118e096e1015a9969f17"});expect(current.s30).toEqual({"cache":"s30-v32108-chromium-149.0.7827.55-41593102467","manifestSha256":"f0d18bfc11a72774c2f4ddb923ed98a8f3d24c8e0beaeebbb8a12cc604079aa2","provenanceSha256":"62f4b3ce31ad66bab4d4d79c980a64929264b0f9f6a572d5deba62c23b82d9e6"});expect(current.s31).toEqual({"cache":"s31-v32108-chromium-149.0.7827.55-41795771621","manifestSha256":"d16430a6a405418f506085111e4486741ba0d46aa25e7ad32fcc937d3f1778d9","provenanceSha256":"cef8aedce696d134f8cdbff97a024bdd7d412a5a5441e14c809f31533326ae07"});expect(current.s32).toEqual({"cache":"s32-v32108-chromium-149.0.7827.55-42000573063","manifestSha256":"5e972c42dd42416603f3f6f69448cdbfc5497fefac61a5243ca28f857a6e13c0","provenanceSha256":"da6ce5a2091308254397c0d60e73505d82a75a2ea7dfb673e89155921ef6876d"});expect(current.s33).toEqual({"cache":"s33-v32108-chromium-149.0.7827.55-42232322310","manifestSha256":"0e473a7a59f21fb909037024a6bb34c9959124b327a95d7c30db68a8f1fe7b12","provenanceSha256":"1c5cd12d34fc2347fd1b8f56ba9ca767a68dd9350a915c42ef7e4de68c49b860"});expect(current.s34).toEqual({"cache":"s34-v32108-chromium-149.0.7827.55-42357105281","manifestSha256":"1b6bbcd0df03a06e95be5e42b7163ea792f9d5a814a500695d2dfe008e032965","provenanceSha256":"a9b8658c83b4fa57bcd7c5f6fa4a1c93ee5626e2aba9fc55257cb40bc4550902"});expect(current.s35).toEqual({"cache":"s35-v32108-chromium-149.0.7827.55-43607096411","manifestSha256":"62d0a14bb63f0ea226c9246c80c9f72124fd869d3b1f22730a7b775bb6f9c6f9","provenanceSha256":"904d1edee324d0c84e92ff809ab4cffb1abcb3a6278e73ca75573b0db9e909dd"});delete current.s35;delete current.s34;delete current.s33;delete current.s32;delete current.s31;delete current.s30;delete current.s29;delete current.s28;delete current.integrityApproval;delete before.integrityApproval;
    // S-25's exact cache/provenance is pinned by nyay66-s25-import.test.mjs;
    // only that additive field is excluded from this older policy snapshot.
    // Only the additive S-21 cache is checked separately by its exact-provenance
    // import test; no historical setting or exception comparison is removed.
    // S-20 additions are validated by the coverage/owner-approval contracts;
    // Pin every old byte/order after separately checking the one exact S-19
    // capture replacement; this test-only normalization never edits policy.
    if(mode==='proposed')current.exceptions=[...current.exceptions.filter(e=>e.screen!=='S-21'),...structuredClone(s21Proposals)];
    if(mode==='s25-proposed')current.exceptions=[...current.exceptions.filter(e=>e.screen!=='S-25'),...structuredClone(s25Proposals)];
    if(mode==='s26-proposed')current.exceptions=[...current.exceptions.filter(e=>e.screen!=='S-26'),...structuredClone(s26Proposals)];
    if(mode==='s27-proposed')current.exceptions=[...current.exceptions.filter(e=>e.screen!=='S-27'),...structuredClone(s27Proposals)];
    current.exceptions=withoutS25ProposalsForTest(withoutS26ProposalsForTest(withoutS27ProposalsForTest(current.exceptions)));
    current.exceptions=normalizeS19RasterForTest(withoutS21ProposalsForTest(current.exceptions)).filter(e=>e.screen!=='S-20');
    expect(JSON.stringify(current.exceptions)).toBe(JSON.stringify(before.exceptions));
    expect(current).toEqual(before);
  });
});
