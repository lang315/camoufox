// Surface ids from the AccessObserver enum (additions/camoucfg/AccessObserver.hpp).
const SURFACES = {
  1: "canvas", 2: "webgl", 3: "webrtc", 4: "navigator", 5: "screen", 6: "fonts", 7: "audio",
};

export class AboutObserverChild extends JSWindowActorChild {
  handleEvent(event) {
    if (event.type !== "DOMContentLoaded") return;
    this._refresh();
    this.contentWindow.setInterval(() => this._refresh(), 1000);
  }

  async _refresh() {
    let rows;
    try {
      rows = await this.sendQuery("camoufox-observer:snapshot");
    } catch {
      return;
    }
    const doc = this.document;
    doc.getElementById("raw").textContent = JSON.stringify(rows, null, 2);
    const tbody = doc.getElementById("rows");
    tbody.replaceChildren();
    for (const row of rows) {
      const tr = doc.createElement("tr");
      const surfaces = Object.keys(row.surfaces).map(id => SURFACES[id] ?? id).join(", ");
      for (const text of [row.key.site, row.key.userContextId, surfaces]) {
        tr.appendChild(doc.createElement("td")).textContent = text;
      }
      const td = tr.appendChild(doc.createElement("td"));
      const details = td.appendChild(doc.createElement("details"));
      details.appendChild(doc.createElement("summary")).textContent = row.requests.length;
      for (const req of row.requests) {
        details.appendChild(doc.createElement("pre")).textContent = JSON.stringify(req);
      }
      tbody.appendChild(tr);
    }
  }
}
