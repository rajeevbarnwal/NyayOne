import {describe,it,expect,vi} from 'vitest';
import {readFileSync} from 'node:fs';
import {withS21RasterBrowser} from './nyay66-s21-raster.mjs';

function browsers(version='149.0.7827.55'){
  const isolated={version:()=>version,close:vi.fn(async()=>{})};
  const launch=vi.fn(async()=>isolated);
  const shared={version:()=> '149.0.7827.55',browserType:()=>({name:()=> 'chromium',launch}),close:vi.fn()};
  return {shared,isolated,launch};
}
describe('S-21-only full-raster capture isolation',()=>{
  it('uses the same pinned Chromium version in a separate process, without changing the shared browser',async()=>{
    const {shared,isolated,launch}=browsers(),capture=vi.fn(async browser=>{expect(browser).toBe(isolated);return 'raw capture';});
    expect(await withS21RasterBrowser(shared,capture)).toBe('raw capture');
    expect(launch).toHaveBeenCalledExactlyOnceWith({args:['--disable-partial-raster']});
    expect(capture).toHaveBeenCalledTimes(1);expect(isolated.close).toHaveBeenCalledTimes(1);expect(shared.close).not.toHaveBeenCalled();
  });
  it('closes the isolated process on capture failure, propagating the failure without retry or fallback',async()=>{
    const {shared,isolated}=browsers(),error=Error('capture failed'),capture=vi.fn(async()=>{throw error;});
    await expect(withS21RasterBrowser(shared,capture)).rejects.toBe(error);
    expect(capture).toHaveBeenCalledTimes(1);expect(isolated.close).toHaveBeenCalledTimes(1);expect(shared.close).not.toHaveBeenCalled();
  });
  it('fails closed before capture if the isolated browser version differs',async()=>{
    const {shared,isolated}=browsers('different'),capture=vi.fn();
    await expect(withS21RasterBrowser(shared,capture)).rejects.toThrow('S21_RASTER_BROWSER_PIN_MISMATCH');
    expect(capture).not.toHaveBeenCalled();expect(isolated.close).toHaveBeenCalledTimes(1);
  });
  it('fails closed on non-Chromium input',async()=>{
    const launch=vi.fn(),capture=vi.fn();
    await expect(withS21RasterBrowser({browserType:()=>({name:()=> 'other',launch})},capture)).rejects.toThrow('S21_RASTER_REQUIRES_CHROMIUM');
    expect(launch).not.toHaveBeenCalled();expect(capture).not.toHaveBeenCalled();
  });
  it('is called only by the S-21 producer; shared captures keep their existing browser',()=>{
    const read=name=>readFileSync(new URL(name,import.meta.url),'utf8');
    expect(read('nyay66-s21-live.mjs')).toContain('withS21RasterBrowser');
    for(const name of ['../nyay66-live.mjs','nyay66-s18-live.mjs','nyay66-s19-live.mjs','nyay66-s21-capture.mjs'])
      expect(read(name)).not.toContain('withS21RasterBrowser');
  });
});
