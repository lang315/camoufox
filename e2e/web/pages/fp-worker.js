const snap = () => ({ua: navigator.userAgent, platform: navigator.platform, language: navigator.language,
  languages: [...navigator.languages], cores: navigator.hardwareConcurrency,
  tz: Intl.DateTimeFormat().resolvedOptions().timeZone});
self.onconnect = e => e.ports[0].postMessage(snap());  // SharedWorker
self.onmessage = () => postMessage(snap());            // dedicated Worker
