# Tracking Observer — Step 1 (infra + canvas) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the full tracking-observer pipeline end-to-end with a single surface (canvas), proving the hard plumbing + the two anti-detection guardrails (timing-parity, chrome-XSS-safe panel) before any other surface is wired.

**Architecture:** Content-process C++ pushes a context-carrying record into a thread-safe, allocation-free ring buffer at the canvas DOM-op boundary (no IPC/observer on the read path → timing-safe, OMT-safe). A `profile-after-change` component registers, once per process, a JSWindowActor that drains the buffer on a timer and forwards batches to a parent-process memory-only Collector via native actor messaging; a read-only `http-on-modify-request` NetHook feeds the same Collector. A non-content-accessible `chrome://camoufox` panel tab renders live per-`(site,userContextId)` rows using `textContent` under a strict CSP.

**Tech Stack:** Firefox 152.0.4 (Gecko) C++, `additions/camoucfg` (header + source, compiled into xul), JSWindowActor (`resource://gre/modules/ActorManagerParent.sys.mjs`), XPCOM `profile-after-change` component (juggler model), chrome:// jar packaging, plain HTML/JS panel, Node for pure-logic unit tests, clang for the standalone C++ ring-buffer test.

## Global Constraints

- **Source tree is generated.** Never edit `camoufox-*/` directly; all browser-behavior changes persist as `patches/*.patch` or `additions/` files. (CLAUDE.md)
- **Patch method (established in this repo's history):** to change a `.patch`, reconstruct the post-prereq tree (apply prereqs in basename order via the rehearse harness), edit files, `diff -u -L a/<rel> -L b/<rel>` → hunks, prepend `diff --git a/<rel> b/<rel>` (+ `new file mode 100644` on creations), **no `index` lines on edit hunks** (all-zero index → gpatch treats as create → silent no-op). Editing an `additions/` file needs NO patch (it is copied into the tree) — just a rebuild.
- **Rehearsal gate (per touched patch):** `FETCH="curl -fsSL" CAMOU_PATCH=gpatch /opt/homebrew/bin/bash scripts/rehearse-patch.sh <patch-basename>` must report `rc=0 rejects=0 skipped=0 wrongpath=0 fuzz=0 max|offset|=0`.
- **Toolchain:** bash 5 at `/opt/homebrew/bin/bash` (assoc arrays); GNU patch `gpatch`; FF pin `version=152.0.4` (`upstream.sh`).
- **Build reality:** cold `./mach build` ~40 min, incremental ~5 min; macOS CI ~5 h. Prefer local incremental builds; use CI only for cross-platform compile confirmation.
- **Evidence in every PR** (command output + exit status), never a success claim without output. (CLAUDE.md)
- **Default build inert:** with the observer disarmed, the fingerprint read hot path must be byte-identical to today and register no actor/observer/panel. This is a tested requirement, not an afterthought.
- **Emit hot path:** O(1) ring-buffer push only — no allocation, no IPC, no observer-service, no main-thread dispatch. All cross-process/JS/serialize work happens on the async drain.
- **Panel:** every captured string (host/url/site) rendered via `document.createElement`+`textContent` only — never `innerHTML`/interpolation. Strict CSP, no inline, no eval.
- **NetHook read-only:** never `setRequestHeader`/`cancel`/`redirectTo`; request headers + ordering byte-identical armed vs disarmed.
- **Attribution granularity = `(site=eTLD+1, userContextId)`**, carried in the emit from C++, never reconstructed in JS. Panel labels it "site", not "origin".

---

## File Structure

- `additions/camoucfg/AccessObserver.hpp` (new) — public API: `SurfaceId` enum, `AccessObserver::Record(...)`, `AccessObserver::DrainJSON(...)`, `AccessObserver::IsArmed()`.
- `additions/camoucfg/AccessObserver.cpp` (new) — ring-buffer storage + mutex + armed-flag (cached once).
- `additions/camoucfg/moz.build` (modify) — add `AccessObserver.cpp` to `SOURCES`, `AccessObserver.hpp` to `EXPORTS`.
- `additions/camoucfg/test_access_observer.cpp` (new) — standalone clang unit test for the ring buffer (not built into xul).
- `patches/canvas-spoofing.patch` (modify) — add the `AccessObserver::Record(...)` emit at canvas readback boundaries.
- `additions/observer/TrackingObserver.sys.mjs` (new) — the `profile-after-change` component: registers actor, NetHook, Collector; opens panel on operator gesture.
- `additions/observer/components.conf` (new) + `additions/observer/moz.build` (new) — XPCOM registration (juggler model).
- `additions/observer/TrackingObserverChild.sys.mjs` (new) — JSWindowActor child: timer-drains the ring buffer, batches, `sendAsyncMessage`.
- `additions/observer/TrackingObserverParent.sys.mjs` (new) — JSWindowActor parent: forwards batches to Collector.
- `additions/observer/Collector.sys.mjs` (new) — memory-only per-`(site,userContextId)` store + broadcast. Pure logic, node-testable.
- `additions/observer/Collector.test.mjs` (new) — node unit test for grouping/counts.
- `additions/observer/NetHook.sys.mjs` (new) — read-only `http-on-modify-request` observer.
- `additions/observer/content/tracking.html` + `tracking.js` (new) — panel.
- `additions/observer/content/tracking.test.mjs` (new) — node/jsdom escaping test.
- `additions/observer/jar.mn` (new) — `% content camoufox %content/` (NOT content-accessible).
- `copy-additions.sh` (modify) — copy `additions/observer/` into the tree + hook its `moz.build` into the build graph.
- `build-tester/` probe pages (new, under the plan's test dir) — canvas emit + timing-parity + nethook-parity.

Wiring note: the `additions/observer/` subtree is copied into the FF source by `scripts/copy-additions.sh`; its `moz.build` must be referenced from a parent `moz.build` that the build already descends into (mirror how `additions/camoucfg/moz.build` and `additions/juggler` get pulled in — read those before wiring).

---

### Task 1: AccessObserver ring buffer (pure C++, standalone-testable)

**Files:**
- Create: `additions/camoucfg/AccessObserver.hpp`
- Create: `additions/camoucfg/AccessObserver.cpp`
- Create: `additions/camoucfg/test_access_observer.cpp`
- Modify: `additions/camoucfg/moz.build`

**Interfaces:**
- Produces:
  - `enum class SurfaceId : uint16_t { Canvas=1, WebGL=2, WebRTC=3, Navigator=4, Screen=5, Fonts=6, Audio=7 };`
  - `void AccessObserver::Record(uint32_t userContextId, const std::string& site, SurfaceId surface, uint64_t tsMillis);`
  - `bool AccessObserver::IsArmed();`  // cached once from env `CAMOU_OBSERVE` (compile-time flag added in Task 9)
  - `std::string AccessObserver::DrainJSON();`  // pops all records, returns a JSON array string `[{"u":<uctx>,"s":"<site>","f":<surface>,"t":<ts>},...]`, empty `[]` if none

- [ ] **Step 1: Write the failing standalone test**

`additions/camoucfg/test_access_observer.cpp`:
```cpp
// Standalone unit test — NOT compiled into xul. Build with:
//   clang++ -std=c++17 -DCAMOU_OBSERVE_TEST test_access_observer.cpp AccessObserver.cpp -o /tmp/aotest
#include "AccessObserver.hpp"
#include <cassert>
#include <cstdio>
#include <string>
using namespace camoufox;

int main() {
  // Force-arm for the test regardless of env.
  AccessObserver::ForceArmForTest(true);

  // Empty drain is a valid empty array.
  assert(AccessObserver::DrainJSON() == "[]");

  // One record round-trips with all fields.
  AccessObserver::Record(2, "facebook.com", SurfaceId::Canvas, 1000);
  std::string j = AccessObserver::DrainJSON();
  assert(j.find("\"u\":2") != std::string::npos);
  assert(j.find("\"s\":\"facebook.com\"") != std::string::npos);
  assert(j.find("\"f\":1") != std::string::npos);
  assert(j.find("\"t\":1000") != std::string::npos);

  // Drain clears: second drain is empty.
  assert(AccessObserver::DrainJSON() == "[]");

  // Overflow is bounded and lossy-newest-dropped, never a crash or OOB.
  for (int i = 0; i < 100000; ++i)
    AccessObserver::Record(1, "x.com", SurfaceId::WebGL, i);
  std::string big = AccessObserver::DrainJSON();
  assert(!big.empty() && big.front() == '[' && big.back() == ']');
  assert(AccessObserver::DrainJSON() == "[]");

  // Disarmed => Record is a no-op.
  AccessObserver::ForceArmForTest(false);
  AccessObserver::Record(2, "facebook.com", SurfaceId::Canvas, 1);
  AccessObserver::ForceArmForTest(true);
  assert(AccessObserver::DrainJSON() == "[]");

  // Site with a double-quote is JSON-escaped (defense in depth).
  AccessObserver::Record(0, "a\"b.com", SurfaceId::Fonts, 5);
  std::string esc = AccessObserver::DrainJSON();
  assert(esc.find("a\\\"b.com") != std::string::npos);

  printf("ALL PASS\n");
  return 0;
}
```

- [ ] **Step 2: Run it to verify it fails to compile (no header yet)**

Run: `clang++ -std=c++17 additions/camoucfg/test_access_observer.cpp -o /tmp/aotest 2>&1 | head`
Expected: FAIL — `'AccessObserver.hpp' file not found`.

- [ ] **Step 3: Write the header**

`additions/camoucfg/AccessObserver.hpp`:
```cpp
#ifndef CAMOUFOX_ACCESS_OBSERVER_HPP
#define CAMOUFOX_ACCESS_OBSERVER_HPP
#include <cstdint>
#include <string>

namespace camoufox {

enum class SurfaceId : uint16_t {
  Canvas = 1, WebGL = 2, WebRTC = 3, Navigator = 4,
  Screen = 5, Fonts = 6, Audio = 7,
};

class AccessObserver {
 public:
  // O(1), allocation-free, thread-safe. No-op when disarmed. Safe off-main-thread.
  static void Record(uint32_t userContextId, const std::string& site,
                     SurfaceId surface, uint64_t tsMillis);
  // Cached once (env CAMOU_OBSERVE; compile-time flag supersedes in Task 9).
  static bool IsArmed();
  // Pops all buffered records as a JSON array string. Main-thread drain path.
  static std::string DrainJSON();
  // Test-only override of the armed flag.
  static void ForceArmForTest(bool armed);
};

}  // namespace camoufox
#endif
```

- [ ] **Step 4: Write the source**

`additions/camoucfg/AccessObserver.cpp`:
```cpp
#include "AccessObserver.hpp"
#include <array>
#include <mutex>
#include <atomic>
#include <cstdlib>

namespace camoufox {
namespace {

struct Record_t {
  uint32_t userContextId;
  uint64_t tsMillis;
  uint16_t surface;
  char site[64];   // POD, fixed — no allocation on the hot path
};

constexpr size_t kCapacity = 4096;

std::mutex gMutex;
std::array<Record_t, kCapacity> gBuf;
size_t gCount = 0;               // number of valid records [0, kCapacity]

std::atomic<int> gForcedArm{-1}; // -1 = use env, 0/1 = forced (test)

void AppendEscaped(std::string& out, const char* s) {
  for (const char* p = s; *p; ++p) {
    if (*p == '"' || *p == '\\') out.push_back('\\');
    out.push_back(*p);
  }
}

}  // namespace

bool AccessObserver::IsArmed() {
  int forced = gForcedArm.load(std::memory_order_relaxed);
  if (forced >= 0) return forced == 1;
  static const bool sArmed = [] {
    const char* v = std::getenv("CAMOU_OBSERVE");
    return v && v[0] && !(v[0] == '0' && v[1] == '\0');
  }();
  return sArmed;
}

void AccessObserver::ForceArmForTest(bool armed) {
  gForcedArm.store(armed ? 1 : 0, std::memory_order_relaxed);
}

void AccessObserver::Record(uint32_t userContextId, const std::string& site,
                            SurfaceId surface, uint64_t tsMillis) {
  if (!IsArmed()) return;
  std::lock_guard<std::mutex> lock(gMutex);
  if (gCount >= kCapacity) return;   // bounded: drop newest, never OOB/crash
  Record_t& r = gBuf[gCount++];
  r.userContextId = userContextId;
  r.tsMillis = tsMillis;
  r.surface = static_cast<uint16_t>(surface);
  size_t n = site.size() < sizeof(r.site) - 1 ? site.size() : sizeof(r.site) - 1;
  for (size_t i = 0; i < n; ++i) r.site[i] = site[i];
  r.site[n] = '\0';
}

std::string AccessObserver::DrainJSON() {
  std::lock_guard<std::mutex> lock(gMutex);
  std::string out = "[";
  for (size_t i = 0; i < gCount; ++i) {
    const Record_t& r = gBuf[i];
    if (i) out.push_back(',');
    out += "{\"u\":";
    out += std::to_string(r.userContextId);
    out += ",\"s\":\"";
    AppendEscaped(out, r.site);
    out += "\",\"f\":";
    out += std::to_string(r.surface);
    out += ",\"t\":";
    out += std::to_string(r.tsMillis);
    out += "}";
  }
  out.push_back(']');
  gCount = 0;
  return out;
}

}  // namespace camoufox
```

- [ ] **Step 5: Build + run the standalone test**

Run: `clang++ -std=c++17 additions/camoucfg/test_access_observer.cpp additions/camoucfg/AccessObserver.cpp -o /tmp/aotest && /tmp/aotest`
Expected: `ALL PASS`.

- [ ] **Step 6: Wire into the xul build**

Modify `additions/camoucfg/moz.build`: add `AccessObserver.cpp` to `SOURCES` and `AccessObserver.hpp` to `EXPORTS` (read the current file first; match its existing `EXPORTS`/`SOURCES`/`FINAL_LIBRARY = "xul"` style). Do NOT add `test_access_observer.cpp` to the build.

- [ ] **Step 7: Commit**

```bash
git add additions/camoucfg/AccessObserver.hpp additions/camoucfg/AccessObserver.cpp \
        additions/camoucfg/test_access_observer.cpp additions/camoucfg/moz.build
git commit -m "feat(observer): thread-safe ring buffer + JSON drain (AccessObserver)"
```

---

### Task 2: Canvas emit at the readback boundary

**Files:**
- Modify: `patches/canvas-spoofing.patch` (the canvas hook sites already present from Task 7 of the prior effort)
- Test: `build-tester/observer/canvas_emit_probe.js` (new probe)

**Interfaces:**
- Consumes: `camoufox::AccessObserver::Record`, `SurfaceId::Canvas` (Task 1).
- Produces: canvas readback (`toDataURL`/`getImageData`/`readPixels`) pushes one record per JS-observable op carrying `(userContextId, site)` from the owning document.

- [ ] **Step 1: Reconstruct the post-prereq canvas tree**

Run the rehearse harness so `.rehearse/canvas-spoofing.patch/tree` holds the post-prereq + canvas-applied tree, then reverse-apply current canvas to get the clean post-prereq base (this repo's established recovery method):
```
FETCH="curl -fsSL" CAMOU_PATCH=gpatch /opt/homebrew/bin/bash scripts/rehearse-patch.sh canvas-spoofing.patch
```
Expected: `rc=0 rejects=0 skipped=0 wrongpath=0 fuzz=0 max|offset|=0` (baseline before edit).

- [ ] **Step 2: Add the emit at each canvas readback site**

At the three existing perturbation sites in `dom/canvas/CanvasRenderingContext2D.cpp` (`GetImageBuffer`, `GetImageDataArray`) and `dom/canvas/ClientWebGLContext.cpp` (`ReadPixels`), where `seedDoc`/the owning `Document*` is already resolved (`CanvasSeedDocumentFor(...)`), add — BEFORE the perturbation `if` — one emit. The userContextId is already obtained as in the seed path; the site comes from the document's node principal base domain. Exact expression to use (verify the principal accessor against the post-prereq tree's `mozilla::dom::Document` / `nsIPrincipal` before finalizing):
```cpp
// Camoufox tracking-observer: record the read (no-op when disarmed).
if (camoufox::AccessObserver::IsArmed() && seedDoc) {
  uint32_t uctx = 0;
  nsAutoCString baseDomain;
  if (nsIPrincipal* p = seedDoc->NodePrincipal()) {
    p->GetBaseDomain(baseDomain);
    mozilla::OriginAttributes oa = p->OriginAttributesRef();
    uctx = oa.mUserContextId;
  }
  camoufox::AccessObserver::Record(
      uctx, std::string(baseDomain.get()),
      camoufox::SurfaceId::Canvas,
      static_cast<uint64_t>(PR_Now() / 1000));
}
```
Add `#include "AccessObserver.hpp"` near the existing `#include "MaskConfig.hpp"` in each file, and ensure `nsIPrincipal.h` is included (it usually is transitively via `Document.h`; add if the build says otherwise). Regenerate the patch hunks with the repo's `diff -u` method (no `index` lines).

- [ ] **Step 3: Rehearse the modified patch**

Run: `FETCH="curl -fsSL" CAMOU_PATCH=gpatch /opt/homebrew/bin/bash scripts/rehearse-patch.sh canvas-spoofing.patch`
Expected: `rc=0 rejects=0 skipped=0 wrongpath=0 fuzz=0 max|offset|=0`.

- [ ] **Step 4: Add a temporary stderr drain to prove the emit (removed in Task 3)**

For this task only, in `AccessObserver::Record` add — behind `IsArmed()` — a `#ifdef CAMOU_OBSERVE_STDERR` `printf_stderr("FPACCESS %u %s %u\n", ...)`. Build with that define. (Delete in Task 3 once the real drain exists.)

- [ ] **Step 5: Build + runtime probe**

Build: `make dir && make build` (incremental after first). Probe page `canvas_emit_probe.js` calls `document.createElement('canvas').getContext('2d')...toDataURL()`.
Run with `CAMOU_OBSERVE=1` against the built binary via build-tester (`python scripts/run_tests.py /path/to/camoufox-bin` with the probe added).
Expected: stderr shows one `FPACCESS` line with `surface=1` (Canvas) and the probe page's site + the context's userContextId; visiting with the env unset → no line.

- [ ] **Step 6: Commit**

```bash
git add patches/canvas-spoofing.patch additions/camoucfg/AccessObserver.cpp build-tester/observer/canvas_emit_probe.js
git commit -m "feat(observer): emit canvas readback access records with site+userContextId"
```

---

### Task 3: Registration component + JSWindowActor drain → parent log

**Files:**
- Create: `additions/observer/TrackingObserver.sys.mjs`, `components.conf`, `moz.build`
- Create: `additions/observer/TrackingObserverChild.sys.mjs`, `TrackingObserverParent.sys.mjs`
- Modify: `scripts/copy-additions.sh` (copy `additions/observer/` + wire moz.build)
- Modify: `additions/camoucfg/AccessObserver.cpp` (remove Task 2's temporary stderr drain)

**Interfaces:**
- Consumes: `AccessObserver::DrainJSON` (Task 1) — exposed to JS via `ChromeUtils` binding or a tiny XPCOM shim (see Step 2).
- Produces: actor message `"camoufox-observer:batch"` with payload `{records:[{u,s,f,t}], _from:"content"}` delivered to `TrackingObserverParent.receiveMessage`.

- [ ] **Step 1: Expose `DrainJSON` to chrome JS**

The content actor (privileged JS) needs to pull the C++ ring buffer. Add a `ChromeUtils` static (mirror how camoufox exposes `ChromeUtils.camouGetBool`/`camouGetStringList` — grep `camouGet` to find the WebIDL + impl site) named `ChromeUtils.camouDrainAccessRecords()` returning the JSON string from `AccessObserver::DrainJSON()`. Read the existing `camouGet*` binding before adding; follow it exactly.

- [ ] **Step 2: Write the `profile-after-change` component (registers once per process)**

`additions/observer/TrackingObserver.sys.mjs` — modeled on `additions/juggler/components/Juggler.js` + `components.conf` (`profile-after-change`). At construction: register the JSWindowActor pair via `ActorManagerParent.addJSWindowActors({ CamoufoxObserver: { parent:{esModuleURI:...Parent...}, child:{esModuleURI:...Child..., events:{DOMWindowCreated:{}}} } })`; instantiate the Collector (Task 4) and NetHook (Task 5) — stubs acceptable in this task. Guard the whole body behind the armed check (env for now; compile-time in Task 9) so the default profile registers nothing.

`additions/observer/components.conf`: register `{ 'cid': '{<new-uuid>}', 'contract_ids': ['@camoufox.org/observer;1'], 'esModule': '.../TrackingObserver.sys.mjs', 'constructor': 'TrackingObserver', 'categories': { 'profile-after-change': 'TrackingObserver' } }`. Generate a fresh UUID.

- [ ] **Step 3: Write the actor child (timer drain) + parent (log)**

`TrackingObserverChild.sys.mjs`:
```js
export class TrackingObserverChild extends JSWindowActorChild {
  actorCreated() {
    // Low-frequency drain keeps all IPC/serialize off the fingerprint read path.
    this._timer = this.contentWindow.setInterval(() => this._drain(), 500);
  }
  didDestroy() { if (this._timer) this.contentWindow.clearInterval(this._timer); }
  _drain() {
    let json = ChromeUtils.camouDrainAccessRecords();  // "[]" when empty
    if (json === "[]") return;
    let records;
    try { records = JSON.parse(json); } catch { return; }
    if (records.length) this.sendAsyncMessage("camoufox-observer:batch", { records });
  }
}
```
`TrackingObserverParent.sys.mjs`:
```js
export class TrackingObserverParent extends JSWindowActorParent {
  receiveMessage(msg) {
    if (msg.name !== "camoufox-observer:batch") return;
    // Task 4 replaces this with Collector.ingestAccess(...).
    dump(`[camoufox-observer] batch ${msg.data.records.length}\n`);
  }
}
```

- [ ] **Step 4: Wire copy-additions + remove the temporary stderr drain**

Modify `scripts/copy-additions.sh` to copy `additions/observer/` into the tree and reference its `moz.build` (mirror the juggler copy). Remove Task 2's `#ifdef CAMOU_OBSERVE_STDERR` block from `AccessObserver.cpp`.

- [ ] **Step 5: Build + runtime verify the drain reaches the parent**

Build, run with `CAMOU_OBSERVE=1`, browse the canvas probe page. In the Browser Console (parent `dump` output / stdout) expect `[camoufox-observer] batch N` within ~0.5s of the canvas read; env unset → no registration, no batches.

- [ ] **Step 6: Commit**

```bash
git add additions/observer scripts/copy-additions.sh additions/camoucfg/AccessObserver.cpp
git commit -m "feat(observer): profile-after-change registration + JSActor timer-drain to parent"
```

---

### Task 4: Collector (memory-only, pure logic, node-tested)

**Files:**
- Create: `additions/observer/Collector.sys.mjs`, `additions/observer/Collector.test.mjs`
- Modify: `additions/observer/TrackingObserverParent.sys.mjs`, `TrackingObserver.sys.mjs`

**Interfaces:**
- Produces:
  - `class Collector { ingestAccess(userContextId, site, surface, ts); ingestNet(userContextId, site, host, url, method, ts); snapshot() → [{key:{site,userContextId}, surfaces:{<id>:count}, requests:[{host,url,method,ts}]}]; subscribe(fn); clear(); }`
  - Memory-only; nothing written to disk/console/profile.

- [ ] **Step 1: Write the failing node test**

`additions/observer/Collector.test.mjs`:
```js
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
```

- [ ] **Step 2: Run it to verify it fails**

Run: `node additions/observer/Collector.test.mjs`
Expected: FAIL — cannot find `Collector.sys.mjs`.

- [ ] **Step 3: Implement the Collector**

`additions/observer/Collector.sys.mjs`:
```js
export class Collector {
  constructor(maxRequestsPerKey = 500) {
    this._rows = new Map();        // "site uctx" -> row
    this._subs = new Set();
    this._cap = maxRequestsPerKey;
  }
  _key(site, u) { return `${site} ${u}`; }
  _row(site, u) {
    const k = this._key(site, u);
    let r = this._rows.get(k);
    if (!r) { r = { key: { site, userContextId: u }, surfaces: {}, requests: [] }; this._rows.set(k, r); }
    return r;
  }
  ingestAccess(u, site, surface, ts) {
    const r = this._row(site, u);
    r.surfaces[surface] = (r.surfaces[surface] || 0) + 1;
    r.lastTs = ts; this._emit();
  }
  ingestNet(u, site, host, url, method, ts) {
    const r = this._row(site, u);
    r.requests.push({ host, url, method, ts });
    if (r.requests.length > this._cap) r.requests.shift();  // bounded, memory-only
    r.lastTs = ts; this._emit();
  }
  snapshot() { return [...this._rows.values()]; }
  subscribe(fn) { this._subs.add(fn); return () => this._subs.delete(fn); }
  clear() { this._rows.clear(); this._emit(); }
  _emit() { for (const fn of this._subs) { try { fn(); } catch {} } }
}
```

- [ ] **Step 4: Run it to verify it passes**

Run: `node additions/observer/Collector.test.mjs`
Expected: `COLLECTOR PASS`.

- [ ] **Step 5: Wire Collector into the component + parent actor**

In `TrackingObserver.sys.mjs` construct one `Collector` and pass it to the actor parent registration (via `sharedData` or a module singleton). In `TrackingObserverParent.receiveMessage`, replace the `dump` with `for (const rec of msg.data.records) this._collector.ingestAccess(rec.u, rec.s, rec.f, rec.t)`.

- [ ] **Step 6: Commit**

```bash
git add additions/observer/Collector.sys.mjs additions/observer/Collector.test.mjs \
        additions/observer/TrackingObserverParent.sys.mjs additions/observer/TrackingObserver.sys.mjs
git commit -m "feat(observer): memory-only Collector with (site,userContextId) grouping"
```

---

### Task 5: NetHook (read-only) + request-parity test

**Files:**
- Create: `additions/observer/NetHook.sys.mjs`
- Modify: `additions/observer/TrackingObserver.sys.mjs`
- Test: `build-tester/observer/nethook_parity_probe.js`

**Interfaces:**
- Consumes: `Collector.ingestNet` (Task 4).
- Produces: on each `http-on-modify-request`, calls `ingestNet(userContextId, topSite, host, url, method, ts)`; never mutates the channel.

- [ ] **Step 1: Implement the read-only observer**

`additions/observer/NetHook.sys.mjs`:
```js
export class NetHook {
  constructor(collector) { this._c = collector; }
  start() { Services.obs.addObserver(this, "http-on-modify-request"); }
  stop() { Services.obs.removeObserver(this, "http-on-modify-request"); }
  observe(subject) {
    let ch;
    try { ch = subject.QueryInterface(Ci.nsIHttpChannel); } catch { return; }
    // READ ONLY. Never setRequestHeader/cancel/redirectTo here.
    const li = ch.loadInfo;
    const u = li?.originAttributes?.userContextId ?? 0;
    const host = ch.URI.host;
    // Top site: walk to the top browsing context's document principal.
    let site = host;
    try {
      const top = li.browsingContext?.top?.currentWindowGlobal?.documentPrincipal;
      if (top) site = top.baseDomain || site;
    } catch {}
    this._c.ingestNet(u, site, host, ch.URI.spec, ch.requestMethod, Date.now());
  }
}
```

- [ ] **Step 2: Start it from the component (armed only)**

In `TrackingObserver.sys.mjs`, when armed, `this._netHook = new NetHook(this._collector); this._netHook.start();`.

- [ ] **Step 3: Write the parity probe**

`build-tester/observer/nethook_parity_probe.js`: from the page, `performance.getEntriesByType('resource')` for a fixed set of subresource fetches, plus capture the outgoing request headers via a controlled echo endpoint. The test compares two runs (env armed vs unset) and asserts identical request headers + identical resource-entry ordering.

- [ ] **Step 4: Build + run the parity probe**

Build, then run the probe armed and unarmed.
Expected: request headers byte-identical and resource ordering identical between runs (NetHook is read-only). Collector shows net rows only in the armed run.

- [ ] **Step 5: Commit**

```bash
git add additions/observer/NetHook.sys.mjs additions/observer/TrackingObserver.sys.mjs build-tester/observer/nethook_parity_probe.js
git commit -m "feat(observer): read-only http-on-modify-request NetHook + parity probe"
```

---

### Task 6: chrome://camoufox jar + hardened panel (escaping test)

**Files:**
- Create: `additions/observer/jar.mn`, `additions/observer/content/tracking.html`, `tracking.js`, `additions/observer/content/tracking.test.mjs`
- Modify: `additions/observer/moz.build` (reference the jar)

**Interfaces:**
- Consumes: a snapshot array shaped like `Collector.snapshot()` (Task 4).
- Produces: `renderRows(container, snapshot)` — pure DOM builder using `textContent` only; node/jsdom-testable.

- [ ] **Step 1: Write the failing escaping test**

`additions/observer/content/tracking.test.mjs`:
```js
import assert from "node:assert";
import { JSDOM } from "jsdom";           // dev-only; if unavailable, use a minimal DOM shim
import { renderRows } from "./tracking.js";

const dom = new JSDOM("<div id=root></div>");
const root = dom.window.document.getElementById("root");
const malicious = "<img src=x onerror=alert(1)>";
renderRows(root, [{ key: { site: malicious, userContextId: 0 }, surfaces: { 1: 3 }, requests: [
  { host: malicious, url: "https://" + malicious, method: "GET", ts: 1 } ] }], dom.window.document);

// No element was created from the payload — it is inert text.
assert.equal(root.querySelectorAll("img").length, 0, "no markup injected");
assert.ok(root.textContent.includes(malicious), "payload shown as literal text");
console.log("PANEL ESCAPING PASS");
```

- [ ] **Step 2: Run it to verify it fails**

Run: `node additions/observer/content/tracking.test.mjs`
Expected: FAIL — `tracking.js` / `renderRows` missing.

- [ ] **Step 3: Implement the panel renderer (textContent only)**

`additions/observer/content/tracking.js`:
```js
const SURFACE_NAMES = {1:"canvas",2:"webgl",3:"webrtc",4:"navigator",5:"screen",6:"fonts",7:"audio"};
const HIGHLIGHT = new Set(["facebook.com","instagram.com","threads.net"]);

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
```
`tracking.html` loads `tracking.js`, holds `<div id="rows">`, and (in the browser) subscribes to the Collector and calls `renderRows`. Add the strict CSP as a `<meta http-equiv="Content-Security-Policy" content="default-src 'none'; script-src chrome://camoufox/content/tracking.js; style-src 'self'; object-src 'none'">` AND (belt-and-braces) the same via the jar/manifest if supported.

`additions/observer/jar.mn`:
```
camoufox.jar:
% content camoufox %content/
  content/tracking.html   (content/tracking.html)
  content/tracking.js     (content/tracking.js)
```
(No `contentaccessible=yes` — panel must NOT be web-reachable.)

- [ ] **Step 4: Run it to verify it passes**

Run: `node additions/observer/content/tracking.test.mjs`
Expected: `PANEL ESCAPING PASS`.

- [ ] **Step 5: Add the blind-spot enumeration**

In `tracking.html`, add a static, always-visible "Not observable (reads invisible to this tool)" section listing: timezone, locale/Intl (engine-cached); navigator.vendor, plugins, deviceMemory, userAgentData, enumerateDevices, battery, connection (un-spoofed). This is required so silence is never read as "safe".

- [ ] **Step 6: Commit**

```bash
git add additions/observer/jar.mn additions/observer/content additions/observer/moz.build
git commit -m "feat(observer): non-content-accessible chrome://camoufox panel, textContent+CSP, blind-spot list"
```

---

### Task 7: Live wiring + end-to-end runtime validation

**Files:**
- Modify: `additions/observer/TrackingObserver.sys.mjs` (open panel on gesture; subscribe panel to Collector), `tracking.html` (live subscribe)
- Test: `build-tester/observer/e2e_probe.js`

**Interfaces:**
- Consumes: Collector snapshot + subscribe (Task 4), renderRows (Task 6).

- [ ] **Step 1: Wire panel ↔ Collector**

Add a way for `tracking.html` (chrome page) to reach the parent Collector singleton (module import of the component's singleton, or `Services.obs` broadcast of snapshot deltas the page subscribes to). On each Collector `_emit`, push `snapshot()` to any open panel; the panel calls `renderRows`. Add a gesture to open the panel (e.g. a menu item added in `browser-init.js` guarded by armed — the ONLY window-side hook).

- [ ] **Step 2: Build + end-to-end probe**

Build. With `CAMOU_OBSERVE=1`, open the panel, visit a canvas-fingerprinting tester and facebook.com.
Expected: a `facebook.com [ctx N]` row appears with `canvas:>=1` and `>=1 req`; the canvas tester's site appears with its canvas count; the blind-spot list is visible; env unset → panel cannot be opened / stays empty.

- [ ] **Step 3: Rehearse all touched patches + confirm default-inert**

Run rehearsal on every modified patch (`canvas-spoofing.patch`) → all-zero gate. Build with env unset and confirm: no actor registered, no `http-on-modify-request` observer, panel unopenable.

- [ ] **Step 4: Commit**

```bash
git add additions/observer build-tester/observer/e2e_probe.js patches/canvas-spoofing.patch
git commit -m "feat(observer): live panel wiring + end-to-end canvas+network validation"
```

---

### Task 8: Timing-parity test (the anti-detection gate)

**Files:**
- Test: `build-tester/observer/timing_parity_probe.js`

**Interfaces:**
- Consumes: the built binary, armed and unarmed.

- [ ] **Step 1: Write the timing probe**

`timing_parity_probe.js`: time a tight loop of the instrumented op (`canvas.toDataURL()` ×N, and `gl.getParameter` ×N once webgl lands) with `performance.now()`, collect median + p95 + variance over many trials; output JSON.

- [ ] **Step 2: Measure armed vs unarmed**

Run the probe against the same binary with `CAMOU_OBSERVE=1` and unset (≥ 5 runs each).
Expected: armed median/p95/variance for canvas readback within measurement noise of unarmed (define the threshold empirically from the unarmed run-to-run spread; armed must not exceed unarmed's own inter-run band). If armed is measurably slower/higher-variance, the hot path is doing too much — fix Task 1/2 (the emit must be push-only) before proceeding.

- [ ] **Step 3: Record evidence + commit**

Capture the JSON from both conditions into the commit/PR body as the anti-detection evidence.
```bash
git add build-tester/observer/timing_parity_probe.js
git commit -m "test(observer): timing-parity probe — armed readback within noise of unarmed"
```

---

### Task 9: Compile-time gate (default binary contains zero instrumentation)

**Files:**
- Modify: `assets/base.mozconfig` (or the mozconfig writer in `scripts/patch.py`), `additions/camoucfg/AccessObserver.cpp/.hpp`, the canvas emit, `TrackingObserver.sys.mjs`

**Interfaces:**
- Produces: `MOZ_CAMOU_OBSERVE` build flag; when undefined, `AccessObserver::Record` compiles to empty and no observer JS registers.

- [ ] **Step 1: Add the build flag**

Add `MOZ_CAMOU_OBSERVE` to the mozconfig only for observe builds (read how existing camoufox flags are threaded into `MOZ_*` defines). Wrap the C++ ring buffer body and the canvas emit in `#ifdef MOZ_CAMOU_OBSERVE` (declaration stays; body no-ops without it). Gate the component registration on a pref/flag that is compiled out of default builds.

- [ ] **Step 2: Verify both build variants**

Build WITHOUT the flag: confirm `AccessObserver::Record` is empty (no ring buffer symbol / no `getenv`) and the fingerprint hot path is byte-identical to pre-feature (compare disassembly of `GetImageBuffer` or diff the preprocessed TU). Build WITH the flag + `CAMOU_OBSERVE=1`: Task 7 e2e still passes.
Expected: default build inert (no instrumentation present); observe build works.

- [ ] **Step 3: Commit**

```bash
git add assets/base.mozconfig additions/camoucfg additions/observer patches/canvas-spoofing.patch
git commit -m "feat(observer): compile-time MOZ_CAMOU_OBSERVE gate — default binary inert"
```

---

### Task 10: Docs + PR evidence

**Files:**
- Create: `docs/observer/README.md`
- Modify: PR body

- [ ] **Step 1: Write operator docs**

`docs/observer/README.md`: how to build the observe variant, run with `CAMOU_OBSERVE=1`, open the panel, read the per-site rows; **explicitly document** that (a) attribution is site-level, (b) engine-cached + un-spoofed surfaces are blind spots (listed), and (c) observe-mode with the runtime env may be timing-detectable — prefer the compile-time observe build and treat observe-mode as an audit tool, not a stealth mode.

- [ ] **Step 2: Assemble PR evidence**

Collect into the PR body: standalone ring-buffer test `ALL PASS`; `node Collector.test.mjs` + `tracking.test.mjs` output; rehearsal all-zero for `canvas-spoofing.patch`; CI `Build` green (mac + win); e2e probe screenshot/log; timing-parity JSON (armed within noise); nethook-parity (headers identical). Open the PR tied to a GitHub issue per CONTRIBUTING.md, `--repo lang315/camoufox`.

- [ ] **Step 3: Commit + open PR**

```bash
git add docs/observer/README.md
git commit -m "docs(observer): operator guide + blind-spot/detectability caveats"
```

---

## Self-Review

**Spec coverage:** ring buffer + emit (T1–2) ✓; profile-after-change registration + native JSActor (T3) ✓; memory-only Collector + site,userContextId join (T4) ✓; read-only NetHook + top-site walk (T5) ✓; chrome jar + textContent/CSP panel + blind-spot enumeration (T6) ✓; live wiring/e2e (T7) ✓; timing-parity (T8) ✓; compile-time gate/default-inert (T9) ✓; docs/detectability caveats (T10) ✓. Surfaces webgl/webrtc/fonts/navigator/screen/audio, engine-cached, un-spoofed, and Phase-2 bodies are explicitly out of Step 1 → follow-on plans.

**Placeholder scan:** pure-logic pieces (ring buffer, Collector, panel renderer, all tests) ship complete code. Gecko-integrated expressions (canvas principal accessor, `camouGet*` binding, mozconfig flag threading) point to the exact existing pattern to read and copy rather than a fabricated snippet — deliberate, because inventing exact Gecko/patch expressions blind is this project's known failure mode (all-zero index, nsCString). Each such step carries a concrete verification gate (rehearsal / build / runtime probe).

**Type consistency:** `Record(userContextId, site, surface, ts)` / `DrainJSON` (T1) consumed unchanged in T2/T3; `ingestAccess(u,site,surface,ts)` / `ingestNet(u,site,host,url,method,ts)` / `snapshot()` shape (T4) consumed identically in T5/T6/T7; `renderRows(container, snapshot, doc)` (T6) consumed in T7; message name `"camoufox-observer:batch"` consistent T3↔T4; `SurfaceId::Canvas==1` consistent across C++ + `SURFACE_NAMES`.
