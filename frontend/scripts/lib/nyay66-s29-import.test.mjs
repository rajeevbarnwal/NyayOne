import {describe,it,expect} from 'vitest';
import {readFileSync,mkdtempSync,writeFileSync,rmSync,mkdirSync,symlinkSync} from 'node:fs';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import {execFileSync} from 'node:child_process';
import {fileURLToPath} from 'node:url';
import {PNG} from 'pngjs';
import {digest} from './nyay66-enforcement.mjs';
import {continuationRows} from './nyay66-continuation.mjs';
import {loadS29Source,S29_STATES,S29_VIEWPORTS,S29_PINS} from './nyay66-s29-reference.mjs';
import {verifyS29Archive,loadS29Cache} from './nyay66-s29-import.mjs';
const root=fileURLToPath(new URL('../../../',import.meta.url));
const {data}=await loadS29Source(root);
const policy=JSON.parse(readFileSync(join(root,'frontend/scripts/nyay66-policy.json')));
const fonts=JSON.parse(readFileSync(join(root,'frontend/test-baselines/nyay66',policy.cache,'manifest.json'))).fonts;
const sourceHead='a'.repeat(40),controlHead='b'.repeat(40);
const pngs=new Map(S29_VIEWPORTS.map(vp=>[vp.id,PNG.sync.write(new PNG({width:vp.width,height:vp.height}))]));
function archiveFixture(change=()=>{}){
  const dir=mkdtempSync(join(tmpdir(),'nyay-s29-import-test-'));
  const files=new Map(),rows=[];
  for(const state of S29_STATES)for(const vp of S29_VIEWPORTS){
    const bytes=pngs.get(vp.id),sha256=digest(bytes),file=`s29-${state}-${vp.id}-0.png`;
    files.set(file,bytes);rows.push({view:`s29-${state}`,viewport:vp.id,file,sha256,sampleHashes:Array(3).fill(sha256),dimensions:[vp.width,vp.height],
      surface:{controls:[],headings:[],masks:[],text:'synthetic',overflow:0,dimensions:[vp.width,vp.height]},fontStack:{viewport:'Public Sans',faces:[]},reviewerFrame:{borderRadius:'0px',x:0,y:0}});
  }
  const manifest={schema:1,purpose:'UNIMPORTED_REFERENCE_CALIBRATION',screen:'S-29',theme:'light',approval:data.designApproval,sourceArchiveSha256:data.archiveSha256,sourceSha256:data.htmlSha256,embeddedResources:data.inventory.embeddedResources,producerHead:sourceHead,controlHead,...S29_PINS,fonts,deferredStates:[],rows};
  const pins={purpose:'REFERENCE_GENERATION_ONLY_NOT_IMPORT_APPROVAL',sourceHead,reference:'s29-v32108',...S29_PINS,node:'v22.21.1',fonts};
  change(manifest,files,pins);
  files.set('manifest.json',Buffer.from(JSON.stringify(manifest)));
  files.set('runtime-pins.json',Buffer.from(JSON.stringify(pins)));
  files.set('SHA256SUMS',Buffer.from([...files].map(([name,bytes])=>`${digest(bytes)}  ${name}`).join('\n')+'\n'));
  for(const [name,bytes] of files)writeFileSync(join(dir,name),bytes);
  const path=join(dir,'calibration.zip');execFileSync('zip',['-q',path,...files.keys()],{cwd:dir});
  return {dir,path,expected:{archiveSha256:digest(readFileSync(path)),sourceHead,controlHead},files};
}
describe('S-29 archive import fails closed before writing',()=>{
  it('verifies the archive bytes, all 12 PNGs and the three-sample rehearsal inventory',async()=>{
    const f=archiveFixture();try{const got=await verifyS29Archive(f.path,f.expected,data,fonts);expect(got.manifest.rows).toHaveLength(12);expect(got.files.size).toBe(15);expect(got.archiveSha256).toBe(f.expected.archiveSha256);}finally{rmSync(f.dir,{recursive:true,force:true});}
  });
  it('rejects a tampered archive with its formerly valid digest',async()=>{
    const f=archiveFixture();try{writeFileSync(f.path,Buffer.concat([readFileSync(f.path),Buffer.from('tampered')]));await expect(verifyS29Archive(f.path,f.expected,data,fonts)).rejects.toThrow('S29_ARCHIVE_DIGEST_MISMATCH');}finally{rmSync(f.dir,{recursive:true,force:true});}
  });
  it('rejects a tampered PNG even with a recomputed archive and checksum list',async()=>{
    const f=archiveFixture((_m,files)=>{const [name,bytes]=files.entries().next().value;const altered=Buffer.from(bytes);altered[30]^=1;files.set(name,altered);});
    try{await expect(verifyS29Archive(f.path,f.expected,data,fonts)).rejects.toThrow('S29_REFERENCE_BYTES_MISMATCH');}finally{rmSync(f.dir,{recursive:true,force:true});}
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
    const f=archiveFixture(change);try{await expect(verifyS29Archive(f.path,f.expected,data,fonts)).rejects.toThrow();}finally{rmSync(f.dir,{recursive:true,force:true});}
  });
  it('requires an explicit safe cache binding without fabricating coverage',async()=>{
    expect(await loadS29Cache(root,undefined,data,fonts)).toBe(null);
    await expect(loadS29Cache(root,{cache:'../escape'},data,fonts)).rejects.toThrow('S29_INVALID_CACHE_BINDING');
  });
  it('rejects unexpected members and nonregular archive inputs',async()=>{
    const extra=archiveFixture((_m,files)=>files.set('unexpected.txt',Buffer.from('not an approved member')));
    try{await expect(verifyS29Archive(extra.path,extra.expected,data,fonts)).rejects.toThrow('S29_ARCHIVE_MEMBER_INVENTORY');}finally{rmSync(extra.dir,{recursive:true,force:true});}
    const f=archiveFixture();try{const link=join(f.dir,'linked.zip');symlinkSync(f.path,link);await expect(verifyS29Archive(link,f.expected,data,fonts)).rejects.toThrow('S29_NONREGULAR_INPUT');}finally{rmSync(f.dir,{recursive:true,force:true});}
  });
  it('revalidates cached bytes without promoting references to product measurements',async()=>{
    const f=archiveFixture();try{
      const cache='synthetic-s29',dir=join(f.dir,'frontend/test-baselines/nyay66',cache);mkdirSync(dir,{recursive:true});
      for(const [name,bytes] of f.files)writeFileSync(join(dir,name),bytes);
      const provenance=Buffer.from(JSON.stringify({...f.expected,runId:'1',artifactId:'2',referenceRows:12,manualRows:0}));
      writeFileSync(join(dir,'provenance.json'),provenance);
      const config={cache,manifestSha256:digest(f.files.get('manifest.json')),provenanceSha256:digest(provenance)};
      const got=await loadS29Cache(f.dir,config,data,fonts);
      expect(got.manifest.rows).toHaveLength(12);
      expect(got.manifest.rows.every(row=>row.measured===undefined&&row.executed===undefined&&row.verdict===undefined)).toBe(true);
      writeFileSync(join(dir,got.manifest.rows.at(-1).file),Buffer.from('tampered after import'));
      await expect(loadS29Cache(f.dir,config,data,fonts)).rejects.toThrow('S29_ARTIFACT_CHECKSUM_MISMATCH');
    }finally{rmSync(f.dir,{recursive:true,force:true});}
  });
  it('pins all 12 S-29 references and exact owner-dispatch provenance without changing historical policy or promoting coverage',async()=>{
    const got=await loadS29Cache(root,policy.s29,data,fonts);
    expect(got).not.toBe(null);expect(got.manifest.rows).toHaveLength(12);
    expect(got.provenance).toEqual({"status":"CANDIDATE_PENDING_OWNER_INTEGRITY_APPROVAL","runId":"41352544483","artifactId":"13102545154","archiveSha256":"7a8dd47fde8c7202c139b83e420654edb85c318920ccc9f71888a624b04f242e","sourceHead":"e0f780f9d3e1443ae3803ceb37118d4e93f72d2f","controlHead":"e0f780f9d3e1443ae3803ceb37118d4e93f72d2f","manifestSha256":"207f0d96ed928beee038f02d193a5febe3e3eae58d5f0b80a5a6af540cd6334c","referenceRows":12,"manualRows":0});
    expect(policy.s29).toEqual({"cache":"s29-v32108-chromium-149.0.7827.55-41352544483","manifestSha256":"207f0d96ed928beee038f02d193a5febe3e3eae58d5f0b80a5a6af540cd6334c","provenanceSha256":"5de0808e4f1baa04f9696dd2613d04012ded898c4223118e096e1015a9969f17"});
    expect(got.manifest.rows.map(({view,viewport,sha256,dimensions})=>({view,viewport,sha256,dimensions}))).toEqual([{"view":"s29-loading","viewport":"mobile390","sha256":"104ac56feb0275b84e492ebf50b294168442ce5d3ad256b23787934c0689c26e","dimensions":[390,844]},{"view":"s29-loading","viewport":"desktop","sha256":"af6bff6cf8a113049f4c7e7db2eb734d1d15b65222b050debb455d822b4cfc6c","dimensions":[1440,1024]},{"view":"s29-complete","viewport":"mobile390","sha256":"93243657a0a1e0fe469061c185476b69f329948b0f716fcdac4818636b69c733","dimensions":[390,844]},{"view":"s29-complete","viewport":"desktop","sha256":"63dc49d4bb0af10d856bb6374fc16621c1b4428f087a523414fee494f4012277","dimensions":[1440,1024]},{"view":"s29-three","viewport":"mobile390","sha256":"563e3e6140da40bd291d1f4a14ffe216d14cbef1dacba0f9998bcc71a97234c6","dimensions":[390,844]},{"view":"s29-three","viewport":"desktop","sha256":"562a331c0407d56b31cec53d2a65ac2551f4a1922337d65514d7e48db90236de","dimensions":[1440,1024]},{"view":"s29-incomplete","viewport":"mobile390","sha256":"567f5c02c37f136cc809f67c9f233f9f76cbff6e4f44207633548d14676243e8","dimensions":[390,844]},{"view":"s29-incomplete","viewport":"desktop","sha256":"463249d20d4271d19649b8059c28721b99a581f83373ac4d7f4a54e4d12e7e8d","dimensions":[1440,1024]},{"view":"s29-too-few","viewport":"mobile390","sha256":"3820775d49afccf2c713ce015d7c315c6eb23f6f00eee1ee822b35df297d67aa","dimensions":[390,844]},{"view":"s29-too-few","viewport":"desktop","sha256":"edce877c2816c39cec83fe40a4da949ffca557bfe0d61eac918e33d9c232992d","dimensions":[1440,1024]},{"view":"s29-error","viewport":"mobile390","sha256":"e2e7192fcb0341cc39b12381eecb68680964e2dada900959c3cc9f1d443a8275","dimensions":[390,844]},{"view":"s29-error","viewport":"desktop","sha256":"7fdda1db6c8a96ed2934668acfdfeb39708ec85fa769b9e35d6d885c553b5249","dimensions":[1440,1024]}]);
    const beforeBytes=execFileSync('git',['show','e0f780f9d3e1443ae3803ceb37118d4e93f72d2f:frontend/scripts/nyay66-policy.json'],{cwd:root,encoding:'utf8'});
    const currentBytes=readFileSync(join(root,'frontend/scripts/nyay66-policy.json'),'utf8');
    const before=JSON.parse(beforeBytes),current=structuredClone(policy);
    expect(current.exceptions).toHaveLength(204);
    expect(currentBytes.slice(currentBytes.indexOf('  "exceptions": ['))).toBe(beforeBytes.slice(beforeBytes.indexOf('  "exceptions": [')));
    delete current.s29;delete current.integrityApproval;delete before.integrityApproval;
    expect(current).toEqual(before);
    const rows=continuationRows(data).filter(r=>r.screen==='S-29');
    expect(rows).toHaveLength(12);
    expect(rows.every(r=>r.verdict==='DESIGN-GAP'&&r.executed===false&&r.measured===false)).toBe(true);
  });
});
