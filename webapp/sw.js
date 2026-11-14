/* REMEM service worker: cache the app shell; cache-fallback for the due list and concept list. */
const SHELL = "remem-shell-v20";
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

// ---- review reminders: the server sends "N concepts are ready to review"; show it and put N on the app icon, even while the app is closed
self.addEventListener("push", e => {
  let d = {};
  try { d = e.data ? e.data.json() : {}; } catch (x) { d = { body: e.data ? e.data.text() : "" }; }
  const n = Number(d.count) || 0;
  const badge = n > 0 && self.navigator.setAppBadge ? self.navigator.setAppBadge(n).catch(() => {}) : Promise.resolve();
  e.waitUntil(Promise.all([badge, self.registration.showNotification(d.title || "Time to review", {
    body: d.body || "Some concepts are ready to review.", icon: "icon-192.png", badge: "icon-192.png",
    tag: "remem-due", renotify: true, data: { url: d.url || "./#/" },
  })]));
});

self.addEventListener("notificationclick", e => {
  e.notification.close();
  const url = new URL(e.notification.data && e.notification.data.url || "./#/", self.registration.scope).href;
  e.waitUntil(self.clients.matchAll({ type: "window", includeUncontrolled: true }).then(list => {
    for (const c of list) if (c.url.startsWith(self.registration.scope) && "focus" in c) { c.navigate(url).catch(() => {}); return c.focus(); }
    return self.clients.openWindow(url);
  }));
});
