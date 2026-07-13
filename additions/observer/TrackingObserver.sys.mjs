import { Collector } from "./Collector.sys.mjs";
import { NetHook } from "./NetHook.sys.mjs";

// Env-based arm switch: a default (unarmed) profile registers nothing.
// Mirrors the cached CAMOU_OBSERVE gate in AccessObserver::IsArmed()
// (additions/camoucfg/AccessObserver.hpp).
function isArmed() {
  const v = Services.env.get("CAMOU_OBSERVE");
  return !!v && v !== "0";
}

let gCollector = null;
let gNetHook = null;

// Shared with TrackingObserverParent.sys.mjs, which has no other way to
// reach the singleton Collector instantiated below.
export function getCollector() {
  return gCollector;
}

let gRegistered = false;

function register() {
  if (gRegistered || !isArmed()) return;
  gRegistered = true;

  const { ActorManagerParent } = ChromeUtils.importESModule(
    "resource://gre/modules/ActorManagerParent.sys.mjs"
  );

  // Actor name MUST match the exported class names (TrackingObserverParent /
  // TrackingObserverChild). Firefox resolves `${ActorName}Child` from the
  // child esModule; a mismatch makes the child silently never instantiate
  // (no drain, no capture) — verified at runtime.
  ActorManagerParent.addJSWindowActors({
    TrackingObserver: {
      parent: {
        esModuleURI: "resource://gre/modules/TrackingObserverParent.sys.mjs",
      },
      child: {
        esModuleURI: "resource://gre/modules/TrackingObserverChild.sys.mjs",
        events: {
          DOMWindowCreated: {},
        },
      },
    },
  });

  gCollector = new Collector();
  gCollector.subscribe(() => Services.obs.notifyObservers(null, "camoufox-observer:update", null));
  gNetHook = new NetHook(gCollector);
  gNetHook.start();
}

export class TrackingObserver {
  constructor() {
    register();
  }
  get classID() {
    return Components.ID("{d24d491f-820f-4d4d-b71f-900df0347aea}");
  }
  get contractID() {
    return "@camoufox.org/observer;1";
  }
  get QueryInterface() {
    return ChromeUtils.generateQI(["nsIObserver"]);
  }
  observe() {}
}
