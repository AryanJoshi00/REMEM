/* REMEM service worker: cache the app shell; cache-fallback for the due list and concept list. */
const SHELL = "remem-shell-v9";
const API = "remem-api";
const FILES = ["./", "index.html", "app.js", "styles.css", "manifest.json", "icon-192.png", "icon-512.png", "icon.svg", "icon-maskable-512.png", "apple-touch-icon.png", "favicon-32.png"];

self.addEventListener("install", e => { e.waitUntil(caches.open(SHELL).then(c => c.addAll(FILES)).then(() => self.skipWaiting())); });
self.addEventListener("activate", e => {
  e.waitUntil(caches.keys().then(keys => Promise.all(keys.filter(k => k !== SHELL && k !== API).map(k => caches.delete(k)))).then(() => self.clients.claim()));
});

self.addEventListener("fetch", e => {
  const req = e.request, url = new URL(req.url);
  if (req.method !== "GET" || url.origin !== location.origin) return;
  if (url.pathname.endsWith("/api/due") || url.pathname.endsWith("/api/concepts")) {          // network first, cached fallback when offline
    e.respondWith(fetch(req).then(r => { if (r.ok) { const copy = r.clone(); caches.open(API).then(c => c.put(req, copy)); } return r; })
      .catch(() => caches.match(req).then(r => r || new Response(JSON.stringify({ detail: "Offline" }), { status: 503, headers: { "Content-Type": "application/json" } }))));
    return;
  }
  if (url.pathname.includes("/api/")) return;                                                // never cache other API calls
  e.respondWith(fetch(req).then(r => { if (r.ok) { const copy = r.clone(); caches.open(SHELL).then(c => c.put(req, copy)); } return r; })   // network first so app updates reach phones; cache when offline
    .catch(() => caches.match(req)));
});
