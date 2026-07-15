import { getCollector } from "./TrackingObserver.sys.mjs";

export class TrackingObserverParent extends JSWindowActorParent {
  get _collector() {
    return getCollector();
  }
  receiveMessage(msg) {
    if (msg.name !== "camoufox-observer:batch") return;
    if (!this._collector) return;
    for (const rec of msg.data.records) {
      this._collector.ingestAccess(rec.u, rec.s, rec.f, rec.t);
    }
  }
}
