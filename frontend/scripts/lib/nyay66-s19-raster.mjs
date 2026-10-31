// Test-only isolation for every measured S-19 row. Browser contexts alone share
// process raster caches; selecting only previously flaky states leaves the
// remaining sequence dependent on prior paints. References, other screens and
// the shared browser are untouched. A deterministic image still needs its own
// exact owner approval; this helper never selects images by approval hash.
import {S19_MEASURED_STATES} from './nyay66-s19-coverage.mjs';
export const needsS19RasterIsolation=(state,viewport)=>
  S19_MEASURED_STATES.includes(state)&&['mobile390','desktop'].includes(viewport);
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
