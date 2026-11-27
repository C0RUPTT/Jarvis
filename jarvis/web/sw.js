// Opens the Jarvis app instantly, even while the server is slow or restarting: the page itself is
// kept on the phone and refreshed from the server whenever it answers within a few seconds.
// Only the app page is cached; everything Jarvis says or does still goes to the server.
const CACHE = "jarvis-app-v1";

self.addEventListener("install", (e) => {
  e.waitUntil(caches.open(CACHE).then(c => c.add("/")).then(() => self.skipWaiting()).catch(() => self.skipWaiting()));
});
self.addEventListener("activate", (e) => e.waitUntil(self.clients.claim()));

self.addEventListener("fetch", (e) => {
  const url = new URL(e.request.url);
  if (e.request.mode !== "navigate" || url.pathname !== "/") return;   // only the app page itself
  e.respondWith((async () => {
    const cache = await caches.open(CACHE);
    const fresh = fetch(e.request).then(r => { if (r.ok) cache.put("/", r.clone()); return r; });
    const timeout = new Promise(res => setTimeout(res, 3500, null));
    const quick = await Promise.race([fresh.catch(() => null), timeout]);
    if (quick) return quick;                                          // the server answered in time
    const saved = await cache.match("/");
    return saved || fresh;                                            // slow server: open the saved copy
  })());
});
