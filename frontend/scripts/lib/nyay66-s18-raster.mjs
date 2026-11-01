// Test-only isolation for S-18 desktop validation-error. Font-delivery timing
// changes partial-raster border bytes despite identical geometry. Keep every
// other row on its existing capture path; never choose images by approval hash.
export const needsS18RasterIsolation=(state,viewport)=>state==='invalid'&&viewport==='desktop';
export async function withS18RasterBrowser(shared,state,viewport,capture){
  if(!needsS18RasterIsolation(state,viewport))return capture(shared);
  const type=shared.browserType();
  if(type.name()!=='chromium')throw Error('S18_RASTER_REQUIRES_CHROMIUM');
  const isolated=await type.launch({args:['--disable-partial-raster']});
  try{
    if(isolated.version()!==shared.version())throw Error('S18_RASTER_BROWSER_PIN_MISMATCH');
    return await capture(isolated);
  }finally{await isolated.close();}
}
