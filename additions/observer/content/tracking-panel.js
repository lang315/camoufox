import { renderRows } from "./tracking.js";

const { getCollector } = ChromeUtils.importESModule(
  "resource://gre/modules/TrackingObserver.sys.mjs"
);

function refresh() {
  const c = getCollector();
  if (c) renderRows(document.getElementById("rows"), c.snapshot(), document);
}

const obs = { observe: refresh };
Services.obs.addObserver(obs, "camoufox-observer:update");
window.addEventListener("unload", () => Services.obs.removeObserver(obs, "camoufox-observer:update"));
refresh();
