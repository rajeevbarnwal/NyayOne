import { describe, it, expect } from 'vitest';
import { PNG } from 'pngjs';
import { enforcePins, pixelMetrics, compareStructure, approveException, validateProgression } from './nyay66-enforcement.mjs';
const surface = () => ({ text: 'Hello', controls: [{ role: 'button', name: 'Continue', disabled: false, box: {x:1,y:1,width:2,height:2} }], headings: [], masks: [], overflow: 0 });
const pins = { chromium: '149.0.7827.55', platform: 'linux-x64', sourceSha256: 'a', fonts: {a:'b'}, playwright:'1.61.1' };
describe('NYAY-66 activated enforcement', () => {
  it('requires exact browser, platform, source and font pins', () => {
    expect(enforcePins(pins,pins)).toBe(true);
    for(const field of Object.keys(pins)) expect(()=>enforcePins(pins,{...pins,[field]:'changed'})).toThrow();
  });
  it('refuses missing version evidence', () => expect(()=>enforcePins(pins,{})).toThrow());
  it('compares unchanged pixels exactly', () => {
    const a=new PNG({width:10,height:10}); a.data.fill(255);
    expect(pixelMetrics(a,a,[]).pass).toBe(true);
  });
  it('blocks a solid changed component', () => {
    const a=new PNG({width:10,height:10}),b=new PNG({width:10,height:10});b.data.fill(255);
    expect(pixelMetrics(a,b,[]).pass).toBe(false);
  });
  it('never resizes a reference to fit a changed application', () => expect(()=>pixelMetrics(new PNG({width:2,height:2}),new PNG({width:3,height:2}),[])).toThrow());
  it('excludes bounded dynamic pixels while retaining other pixels', () => {
    const a=new PNG({width:10,height:10}),b=new PNG({width:10,height:10});a.data.fill(255);b.data.fill(255);b.data[0]=0;
    expect(pixelMetrics(a,b,[{x:0,y:0,width:1,height:1}]).pass).toBe(true);
  });
  it('rejects viewport-wide masking', () => expect(()=>pixelMetrics(new PNG({width:10,height:10}),new PNG({width:10,height:10}),[{x:0,y:0,width:10,height:10}])).toThrow());
  it('rejects non-finite masks', () => expect(()=>pixelMetrics(new PNG({width:10,height:10}),new PNG({width:10,height:10}),[{x:NaN,y:0,width:1,height:1}])).toThrow());
  it('passes identical structure', () => expect(compareStructure(surface(),surface(),0)).toEqual([]));
  for(const field of ['name','role','disabled']) it(`rejects changed control ${field}`,()=>{
    const b=surface();b.controls[0][field]='changed';expect(compareStructure(surface(),b,0)).toContain('controls');
  });
  it('checks text outside pixel masks',()=>{const b=surface();b.text='Different';expect(compareStructure(surface(),b,0)).toContain('text');});
  it('blocks absent controls',()=>{const b=surface();b.controls=[];expect(compareStructure(surface(),b,0)).toContain('controls');});
  it('bounds geometry to one pixel inclusive',()=>{const b=surface();b.controls[0].box.x+=1;expect(compareStructure(surface(),b,0)).toEqual([]);b.controls[0].box.x+=0.1;expect(compareStructure(surface(),b,0)).toContain('geometry');});
  it('requires both dynamic clock regions even if pixels match',()=>expect(compareStructure(surface(),surface(),2)).toContain('dynamic-regions'));
  it('rejects malformed clock text and nonzero overflow',()=>{const b=surface();b.masks=[{kind:'otp-clock',text:'secret'}];b.overflow=1;expect(compareStructure(surface(),b,0)).toContain('dynamic-regions');expect(compareStructure(surface(),b,0)).toContain('overflow');});
  it('accepts only an exact owner PR-comment approval',()=>{
    const entry={screen:'S-03',viewport:'mobile390',theme:'light',referenceSha256:'a'.repeat(64),liveSha256:'b'.repeat(64),checks:['text']};
    expect(approveException(entry,[])).toBe(false);
    const hash=approveException(entry,null);
    expect(approveException(entry,[{id:1,user:{login:'rajeevbarnwal'},body:`NYAY66-EXCEPTION ${hash}`}])).toBe(true);
    expect(approveException(entry,[{id:1,user:{login:'someone'},body:`NYAY66-EXCEPTION ${hash}`}])).toBe(false);
    expect(approveException({...entry,liveSha256:'c'.repeat(64)},[{id:1,user:{login:'rajeevbarnwal'},body:`NYAY66-EXCEPTION ${hash}`}])).toBe(false);
  });
  it('rejects removal and unknown enforced screens',()=>{
    expect(()=>validateProgression(['S-03'],[])).toThrow();
    expect(()=>validateProgression([],['unknown'])).toThrow();
    expect(validateProgression(['S-03'],['S-03','S-04'])).toBe(true);
  });
});
