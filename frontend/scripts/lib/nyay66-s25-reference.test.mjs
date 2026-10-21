import {describe,it,expect} from 'vitest';
import {fileURLToPath} from 'node:url';
import {PNG} from 'pngjs';
import {readFileSync} from 'node:fs';
import {digest} from './nyay66-enforcement.mjs';
import {S25_STATES,S25_VIEWPORTS,S25_PINS,loadS25Source,validateS25Pins,validateS25Manifest,verifyS25PNG,verifyS25ControlWorkflow} from './nyay66-s25-reference.mjs';
const root=fileURLToPath(new URL('../../../',import.meta.url));
const source=await loadS25Source(root);
const makeManifest=()=>({schema:1,purpose:'UNIMPORTED_REFERENCE_CALIBRATION',screen:'S-25',theme:'light',
  approval:'NYAY-90:16011',sourceArchiveSha256:source.data.archiveSha256,sourceSha256:source.data.htmlSha256,
  embeddedResources:source.data.inventory.embeddedResources,producerHead:'a'.repeat(40),controlHead:'b'.repeat(40),
  ...S25_PINS,fonts:{'public-sans.woff2':'c'.repeat(64)},
  deferredStates:[],rows:S25_STATES.flatMap(state=>S25_VIEWPORTS.map(vp=>({
    view:`s25-${state}`,viewport:vp.id,file:`s25-${state}-${vp.id}-0.png`,sha256:'d'.repeat(64),
    sampleHashes:Array(3).fill('d'.repeat(64)),dimensions:[vp.width,vp.height],
    surface:{controls:[],headings:[],text:'synthetic test only',masks:[],overflow:0,dimensions:[vp.width,vp.height]},
    fontStack:{viewport:'Public Sans',faces:[]},reviewerFrame:{borderRadius:'0px',x:0,y:0},
  })))});
describe('S-25 artifact-only reference calibration',()=>{
  it('binds the exact dispatch workflow bytes into the protected bundle and rejects workflow drift',()=>{
    const bytes=readFileSync(new URL('../../../.github/workflows/nyay66-calibration.yml',import.meta.url));
    expect(verifyS25ControlWorkflow(bytes)).toBe(true);
    expect(()=>verifyS25ControlWorkflow(Buffer.concat([bytes,Buffer.from('\n# drift')]))).toThrow('S25_CONTROL_WORKFLOW_MISMATCH');
  });
  it('hash-verifies the frozen canonical archive, HTML and embedded assets without running package helpers',async()=>{
    expect(digest(source.html)).toBe(source.data.htmlSha256);
    expect(source.data.archiveSha256).toBe('0476ec549b3776cc33af52692f71a4029404443f4f02f5b0485b02d5f38cf964');
    expect(S25_STATES).toEqual(['loading','list','empty','remove-pending','remove-failed','error']);
  });
  it('requires the exact hosted platform, Chromium, Playwright and font bytes',()=>{
    const fonts={'font.woff2':'a'.repeat(64)};
    expect(validateS25Pins({...S25_PINS,fonts},fonts)).toBe(true);
    for(const key of ['platform','chromium','playwright','fonts'])expect(()=>validateS25Pins({...S25_PINS,fonts,[key]:key==='fonts'?{}:'wrong'},fonts)).toThrow();
  });
  it('accepts all 6 approved design states at both viewports without promoting product coverage',()=>{
    expect(validateS25Manifest(makeManifest(),source.data)).toBe(true);
    expect(makeManifest().rows).toHaveLength(12);
    for(const change of [m=>m.rows.pop(),m=>m.rows.push(m.rows[0]),m=>m.rows[0].view='s25-invented',m=>m.deferredStates=['complete']]){
      const m=makeManifest();change(m);expect(()=>validateS25Manifest(m,source.data)).toThrow();
    }
  });
  it('fails closed for tampered source, non-identical samples, unsafe filenames, clipping and missing surface evidence',()=>{
    for(const change of [m=>m.sourceSha256='0'.repeat(64),m=>m.sourceArchiveSha256='0'.repeat(64),
      m=>m.embeddedResources={},m=>m.rows[0].sampleHashes[2]='0'.repeat(64),m=>m.rows[0].file='../escape.png',
      m=>m.rows[0].dimensions[0]=320,m=>m.rows[0].reviewerFrame.borderRadius='8px',m=>delete m.rows[0].surface,
      m=>m.rows[0].surface.dimensions=[1,1],m=>m.producerHead='main']){
      const m=makeManifest();change(m);expect(()=>validateS25Manifest(m,source.data)).toThrow();
    }
  });
  it('checks every PNG hash and decoded dimensions at use',()=>{
    const png=new PNG({width:390,height:844}),bytes=PNG.sync.write(png);
    const row={sha256:digest(bytes),dimensions:[390,844]};
    expect(verifyS25PNG(row,bytes)).toBe(true);
    const changed=Buffer.from(bytes);changed[30]^=1;
    expect(()=>verifyS25PNG(row,changed)).toThrow();
    expect(()=>verifyS25PNG({...row,dimensions:[1440,1024]},bytes)).toThrow();
  });
});
