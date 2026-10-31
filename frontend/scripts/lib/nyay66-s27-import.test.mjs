import {s27Proposals,withoutS27ProposalsForTest} from './nyay66-s27-exceptions.test-fixture.mjs';
import {describe,it,expect} from 'vitest';
import {readFileSync,mkdtempSync,writeFileSync,rmSync,mkdirSync,symlinkSync} from 'node:fs';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import {execFileSync} from 'node:child_process';
import {fileURLToPath} from 'node:url';
import {PNG} from 'pngjs';
import {digest} from './nyay66-enforcement.mjs';
import {loadS27Source,S27_STATES,S27_VIEWPORTS,S27_PINS} from './nyay66-s27-reference.mjs';
import {verifyS27Archive,loadS27Cache} from './nyay66-s27-import.mjs';
import {continuationRows} from './nyay66-continuation.mjs';
const root=fileURLToPath(new URL('../../../',import.meta.url));
const {data}=await loadS27Source(root);
const policy=JSON.parse(readFileSync(join(root,'frontend/scripts/nyay66-policy.json')));
const fonts=JSON.parse(readFileSync(join(root,'frontend/test-baselines/nyay66',policy.cache,'manifest.json'))).fonts;
const sourceHead='a'.repeat(40),controlHead='b'.repeat(40);
const pngs=new Map(S27_VIEWPORTS.map(vp=>[vp.id,PNG.sync.write(new PNG({width:vp.width,height:vp.height}))]));
function archiveFixture(change=()=>{}){
  const dir=mkdtempSync(join(tmpdir(),'nyay-s27-import-test-'));
  const files=new Map(),rows=[];
  for(const state of S27_STATES)for(const vp of S27_VIEWPORTS){
    const bytes=pngs.get(vp.id),sha256=digest(bytes),file=`s27-${state}-${vp.id}-0.png`;
    files.set(file,bytes);rows.push({view:`s27-${state}`,viewport:vp.id,file,sha256,sampleHashes:Array(3).fill(sha256),dimensions:[vp.width,vp.height],
      surface:{controls:[],headings:[],masks:[],text:'synthetic',overflow:0,dimensions:[vp.width,vp.height]},fontStack:{viewport:'Public Sans',faces:[]},reviewerFrame:{borderRadius:'0px',x:0,y:0}});
  }
  const manifest={schema:1,purpose:'UNIMPORTED_REFERENCE_CALIBRATION',screen:'S-27',theme:'light',approval:data.designApproval,sourceArchiveSha256:data.archiveSha256,sourceSha256:data.htmlSha256,embeddedResources:data.inventory.embeddedResources,producerHead:sourceHead,controlHead,...S27_PINS,fonts,deferredStates:[],rows};
  const pins={purpose:'REFERENCE_GENERATION_ONLY_NOT_IMPORT_APPROVAL',sourceHead,reference:'s27-v32108',...S27_PINS,node:'v22.21.1',fonts};
  change(manifest,files,pins);
  files.set('manifest.json',Buffer.from(JSON.stringify(manifest)));
  files.set('runtime-pins.json',Buffer.from(JSON.stringify(pins)));
  files.set('SHA256SUMS',Buffer.from([...files].map(([name,bytes])=>`${digest(bytes)}  ${name}`).join('\n')+'\n'));
  for(const [name,bytes] of files)writeFileSync(join(dir,name),bytes);
  const path=join(dir,'calibration.zip');execFileSync('zip',['-q',path,...files.keys()],{cwd:dir});
  return {dir,path,expected:{archiveSha256:digest(readFileSync(path)),sourceHead,controlHead},files};
}
describe('S-27 archive import fails closed before writing',()=>{
  it('verifies the archive bytes, all 22 PNGs and the three-sample rehearsal inventory',async()=>{
    const f=archiveFixture();try{const got=await verifyS27Archive(f.path,f.expected,data,fonts);expect(got.manifest.rows).toHaveLength(22);expect(got.files.size).toBe(25);expect(got.archiveSha256).toBe(f.expected.archiveSha256);}finally{rmSync(f.dir,{recursive:true,force:true});}
  });
  it('rejects a tampered archive with its formerly valid digest',async()=>{
    const f=archiveFixture();try{writeFileSync(f.path,Buffer.concat([readFileSync(f.path),Buffer.from('tampered')]));await expect(verifyS27Archive(f.path,f.expected,data,fonts)).rejects.toThrow('S27_ARCHIVE_DIGEST_MISMATCH');}finally{rmSync(f.dir,{recursive:true,force:true});}
  });
  it('rejects a tampered PNG even with a recomputed archive and checksum list',async()=>{
    const f=archiveFixture((_m,files)=>{const [name,bytes]=files.entries().next().value;const altered=Buffer.from(bytes);altered[30]^=1;files.set(name,altered);});
    try{await expect(verifyS27Archive(f.path,f.expected,data,fonts)).rejects.toThrow('S27_REFERENCE_BYTES_MISMATCH');}finally{rmSync(f.dir,{recursive:true,force:true});}
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
    const f=archiveFixture(change);try{await expect(verifyS27Archive(f.path,f.expected,data,fonts)).rejects.toThrow();}finally{rmSync(f.dir,{recursive:true,force:true});}
  });
  it('requires an explicit safe cache binding without fabricating coverage',async()=>{
    expect(await loadS27Cache(root,undefined,data,fonts)).toBe(null);
    await expect(loadS27Cache(root,{cache:'../escape'},data,fonts)).rejects.toThrow('S27_INVALID_CACHE_BINDING');
  });
  it('rejects unexpected members and nonregular archive inputs',async()=>{
    const extra=archiveFixture((_m,files)=>files.set('unexpected.txt',Buffer.from('not an approved member')));
    try{await expect(verifyS27Archive(extra.path,extra.expected,data,fonts)).rejects.toThrow('S27_ARCHIVE_MEMBER_INVENTORY');}finally{rmSync(extra.dir,{recursive:true,force:true});}
    const f=archiveFixture();try{const link=join(f.dir,'linked.zip');symlinkSync(f.path,link);await expect(verifyS27Archive(link,f.expected,data,fonts)).rejects.toThrow('S27_NONREGULAR_INPUT');}finally{rmSync(f.dir,{recursive:true,force:true});}
  });
  it('revalidates cached bytes without promoting references to product measurements',async()=>{
    const f=archiveFixture();try{
      const cache='synthetic-s27',dir=join(f.dir,'frontend/test-baselines/nyay66',cache);mkdirSync(dir,{recursive:true});
      for(const [name,bytes] of f.files)writeFileSync(join(dir,name),bytes);
      const provenance=Buffer.from(JSON.stringify({...f.expected,runId:'1',artifactId:'2',referenceRows:22,manualRows:0}));
      writeFileSync(join(dir,'provenance.json'),provenance);
      const config={cache,manifestSha256:digest(f.files.get('manifest.json')),provenanceSha256:digest(provenance)};
      const got=await loadS27Cache(f.dir,config,data,fonts);
      expect(got.manifest.rows).toHaveLength(22);
      expect(got.manifest.rows.every(row=>row.measured===undefined&&row.executed===undefined&&row.verdict===undefined)).toBe(true);
      writeFileSync(join(dir,got.manifest.rows.at(-1).file),Buffer.from('tampered after import'));
      await expect(loadS27Cache(f.dir,config,data,fonts)).rejects.toThrow('S27_ARTIFACT_CHECKSUM_MISMATCH');
    }finally{rmSync(f.dir,{recursive:true,force:true});}
  });
  it('pins the exact owner-dispatched S-27 cache without changing any historical policy record',async()=>{
    const got=await loadS27Cache(root,policy.s27,data,fonts);
    expect(got).not.toBe(null);expect(got.manifest.rows).toHaveLength(22);
    expect(got.provenance).toEqual({"status":"CANDIDATE_PENDING_OWNER_INTEGRITY_APPROVAL","runId":"41104712468","artifactId":"13001086396","archiveSha256":"78e78edfc0db48f76b85c87ebc02e69721da02bd805a7cc713849f4fc1d6514e","sourceHead":"e80c75f0095bd0a39c93408bf68c7a2773878958","controlHead":"e80c75f0095bd0a39c93408bf68c7a2773878958","manifestSha256":"fc702af18fc6ad997149669b88cae1dec2e8247beb7a4068b22c9ecccc078b44","referenceRows":22,"manualRows":0});
    expect(policy.s27).toEqual({"cache":"s27-v32108-chromium-149.0.7827.55-41104712468","manifestSha256":"fc702af18fc6ad997149669b88cae1dec2e8247beb7a4068b22c9ecccc078b44","provenanceSha256":"aee7a39dafe6fa056b0c9bfb304b0d7ccf1567ca1763ccd0b76a694bcf7b9e5f"});
    expect(got.manifest.rows.map(({view,viewport,sha256,dimensions})=>({view,viewport,sha256,dimensions}))).toEqual([{"view":"s27-loading","viewport":"mobile390","sha256":"de4f4256f2ba34460128d7ade71c40c0610547eaa9360f0d7f91d70505a0789e","dimensions":[390,844]},{"view":"s27-loading","viewport":"desktop","sha256":"0417bfe6ae86d982771b63d9a9cf83fbce4d3e100eff8303130f4cc106edab6d","dimensions":[1440,1024]},{"view":"s27-results","viewport":"mobile390","sha256":"a10e88fceef7957cccffdd5b85dfd0aa32eba22d832bf1be05aa22799c02ae66","dimensions":[390,844]},{"view":"s27-results","viewport":"desktop","sha256":"ae8c29e2da7721ef486026b564e27a77109f2dd4b270fd947ce988ef43edcc05","dimensions":[1440,1024]},{"view":"s27-filters-open","viewport":"mobile390","sha256":"398498a9f3543d4f89a2022725de8181c5609982117db3de9361a49bdbab0976","dimensions":[390,844]},{"view":"s27-filters-open","viewport":"desktop","sha256":"4fe8d6e18b002d1cd8d7be5203db0954f49420d1a5f0d7a0009fe97102ac929a","dimensions":[1440,1024]},{"view":"s27-compare","viewport":"mobile390","sha256":"b73019ac6561dbaa0e314016db288b361962a09025d5606be47acbb9584f10da","dimensions":[390,844]},{"view":"s27-compare","viewport":"desktop","sha256":"ac80e6fff76ebb37646e7821d70cc9d34e09f8183855a79fb6cdb3bbb4405d7c","dimensions":[1440,1024]},{"view":"s27-no-results","viewport":"mobile390","sha256":"dc4e2414993bc872ebb66a20a173c2cacf82afaf8fe910f4515523db1ced1400","dimensions":[390,844]},{"view":"s27-no-results","viewport":"desktop","sha256":"4cc3d99bb4a43acfe80669247a12452589c483bfc748a9cbe98b3b6fb8748231","dimensions":[1440,1024]},{"view":"s27-invalid-filter","viewport":"mobile390","sha256":"1257c87d50be77fd26caba76f78a32d95ba8174bc95df04678bb784604ce2836","dimensions":[390,844]},{"view":"s27-invalid-filter","viewport":"desktop","sha256":"b37fe87707c67b496dcff9a1b7707f54510d89f224b8480622c33163605c5abe","dimensions":[1440,1024]},{"view":"s27-error","viewport":"mobile390","sha256":"a0f7ebc41c514085d5348c9f7f47f01d1c035d3ec9d71e3c0b70707beed5768c","dimensions":[390,844]},{"view":"s27-error","viewport":"desktop","sha256":"23c25c805612f5bdf857b7bc037fed27bb2a5c35585848445fb3111eb28cc891","dimensions":[1440,1024]},{"view":"s27-offline","viewport":"mobile390","sha256":"07bc47c3de72b81f70522402cdf2e0f9e9ab774c172ef8ff1886a74a7b280c16","dimensions":[390,844]},{"view":"s27-offline","viewport":"desktop","sha256":"0d927870a816424c21a2c642b1f5e2c9f12164d64ee9a802f565d0fa5a2a8cbd","dimensions":[1440,1024]},{"view":"s27-page-2","viewport":"mobile390","sha256":"ea5bb677f51211ef8bd6a81414cbd6b330ee8bec3e514a83b37dc68703de3341","dimensions":[390,844]},{"view":"s27-page-2","viewport":"desktop","sha256":"8983d8fad2e0a315af229e9b6a6914f7dc9c29c52e981031c29ddef40295710e","dimensions":[1440,1024]},{"view":"s27-sort-fees","viewport":"mobile390","sha256":"0866c2201508db51a343b51971bfbc8f7de04eb49413f9c2a6eb5b23f367b55b","dimensions":[390,844]},{"view":"s27-sort-fees","viewport":"desktop","sha256":"311b2f1a52d2717590ac3a3cea17fe357b8703c28f8dcdf8047864144e38b47c","dimensions":[1440,1024]},{"view":"s27-sort-nirf","viewport":"mobile390","sha256":"2b7a0c0e88a37268984af6171ca5371d9d88267dff5ee9afd001b118855bb6c7","dimensions":[390,844]},{"view":"s27-sort-nirf","viewport":"desktop","sha256":"820e3f2a888f77f0b6984003774746155d769b6b9d97b473b2a5b91d5cde4ad2","dimensions":[1440,1024]}]);
    const before=JSON.parse(execFileSync('git',['show','e80c75f0095bd0a39c93408bf68c7a2773878958:frontend/scripts/nyay66-policy.json'],{cwd:root}));
    const withAdditions=[...policy.exceptions.filter(e=>e.screen!=='S-27'),...structuredClone(s27Proposals)];
    expect(withoutS27ProposalsForTest(withAdditions)).toHaveLength(168);
    expect(JSON.stringify(withoutS27ProposalsForTest(withAdditions))).toBe(JSON.stringify(before.exceptions));
    expect(withoutS27ProposalsForTest(policy.exceptions)).toHaveLength(168);
    expect(JSON.stringify(withoutS27ProposalsForTest(policy.exceptions))).toBe(JSON.stringify(before.exceptions));
    const current=structuredClone(policy);current.exceptions=withoutS27ProposalsForTest(current.exceptions);delete current.s27;delete current.integrityApproval;delete before.integrityApproval;
    expect(current).toEqual(before);
    const rows=continuationRows(data).filter(r=>r.screen==='S-27');
    expect(rows).toHaveLength(22);
    expect(rows.every(r=>r.verdict==='DESIGN-GAP'&&r.executed===false&&r.measured===false)).toBe(true);
  });
});
