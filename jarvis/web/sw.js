// Opens the Jarvis app instantly: the page is kept on the phone and shown at once, and a fresh copy
// is fetched from the server in the background for next time (updates show from the next opening).
// Only the app page is cached; everything Jarvis says or does still goes to the server.
const CACHE = "jarvis-app-v2";

self.addEventListener("install", (e) => {
  e.waitUntil(caches.open(CACHE).then(c => c.add("/")).then(() => self.skipWaiting()).catch(() => self.skipWaiting()));
});
self.addEventListener("activate", (e) => e.waitUntil((async () => {
  for (const key of await caches.keys()) if (key !== CACHE) await caches.delete(key);
  await self.clients.claim();
})()));

self.addEventListener("fetch", (e) => {
  const url = new URL(e.request.url);
  if (e.request.mode !== "navigate" || url.pathname !== "/") return;   // only the app page itself
  e.respondWith((async () => {
    const cache = await caches.open(CACHE);
    const fresh = fetch(e.request).then(r => { if (r.ok) cache.put("/", r.clone()); return r; });
    const saved = await cache.match("/");
    if (saved) { e.waitUntil(fresh.catch(() => {})); return saved; }   // instant; refreshed for next time
    return fresh;                                                      // first time: from the server
  })());
});
