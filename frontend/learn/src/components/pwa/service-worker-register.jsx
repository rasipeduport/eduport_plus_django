import { useEffect } from 'react';

// Registers /sw.js on mount. Rendered once from <App />; silently no-ops when
// the Service Worker API is unavailable (old browsers, insecure origins).
// `updateViaCache: 'none'` keeps the worker script itself out of the HTTP
// cache, so a redeploy always picks up the new sw.js.
export function ServiceWorkerRegister() {
  useEffect(() => {
    if (!('serviceWorker' in navigator)) return;

    navigator.serviceWorker
      .register('/sw.js', { scope: '/', updateViaCache: 'none' })
      .catch((err) => {
        console.warn('[SW] Registration failed:', err);
      });
  }, []);

  return null;
}
