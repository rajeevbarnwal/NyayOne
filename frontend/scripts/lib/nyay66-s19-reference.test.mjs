import {describe,it,expect} from 'vitest';
import {fileURLToPath} from 'node:url';
import {PNG} from 'pngjs';
import {readFileSync} from 'node:fs';
import {digest} from './nyay66-enforcement.mjs';
import {S19_STATES,S19_VIEWPORTS,S19_PINS,loadS19Source,validateS19Pins,validateS19Manifest,verifyS19PNG,verifyS19ControlWorkflow} from './nyay66-s19-reference.mjs';
const root=fileURLToPath(new URL('../../../',import.meta.url));
const source=await loadS19Source(root);
const makeManifest=()=>({schema:1,purpose:'UNIMPORTED_REFERENCE_CALIBRATION',screen:'S-19',theme:'light',
  approval:'NYAY-90:16011',sourceArchiveSha256:source.data.archiveSha256,sourceSha256:source.data.htmlSha256,
  embeddedResources:source.data.inventory.embeddedResources,producerHead:'a'.repeat(40),controlHead:'b'.repeat(40),
  ...S19_PINS,fonts:{'public-sans.woff2':'c'.repeat(64)},
  deferredStates:[],rows:S19_STATES.flatMap(state=>S19_VIEWPORTS.map(vp=>({
    view:`s19-${state}`,viewport:vp.id,file:`s19-${state}-${vp.id}-0.png`,sha256:'d'.repeat(64),
    sampleHashes:Array(3).fill('d'.repeat(64)),dimensions:[vp.width,vp.height],
    surface:{controls:[],headings:[],text:'synthetic test only',masks:[],overflow:0,dimensions:[vp.width,vp.height]},
    fontStack:{viewport:'Public Sans',faces:[]},reviewerFrame:{borderRadius:'0px',x:0,y:0},
  })))});
describe('S-19 artifact-only reference calibration',()=>{
  it('binds the exact dispatch workflow bytes into the protected bundle and rejects workflow drift',()=>{
    const bytes=readFileSync(new URL('../../../.github/workflows/nyay66-calibration.yml',import.meta.url));
    expect(verifyS19ControlWorkflow(bytes)).toBe(true);
    expect(()=>verifyS19ControlWorkflow(Buffer.concat([bytes,Buffer.from('\n# drift')]))).toThrow('S19_CONTROL_WORKFLOW_MISMATCH');
  });
  it('hash-verifies the frozen canonical archive, HTML and embedded assets without running package helpers',async()=>{
    expect(digest(source.html)).toBe(source.data.htmlSha256);
    expect(source.data.archiveSha256).toBe('0476ec549b3776cc33af52692f71a4029404443f4f02f5b0485b02d5f38cf964');
    expect(S19_STATES).toEqual(['loading','loaded','saving','saved','conflict','network','export-accepted','export-processing','export-complete','export-failed','request-not-found','delete-confirm','delete-invalid','delete-reauth','delete-reauth-rejected','delete-reauth-required','delete-conflict','delete-accepted','session','option-manual','export-check-failed','delete-mobile-invalid','delete-start-failed','delete-rate-limited','delete-code-expired','delete-typed']);
    expect(S19_STATES).toContain('option-manual'); // capture only; not shipped-mode approval
  });
  it('requires the exact hosted platform, Chromium, Playwright and font bytes',()=>{
    const fonts={'font.woff2':'a'.repeat(64)};
    expect(validateS19Pins({...S19_PINS,fonts},fonts)).toBe(true);
    for(const key of ['platform','chromium','playwright','fonts'])expect(()=>validateS19Pins({...S19_PINS,fonts,[key]:key==='fonts'?{}:'wrong'},fonts)).toThrow();
  });
  it('accepts all 26 approved design states at both viewports without promoting product coverage',()=>{
    expect(validateS19Manifest(makeManifest(),source.data)).toBe(true);
    expect(makeManifest().rows).toHaveLength(52);
    for(const change of [m=>m.rows.pop(),m=>m.rows.push(m.rows[0]),m=>m.rows[0].view='s19-invented',m=>m.deferredStates=['option-manual']]){
      const m=makeManifest();change(m);expect(()=>validateS19Manifest(m,source.data)).toThrow();
    }
  });
  it('fails closed for tampered source, non-identical samples, unsafe filenames, clipping and missing surface evidence',()=>{
    for(const change of [m=>m.sourceSha256='0'.repeat(64),m=>m.sourceArchiveSha256='0'.repeat(64),
      m=>m.embeddedResources={},m=>m.rows[0].sampleHashes[2]='0'.repeat(64),m=>m.rows[0].file='../escape.png',
      m=>m.rows[0].dimensions[0]=320,m=>m.rows[0].reviewerFrame.borderRadius='8px',m=>delete m.rows[0].surface,
      m=>m.rows[0].surface.dimensions=[1,1],m=>m.producerHead='main']){
      const m=makeManifest();change(m);expect(()=>validateS19Manifest(m,source.data)).toThrow();
    }
  });
  it('checks every PNG hash and decoded dimensions at use',()=>{
    const png=new PNG({width:390,height:844}),bytes=PNG.sync.write(png);
    const row={sha256:digest(bytes),dimensions:[390,844]};
    expect(verifyS19PNG(row,bytes)).toBe(true);
    const changed=Buffer.from(bytes);changed[30]^=1;
    expect(()=>verifyS19PNG(row,changed)).toThrow();
    expect(()=>verifyS19PNG({...row,dimensions:[1440,1024]},bytes)).toThrow();
  });
});
