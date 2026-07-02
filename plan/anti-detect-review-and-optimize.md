# Camoufox anti-detect — review + optimization plan (2026-07-02)

Reviews the anti-detection surface and prioritizes the remaining optimization work.
Builds on (does not duplicate) `plan/device-faking-targets.md` and `plan/optimize-for-donut.md`.

---

## 1. What Camoufox is (architecture)

Anti-detect Firefox fork. Spoofing lives at the **C++/Gecko level**, not injected JS — so it
survives `Function.prototype.toString`/`getOwnPropertyDescriptor` lie-detection that breaks every
JS-injection stealth tool. Four layers:

1. **Patches (`patches/*.patch`)** — ~35 diffs against Firefox source. Most follow a *Manager
   pattern*: a new `*Manager.cpp/.h` under `dom/base/`, wired through `moz.build` +
   `Window.webidl` + `nsGlobalWindowInner`, reading spoof values from a shared config header.
   Applied by `scripts/patch.py` (globs the whole `patches/` dir → **all** patches ship in a
   local build).
2. **Config contract (`additions/camoucfg/MaskConfig.hpp`)** — reads a JSON blob from
   `CAMOU_CONFIG[_N]` env vars once (`std::call_once`), exposes typed getters the patched Gecko
   getters call. Missing key → `std::nullopt` → engine falls through to real behavior.
3. **Producers** — `goapi/` (Go driver, this fork's addition) and donutbrowser (Rust) both emit
   the CAMOU keys + override prefs. `pythonlib/` = BrowserForge-based launcher.
4. **Automation transport** — patched **Juggler** (not CDP) with an isolated page copy, so
   Playwright leaves no `window.__playwright__` traces and getter/listener reads are invisible.

**Spoofing coverage (strong):** navigator, screen/window geometry, canvas 2D + WebGL readPixels
(seeded per-context noise), WebGL params/vendor/renderer/extensions, audio (AnalyserNode/AudioBuffer
noise + AudioContext sampleRate/latency), fonts (per-glyph spacing perturbation + font-list
restriction + system-ui mapping), timezone (SpiderMonkey `DateTime`), locale/language + HTTP
`Accept-Language`, geolocation, WebRTC IP (ICE/SDP), media codecs/`mediaCapabilities`, media-device
counts, speech voices, battery, CSS media features, screen.orientation, touch trio, WebGPU (disabled).

**Behavioral:** C++ Bezier human-cursor (`MouseTrajectories.hpp`); Juggler routes input through
Firefox's real handlers; headless patched to look headed (+ Python virtual-display fallback).

**Identity rotation:** BrowserForge generates fingerprints matching real-world market-share
distribution; goapi `WithGeoIP` can bind timezone/locale/WebRTC-IP to the proxy's region.

---

## 2. Verified current state (2026-07-02)

- **Passing** (integration test vs oracles): headless (CreepJS `0% like headless`, AreYouHeadless),
  webdriver/automation (sannysoft all `ok`, `navigator.webdriver=false`), WebRTC LAN leak
  (mDNS `no_host` on).
- **Device-faking surface declared SATURATED** — the 2026-06-30 audit ran 8 remaining P1/P2
  targets against real FF150 source and shipped **0**: each was already covered or not a real
  host/OS leak. → *More C++ device-faking patches are NOT the leverage.*
- **The real gap = an unverified build.** The 7 new spoofs (WebGPU-off, media-codec matrix, CSS
  media, screen.orientation, touch trio, voices-lang, readPixels) are "landed, **CI-build-verify
  pending**." The WebRTC-IP + canvas-per-context patches are written and in the build series but
  **never proven in a shipped binary** — the integration test ran against the *official prebuilt*
  150.0.2-beta.25, which predates them (hence its "public-IP leak" and "canvas cross-context fail"
  are stale, not real regressions).

---

## 3. Optimization plan (priority-ranked, each with a verify step)

> **Execution status (2026-07-02).** Adversarial verification of the P0 data-fixes flipped two of
> them: **T2 and T3 were premised on the integration doc's assumptions and are actually regressions
> — dropped with evidence below.** T4/T7/T10 are implemented + `go test`-verified. T1's build is
> in flight (CI). T5/T6/T8/T9 remain frontier/build-gated and are staged, not shipped blind.

### P0 — Prove the pipeline. Cheap, high-value, no new C++.

**T1. Build + integration-test a binary with the local patch set.**  *(build in progress)*
This is the single highest-leverage action: everything "verify-pending" is unknown until one
build runs the full oracle suite. Build applies **all** `patches/*.patch` via `scripts/patch.py`,
so the WebRTC-IP + canvas + 7 device-faking patches ship in it.
→ *Verify:* a green `smoke` run (full `go test -timeout 15m ./...`) against the freshly-built
artifact. **Status:** build.yml run `28571897480` (fix-integration-findings, current HEAD patches)
in progress; dispatch smoke.yml against it on completion.

**T2. ~~Fix WebGL vendor to "Mozilla".~~ DROPPED — verified regression.**
Premise was false. `fingerprint-presets.json` pairs **Windows Firefox UAs** with
`unmaskedVendor: "Google Inc. (Intel/AMD/NVIDIA)"` + `ANGLE (… Direct3D11 vs_5_0 ps_5_0)`
renderers — and the renderer has **no trailing `, D3D11)`**, i.e. the *Firefox* ANGLE format, not
Chrome's. Firefox on Windows renders WebGL through ANGLE and genuinely reports `Google Inc. (…)`
as the unmasked vendor (web-confirmed: *"In Firefox, the Unmasked Vendor typically shows 'Google
Inc.' when using ANGLE with Direct3D11"*). The data is real and coherent. Forcing `"Mozilla"` would
pair a Mozilla vendor with an ANGLE/D3D renderer — the exact vendor↔renderer contradiction this
plan warns against. The masked `gl.VENDOR` already stays `"Mozilla"` (patch default); only the
*unmasked* value carries the GPU, correctly. **No change. Guarded by T7.**

**T3. ~~Rewrite the SDP `THIS_IS_SDPARTA-99.0` marker.~~ DROPPED — verified regression.**
The `99.0` comes from **stock Firefox source** — camoufox's `SanitizeSDPForIPLeak` only rewrites
IP addresses / candidate lines and never touches the origin version (confirmed in the patch body).
Mozilla froze this marker upstream (all Firefox ≥99 emit `THIS_IS_SDPARTA-99.0` regardless of the
real version), so it is herd behavior, not a camoufox tell. Rewriting it to track the UA rv would
make camoufox the **only** browser whose SDP version ≠ 99.0 — a de-anonymizing regression. The
original doc even flagged it "not part of current plan." **No change.**

**T4. Close the timezone default gap.**  *(DONE — `go test`-verified)*
Auto-preset path leaks host TZ unless `WithGeoIP(true)` or explicit `Config.Timezone`. Presets
carry **no** timezone, so auto-setting one would fabricate a value that may contradict the proxy —
the correct fix is to warn, not guess. Added `leakWarnings()`/`emitLeakWarnings()` in
`goapi/warnings.go` (mirrors pythonlib `_warnings.py`): a proxy set without geoip and without an
explicit tz/locale prints a `LEAK WARNING` to stderr from `Launch`.
→ *Verify:* `go test ./goapi -run TestLeakWarning` → **PASS** (`warnings_test.go`).

### P1 — Coherence (the meta-risk). Needs datasets, medium effort.

**T5. Per-renderer WebGL dataset.**  *(staged — dataset port + build-gated)*
goapi presets emit renderer/vendor strings but **no** `getParameter`/`getShaderPrecisionFormat`/
`contextAttributes` data → those leak host values (CreepJS internal inconsistency). Port
`pythonlib/camoufox/webgl/webgl_data.db` (sqlite, present) into a per-renderer template. Deferred
here because the browser-side effect is unverifiable without T1's build, and blind numeric params
would themselves be a tell. Next step: read the sqlite schema, map renderer→params, emit under
`webGl:parameters`; unit-test the Go mapping, then confirm via smoke.

**T6. Geo→language population-weighted table.**  *(staged — dataset port)*
Bind `navigator.language(s)` to region using a population-weighted territory→language map.
`pythonlib/camoufox/territoryInfo.xml` + `locales.py` hold the CLDR data. Next step: parse
territoryInfo into a Go map, set `locale:*`/`navigator.language` in `applyGeo`, unit-test
region→language.

**T7. One-profile coherence validator.**  *(DONE — `go test`-verified)*
Added `TestPresetCoherence` (`goapi/pkg/fingerprint/coherence_test.go`): every bundled preset must
agree platform ↔ WebGL identity ↔ speech-voice family. Catches the impossible-device class
(Windows UA + Apple GPU; macOS UA + Direct3D/ANGLE renderer; ANGLE renderer off Windows; wrong
voice family). → *Verify:* `go test ./goapi/pkg/fingerprint -run TestPresetCoherence` → **PASS**
(0 violations across all windows/macos/linux presets).

### P2 — Realism (spoofed-but-detectable-as-spoofed). Hard, lower ROI.

**T8.**  *(staged — high effort, low ROI)* Audio LCG delta and canvas-2D noise distributions are
themselves CreepJS "lie" signals. Shape perturbation toward a real-device distribution. Defer
behind P0/P1; browser-verification-gated.

### Infra — producer robustness (not a spoof, but gates trust)

**T9. goapi platform coverage.**  *(staged — infra, build-gated)*
goapi is v0.1, smoke-tested **macOS-arm64 only** — no Windows Juggler pipe transport, Linux
untested, WebGL/Network RPC domains unexercised. Patch-companion knobs (`WithCanvasNoise`,
`WithWebRTCLocalIP`, `WithMDNSObfuscation`) silently no-op on a stock binary. Next step: add
Windows-pipe transport + a Linux smoke leg once T1's build artifact exists.

**T10. Producer↔schema drift guard.**  *(DONE — `go test`-verified)*
Added `TestProducerSchemaDrift` (`goapi/pkg/config/drift_test.go`): reflects config.go's
`CAMOU_CONFIG` keys, diffs against `settings/properties.json`. Every schema key must have a
producer field; every producer key must be registered or in a documented-lag allowlist.
**Finding:** config.go is a superset — 7 live patch keys (`cssMedia:*`, `mediaCapabilities:*`,
`screen:orientation[Angle]`) ship in patches but are **absent from `properties.json`**; frozen in
`knownConfigOnlyKeys` so the canonical schema should register them, and any *new* drift fails.
→ *Verify:* `go test ./goapi/pkg/config -run TestProducerSchemaDrift` → **PASS**.

---

## 4. Explicit non-goals (already decided — do not redo)

- More C++ device-faking patches — surface saturated (2026-06-30 audit).
- Enabling `privacy.fingerprintingProtection` — rejected; normalizing fights the "blend as a real
  device" model and leaves FPP's own tells.
- DOMRect sub-pixel noise — breaks goapi's own click/scroll targeting.
- Full WebGPU adapter spoof — `dom.webgpu.enabled=false` is the terminal pragmatic choice.
- WebRTC per-OS SDP codec templating — low cross-OS entropy, not worth it.

---

## 5. Sequencing

T1 gates everything (nothing is real until a patched binary is oracle-tested). T2–T4 are cheap
data/patch edits that ride the same build. T5–T7 are the coherence dataset work — the actual
frontier now that the device-faking surface is saturated. T8 last.
