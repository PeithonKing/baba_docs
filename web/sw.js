// Minimal service worker: needed for "Install app". Always goes to the network
// (the app is useless offline anyway, and we never want stale pages).
self.addEventListener("install", () => self.skipWaiting());
self.addEventListener("activate", (e) => e.waitUntil(self.clients.claim()));
self.addEventListener("fetch", () => {});
