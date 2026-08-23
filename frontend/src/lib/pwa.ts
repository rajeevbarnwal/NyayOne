/**
 * PWA registration skeleton (SAATHI-346). Registers the service worker only in
 * production and when supported; a no-op in dev/tests. The service worker
 * (public/sw.js) caches the shell/assets for offline/low-connectivity and never
 * caches API responses aggressively.
 */
export function registerServiceWorker(): void {
  if (typeof navigator === 'undefined' || !('serviceWorker' in navigator)) return;
  const env = (import.meta as { env?: { PROD?: boolean } }).env;
  const isProd = Boolean(env?.PROD);
  if (!isProd) return; // dev/test: skip
  window.addEventListener('load', () => {
    navigator.serviceWorker.register('/sw.js').catch(() => {
      /* registration failure is non-fatal */
    });
  });
}
