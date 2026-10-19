// Test-only capture isolation for the one S-19 row with a demonstrated
// paint-history-dependent rounded-border raster. Other S-19 rows and the
// shared browser are untouched. This does not grant an exception or claim
// that the deterministic result matches any historical approval hash.
export const needsS19RasterIsolation=(state,viewport)=>state==='delete-reauth-rejected'&&viewport==='mobile390';
export async function withS19RasterBrowser(shared,state,viewport,capture){
  if(!needsS19RasterIsolation(state,viewport))return capture(shared);
  const type=shared.browserType();
  if(type.name()!=='chromium')throw Error('S19_RASTER_REQUIRES_CHROMIUM');
  const isolated=await type.launch({args:['--disable-partial-raster']});
  try{
    if(isolated.version()!==shared.version())throw Error('S19_RASTER_BROWSER_PIN_MISMATCH');
    return await capture(isolated);
  }finally{await isolated.close();}
}
