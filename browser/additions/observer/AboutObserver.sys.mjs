// about:observer, registered at runtime and only when the observer is armed
// (TrackingObserver.sys.mjs register()), so a disarmed browser has no such name.
// The page is an unprivileged file served from resource://gre/modules/, a host
// every Firefox registers; the actor pair feeds it from the parent's Collector.
const PAGE = "resource://gre/modules/AboutObserver.html";

const aboutModule = {
  QueryInterface: ChromeUtils.generateQI(["nsIAboutModule"]),
  getURIFlags() {
    return Ci.nsIAboutModule.ALLOW_SCRIPT | Ci.nsIAboutModule.HIDE_FROM_ABOUTABOUT;
  },
  newChannel(uri, loadInfo) {
    const channel = Services.io.newChannelFromURIWithLoadInfo(
      Services.io.newURI(PAGE),
      loadInfo
    );
    channel.originalURI = uri;
    return channel;
  },
  getChromeURI() {
    return Services.io.newURI(PAGE);
  },
};

export function registerAboutObserver() {
  Components.manager.QueryInterface(Ci.nsIComponentRegistrar).registerFactory(
    Components.ID("{6c9e8b0a-7b44-4a3e-9f6a-2d5b1f0c8e11}"),
    "about:observer",
    "@mozilla.org/network/protocol/about;1?what=observer",
    {
      QueryInterface: ChromeUtils.generateQI(["nsIFactory"]),
      createInstance(iid) {
        return aboutModule.QueryInterface(iid);
      },
    }
  );

  const { ActorManagerParent } = ChromeUtils.importESModule(
    "resource://gre/modules/ActorManagerParent.sys.mjs"
  );
  ActorManagerParent.addJSWindowActors({
    AboutObserver: {
      parent: { esModuleURI: "resource://gre/modules/AboutObserverParent.sys.mjs" },
      child: {
        esModuleURI: "resource://gre/modules/AboutObserverChild.sys.mjs",
        events: { DOMContentLoaded: {} },
      },
      matches: ["about:observer"],
    },
  });
}
