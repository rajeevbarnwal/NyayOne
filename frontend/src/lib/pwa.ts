/**
 * PWA registration skeleton (SAATHI-346). Registers the service worker only in
 * production and when supported; a no-op in dev/tests. The service worker
 * (public/sw.js) caches the shell/assets for offline/low-connectivity and never
 * caches API responses aggressively.
 */
export function registerServiceWorker(): void {
  if (typeof navigator === 'undefined' || !('serviceWorker' in navigator)) return;
  const env = (import.meta as { env?: { PROD?: boolean; VITE_DISABLE_SERVICE_WORKER?: string } }).env;
  const isProd = Boolean(env?.PROD);
  if (!isProd) return; // dev/test: skip
  // Self-signed target-runtime fixtures cannot install a service worker even
  // when their page context explicitly accepts the certificate. Keep the
  // production default enabled, but permit release-test deployments to opt out
  // explicitly so a Chromium certificate warning is never mistaken for an
  // application console defect.
  if (env?.VITE_DISABLE_SERVICE_WORKER === 'true') return;
  window.addEventListener('load', () => {
    navigator.serviceWorker.register('/sw.js').catch(() => {
      /* registration failure is non-fatal */
    });
  });
}
