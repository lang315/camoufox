import { Collector } from "./Collector.sys.mjs";
import { NetHook } from "./NetHook.sys.mjs";

// Env-based arm switch for now; Task 9 replaces this with a compile-time
// build flag so a default (unarmed) profile registers nothing. Mirrors
// AccessObserver::IsArmed() in additions/camoucfg/AccessObserver.cpp.
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

  ActorManagerParent.addJSWindowActors({
    CamoufoxObserver: {
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
