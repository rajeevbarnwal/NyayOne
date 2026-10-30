import {describe,it,expect} from 'vitest';
import {fileURLToPath} from 'node:url';
import {PNG} from 'pngjs';
import {readFileSync} from 'node:fs';
import {digest} from './nyay66-enforcement.mjs';
import {S26_STATES,S26_VIEWPORTS,S26_PINS,loadS26Source,validateS26Pins,validateS26Manifest,verifyS26PNG,verifyS26ControlWorkflow} from './nyay66-s26-reference.mjs';
const root=fileURLToPath(new URL('../../../',import.meta.url));
const source=await loadS26Source(root);
const makeManifest=()=>({schema:1,purpose:'UNIMPORTED_REFERENCE_CALIBRATION',screen:'S-26',theme:'light',
  approval:'NYAY-90:16011',sourceArchiveSha256:source.data.archiveSha256,sourceSha256:source.data.htmlSha256,
  embeddedResources:source.data.inventory.embeddedResources,producerHead:'a'.repeat(40),controlHead:'b'.repeat(40),
  ...S26_PINS,fonts:{'public-sans.woff2':'c'.repeat(64)},
  deferredStates:[],rows:S26_STATES.flatMap(state=>S26_VIEWPORTS.map(vp=>({
    view:`s26-${state}`,viewport:vp.id,file:`s26-${state}-${vp.id}-0.png`,sha256:'d'.repeat(64),
    sampleHashes:Array(3).fill('d'.repeat(64)),dimensions:[vp.width,vp.height],
    surface:{controls:[],headings:[],text:'synthetic test only',masks:[],overflow:0,dimensions:[vp.width,vp.height]},
    fontStack:{viewport:'Public Sans',faces:[]},reviewerFrame:{borderRadius:'0px',x:0,y:0},
  })))});
describe('S-26 artifact-only reference calibration',()=>{
  it('binds the exact dispatch workflow bytes into the protected bundle and rejects workflow drift',()=>{
    const bytes=readFileSync(new URL('../../../.github/workflows/nyay66-calibration.yml',import.meta.url));
    expect(verifyS26ControlWorkflow(bytes)).toBe(true);
    expect(()=>verifyS26ControlWorkflow(Buffer.concat([bytes,Buffer.from('\n# drift')]))).toThrow('S26_CONTROL_WORKFLOW_MISMATCH');
  });
  it('hash-verifies the frozen canonical archive, HTML and embedded assets without running package helpers',async()=>{
    expect(digest(source.html)).toBe(source.data.htmlSha256);
    expect(source.data.archiveSha256).toBe('0476ec549b3776cc33af52692f71a4029404443f4f02f5b0485b02d5f38cf964');
    expect(S26_STATES).toEqual(['empty','loading','error','nonempty']);
  });
  it('requires the exact hosted platform, Chromium, Playwright and font bytes',()=>{
    const fonts={'font.woff2':'a'.repeat(64)};
    expect(validateS26Pins({...S26_PINS,fonts},fonts)).toBe(true);
    for(const key of ['platform','chromium','playwright','fonts'])expect(()=>validateS26Pins({...S26_PINS,fonts,[key]:key==='fonts'?{}:'wrong'},fonts)).toThrow();
  });
  it('accepts all 4 approved design states at both viewports without promoting product coverage',()=>{
    expect(validateS26Manifest(makeManifest(),source.data)).toBe(true);
    expect(makeManifest().rows).toHaveLength(8);
    for(const change of [m=>m.rows.pop(),m=>m.rows.push(m.rows[0]),m=>m.rows[0].view='s26-invented',m=>m.deferredStates=['complete']]){
      const m=makeManifest();change(m);expect(()=>validateS26Manifest(m,source.data)).toThrow();
    }
  });
  it('fails closed for tampered source, non-identical samples, unsafe filenames, clipping and missing surface evidence',()=>{
    for(const change of [m=>m.sourceSha256='0'.repeat(64),m=>m.sourceArchiveSha256='0'.repeat(64),
      m=>m.embeddedResources={},m=>m.rows[0].sampleHashes[2]='0'.repeat(64),m=>m.rows[0].file='../escape.png',
      m=>m.rows[0].dimensions[0]=320,m=>m.rows[0].reviewerFrame.borderRadius='8px',m=>delete m.rows[0].surface,
      m=>m.rows[0].surface.dimensions=[1,1],m=>m.producerHead='main']){
      const m=makeManifest();change(m);expect(()=>validateS26Manifest(m,source.data)).toThrow();
    }
  });
  it('checks every PNG hash and decoded dimensions at use',()=>{
    const png=new PNG({width:390,height:844}),bytes=PNG.sync.write(png);
    const row={sha256:digest(bytes),dimensions:[390,844]};
    expect(verifyS26PNG(row,bytes)).toBe(true);
    const changed=Buffer.from(bytes);changed[30]^=1;
    expect(()=>verifyS26PNG(row,changed)).toThrow();
    expect(()=>verifyS26PNG({...row,dimensions:[1440,1024]},bytes)).toThrow();
  });
});
