import {withoutS29ProposalsForTest,withoutS29PolicyBytesForTest} from './nyay66-s29-exceptions.test-fixture.mjs';
import {withoutS28ProposalsForTest,withoutS28PolicyBytesForTest} from './nyay66-s28-exceptions.test-fixture.mjs';
import {describe,it,expect} from 'vitest';
import {readFileSync,mkdtempSync,writeFileSync,rmSync,mkdirSync,symlinkSync} from 'node:fs';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import {execFileSync} from 'node:child_process';
import {fileURLToPath} from 'node:url';
import {PNG} from 'pngjs';
import {digest} from './nyay66-enforcement.mjs';
import {loadS28Source,S28_STATES,S28_VIEWPORTS,S28_PINS} from './nyay66-s28-reference.mjs';
import {verifyS28Archive,loadS28Cache} from './nyay66-s28-import.mjs';
import {continuationRows} from './nyay66-continuation.mjs';
import {normalizeS18InvalidForTest,normalizeS18InvalidPolicyBytesForTest} from './nyay66-s18-invalid-reapproval.test-fixture.mjs';
const root=fileURLToPath(new URL('../../../',import.meta.url));
const {data}=await loadS28Source(root);
const policy=JSON.parse(readFileSync(join(root,'frontend/scripts/nyay66-policy.json')));
const fonts=JSON.parse(readFileSync(join(root,'frontend/test-baselines/nyay66',policy.cache,'manifest.json'))).fonts;
const sourceHead='a'.repeat(40),controlHead='b'.repeat(40);
const pngs=new Map(S28_VIEWPORTS.map(vp=>[vp.id,PNG.sync.write(new PNG({width:vp.width,height:vp.height}))]));
function archiveFixture(change=()=>{}){
  const dir=mkdtempSync(join(tmpdir(),'nyay-s28-import-test-'));
  const files=new Map(),rows=[];
  for(const state of S28_STATES)for(const vp of S28_VIEWPORTS){
    const bytes=pngs.get(vp.id),sha256=digest(bytes),file=`s28-${state}-${vp.id}-0.png`;
    files.set(file,bytes);rows.push({view:`s28-${state}`,viewport:vp.id,file,sha256,sampleHashes:Array(3).fill(sha256),dimensions:[vp.width,vp.height],
      surface:{controls:[],headings:[],masks:[],text:'synthetic',overflow:0,dimensions:[vp.width,vp.height]},fontStack:{viewport:'Public Sans',faces:[]},reviewerFrame:{borderRadius:'0px',x:0,y:0}});
  }
  const manifest={schema:1,purpose:'UNIMPORTED_REFERENCE_CALIBRATION',screen:'S-28',theme:'light',approval:data.designApproval,sourceArchiveSha256:data.archiveSha256,sourceSha256:data.htmlSha256,embeddedResources:data.inventory.embeddedResources,producerHead:sourceHead,controlHead,...S28_PINS,fonts,deferredStates:[],rows};
  const pins={purpose:'REFERENCE_GENERATION_ONLY_NOT_IMPORT_APPROVAL',sourceHead,reference:'s28-v32108',...S28_PINS,node:'v22.21.1',fonts};
  change(manifest,files,pins);
  files.set('manifest.json',Buffer.from(JSON.stringify(manifest)));
  files.set('runtime-pins.json',Buffer.from(JSON.stringify(pins)));
  files.set('SHA256SUMS',Buffer.from([...files].map(([name,bytes])=>`${digest(bytes)}  ${name}`).join('\n')+'\n'));
  for(const [name,bytes] of files)writeFileSync(join(dir,name),bytes);
  const path=join(dir,'calibration.zip');execFileSync('zip',['-q',path,...files.keys()],{cwd:dir});
  return {dir,path,expected:{archiveSha256:digest(readFileSync(path)),sourceHead,controlHead},files};
}
describe('S-28 archive import fails closed before writing',()=>{
  it('verifies the archive bytes, all 14 PNGs and the three-sample rehearsal inventory',async()=>{
    const f=archiveFixture();try{const got=await verifyS28Archive(f.path,f.expected,data,fonts);expect(got.manifest.rows).toHaveLength(14);expect(got.files.size).toBe(17);expect(got.archiveSha256).toBe(f.expected.archiveSha256);}finally{rmSync(f.dir,{recursive:true,force:true});}
  });
  it('rejects a tampered archive with its formerly valid digest',async()=>{
    const f=archiveFixture();try{writeFileSync(f.path,Buffer.concat([readFileSync(f.path),Buffer.from('tampered')]));await expect(verifyS28Archive(f.path,f.expected,data,fonts)).rejects.toThrow('S28_ARCHIVE_DIGEST_MISMATCH');}finally{rmSync(f.dir,{recursive:true,force:true});}
  });
  it('rejects a tampered PNG even with a recomputed archive and checksum list',async()=>{
    const f=archiveFixture((_m,files)=>{const [name,bytes]=files.entries().next().value;const altered=Buffer.from(bytes);altered[30]^=1;files.set(name,altered);});
    try{await expect(verifyS28Archive(f.path,f.expected,data,fonts)).rejects.toThrow('S28_REFERENCE_BYTES_MISMATCH');}finally{rmSync(f.dir,{recursive:true,force:true});}
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
    const f=archiveFixture(change);try{await expect(verifyS28Archive(f.path,f.expected,data,fonts)).rejects.toThrow();}finally{rmSync(f.dir,{recursive:true,force:true});}
  });
  it('requires an explicit safe cache binding without fabricating coverage',async()=>{
    expect(await loadS28Cache(root,undefined,data,fonts)).toBe(null);
    await expect(loadS28Cache(root,{cache:'../escape'},data,fonts)).rejects.toThrow('S28_INVALID_CACHE_BINDING');
  });
  it('rejects unexpected members and nonregular archive inputs',async()=>{
    const extra=archiveFixture((_m,files)=>files.set('unexpected.txt',Buffer.from('not an approved member')));
    try{await expect(verifyS28Archive(extra.path,extra.expected,data,fonts)).rejects.toThrow('S28_ARCHIVE_MEMBER_INVENTORY');}finally{rmSync(extra.dir,{recursive:true,force:true});}
    const f=archiveFixture();try{const link=join(f.dir,'linked.zip');symlinkSync(f.path,link);await expect(verifyS28Archive(link,f.expected,data,fonts)).rejects.toThrow('S28_NONREGULAR_INPUT');}finally{rmSync(f.dir,{recursive:true,force:true});}
  });
  it('revalidates cached bytes without promoting references to product measurements',async()=>{
    const f=archiveFixture();try{
      const cache='synthetic-s28',dir=join(f.dir,'frontend/test-baselines/nyay66',cache);mkdirSync(dir,{recursive:true});
      for(const [name,bytes] of f.files)writeFileSync(join(dir,name),bytes);
      const provenance=Buffer.from(JSON.stringify({...f.expected,runId:'1',artifactId:'2',referenceRows:14,manualRows:0}));
      writeFileSync(join(dir,'provenance.json'),provenance);
      const config={cache,manifestSha256:digest(f.files.get('manifest.json')),provenanceSha256:digest(provenance)};
      const got=await loadS28Cache(f.dir,config,data,fonts);
      expect(got.manifest.rows).toHaveLength(14);
      expect(got.manifest.rows.every(row=>row.measured===undefined&&row.executed===undefined&&row.verdict===undefined)).toBe(true);
      writeFileSync(join(dir,got.manifest.rows.at(-1).file),Buffer.from('tampered after import'));
      await expect(loadS28Cache(f.dir,config,data,fonts)).rejects.toThrow('S28_ARTIFACT_CHECKSUM_MISMATCH');
    }finally{rmSync(f.dir,{recursive:true,force:true});}
  });
  it('pins the 14 owner-dispatched references while preserving every existing policy record',async()=>{
    const got=await loadS28Cache(root,policy.s28,data,fonts);
    expect(got).not.toBe(null);expect(got.manifest.rows).toHaveLength(14);
    expect(got.provenance).toEqual({"status":"CANDIDATE_PENDING_OWNER_INTEGRITY_APPROVAL","runId":"41323481198","artifactId":"13090666603","archiveSha256":"70c7acfde6c8ad6ee4fe7af6ceff3af2a50e70f4cee03c92dfe55d3fd60a9c21","sourceHead":"d1aa7f46cff579327b95370a4293d4145221c944","controlHead":"d1aa7f46cff579327b95370a4293d4145221c944","manifestSha256":"0e68f61b7b664ce41375893827e9d693f516ece614ca66fb6c1318a1a1ebf513","referenceRows":14,"manualRows":0});
    expect(policy.s28).toEqual({"cache":"s28-v32108-chromium-149.0.7827.55-41323481198","manifestSha256":"0e68f61b7b664ce41375893827e9d693f516ece614ca66fb6c1318a1a1ebf513","provenanceSha256":"36a33702d2f2eeedb9be2c48c55b8b1af3ca44817996da1b9820930ec8a683b4"});
    expect(got.manifest.rows.map(({view,viewport,sha256,dimensions})=>({view,viewport,sha256,dimensions}))).toEqual([{"view":"s28-loading","viewport":"mobile390","sha256":"17f058cbdf4ae6616398df68398f998520598e21c79de582dd5924e261c352b7","dimensions":[390,844]},{"view":"s28-loading","viewport":"desktop","sha256":"38772f186315c23cb9af3f54cc7148532731b3ba0e58c77eb4cd9903bf9618ac","dimensions":[1440,1024]},{"view":"s28-complete","viewport":"mobile390","sha256":"14ab2939592415c31f9f15223413674acda2f860da3f5355b08f98c274e1c518","dimensions":[390,844]},{"view":"s28-complete","viewport":"desktop","sha256":"c3488bef5cbaddde7a3d1bc0dc66e794deb39e3f9971139739392cbdc48e75fd","dimensions":[1440,1024]},{"view":"s28-following","viewport":"mobile390","sha256":"14ab2939592415c31f9f15223413674acda2f860da3f5355b08f98c274e1c518","dimensions":[390,844]},{"view":"s28-following","viewport":"desktop","sha256":"c3488bef5cbaddde7a3d1bc0dc66e794deb39e3f9971139739392cbdc48e75fd","dimensions":[1440,1024]},{"view":"s28-save-pending","viewport":"mobile390","sha256":"a9bf72e7bbe559742e49f3e8d037f91b0b8ba96dc568d853048487c14762dc26","dimensions":[390,844]},{"view":"s28-save-pending","viewport":"desktop","sha256":"de9b0ed4f9e555a6bcb3fb32d649306cdf14a0687fb283d534daac6a8c1aeafc","dimensions":[1440,1024]},{"view":"s28-follow-error","viewport":"mobile390","sha256":"1a305acc36e92988a676b758d8e2db257840e33d89f6e423fcecc5072546a883","dimensions":[390,844]},{"view":"s28-follow-error","viewport":"desktop","sha256":"d98d0d108bd1a7e4fe85dcc02a39934848486f91c6497d73a34f2593a32e4da0","dimensions":[1440,1024]},{"view":"s28-missing","viewport":"mobile390","sha256":"da36c24064775b7476f445bc8255d52aab7b02a3b0c40580532284632002d80a","dimensions":[390,844]},{"view":"s28-missing","viewport":"desktop","sha256":"e548084c33ee6528ddbcbffed22bdd49261527c89c41fa8a9de815882a14c472","dimensions":[1440,1024]},{"view":"s28-error","viewport":"mobile390","sha256":"545eb914bcf5d26ab86a1e05ca0ac1b96691d6cc0770afc8454683a8ba53ebb5","dimensions":[390,844]},{"view":"s28-error","viewport":"desktop","sha256":"9f814429274dae526d2cd40ad634c4e7003cae006dbf3dbde43113fab45a32ef","dimensions":[1440,1024]}]);
    const beforeBytes=execFileSync('git',['show','d1aa7f46cff579327b95370a4293d4145221c944:frontend/scripts/nyay66-policy.json'],{cwd:root,encoding:'utf8'});
    const currentBytes=readFileSync(join(root,'frontend/scripts/nyay66-policy.json'),'utf8');
    const before=JSON.parse(beforeBytes),current={...structuredClone(policy),exceptions:normalizeS18InvalidForTest(withoutS28ProposalsForTest(withoutS29ProposalsForTest(policy.exceptions)))};
    expect(current.exceptions).toHaveLength(190);
    const normalizedBytes=normalizeS18InvalidPolicyBytesForTest(withoutS28PolicyBytesForTest(withoutS29PolicyBytesForTest(currentBytes)));
    expect(normalizedBytes.slice(normalizedBytes.indexOf('  "exceptions": ['))).toBe(beforeBytes.slice(beforeBytes.indexOf('  "exceptions": [')));
    expect(current.s29).toEqual({"cache":"s29-v32108-chromium-149.0.7827.55-41352544483","manifestSha256":"207f0d96ed928beee038f02d193a5febe3e3eae58d5f0b80a5a6af540cd6334c","provenanceSha256":"5de0808e4f1baa04f9696dd2613d04012ded898c4223118e096e1015a9969f17"});expect(current.s30).toEqual({"cache":"s30-v32108-chromium-149.0.7827.55-41593102467","manifestSha256":"f0d18bfc11a72774c2f4ddb923ed98a8f3d24c8e0beaeebbb8a12cc604079aa2","provenanceSha256":"62f4b3ce31ad66bab4d4d79c980a64929264b0f9f6a572d5deba62c23b82d9e6"});expect(current.s31).toEqual({"cache":"s31-v32108-chromium-149.0.7827.55-41795771621","manifestSha256":"d16430a6a405418f506085111e4486741ba0d46aa25e7ad32fcc937d3f1778d9","provenanceSha256":"cef8aedce696d134f8cdbff97a024bdd7d412a5a5441e14c809f31533326ae07"});expect(current.s32).toEqual({"cache":"s32-v32108-chromium-149.0.7827.55-42000573063","manifestSha256":"5e972c42dd42416603f3f6f69448cdbfc5497fefac61a5243ca28f857a6e13c0","provenanceSha256":"da6ce5a2091308254397c0d60e73505d82a75a2ea7dfb673e89155921ef6876d"});expect(current.s33).toEqual({"cache":"s33-v32108-chromium-149.0.7827.55-42232322310","manifestSha256":"0e473a7a59f21fb909037024a6bb34c9959124b327a95d7c30db68a8f1fe7b12","provenanceSha256":"1c5cd12d34fc2347fd1b8f56ba9ca767a68dd9350a915c42ef7e4de68c49b860"});expect(current.s34).toEqual({"cache":"s34-v32108-chromium-149.0.7827.55-42357105281","manifestSha256":"1b6bbcd0df03a06e95be5e42b7163ea792f9d5a814a500695d2dfe008e032965","provenanceSha256":"a9b8658c83b4fa57bcd7c5f6fa4a1c93ee5626e2aba9fc55257cb40bc4550902"});expect(current.s35).toEqual({"cache":"s35-v32108-chromium-149.0.7827.55-43607096411","manifestSha256":"62d0a14bb63f0ea226c9246c80c9f72124fd869d3b1f22730a7b775bb6f9c6f9","provenanceSha256":"904d1edee324d0c84e92ff809ab4cffb1abcb3a6278e73ca75573b0db9e909dd"});delete current.s35;delete current.s34;delete current.s33;delete current.s32;delete current.s31;delete current.s30;delete current.s29;delete current.s28;delete current.integrityApproval;delete before.integrityApproval;
    expect(current).toEqual(before);
    const rows=continuationRows(data).filter(r=>r.screen==='S-28');
    expect(rows).toHaveLength(14);
    expect(rows.every(r=>r.verdict==='DESIGN-GAP'&&r.executed===false&&r.measured===false)).toBe(true);
  });
});
