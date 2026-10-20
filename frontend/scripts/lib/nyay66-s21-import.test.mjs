import {describe,it,expect} from 'vitest';
import {readFileSync,mkdtempSync,writeFileSync,rmSync,mkdirSync,symlinkSync} from 'node:fs';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import {execFileSync} from 'node:child_process';
import {fileURLToPath} from 'node:url';
import {PNG} from 'pngjs';
import {digest,approveException} from './nyay66-enforcement.mjs';
import {s21Proposals,s21ProposalHashes,historicalExceptionsSha256,withoutS21ProposalsForTest} from './nyay66-s21-exceptions.test-fixture.mjs';
import {loadS21Source,S21_STATES,S21_VIEWPORTS,S21_PINS} from './nyay66-s21-reference.mjs';
import {verifyS21Archive,loadS21Cache} from './nyay66-s21-import.mjs';
const root=fileURLToPath(new URL('../../../',import.meta.url));
const {data}=await loadS21Source(root);
const policy=JSON.parse(readFileSync(join(root,'frontend/scripts/nyay66-policy.json')));
const fonts=JSON.parse(readFileSync(join(root,'frontend/test-baselines/nyay66',policy.cache,'manifest.json'))).fonts;
const sourceHead='a'.repeat(40),controlHead='b'.repeat(40);
const pngs=new Map(S21_VIEWPORTS.map(vp=>[vp.id,PNG.sync.write(new PNG({width:vp.width,height:vp.height}))]));
function archiveFixture(change=()=>{}){
  const dir=mkdtempSync(join(tmpdir(),'nyay-s21-import-test-'));
  const files=new Map(),rows=[];
  for(const state of S21_STATES)for(const vp of S21_VIEWPORTS){
    const bytes=pngs.get(vp.id),sha256=digest(bytes),file=`s21-${state}-${vp.id}-0.png`;
    files.set(file,bytes);rows.push({view:`s21-${state}`,viewport:vp.id,file,sha256,sampleHashes:Array(3).fill(sha256),dimensions:[vp.width,vp.height],
      surface:{controls:[],headings:[],masks:[],text:'synthetic',overflow:0,dimensions:[vp.width,vp.height]},fontStack:{viewport:'Public Sans',faces:[]},reviewerFrame:{borderRadius:'0px',x:0,y:0}});
  }
  const manifest={schema:1,purpose:'UNIMPORTED_REFERENCE_CALIBRATION',screen:'S-21',theme:'light',approval:data.designApproval,sourceArchiveSha256:data.archiveSha256,sourceSha256:data.htmlSha256,embeddedResources:data.inventory.embeddedResources,producerHead:sourceHead,controlHead,...S21_PINS,fonts,deferredStates:[],rows};
  change(manifest,files);
  files.set('manifest.json',Buffer.from(JSON.stringify(manifest)));
  files.set('runtime-pins.json',Buffer.from(JSON.stringify({purpose:'REFERENCE_GENERATION_ONLY_NOT_IMPORT_APPROVAL',sourceHead,reference:'s21-v32108',...S21_PINS,node:'v22.21.1',fonts})));
  files.set('SHA256SUMS',Buffer.from([...files].map(([name,bytes])=>`${digest(bytes)}  ${name}`).join('\n')+'\n'));
  for(const [name,bytes] of files)writeFileSync(join(dir,name),bytes);
  const path=join(dir,'calibration.zip');execFileSync('zip',['-q',path,...files.keys()],{cwd:dir});
  return {dir,path,expected:{archiveSha256:digest(readFileSync(path)),sourceHead,controlHead},files};
}
describe('S-21 archive import fails closed before writing',()=>{
  it('verifies the archive bytes, all PNGs and the exact 16-row rehearsal inventory',async()=>{
    const f=archiveFixture();try{const got=await verifyS21Archive(f.path,f.expected,data,fonts);expect(got.manifest.rows).toHaveLength(16);expect(got.files.size).toBe(19);expect(got.archiveSha256).toBe(f.expected.archiveSha256);}finally{rmSync(f.dir,{recursive:true,force:true});}
  });
  it('rejects a tampered archive with the formerly valid caller digest',async()=>{
    const f=archiveFixture();try{writeFileSync(f.path,Buffer.concat([readFileSync(f.path),Buffer.from('tampered')]));await expect(verifyS21Archive(f.path,f.expected,data,fonts)).rejects.toThrow('S21_ARCHIVE_DIGEST_MISMATCH');}finally{rmSync(f.dir,{recursive:true,force:true});}
  });
  it('rejects a tampered PNG even with recomputed archive and checksum-list digests',async()=>{
    const f=archiveFixture((_m,files)=>{const [name,bytes]=files.entries().next().value;const altered=Buffer.from(bytes);altered[30]^=1;files.set(name,altered);});
    try{await expect(verifyS21Archive(f.path,f.expected,data,fonts)).rejects.toThrow('S21_REFERENCE_BYTES_MISMATCH');}finally{rmSync(f.dir,{recursive:true,force:true});}
  });
  it('rejects missing states, unstable samples, changed heads and runtime/font pins',async()=>{
    for(const change of [m=>m.rows.pop(),m=>m.rows[0].sampleHashes[1]='c'.repeat(64),m=>m.producerHead='c'.repeat(40),m=>m.controlHead='c'.repeat(40),m=>m.chromium='wrong',m=>m.fonts={}]){
      const f=archiveFixture(change);try{await expect(verifyS21Archive(f.path,f.expected,data,fonts)).rejects.toThrow();}finally{rmSync(f.dir,{recursive:true,force:true});}
    }
  });
  it('requires an explicit safe cache binding without fabricating coverage',async()=>{
    expect(await loadS21Cache(root,undefined,data,fonts)).toBe(null);
    await expect(loadS21Cache(root,{cache:'../escape'},data,fonts)).rejects.toThrow('S21_INVALID_CACHE_BINDING');
  });
  it('rejects unexpected members and nonregular archive inputs',async()=>{
    const extra=archiveFixture((_m,files)=>files.set('unexpected.txt',Buffer.from('not an approved member')));
    try{await expect(verifyS21Archive(extra.path,extra.expected,data,fonts)).rejects.toThrow('S21_ARCHIVE_MEMBER_INVENTORY');}finally{rmSync(extra.dir,{recursive:true,force:true});}
    const f=archiveFixture();try{const link=join(f.dir,'linked.zip');symlinkSync(f.path,link);await expect(verifyS21Archive(link,f.expected,data,fonts)).rejects.toThrow('S21_NONREGULAR_INPUT');}finally{rmSync(f.dir,{recursive:true,force:true});}
  });
  it('revalidates cached bytes without promoting references to product measurements',async()=>{
    const f=archiveFixture();try{
      const cache='synthetic-s21',dir=join(f.dir,'frontend/test-baselines/nyay66',cache);mkdirSync(dir,{recursive:true});
      for(const [name,bytes] of f.files)writeFileSync(join(dir,name),bytes);
      const provenance=Buffer.from(JSON.stringify({...f.expected,runId:'1',artifactId:'2',referenceRows:16,manualRows:0}));
      writeFileSync(join(dir,'provenance.json'),provenance);
      const config={cache,manifestSha256:digest(f.files.get('manifest.json')),provenanceSha256:digest(provenance)};
      const got=await loadS21Cache(f.dir,config,data,fonts);
      expect(got.manifest.rows).toHaveLength(16);
      expect(got.manifest.rows.every(row=>row.measured===undefined&&row.executed===undefined&&row.verdict===undefined)).toBe(true);
      writeFileSync(join(dir,got.manifest.rows.at(-1).file),Buffer.from('tampered after import'));
      await expect(loadS21Cache(f.dir,config,data,fonts)).rejects.toThrow('S21_ARTIFACT_CHECKSUM_MISMATCH');
    }finally{rmSync(f.dir,{recursive:true,force:true});}
  });
  it.each(['current','proposed'])('pins the owner-dispatched cache and preserves every historical policy byte (%s exceptions)',async(mode)=>{
    const got=await loadS21Cache(root,policy.s21,data,fonts);
    expect(got).not.toBe(null);expect(got.manifest.rows).toHaveLength(16);
    expect(got.provenance).toEqual({status:'CANDIDATE_PENDING_OWNER_INTEGRITY_APPROVAL',runId:'39279617257',artifactId:'12200177444',archiveSha256:'4ae108aab062f6b3e7ded73b85e4efdcb95962fe3ca3ce54400107ce95e9de60',sourceHead:'0d381b7aee9d438712549cb62275582951536438',controlHead:'0d381b7aee9d438712549cb62275582951536438',manifestSha256:'1e13cfa4d7ab2561890e229ead844e4768240d593f3dae4ab545d1069ce0e9d0',referenceRows:16,manualRows:0});
    expect(policy.s21).toEqual({cache:'s21-v32108-chromium-149.0.7827.55-39279617257',manifestSha256:'1e13cfa4d7ab2561890e229ead844e4768240d593f3dae4ab545d1069ce0e9d0',provenanceSha256:'dae65825f99fda6e069ee91e2bb12a2981e0e961ca42d05633ca14cca96de92d'});
    const before=JSON.parse(execFileSync('git',['show','0d381b7aee9d438712549cb62275582951536438:frontend/scripts/nyay66-policy.json'],{cwd:root}));
    const current=structuredClone(policy);delete current.s21;delete current.integrityApproval;delete before.integrityApproval;
    if(mode==='proposed')current.exceptions=[...current.exceptions.filter(e=>e.screen!=='S-21'),...structuredClone(s21Proposals)];
    current.exceptions=withoutS21ProposalsForTest(current.exceptions);
    expect(current.exceptions).toHaveLength(132);
    expect(digest(JSON.stringify(current.exceptions))).toBe(historicalExceptionsSha256);
    expect(JSON.stringify(current.exceptions)).toBe(JSON.stringify(before.exceptions));
    expect(current).toEqual(before);
  });
  it('pins all 16 proposed hashes without substituting test fixtures for owner read-back',()=>{
    const options={r2:true,s18:true,s19:true,s20:true,s21:true};
    expect(s21Proposals.map(e=>approveException(e,null,options))).toEqual(s21ProposalHashes);
    for(const entry of s21Proposals)expect(approveException(entry,[],options)).toBe(false);
    const before=JSON.stringify(policy.exceptions.filter(e=>e.screen!=='S-21'));
    const candidate=[...JSON.parse(before),...structuredClone(s21Proposals)];
    const original=JSON.stringify(candidate);
    expect(JSON.stringify(withoutS21ProposalsForTest(candidate))).toBe(before);
    expect(JSON.stringify(candidate)).toBe(original);
  });
  it.each([
    ['missing row',p=>p.pop()],
    ['duplicate row',p=>{p[1]=structuredClone(p[0]);}],
    ['extra row',p=>p.push(structuredClone(p[0]))],
    ['reference bytes',p=>{p[0].referenceSha256='0'.repeat(64);}],
    ['live bytes',p=>{p[0].liveSha256='0'.repeat(64);}],
    ['disclosure',p=>{p[0].reason+=' widened';}],
    ['check scope',p=>{p[0].checks=['pixels'];}],
    ['approval PR',p=>{p[0].approvalPr=73;}],
    ['viewport',p=>{p[0].viewport='mobile360';}],
    ['screen',p=>{p[0].screen='S-22';}],
    ['theme',p=>{p[0].theme='dark';}],
    ['extra field',p=>{p[0].approved=true;}],
  ])('rejects changed S-21 %s without relaxing any historical comparison',(_,mutate)=>{
    const additions=structuredClone(s21Proposals);mutate(additions);
    expect(()=>withoutS21ProposalsForTest([...policy.exceptions.filter(e=>e.screen!=='S-21'),...additions])).toThrow();
  });
});
