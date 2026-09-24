const snap = () => ({ua: navigator.userAgent, platform: navigator.platform, language: navigator.language,
  languages: [...navigator.languages], cores: navigator.hardwareConcurrency,
  tz: Intl.DateTimeFormat().resolvedOptions().timeZone});
self.addEventListener("install", () => self.skipWaiting());
self.addEventListener("activate", e => e.waitUntil(self.clients.claim()));
self.addEventListener("fetch", e => {
  if (new URL(e.request.url).pathname === "/sw-probe") e.respondWith(new Response("from-sw"));
});
self.addEventListener("message", e => e.source.postMessage(snap()));
