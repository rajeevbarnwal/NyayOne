// Synthetic UX regression against the production build. Server fixtures are
// test inputs, not product authority. No real identity or raw response is saved.
import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import { mkdir, readFile, writeFile } from 'node:fs/promises';
import { resolve } from 'node:path';
import { chromium } from 'playwright';

const base = process.env.NYAY10_BASE_URL ?? 'http://127.0.0.1:4188';
const colorScheme = process.env.NYAY10_COLOR_SCHEME ?? 'light';
assert.ok(['light','dark'].includes(colorScheme), 'NYAY10_THEME_INVALID');
const output = resolve(process.env.NYAY10_OUTPUT ?? 'test-results/nyay10-browser');
const require = createRequire(import.meta.url);
const axe = await readFile(require.resolve('axe-core/axe.min.js'), 'utf8');
await mkdir(output, { recursive: true });
const rows = [];
function check(id, pass) {
  rows.push({ id, pass: pass === true, executed: true });
  assert.equal(pass, true, id);
}
function freshProjection() {
  return { profile_version: 1, completion_version: 'v1', completion_percent: 0,
    completed_sections: [], missing_requirements: ['personal.preferred_language', 'personal.city',
      'academic.college','academic.year_of_study','academic.enrolment_number','interests.interests','interests.goals'],
    next_incomplete_section: 'personal', is_complete: false,
    institutional_email_status: 'not_provided', guardian: {required:false,status:'not_required'},
    access_mode:'full', disabled_capabilities: [],
    profile_prompt:{should_show:true,dismissed_for_session:false},
    profile:{personal:{first_name:'Synthetic',middle_name:null,last_name:'Student',
      date_of_birth:'2000-01-01',preferred_language:null,city:null,pronouns:null},
    academic:{college:null,year_of_study:null,enrolment_number:null,institutional_email:null,bar_enrolment_number:null},
    interests:{interests:[],goals:[]}}};
}
const actor = {sub:'00000000-0000-4000-8000-000000002701',roles:['student'],
  student_profile_id:'00000000-0000-4000-8000-000000002702',student_verification:'draft',
  is_minor:false,consent_state:['privacy_notice','terms']};
const browser = await chromium.launch();
let active = 'setup';
try {
  for (const viewport of [{width:390,height:844}, {width:1440,height:1000}]) {
    const prefix = String(viewport.width);
    const context = await browser.newContext({viewport, colorScheme, serviceWorkers:'block'});
    const page = await context.newPage();
    let projection = freshProjection();
    let failure = null;
    let release;
    let arrived;
    let pending;
    const headers = {'access-control-allow-origin':new URL(base).origin,
      'access-control-allow-credentials':'true',
      'access-control-allow-methods':'GET,POST,PUT,OPTIONS',
      'access-control-allow-headers':'content-type,idempotency-key,x-csrf-token'};
    await page.route('**/api/v1/**', async route => {
      const path = new URL(route.request().url()).pathname;
      const json = (body,status=200) => route.fulfill({status,headers,contentType:'application/json',body:JSON.stringify(body)});
      if (route.request().method()==='OPTIONS') return route.fulfill({status:204,headers});
      if (path==='/api/v1/auth/student/session') return json({authenticated:true,actor});
      if (path==='/api/v1/student/profile') return json(projection);
      if (path==='/api/v1/student/profile/prompt-dismiss') {
        if (pending) { arrived(); await pending; }
        if (failure === 'network') return route.abort('failed');
        if (failure !== null) return json({detail:{code:failure===401?'authentication_required':'profile_request_refused'}},failure);
        projection = {...projection, profile_prompt:{should_show:false,dismissed_for_session:true}};
        return json(projection);
      }
      return json({detail:{code:'synthetic_route_not_provided'}},404);
    });
    async function open() {
      const observed = page.waitForResponse(r=>new URL(r.url()).pathname==='/api/v1/student/profile');
      await page.goto(base+'/s-07', {waitUntil:'domcontentloaded'});
      await observed;
      await page.getByRole('dialog').waitFor();
      await page.evaluate(()=>document.fonts.ready);
    }
    active=prefix+'-dialog';
    await open();
    check(active+'-entry-focus', await page.locator('#profile-completion-dialog-title').evaluate(e=>e===document.activeElement));
    check(active+'-inert', await page.getByTestId('profile-prompt-background').evaluate(e=>e.hasAttribute('inert')));
    const dialog=page.getByRole('dialog');
    await dialog.getByRole('button',{name:'Sign out',exact:true}).focus();
    await page.keyboard.press('Tab');
    check(active+'-trap', await dialog.getByRole('button',{name:'Close profile prompt',exact:true}).evaluate(e=>e===document.activeElement));
    for (const [index,name] of ['Complete Profile','Maybe Later','Sign out','Close profile prompt'].entries()) {
      await page.keyboard.press('Tab');
      check(active+'-control-order-'+index, await dialog.getByRole('button',{name,exact:true}).evaluate(e=>e===document.activeElement));
    }
    await page.keyboard.press('Shift+Tab');
    check(active+'-reverse-trap', await dialog.getByRole('button',{name:'Sign out',exact:true}).evaluate(e=>e===document.activeElement));
    const rect=await dialog.boundingBox();
    check(active+'-layout',viewport.width===390
      ? Math.abs(rect.x+rect.width/2-viewport.width/2)<2
        && Math.abs(rect.y+rect.height/2-viewport.height/2)<2
        && rect.width<=viewport.width-32
      : rect.y>100);
    await page.addScriptTag({content:axe});
    const violations=await page.evaluate(async()=> (await window.axe.run(document)).violations
      .filter(v=>['serious','critical'].includes(v.impact)).map(v=>v.id));
    if (violations.length) console.log(JSON.stringify({check:'axe',violationIds:violations}));
    check(prefix+'-dialog-axe',violations.length===0);
    await page.screenshot({path:resolve(output,`prompt-${prefix}.png`)});
    for (const status of [403,409,422,500,'network']) {
      active=prefix+'-dismiss-'+status;
      failure=status;
      await page.getByRole('button',{name:'Maybe Later'}).click();
      await page.getByTestId('profile-save-error').waitFor();
      await page.waitForFunction(()=>document.querySelector('[data-testid="profile-save-error"]')===document.activeElement);
      check(active+'-focus',await page.getByTestId('profile-save-error').evaluate(e=>e===document.activeElement));
      check(active+'-no-navigation',new URL(page.url()).pathname==='/s-07');
    }
    failure=null;
    active=prefix+'-pending';
    const arrival=new Promise(r=>{arrived=r;});
    pending=new Promise(r=>{release=r;});
    await page.getByRole('button',{name:'Maybe Later'}).click();
    await arrival;
    check(active+'-cannot-race',await page.getByRole('button',{name:'Complete Profile',exact:true}).isDisabled());
    check(active+'-not-success-yet',new URL(page.url()).pathname==='/s-07');
    release(); pending=null;
    await page.waitForURL('**/s-14');
    await page.getByTestId('profile-completion-card').waitFor();
    check(prefix+'-home-cta',await page.getByTestId('profile-completion-card').getByRole('link').getAttribute('href')==='/s-10?section=personal');
    await page.reload({waitUntil:'domcontentloaded'});
    await page.getByTestId('profile-completion-card').waitFor();
    check(prefix+'-server-dismissal-persists',await page.getByRole('dialog').count()===0);
    await page.screenshot({path:resolve(output,`home-card-${prefix}.png`)});
    await page.goto(base+'/s-17',{waitUntil:'domcontentloaded'});
    await page.getByTestId('profile-completion-card').waitFor();
    check(prefix+'-profile-cta',await page.getByTestId('profile-completion-card').getByRole('link').getAttribute('href')==='/s-10?section=personal');
    projection=freshProjection();
    active=prefix+'-dismiss-401';
    await open();
    failure=401;
    const refreshed=page.waitForResponse(r=>new URL(r.url()).pathname==='/api/v1/auth/student/session');
    await page.getByRole('button',{name:'Maybe Later'}).click();
    await refreshed;
    check(active+'-no-completion-navigation',!['/s-14','/s-10','/s-11'].includes(new URL(page.url()).pathname));
    await context.close();
  }
} catch {
  if (!rows.some(r=>r.pass===false)) rows.push({id:active,pass:false,executed:true});
  process.exitCode=1;
} finally {
  await browser.close();
  const summary={schemaVersion:'nyay10-ux-regression/v1',fixtureKind:'synthetic-api-responses',
    colorScheme, retryCount:0,passed:rows.filter(r=>r.pass).length,failed:rows.filter(r=>!r.pass).length,rows};
  await writeFile(resolve(output,'results.json'),JSON.stringify(summary,null,2)+'\n');
  console.log(JSON.stringify({passed:summary.passed,failed:summary.failed}));
}
