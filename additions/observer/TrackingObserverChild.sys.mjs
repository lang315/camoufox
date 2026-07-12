export class TrackingObserverChild extends JSWindowActorChild {
  actorCreated() {
    // Low-frequency drain keeps all IPC/serialize off the fingerprint read path.
    this._timer = this.contentWindow.setInterval(() => this._drain(), 500);
  }
  didDestroy() {
    // contentWindow may already be torn down here; guard + swallow so a
    // teardown race never throws into the console (a page-observable tell).
    try {
      this.contentWindow?.clearInterval(this._timer);
    } catch {}
  }
  _drain() {
    // Swallow everything: a dead actor's sendAsyncMessage, a ChromeUtils hiccup,
    // or a parse error must not spam the console or break the interval.
    try {
      let json = ChromeUtils.camouDrainAccessRecords();  // "[]" when empty
      if (json === "[]") return;
      let records;
      try {
        records = JSON.parse(json);
      } catch {
        return;
      }
      if (records.length) {
        this.sendAsyncMessage("camoufox-observer:batch", { records });
      }
    } catch {}
  }
}
