import { describe, it, expect, vi } from 'vitest';
import { inspectSurface } from './nyay66-dom.mjs';
import { PNG } from 'pngjs';
import { readFileSync } from 'node:fs';
import { spawnSync } from 'node:child_process';
import * as enforcement from './nyay66-enforcement.mjs';
import { enforcePins, pixelMetrics, compareStructure, approveException, validateProgression } from './nyay66-enforcement.mjs';
const surface = () => ({ text: 'Hello', controls: [{ role: 'button', name: 'Continue', disabled: false, box: {x:1,y:1,width:2,height:2} }], headings: [], masks: [], overflow: 0 });
const pins = { chromium: '149.0.7827.55', platform: 'linux-x64', sourceSha256: 'a', fonts: {a:'b'}, playwright:'1.61.1' };
describe('NYAY-66 activated enforcement', () => {
  it('checks rendered heading text without hidden responsive alternatives', () => {
    const rect={x:0,y:0,top:0,bottom:30,width:200,height:30};
    const hidden={nodeType:1,css:{display:'none',visibility:'visible'},childNodes:[{nodeType:3,textContent:'Hidden desktop heading'}]};
    const heading={childNodes:[hidden,{nodeType:3,textContent:'Visible heading'}],innerText:'Visible heading',textContent:'Hidden desktop headingVisible heading',getBoundingClientRect:()=>rect};
    const root={innerText:'Visible heading',scrollWidth:200,clientWidth:200,getBoundingClientRect:()=>rect,querySelectorAll:selector=>selector.startsWith('h1')?[heading]:[]};
    vi.stubGlobal('document',{body:root});
    vi.stubGlobal('getComputedStyle',element=>element.css||({visibility:'visible',display:'block'}));
    try{expect(inspectSurface().headings[0].text).toBe('Visible heading');}
    finally{vi.unstubAllGlobals();}
  });
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
    const entry={screen:'S-03',viewport:'mobile390',theme:'light',referenceSha256:'a'.repeat(64),liveSha256:'b'.repeat(64),checks:['text'],approvalPr:37};
    expect(approveException(entry,[])).toBe(false);
    const hash=approveException(entry,null);
    expect(approveException(entry,[{id:1,approvalPr:37,user:{login:'rajeevbarnwal'},body:`NYAY66-EXCEPTION ${hash}`}])).toBe(true);
    expect(approveException(entry,[{id:1,approvalPr:37,user:{login:'someone'},body:`NYAY66-EXCEPTION ${hash}`}])).toBe(false);
    expect(approveException({...entry,liveSha256:'c'.repeat(64)},[{id:1,approvalPr:37,user:{login:'rajeevbarnwal'},body:`NYAY66-EXCEPTION ${hash}`}])).toBe(false);
  });
  it('rejects removal and unknown enforced screens',()=>{
    expect(()=>validateProgression(['S-03'],[])).toThrow();
    expect(()=>validateProgression([],['unknown'])).toThrow();
    expect(validateProgression(['S-03'],['S-03','S-04'])).toBe(true);
  });
});

describe('NYAY-84 PR5 light enforcement promotion', () => {
  const options = { r2: true };
  const screens = [...Array.from({length:17}, (_,i)=>`S-${String(i+1).padStart(2,'0')}`),'S-07-popup'];
  const policy = () => ({ enforced: screens, exceptions: [] });
  const rows = () => enforcement.lightRowInventory(options).map(identity => ({
    ...identity, executed: true, verdict: 'PARITY', errors: [],
    referenceSha256: 'a'.repeat(64), liveSha256: 'b'.repeat(64),
    metrics: {pass:true}, regions: [{pass:true}], structure: [], accessibility: [],
    ...(identity.state === 'S-01-resolved' ? {
      evidenceKind:'component-visual', coverageApproval:'NYAY-77:15493',
      liveRouteBehavior:{executed:true,from:'/s-01',to:'/s-07',syntheticServer:true,artificialDelay:false,navigationFrozen:false},
    } : {}),
  }));
  const finish = (values=rows(), config=policy(), comments=[]) => enforcement.finalizeEnforcement(values,config,comments,options);
  const exception = () => ({screen:'S-07',viewport:'mobile390',theme:'light',referenceSha256:'a'.repeat(64),liveSha256:'b'.repeat(64),checks:['pixels'],approvalPr:57});
  const comment = entry => ({id:123,approvalPr:entry.approvalPr,user:{login:'rajeevbarnwal'},body:`NYAY66-EXCEPTION ${approveException(entry,null,options)}`});

  it('promotes all 18 covered light screens including S-07 dashboard and popup', () => {
    const config=JSON.parse(readFileSync(new URL('../nyay66-policy.json',import.meta.url),'utf8'));
    expect(config.enforced).toEqual(screens);
    expect(config.tolerances).toEqual({pixelRatio:0.001,mean:0.25,geometry:1});
  });
  it('requires exactly 74 light state/viewport rows and retains component evidence', () => {
    const result=finish();
    expect(result.expectedLightRows).toBe(74);
    expect(result.failures).toEqual([]);
    expect(result.blocking).toBe(false);
    expect(result.rows.filter(row=>['S-07','S-07-popup'].includes(row.screen))).toHaveLength(4);
    expect(result.rows.filter(row=>row.evidenceKind==='component-visual')).toHaveLength(3);
  });
  it('matches the existing S-06 producer state IDs without rewriting historical reports',()=>{
    expect(enforcement.lightRowInventory(options).filter(r=>r.screen==='S-06').map(r=>r.state)).toEqual(
      ['mobile390','mobile360','desktop'].flatMap(()=>['entry','invalidnum','submitting','challenge','wrong','expired','locked','neterr','success'].map(s=>`s06-${s}`)));
  });
  it('fails for EACH missing state/viewport, including either S-07 surface', () => {
    const all=rows();
    for(let index=0;index<all.length;index++){
      const result=finish(all.filter((_,i)=>i!==index));
      expect(result.blocking,JSON.stringify(all[index])).toBe(true);
      expect(result.failures.some(f=>f.startsWith('MISSING_LIGHT_ROW:'))).toBe(true);
    }
  });
  it('rejects duplicate and unexpected light rows rather than substituting them for coverage', () => {
    expect(finish([...rows(),rows()[0]]).failures).toContain('DUPLICATE_LIGHT_ROW:S-01:S-01-checking:mobile390');
    expect(finish([...rows(),{...rows()[0],state:'invented'}]).blocking).toBe(true);
  });
  for(const verdict of ['DESIGN-GAP','NOT-YET-MEASURED','CAPTURE-FAILED','PARITY-INVENTED']){
    it(`cannot count unexecuted ${verdict} as passing coverage`,()=>{
      const all=rows();all[0]={...all[0],executed:false,verdict,blocking:false};
      expect(finish(all).blocking).toBe(true);
    });
  }
  it('keeps the 36 deferred dark gaps explicitly unexecuted and non-blocking', () => {
    const dark=screens.flatMap(screen=>['mobile390','desktop'].map(viewport=>({screen,viewport,theme:'dark',executed:false,verdict:'DESIGN-GAP'})));
    const result=finish([...rows(),...dark]);
    expect(result.rows).toHaveLength(110);expect(result.blocking).toBe(false);
    expect(result.rows.filter(row=>row.theme==='dark').every(row=>row.executed===false&&row.verdict==='DESIGN-GAP'&&row.blocking===false)).toBe(true);
  });
  it('blocks a real pixel-comparator regression despite a stale PARITY label', () => {
    const a=new PNG({width:10,height:10}),b=new PNG({width:10,height:10});b.data.fill(255);
    const all=rows();all[0].metrics=pixelMetrics(a,b,[]);
    expect(finish(all).rows[0]).toMatchObject({verdict:'NONCONFORMANT',blocking:true,remaining:['pixels']});
  });
  for(const check of ['text','controls','headings','geometry','dynamic-regions','overflow']){
    it(`blocks a measured ${check} regression`,()=>{
      const all=rows();all[0].structure=[check];expect(finish(all).blocking).toBe(true);
    });
  }
  for(const mutation of [r=>{r.regions=[{pass:false}];},r=>{r.accessibility=[{impact:'serious'}];},r=>{r.accessibility=[{impact:'critical'}];},r=>{r.errors=['PAGE_ERROR'];},r=>{delete r.metrics;},r=>{delete r.referenceSha256;}]){
    it('fails closed for crops, a11y, capture errors and incomplete measured proof',()=>{
      const all=rows();mutation(all[0]);expect(finish(all).blocking).toBe(true);
    });
  }
  for(const mutation of [r=>{delete r.liveRouteBehavior;},r=>{r.liveRouteBehavior.executed=false;},r=>{r.liveRouteBehavior.navigationFrozen=true;},r=>{r.liveRouteBehavior.artificialDelay=true;},r=>{r.evidenceKind='live-route';},r=>{r.coverageApproval='unapproved';}]){
    it('requires the approved S-01 component PLUS immediate live redirect proof',()=>{
      const all=rows();mutation(all.find(r=>r.state==='S-01-resolved'));expect(finish(all).blocking).toBe(true);
    });
  }
  it('retains a valid exact-image owner exception without changing its hash',()=>{
    const entry=exception(),all=rows();all.find(r=>r.screen==='S-07'&&r.viewport==='mobile390').metrics.pass=false;
    const result=finish(all,{...policy(),exceptions:[entry]},[comment(entry)]);
    expect(result.blocking).toBe(false);
    expect(result.rows.find(r=>r.screen==='S-07'&&r.viewport==='mobile390').verdict).toBe('PARITY-WITH-DISCLOSED-DELTA');
    all.find(r=>r.screen==='S-07'&&r.viewport==='mobile390').liveSha256='c'.repeat(64);
    expect(finish(all,{...policy(),exceptions:[entry]},[comment(entry)]).blocking).toBe(true);
  });
  for(const change of [()=>[],c=>[{...c,user:{login:'not-owner'}}],c=>[{...c,approvalPr:999}],c=>[{...c,body:'approved generally'}],c=>[{...c,body:`${c.body} extra`}],c=>[{...c,body:'NYAY66-EXCEPTION '+'0'.repeat(64)}]]){
    it('rejects missing, non-owner, wrong-PR, edited or stale exception approval',()=>{
      const entry=exception();expect(()=>finish(rows(),{...policy(),exceptions:[entry]},change(comment(entry)))).toThrow('OWNER_EXCEPTION_APPROVAL_MISSING');
    });
  }
  for(const check of ['accessibility','overflow','dynamic-regions']){
    it(`never permits an owner comment to waive ${check}`,()=>{
      const entry={...exception(),checks:[check]};
      expect(()=>finish(rows(),{...policy(),exceptions:[entry]},[comment(entry)])).toThrow('OWNER_EXCEPTION_APPROVAL_MISSING');
    });
  }
  it('keeps capture failures blocking even for screens not yet promoted',()=>{
    const all=rows();all[0].verdict='CAPTURE-FAILED';all[0].failure='synthetic';
    expect(finish(all,{enforced:[],exceptions:[]}).blocking).toBe(true);
  });
  it('uses the tested finalizer in the real hosted producer, with a nonzero failure exit',()=>{
    const source=readFileSync(new URL('../nyay66-live.mjs',import.meta.url),'utf8');
    expect(source).toContain('finalizeEnforcement(report.rows,config,comments,coverageOptions)');
    expect(source).toContain('if(report.blocking)process.exitCode=1');
  });
  it('exits the Node build check nonzero for regression, missing coverage and unsigned exception',()=>{
    const good=rows(),regression=rows();regression[0].structure=['text'];
    const entry=exception();
    const cli=`import {finalizeEnforcement} from './scripts/lib/nyay66-enforcement.mjs';let data='';for await(const chunk of process.stdin)data+=chunk;const {rows,config,comments}=JSON.parse(data);try{process.exitCode=finalizeEnforcement(rows,config,comments,{r2:true}).blocking?1:0}catch{process.exitCode=1}`;
    for(const [values,config,comments,code] of [[good,policy(),[],0],[regression,policy(),[],1],[good.slice(1),policy(),[],1],[good,{...policy(),exceptions:[entry]},[],1]]){
      const run=spawnSync(process.execPath,['--input-type=module','-e',cli],{cwd:new URL('../..',import.meta.url),input:JSON.stringify({rows:values,config,comments}),encoding:'utf8'});
      expect(run.status,run.stderr).toBe(code);
    }
  });
});
