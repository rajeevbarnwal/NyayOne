import {withoutS31ProposalsForTest,withoutS31PolicyBytesForTest} from './nyay66-s31-exceptions.test-fixture.mjs';
import {describe,it,expect} from 'vitest';
import {readFileSync,mkdtempSync,writeFileSync,rmSync,mkdirSync,symlinkSync} from 'node:fs';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import {execFileSync} from 'node:child_process';
import {fileURLToPath} from 'node:url';
import {PNG} from 'pngjs';
import {digest} from './nyay66-enforcement.mjs';
import {continuationRows} from './nyay66-continuation.mjs';
import {loadS31Source,S31_STATES,S31_VIEWPORTS,S31_PINS} from './nyay66-s31-reference.mjs';
import {verifyS31Archive,loadS31Cache} from './nyay66-s31-import.mjs';
const root=fileURLToPath(new URL('../../../',import.meta.url));
const {data}=await loadS31Source(root);
const policy=JSON.parse(readFileSync(join(root,'frontend/scripts/nyay66-policy.json')));
const fonts=JSON.parse(readFileSync(join(root,'frontend/test-baselines/nyay66',policy.cache,'manifest.json'))).fonts;
const sourceHead='a'.repeat(40),controlHead='b'.repeat(40);
const pngs=new Map(S31_VIEWPORTS.map(vp=>[vp.id,PNG.sync.write(new PNG({width:vp.width,height:vp.height}))]));
function archiveFixture(change=()=>{}){
  const dir=mkdtempSync(join(tmpdir(),'nyay-s31-import-test-'));
  const files=new Map(),rows=[];
  for(const state of S31_STATES)for(const vp of S31_VIEWPORTS){
    const bytes=pngs.get(vp.id),sha256=digest(bytes),file=`s31-${state}-${vp.id}-0.png`;
    files.set(file,bytes);rows.push({view:`s31-${state}`,viewport:vp.id,file,sha256,sampleHashes:Array(3).fill(sha256),dimensions:[vp.width,vp.height],
      surface:{controls:[],headings:[],masks:[],text:'synthetic',overflow:0,dimensions:[vp.width,vp.height]},fontStack:{viewport:'Public Sans',faces:[]},reviewerFrame:{borderRadius:'0px',x:0,y:0}});
  }
  const manifest={schema:1,purpose:'UNIMPORTED_REFERENCE_CALIBRATION',screen:'S-31',theme:'light',approval:data.designApproval,sourceArchiveSha256:data.archiveSha256,sourceSha256:data.htmlSha256,embeddedResources:data.inventory.embeddedResources,producerHead:sourceHead,controlHead,...S31_PINS,fonts,deferredStates:[],rows};
  const pins={purpose:'REFERENCE_GENERATION_ONLY_NOT_IMPORT_APPROVAL',sourceHead,reference:'s31-v32108',...S31_PINS,node:'v22.21.1',fonts};
  change(manifest,files,pins);
  files.set('manifest.json',Buffer.from(JSON.stringify(manifest)));
  files.set('runtime-pins.json',Buffer.from(JSON.stringify(pins)));
  files.set('SHA256SUMS',Buffer.from([...files].map(([name,bytes])=>`${digest(bytes)}  ${name}`).join('\n')+'\n'));
  for(const [name,bytes] of files)writeFileSync(join(dir,name),bytes);
  const path=join(dir,'calibration.zip');execFileSync('zip',['-q',path,...files.keys()],{cwd:dir});
  return {dir,path,expected:{archiveSha256:digest(readFileSync(path)),sourceHead,controlHead},files};
}
describe('S-31 archive import fails closed before writing',()=>{
  it('verifies the archive bytes, all 16 PNGs and the three-sample rehearsal inventory',async()=>{
    const f=archiveFixture();try{const got=await verifyS31Archive(f.path,f.expected,data,fonts);expect(got.manifest.rows).toHaveLength(16);expect(got.files.size).toBe(19);expect(got.archiveSha256).toBe(f.expected.archiveSha256);}finally{rmSync(f.dir,{recursive:true,force:true});}
  });
  it('rejects a tampered archive with its formerly valid digest',async()=>{
    const f=archiveFixture();try{writeFileSync(f.path,Buffer.concat([readFileSync(f.path),Buffer.from('tampered')]));await expect(verifyS31Archive(f.path,f.expected,data,fonts)).rejects.toThrow('S31_ARCHIVE_DIGEST_MISMATCH');}finally{rmSync(f.dir,{recursive:true,force:true});}
  });
  it('rejects a tampered PNG even with a recomputed archive and checksum list',async()=>{
    const f=archiveFixture((_m,files)=>{const [name,bytes]=files.entries().next().value;const altered=Buffer.from(bytes);altered[30]^=1;files.set(name,altered);});
    try{await expect(verifyS31Archive(f.path,f.expected,data,fonts)).rejects.toThrow('S31_REFERENCE_BYTES_MISMATCH');}finally{rmSync(f.dir,{recursive:true,force:true});}
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
    const f=archiveFixture(change);try{await expect(verifyS31Archive(f.path,f.expected,data,fonts)).rejects.toThrow();}finally{rmSync(f.dir,{recursive:true,force:true});}
  });
  it('requires an explicit safe cache binding without fabricating coverage',async()=>{
    expect(await loadS31Cache(root,undefined,data,fonts)).toBe(null);
    await expect(loadS31Cache(root,{cache:'../escape'},data,fonts)).rejects.toThrow('S31_INVALID_CACHE_BINDING');
  });
  it('rejects unexpected members and nonregular archive inputs',async()=>{
    const extra=archiveFixture((_m,files)=>files.set('unexpected.txt',Buffer.from('not an approved member')));
    try{await expect(verifyS31Archive(extra.path,extra.expected,data,fonts)).rejects.toThrow('S31_ARCHIVE_MEMBER_INVENTORY');}finally{rmSync(extra.dir,{recursive:true,force:true});}
    const f=archiveFixture();try{const link=join(f.dir,'linked.zip');symlinkSync(f.path,link);await expect(verifyS31Archive(link,f.expected,data,fonts)).rejects.toThrow('S31_NONREGULAR_INPUT');}finally{rmSync(f.dir,{recursive:true,force:true});}
  });
  it('revalidates cached bytes without promoting references to product measurements',async()=>{
    const f=archiveFixture();try{
      const cache='synthetic-s31',dir=join(f.dir,'frontend/test-baselines/nyay66',cache);mkdirSync(dir,{recursive:true});
      for(const [name,bytes] of f.files)writeFileSync(join(dir,name),bytes);
      const provenance=Buffer.from(JSON.stringify({...f.expected,runId:'1',artifactId:'2',referenceRows:16,manualRows:0}));
      writeFileSync(join(dir,'provenance.json'),provenance);
      const config={cache,manifestSha256:digest(f.files.get('manifest.json')),provenanceSha256:digest(provenance)};
      const got=await loadS31Cache(f.dir,config,data,fonts);
      expect(got.manifest.rows).toHaveLength(16);
      expect(got.manifest.rows.every(row=>row.measured===undefined&&row.executed===undefined&&row.verdict===undefined)).toBe(true);
      writeFileSync(join(dir,got.manifest.rows.at(-1).file),Buffer.from('tampered after import'));
      await expect(loadS31Cache(f.dir,config,data,fonts)).rejects.toThrow('S31_ARTIFACT_CHECKSUM_MISMATCH');
    }finally{rmSync(f.dir,{recursive:true,force:true});}
  });
  it('pins all 16 S-31 references and exact owner-dispatch provenance without changing historical policy or promoting coverage',async()=>{
    const got=await loadS31Cache(root,policy.s31,data,fonts);
    expect(got).not.toBe(null);expect(got.manifest.rows).toHaveLength(16);
    expect(got.provenance).toEqual({"status":"CANDIDATE_PENDING_OWNER_INTEGRITY_APPROVAL","runId":"41795771621","artifactId":"13304589417","archiveSha256":"2876a57251e5c74787822913ee7aaf3504dcc0644425fc1019a3bb3d33320458","sourceHead":"6c6005d26342a3cb97f9d8de3f4d11ddfe451e38","controlHead":"6c6005d26342a3cb97f9d8de3f4d11ddfe451e38","manifestSha256":"d16430a6a405418f506085111e4486741ba0d46aa25e7ad32fcc937d3f1778d9","referenceRows":16,"manualRows":0});
    expect(policy.s31).toEqual({"cache":"s31-v32108-chromium-149.0.7827.55-41795771621","manifestSha256":"d16430a6a405418f506085111e4486741ba0d46aa25e7ad32fcc937d3f1778d9","provenanceSha256":"cef8aedce696d134f8cdbff97a024bdd7d412a5a5441e14c809f31533326ae07"});
    expect(got.manifest.rows.map(({view,viewport,sha256,dimensions})=>({view,viewport,sha256,dimensions}))).toEqual([{"view":"s31-loading","viewport":"mobile390","sha256":"2fbc6455d035d3404a51a10a39f4de6d9930a82e3da0dc24f1ec2814f283dba3","dimensions":[390,844]},{"view":"s31-loading","viewport":"desktop","sha256":"eab3463bc47b06527baad06f617c1553e87c90e03f344060fa801e4888c02c18","dimensions":[1440,1024]},{"view":"s31-results","viewport":"mobile390","sha256":"05868a13f5af9821f7855a7ea158d6750fe120a0decb431a1ee2630b3c12a3aa","dimensions":[390,844]},{"view":"s31-results","viewport":"desktop","sha256":"c68c617c9924e70be09b8527f82d606d958d78e5ce361ea8f4f5c7c27a16cf6e","dimensions":[1440,1024]},{"view":"s31-filters-open","viewport":"mobile390","sha256":"8712c4ee8e6bec9246b611a024ed3feb67e745acedbd54c932dd6fe4d1e898e7","dimensions":[390,844]},{"view":"s31-filters-open","viewport":"desktop","sha256":"7049ee664b45bb917ac596706cc611c9a1bb71003f74aae8f605ed12a3a44858","dimensions":[1440,1024]},{"view":"s31-no-matches","viewport":"mobile390","sha256":"57f35c8ebb3f9ebb7529f58ef8ebc0cc90b43f2d86849e96fd74e4c0bc0eeb45","dimensions":[390,844]},{"view":"s31-no-matches","viewport":"desktop","sha256":"a2d3447ad75f9242be784a919cb3f631917cec9ac74f0d1c0fa5ecab7abbd4f3","dimensions":[1440,1024]},{"view":"s31-rate-limited","viewport":"mobile390","sha256":"295e39d744d094e9ca644104cd3012b5970ae2564574133cc43a3831bb44eac7","dimensions":[390,844]},{"view":"s31-rate-limited","viewport":"desktop","sha256":"085bc0638810591e83d597a2ac27b35224597513cc372b46aaa2938e692ad96f","dimensions":[1440,1024]},{"view":"s31-error","viewport":"mobile390","sha256":"aa5da5043326e4faa78ebfe074b1c7454bed9935c938b56bf6d9953c673bf898","dimensions":[390,844]},{"view":"s31-error","viewport":"desktop","sha256":"2c728e1617ef50183af5dae7da3a7b736c60d3bf2b4fa676390f1ced4edc2ff0","dimensions":[1440,1024]},{"view":"s31-offline","viewport":"mobile390","sha256":"7a83e5765a72c00e3debbf5a436d23a37cd2752a8236f9574184c88e241303d3","dimensions":[390,844]},{"view":"s31-offline","viewport":"desktop","sha256":"09e8487a4ee9dccf8353f088a7d06efff0b5c983c8cefbcd18d218c32a7f6e00","dimensions":[1440,1024]},{"view":"s31-page-2","viewport":"mobile390","sha256":"045e6be0a49e52f47befacfc73721ad33766063ffbf4f3b9ae68c4ec0497ab86","dimensions":[390,844]},{"view":"s31-page-2","viewport":"desktop","sha256":"df97102363b15c6482ad2e54834a5e27896d8aae355a647b85f1652071526064","dimensions":[1440,1024]}]);
    const beforeBytes=execFileSync('git',['show','6c6005d26342a3cb97f9d8de3f4d11ddfe451e38:frontend/scripts/nyay66-policy.json'],{cwd:root,encoding:'utf8'});
    const currentBytes=withoutS31PolicyBytesForTest(readFileSync(join(root,'frontend/scripts/nyay66-policy.json'),'utf8'));
    const before=JSON.parse(beforeBytes),current=structuredClone(policy);
    current.exceptions=withoutS31ProposalsForTest(current.exceptions);
    expect(current.exceptions).toHaveLength(232);
    expect(currentBytes.slice(currentBytes.indexOf('  "exceptions": ['))).toBe(beforeBytes.slice(beforeBytes.indexOf('  "exceptions": [')));
    expect(current.s32).toEqual({"cache":"s32-v32108-chromium-149.0.7827.55-42000573063","manifestSha256":"5e972c42dd42416603f3f6f69448cdbfc5497fefac61a5243ca28f857a6e13c0","provenanceSha256":"da6ce5a2091308254397c0d60e73505d82a75a2ea7dfb673e89155921ef6876d"});expect(current.s33).toEqual({"cache":"s33-v32108-chromium-149.0.7827.55-42232322310","manifestSha256":"0e473a7a59f21fb909037024a6bb34c9959124b327a95d7c30db68a8f1fe7b12","provenanceSha256":"1c5cd12d34fc2347fd1b8f56ba9ca767a68dd9350a915c42ef7e4de68c49b860"});expect(current.s34).toEqual({"cache":"s34-v32108-chromium-149.0.7827.55-42357105281","manifestSha256":"1b6bbcd0df03a06e95be5e42b7163ea792f9d5a814a500695d2dfe008e032965","provenanceSha256":"a9b8658c83b4fa57bcd7c5f6fa4a1c93ee5626e2aba9fc55257cb40bc4550902"});delete current.s34;delete current.s33;delete current.s32;delete current.s31;delete current.integrityApproval;delete before.integrityApproval;
    expect(current).toEqual(before);
    const rows=continuationRows(data).filter(r=>r.screen==='S-31');
    expect(rows).toHaveLength(16);
    expect(rows.every(r=>r.verdict==='DESIGN-GAP'&&r.executed===false&&r.measured===false)).toBe(true);
  });
});
