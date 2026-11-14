import {describe,it,expect} from 'vitest';
import {continuationRows} from './nyay66-continuation.mjs';
import {readFileSync,mkdtempSync,writeFileSync,rmSync,mkdirSync,symlinkSync} from 'node:fs';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import {execFileSync} from 'node:child_process';
import {fileURLToPath} from 'node:url';
import {PNG} from 'pngjs';
import {digest} from './nyay66-enforcement.mjs';
import {loadS35Source,S35_STATES,S35_VIEWPORTS,S35_PINS} from './nyay66-s35-reference.mjs';
import {verifyS35Archive,loadS35Cache} from './nyay66-s35-import.mjs';
const root=fileURLToPath(new URL('../../../',import.meta.url));
const {data}=await loadS35Source(root);
const policy=JSON.parse(readFileSync(join(root,'frontend/scripts/nyay66-policy.json')));
const fonts=JSON.parse(readFileSync(join(root,'frontend/test-baselines/nyay66',policy.cache,'manifest.json'))).fonts;
const sourceHead='a'.repeat(40),controlHead='b'.repeat(40);
const pngs=new Map(S35_VIEWPORTS.map(vp=>[vp.id,PNG.sync.write(new PNG({width:vp.width,height:vp.height}))]));
function archiveFixture(change=()=>{}){
  const dir=mkdtempSync(join(tmpdir(),'nyay-s35-import-test-'));
  const files=new Map(),rows=[];
  for(const state of S35_STATES)for(const vp of S35_VIEWPORTS){
    const bytes=pngs.get(vp.id),sha256=digest(bytes),file=`s35-${state}-${vp.id}-0.png`;
    files.set(file,bytes);rows.push({view:`s35-${state}`,viewport:vp.id,file,sha256,sampleHashes:Array(3).fill(sha256),dimensions:[vp.width,vp.height],
      surface:{controls:[],headings:[],masks:[],text:'synthetic',overflow:0,dimensions:[vp.width,vp.height]},fontStack:{viewport:'Public Sans',faces:[]},reviewerFrame:{borderRadius:'0px',x:0,y:0}});
  }
  const manifest={schema:1,purpose:'UNIMPORTED_REFERENCE_CALIBRATION',screen:'S-35',theme:'light',approval:data.designApproval,sourceArchiveSha256:data.archiveSha256,sourceSha256:data.htmlSha256,embeddedResources:data.inventory.embeddedResources,producerHead:sourceHead,controlHead,...S35_PINS,fonts,deferredStates:[],rows};
  const pins={purpose:'REFERENCE_GENERATION_ONLY_NOT_IMPORT_APPROVAL',sourceHead,reference:'s35-v32108',...S35_PINS,node:'v22.21.1',fonts};
  change(manifest,files,pins);
  files.set('manifest.json',Buffer.from(JSON.stringify(manifest)));
  files.set('runtime-pins.json',Buffer.from(JSON.stringify(pins)));
  files.set('SHA256SUMS',Buffer.from([...files].map(([name,bytes])=>`${digest(bytes)}  ${name}`).join('\n')+'\n'));
  for(const [name,bytes] of files)writeFileSync(join(dir,name),bytes);
  const path=join(dir,'calibration.zip');execFileSync('zip',['-q',path,...files.keys()],{cwd:dir});
  return {dir,path,expected:{archiveSha256:digest(readFileSync(path)),sourceHead,controlHead},files};
}
describe('S-35 archive import fails closed before writing',()=>{
  it('verifies the archive bytes, all 112 PNGs and the three-sample rehearsal inventory',async()=>{
    const f=archiveFixture();try{const got=await verifyS35Archive(f.path,f.expected,data,fonts);expect(got.manifest.rows).toHaveLength(112);expect(got.files.size).toBe(115);expect(got.archiveSha256).toBe(f.expected.archiveSha256);}finally{rmSync(f.dir,{recursive:true,force:true});}
  });
  it('rejects a tampered archive with its formerly valid digest',async()=>{
    const f=archiveFixture();try{writeFileSync(f.path,Buffer.concat([readFileSync(f.path),Buffer.from('tampered')]));await expect(verifyS35Archive(f.path,f.expected,data,fonts)).rejects.toThrow('S35_ARCHIVE_DIGEST_MISMATCH');}finally{rmSync(f.dir,{recursive:true,force:true});}
  });
  it('rejects a tampered PNG even with a recomputed archive and checksum list',async()=>{
    const f=archiveFixture((_m,files)=>{const [name,bytes]=files.entries().next().value;const altered=Buffer.from(bytes);altered[30]^=1;files.set(name,altered);});
    try{await expect(verifyS35Archive(f.path,f.expected,data,fonts)).rejects.toThrow('S35_REFERENCE_BYTES_MISMATCH');}finally{rmSync(f.dir,{recursive:true,force:true});}
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
    const f=archiveFixture(change);try{await expect(verifyS35Archive(f.path,f.expected,data,fonts)).rejects.toThrow();}finally{rmSync(f.dir,{recursive:true,force:true});}
  });
  it('requires an explicit safe cache binding without fabricating coverage',async()=>{
    expect(await loadS35Cache(root,undefined,data,fonts)).toBe(null);
    await expect(loadS35Cache(root,{cache:'../escape'},data,fonts)).rejects.toThrow('S35_INVALID_CACHE_BINDING');
  });
  it('rejects unexpected members and nonregular archive inputs',async()=>{
    const extra=archiveFixture((_m,files)=>files.set('unexpected.txt',Buffer.from('not an approved member')));
    try{await expect(verifyS35Archive(extra.path,extra.expected,data,fonts)).rejects.toThrow('S35_ARCHIVE_MEMBER_INVENTORY');}finally{rmSync(extra.dir,{recursive:true,force:true});}
    const f=archiveFixture();try{const link=join(f.dir,'linked.zip');symlinkSync(f.path,link);await expect(verifyS35Archive(link,f.expected,data,fonts)).rejects.toThrow('S35_NONREGULAR_INPUT');}finally{rmSync(f.dir,{recursive:true,force:true});}
  });
  it('revalidates cached bytes without promoting references to product measurements',async()=>{
    const f=archiveFixture();try{
      const cache='synthetic-s35',dir=join(f.dir,'frontend/test-baselines/nyay66',cache);mkdirSync(dir,{recursive:true});
      for(const [name,bytes] of f.files)writeFileSync(join(dir,name),bytes);
      const provenance=Buffer.from(JSON.stringify({...f.expected,runId:'1',artifactId:'2',referenceRows:112,manualRows:0}));
      writeFileSync(join(dir,'provenance.json'),provenance);
      const config={cache,manifestSha256:digest(f.files.get('manifest.json')),provenanceSha256:digest(provenance)};
      const got=await loadS35Cache(f.dir,config,data,fonts);
      expect(got.manifest.rows).toHaveLength(112);
      expect(got.manifest.rows.every(row=>row.measured===undefined&&row.executed===undefined&&row.verdict===undefined)).toBe(true);
      writeFileSync(join(dir,got.manifest.rows.at(-1).file),Buffer.from('tampered after import'));
      await expect(loadS35Cache(f.dir,config,data,fonts)).rejects.toThrow('S35_ARTIFACT_CHECKSUM_MISMATCH');
    }finally{rmSync(f.dir,{recursive:true,force:true});}
  });
});

describe('S-35 reference-only integration',()=>{
  it('verifies imported cache before capture without claiming S-35 product measurement',()=>{
    const live=readFileSync(join(root,'frontend/scripts/nyay66-live.mjs'),'utf8');
    expect(live).toContain("import {loadS35Cache} from './lib/nyay66-s35-import.mjs'");
    expect(live).toContain('await loadS35Cache(root,config.s35,continuation,manifest.fonts)');
    expect(live).toContain('if(s35)report.s35Reference={cache:config.s35.cache,manifestSha256:config.s35.manifestSha256,provenance:s35.provenance}');
    expect(live).not.toContain('captureS35Rows');
    expect(live).not.toContain('s35:!!s35');
  });
});

// This import adds references only. The SHA pins bind every manifest row and source byte.
describe('S-35 owner-dispatched reference provenance',()=>{
  it('pins the completed 112-row artifact and independently validates every cached PNG',async()=>{
    expect(policy.s35).toEqual({"cache":"s35-v32108-chromium-149.0.7827.55-43607096411","manifestSha256":"62d0a14bb63f0ea226c9246c80c9f72124fd869d3b1f22730a7b775bb6f9c6f9","provenanceSha256":"904d1edee324d0c84e92ff809ab4cffb1abcb3a6278e73ca75573b0db9e909dd"});
    const got=await loadS35Cache(root,policy.s35,data,fonts);
    expect(got.provenance).toEqual({"status":"CANDIDATE_PENDING_OWNER_INTEGRITY_APPROVAL","runId":"43607096411","artifactId":"14119575817","archiveSha256":"c9168271cf9d5d5ae3d96d6447348dbf29eb98e31405ddb2b162ba738288cc76","sourceHead":"25575eba78deabff1ec75f30a2fd676c82d80b11","controlHead":"25575eba78deabff1ec75f30a2fd676c82d80b11","manifestSha256":"62d0a14bb63f0ea226c9246c80c9f72124fd869d3b1f22730a7b775bb6f9c6f9","referenceRows":112,"manualRows":0});
    expect(got.manifest.rows).toHaveLength(112);
    expect(new Set(got.manifest.rows.map(r=>`${r.view}:${r.viewport}`)).size).toBe(112);
    for(const row of got.manifest.rows){
      expect(row.sampleHashes).toEqual([row.sha256,row.sha256,row.sha256]);
      expect(row.executed).toBeUndefined();expect(row.measured).toBeUndefined();expect(row.verdict).toBeUndefined();
    }
  });
  it('preserves all historical policy settings and the 310 exception records byte-for-byte',()=>{
    const current=structuredClone(policy);delete current.s35;delete current.integrityApproval;
    expect(digest(JSON.stringify(current))).toBe('1c15b06b8ba3793341a81f994db2929e318e811a67ee354b09a13fa7f51f0ff9');
    const bytes=readFileSync(join(root,'frontend/scripts/nyay66-policy.json'),'utf8');
    expect(digest(bytes.slice(bytes.indexOf('  "exceptions": [')))).toBe('06490c18201cae63ca01be9744e546afc2d73dde9a4da0b2fb81ba047a9a1b3f');
    expect(current.exceptions).toHaveLength(310);
  });
  it('keeps all 112 S-35 rows DESIGN-GAP until separate product capture is implemented',()=>{
    const rows=continuationRows(data).filter(row=>row.screen==='S-35');
    expect(rows).toHaveLength(112);
    expect(rows.every(row=>row.verdict==='DESIGN-GAP'&&row.executed===false&&row.measured===false)).toBe(true);
  });
});
