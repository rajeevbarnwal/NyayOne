import {describe,it,expect} from 'vitest';
import {PNG} from 'pngjs';
import {digest} from './nyay66-enforcement.mjs';
import * as r2 from './nyay66-r2.mjs';

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
