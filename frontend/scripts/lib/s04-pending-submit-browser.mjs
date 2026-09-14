// QA-NYAY83-1: synthetic delayed transport, real browser routing and unmount.
// No request in these isolated contexts reaches the real authentication backend.
export async function runS04PendingSubmitBrowser({ browser, base }) {
  const webOrigin = new URL(base).origin;
  const cases = [];
  async function boundedHandshake(promise, label) {
    let timer;
    try {
      return await Promise.race([
        promise,
        new Promise((_, reject) => { timer = setTimeout(() => reject(new Error(`S04_SYNTHETIC_TIMEOUT:${label}`)), 8_000); }),
      ]);
    } finally { clearTimeout(timer); }
  }
  for (const channel of ['mobile', 'email']) {
    for (const outcome of ['success', 'failure']) {
      for (const transport of ['honors-abort', 'ignores-abort']) {
        const context = await browser.newContext({
          viewport: { width: 390, height: 844 },
          colorScheme: 'light', reducedMotion: 'reduce', serviceWorkers: 'block',
        });
        const page = await context.newPage();
        page.setDefaultTimeout(8_000);
        const result = { channel, outcome, transport, evidenceClass: 'SYNTHETIC_API_REAL_BROWSER_HISTORY', pass: false };
        const unexpected = [];
        const pageErrors = [];
        let releaseResponse;
        const responseReleased = new Promise(resolve => { releaseResponse = resolve; });
        let observeStart;
        const startObserved = new Promise(resolve => { observeStart = resolve; });
        let finishResponse;
        const responseFinished = new Promise(resolve => { finishResponse = resolve; });
        const unavailable = {
          status: 'unavailable', purpose: null, destination_masked: null,
          attempts_left: null, expires_in_seconds: null, resend_in_seconds: null,
          locked_for_seconds: null, resend_allowed: false,
        };
        const pending = {
          status: 'pending', purpose: 'login',
          destination_masked: channel === 'email' ? 's•••••@example.test' : '••••••0340',
          attempts_left: 3, expires_in_seconds: 300, resend_in_seconds: 30,
          locked_for_seconds: 0, resend_allowed: false,
        };
        page.on('pageerror', error => pageErrors.push(error.name));
        await context.addInitScript(({ transport }) => {
          const observed = { starts: 0, settles: 0, signals: 0, aborts: 0, paths: [] };
          window.__nyay83PendingSubmit = observed;
          for (const method of ['pushState', 'replaceState']) {
            const original = history[method].bind(history);
            history[method] = (...args) => {
              const returned = original(...args);
              observed.paths.push(location.pathname);
              return returned;
            };
          }
          const originalFetch = window.fetch.bind(window);
          window.fetch = (input, init) => {
            const path = new URL(typeof input === 'string' ? input : input.url, location.href).pathname;
            if (!['/api/v1/auth/student/login/otp/start', '/api/v1/auth/student/login/email/start'].includes(path)) {
              return originalFetch(input, init);
            }
            observed.starts += 1;
            if (init?.signal instanceof AbortSignal) {
              observed.signals += 1;
              init.signal.addEventListener('abort', () => { observed.aborts += 1; }, { once: true });
            }
            // Deliberately model a transport which cannot cancel a response.
            // Product request ownership must still refuse its stale completion.
            const effectiveInit = transport === 'ignores-abort' ? { ...init, signal: undefined } : init;
            return originalFetch(input, effectiveInit).finally(() => { observed.settles += 1; });
          };
        }, { transport });
        await page.route('**/*', async route => {
          const request = route.request();
          const url = new URL(request.url());
          const json = (body, status = 200) => route.fulfill({ status, contentType: 'application/json', body: JSON.stringify(body) });
          if (!url.pathname.startsWith('/api/')) {
            if (url.origin === webOrigin) return route.continue();
            unexpected.push('external-resource');
            return route.abort();
          }
          if (request.method() === 'GET' && url.pathname === '/api/v1/auth/student/session') return json({ authenticated: false, actor: null });
          if (request.method() === 'GET' && url.pathname === '/api/v1/auth/student/login/channels') return json({ channels: [{ channel: 'mobile', enabled: true }, { channel: 'email', enabled: true }] });
          if (request.method() === 'GET' && url.pathname === '/api/v1/auth/student/otp/state') return json(pending);
          if (request.method() === 'POST' && ['/api/v1/auth/student/login/otp/start', '/api/v1/auth/student/login/email/start'].includes(url.pathname)) {
            observeStart();
            await responseReleased;
            try {
              if (outcome === 'success') await json(pending);
              else await json({ detail: { code: 'synthetic_delayed_start_failure' } }, 503);
            } catch (error) {
              // An aborted browser request cannot receive the delayed body.
              // Other failures are not silently converted into a passing case.
              if (transport !== 'honors-abort' || !/closed|canceled|cancelled|aborted|invalid interception/iu.test(String(error.message))) throw error;
            } finally { finishResponse(); }
            return;
          }
          if (request.method() === 'POST' && url.pathname === '/api/v1/auth/student/otp/cancel') return json(unavailable);
          unexpected.push(`${request.method()} ${url.pathname}`);
          return json({ detail: { code: 'UNMATCHED_SYNTHETIC_ENDPOINT' } }, 404);
        });
        try {
          await page.goto(`${base}/s-03`);
          await page.getByRole('button', { name: 'Sign In Securely', exact: true }).click();
          await page.waitForURL('**/s-04');
          await page.waitForFunction(() => {
            const button = [...document.querySelectorAll('.v321-segment button')].find(node => node.textContent.includes('Verified Email'));
            return button && !button.disabled;
          });
          if (channel === 'email') {
            await page.getByRole('button', { name: 'Verified Email', exact: true }).click();
            await page.locator('#v34-login-email').fill('synthetic.student@example.test');
          } else await page.locator('#v34-login-mobile').fill('9000000340');
          await page.getByRole('button', { name: 'Send Code', exact: true }).click();
          await boundedHandshake(startObserved, 'start-observed');
          await page.goBack();
          await page.waitForURL('**/s-03');
          await page.getByRole('button', { name: 'Sign In Securely', exact: true }).waitFor();
          result.pathBeforeRelease = new URL(page.url()).pathname;
          releaseResponse();
          await boundedHandshake(responseFinished, 'response-finished');
          await page.waitForFunction(() => window.__nyay83PendingSubmit.settles === 1);
          // Drain response/parser microtasks and the following React paint;
          // no sleeps or artificial production navigation delays are added.
          await page.evaluate(() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve))));
          result.observed = await page.evaluate(() => ({ ...window.__nyay83PendingSubmit, pathname: location.pathname, alerts: document.querySelectorAll('[role="alert"]').length }));
          result.unexpected = unexpected;
          result.pageErrors = pageErrors;
          result.pass = result.pathBeforeRelease === '/s-03'
            && result.observed.pathname === '/s-03'
            && !result.observed.paths.includes('/s-05')
            && result.observed.starts === 1 && result.observed.signals === 1
            && result.observed.aborts === 1 && result.observed.settles === 1
            && result.observed.alerts === 0 && unexpected.length === 0 && pageErrors.length === 0;
        } catch (error) {
          result.error = String(error.message).slice(0, 400);
        } finally {
          releaseResponse();
          await context.close();
        }
        cases.push(result);
      }
    }
  }
  return {
    evidenceClass: 'SYNTHETIC_API_REAL_BROWSER_HISTORY',
    scope: 'S-04 pending-submit abandonment; no real backend, physical device or spoken screen-reader claim',
    total: cases.length, passed: cases.filter(row => row.pass).length,
    pass: cases.length === 8 && cases.every(row => row.pass), cases,
  };
}
