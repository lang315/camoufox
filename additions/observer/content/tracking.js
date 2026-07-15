// Mirrors the SurfaceId enum in additions/camoucfg/AccessObserver.hpp — keep in
// sync when adding a surface (no C++→JS codegen bridge across that boundary).
const SURFACE_NAMES = { 1: "canvas", 2: "webgl", 3: "webrtc", 4: "navigator", 5: "screen", 6: "fonts", 7: "audio" };
const HIGHLIGHT = new Set(["facebook.com", "instagram.com", "threads.net"]);

export function renderRows(container, snapshot, doc = document) {
  container.textContent = "";                     // clear
  for (const row of snapshot) {
    const el = doc.createElement("div");
    el.className = "row" + (HIGHLIGHT.has(row.key.site) ? " highlight" : "");
    const site = doc.createElement("span");
    site.className = "site";
    site.textContent = `${row.key.site} [ctx ${row.key.userContextId}]`;  // textContent — never innerHTML
    el.appendChild(site);
    for (const [id, count] of Object.entries(row.surfaces)) {
      const b = doc.createElement("span");
      b.className = "badge";
      b.textContent = `${SURFACE_NAMES[id] || id}:${count}`;
      el.appendChild(b);
    }
    const net = doc.createElement("span");
    net.className = "net";
    net.textContent = `${row.requests.length} req`;
    el.appendChild(net);
    container.appendChild(el);
  }
}
