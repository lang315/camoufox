# FB Fingerprint Observer — Verify + Recon (Plan A) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Prove the built-in Tracking Observer records fingerprint reads at runtime, then drive it against Facebook's real fingerprinting code (local Meta Pixel/SDK surrogate) to produce a recon report of which surfaces FB consults — and a leak-evidence table that scopes the follow-on spoof work (Plan B).

**Architecture:** A small Python/Playwright harness under `build-tester/observer/` that arms the *existing* binary with `CAMOU_OBSERVE=1`, drives probe pages, and reads the observer's records back by scraping the `chrome://camoufox` panel DOM. No browser rebuild — Plan A runs entirely against the already-built `cfx_sync4` binary. Plan B (spoofing the confirmed leaks) is deferred and gets its own plan once Task 6 produces the evidence.

**Tech Stack:** Python 3.11+, Playwright (`playwright==1.55.0`, async API), the existing `build-tester/scripts/` plumbing (`server.start_http_server`), the pre-built `cfx_sync4` Camoufox binary.

## Global Constraints

- **No browser rebuild in Plan A.** Every task runs against the pre-built binary at `/tmp/cfx_sync4/app/Camoufox.app/Contents/MacOS/camoufox` (override via `--binary`). If that path is gone, re-download the beta.28 CI artifact first (out of plan scope).
- **Playwright pin:** the `build-tester` venv must use `playwright==1.55.0` (newer → false 0/0 regression on camoufox-152). Reuse `build-tester/.venv` if present.
- **Observer arming:** set env `CAMOU_OBSERVE=1`. Off/`0` = observer does nothing. Always pass a realistic `CAMOU_CONFIG` too, so the spoof getters (which host the `Record()` calls) are on the live path.
- **Facebook target policy:** the local `fbevents.js` + `sdk.js` surrogate is the primary stimulus. At most **one** manual, human-paced, logged-out, no-interaction facebook.com load as a spot-check. **No automated loops against facebook.com.**
- **Honest scope caveat** (verbatim in the Task 6 report): observer sees presence + drain-window count at the JS/WebIDL boundary only — not values/hashes/scoring; blind to TLS/JA3/H2/TCP, WASM, workers/service-workers, pure-CSS `@media`, timing side-channels, server-side scoring. "Silence ≠ not read" for anything unhooked.
- **Branch:** `feat/fb-fingerprint-observer`. Commits end with:
  ```
  Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>
  Claude-Session: https://claude.ai/code/session_01Y9Fmes3gzm8FB7Y3ajKjfv
  ```
- **SurfaceId ground truth** (`additions/camoucfg/AccessObserver.hpp` / `content/tracking.js`): `1 canvas, 2 webgl, 3 webrtc, 4 navigator, 5 screen, 6 fonts, 7 audio`.

---

## File Structure

- `build-tester/observer/harness.py` — shared: arm+launch, serve a dir, `read_snapshot()` (panel scrape). Consumed by every later task.
- `build-tester/observer/probe_all_surfaces.html` — page that touches all 7 wired surfaces.
- `build-tester/observer/test_observer_records.py` — Task 2 functional test (7-surface truth table).
- `build-tester/observer/run_timing_parity.py` — Task 3 (wraps the existing `timing_parity_probe.js`).
- `build-tester/observer/fb_surrogate.html` — Task 4 Meta Pixel + SDK stimulus page.
- `build-tester/observer/recon_fb.py` — Task 4 driver (observer snapshot + Playwright network/cookie capture) → JSON.
- `build-tester/observer/probe_leaks.html` + `probe_leaks.py` — Task 5 un-spoofed-leak evidence probe.
- `build-tester/observer/REPORT.md` — Task 6 committed recon report + leak-evidence table + scope caveat.

---

## Task 1: Readout helper (arm → touch canvas → read one record)

The one genuinely-unverified mechanism: reading records back headless. Prove the smallest end-to-end slice and expose it as `read_snapshot()` so later tasks don't care how it works.

**Files:**
- Create: `build-tester/observer/harness.py`
- Create: `build-tester/observer/test_readout.py`

**Interfaces:**
- Produces: `async launch_armed(pw, binary, camou_config: dict|None) -> Browser`; `serve(dir) -> (port, stop)`; `async read_snapshot(context) -> list[dict]` where each dict is `{"site": str, "surfaces": {name: count}}`.

- [ ] **Step 1: Write the failing test**

```python
# build-tester/observer/test_readout.py
import asyncio, os, sys
from pathlib import Path
HERE = Path(__file__).parent
sys.path.insert(0, str(HERE.parent / "scripts"))
from playwright.async_api import async_playwright
import harness

BIN = os.environ.get("CFX_BIN", "/tmp/cfx_sync4/app/Camoufox.app/Contents/MacOS/camoufox")

CANVAS_POKE = """
const c = document.createElement('canvas'); c.width=200; c.height=50;
const x = c.getContext('2d'); x.textBaseline='top'; x.font='14px Arial';
x.fillText('camoufox-observer-probe', 2, 2);
c.toDataURL();  // canvas readback → SurfaceId::Canvas Record()
window.__done__ = true;
"""

async def main():
    async with async_playwright() as pw:
        browser = await harness.launch_armed(pw, BIN, camou_config={"canvas:seed": 424242})
        ctx = await browser.new_context()
        page = await ctx.new_page()
        await page.goto("about:blank")
        await page.evaluate(CANVAS_POKE)
        await page.wait_for_timeout(800)  # > one 500ms drain cycle
        snap = await harness.read_snapshot(ctx)
        await browser.close()
        assert any("canvas" in row["surfaces"] for row in snap), f"no canvas record: {snap}"
        print("PASS: canvas recorded ->", snap)

asyncio.run(main())
```

- [ ] **Step 2: Run it to confirm it fails**

Run: `cd build-tester && ./.venv/bin/python observer/test_readout.py`
Expected: FAIL — `ModuleNotFoundError: harness` (or `AttributeError`), because `harness.py` doesn't exist yet.

- [ ] **Step 3: Implement `harness.py`**

```python
# build-tester/observer/harness.py
import functools, http.server, json, os, socketserver, threading
from pathlib import Path

PANEL_URL = "chrome://camoufox/content/tracking.html"

async def launch_armed(pw, binary, camou_config=None):
    env = {**dict(os.environ), "CAMOU_OBSERVE": "1"}
    if camou_config is not None:
        env["CAMOU_CONFIG"] = json.dumps(camou_config)
    return await pw.firefox.launch(executable_path=binary, headless=True, env=env)

def serve(directory):
    handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(directory))
    httpd = socketserver.TCPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    return httpd.server_address[1], httpd.shutdown

async def read_snapshot(context):
    """Scrape the chrome://camoufox panel DOM (rows built by content/tracking.js renderRows:
    .row > .site + .badge('name:count'))."""
    panel = await context.new_page()
    try:
        await panel.goto(PANEL_URL, wait_until="domcontentloaded", timeout=10000)
    except Exception as e:
        raise RuntimeError(
            f"panel readout failed ({e}). Fallback options if chrome:// nav is blocked: "
            "(a) launch binary via subprocess with browser.startup.homepage=PANEL_URL and "
            "screenshot/dump; (b) add a test-only privileged drain — but that needs a rebuild "
            "(out of Plan A scope). Resolve before Task 2."
        )
    await panel.wait_for_timeout(800)
    rows = await panel.eval_on_selector_all("#rows .row", """els => els.map(el => ({
        site: el.querySelector('.site')?.textContent || '',
        badges: [...el.querySelectorAll('.badge')].map(b => b.textContent),
    }))""")
    await panel.close()
    out = []
    for r in rows:
        surfaces = {}
        for b in r["badges"]:
            name, _, cnt = b.partition(":")
            surfaces[name] = int(cnt or 0)
        out.append({"site": r["site"], "surfaces": surfaces})
    return out
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `cd build-tester && ./.venv/bin/python observer/test_readout.py`
Expected: `PASS: canvas recorded -> [...]`.
If the panel `goto` raises: this is the readout-mechanism unknown surfacing. Investigate with systematic-debugging (is chrome:// reachable at all? does the panel render for a real profile?) and implement the documented fallback before proceeding. Do **not** fake the record.

- [ ] **Step 5: Commit**

```bash
git add build-tester/observer/harness.py build-tester/observer/test_readout.py
git commit -m "test(observer): headless readout helper via chrome://camoufox panel scrape"
```

---

## Task 2: Seven-surface truth table (functional regression test)

Resolve the stale-README discrepancy: prove all 7 wired surfaces actually record at runtime.

**Files:**
- Create: `build-tester/observer/probe_all_surfaces.html`
- Create: `build-tester/observer/test_observer_records.py`

**Interfaces:**
- Consumes: `harness.launch_armed / serve / read_snapshot` from Task 1.

- [ ] **Step 1: Write the probe page** (`build-tester/observer/probe_all_surfaces.html`)

```html
<!doctype html><meta charset=utf-8><title>observer probe</title><body><script>
(async () => {
  const log = {};
  try { const c=document.createElement('canvas'); c.width=200;c.height=50;
    const x=c.getContext('2d'); x.font='14px Arial'; x.fillText('probe',2,2); c.toDataURL(); log.canvas=1; } catch(e){ log.canvas='ERR:'+e; }
  try { const g=document.createElement('canvas').getContext('webgl');
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
    const o=ac.createOscillator(); o.connect(ac.destination); o.start(); await ac.startRendering(); log.audio=1; } catch(e){ log.audio='ERR:'+e; }
  window.__probeLog__ = log; window.__done__ = true;
})();
</script></body>
```

- [ ] **Step 2: Write the failing test** (`build-tester/observer/test_observer_records.py`)

```python
import asyncio, os, sys
from pathlib import Path
HERE = Path(__file__).parent
sys.path.insert(0, str(HERE.parent / "scripts"))
from playwright.async_api import async_playwright
import harness

BIN = os.environ.get("CFX_BIN", "/tmp/cfx_sync4/app/Camoufox.app/Contents/MacOS/camoufox")
EXPECTED = {"canvas","webgl","webrtc","navigator","screen","fonts","audio"}

async def main():
    port, stop = harness.serve(HERE)
    try:
        async with async_playwright() as pw:
            browser = await harness.launch_armed(pw, BIN, camou_config={"canvas:seed": 424242})
            ctx = await browser.new_context()
            page = await ctx.new_page()
            await page.goto(f"http://127.0.0.1:{port}/probe_all_surfaces.html")
            await page.wait_for_function("!!window.__done__", timeout=30000)
            probe_log = await page.evaluate("window.__probeLog__")
            await page.wait_for_timeout(900)
            snap = await harness.read_snapshot(ctx)
            await browser.close()
    finally:
        stop()
    recorded = set()
    for row in snap: recorded |= set(row["surfaces"])
    print("probe page results:", probe_log)
    print("observer recorded:", sorted(recorded))
    missing = EXPECTED - recorded
    assert not missing, f"surfaces NOT recorded: {sorted(missing)} | probe={probe_log} | snap={snap}"
    print("PASS: all 7 surfaces recorded")

asyncio.run(main())
```

- [ ] **Step 3: Run to verify it fails or reveals gaps**

Run: `cd build-tester && ./.venv/bin/python observer/test_observer_records.py`
Expected initially: may FAIL listing surfaces not recorded. For each missing surface, first check `probe_log` — if the poke itself errored (`ERR:...`), fix the poke (wrong API). If the poke succeeded but no record appeared, that's a real observer gap: note it in the truth table and the report (do not force a pass).

- [ ] **Step 4: Iterate pokes until the table is truthful, then it passes**

Adjust `probe_all_surfaces.html` pokes so every surface that *is* wired records. The assertion passes only when all 7 record. If a surface genuinely never records despite a valid poke, downgrade the assertion for that surface to a printed `KNOWN-GAP` line (with a code comment citing the evidence) rather than a false pass — and carry it into Task 6.
Expected final: `PASS: all 7 surfaces recorded` (or an explicit, justified KNOWN-GAP list).

- [ ] **Step 5: Commit**

```bash
git add build-tester/observer/probe_all_surfaces.html build-tester/observer/test_observer_records.py
git commit -m "test(observer): 7-surface runtime truth table (resolves stale canvas-only README)"
```

---

## Task 3: Timing-parity gate (detectability regression)

Wrap the existing `timing_parity_probe.js` in a runnable armed-vs-unarmed comparison so the anti-detection property is a checked gate, not a comment.

**Files:**
- Create: `build-tester/observer/run_timing_parity.py`
- Reference: `build-tester/observer/timing_parity_probe.js` (unchanged)

- [ ] **Step 1: Write the runner** (drives the probe twice, same binary)

```python
import asyncio, os, sys, statistics
from pathlib import Path
HERE = Path(__file__).parent
sys.path.insert(0, str(HERE.parent / "scripts"))
from playwright.async_api import async_playwright
import harness

BIN = os.environ.get("CFX_BIN", "/tmp/cfx_sync4/app/Camoufox.app/Contents/MacOS/camoufox")
PROBE = (HERE / "timing_parity_probe.js").read_text()

async def measure(pw, armed):
    env = {**dict(os.environ)}
    if armed: env["CAMOU_OBSERVE"] = "1"
    else: env.pop("CAMOU_OBSERVE", None)
    b = await pw.firefox.launch(executable_path=BIN, headless=True, env=env)
    p = await (await b.new_context()).new_page()
    await p.goto("about:blank")
    r = await p.evaluate(PROBE + "\n; window.__timingResult__")
    await b.close()
    return r

async def main():
    async with async_playwright() as pw:
        unarmed = [await measure(pw, False) for _ in range(3)]
        armed   = [await measure(pw, True)  for _ in range(3)]
    def med(runs, op): return statistics.median(x[op]["median"] for x in runs if x and x[op])
    for op in ("toDataURL","getParameter"):
        u, a = med(unarmed, op), med(armed, op)
        ratio = a / u if u else float("nan")
        print(f"{op}: unarmed={u:.4f}ms armed={a:.4f}ms ratio={ratio:.3f}")
        assert ratio < 1.5, f"{op} armed {ratio:.2f}x slower — ring-buffer hot path too heavy"
    print("PASS: timing parity within band")

asyncio.run(main())
```

- [ ] **Step 2: Run it**

Run: `cd build-tester && ./.venv/bin/python observer/run_timing_parity.py`
Expected: PASS with ratios near 1.0 (threshold 1.5× is deliberately loose for a 3-run macOS sample; tighten only if stable). If armed is >1.5× slower, that is a real detectability finding — record it, do not relax the threshold to force a pass.

- [ ] **Step 3: Commit**

```bash
git add build-tester/observer/run_timing_parity.py
git commit -m "test(observer): armed-vs-unarmed timing-parity gate"
```

---

## Task 4: Facebook stimulus recon (local Pixel + SDK surrogate)

Drive Meta's real fingerprinting code with zero facebook.com exposure; capture which surfaces it reads (observer) plus its network/cookie envelope (Playwright).

**Files:**
- Create: `build-tester/observer/fb_surrogate.html`
- Create: `build-tester/observer/recon_fb.py`

- [ ] **Step 1: Write the surrogate page** (loads Meta's own distributable code)

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
<script>window.__done__ = true;</script>
</body>
```

- [ ] **Step 2: Write the recon driver** (observer snapshot + network/cookie capture)

```python
import asyncio, json, os, sys
from pathlib import Path
HERE = Path(__file__).parent
sys.path.insert(0, str(HERE.parent / "scripts"))
from playwright.async_api import async_playwright
import harness

BIN = os.environ.get("CFX_BIN", "/tmp/cfx_sync4/app/Camoufox.app/Contents/MacOS/camoufox")

async def main():
    port, stop = harness.serve(HERE)
    reqs = []
    try:
        async with async_playwright() as pw:
            browser = await harness.launch_armed(pw, BIN, camou_config={"canvas:seed": 424242})
            ctx = await browser.new_context()
            ctx.on("request", lambda r: reqs.append({"url": r.url, "method": r.method}))
            page = await ctx.new_page()
            await page.goto(f"http://127.0.0.1:{port}/fb_surrogate.html", wait_until="networkidle", timeout=45000)
            await page.wait_for_timeout(1500)  # let fbevents/sdk load + fingerprint + drain
            snap = await harness.read_snapshot(ctx)
            cookies = await ctx.cookies()
            await browser.close()
    finally:
        stop()
    fb_hosts = sorted({r["url"].split("/")[2] for r in reqs if "facebook" in r["url"] or "fbcdn" in r["url"]})
    out = {
        "observer_surfaces": snap,
        "fb_request_hosts": fb_hosts,
        "fb_request_count": sum(1 for r in reqs if "facebook" in r["url"] or "fbcdn" in r["url"]),
        "cookie_names": sorted({c["name"] for c in cookies}),
    }
    (HERE / "recon_fb.json").write_text(json.dumps(out, indent=2))
    print(json.dumps(out, indent=2))
    assert snap or fb_hosts, "surrogate produced no observer rows AND no FB requests — check network egress"

asyncio.run(main())
```

- [ ] **Step 3: Run it**

Run: `cd build-tester && ./.venv/bin/python observer/recon_fb.py`
Expected: JSON with `observer_surfaces` (surfaces Meta's code touched) + `fb_request_hosts` (e.g. `connect.facebook.net`) + `cookie_names`. Requires network egress to `connect.facebook.net`. If offline/blocked, note it and defer this task (the surrogate needs Meta's real JS). Do not fabricate rows.

- [ ] **Step 4 (optional, manual): one facebook.com spot-check**

Only if the operator chooses. Manually (not in a loop) run:
`CAMOU_OBSERVE=1 CAMOU_CONFIG='{"canvas:seed":424242}' <binary>`, browse to facebook.com once logged-out, open `chrome://camoufox/content/tracking.html`, and eyeball whether the surrogate's surface set matches. Record the outcome in the report. Skip if unsure — the surrogate is authoritative for "what Meta's code reads."

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

- [ ] **Step 1: Write the probe page** (dumps raw candidate values)

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

- [ ] **Step 2: Write the probe driver** (compare two different presets → device-varying?)

```python
import asyncio, json, os, sys
from pathlib import Path
HERE = Path(__file__).parent
sys.path.insert(0, str(HERE.parent / "scripts"))
from playwright.async_api import async_playwright
import harness

BIN = os.environ.get("CFX_BIN", "/tmp/cfx_sync4/app/Camoufox.app/Contents/MacOS/camoufox")

async def read_leaks(pw, camou_config):
    port, stop = harness.serve(HERE)
    try:
        b = await harness.launch_armed(pw, BIN, camou_config=camou_config)
        p = await (await b.new_context()).new_page()
        await p.goto(f"http://127.0.0.1:{port}/probe_leaks.html")
        await p.wait_for_function("!!window.__done__", timeout=30000)
        leaks = await p.evaluate("window.__leaks__")
        await b.close()
        return leaks
    finally:
        stop()

async def main():
    async with async_playwright() as pw:
        a = await read_leaks(pw, {"canvas:seed": 1})
        b = await read_leaks(pw, {"canvas:seed": 2, "navigator.oscpu": "Windows NT 10.0; Win64; x64"})
    table = {}
    for k in a:
        table[k] = {"config_a": a[k], "config_b": b[k],
                    "verdict": ("ABSENT" if a[k]=="<<absent>>" else
                                "CONSTANT" if a[k]==b[k] else "VARIES")}
    (HERE / "leak_evidence.json").write_text(json.dumps(table, indent=2))
    print(json.dumps(table, indent=2))
    # Not an assertion of pass/fail — this is the evidence that scopes Plan B.
    leaking = [k for k,v in table.items() if v["verdict"] not in ("ABSENT","CONSTANT")]
    print("PLAN-B SPOOF CANDIDATES (leak a real value):", leaking or "none")

asyncio.run(main())
```

- [ ] **Step 3: Run it**

Run: `cd build-tester && ./.venv/bin/python observer/probe_leaks.py`
Expected: a per-surface verdict table. Interpretation for Plan B: `ABSENT` → skip (Firefox doesn't expose it; e.g. likely `userAgentData`, `connection`). `CONSTANT` → likely skip (e.g. `vendor=""`), unless it's a constant that itself leaks Firefox-ness. `VARIES` or a real non-empty value with no MaskConfig key → Plan B spoof candidate (expected: `deviceMemory`, possibly `plugins`). Note `battery`/`devices` already have MaskConfig keys → observe-only in Plan B.

- [ ] **Step 4: Commit**

```bash
git add build-tester/observer/probe_leaks.html build-tester/observer/probe_leaks.py build-tester/observer/leak_evidence.json
git commit -m "recon(observer): un-spoofed-leak evidence table (scopes Plan B spoofs)"
```

---

## Task 6: Recon report (deliverable)

Assemble Tasks 2/4/5 outputs into one honest report — the actual answer to "how does FB track the browser, and where does camoufox leak."

**Files:**
- Create: `build-tester/observer/REPORT.md`

- [ ] **Step 1: Write the report** pulling in the committed JSON artifacts. Sections:
  1. **Runtime gate result** — the 7-surface truth table from Task 2 (which surfaces record; any KNOWN-GAP).
  2. **What Meta's code reads** — `recon_fb.json` observer surfaces + FB hosts + cookie names; the optional facebook.com spot-check outcome if run.
  3. **Leak evidence** — `leak_evidence.json` verdicts; the explicit Plan-B spoof candidate list (confirmed leaks) vs skip list (absent/constant) vs observe-only list (already-spoofed battery/mediaDevices).
  4. **Scope caveat** — the Global-Constraints scope paragraph verbatim ("presence + count only … silence ≠ not read … blind to TLS/JA3/WASM/workers/CSS/timing/server-side").
  5. **Timing parity** — Task 3 ratios.

- [ ] **Step 2: Sanity-check the report** against the JSON files (numbers match; no claim beyond the evidence).

- [ ] **Step 3: Commit**

```bash
git add build-tester/observer/REPORT.md
git commit -m "recon(observer): FB fingerprint recon report + Plan-B scope"
```

---

## After Plan A

Task 5's `leak_evidence.json` + Task 4's `recon_fb.json` are the inputs to **Plan B** (Phase 3: observe + spoof the confirmed leaks). Do not write Plan B until these exist — its task list (which MaskConfig keys, which getters, which pythonlib fields) is determined by the evidence, and every Plan-B spoof is gated by `build-tester ≥ 1000` (playwright==1.55.0) to avoid the lie-detection regression that broke it to 0/0 once before.

## Self-Review

- **Spec coverage:** Plan A = spec Phase 1 (Tasks 1-3) + Phase 2 (Task 4) + the Phase-3 evidence gate (Task 5) + honest-scope deliverable (Task 6). Spec Phase 3 spoofs = Plan B (deferred by design, evidence-gated). ✓
- **Placeholder scan:** readout method is real code (panel scrape) with a documented fallback path, not a TODO; exploratory tasks (4, 5) have "produces non-empty report" success criteria, not fake asserts. ✓
- **Type consistency:** every task consumes `harness.launch_armed/serve/read_snapshot` with the Task-1 signatures; `read_snapshot` returns `[{"site","surfaces":{name:count}}]` used uniformly. ✓
