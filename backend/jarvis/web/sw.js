/* Service Worker: speichert die App-Oberfläche für den Offline-Start.
   API-Antworten werden NICHT zwischengespeichert (die App speichert Daten selbst lokal). */
const CACHE = "jarvis-shell-v4";
const SHELL = ["/", "/static/app.js", "/static/style.css", "/manifest.webmanifest",
  "/static/icons/icon.svg", "/static/icons/icon-192.png", "/static/icons/icon-180.png"];
self.addEventListener("install", (e) => { e.waitUntil(caches.open(CACHE).then((c) => c.addAll(SHELL)).then(() => self.skipWaiting())); });
self.addEventListener("activate", (e) => {
  e.waitUntil(caches.keys().then((keys) => Promise.all(keys.filter((k) => k !== CACHE).map((k) => caches.delete(k)))).then(() => self.clients.claim()));
});
self.addEventListener("fetch", (e) => {
  const url = new URL(e.request.url);
  if (e.request.method !== "GET" || url.origin !== location.origin || url.pathname.startsWith("/api") || url.pathname === "/ws") return;
  // Netzwerk zuerst (immer aktuelle Version), bei Offline aus dem Cache
  e.respondWith(fetch(e.request).then((r) => {
    if (r.ok && SHELL.includes(url.pathname)) { const copy = r.clone(); caches.open(CACHE).then((c) => c.put(e.request, copy)); }
    return r;
  }).catch(() => caches.match(e.request).then((m) => m || caches.match("/"))));
});
