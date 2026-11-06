import {withoutS33ProposalsForTest,withoutS33PolicyBytesForTest} from './nyay66-s33-exceptions.test-fixture.mjs';
import {continuationRows} from './nyay66-continuation.mjs';
import {describe,it,expect} from 'vitest';
import {readFileSync,mkdtempSync,writeFileSync,rmSync,mkdirSync,symlinkSync} from 'node:fs';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import {execFileSync} from 'node:child_process';
import {fileURLToPath} from 'node:url';
import {PNG} from 'pngjs';
import {digest} from './nyay66-enforcement.mjs';
import {loadS33Source,S33_STATES,S33_VIEWPORTS,S33_PINS} from './nyay66-s33-reference.mjs';
import {verifyS33Archive,loadS33Cache} from './nyay66-s33-import.mjs';
const root=fileURLToPath(new URL('../../../',import.meta.url));
const {data}=await loadS33Source(root);
const policy=JSON.parse(readFileSync(join(root,'frontend/scripts/nyay66-policy.json')));
const fonts=JSON.parse(readFileSync(join(root,'frontend/test-baselines/nyay66',policy.cache,'manifest.json'))).fonts;
const sourceHead='a'.repeat(40),controlHead='b'.repeat(40);
const pngs=new Map(S33_VIEWPORTS.map(vp=>[vp.id,PNG.sync.write(new PNG({width:vp.width,height:vp.height}))]));
function archiveFixture(change=()=>{}){
  const dir=mkdtempSync(join(tmpdir(),'nyay-s33-import-test-'));
  const files=new Map(),rows=[];
  for(const state of S33_STATES)for(const vp of S33_VIEWPORTS){
    const bytes=pngs.get(vp.id),sha256=digest(bytes),file=`s33-${state}-${vp.id}-0.png`;
    files.set(file,bytes);rows.push({view:`s33-${state}`,viewport:vp.id,file,sha256,sampleHashes:Array(3).fill(sha256),dimensions:[vp.width,vp.height],
      surface:{controls:[],headings:[],masks:[],text:'synthetic',overflow:0,dimensions:[vp.width,vp.height]},fontStack:{viewport:'Public Sans',faces:[]},reviewerFrame:{borderRadius:'0px',x:0,y:0}});
  }
  const manifest={schema:1,purpose:'UNIMPORTED_REFERENCE_CALIBRATION',screen:'S-33',theme:'light',approval:data.designApproval,sourceArchiveSha256:data.archiveSha256,sourceSha256:data.htmlSha256,embeddedResources:data.inventory.embeddedResources,producerHead:sourceHead,controlHead,...S33_PINS,fonts,deferredStates:[],rows};
  const pins={purpose:'REFERENCE_GENERATION_ONLY_NOT_IMPORT_APPROVAL',sourceHead,reference:'s33-v32108',...S33_PINS,node:'v22.21.1',fonts};
  change(manifest,files,pins);
  files.set('manifest.json',Buffer.from(JSON.stringify(manifest)));
  files.set('runtime-pins.json',Buffer.from(JSON.stringify(pins)));
  files.set('SHA256SUMS',Buffer.from([...files].map(([name,bytes])=>`${digest(bytes)}  ${name}`).join('\n')+'\n'));
  for(const [name,bytes] of files)writeFileSync(join(dir,name),bytes);
  const path=join(dir,'calibration.zip');execFileSync('zip',['-q',path,...files.keys()],{cwd:dir});
  return {dir,path,expected:{archiveSha256:digest(readFileSync(path)),sourceHead,controlHead},files};
}
describe('S-33 archive import fails closed before writing',()=>{
  it('verifies the archive bytes, all 28 PNGs and the three-sample rehearsal inventory',async()=>{
    const f=archiveFixture();try{const got=await verifyS33Archive(f.path,f.expected,data,fonts);expect(got.manifest.rows).toHaveLength(28);expect(got.files.size).toBe(31);expect(got.archiveSha256).toBe(f.expected.archiveSha256);}finally{rmSync(f.dir,{recursive:true,force:true});}
  });
  it('rejects a tampered archive with its formerly valid digest',async()=>{
    const f=archiveFixture();try{writeFileSync(f.path,Buffer.concat([readFileSync(f.path),Buffer.from('tampered')]));await expect(verifyS33Archive(f.path,f.expected,data,fonts)).rejects.toThrow('S33_ARCHIVE_DIGEST_MISMATCH');}finally{rmSync(f.dir,{recursive:true,force:true});}
  });
  it('rejects a tampered PNG even with a recomputed archive and checksum list',async()=>{
    const f=archiveFixture((_m,files)=>{const [name,bytes]=files.entries().next().value;const altered=Buffer.from(bytes);altered[30]^=1;files.set(name,altered);});
    try{await expect(verifyS33Archive(f.path,f.expected,data,fonts)).rejects.toThrow('S33_REFERENCE_BYTES_MISMATCH');}finally{rmSync(f.dir,{recursive:true,force:true});}
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
    const f=archiveFixture(change);try{await expect(verifyS33Archive(f.path,f.expected,data,fonts)).rejects.toThrow();}finally{rmSync(f.dir,{recursive:true,force:true});}
  });
  it('requires an explicit safe cache binding without fabricating coverage',async()=>{
    expect(await loadS33Cache(root,undefined,data,fonts)).toBe(null);
    await expect(loadS33Cache(root,{cache:'../escape'},data,fonts)).rejects.toThrow('S33_INVALID_CACHE_BINDING');
  });
  it('rejects unexpected members and nonregular archive inputs',async()=>{
    const extra=archiveFixture((_m,files)=>files.set('unexpected.txt',Buffer.from('not an approved member')));
    try{await expect(verifyS33Archive(extra.path,extra.expected,data,fonts)).rejects.toThrow('S33_ARCHIVE_MEMBER_INVENTORY');}finally{rmSync(extra.dir,{recursive:true,force:true});}
    const f=archiveFixture();try{const link=join(f.dir,'linked.zip');symlinkSync(f.path,link);await expect(verifyS33Archive(link,f.expected,data,fonts)).rejects.toThrow('S33_NONREGULAR_INPUT');}finally{rmSync(f.dir,{recursive:true,force:true});}
  });
  it('revalidates cached bytes without promoting references to product measurements',async()=>{
    const f=archiveFixture();try{
      const cache='synthetic-s33',dir=join(f.dir,'frontend/test-baselines/nyay66',cache);mkdirSync(dir,{recursive:true});
      for(const [name,bytes] of f.files)writeFileSync(join(dir,name),bytes);
      const provenance=Buffer.from(JSON.stringify({...f.expected,runId:'1',artifactId:'2',referenceRows:28,manualRows:0}));
      writeFileSync(join(dir,'provenance.json'),provenance);
      const config={cache,manifestSha256:digest(f.files.get('manifest.json')),provenanceSha256:digest(provenance)};
      const got=await loadS33Cache(f.dir,config,data,fonts);
      expect(got.manifest.rows).toHaveLength(28);
      expect(got.manifest.rows.every(row=>row.measured===undefined&&row.executed===undefined&&row.verdict===undefined)).toBe(true);
      writeFileSync(join(dir,got.manifest.rows.at(-1).file),Buffer.from('tampered after import'));
      await expect(loadS33Cache(f.dir,config,data,fonts)).rejects.toThrow('S33_ARTIFACT_CHECKSUM_MISMATCH');
    }finally{rmSync(f.dir,{recursive:true,force:true});}
  });
  it('requires separate product capture after loading the verified reference cache',()=>{
    const live=readFileSync(join(root,'frontend/scripts/nyay66-live.mjs'),'utf8');
    expect(live).toContain("import {loadS33Cache} from './lib/nyay66-s33-import.mjs'");
    expect(live).toContain('await loadS33Cache(root,config.s33,continuation,manifest.fonts)');
    expect(live).toContain('report.s33Reference={cache:config.s33.cache,manifestSha256:config.s33.manifestSha256,provenance:s33.provenance}');
    expect(live).toContain('await captureS33Rows({browser,origin,out,reference:s33})');
  });
  it('pins all 28 references and exact owner-dispatch provenance while preserving historical policy and DESIGN-GAP rows',async()=>{
    const got=await loadS33Cache(root,policy.s33,data,fonts);
    expect(got).not.toBe(null);expect(got.manifest.rows).toHaveLength(28);
    expect(got.provenance).toEqual({"status":"CANDIDATE_PENDING_OWNER_INTEGRITY_APPROVAL","runId":"42232322310","artifactId":"13510893626","archiveSha256":"6eda0e0f5df58f56609e1d2cb080c7f2490655f57c77b2227d9efe6b3c8133fa","sourceHead":"684942d308f43c131a1adf76e530aa72a4f513ed","controlHead":"684942d308f43c131a1adf76e530aa72a4f513ed","manifestSha256":"0e473a7a59f21fb909037024a6bb34c9959124b327a95d7c30db68a8f1fe7b12","referenceRows":28,"manualRows":0});
    expect(policy.s33).toEqual({"cache":"s33-v32108-chromium-149.0.7827.55-42232322310","manifestSha256":"0e473a7a59f21fb909037024a6bb34c9959124b327a95d7c30db68a8f1fe7b12","provenanceSha256":"1c5cd12d34fc2347fd1b8f56ba9ca767a68dd9350a915c42ef7e4de68c49b860"});
    expect(got.manifest.rows.map(({view,viewport,sha256,dimensions})=>({view,viewport,sha256,dimensions}))).toEqual([{"view":"s33-hold-creating","viewport":"mobile390","sha256":"94aa70ced75623489a2276f5ea3275215320398a5a4d67a82b3ca799f03b417f","dimensions":[390,844]},{"view":"s33-hold-creating","viewport":"desktop","sha256":"73deed42942056545aea053cae85a3313dd0fdcb9c1c0f2564bc4af1a91e1d1e","dimensions":[1440,1024]},{"view":"s33-hold-active","viewport":"mobile390","sha256":"22009a2cfec75af90266fe988cb3b794cf20efbe50e29603cc4d47b14989132b","dimensions":[390,844]},{"view":"s33-hold-active","viewport":"desktop","sha256":"3d57f6453e6ea6f6b3ac6c3c8002424ef138ffae29f2db350fa45446957274c8","dimensions":[1440,1024]},{"view":"s33-slot-conflict","viewport":"mobile390","sha256":"1a1cf72d1d56b93b99230c581ea31c8f5c58c51f1d160d1325557572467f0a70","dimensions":[390,844]},{"view":"s33-slot-conflict","viewport":"desktop","sha256":"790f393b2a6052c162e3a2609b90ff4729e1de33fd3b88f0408dd256235e59dd","dimensions":[1440,1024]},{"view":"s33-hold-expired","viewport":"mobile390","sha256":"4bdfd0cb37cf8f11bf30783f789fd4e86f3d20b733a6b7998cc644572929835f","dimensions":[390,844]},{"view":"s33-hold-expired","viewport":"desktop","sha256":"587de568c5e18717780661bdc56f81f02e2628d25437bbd52624c3228dc7db5a","dimensions":[1440,1024]},{"view":"s33-order-pending","viewport":"mobile390","sha256":"1ca3c37f89d808b109e616f5377691b9610fe0043af83b14089a38f42a3dc3e5","dimensions":[390,844]},{"view":"s33-order-pending","viewport":"desktop","sha256":"d694311b8c06c93a00e91554d99468fd47d373f911381d43134908458ddb44be","dimensions":[1440,1024]},{"view":"s33-payment-failed","viewport":"mobile390","sha256":"d1053e5b282a5954834e32eb16ab8f54df8f77c5d6a622bf418f4c5f48d50a84","dimensions":[390,844]},{"view":"s33-payment-failed","viewport":"desktop","sha256":"6ffbc9086e4b90329f8af188c5627dd895b77437c61cd6367cdea0994a423d1b","dimensions":[1440,1024]},{"view":"s33-creating-session","viewport":"mobile390","sha256":"76596252616b65905707d7dbe3585e5747e9f15d0c2c3a14aae38f67c298c14f","dimensions":[390,844]},{"view":"s33-creating-session","viewport":"desktop","sha256":"bf959536eb673bd2cfc5add0363758ad04204d3a91202679efe619b97d7648fa","dimensions":[1440,1024]},{"view":"s33-payment-unverified","viewport":"mobile390","sha256":"0d3eb8d3869e6585d4701f6f1facde2e3d71e5b3532d909c0a760f430e0bde6e","dimensions":[390,844]},{"view":"s33-payment-unverified","viewport":"desktop","sha256":"69c4f4565af7c180b8c7bca19b161a585c970d4b4787abaa175e58851be7a289","dimensions":[1440,1024]},{"view":"s33-confirmed","viewport":"mobile390","sha256":"ad3e7a16946f52acd89edf63151e4e93e563805eb641086e6ffea85820acec64","dimensions":[390,844]},{"view":"s33-confirmed","viewport":"desktop","sha256":"2588fc05bd38aa2e3fa71cf9911cf2bcc7bc25dde61cea01ded066ef2bf27901","dimensions":[1440,1024]},{"view":"s33-rate-limited","viewport":"mobile390","sha256":"08518fd9bc01f957da96fd32dfb29e19c1a6fba678e7e3f7ed176a8ef175d17d","dimensions":[390,844]},{"view":"s33-rate-limited","viewport":"desktop","sha256":"bd7aced700ee3f7c90b0318f145b88cddd6e7cabfb557d66ecaacf3252d507a4","dimensions":[1440,1024]},{"view":"s33-network","viewport":"mobile390","sha256":"5004d983b726e73ac77b3db2f8509b4c5e71735972c9f5d512688ebcf9fbb5f3","dimensions":[390,844]},{"view":"s33-network","viewport":"desktop","sha256":"94491e4fd33eb819f247387d1b146ebf40589154f8660cb6eb3e6b6caf5c8459","dimensions":[1440,1024]},{"view":"s33-session","viewport":"mobile390","sha256":"c45ff9d15e0b659a6f53ab27303e1f9b405767edfc038abb697caba9fd4d5e66","dimensions":[390,844]},{"view":"s33-session","viewport":"desktop","sha256":"fe44afc2e60cca106c354771a1d2404c226f8bca437e23029ae86e3da5a04443","dimensions":[1440,1024]},{"view":"s33-hold-60min","viewport":"mobile390","sha256":"39eddc3276f8f929cf0ecbd41ce8fe2f4f3c9d75458b25031c36b2f841df5ddd","dimensions":[390,844]},{"view":"s33-hold-60min","viewport":"desktop","sha256":"36e279a6d7442b06f97eed8292aef35be5c6298d866b43a9f8c222a64e1935b2","dimensions":[1440,1024]},{"view":"s33-hold-other-mentor","viewport":"mobile390","sha256":"6eaab25cf9aa04e0168edcd4fb0616dabd85f965206a748e16a222282ee5290a","dimensions":[390,844]},{"view":"s33-hold-other-mentor","viewport":"desktop","sha256":"16b53b775accec167b74d37fdb5541ec725b344c9bbcacfa276de06d0e992e2e","dimensions":[1440,1024]}]);
    const beforeBytes=execFileSync('git',['show','684942d308f43c131a1adf76e530aa72a4f513ed:frontend/scripts/nyay66-policy.json'],{cwd:root,encoding:'utf8'});
    const currentBytes=withoutS33PolicyBytesForTest(readFileSync(join(root,'frontend/scripts/nyay66-policy.json'),'utf8'));
    const before=JSON.parse(beforeBytes),current=structuredClone(policy);
    current.exceptions=withoutS33ProposalsForTest(current.exceptions);
    expect(current.exceptions).toHaveLength(270);
    expect(currentBytes.slice(currentBytes.indexOf('  "exceptions": ['))).toBe(beforeBytes.slice(beforeBytes.indexOf('  "exceptions": [')));
    delete current.s33;delete current.integrityApproval;delete before.integrityApproval;
    expect(current).toEqual(before);
    const rows=continuationRows(data).filter(r=>r.screen==='S-33');
    expect(rows).toHaveLength(28);
    expect(rows.every(r=>r.verdict==='DESIGN-GAP'&&r.executed===false&&r.measured===false)).toBe(true);
  });
});
