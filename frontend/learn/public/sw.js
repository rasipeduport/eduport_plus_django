/**
 * Eduport Plus Learn – Service Worker
 *
 * Strategy: "offline fallback only".
 * We deliberately do NOT precache app bundles or API responses — the app is
 * still fully online-first. The only thing kept in the cache is /offline.html
 * so a lost connection shows a branded page instead of the browser's error.
 *
 * Ported from the Next.js Learn app (public/sw.js) so both clients behave the
 * same way.
 */

const CACHE_NAME = 'eduport-learn-offline-v1';
// Static HTML with every style inlined -- no external CSS/JS chunks needed.
// The page therefore renders correctly regardless of build-hash changes.
const OFFLINE_URL = '/offline.html';

// ─── Install ─────────────────────────────────────────────────────────────────
self.addEventListener('install', (event) => {
  event.waitUntil(
    caches
      .open(CACHE_NAME)
      .then((cache) => cache.add(new Request(OFFLINE_URL, { cache: 'reload' })))
      .then(() => self.skipWaiting())
  );
});

// ─── Activate ────────────────────────────────────────────────────────────────
self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches
      .keys()
      .then((keys) =>
        Promise.all(
          keys.filter((key) => key !== CACHE_NAME).map((key) => caches.delete(key))
        )
      )
      .then(() => self.clients.claim())
  );
});

// ─── Fetch ───────────────────────────────────────────────────────────────────
self.addEventListener('fetch', (event) => {
  // Only same-origin navigations (HTML page loads). Assets and the cross-origin
  // API calls fall through to the network untouched.
  if (
    event.request.mode !== 'navigate' ||
    !event.request.url.startsWith(self.location.origin)
  ) {
    return;
  }

  event.respondWith(
    fetch(event.request).catch(() =>
      caches
        .open(CACHE_NAME)
        .then((cache) => cache.match(OFFLINE_URL))
        .then((response) => response ?? Response.error())
    )
  );
});
