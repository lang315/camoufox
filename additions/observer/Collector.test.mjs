import assert from "node:assert";
import { Collector } from "./Collector.sys.mjs";

const c = new Collector();
c.ingestAccess(2, "facebook.com", 1, 1000);
c.ingestAccess(2, "facebook.com", 1, 1001);   // same key+surface → count 2
c.ingestAccess(2, "facebook.com", 2, 1002);   // webgl → separate count
c.ingestAccess(0, "facebook.com", 1, 1003);   // different userContextId → separate row
c.ingestNet(2, "facebook.com", "graph.facebook.com", "https://graph.facebook.com/x", "POST", 1004);

const snap = c.snapshot();
const fb2 = snap.find(r => r.key.site === "facebook.com" && r.key.userContextId === 2);
assert.equal(fb2.surfaces[1], 2, "canvas counted per read");
assert.equal(fb2.surfaces[2], 1, "webgl counted");
assert.equal(fb2.requests.length, 1, "net request grouped by (site,userContextId)");
assert.equal(snap.filter(r => r.key.site === "facebook.com").length, 2, "userContextId splits rows");

let fired = 0; c.subscribe(() => fired++);
c.ingestAccess(2, "facebook.com", 1, 1005);
assert.ok(fired >= 1, "subscribers notified on ingest");

c.clear();
assert.equal(c.snapshot().length, 0, "clear wipes memory");
console.log("COLLECTOR PASS");
