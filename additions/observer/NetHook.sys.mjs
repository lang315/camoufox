// Read-only http-on-modify-request observer. Feeds Collector.ingestNet(...)
// for passive request-shape logging; must never mutate the channel (any
// mutation would be a page-observable fingerprint).
export class NetHook {
  constructor(collector) {
    this._c = collector;
  }
  start() {
    Services.obs.addObserver(this, "http-on-modify-request");
  }
  stop() {
    Services.obs.removeObserver(this, "http-on-modify-request");
  }
  observe(subject) {
    let ch;
    try {
      ch = subject.QueryInterface(Ci.nsIHttpChannel);
    } catch {
      return;
    }
    // READ ONLY. Never setRequestHeader/cancel/redirectTo/setResponseHeader
    // or otherwise mutate the channel here.
    const li = ch.loadInfo;
    const u = li?.originAttributes?.userContextId ?? 0;
    const host = ch.URI.host;
    // Top site: walk to the top browsing context's document principal.
    let site = host;
    try {
      const top = li?.browsingContext?.top?.currentWindowGlobal?.documentPrincipal;
      if (top) site = top.baseDomain || site;
    } catch {}
    this._c.ingestNet(u, site, host, ch.URI.spec, ch.requestMethod, Date.now());
  }
  get QueryInterface() {
    return ChromeUtils.generateQI(["nsIObserver"]);
  }
}
