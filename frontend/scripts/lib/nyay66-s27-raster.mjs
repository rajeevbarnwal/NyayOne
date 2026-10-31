// Test-only S-27 raster isolation. Partial damage replay can round the edge of
// a fractional-position rounded border differently according to paint history,
// even after fonts settle and successive screenshots of that page agree.
// Force complete rasterization in a separate process for EACH row (contexts
// alone still share process raster caches). Never change the shared
// browser used by the existing 198 rows, product DOM/CSS, or screenshot pixels.
export async function withS27RasterBrowser(shared,capture){
  const type=shared.browserType();
  if(type.name()!=='chromium')throw Error('S27_RASTER_REQUIRES_CHROMIUM');
  const isolated=await type.launch({args:['--disable-partial-raster']});
  try{
    if(isolated.version()!==shared.version())throw Error('S27_RASTER_BROWSER_PIN_MISMATCH');
    return await capture(isolated);
  }finally{await isolated.close();}
}
