import assert from "node:assert";
import { renderRows } from "./tracking.js";

// Minimal DOM shim for Node.js testing (no jsdom dependency)
class MinimalElement {
  constructor(tag) {
    this.tag = tag;
    this.className = "";
    this.children = [];
    this._textContent = "";
  }

  set textContent(value) {
    this._textContent = value;
    this.children = [];
  }

  get textContent() {
    if (this._textContent) return this._textContent;
    return this.children.map(c => c.textContent).join("");
  }

  appendChild(child) {
    this.children.push(child);
  }

  querySelectorAll(selector) {
    const results = [];
    const walk = (el) => {
      if (el.tag === selector.replace(/^\.|#/, "")) {
        results.push(el);
      }
      for (const child of el.children) {
        walk(child);
      }
    };
    walk(this);
    return results;
  }
}

class MinimalDocument {
  createElement(tag) {
    return new MinimalElement(tag);
  }

  getElementById(id) {
    return new MinimalElement("div");
  }
}

const doc = new MinimalDocument();
const root = doc.getElementById("root");

const malicious = "<img src=x onerror=alert(1)>";
renderRows(root, [
  {
    key: { site: malicious, userContextId: 0 },
    surfaces: { 1: 3 },
    requests: [{ host: malicious, url: "https://" + malicious, method: "GET", ts: 1 }]
  }
], doc);

// No element was created from the payload — it is inert text.
assert.equal(root.querySelectorAll("img").length, 0, "no markup injected");
assert.ok(root.textContent.includes(malicious), "payload shown as literal text");
console.log("PANEL ESCAPING PASS");
