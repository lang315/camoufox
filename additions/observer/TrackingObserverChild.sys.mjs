export class TrackingObserverChild extends JSWindowActorChild {
  actorCreated() {
    // Low-frequency drain keeps all IPC/serialize off the fingerprint read path.
    this._timer = this.contentWindow.setInterval(() => this._drain(), 500);
  }
  didDestroy() { if (this._timer) this.contentWindow.clearInterval(this._timer); }
  _drain() {
    let json = ChromeUtils.camouDrainAccessRecords();  // "[]" when empty
    if (json === "[]") return;
    let records;
    try { records = JSON.parse(json); } catch { return; }
    if (records.length) this.sendAsyncMessage("camoufox-observer:batch", { records });
  }
}
