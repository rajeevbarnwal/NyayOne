import {describe,it,expect,vi,afterEach} from 'vitest';
import {readFileSync} from 'node:fs';
import * as capture from './nyay66-r2-capture.mjs';

afterEach(()=>vi.unstubAllGlobals());
describe('R2 capture excludes reviewer-only corner clipping',()=>{
  it('removes only the viewport frame radius, preserving layout and scroll clipping',()=>{
    const viewport={style:{borderRadius:'26px',overflow:'auto',width:'390px',height:'844px'}};
    const app={style:{borderRadius:'18px',background:'approved'}};
    const query=vi.fn(selector=>selector==='.vp'?viewport:app);
    vi.stubGlobal('document',{querySelector:query});
    capture.removeR2ReviewerClipping();
    expect(viewport.style).toEqual({borderRadius:'0px',overflow:'auto',width:'390px',height:'844px'});
    expect(app.style).toEqual({borderRadius:'18px',background:'approved'});
    expect(query.mock.calls).toEqual([['.vp']]);
  });
  it('refuses a missing reviewer viewport instead of touching the app or body',()=>{
    vi.stubGlobal('document',{querySelector:()=>null});
    expect(()=>capture.removeR2ReviewerClipping()).toThrow('R2_CAPTURE_VIEWPORT_MISSING');
  });
  it('uses the capture-only transform before measuring reference bytes',()=>{
    const text=readFileSync(new URL('../nyay66-r2-calibrate.mjs',import.meta.url),'utf8');
    expect(text).toContain('await page.evaluate(removeR2ReviewerClipping);');
    expect(text.indexOf('await page.evaluate(removeR2ReviewerClipping);')).toBeLessThan(text.indexOf("page.locator('.vp').screenshot"));
    const live=readFileSync(new URL('../nyay66-live.mjs',import.meta.url),'utf8');
    expect(live).not.toContain('removeR2ReviewerClipping');
  });
});
