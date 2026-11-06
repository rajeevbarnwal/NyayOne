import {describe,it,expect} from 'vitest';
import {fileURLToPath} from 'node:url';
import {PNG} from 'pngjs';
import {readFileSync} from 'node:fs';
import {digest} from './nyay66-enforcement.mjs';
import {S33_STATES,S33_VIEWPORTS,S33_PINS,loadS33Source,validateS33Pins,validateS33Manifest,verifyS33PNG,verifyS33ControlWorkflow} from './nyay66-s33-reference.mjs';
const root=fileURLToPath(new URL('../../../',import.meta.url));
const source=await loadS33Source(root);
const makeManifest=()=>({schema:1,purpose:'UNIMPORTED_REFERENCE_CALIBRATION',screen:'S-33',theme:'light',
  approval:'NYAY-90:16011',sourceArchiveSha256:source.data.archiveSha256,sourceSha256:source.data.htmlSha256,
  embeddedResources:source.data.inventory.embeddedResources,producerHead:'a'.repeat(40),controlHead:'b'.repeat(40),
  ...S33_PINS,fonts:{'public-sans.woff2':'c'.repeat(64)},
  deferredStates:[],rows:S33_STATES.flatMap(state=>S33_VIEWPORTS.map(vp=>({
    view:`s33-${state}`,viewport:vp.id,file:`s33-${state}-${vp.id}-0.png`,sha256:'d'.repeat(64),
    sampleHashes:Array(3).fill('d'.repeat(64)),dimensions:[vp.width,vp.height],
    surface:{controls:[],headings:[],text:'synthetic test only',masks:[],overflow:0,dimensions:[vp.width,vp.height]},
    fontStack:{viewport:'Public Sans',faces:[]},reviewerFrame:{borderRadius:'0px',x:0,y:0},
  })))});
describe('S-33 artifact-only reference calibration',()=>{
  it('binds the exact dispatch workflow bytes into the protected bundle and rejects workflow drift',()=>{
    const bytes=readFileSync(new URL('../../../.github/workflows/nyay66-calibration.yml',import.meta.url));
    expect(verifyS33ControlWorkflow(bytes)).toBe(true);
    expect(()=>verifyS33ControlWorkflow(Buffer.concat([bytes,Buffer.from('\n# drift')]))).toThrow('S33_CONTROL_WORKFLOW_MISMATCH');
  });
  it('hash-verifies the frozen canonical archive, HTML and embedded assets without running package helpers',async()=>{
    expect(digest(source.html)).toBe(source.data.htmlSha256);
    expect(source.data.archiveSha256).toBe('0476ec549b3776cc33af52692f71a4029404443f4f02f5b0485b02d5f38cf964');
    expect(S33_STATES).toEqual(['hold-creating','hold-active','slot-conflict','hold-expired','order-pending','payment-failed','creating-session','payment-unverified','confirmed','rate-limited','network','session','hold-60min','hold-other-mentor']);
  });
  it('requires the exact hosted platform, Chromium, Playwright and font bytes',()=>{
    const fonts={'font.woff2':'a'.repeat(64)};
    expect(validateS33Pins({...S33_PINS,fonts},fonts)).toBe(true);
    for(const key of ['platform','chromium','playwright','fonts'])expect(()=>validateS33Pins({...S33_PINS,fonts,[key]:key==='fonts'?{}:'wrong'},fonts)).toThrow();
  });
  it('accepts all 14 approved design states at both viewports without promoting product coverage',()=>{
    expect(validateS33Manifest(makeManifest(),source.data)).toBe(true);
    expect(makeManifest().rows).toHaveLength(28);
    for(const change of [m=>m.rows.pop(),m=>m.rows.push(m.rows[0]),m=>m.rows[0].view='s33-invented',m=>m.deferredStates=['complete']]){
      const m=makeManifest();change(m);expect(()=>validateS33Manifest(m,source.data)).toThrow();
    }
  });
  it('fails closed for tampered source, non-identical samples, unsafe filenames, clipping and missing surface evidence',()=>{
    for(const change of [m=>m.sourceSha256='0'.repeat(64),m=>m.sourceArchiveSha256='0'.repeat(64),
      m=>m.embeddedResources={},m=>m.rows[0].sampleHashes[2]='0'.repeat(64),m=>m.rows[0].file='../escape.png',
      m=>m.rows[0].dimensions[0]=320,m=>m.rows[0].reviewerFrame.borderRadius='8px',m=>delete m.rows[0].surface,
      m=>m.rows[0].surface.dimensions=[1,1],m=>m.producerHead='main']){
      const m=makeManifest();change(m);expect(()=>validateS33Manifest(m,source.data)).toThrow();
    }
  });
  it('checks every PNG hash and decoded dimensions at use',()=>{
    const png=new PNG({width:390,height:844}),bytes=PNG.sync.write(png);
    const row={sha256:digest(bytes),dimensions:[390,844]};
    expect(verifyS33PNG(row,bytes)).toBe(true);
    const changed=Buffer.from(bytes);changed[30]^=1;
    expect(()=>verifyS33PNG(row,changed)).toThrow();
    expect(()=>verifyS33PNG({...row,dimensions:[1440,1024]},bytes)).toThrow();
  });
});
