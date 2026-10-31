import {s26Proposals,withoutS26ProposalsForTest} from './nyay66-s26-exceptions.test-fixture.mjs';
import {describe,it,expect} from 'vitest';
import {readFileSync,mkdtempSync,writeFileSync,rmSync,mkdirSync,symlinkSync} from 'node:fs';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import {execFileSync} from 'node:child_process';
import {fileURLToPath} from 'node:url';
import {PNG} from 'pngjs';
import {digest,approveException} from './nyay66-enforcement.mjs';
import {s25Proposals,s25ProposalHashes,historicalS25ExceptionsSha256,withoutS25ProposalsForTest} from './nyay66-s25-exceptions.test-fixture.mjs';
import {loadS25Source,S25_STATES,S25_VIEWPORTS,S25_PINS} from './nyay66-s25-reference.mjs';
import {verifyS25Archive,loadS25Cache} from './nyay66-s25-import.mjs';
import {continuationRows} from './nyay66-continuation.mjs';
const root=fileURLToPath(new URL('../../../',import.meta.url));
const {data}=await loadS25Source(root);
const policy=JSON.parse(readFileSync(join(root,'frontend/scripts/nyay66-policy.json')));
const fonts=JSON.parse(readFileSync(join(root,'frontend/test-baselines/nyay66',policy.cache,'manifest.json'))).fonts;
const sourceHead='a'.repeat(40),controlHead='b'.repeat(40);
const pngs=new Map(S25_VIEWPORTS.map(vp=>[vp.id,PNG.sync.write(new PNG({width:vp.width,height:vp.height}))]));
function archiveFixture(change=()=>{}){
  const dir=mkdtempSync(join(tmpdir(),'nyay-s25-import-test-'));
  const files=new Map(),rows=[];
  for(const state of S25_STATES)for(const vp of S25_VIEWPORTS){
    const bytes=pngs.get(vp.id),sha256=digest(bytes),file=`s25-${state}-${vp.id}-0.png`;
    files.set(file,bytes);rows.push({view:`s25-${state}`,viewport:vp.id,file,sha256,sampleHashes:Array(3).fill(sha256),dimensions:[vp.width,vp.height],
      surface:{controls:[],headings:[],masks:[],text:'synthetic',overflow:0,dimensions:[vp.width,vp.height]},fontStack:{viewport:'Public Sans',faces:[]},reviewerFrame:{borderRadius:'0px',x:0,y:0}});
  }
  const manifest={schema:1,purpose:'UNIMPORTED_REFERENCE_CALIBRATION',screen:'S-25',theme:'light',approval:data.designApproval,sourceArchiveSha256:data.archiveSha256,sourceSha256:data.htmlSha256,embeddedResources:data.inventory.embeddedResources,producerHead:sourceHead,controlHead,...S25_PINS,fonts,deferredStates:[],rows};
  const pins={purpose:'REFERENCE_GENERATION_ONLY_NOT_IMPORT_APPROVAL',sourceHead,reference:'s25-v32108',...S25_PINS,node:'v22.21.1',fonts};
  change(manifest,files,pins);
  files.set('manifest.json',Buffer.from(JSON.stringify(manifest)));
  files.set('runtime-pins.json',Buffer.from(JSON.stringify(pins)));
  files.set('SHA256SUMS',Buffer.from([...files].map(([name,bytes])=>`${digest(bytes)}  ${name}`).join('\n')+'\n'));
  for(const [name,bytes] of files)writeFileSync(join(dir,name),bytes);
  const path=join(dir,'calibration.zip');execFileSync('zip',['-q',path,...files.keys()],{cwd:dir});
  return {dir,path,expected:{archiveSha256:digest(readFileSync(path)),sourceHead,controlHead},files};
}
describe('S-25 archive import fails closed before writing',()=>{
  it('verifies the archive bytes, all 12 PNGs and the three-sample rehearsal inventory',async()=>{
    const f=archiveFixture();try{const got=await verifyS25Archive(f.path,f.expected,data,fonts);expect(got.manifest.rows).toHaveLength(12);expect(got.files.size).toBe(15);expect(got.archiveSha256).toBe(f.expected.archiveSha256);}finally{rmSync(f.dir,{recursive:true,force:true});}
  });
  it('rejects a tampered archive with its formerly valid digest',async()=>{
    const f=archiveFixture();try{writeFileSync(f.path,Buffer.concat([readFileSync(f.path),Buffer.from('tampered')]));await expect(verifyS25Archive(f.path,f.expected,data,fonts)).rejects.toThrow('S25_ARCHIVE_DIGEST_MISMATCH');}finally{rmSync(f.dir,{recursive:true,force:true});}
  });
  it('rejects a tampered PNG even with a recomputed archive and checksum list',async()=>{
    const f=archiveFixture((_m,files)=>{const [name,bytes]=files.entries().next().value;const altered=Buffer.from(bytes);altered[30]^=1;files.set(name,altered);});
    try{await expect(verifyS25Archive(f.path,f.expected,data,fonts)).rejects.toThrow('S25_REFERENCE_BYTES_MISMATCH');}finally{rmSync(f.dir,{recursive:true,force:true});}
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
    const f=archiveFixture(change);try{await expect(verifyS25Archive(f.path,f.expected,data,fonts)).rejects.toThrow();}finally{rmSync(f.dir,{recursive:true,force:true});}
  });
  it('requires an explicit safe cache binding without fabricating coverage',async()=>{
    expect(await loadS25Cache(root,undefined,data,fonts)).toBe(null);
    await expect(loadS25Cache(root,{cache:'../escape'},data,fonts)).rejects.toThrow('S25_INVALID_CACHE_BINDING');
  });
  it('rejects unexpected members and nonregular archive inputs',async()=>{
    const extra=archiveFixture((_m,files)=>files.set('unexpected.txt',Buffer.from('not an approved member')));
    try{await expect(verifyS25Archive(extra.path,extra.expected,data,fonts)).rejects.toThrow('S25_ARCHIVE_MEMBER_INVENTORY');}finally{rmSync(extra.dir,{recursive:true,force:true});}
    const f=archiveFixture();try{const link=join(f.dir,'linked.zip');symlinkSync(f.path,link);await expect(verifyS25Archive(link,f.expected,data,fonts)).rejects.toThrow('S25_NONREGULAR_INPUT');}finally{rmSync(f.dir,{recursive:true,force:true});}
  });
  it('revalidates cached bytes without promoting references to product measurements',async()=>{
    const f=archiveFixture();try{
      const cache='synthetic-s25',dir=join(f.dir,'frontend/test-baselines/nyay66',cache);mkdirSync(dir,{recursive:true});
      for(const [name,bytes] of f.files)writeFileSync(join(dir,name),bytes);
      const provenance=Buffer.from(JSON.stringify({...f.expected,runId:'1',artifactId:'2',referenceRows:12,manualRows:0}));
      writeFileSync(join(dir,'provenance.json'),provenance);
      const config={cache,manifestSha256:digest(f.files.get('manifest.json')),provenanceSha256:digest(provenance)};
      const got=await loadS25Cache(f.dir,config,data,fonts);
      expect(got.manifest.rows).toHaveLength(12);
      expect(got.manifest.rows.every(row=>row.measured===undefined&&row.executed===undefined&&row.verdict===undefined)).toBe(true);
      writeFileSync(join(dir,got.manifest.rows.at(-1).file),Buffer.from('tampered after import'));
      await expect(loadS25Cache(f.dir,config,data,fonts)).rejects.toThrow('S25_ARTIFACT_CHECKSUM_MISMATCH');
    }finally{rmSync(f.dir,{recursive:true,force:true});}
  });
  it.each(['current','s25-proposed','s26-proposed'])('pins the exact owner-dispatched cache and preserves the full historical policy (%s exceptions)',async(mode)=>{
    const got=await loadS25Cache(root,policy.s25,data,fonts);
    expect(got).not.toBe(null);expect(got.manifest.rows).toHaveLength(12);
    expect(got.provenance).toEqual({status:'CANDIDATE_PENDING_OWNER_INTEGRITY_APPROVAL',runId:'39558506587',artifactId:'12326656920',archiveSha256:'9472c2ef4a37772a41e74a80128e174b688184a5bf7d07af41f12c3895c88aab',sourceHead:'5fd6230526badfa03cf57d301b54edfb24208c76',controlHead:'5fd6230526badfa03cf57d301b54edfb24208c76',manifestSha256:'c2725e568cecf64f464cd687774ec331f3bbf563c9534d137ade298f0f40eb67',referenceRows:12,manualRows:0});
    expect(policy.s25).toEqual({cache:'s25-v32108-chromium-149.0.7827.55-39558506587',manifestSha256:'c2725e568cecf64f464cd687774ec331f3bbf563c9534d137ade298f0f40eb67',provenanceSha256:'16567edebd066feb41cbaf3b9754f5cc62f19d50e1fed2404aea7d884ab86675'});
    const before=JSON.parse(execFileSync('git',['show','5fd6230526badfa03cf57d301b54edfb24208c76:frontend/scripts/nyay66-policy.json'],{cwd:root}));
    // The additive S-26/S-27 caches are pinned by their exact-provenance import tests.
    const current=structuredClone(policy);delete current.s25;delete current.s26;delete current.s27;delete current.integrityApproval;delete before.integrityApproval;
    if(mode==='s25-proposed')current.exceptions=[...current.exceptions.filter(e=>e.screen!=='S-25'),...structuredClone(s25Proposals)];
    if(mode==='s26-proposed')current.exceptions=[...current.exceptions.filter(e=>e.screen!=='S-26'),...structuredClone(s26Proposals)];
    current.exceptions=withoutS25ProposalsForTest(withoutS26ProposalsForTest(current.exceptions));
    expect(current.exceptions).toHaveLength(148);
    expect(digest(JSON.stringify(current.exceptions))).toBe(historicalS25ExceptionsSha256);
    expect(JSON.stringify(current.exceptions)).toBe(JSON.stringify(before.exceptions));
    expect(current).toEqual(before);
    const rows=continuationRows(data).filter(r=>r.screen==='S-25');
    expect(rows).toHaveLength(12);
    expect(rows.every(r=>r.verdict==='DESIGN-GAP'&&r.executed===false&&r.measured===false)).toBe(true);
  });
  it('pins twelve proposals without granting runtime approval or changing the 148 historical records',()=>{
    const options={r2:true,s18:true,s19:true,s20:true,s21:true,s25:true};
    expect(s25Proposals.map(e=>approveException(e,null,options))).toEqual(s25ProposalHashes);
    for(const entry of s25Proposals)expect(approveException(entry,[],options)).toBe(false);
    const history=withoutS25ProposalsForTest(withoutS26ProposalsForTest(policy.exceptions));
    expect(history).toHaveLength(148);
    expect(digest(JSON.stringify(history))).toBe(historicalS25ExceptionsSha256);
    const candidate=[...history,...structuredClone(s25Proposals)],original=JSON.stringify(candidate);
    expect(JSON.stringify(withoutS25ProposalsForTest(withoutS26ProposalsForTest(candidate)))).toBe(JSON.stringify(history));
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
    ['approval PR',p=>{p[0].approvalPr=77;}],
    ['viewport',p=>{p[0].viewport='mobile360';}],
    ['screen',p=>{p[0].screen='S-26';}],
    ['theme',p=>{p[0].theme='dark';}],
    ['extra field',p=>{p[0].approved=true;}],
  ])('rejects changed S-25 %s without relaxing historical or provenance checks',(_,mutate)=>{
    const additions=structuredClone(s25Proposals);mutate(additions);
    expect(()=>withoutS25ProposalsForTest([...policy.exceptions.filter(e=>e.screen!=='S-25'),...additions])).toThrow();
  });
});
