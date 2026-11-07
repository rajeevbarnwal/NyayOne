import {continuationRows} from './nyay66-continuation.mjs';
import {describe,it,expect} from 'vitest';
import {readFileSync,mkdtempSync,writeFileSync,rmSync,mkdirSync,symlinkSync} from 'node:fs';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import {execFileSync} from 'node:child_process';
import {fileURLToPath} from 'node:url';
import {PNG} from 'pngjs';
import {digest} from './nyay66-enforcement.mjs';
import {loadS34Source,S34_STATES,S34_VIEWPORTS,S34_PINS} from './nyay66-s34-reference.mjs';
import {verifyS34Archive,loadS34Cache} from './nyay66-s34-import.mjs';
const root=fileURLToPath(new URL('../../../',import.meta.url));
const {data}=await loadS34Source(root);
const policy=JSON.parse(readFileSync(join(root,'frontend/scripts/nyay66-policy.json')));
const fonts=JSON.parse(readFileSync(join(root,'frontend/test-baselines/nyay66',policy.cache,'manifest.json'))).fonts;
const sourceHead='a'.repeat(40),controlHead='b'.repeat(40);
const pngs=new Map(S34_VIEWPORTS.map(vp=>[vp.id,PNG.sync.write(new PNG({width:vp.width,height:vp.height}))]));
function archiveFixture(change=()=>{}){
  const dir=mkdtempSync(join(tmpdir(),'nyay-s34-import-test-'));
  const files=new Map(),rows=[];
  for(const state of S34_STATES)for(const vp of S34_VIEWPORTS){
    const bytes=pngs.get(vp.id),sha256=digest(bytes),file=`s34-${state}-${vp.id}-0.png`;
    files.set(file,bytes);rows.push({view:`s34-${state}`,viewport:vp.id,file,sha256,sampleHashes:Array(3).fill(sha256),dimensions:[vp.width,vp.height],
      surface:{controls:[],headings:[],masks:[],text:'synthetic',overflow:0,dimensions:[vp.width,vp.height]},fontStack:{viewport:'Public Sans',faces:[]},reviewerFrame:{borderRadius:'0px',x:0,y:0}});
  }
  const manifest={schema:1,purpose:'UNIMPORTED_REFERENCE_CALIBRATION',screen:'S-34',theme:'light',approval:data.designApproval,sourceArchiveSha256:data.archiveSha256,sourceSha256:data.htmlSha256,embeddedResources:data.inventory.embeddedResources,producerHead:sourceHead,controlHead,...S34_PINS,fonts,deferredStates:[],rows};
  const pins={purpose:'REFERENCE_GENERATION_ONLY_NOT_IMPORT_APPROVAL',sourceHead,reference:'s34-v32108',...S34_PINS,node:'v22.21.1',fonts};
  change(manifest,files,pins);
  files.set('manifest.json',Buffer.from(JSON.stringify(manifest)));
  files.set('runtime-pins.json',Buffer.from(JSON.stringify(pins)));
  files.set('SHA256SUMS',Buffer.from([...files].map(([name,bytes])=>`${digest(bytes)}  ${name}`).join('\n')+'\n'));
  for(const [name,bytes] of files)writeFileSync(join(dir,name),bytes);
  const path=join(dir,'calibration.zip');execFileSync('zip',['-q',path,...files.keys()],{cwd:dir});
  return {dir,path,expected:{archiveSha256:digest(readFileSync(path)),sourceHead,controlHead},files};
}
describe('S-34 archive import fails closed before writing',()=>{
  it('verifies the archive bytes, all 12 PNGs and the three-sample rehearsal inventory',async()=>{
    const f=archiveFixture();try{const got=await verifyS34Archive(f.path,f.expected,data,fonts);expect(got.manifest.rows).toHaveLength(12);expect(got.files.size).toBe(15);expect(got.archiveSha256).toBe(f.expected.archiveSha256);}finally{rmSync(f.dir,{recursive:true,force:true});}
  });
  it('rejects a tampered archive with its formerly valid digest',async()=>{
    const f=archiveFixture();try{writeFileSync(f.path,Buffer.concat([readFileSync(f.path),Buffer.from('tampered')]));await expect(verifyS34Archive(f.path,f.expected,data,fonts)).rejects.toThrow('S34_ARCHIVE_DIGEST_MISMATCH');}finally{rmSync(f.dir,{recursive:true,force:true});}
  });
  it('rejects a tampered PNG even with a recomputed archive and checksum list',async()=>{
    const f=archiveFixture((_m,files)=>{const [name,bytes]=files.entries().next().value;const altered=Buffer.from(bytes);altered[30]^=1;files.set(name,altered);});
    try{await expect(verifyS34Archive(f.path,f.expected,data,fonts)).rejects.toThrow('S34_REFERENCE_BYTES_MISMATCH');}finally{rmSync(f.dir,{recursive:true,force:true});}
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
    const f=archiveFixture(change);try{await expect(verifyS34Archive(f.path,f.expected,data,fonts)).rejects.toThrow();}finally{rmSync(f.dir,{recursive:true,force:true});}
  });
  it('requires an explicit safe cache binding without fabricating coverage',async()=>{
    expect(await loadS34Cache(root,undefined,data,fonts)).toBe(null);
    await expect(loadS34Cache(root,{cache:'../escape'},data,fonts)).rejects.toThrow('S34_INVALID_CACHE_BINDING');
  });
  it('rejects unexpected members and nonregular archive inputs',async()=>{
    const extra=archiveFixture((_m,files)=>files.set('unexpected.txt',Buffer.from('not an approved member')));
    try{await expect(verifyS34Archive(extra.path,extra.expected,data,fonts)).rejects.toThrow('S34_ARCHIVE_MEMBER_INVENTORY');}finally{rmSync(extra.dir,{recursive:true,force:true});}
    const f=archiveFixture();try{const link=join(f.dir,'linked.zip');symlinkSync(f.path,link);await expect(verifyS34Archive(link,f.expected,data,fonts)).rejects.toThrow('S34_NONREGULAR_INPUT');}finally{rmSync(f.dir,{recursive:true,force:true});}
  });
  it('revalidates cached bytes without promoting references to product measurements',async()=>{
    const f=archiveFixture();try{
      const cache='synthetic-s34',dir=join(f.dir,'frontend/test-baselines/nyay66',cache);mkdirSync(dir,{recursive:true});
      for(const [name,bytes] of f.files)writeFileSync(join(dir,name),bytes);
      const provenance=Buffer.from(JSON.stringify({...f.expected,runId:'1',artifactId:'2',referenceRows:12,manualRows:0}));
      writeFileSync(join(dir,'provenance.json'),provenance);
      const config={cache,manifestSha256:digest(f.files.get('manifest.json')),provenanceSha256:digest(provenance)};
      const got=await loadS34Cache(f.dir,config,data,fonts);
      expect(got.manifest.rows).toHaveLength(12);
      expect(got.manifest.rows.every(row=>row.measured===undefined&&row.executed===undefined&&row.verdict===undefined)).toBe(true);
      writeFileSync(join(dir,got.manifest.rows.at(-1).file),Buffer.from('tampered after import'));
      await expect(loadS34Cache(f.dir,config,data,fonts)).rejects.toThrow('S34_ARTIFACT_CHECKSUM_MISMATCH');
    }finally{rmSync(f.dir,{recursive:true,force:true});}
  });
  it('loads the bound reference cache in the hosted gate without claiming product capture',()=>{
    const live=readFileSync(join(root,'frontend/scripts/nyay66-live.mjs'),'utf8');
    expect(live).toContain("import {loadS34Cache} from './lib/nyay66-s34-import.mjs'");
    expect(live).toContain('await loadS34Cache(root,config.s34,continuation,manifest.fonts)');
    expect(live).toContain('report.s34Reference={cache:config.s34.cache,manifestSha256:config.s34.manifestSha256,provenance:s34.provenance}');
    expect(live).not.toContain('captureS34Rows');
  });
  it('pins all 12 references and exact owner-dispatch provenance while preserving every historical setting and exception byte',async()=>{
    const got=await loadS34Cache(root,policy.s34,data,fonts);
    expect(got).not.toBe(null);expect(got.manifest.rows).toHaveLength(12);
    expect(got.provenance).toEqual({"status":"CANDIDATE_PENDING_OWNER_INTEGRITY_APPROVAL","runId":"42357105281","artifactId":"13568271090","archiveSha256":"e363bb81f5616e6d5ecaf7f2bd3491f42d6dd0da1537d64aeb947f52c0b8744e","sourceHead":"14837461f0ca1d95ba99202ced85a3f18375fa58","controlHead":"14837461f0ca1d95ba99202ced85a3f18375fa58","manifestSha256":"1b6bbcd0df03a06e95be5e42b7163ea792f9d5a814a500695d2dfe008e032965","referenceRows":12,"manualRows":0});
    expect(policy.s34).toEqual({"cache":"s34-v32108-chromium-149.0.7827.55-42357105281","manifestSha256":"1b6bbcd0df03a06e95be5e42b7163ea792f9d5a814a500695d2dfe008e032965","provenanceSha256":"a9b8658c83b4fa57bcd7c5f6fa4a1c93ee5626e2aba9fc55257cb40bc4550902"});
    expect(got.manifest.rows.map(({view,viewport,sha256,dimensions,sampleHashes})=>({view,viewport,sha256,dimensions,sampleHashes}))).toEqual([{"view":"s34-loading","viewport":"mobile390","sha256":"d41aa94f8cbf1f388ff4aac415f872a44517333f323a7712e80c62673698454e","dimensions":[390,844],"sampleHashes":["d41aa94f8cbf1f388ff4aac415f872a44517333f323a7712e80c62673698454e","d41aa94f8cbf1f388ff4aac415f872a44517333f323a7712e80c62673698454e","d41aa94f8cbf1f388ff4aac415f872a44517333f323a7712e80c62673698454e"]},{"view":"s34-loading","viewport":"desktop","sha256":"9c8460f36d119c6cf22ea56e95d1c71d889800bcdc8745ee7aea1df2008af779","dimensions":[1440,1024],"sampleHashes":["9c8460f36d119c6cf22ea56e95d1c71d889800bcdc8745ee7aea1df2008af779","9c8460f36d119c6cf22ea56e95d1c71d889800bcdc8745ee7aea1df2008af779","9c8460f36d119c6cf22ea56e95d1c71d889800bcdc8745ee7aea1df2008af779"]},{"view":"s34-confirmed","viewport":"mobile390","sha256":"2350cb80a521dc43a4675b2d7b92aa8f8f01b6a952ada7fa8022a217ab48609c","dimensions":[390,844],"sampleHashes":["2350cb80a521dc43a4675b2d7b92aa8f8f01b6a952ada7fa8022a217ab48609c","2350cb80a521dc43a4675b2d7b92aa8f8f01b6a952ada7fa8022a217ab48609c","2350cb80a521dc43a4675b2d7b92aa8f8f01b6a952ada7fa8022a217ab48609c"]},{"view":"s34-confirmed","viewport":"desktop","sha256":"202dd508b9153ae73e889d0b44484af7cde517320de24cb53322f95388c912fb","dimensions":[1440,1024],"sampleHashes":["202dd508b9153ae73e889d0b44484af7cde517320de24cb53322f95388c912fb","202dd508b9153ae73e889d0b44484af7cde517320de24cb53322f95388c912fb","202dd508b9153ae73e889d0b44484af7cde517320de24cb53322f95388c912fb"]},{"view":"s34-pending-provider","viewport":"mobile390","sha256":"c5dace809bb50b814ce3c8a364a94a6df85cb2a6ae3cec6675cee4cbfb1b3ae6","dimensions":[390,844],"sampleHashes":["c5dace809bb50b814ce3c8a364a94a6df85cb2a6ae3cec6675cee4cbfb1b3ae6","c5dace809bb50b814ce3c8a364a94a6df85cb2a6ae3cec6675cee4cbfb1b3ae6","c5dace809bb50b814ce3c8a364a94a6df85cb2a6ae3cec6675cee4cbfb1b3ae6"]},{"view":"s34-pending-provider","viewport":"desktop","sha256":"edce77b080e9d3cbe972860cfa36d18aa048b58f206d441c6c42e31ce7747180","dimensions":[1440,1024],"sampleHashes":["edce77b080e9d3cbe972860cfa36d18aa048b58f206d441c6c42e31ce7747180","edce77b080e9d3cbe972860cfa36d18aa048b58f206d441c6c42e31ce7747180","edce77b080e9d3cbe972860cfa36d18aa048b58f206d441c6c42e31ce7747180"]},{"view":"s34-cancelled","viewport":"mobile390","sha256":"4c32e55677c796b47ed8dde1ccd00aeb08dadbe1a39b046d9cc9b1b56c586662","dimensions":[390,844],"sampleHashes":["4c32e55677c796b47ed8dde1ccd00aeb08dadbe1a39b046d9cc9b1b56c586662","4c32e55677c796b47ed8dde1ccd00aeb08dadbe1a39b046d9cc9b1b56c586662","4c32e55677c796b47ed8dde1ccd00aeb08dadbe1a39b046d9cc9b1b56c586662"]},{"view":"s34-cancelled","viewport":"desktop","sha256":"151eefc9357b07a3a1aa59a018bd5c62ebb95dcb27a89aa065a8d7537fe84416","dimensions":[1440,1024],"sampleHashes":["151eefc9357b07a3a1aa59a018bd5c62ebb95dcb27a89aa065a8d7537fe84416","151eefc9357b07a3a1aa59a018bd5c62ebb95dcb27a89aa065a8d7537fe84416","151eefc9357b07a3a1aa59a018bd5c62ebb95dcb27a89aa065a8d7537fe84416"]},{"view":"s34-error","viewport":"mobile390","sha256":"5f44287847eb5e10455040ad0db8b751e6254c28b7e182f6cdda66c7b71fb8e4","dimensions":[390,844],"sampleHashes":["5f44287847eb5e10455040ad0db8b751e6254c28b7e182f6cdda66c7b71fb8e4","5f44287847eb5e10455040ad0db8b751e6254c28b7e182f6cdda66c7b71fb8e4","5f44287847eb5e10455040ad0db8b751e6254c28b7e182f6cdda66c7b71fb8e4"]},{"view":"s34-error","viewport":"desktop","sha256":"a635af7948da4316737ddb17b0608701c3455b05cb8a42733ff32cc1ec20f149","dimensions":[1440,1024],"sampleHashes":["a635af7948da4316737ddb17b0608701c3455b05cb8a42733ff32cc1ec20f149","a635af7948da4316737ddb17b0608701c3455b05cb8a42733ff32cc1ec20f149","a635af7948da4316737ddb17b0608701c3455b05cb8a42733ff32cc1ec20f149"]},{"view":"s34-missing","viewport":"mobile390","sha256":"997b9248193c9b077a9e4774126b1b5e3c9753913e31d7f249760c1b7fbfca7b","dimensions":[390,844],"sampleHashes":["997b9248193c9b077a9e4774126b1b5e3c9753913e31d7f249760c1b7fbfca7b","997b9248193c9b077a9e4774126b1b5e3c9753913e31d7f249760c1b7fbfca7b","997b9248193c9b077a9e4774126b1b5e3c9753913e31d7f249760c1b7fbfca7b"]},{"view":"s34-missing","viewport":"desktop","sha256":"6dd16ccd3b002db90b8266cb568934b2ee034af05fc1aeae515acb8c9663d73a","dimensions":[1440,1024],"sampleHashes":["6dd16ccd3b002db90b8266cb568934b2ee034af05fc1aeae515acb8c9663d73a","6dd16ccd3b002db90b8266cb568934b2ee034af05fc1aeae515acb8c9663d73a","6dd16ccd3b002db90b8266cb568934b2ee034af05fc1aeae515acb8c9663d73a"]}]);
    const beforeBytes=execFileSync('git',['show','14837461f0ca1d95ba99202ced85a3f18375fa58:frontend/scripts/nyay66-policy.json'],{cwd:root,encoding:'utf8'});
    const currentBytes=readFileSync(join(root,'frontend/scripts/nyay66-policy.json'),'utf8');
    const before=JSON.parse(beforeBytes),current=structuredClone(policy);
    expect(current.exceptions).toHaveLength(298);
    expect(currentBytes.slice(currentBytes.indexOf('  "exceptions": ['))).toBe(beforeBytes.slice(beforeBytes.indexOf('  "exceptions": [')));
    delete current.s34;delete current.integrityApproval;delete before.integrityApproval;
    expect(current).toEqual(before);
    const rows=continuationRows(data).filter(r=>r.screen==='S-34');
    expect(rows).toHaveLength(12);
    expect(rows.every(r=>r.verdict==='DESIGN-GAP'&&r.executed===false&&r.measured===false)).toBe(true);
  });
});
