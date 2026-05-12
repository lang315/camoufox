# Integration test results — Camoufox vs anti-browser detection

**Run date:** 2026-05-12
**Binary:** Camoufox 150.0.2-beta.25 (mac arm64, upstream prebuilt — patches in `patches/canvas-spoofing.patch` + `patches/webrtc-ip-spoofing2.patch` **not yet compiled in**)
**Harness:** `goapi/example/integration/`, `goapi/example/canvas/`, `goapi/example/baseline/`
**Sessions:** 1 online integration + 5 offline baseline + 1 canvas determinism
**Spoofed OS:** Windows (UA / WebGL / platform)

## TL;DR

| Surface | Oracle | Verdict | Note |
|---|---|---|---|
| Headless detection | CreepJS | **PASS** — `0% like headless` | undetected |
| Headless detection | AreYouHeadless | **PASS** — "You are not Chrome headless" | undetected |
| Webdriver / automation | bot.sannysoft.com | **PASS** — `navigator.webdriver = false`, all HEADCHR_/PHANTOM_/SELENIUM_ tests `ok` | |
| Canvas (cross-iframe within session) | sannysoft | identical 5/5 (`-1175717545`) | session-stable as expected |
| Canvas (cross-context) | local determinism smoke | **FAIL pre-patch** — same hash across BrowserContexts | confirms `setCanvasSeed` not wired in binary |
| Canvas (cross-launch, browserforge preset rotation) | offline baseline n=5 | 5/5 unique (4910/4722/4774/4902/4886 bytes) | font subset per preset varies canvas |
| WebGL renderer | sannysoft | `ANGLE (NVIDIA, NVIDIA GeForce 8800 GTX Direct3D11 vs_4_0 ps_4_0)` | Windows-style spoof active |
| WebGL vendor | sannysoft | `Google Inc. (NVIDIA)` | Chromium-style on Firefox — minor tell (`webgl-spoofing.patch` choice) |
| WebRTC LAN leak | BrowserLeaks | **PASS** — `Local IP Address: -` (mDNS obfuscation working) | Firefox default |
| WebRTC public IP | BrowserLeaks | host IP exposed `171.250.165.85` | expected — webrtc-ip-spoofing patches not in binary |
| WebRTC DTLS fingerprint | BrowserLeaks SDP | host's real DTLS cert `CE:14:69:E7:7B:8E:...` | out of scope per plan |
| Timezone | client_eval | host TZ `Asia/Ho_Chi_Minh` leaks | no `WithGeoIP(true)` + no `intl:timezone` config in test |

## Detail — per oracle

### 1. CreepJS — https://abrahamjuliot.github.io/creepjs/

```
fp_id:         ce437124dabc1544c431495d79b5c2bc423d38a99f6211417700274b346ad0c4
fuzzy_hash:    d54a784a15ecfc4dfee944834f1c8c265f032af82e8f1ffefc97000000000000
headless_pct:  0% like headless: bada4467
webrtc_line:   WebRTC5a56731e
ua_line:       userAgent:
```

- **Headless: undetected.**
- Modern CreepJS DOM no longer exposes `.trust-score` class (the harness in `goapi/example/creepjs/main.go` predates this change). New oracle in `goapi/example/integration/main.go` extracts `FP ID` / `Fuzzy` / headless-line text directly.
- Fingerprint hash unique per launch — drives the per-session uniqueness baseline that the canvas patches will target.

### 2. AreYouHeadless — https://arh.antoinevastel.com/bots/areyouheadless

```
You are not Chrome headless
```

- Passes. (Test specifically targets Chrome headless signatures; Firefox-based Camoufox sidesteps it by construction, but key automation tells like `navigator.webdriver` are also absent.)

### 3. bot.sannysoft.com — comprehensive matrix

All HEADCHR_, PHANTOM_, SELENIUM_, SEQUENTUM tests `ok`. `WebDriver (New): "missing (passed)"`. `Plugins is of type PluginArray: "passed"`. Five plugins reported (matches Firefox baseline post-PDFViewer pin).

Within-session canvas hash identical across all 5 sannysoft canvas frames (`-1175717545`) — expected: canvas is deterministic per (page, context, draw) on unpatched Firefox.

WebGL exposes `Google Inc. (NVIDIA)` + `ANGLE (NVIDIA, NVIDIA GeForce 8800 GTX Direct3D11 vs_4_0 ps_4_0)`. The Chromium-style vendor string on a Firefox UA is a known inconsistency in the current `webgl-spoofing.patch` preset table; downstream anti-bot stacks that cross-check vendor-against-UA may flag this. Not addressed by the WebRTC/canvas plan.

### 4. BrowserLeaks WebRTC — https://browserleaks.com/webrtc

```
Your Remote IP        171.250.165.85 / 2402:800:6388:af1e:300f:3cf1:99db:b63f
WebRTC Leak Test      ✔ No Leak
Local IP Address      -
Public IP Address     171.250.165.85 / 2402:800:6388:af1e:300f:3cf1:99db:b63f
```

SDP excerpt:

```
o=mozilla...THIS_IS_SDPARTA-99.0 7416570578096376930 0 IN IP4 0.0.0.0
a=fingerprint:sha-256 CE:14:69:E7:7B:8E:BA:F7:78:C9:C6:1C:D2:FE:F5:37:58:25:A7:8C:A4:2A:64:37:B3:17:51:6E:78:A8:92:F1
a=candidate:1 1 UDP 1685987327 171.250.165.85 10534 typ srflx raddr 171.250.165.85 rport 10534
a=candidate:3 1 UDP 1686052607 2402:800:6388:af1e:300f:3cf1:99db:b63f 64566 typ srflx raddr 2...
```

Confirmations:
- **mDNS host-address obfuscation is on** in this binary build (LAN IP shown as `-`, not as RFC1918 numerics). Plan phase 5 ("disable mDNS for uniform IP regex coverage") is therefore an active change — current default behavior already hides LAN.
- **Public IP not spoofed** — `webrtc-ip-spoofing.patch` + new `webrtc-ip-spoofing2.patch` are written but binary is upstream Camoufox without them.
- **DTLS fingerprint untouched** — matches plan ("DTLS sanitization explicitly out of scope").
- **SDP origin string** = `THIS_IS_SDPARTA-99.0` (Firefox 99 marker baked into the SDP origin line; doesn't track the actual Firefox version Camoufox forks from). Detectable cross-check against UA's claimed `Firefox/148.0`, but unrelated to either WebRTC IP or canvas — flagged here for awareness; not part of current plan.

### 5. Canvas determinism smoke — `example/canvas`

```
ctx1 read1: 99874bb8826867087017d3b46c8cd120
ctx1 read2: 99874bb8826867087017d3b46c8cd120
ctx2 read1: 99874bb8826867087017d3b46c8cd120
```

Same draw across two BrowserContexts in one launch → identical hash. Confirms `setCanvasSeed` is a no-op in the current binary, exactly as the plan documents. Post-patch acceptance: `ctx1` and `ctx2` should differ; `ctx1 read1 == ctx1 read2` must still hold.

### 6. Offline baseline n=5 — preset rotation across launches

```
session  ua_rv  canvas_hash  canvas_len  tz
0        148.0  669685491    4910        Asia/Ho_Chi_Minh
1        147.0  1788240763   4722        Asia/Ho_Chi_Minh
2        109.0  2901879696   4774        Asia/Ho_Chi_Minh
3        148.0  1409674263   4902        Asia/Ho_Chi_Minh
4        147.0  3100415226   4886        Asia/Ho_Chi_Minh
```

- 5/5 unique canvas hashes — preset's font-subset variance produces cross-launch divergence even without patches. This is the surface the canvas patches will *control* (per-context) instead of letting it be a noisy side effect of font selection.
- Host TZ leaks in all 5 sessions: the auto-preset path does not set `intl:timezone`. Callers needing TZ spoof must use `WithGeoIP(true)` or set `Config.Locale.Timezone` directly. Open item for documentation.

## What the integration test does NOT validate

1. **Post-patch behavior of `webrtc-ip-spoofing2.patch` and `canvas-spoofing.patch`.** Both patches live in `patches/` but `make build` was not executed (Linux-only Firefox toolchain). The Mac binary tested here is upstream-only. Post-patch acceptance metrics are in plan section P7.
2. **Real WebRTC peer connection.** Jitsi/Whereby validation deferred until a patched build exists.
3. **Sequence of N sessions against CreepJS / BrowserLeaks / AmIUnique** for uniqueness ratio. The full P0-T2 harness times out per session on the current macOS network path; single-session results captured here are representative of one-shot behavior, not the 10-session ratio target.

## Harness files

```
goapi/example/baseline/main.go        # multi-oracle CSV harness (timeout per probe needs raising for slow nets)
goapi/example/integration/main.go     # 4-oracle JSON dump used here
goapi/example/canvas/main.go          # determinism smoke
goapi/example/creepjs-probe/main.go   # one-shot CreepJS DOM dump used to derive the new selectors
goapi/example/botdetect/main.go       # extended bot-detection probe (sannysoft+arh+rebrowser+browserleaks_js+webgl) — written but not exercised this run
```

Results JSON: `goapi/integration-results/{creepjs,sannysoft,areyouheadless,browserleaks_webrtc}.json`.

## Next actions

1. Run a patched Camoufox build (Docker `make build` on a Linux host or VM) and rerun `goapi/example/integration` + `goapi/example/canvas`. Expected deltas: `ctx2 read1` hash diverges from `ctx1`; BrowserLeaks `Public IP` shows the value set via `WithWebRTCLocalIP` or the config preset.
2. Fix `goapi/example/baseline` per-probe timeouts (currently a single session-wide deadline starves later probes when CreepJS takes 90s).
3. Decide whether to bring SDP `THIS_IS_SDPARTA-99.0` origin-string rewrite into scope. Detectable across UA/SDP mismatch but distinct from the WebRTC IP plan — separate ticket.
