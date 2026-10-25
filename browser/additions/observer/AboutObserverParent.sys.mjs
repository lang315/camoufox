import { getCollector } from "./TrackingObserver.sys.mjs";

export class AboutObserverParent extends JSWindowActorParent {
  receiveMessage(msg) {
    if (msg.name === "camoufox-observer:snapshot") {
      return getCollector()?.snapshot() ?? [];
    }
    return undefined;
  }
}
