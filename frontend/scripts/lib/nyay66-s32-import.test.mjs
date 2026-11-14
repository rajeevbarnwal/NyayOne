import {withoutS32ProposalsForTest,withoutS32PolicyBytesForTest} from './nyay66-s32-exceptions.test-fixture.mjs';
import {describe,it,expect} from 'vitest';
import {readFileSync,mkdtempSync,writeFileSync,rmSync,mkdirSync,symlinkSync} from 'node:fs';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import {execFileSync} from 'node:child_process';
import {fileURLToPath} from 'node:url';
import {PNG} from 'pngjs';
import {digest} from './nyay66-enforcement.mjs';
import {continuationRows} from './nyay66-continuation.mjs';
import {loadS32Source,S32_STATES,S32_VIEWPORTS,S32_PINS} from './nyay66-s32-reference.mjs';
import {verifyS32Archive,loadS32Cache} from './nyay66-s32-import.mjs';
const root=fileURLToPath(new URL('../../../',import.meta.url));
const {data}=await loadS32Source(root);
const policy=JSON.parse(readFileSync(join(root,'frontend/scripts/nyay66-policy.json')));
const fonts=JSON.parse(readFileSync(join(root,'frontend/test-baselines/nyay66',policy.cache,'manifest.json'))).fonts;
const sourceHead='a'.repeat(40),controlHead='b'.repeat(40);
const pngs=new Map(S32_VIEWPORTS.map(vp=>[vp.id,PNG.sync.write(new PNG({width:vp.width,height:vp.height}))]));
function archiveFixture(change=()=>{}){
  const dir=mkdtempSync(join(tmpdir(),'nyay-s32-import-test-'));
  const files=new Map(),rows=[];
  for(const state of S32_STATES)for(const vp of S32_VIEWPORTS){
    const bytes=pngs.get(vp.id),sha256=digest(bytes),file=`s32-${state}-${vp.id}-0.png`;
    files.set(file,bytes);rows.push({view:`s32-${state}`,viewport:vp.id,file,sha256,sampleHashes:Array(3).fill(sha256),dimensions:[vp.width,vp.height],
      surface:{controls:[],headings:[],masks:[],text:'synthetic',overflow:0,dimensions:[vp.width,vp.height]},fontStack:{viewport:'Public Sans',faces:[]},reviewerFrame:{borderRadius:'0px',x:0,y:0}});
  }
  const manifest={schema:1,purpose:'UNIMPORTED_REFERENCE_CALIBRATION',screen:'S-32',theme:'light',approval:data.designApproval,sourceArchiveSha256:data.archiveSha256,sourceSha256:data.htmlSha256,embeddedResources:data.inventory.embeddedResources,producerHead:sourceHead,controlHead,...S32_PINS,fonts,deferredStates:[],rows};
  const pins={purpose:'REFERENCE_GENERATION_ONLY_NOT_IMPORT_APPROVAL',sourceHead,reference:'s32-v32108',...S32_PINS,node:'v22.21.1',fonts};
  change(manifest,files,pins);
  files.set('manifest.json',Buffer.from(JSON.stringify(manifest)));
  files.set('runtime-pins.json',Buffer.from(JSON.stringify(pins)));
  files.set('SHA256SUMS',Buffer.from([...files].map(([name,bytes])=>`${digest(bytes)}  ${name}`).join('\n')+'\n'));
  for(const [name,bytes] of files)writeFileSync(join(dir,name),bytes);
  const path=join(dir,'calibration.zip');execFileSync('zip',['-q',path,...files.keys()],{cwd:dir});
  return {dir,path,expected:{archiveSha256:digest(readFileSync(path)),sourceHead,controlHead},files};
}
describe('S-32 archive import fails closed before writing',()=>{
  it('verifies the archive bytes, all 22 PNGs and the three-sample rehearsal inventory',async()=>{
    const f=archiveFixture();try{const got=await verifyS32Archive(f.path,f.expected,data,fonts);expect(got.manifest.rows).toHaveLength(22);expect(got.files.size).toBe(25);expect(got.archiveSha256).toBe(f.expected.archiveSha256);}finally{rmSync(f.dir,{recursive:true,force:true});}
  });
  it('rejects a tampered archive with its formerly valid digest',async()=>{
    const f=archiveFixture();try{writeFileSync(f.path,Buffer.concat([readFileSync(f.path),Buffer.from('tampered')]));await expect(verifyS32Archive(f.path,f.expected,data,fonts)).rejects.toThrow('S32_ARCHIVE_DIGEST_MISMATCH');}finally{rmSync(f.dir,{recursive:true,force:true});}
  });
  it('rejects a tampered PNG even with a recomputed archive and checksum list',async()=>{
    const f=archiveFixture((_m,files)=>{const [name,bytes]=files.entries().next().value;const altered=Buffer.from(bytes);altered[30]^=1;files.set(name,altered);});
    try{await expect(verifyS32Archive(f.path,f.expected,data,fonts)).rejects.toThrow('S32_REFERENCE_BYTES_MISMATCH');}finally{rmSync(f.dir,{recursive:true,force:true});}
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
    const f=archiveFixture(change);try{await expect(verifyS32Archive(f.path,f.expected,data,fonts)).rejects.toThrow();}finally{rmSync(f.dir,{recursive:true,force:true});}
  });
  it('requires an explicit safe cache binding without fabricating coverage',async()=>{
    expect(await loadS32Cache(root,undefined,data,fonts)).toBe(null);
    await expect(loadS32Cache(root,{cache:'../escape'},data,fonts)).rejects.toThrow('S32_INVALID_CACHE_BINDING');
  });
  it('rejects unexpected members and nonregular archive inputs',async()=>{
    const extra=archiveFixture((_m,files)=>files.set('unexpected.txt',Buffer.from('not an approved member')));
    try{await expect(verifyS32Archive(extra.path,extra.expected,data,fonts)).rejects.toThrow('S32_ARCHIVE_MEMBER_INVENTORY');}finally{rmSync(extra.dir,{recursive:true,force:true});}
    const f=archiveFixture();try{const link=join(f.dir,'linked.zip');symlinkSync(f.path,link);await expect(verifyS32Archive(link,f.expected,data,fonts)).rejects.toThrow('S32_NONREGULAR_INPUT');}finally{rmSync(f.dir,{recursive:true,force:true});}
  });
  it('revalidates cached bytes without promoting references to product measurements',async()=>{
    const f=archiveFixture();try{
      const cache='synthetic-s32',dir=join(f.dir,'frontend/test-baselines/nyay66',cache);mkdirSync(dir,{recursive:true});
      for(const [name,bytes] of f.files)writeFileSync(join(dir,name),bytes);
      const provenance=Buffer.from(JSON.stringify({...f.expected,runId:'1',artifactId:'2',referenceRows:22,manualRows:0}));
      writeFileSync(join(dir,'provenance.json'),provenance);
      const config={cache,manifestSha256:digest(f.files.get('manifest.json')),provenanceSha256:digest(provenance)};
      const got=await loadS32Cache(f.dir,config,data,fonts);
      expect(got.manifest.rows).toHaveLength(22);
      expect(got.manifest.rows.every(row=>row.measured===undefined&&row.executed===undefined&&row.verdict===undefined)).toBe(true);
      writeFileSync(join(dir,got.manifest.rows.at(-1).file),Buffer.from('tampered after import'));
      await expect(loadS32Cache(f.dir,config,data,fonts)).rejects.toThrow('S32_ARTIFACT_CHECKSUM_MISMATCH');
    }finally{rmSync(f.dir,{recursive:true,force:true});}
  });
  it('pins all 22 S-32 references and exact owner-dispatch provenance without changing historical policy or promoting coverage',async()=>{
    const got=await loadS32Cache(root,policy.s32,data,fonts);
    expect(got).not.toBe(null);expect(got.manifest.rows).toHaveLength(22);
    expect(got.provenance).toEqual({"status":"CANDIDATE_PENDING_OWNER_INTEGRITY_APPROVAL","runId":"42000573063","artifactId":"13401848938","archiveSha256":"7e2b0833d1274f7e1fef6fe66f0c3d231f194fcda6034c31c6ab4741efd6f183","sourceHead":"970a7682e7524864d79a0ebd6bd6d48ff24e1e68","controlHead":"970a7682e7524864d79a0ebd6bd6d48ff24e1e68","manifestSha256":"5e972c42dd42416603f3f6f69448cdbfc5497fefac61a5243ca28f857a6e13c0","referenceRows":22,"manualRows":0});
    expect(policy.s32).toEqual({"cache":"s32-v32108-chromium-149.0.7827.55-42000573063","manifestSha256":"5e972c42dd42416603f3f6f69448cdbfc5497fefac61a5243ca28f857a6e13c0","provenanceSha256":"da6ce5a2091308254397c0d60e73505d82a75a2ea7dfb673e89155921ef6876d"});
    expect(got.manifest.rows.map(({view,viewport,sha256,dimensions})=>({view,viewport,sha256,dimensions}))).toEqual([{"view":"s32-loading","viewport":"mobile390","sha256":"f0504c645571eac85f1fd547bcb6246ca0bb3897772a3c7bc9252be357d685b7","dimensions":[390,844]},{"view":"s32-loading","viewport":"desktop","sha256":"edcd2def9fcba05e5d2b233b8e95d1385f928a36b9e7033f54542fd861acee5c","dimensions":[1440,1024]},{"view":"s32-complete","viewport":"mobile390","sha256":"df3ae24f612d71f017dc1ccc4941791b42b5990987438b36b2975e6aa54334cf","dimensions":[390,844]},{"view":"s32-complete","viewport":"desktop","sha256":"9ec24074966cacfcef6aed2b4a9fce3735bb9dedc2c020fd8e8b350a773696b7","dimensions":[1440,1024]},{"view":"s32-selected","viewport":"mobile390","sha256":"df3ae24f612d71f017dc1ccc4941791b42b5990987438b36b2975e6aa54334cf","dimensions":[390,844]},{"view":"s32-selected","viewport":"desktop","sha256":"8c799cdee91744fbfd296d08fecf9c2983f8f8ba49f49abf1a943a7c5daad0e0","dimensions":[1440,1024]},{"view":"s32-availability-error","viewport":"mobile390","sha256":"89607bd396f1c701d7962408c2327fc528801e9034fb15924c3c1514d830e360","dimensions":[390,844]},{"view":"s32-availability-error","viewport":"desktop","sha256":"abd8ab3d272fbf1aac93e8970bd51dc0c7148b0c7d85f4f58968d1ca99d5e53b","dimensions":[1440,1024]},{"view":"s32-no-slots","viewport":"mobile390","sha256":"dc6d44ef09fe3806554198a1c850ae2bd264b02849ba43187afd4d23440207d9","dimensions":[390,844]},{"view":"s32-no-slots","viewport":"desktop","sha256":"6e2bed7e636ff3a56fa9d28e9f2d538e69812cc34d08a97e73fee96dc784313e","dimensions":[1440,1024]},{"view":"s32-profile-error","viewport":"mobile390","sha256":"c68f5b923e76f838072dea263ef63eb3ebfbcd3c940111e83cbfa9a8a2d05bb1","dimensions":[390,844]},{"view":"s32-profile-error","viewport":"desktop","sha256":"3ee247f87dcf9eebd8774689d64a996b3bb24f185e8f2941385d5c152bf564b6","dimensions":[1440,1024]},{"view":"s32-missing","viewport":"mobile390","sha256":"49e0aab7c6cde497954875f85ab5f6f9ec40374b87375e2532259dc7c9427a79","dimensions":[390,844]},{"view":"s32-missing","viewport":"desktop","sha256":"1fea77422281b2bff6d29301e8183047bfcb34e195a4678247227ecd1cd64199","dimensions":[1440,1024]},{"view":"s32-zone-changed","viewport":"mobile390","sha256":"df9d692ff972f76f760f3f0c6bafd2947f314354b0df00164615106e8a188554","dimensions":[390,844]},{"view":"s32-zone-changed","viewport":"desktop","sha256":"cbbe4eac8bb9cd6bd43de2b8d539a851fc6a6669cd97fd952e6d1caed96c9288","dimensions":[1440,1024]},{"view":"s32-day-empty","viewport":"mobile390","sha256":"c5b0c6dc2ffd1550b7e12ec53c1b56b79bd364335e224fc4d9b40513be371d1a","dimensions":[390,844]},{"view":"s32-day-empty","viewport":"desktop","sha256":"9610437221d4d581709ab299f4cd45efe3bc264d18c7c7795f501152e9b0cb86","dimensions":[1440,1024]},{"view":"s32-dst-ambiguous","viewport":"mobile390","sha256":"ded651055c7395fa366e7b565a8d021fca7452f2da0e12f86a17764a326c6604","dimensions":[390,844]},{"view":"s32-dst-ambiguous","viewport":"desktop","sha256":"6e50caaed1706062365f88caf215ce43ad1bac66c9c42226b3f1487dd4985ae2","dimensions":[1440,1024]},{"view":"s32-dst-gap","viewport":"mobile390","sha256":"9c4c2110f2c2917aa7380d47423d11ad6e4e425bc49254628c0ca32aa059bc81","dimensions":[390,844]},{"view":"s32-dst-gap","viewport":"desktop","sha256":"e5fafe97fa1bfe135d8caa67c6147991ffb8afa6ae814e7db137bc6fe1689bc8","dimensions":[1440,1024]}]);
    const beforeBytes=execFileSync('git',['show','970a7682e7524864d79a0ebd6bd6d48ff24e1e68:frontend/scripts/nyay66-policy.json'],{cwd:root,encoding:'utf8'});
    const currentBytes=withoutS32PolicyBytesForTest(readFileSync(join(root,'frontend/scripts/nyay66-policy.json'),'utf8'));
    const before=JSON.parse(beforeBytes),current=structuredClone(policy);
    current.exceptions=withoutS32ProposalsForTest(current.exceptions);
    expect(current.exceptions).toHaveLength(248);
    expect(currentBytes.slice(currentBytes.indexOf('  "exceptions": ['))).toBe(beforeBytes.slice(beforeBytes.indexOf('  "exceptions": [')));
    expect(current.s33).toEqual({"cache":"s33-v32108-chromium-149.0.7827.55-42232322310","manifestSha256":"0e473a7a59f21fb909037024a6bb34c9959124b327a95d7c30db68a8f1fe7b12","provenanceSha256":"1c5cd12d34fc2347fd1b8f56ba9ca767a68dd9350a915c42ef7e4de68c49b860"});expect(current.s34).toEqual({"cache":"s34-v32108-chromium-149.0.7827.55-42357105281","manifestSha256":"1b6bbcd0df03a06e95be5e42b7163ea792f9d5a814a500695d2dfe008e032965","provenanceSha256":"a9b8658c83b4fa57bcd7c5f6fa4a1c93ee5626e2aba9fc55257cb40bc4550902"});expect(current.s35).toEqual({"cache":"s35-v32108-chromium-149.0.7827.55-43607096411","manifestSha256":"62d0a14bb63f0ea226c9246c80c9f72124fd869d3b1f22730a7b775bb6f9c6f9","provenanceSha256":"904d1edee324d0c84e92ff809ab4cffb1abcb3a6278e73ca75573b0db9e909dd"});delete current.s35;delete current.s34;delete current.s33;delete current.s32;delete current.integrityApproval;delete before.integrityApproval;
    expect(current).toEqual(before);
    const rows=continuationRows(data).filter(r=>r.screen==='S-32');
    expect(rows).toHaveLength(22);
    expect(rows.every(r=>r.verdict==='DESIGN-GAP'&&r.executed===false&&r.measured===false)).toBe(true);
  });
});
