# FB Fingerprint Observer — Verify + Recon (Plan A) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Prove the built-in Tracking Observer records fingerprint reads at runtime, then drive it against Facebook's real fingerprinting code (local Meta Pixel/SDK surrogate) to produce a recon report of which surfaces FB consults — and a leak-evidence table that scopes the follow-on spoof work (Plan B).

**Architecture:** A small Python harness under `build-tester/observer/` that arms the *existing* binary with `CAMOU_OBSERVE=1` and drives it via **Marionette** (Firefox's native automation channel, compiled into this ENABLE_WEBDRIVER build). Marionette gives a **chrome-privileged** execution context, so the harness reads the observer's records directly with `getCollector().snapshot()` — the `chrome://camoufox` panel is *not* reachable from a content tab, so panel-scraping does not work; the chrome context is how we read back. No browser rebuild — Plan A runs entirely against the pre-built `cfx_sync4` binary. Plan B (spoofing the confirmed leaks) is deferred and gets its own plan once Task 6 produces the evidence.

**Tech Stack:** Python 3.12, `marionette_driver` (already installed in `build-tester/.venv`), the pre-built `cfx_sync4` Camoufox binary. Playwright is **not** used in Plan A.

## Why Marionette (not Playwright)

Task 1's first implementation attempt (Playwright, chrome:// panel scrape) hit a hard block: **content tabs cannot navigate to `chrome://` at all** — verified against a known Firefox chrome resource, it is categorical, not a misconfiguration; and the panel was built privileged-only (no `contentaccessible=yes`). The records live in the parent-process `Collector`, reachable only from chrome scope. Marionette's `using_context('chrome')` provides exactly that, build-free. This was spiked and proven: a canvas read on an http page produced `{"surfaces":{"1":1,...}}` via `getCollector().snapshot()`, and the same snapshot carried captured network `requests` (the observer's NetHook), including cross-origin ones.

## Global Constraints

- **No browser rebuild in Plan A.** Every task runs against the pre-built binary at `/tmp/cfx_sync4/app/Camoufox.app/Contents/MacOS/camoufox` (override via env `CFX_BIN`). If that path is gone, re-download the beta.28 CI artifact first (out of plan scope).
- **Dependency:** `marionette_driver` (installed in `build-tester/.venv` via `uv pip install`). Add it to `build-tester/requirements.txt`. Run everything with `build-tester/.venv/bin/python`.
- **Observer arming:** set env `CAMOU_OBSERVE=1` *before* Marionette launches the binary (the child inherits `os.environ`). Off/absent/`0` = observer does nothing. Always also set a realistic `CAMOU_CONFIG`, so the spoof getters that host the `Record()` calls are on the live path.
- **Readout:** Marionette chrome context → `ChromeUtils.importESModule("resource://gre/modules/TrackingObserver.sys.mjs").getCollector().snapshot()`. Returns rows `{key:{site,userContextId}, surfaces:{id:count}, requests:[{host,url,method,ts}]}`. Surface ids: `1 canvas, 2 webgl, 3 webrtc, 4 navigator, 5 screen, 6 fonts, 7 audio`.
- **WebGL in headless:** pass `FIREFOX_WEBGL_PREFS = {"webgl.force-enabled": True, "webgl.enable-webgl2": True, "media.peerconnection.ice.obfuscate_host_addresses": False}` as Marionette prefs (spike showed webgl does not record without GL forced on). If `Marionette(prefs=…)` does not apply them, build the profile with `mozprofile` and pass `profile=…`.
- **Facebook target policy:** the local `fbevents.js` + `sdk.js` surrogate is the primary stimulus. At most **one** manual, human-paced, logged-out, no-interaction facebook.com load as a spot-check. **No automated loops against facebook.com.**
- **Honest scope caveat** (verbatim in the Task 6 report): observer sees presence + drain-window count at the JS/WebIDL boundary only — not values/hashes/scoring; blind to TLS/JA3/H2/TCP, WASM, workers/service-workers, pure-CSS `@media`, timing side-channels, server-side scoring. "Silence ≠ not read" for anything unhooked.
- **Cosmetic noise to ignore:** `marionette_driver`'s `__del__` cleanup prints `ImportError: sys.meta_path is None` tracebacks during interpreter shutdown, and `mozinfo` emits a `SyntaxWarning: invalid escape`. Both are harmless — do not chase them; assert on the printed result line, not a clean stderr.
- **Marionette content-eval Xray gotcha (verified in Task 2):** `eval_content`/`execute_script` runs in a sandbox with an Xray view of the content `window`, so a property the PAGE set on itself (`window.__done__`, `window.__timingResult__`, `window.__leaks__`) reads back `undefined` via plain `window.X` — read it as `window.wrappedJSObject.X`. `harness.wait_done()` already does this. And a value set INSIDE one `eval_content` call does not persist to a later separate `eval_content` (fresh sandbox) — set page globals via a page `<script>` and read them via `wrappedJSObject`, mirroring Task 2's probe page.
- **Branch:** `feat/fb-fingerprint-observer`. Commits end with:
  ```
  Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>
  Claude-Session: https://claude.ai/code/session_01Y9Fmes3gzm8FB7Y3ajKjfv
  ```

---

## File Structure

- `build-tester/observer/harness.py` — shared: `Session` (Marionette launch/arm/navigate/eval/snapshot/cookies) + `serve(dir)`. Consumed by every later task.
- `build-tester/observer/probe_all_surfaces.html` — page that touches all 7 wired surfaces.
- `build-tester/observer/test_observer_records.py` — Task 2 functional test (7-surface truth table).
- `build-tester/observer/run_timing_parity.py` — Task 3 (drives the existing `timing_parity_probe.js` armed vs unarmed).
- `build-tester/observer/fb_surrogate.html` — Task 4 Meta Pixel + SDK stimulus page.
- `build-tester/observer/recon_fb.py` — Task 4 driver (snapshot surfaces + requests + cookies) → JSON.
- `build-tester/observer/probe_leaks.html` + `probe_leaks.py` — Task 5 un-spoofed-leak evidence probe.
- `build-tester/observer/REPORT.md` — Task 6 committed recon report + leak-evidence table + scope caveat.

---

## Task 1: Marionette readout harness (arm → touch canvas → read one record)

Build `harness.py` (the shared `Session`) and prove the smallest end-to-end slice: an armed canvas read is visible via the chrome-context snapshot.

**Files:**
- Create: `build-tester/observer/harness.py`
- Create: `build-tester/observer/test_readout.py`
- Modify: `build-tester/requirements.txt` (add `marionette_driver`)

**Interfaces (later tasks depend on these exact signatures):**
- `serve(directory) -> (port:int, stop:callable)`
- `class Session(camou_config: dict|None = None, arm: bool = True, binary: str|None = None, prefs: dict|None = None)` — context manager; methods: `navigate(url)`, `eval_content(js) -> any` (content context), `wait_done(timeout=30) -> bool` (polls `window.__done__`), `snapshot() -> list[dict]` where each dict is `{"site": str, "surfaces": {name:count}, "requests": [ {host,url,method,ts} ]}`, `cookies() -> list[{name,host}]`.

- [ ] **Step 1: Write the failing test** (`build-tester/observer/test_readout.py`)

```python
import os, sys
from pathlib import Path
HERE = Path(__file__).parent
sys.path.insert(0, str(HERE))
import harness

CANVAS_POKE = """
const c = document.createElement('canvas'); c.width=200; c.height=50;
const x = c.getContext('2d'); x.textBaseline='top'; x.font='14px Arial';
x.fillText('camoufox-observer-probe', 2, 2);
c.toDataURL();
window.__done__ = true; return true;
"""

def main():
    port, stop = harness.serve(HERE)
    try:
        with harness.Session(camou_config={"canvas:seed": 424242}) as s:
            s.navigate(f"http://127.0.0.1:{port}/")   # real origin, not about:blank
            s.eval_content(CANVAS_POKE)
            snap = s.snapshot()
    finally:
        stop()
    assert any("canvas" in row["surfaces"] for row in snap), f"no canvas record: {snap}"
    print("PASS: canvas recorded ->", snap)

main()
```

- [ ] **Step 2: Run it to confirm it fails**

Run: `cd build-tester && ./.venv/bin/python observer/test_readout.py`
Expected: FAIL — `ModuleNotFoundError: harness`.

- [ ] **Step 3: Implement `harness.py`**

```python
import functools, http.server, json, os, socketserver, threading, time

BIN_DEFAULT = "/tmp/cfx_sync4/app/Camoufox.app/Contents/MacOS/camoufox"
SURFACE_NAMES = {1:"canvas",2:"webgl",3:"webrtc",4:"navigator",5:"screen",6:"fonts",7:"audio"}
FIREFOX_WEBGL_PREFS = {"webgl.force-enabled": True, "webgl.enable-webgl2": True,
                       "media.peerconnection.ice.obfuscate_host_addresses": False}

_SNAP_JS = ("try{var {getCollector}=ChromeUtils.importESModule("
            "'resource://gre/modules/TrackingObserver.sys.mjs');var c=getCollector();"
            "return c?JSON.stringify(c.snapshot()):'[]';}catch(e){return 'ERR:'+e;}")
_COOKIE_JS = ("try{let o=[];for(let c of Services.cookies.cookies){o.push({name:c.name,host:c.host});}"
              "return JSON.stringify(o);}catch(e){return 'ERR:'+e;}")

def serve(directory):
    h = functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(directory))
    httpd = socketserver.TCPServer(("127.0.0.1", 0), h)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    return httpd.server_address[1], httpd.shutdown

class Session:
    def __init__(self, camou_config=None, arm=True, binary=None, prefs=None):
        self.camou_config = camou_config
        self.arm = arm
        self.binary = binary or os.environ.get("CFX_BIN", BIN_DEFAULT)
        self.prefs = {**FIREFOX_WEBGL_PREFS, **(prefs or {})}
        self.m = None

    def __enter__(self):
        if self.arm: os.environ["CAMOU_OBSERVE"] = "1"
        else: os.environ.pop("CAMOU_OBSERVE", None)
        if self.camou_config is not None:
            os.environ["CAMOU_CONFIG"] = json.dumps(self.camou_config)
        from marionette_driver.marionette import Marionette
        self.m = Marionette(bin=self.binary, headless=True, prefs=self.prefs)
        self.m.start_session()
        return self

    def __exit__(self, *a):
        try: self.m.delete_session()
        except Exception: pass

    def navigate(self, url): self.m.navigate(url)
    def eval_content(self, js): return self.m.execute_script(js)

    def wait_done(self, timeout=30):
        for _ in range(int(timeout / 0.3)):
            time.sleep(0.3)
            try:
                if self.m.execute_script("return !!window.__done__;"): return True
            except Exception: pass
        return False

    def snapshot(self):
        time.sleep(1.2)  # let the observer's 500ms actor drain feed the parent Collector
        with self.m.using_context("chrome"):
            raw = self.m.execute_script(_SNAP_JS)
        if raw.startswith("ERR:"): raise RuntimeError("snapshot: " + raw)
        out = []
        for r in json.loads(raw):
            surfaces = {SURFACE_NAMES.get(int(k), k): v for k, v in r["surfaces"].items()}
            out.append({"site": r["key"]["site"], "surfaces": surfaces, "requests": r.get("requests", [])})
        return out

    def cookies(self):
        with self.m.using_context("chrome"):
            raw = self.m.execute_script(_COOKIE_JS)
        return json.loads(raw) if not raw.startswith("ERR:") else []
```

Also append `marionette_driver` to `build-tester/requirements.txt`.

- [ ] **Step 4: Run the test to verify it passes**

Run: `cd build-tester && ./.venv/bin/python observer/test_readout.py`
Expected: `PASS: canvas recorded -> [...]` (a row whose `surfaces` contains `canvas`). Ignore the shutdown-time `__del__` tracebacks and the `mozinfo` warning. If `Marionette(prefs=…)` raises about an unexpected kwarg, switch to building a profile via `mozprofile.Profile(preferences=self.prefs)` and pass `Marionette(bin=…, profile=…)`.

- [ ] **Step 5: Commit**

```bash
git add build-tester/observer/harness.py build-tester/observer/test_readout.py build-tester/requirements.txt
git commit -m "test(observer): Marionette chrome-context readout harness (canvas record)"
```

---

## Task 2: Seven-surface truth table (functional regression test)

Resolve the stale-README discrepancy: prove which of the 7 wired surfaces record at runtime.

**Files:**
- Create: `build-tester/observer/probe_all_surfaces.html`
- Create: `build-tester/observer/test_observer_records.py`

**Interfaces:** Consumes `harness.Session / serve` from Task 1.

- [ ] **Step 1: Write the probe page** (`build-tester/observer/probe_all_surfaces.html`)

```html
<!doctype html><meta charset=utf-8><title>observer probe</title><body><script>
(async () => {
  const log = {};
  try { const c=document.createElement('canvas'); c.width=200;c.height=50;
    const x=c.getContext('2d'); x.font='14px Arial'; x.fillText('probe',2,2); c.toDataURL(); log.canvas=1; } catch(e){ log.canvas='ERR:'+e; }
  try { const g=document.createElement('canvas').getContext('webgl') || document.createElement('canvas').getContext('experimental-webgl');
    g.getParameter(g.VENDOR); const ext=g.getExtension('WEBGL_debug_renderer_info');
    if(ext) g.getParameter(ext.UNMASKED_RENDERER_WEBGL); log.webgl=1; } catch(e){ log.webgl='ERR:'+e; }
  try { const pc=new RTCPeerConnection(); pc.createDataChannel('x');
    await pc.createOffer().then(o=>pc.setLocalDescription(o)); log.webrtc=1; } catch(e){ log.webrtc='ERR:'+e; }
  try { void navigator.userAgent; void navigator.platform; void navigator.hardwareConcurrency; void navigator.oscpu; log.navigator=1; } catch(e){ log.navigator='ERR:'+e; }
  try { void screen.width; void screen.height; void screen.colorDepth; log.screen=1; } catch(e){ log.screen='ERR:'+e; }
  try { const x=document.createElement('canvas').getContext('2d');
    for (const f of ['NoSuchFont123','Impact','Webdings','Papyrus']) { x.font='16px '+f; x.measureText('mix wq'); }
    if (document.fonts && document.fonts.check) document.fonts.check('16px Impact'); log.fonts=1; } catch(e){ log.fonts='ERR:'+e; }
  try { const ac=new (window.OfflineAudioContext||window.webkitOfflineAudioContext)(1,44100,44100);
    const o=ac.createOscillator(); o.connect(ac.destination); o.start();
    const an=ac.createAnalyser(); o.connect(an); const buf=new Float32Array(an.frequencyBinCount); an.getFloatFrequencyData(buf);
    await ac.startRendering(); log.audio=1; } catch(e){ log.audio='ERR:'+e; }
  window.__probeLog__ = log; window.__done__ = true;
})();
</script></body>
```

- [ ] **Step 2: Write the failing test** (`build-tester/observer/test_observer_records.py`)

```python
import sys
from pathlib import Path
HERE = Path(__file__).parent
sys.path.insert(0, str(HERE))
import harness

EXPECTED = {"canvas","webgl","webrtc","navigator","screen","fonts","audio"}

def main():
    port, stop = harness.serve(HERE)
    try:
        with harness.Session(camou_config={"canvas:seed": 424242}) as s:
            s.navigate(f"http://127.0.0.1:{port}/probe_all_surfaces.html")
            s.wait_done(30)
            probe_log = s.eval_content("return window.__probeLog__;")
            snap = s.snapshot()
    finally:
        stop()
    recorded = set()
    for row in snap: recorded |= set(row["surfaces"])
    print("probe page results:", probe_log)
    print("observer recorded:", sorted(recorded))
    missing = EXPECTED - recorded
    assert not missing, f"surfaces NOT recorded: {sorted(missing)} | probe={probe_log} | snap={snap}"
    print("PASS: all 7 surfaces recorded")

main()
```

- [ ] **Step 3: Run to verify it fails or reveals gaps**

Run: `cd build-tester && ./.venv/bin/python observer/test_observer_records.py`
Expected initially: may FAIL listing surfaces not recorded. For each missing surface, check `probe_log`: if the poke errored (`ERR:…`), fix the poke (wrong API / headless GL). WebGL: confirm `FIREFOX_WEBGL_PREFS` is applied (Task 1 harness sets them by default). If the poke succeeded but no record appeared, that is a real observer gap.

- [ ] **Step 4: Iterate pokes until the table is truthful, then it passes**

Fix `probe_all_surfaces.html` pokes so every wired surface that *can* record does. If a surface genuinely never records despite a valid, non-erroring poke (e.g. audio may hook a specific node call), downgrade that one to a printed `KNOWN-GAP: <surface> (poke ok, no record)` line with a code comment citing the evidence — never a false pass — and carry it into Task 6.
Expected final: `PASS: all 7 surfaces recorded`, or an explicit justified KNOWN-GAP list with the rest asserted.

- [ ] **Step 5: Commit**

```bash
git add build-tester/observer/probe_all_surfaces.html build-tester/observer/test_observer_records.py
git commit -m "test(observer): 7-surface runtime truth table (resolves stale canvas-only README)"
```

---

## Task 3: Timing-parity gate (detectability regression)

Drive the existing `timing_parity_probe.js` armed vs unarmed on the same binary; assert armed stays within the unarmed band.

**Files:**
- Create: `build-tester/observer/timing_probe.html`
- Create: `build-tester/observer/run_timing_parity.py`
- Reference: `build-tester/observer/timing_parity_probe.js` (unchanged)

**Interfaces:** Consumes `harness.Session` with `arm=True|False`.

- [ ] **Step 1: Write the timing page + runner**

The probe must run as a page `<script>` (not via `eval_content`), so it sets `window.__timingResult__` on the real window — a value set inside an `eval_content` sandbox does not persist to a later separate read (see the Marionette Xray note in Global Constraints). Create `build-tester/observer/timing_probe.html`:

```html
<!doctype html><meta charset=utf-8><title>timing</title><body>
<script src="timing_parity_probe.js"></script>
<script>window.__done__ = true;</script>
</body>
```

Then `build-tester/observer/run_timing_parity.py`:

```python
import statistics, sys
from pathlib import Path
HERE = Path(__file__).parent
sys.path.insert(0, str(HERE))
import harness

def measure(arm):
    port, stop = harness.serve(HERE)
    try:
        with harness.Session(arm=arm) as s:
            s.navigate(f"http://127.0.0.1:{port}/timing_probe.html")
            s.wait_done(30)
            # page <script> set __timingResult__ on the real window; read it through
            # the Marionette Xray boundary via wrappedJSObject.
            return s.eval_content("return window.wrappedJSObject.__timingResult__;")
    finally:
        stop()

def main():
    unarmed = [measure(False) for _ in range(3)]
    armed   = [measure(True)  for _ in range(3)]
    def med(runs, op): return statistics.median(x[op]["median"] for x in runs if x and x.get(op))
    ok = True
    for op in ("toDataURL","getParameter"):
        u, a = med(unarmed, op), med(armed, op)
        ratio = a / u if u else float("nan")
        print(f"{op}: unarmed={u:.4f}ms armed={a:.4f}ms ratio={ratio:.3f}")
        if not (ratio < 1.5): ok = False
    assert ok, "armed run measurably slower than unarmed band — ring-buffer hot path too heavy"
    print("PASS: timing parity within band")

main()
```

- [ ] **Step 2: Run it**

Run: `cd build-tester && ./.venv/bin/python observer/run_timing_parity.py`
Expected: PASS, ratios near 1.0 (1.5× threshold is deliberately loose for a 3-run macOS sample). If armed is >1.5× slower, that is a real detectability finding — record it in Task 6; do not relax the threshold to force a pass.

- [ ] **Step 3: Commit**

```bash
git add build-tester/observer/run_timing_parity.py
git commit -m "test(observer): armed-vs-unarmed timing-parity gate"
```

---

## Task 4: Facebook stimulus recon (local Pixel + SDK surrogate)

Drive Meta's real fingerprinting code with zero facebook.com exposure; capture which surfaces it reads (observer snapshot) plus its network/cookie envelope (same snapshot's `requests` + chrome cookie read).

**Files:**
- Create: `build-tester/observer/fb_surrogate.html`
- Create: `build-tester/observer/recon_fb.py`

- [ ] **Step 1: Write the surrogate page**

```html
<!doctype html><meta charset=utf-8><title>fb surrogate</title><body>
<script>
!function(f,b,e,v,n,t,s){if(f.fbq)return;n=f.fbq=function(){n.callMethod?
n.callMethod.apply(n,arguments):n.queue.push(arguments)};if(!f._fbq)f._fbq=n;
n.push=n;n.loaded=!0;n.version='2.0';n.queue=[];t=b.createElement(e);t.async=!0;
t.src=v;s=b.getElementsByTagName(e)[0];s.parentNode.insertBefore(t,s)}
(window,document,'script','https://connect.facebook.net/en_US/fbevents.js');
fbq('init','000000000000000');  // dummy pixel id — collection code still runs
fbq('track','PageView');
</script>
<script async defer src="https://connect.facebook.net/en_US/sdk.js"></script>
<script>setTimeout(()=>{window.__done__=true;}, 2500);</script>
</body>
```

- [ ] **Step 2: Write the recon driver**

```python
import json, sys
from pathlib import Path
HERE = Path(__file__).parent
sys.path.insert(0, str(HERE))
import harness

def main():
    port, stop = harness.serve(HERE)
    try:
        with harness.Session(camou_config={"canvas:seed": 424242}) as s:
            s.navigate(f"http://127.0.0.1:{port}/fb_surrogate.html")
            s.wait_done(30)
            snap = s.snapshot()
            cookies = s.cookies()
    finally:
        stop()
    all_reqs = [r for row in snap for r in row["requests"]]
    fb_hosts = sorted({r["host"] for r in all_reqs if "facebook" in r["host"] or "fbcdn" in r["host"] or "fbcdn.net" in r["url"]})
    out = {
        "observer_surfaces": [{"site": r["site"], "surfaces": r["surfaces"]} for r in snap],
        "fb_request_hosts": fb_hosts,
        "fb_request_count": sum(1 for r in all_reqs if "facebook" in r["host"] or "fbcdn" in r["host"]),
        "cookie_names": sorted({c["name"] for c in cookies}),
    }
    (HERE / "recon_fb.json").write_text(json.dumps(out, indent=2))
    print(json.dumps(out, indent=2))
    assert snap, "surrogate produced no observer rows — check network egress to connect.facebook.net"

main()
```

- [ ] **Step 3: Run it**

Run: `cd build-tester && ./.venv/bin/python observer/recon_fb.py`
Expected: JSON with `observer_surfaces` (surfaces Meta's code touched), `fb_request_hosts` (e.g. `connect.facebook.net`), `cookie_names`. Requires egress to `connect.facebook.net`. If offline/blocked, note it and defer — the surrogate needs Meta's real JS. Do not fabricate rows.

- [ ] **Step 4 (optional, manual): one facebook.com spot-check**

Only if the operator chooses. Manually (not in a loop): `CAMOU_OBSERVE=1 CAMOU_CONFIG='{"canvas:seed":424242}' <binary>`, browse to facebook.com once logged-out, then in a separate Marionette chrome-context session (or the same one) read `getCollector().snapshot()`. Record whether the surface set matches the surrogate. Skip if unsure — the surrogate is authoritative for "what Meta's code reads."

- [ ] **Step 5: Commit**

```bash
git add build-tester/observer/fb_surrogate.html build-tester/observer/recon_fb.py build-tester/observer/recon_fb.json
git commit -m "recon(observer): local Meta Pixel/SDK surrogate — surfaces + network envelope"
```

---

## Task 5: Un-spoofed-leak evidence probe (scopes Plan B)

Confirm which candidate surfaces actually return a real, device-varying value on FF152 — so Plan B spoofs only genuine leaks, not constants.

**Files:**
- Create: `build-tester/observer/probe_leaks.html`
- Create: `build-tester/observer/probe_leaks.py`

- [ ] **Step 1: Write the probe page**

```html
<!doctype html><meta charset=utf-8><title>leak probe</title><body><script>
(async () => {
  const r = {};
  r.deviceMemory = ('deviceMemory' in navigator) ? navigator.deviceMemory : '<<absent>>';
  r.plugins = [...navigator.plugins].map(p=>p.name);
  r.mimeTypes = [...navigator.mimeTypes].map(m=>m.type);
  r.vendor = navigator.vendor;
  r.userAgentData = ('userAgentData' in navigator) ? JSON.stringify(navigator.userAgentData) : '<<absent>>';
  r.connection = ('connection' in navigator) ? (navigator.connection && navigator.connection.effectiveType || 'present') : '<<absent>>';
  try { r.battery = (typeof navigator.getBattery==='function') ? 'callable' : '<<absent>>'; } catch(e){ r.battery='ERR'; }
  try { r.devices = (await navigator.mediaDevices.enumerateDevices()).map(d=>d.kind+':'+d.label); } catch(e){ r.devices='ERR:'+e; }
  window.__leaks__ = r; window.__done__ = true;
})();
</script></body>
```

- [ ] **Step 2: Write the probe driver** (two different presets → device-varying?)

```python
import json, sys
from pathlib import Path
HERE = Path(__file__).parent
sys.path.insert(0, str(HERE))
import harness

# What makes a surface a Plan-B spoof candidate is NOT "does it vary between two configs"
# (an un-spoofed surface returns the SAME real device value regardless of config, so a
# config-comparison would mislabel it "constant" and miss it). It is: the surface returns
# a present, non-empty REAL value AND camoufox has no MaskConfig key to spoof it.
# MaskConfig coverage (settings/properties.json): only battery:* and mediaDevices:* have
# keys (already spoofable -> observe-only in Plan B). deviceMemory / plugins / mimeTypes /
# vendor / userAgentData / connection have NO key -> a present non-empty value there leaks
# the real device value.
HAS_KEY = {"battery", "devices"}   # 'devices' == navigator.mediaDevices.enumerateDevices

def empty(v):
    return v is None or v == "<<absent>>" or v == "" or v == []

def main():
    port, stop = harness.serve(HERE)
    try:
        with harness.Session(camou_config={"canvas:seed": 1}) as s:
            s.navigate(f"http://127.0.0.1:{port}/probe_leaks.html")
            s.wait_done(30)
            # __leaks__ is set by the page's own <script>; read across the Marionette
            # Xray boundary via wrappedJSObject (see Global Constraints).
            vals = s.eval_content("return window.wrappedJSObject.__leaks__;")
    finally:
        stop()
    assert vals, "probe produced no values"
    table = {k: {"value": vals[k], "present": vals[k] != "<<absent>>",
                 "empty": empty(vals[k]), "has_maskconfig_key": k in HAS_KEY} for k in vals}
    (HERE / "leak_evidence.json").write_text(json.dumps(table, indent=2))
    print(json.dumps(table, indent=2))
    candidates = [k for k in table if table[k]["present"] and not table[k]["empty"]
                  and not table[k]["has_maskconfig_key"]]
    print("PLAN-B SPOOF CANDIDATES (present real value, no MaskConfig key):", candidates or "none")
    print("SKIP (absent/empty):", [k for k in table if table[k]["empty"]] or "none")
    print("OBSERVE-ONLY (already has MaskConfig key):",
          sorted(k for k in table if table[k]["has_maskconfig_key"]))

main()
```

- [ ] **Step 3: Run it**

Run: `cd build-tester && ./.venv/bin/python observer/probe_leaks.py`
Expected: a per-surface table of the actual FF152 values + three printed lists. `PLAN-B SPOOF CANDIDATES` = present, non-empty, no MaskConfig key (expected: `deviceMemory`, possibly `plugins`/`mimeTypes`). `SKIP` = absent or empty (expected: `userAgentData`/`connection` absent, `vendor` likely `""`). `OBSERVE-ONLY` = `battery`/`devices` (already have MaskConfig keys → Plan B adds a `Record()` hook, no new spoof). The committed `leak_evidence.json` carries the raw values for Task 6 / Plan B. Report the ACTUAL lists — do not assume the expected ones; the point is to discover the real FF152 values.

- [ ] **Step 4: Commit**

```bash
git add build-tester/observer/probe_leaks.html build-tester/observer/probe_leaks.py build-tester/observer/leak_evidence.json
git commit -m "recon(observer): un-spoofed-leak evidence table (scopes Plan B spoofs)"
```

---

## Task 6: Recon report (deliverable)

Assemble Tasks 2/4/5 outputs into one honest report — the answer to "how does FB track the browser, and where does camoufox leak."

**Files:**
- Create: `build-tester/observer/REPORT.md`

- [ ] **Step 1: Write the report** pulling in the committed JSON artifacts. Sections:
  1. **Runtime gate** — the 7-surface truth table from Task 2 (which surfaces record; any KNOWN-GAP), plus the readout method (Marionette chrome context; why not the panel).
  2. **What Meta's code reads** — `recon_fb.json` observer surfaces + FB hosts + cookie names; the optional facebook.com spot-check outcome if run.
  3. **Leak evidence** — `leak_evidence.json` verdicts; the explicit Plan-B spoof-candidate list (confirmed leaks) vs skip list (absent/constant) vs observe-only list (already-spoofed battery/mediaDevices).
  4. **Scope caveat** — the Global-Constraints scope paragraph verbatim.
  5. **Timing parity** — Task 3 ratios.

- [ ] **Step 2: Sanity-check** the report against the JSON files (numbers match; no claim beyond the evidence).

- [ ] **Step 3: Commit**

```bash
git add build-tester/observer/REPORT.md
git commit -m "recon(observer): FB fingerprint recon report + Plan-B scope"
```

---

## After Plan A

Task 5's `leak_evidence.json` + Task 4's `recon_fb.json` are the inputs to **Plan B** (Phase 3: observe + spoof the confirmed leaks). Do not write Plan B until these exist — its task list (which MaskConfig keys, which getters, which pythonlib fields) is determined by the evidence, and every Plan-B spoof is gated by `build-tester ≥ 1000` (with the `playwright==1.55.0` pin that Plan B's build-tester runs require) to avoid the lie-detection regression that broke it to 0/0 once before.

## Self-Review

- **Spec coverage:** Plan A = spec Phase 1 (Tasks 1-3) + Phase 2 (Task 4) + the Phase-3 evidence gate (Task 5) + honest-scope deliverable (Task 6). Spec Phase 3 spoofs = Plan B (deferred, evidence-gated). ✓
- **Placeholder scan:** readout is Marionette chrome-context — spiked and proven, not a TODO; exploratory tasks (4, 5) carry a smoke `assert` (non-empty) plus their real deliverable (the JSON), not fake fixed-value asserts. ✓
- **Type consistency:** every task uses `harness.Session` / `harness.serve` with the Task-1 signatures; `snapshot()` returns `[{"site","surfaces":{name:count},"requests":[…]}]` used uniformly; surface-id→name mapping lives once in `harness.SURFACE_NAMES`. ✓
