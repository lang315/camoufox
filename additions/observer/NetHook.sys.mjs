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
    // Skip browser-internal traffic (favicon/telemetry/update/system loads) so
    // the audit rows reflect page-triggered requests, not chrome noise.
    if (!li || li.loadingPrincipal?.isSystemPrincipal) {
      return;
    }
    const u = li?.originAttributes?.userContextId ?? 0;
    const host = ch.URI.host;
    // Site = eTLD+1. For a top-level document load the top principal still
    // points at the previous doc (about:blank / null principal) when this
    // fires, which yielded a null-principal GUID; use the request URI itself
    // there. For subresources the top principal is valid by now; fall back to
    // the request URI if not.
    let site = host;
    try {
      if (li.externalContentPolicyType === Ci.nsIContentPolicy.TYPE_DOCUMENT) {
        site = Services.eTLD.getBaseDomain(ch.URI);
      } else {
        const topP = li?.browsingContext?.top?.currentWindowGlobal?.documentPrincipal;
        site =
          topP?.isContentPrincipal && topP.baseDomain
            ? topP.baseDomain
            : Services.eTLD.getBaseDomain(ch.URI);
      }
    } catch {
      try {
        site = Services.eTLD.getBaseDomain(ch.URI);
      } catch {}
    }
    this._c.ingestNet(u, site, host, ch.URI.spec, ch.requestMethod, Date.now());
  }
  get QueryInterface() {
    return ChromeUtils.generateQI(["nsIObserver"]);
  }
}
