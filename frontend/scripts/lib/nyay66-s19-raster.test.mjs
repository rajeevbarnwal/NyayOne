import {it,expect,vi} from 'vitest';
import {readFileSync,mkdtempSync,rmSync} from 'node:fs';
import {tmpdir} from 'node:os';
import {resolve} from 'node:path';
import {captureS19Rows} from './nyay66-s19-live.mjs';
import {needsS19RasterIsolation,withS19RasterBrowser} from './nyay66-s19-raster.mjs';
import {S19_MEASURED_STATES} from './nyay66-s19-coverage.mjs';

it('isolates only the mobile rejected-recovery and typed-confirmation rows; the other 48 S-19 captures retain their shared browser',async()=>{
  const policy=JSON.parse(readFileSync(new URL('../nyay66-policy.json',import.meta.url)));
  const cache=resolve('test-baselines/nyay66',policy.s19.cache);
  const reference={cache,manifest:JSON.parse(readFileSync(resolve(cache,'manifest.json')))};
  const stop=()=>Promise.reject(Error('CONTEXT_CREATION_PROBE'));
  const isolated={version:()=> '149.0.7827.55',newContext:vi.fn(stop),close:vi.fn(async()=>{})};
  const launch=vi.fn(async()=>isolated);
  const shared={version:()=> '149.0.7827.55',newContext:vi.fn(stop),close:vi.fn(),browserType:()=>({name:()=> 'chromium',launch})};
  const out=mkdtempSync(resolve(tmpdir(),'nyay92-s19-raster-contract-'));
  try{
    const rows=await captureS19Rows({browser:shared,origin:'http://127.0.0.1:4321',out,reference});
    expect(rows).toHaveLength(50);
    expect(launch).toHaveBeenCalledTimes(2);
    expect(launch.mock.calls).toEqual([[{args:['--disable-partial-raster']}],[{args:['--disable-partial-raster']}]]);
    expect(shared.newContext).toHaveBeenCalledTimes(48);expect(isolated.newContext).toHaveBeenCalledTimes(2);
    expect(isolated.close).toHaveBeenCalledTimes(2);expect(shared.close).not.toHaveBeenCalled();
    expect(rows.filter(r=>r.captureRaster?.browser==='isolated-single-row-chromium').map(r=>[r.designState,r.viewport])).toEqual([['delete-reauth-rejected','mobile390'],['delete-typed','mobile390']]);
    expect(rows.every(r=>r.verdict==='CAPTURE-FAILED'&&r.failure==='CONTEXT_CREATION_PROBE')).toBe(true);
  }finally{rmSync(out,{recursive:true,force:true});}
});

function browsers(version='149.0.7827.55'){
  const isolated={version:()=>version,close:vi.fn(async()=>{})};
  const launch=vi.fn(async()=>isolated);
  const shared={version:()=> '149.0.7827.55',browserType:()=>({name:()=> 'chromium',launch}),close:vi.fn()};
  return {shared,isolated,launch};
}
it('selects by fixed fixture identity, never by image hashes; all 48 unaffected rows keep the shared browser',async()=>{
  for(const state of S19_MEASURED_STATES)for(const viewport of ['mobile390','desktop']){
    const expected=['delete-reauth-rejected','delete-typed'].includes(state)&&viewport==='mobile390';
    expect(needsS19RasterIsolation(state,viewport)).toBe(expected);
    const {shared,isolated,launch}=browsers(),capture=vi.fn(async browser=>browser);
    expect(await withS19RasterBrowser(shared,state,viewport,capture)).toBe(expected?isolated:shared);
    expect(capture).toHaveBeenCalledTimes(1);expect(launch).toHaveBeenCalledTimes(expected?1:0);
    expect(shared.close).not.toHaveBeenCalled();
  }
});
it.each(['delete-reauth-rejected','delete-typed'])('closes the isolated %s browser after failure, without retrying or falling back',async state=>{
  const {shared,isolated,launch}=browsers(),error=Error('capture failed'),capture=vi.fn(async()=>{throw error;});
  await expect(withS19RasterBrowser(shared,state,'mobile390',capture)).rejects.toBe(error);
  expect(launch).toHaveBeenCalledTimes(1);expect(capture).toHaveBeenCalledTimes(1);
  expect(isolated.close).toHaveBeenCalledTimes(1);expect(shared.close).not.toHaveBeenCalled();
});
it.each(['delete-reauth-rejected','delete-typed'])('fails closed before %s capture if the browser pin differs',async state=>{
  const {shared,isolated}=browsers('different'),capture=vi.fn();
  await expect(withS19RasterBrowser(shared,state,'mobile390',capture)).rejects.toThrow('S19_RASTER_BROWSER_PIN_MISMATCH');
  expect(capture).not.toHaveBeenCalled();expect(isolated.close).toHaveBeenCalledTimes(1);
});
it.each(['delete-reauth-rejected','delete-typed'])('rejects non-Chromium %s capture and never substitutes another renderer',async state=>{
  const launch=vi.fn(),capture=vi.fn();
  await expect(withS19RasterBrowser({browserType:()=>({name:()=> 'other',launch})},state,'mobile390',capture)).rejects.toThrow('S19_RASTER_REQUIRES_CHROMIUM');
  expect(launch).not.toHaveBeenCalled();expect(capture).not.toHaveBeenCalled();
});
it.each(['delete-reauth-rejected','delete-typed'])('propagates %s launch failure without touching the shared browser or capturing a fallback image',async state=>{
  const {shared,launch}=browsers(),error=Error('launch failed'),capture=vi.fn();launch.mockRejectedValue(error);
  await expect(withS19RasterBrowser(shared,state,'mobile390',capture)).rejects.toBe(error);
  expect(launch).toHaveBeenCalledTimes(1);expect(capture).not.toHaveBeenCalled();expect(shared.close).not.toHaveBeenCalled();
});
it('is not applied to references, other screen captures, or product code',()=>{
  const read=name=>readFileSync(new URL(name,import.meta.url),'utf8');
  expect(read('nyay66-s19-live.mjs')).toContain('withS19RasterBrowser');
  for(const name of ['../nyay66-live.mjs','nyay66-s18-live.mjs','nyay66-s20-live.mjs','nyay66-s19-capture.mjs','nyay66-s19-fixtures.mjs'])expect(read(name)).not.toContain('withS19RasterBrowser');
  expect(read('nyay66-s19-raster.mjs')).not.toMatch(/readFile|sha256|NYAY66-EXCEPTION|screenshot|setTimeout/);
});
