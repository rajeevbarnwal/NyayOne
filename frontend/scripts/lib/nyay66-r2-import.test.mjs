import {describe,it,expect,beforeAll,afterAll} from 'vitest';
import {mkdtemp,readFile,writeFile,mkdir,readdir,rm,symlink,stat} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import {resolve,dirname} from 'node:path';
import {fileURLToPath} from 'node:url';
import {spawnSync} from 'node:child_process';
import {PNG} from 'pngjs';
import {digest} from './nyay66-enforcement.mjs';
import * as r2 from './nyay66-r2.mjs';

describe('R2 importer verifies ZIP bytes before staging',()=>{
  const root=resolve(dirname(fileURLToPath(import.meta.url)),'../../..');
  const input=resolve(root,'frontend/test-baselines/nyay66/chromium-149.0.7827.55-r2');
  let scratch,archive,hash;
  beforeAll(async()=>{
    scratch=await mkdtemp(resolve(tmpdir(),'nyay50-archive-test-'));
    archive=resolve(scratch,'reference.zip');
    const files=(await readdir(input)).filter(n=>n!=='provenance.json').sort();
    const zipped=spawnSync('zip',['-q','-0',archive,...files],{cwd:input,encoding:'utf8'});
    expect(zipped.status,zipped.stderr).toBe(0);hash=digest(await readFile(archive));
  });
  afterAll(async()=>{if(scratch)await rm(scratch,{recursive:true,force:true});});
  const invoke=(output,expected=hash,path=archive)=>spawnSync(process.execPath,[
    resolve(root,'frontend/scripts/nyay66-r2-import.mjs'),input,output,
    '643fb83b7f8316eeca01a020521b97f55856ba08','34719114626','10305658341',expected,
    ...(path===null?[]:[path]),
  ],{cwd:root,encoding:'utf8'});
  it('accepts an intact ZIP and records its computed digest',async()=>{
    const output=resolve(scratch,'valid');const result=invoke(output);
    expect(result.status,result.stderr).toBe(0);
    expect(JSON.parse(await readFile(resolve(output,'provenance.json'))).archiveSha256).toBe(digest(await readFile(archive)));
  });
  for(const kind of ['tampered ZIP','unrelated expected digest','missing argument','missing archive','directory','symlink']){
    it(`refuses ${kind} without creating output`,async()=>{
      const output=resolve(scratch,kind.replaceAll(' ','-')+'-output');let path=archive,expected=hash;
      if(kind==='tampered ZIP'){const bytes=Buffer.from(await readFile(archive));bytes[bytes.length-1]^=1;path=resolve(scratch,'tampered.zip');await writeFile(path,bytes);}
      if(kind==='unrelated expected digest')expected='0'.repeat(64);
      if(kind==='missing argument')path=null;
      if(kind==='missing archive')path=resolve(scratch,'absent.zip');
      if(kind==='directory'){path=resolve(scratch,'directory');await mkdir(path);}
      if(kind==='symlink'){path=resolve(scratch,'link.zip');await symlink(archive,path);}
      const result=invoke(output,expected,path);
      expect(result.status,result.stderr).not.toBe(0);
      await expect(stat(output)).rejects.toMatchObject({code:'ENOENT'});
    });
  }
});

function fixture(){
  const files=new Map(),fonts={'fixture.woff2':'a'.repeat(64)},head='b'.repeat(40);
  const pins={reference:'r2',sourceHead:head,chromium:'149.0.7827.55',playwright:'1.61.1',platform:'linux-x64',node:'v22.21.1',fonts};
  const images=new Map(r2.R2_VIEWPORTS.map(v=>[v.id,PNG.sync.write(new PNG({width:v.width,height:v.height,fill:true}))]));
  const manifest={schema:1,sourceSha256:r2.R2_SOURCE_SHA256,approval:'NYAY-50:15422',theme:'light',producerHead:head,...pins,rows:r2.R2_STATES.flatMap(s=>r2.R2_VIEWPORTS.map(v=>{
    const bytes=images.get(v.id),sha256=digest(bytes),file=`${s.id}-${v.id}-0.png`;files.set(file,bytes);
    return {view:s.id,viewport:v.id,file,sha256,sampleHashes:[sha256,sha256,sha256],dimensions:[v.width,v.height],surface:{controls:[],headings:[],masks:[],text:'synthetic',dimensions:[v.width,v.height]}};
  }))};
  const serialize=()=>{files.set('manifest.json',Buffer.from(JSON.stringify(manifest)));files.set('runtime-pins.json',Buffer.from(JSON.stringify(pins)));return [...files].map(([name,b])=>`${digest(b)}  ${name}`).join('\n')+'\n';};
  return {files,manifest,pins,head,fonts,serialize};
}
describe('R2 calibration import verification',()=>{
  it('verifies all 42 PNGs and both metadata files before staging',async()=>{
    const f=fixture();expect((await r2.verifyR2Calibration(f.serialize(),async n=>f.files.get(n),f.head,f.fonts)).files.size).toBe(44);
  });
  for(const [name,mutate] of [
    ['source head',f=>f.manifest.producerHead='c'.repeat(40)],
    ['runtime head',f=>f.pins.sourceHead='c'.repeat(40)],
    ['browser pin',f=>f.pins.chromium='other'],
    ['font pin',f=>f.pins.fonts={}],
    ['capture variance',f=>f.manifest.rows[0].sampleHashes[2]='c'.repeat(64)],
    ['missing sample',f=>f.manifest.rows[0].sampleHashes.pop()],
    ['missing state',f=>f.manifest.rows.pop()],
    ['unlisted state hash mismatch',f=>f.files.set(f.manifest.rows.at(-1).file,Buffer.from('tampered'))],
  ])it(`refuses ${name} even with rehashed checksum metadata`,async()=>{
    const f=fixture();mutate(f);await expect(r2.verifyR2Calibration(f.serialize(),async n=>f.files.get(n),f.head,f.fonts)).rejects.toThrow();
  });
  for(const mutation of ['duplicate','traversal','missing','tamper'])it(`refuses ${mutation} checksum input`,async()=>{
    const f=fixture();let sums=f.serialize();
    if(mutation==='duplicate')sums+=sums.split('\n')[0]+'\n';
    if(mutation==='traversal')sums+='a'.repeat(64)+'  ../outside\n';
    if(mutation==='missing')sums=sums.split('\n').slice(1).join('\n');
    if(mutation==='tamper')f.files.set('runtime-pins.json',Buffer.from('{}'));
    await expect(r2.verifyR2Calibration(sums,async n=>f.files.get(n),f.head,f.fonts)).rejects.toThrow();
  });
});
