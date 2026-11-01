import {it,expect,vi} from 'vitest';
import {readFileSync,mkdtempSync,rmSync} from 'node:fs';
import {tmpdir} from 'node:os';
import {resolve} from 'node:path';
import {captureS18Rows} from './nyay66-s18-live.mjs';
import {S18_STATES} from './nyay66-s18-reference.mjs';
import {needsS18RasterIsolation,withS18RasterBrowser} from './nyay66-s18-raster.mjs';

function browsers(version='149.0.7827.55'){
  const isolated={version:()=>version,close:vi.fn(async()=>{})};
  const launch=vi.fn(async()=>isolated);
  const shared={version:()=> '149.0.7827.55',browserType:()=>({name:()=> 'chromium',launch}),close:vi.fn()};
  return {shared,isolated,launch};
}
it('the actual S-18 producer isolates only invalid desktop, leaving the other 17 captures on the shared browser',async()=>{
  const policy=JSON.parse(readFileSync(new URL('../nyay66-policy.json',import.meta.url)));
  const cache=resolve('test-baselines/nyay66',policy.s18.cache);
  const reference={cache,manifest:JSON.parse(readFileSync(resolve(cache,'manifest.json')))};
  const {shared,isolated,launch}=browsers(),stop=()=>Promise.reject(Error('CONTEXT_CREATION_PROBE'));
  shared.newContext=vi.fn(stop);isolated.newContext=vi.fn(stop);
  const out=mkdtempSync(resolve(tmpdir(),'nyay97-s18-raster-contract-'));
  try{
    const rows=await captureS18Rows({browser:shared,origin:'http://127.0.0.1:4321',out,reference});
    expect(rows).toHaveLength(18);
    expect(launch.mock.calls).toEqual([[{args:['--disable-partial-raster']}]]);
    expect(shared.newContext).toHaveBeenCalledTimes(17);expect(isolated.newContext).toHaveBeenCalledTimes(1);
    expect(isolated.close).toHaveBeenCalledTimes(1);expect(shared.close).not.toHaveBeenCalled();
    expect(rows.filter(r=>r.captureRaster).map(r=>[r.designState,r.viewport])).toEqual([['invalid','desktop']]);
    expect(rows.find(r=>r.captureRaster).captureRaster).toEqual({browser:'isolated-single-row-chromium',version:'149.0.7827.55',partialRaster:false,pixelPostprocessing:false,approvalHashSelection:false});
    expect(rows.every(r=>r.verdict==='CAPTURE-FAILED'&&r.failure==='CONTEXT_CREATION_PROBE')).toBe(true);
  }finally{rmSync(out,{recursive:true,force:true});}
});
it.each(S18_STATES.flatMap(state=>['mobile390','desktop'].map(viewport=>[state,viewport])))('selects %s/%s by identity only',async(state,viewport)=>{
  const expected=state==='invalid'&&viewport==='desktop', {shared,isolated,launch}=browsers(),capture=vi.fn(async browser=>browser);
  expect(needsS18RasterIsolation(state,viewport)).toBe(expected);
  expect(await withS18RasterBrowser(shared,state,viewport,capture)).toBe(expected?isolated:shared);
  expect(capture).toHaveBeenCalledTimes(1);expect(launch).toHaveBeenCalledTimes(expected?1:0);
  expect(isolated.close).toHaveBeenCalledTimes(expected?1:0);expect(shared.close).not.toHaveBeenCalled();
});
it.each([['option-manual','desktop'],['invalid','tablet'],['S-19-invalid','desktop'],[undefined,'desktop']])('never expands capture scope to %s/%s',async(state,viewport)=>{
  const {shared,launch}=browsers(),capture=vi.fn(async browser=>browser);
  expect(needsS18RasterIsolation(state,viewport)).toBe(false);
  expect(await withS18RasterBrowser(shared,state,viewport,capture)).toBe(shared);
  expect(launch).not.toHaveBeenCalled();expect(capture).toHaveBeenCalledTimes(1);
});
it('closes after capture failure, without retry or shared-browser fallback',async()=>{
  const {shared,isolated,launch}=browsers(),error=Error('capture failed'),capture=vi.fn(async()=>{throw error;});
  await expect(withS18RasterBrowser(shared,'invalid','desktop',capture)).rejects.toBe(error);
  expect(launch).toHaveBeenCalledTimes(1);expect(capture).toHaveBeenCalledTimes(1);
  expect(isolated.close).toHaveBeenCalledTimes(1);expect(shared.close).not.toHaveBeenCalled();
});
it('fails closed before capture if the browser version differs',async()=>{
  const {shared,isolated}=browsers('different'),capture=vi.fn();
  await expect(withS18RasterBrowser(shared,'invalid','desktop',capture)).rejects.toThrow('S18_RASTER_BROWSER_PIN_MISMATCH');
  expect(capture).not.toHaveBeenCalled();expect(isolated.close).toHaveBeenCalledTimes(1);
});
it('rejects non-Chromium without substituting a renderer',async()=>{
  const launch=vi.fn(),capture=vi.fn();
  await expect(withS18RasterBrowser({browserType:()=>({name:()=> 'other',launch})},'invalid','desktop',capture)).rejects.toThrow('S18_RASTER_REQUIRES_CHROMIUM');
  expect(launch).not.toHaveBeenCalled();expect(capture).not.toHaveBeenCalled();
});
it('propagates launch failure without a retry or fallback',async()=>{
  const {shared,launch}=browsers(),error=Error('launch failed'),capture=vi.fn();launch.mockRejectedValue(error);
  await expect(withS18RasterBrowser(shared,'invalid','desktop',capture)).rejects.toBe(error);
  expect(launch).toHaveBeenCalledTimes(1);expect(capture).not.toHaveBeenCalled();expect(shared.close).not.toHaveBeenCalled();
});
it('never applies the correction to references, fixtures or other screen producers',()=>{
  const read=name=>readFileSync(new URL(name,import.meta.url),'utf8');
  expect(read('nyay66-s18-live.mjs')).toContain('withS18RasterBrowser');
  for(const name of ['../nyay66-live.mjs','nyay66-s19-live.mjs','nyay66-s20-live.mjs','nyay66-s21-live.mjs','nyay66-s25-live.mjs','nyay66-s26-live.mjs','nyay66-s27-live.mjs','nyay66-s28-live.mjs','nyay66-s18-capture.mjs','nyay66-s18-fixtures.mjs'])expect(read(name)).not.toContain('withS18RasterBrowser');
  expect(read('nyay66-s18-raster.mjs')).not.toMatch(/readFile|sha256|NYAY66-EXCEPTION|screenshot|setTimeout/);
});
