# Camoufox Device-Faking Target List

> Engineering-ready spoofing target inventory for the Camoufox FF150 fork. Verified in-tree against the actual patch set, `settings/`, `assets/`, and `goapi/`. Mechanism vocabulary: **pref** (`settings/camoufox.cfg` / `defaultPref` / `assets/*.mozconfig`), **C++ patch** (`patches/*.patch` against Gecko), **CAMOU_CONFIG key** (colon-namespaced entry in `settings/properties.json` read by `MaskConfig`), **goapi field** (a `config.Config` field plus a `WithX` `Option` in `goapi/options.go`).

## Executive summary

Camoufox's per-value spoofing layer (navigator, screen, canvas2D, audio, WebGL metadata, fonts, voices, timezone/locale, WebRTC IP) is strong and — critically — implemented at the C++/Gecko level, so it survives the `Function.prototype.toString` lie-detection that breaks every JS-injection stealth tool. But the survivable structural advantage hides two distinct classes of remaining risk:

1. **Untouched hardware surfaces that contradict the spoofed WebGL identity.** Above all **WebGPU adapter info** (live on Windows/macOS in FF150 because there is no `dom.webgpu.enabled=false` pref in-tree), plus the **media-codec / `mediaCapabilities` HW-decode matrix**, **WebRTC codec/SDP capabilities**, **sub-pixel DOMRect geometry**, **WebGL pixel readback** (a confirmed unwired TODO stub at `patches/canvas-spoofing.patch:469,497`), and a family of **CSS `matchMedia` features** (color-gamut, dynamic-range, pointer/hover, prefers-\*) that leak the real monitor and OS.

2. **Surfaces camoufox already spoofs but in an OS-incoherent or detectable-as-spoofed way.** This is the blind spot the critic surfaced: canvas/audio/WebGL/fonts/voices are treated as "covered strengths" when each is actually either **config-driven-without-OS-coherence** (WebGL parameters vs renderer string; the `voices` list has no platform binding; the font list has no OS mapping) or **spoofed-but-statistically-anomalous** (the audio LCG delta and the canvas 2D noise are themselves CreepJS "lie" signals). And glyph/emoji *shape* — Segoe UI Emoji vs Apple Color Emoji vs Noto — is an OS tell that pixel-noise and rect-rounding cannot hide.

The single highest-leverage **enabler** is to stop running with `privacy.fingerprintingProtection` off and instead enable it with a curated `overrides` allow-list, which delivers Mozilla's own normalizers (keyboard layout, fdlibm math, screen orientation, disk-quota, frame-rate, media-capabilities, the CSS media features) "for free" while explicitly excluding the canvas/audio/WebGL/navigator targets camoufox already owns.

The unifying meta-risk is **cross-signal coherence**, and it now has two coherence units, not one: a **GPU/codec coherence unit** (WebGPU ↔ WebGL renderer ↔ WebGL parameters/extensions ↔ media codecs ↔ WebRTC SDP) and an **OS-text-rendering + audio-realism coherence unit** (voices ↔ emoji/glyph shape ↔ measureText ↔ font list ↔ audio baseline). Detectors cross-check the second unit against `navigator.platform`/UA far more cheaply than they probe WebGPU. Every new spoof must be derived from one BrowserForge base OS profile and preserve native prototype placement / key order, or it trades one leak for a lie.

## Implementation status & verification corrections (2026-06-29)

Three findings were corrected after verifying against FF150 reality before coding:

- **#12 Math fdlibm — DROPPED (false gap).** `javascript.options.use_fdlibm_for_sin_cos_tan` has been Firefox-default **`true`** since ~FF93; fdlibm is a software implementation, so `sin/cos/tan` are already cross-OS-deterministic in stock FF150. Setting the pref normalizes nothing. (A wider RFP-`JSMathFdlibm` covers more functions, but only via master FPP — see next.)
- **#5 Enable master FPP — DROPPED (philosophy conflict).** `privacy.fingerprintingProtection` applies Mozilla's *uniform* RFP normalizers, which is the opposite of camoufox's "blend as a real device" model and leaves FPP's own detectable tells. `settings/camoufox.cfg:336` keeps RFP off on purpose ("This will actually hurt fingerprinting"). The surfaces FPP would have normalized (keyboard/orientation/quota/framerate/media-caps/CSS-media) must instead be spoofed to **real per-OS values** via C++/CAMOU keys, not normalized. This invalidates the "free normalizers" mechanism cited under #6/#8/#11/#18/#19/#20/#32/#33/#35 — each needs a real-value spoof instead.
- **#1 WebGPU — interim shipped as a pref; full spoof still open.** Verified: FF150 ships WebGPU **on by default** on Windows (FF141) and Apple-Silicon macOS (FF145); Linux stable is still off. So the live adapter leak is real for Win/recent-Mac profiles. Interim `defaultPref("dom.webgpu.enabled", false)` landed in `settings/camoufox.cfg` (authentic-absent for Linux profiles, low-entropy "missing" tell for Windows). Full C++ adapter spoof remains the real fix.

**Landed this round (verifiable without a Firefox build):**
- **#13 voices ↔ OS lang/localService** — `goapi/pkg/fingerprint`: `loadVoices` now preserves each voice's real `lang`/`localService` (parsed from the `Name:lang:type` data) instead of stamping `en-US`/`true` on every voice; generator resolves per chosen voice. Guarded by `TestVoiceLangCoherence` (Daniel→en-GB, Karen→en-AU). `go test ./...` green.
- **#1 interim** — WebGPU disabled in `settings/camoufox.cfg` (build-verify pending).

**Landed (CI-build-verify pending) — #8 CSS media features:**
New `patches/css-media-spoofing.patch` hooks three `Gecko_MediaFeatures_*` getters in `layout/style/nsMediaFeatures.cpp` to answer from config: `ColorGamut` (was `dx->GetColorGamut()` → leaks P3/Rec2020 monitor), `VideoDynamicRange` (was `dx->GetScreenIsHDR()`, RFP-gated=off → leaks HDR), and `PrefersColorScheme` (was forced dark globally via `ui.systemUsesDarkTheme`). Plain `MaskConfig::GetString` on keys `cssMedia:colorGamut`/`dynamicRange`/`prefersColorScheme` (no new MaskConfig methods); `layout/style/moz.build` gets `LOCAL_INCLUDES += ["/camoucfg"]`. goapi defaults per-profile: srgb gamut, standard range, and a per-profile-random light/dark color-scheme (breaks the all-dark correlation). `DynamicRange` already returns Standard in FF150, so it's left alone. **`PrefersReducedMotion` is deliberately NOT hooked** — the Playwright patch (`patches/playwright/0-playwright.patch`, applied before this one) already rewrites it to `aDocument->PrefersReducedMotion()` (emulation accessor, no host LookAndFeel leak); a first build attempt collided with that rewrite (`nsMediaFeatures.cpp.rej` on the reduced-motion hunk), so the hook was dropped and the surface left to Playwright. Guarded by `TestCSSMediaDefaults`; patch verified to apply (gpatch 2.8 + BSD) and the three hooks confirmed to apply on CI on top of the Playwright-modified file. `go test ./...` green.

**Landed (CI-build-verify pending) — #6 media codec / `mediaCapabilities` matrix:**
New `patches/media-codec-spoofing.patch` hooks all three read surfaces coherently from one config so a cross-OS profile can't leak the host's real decoder support: `HTMLMediaElement::CanPlayType`, `MediaSource::IsTypeSupported` (both via `MaskConfig::GetMediaCanPlayType`, a codec-substring map → `probably`/`maybe`/`""`), and `MediaCapabilities::CreateMediaCapabilitiesDecodingInfo` (resolves early with `MaskConfig::GetMediaDecodingInfo` → supported/smooth/powerEfficient). MaskConfig keys `mediaCapabilities:canPlayType` / `mediaCapabilities:decodingInfo`. goapi `config.Config.MediaCanPlayType`/`MediaDecodingInfo` + generator populate per-OS automatically — HEVC (`hvc1`/`hev1`) `probably`+HW on Windows/macOS, unsupported on Linux (matches FF150 reality). Spoofing all three together avoids the cross-API inconsistency a single-surface spoof would create. EME queries (`decodingInfo` with `keySystemConfiguration`) fall through to the real resolver so `mediaKeySystemAccess` stays correct (the spoof short-circuit is gated on `!mKeySystemConfiguration.WasPassed()` — fix from PR #4 review). Accepted tradeoffs: the `decodingInfo` hook keys off the video content type when both audio+video are passed (audio fourccs won't contain `hvc1`/`hev1`, so no false match in practice); `isTypeSupported` short-circuits before `MakeMediaContainerType` validation for a config-matched substring; and a hand-written config that sets only one of the two map keys can diverge (the generator always sets both coherently). Guarded by `TestMediaCodecProfile` (hvc1+hev1 parity, smooth/powerEfficient, user-config-not-clobbered); patch verified to apply under strict GNU patch 2.8 + BSD against pristine FF150. `go test ./...` green.

**Landed (CI-build-verified) — #10 WebGL `readPixels` perturbation:**
The pre-existing stub (`canvas-spoofing.patch`) was both stale and misplaced — it targeted the PBO/offset `ReadPixels` overload (no client buffer to perturb) at FF146-era line ~3120, and its `index 0000000000..` (git new-file marker) made GNU patch ≥2.8 silently skip the whole hunk. Re-authored against real FF150 source: the hunk now hooks the `ArrayBufferView` overload right after `DoReadPixels` succeeds (the same spot FF's own `nsRFPService::RandomizeElements` runs, which is inert because camoufox keeps RFP off), perturbing `range->data()/size_bytes()` with `CanvasSeedManager` (seed from `GetOwnerDoc()`→`SeedFromDocument`, mirroring the 2D path). No-ops when seed==0 or in offscreen/worker (no owner doc). Verified to apply under strict GNU patch 2.8 + BSD patch against pristine FF150.

**Reassessed after FF150-source inspection (2026-06-30):**
- **#1-full WebGPU adapter spoof — deferred (premise corrected).** FF150 already returns **empty strings** for all four web-facing `GPUAdapterInfo` getters (`Adapter.h:60-63`: `GetVendor`/`GetArchitecture`/`GetDevice`/`GetDescription` → `nsString()`); the `WgpuVendor`/`GetWgpuName` accessors are about:support-only, not web-exposed. So the adapter *string* leak the doc described does not exist on FF150. The real WebGPU fingerprint is `adapter.limits` (≈31 numeric caps) + `adapter.features` (set) + subgroup sizes — all hardware-dependent. Spoofing those to a coherent per-GPU profile needs an accurate per-GPU limits/features dataset that isn't available in-tree; fabricated values are themselves a cross-check tell. The interim `dom.webgpu.enabled=false` (#1, shipped) therefore stands as the pragmatic terminal choice — it closes the real limits/features leak and is authentic-absent for Linux profiles.
- **#7 WebRTC SDP codecs — deprioritized (low signal).** Firefox uses one libwebrtc build across desktop OSes, so the software codec list / fmtp / header-extension set is largely OS-consistent; the OS-variable part is HW-H.264 availability, which overlaps the #6 codec matrix already shipped. Heavy per-OS SDP templating for marginal cross-OS entropy — not worth it ahead of higher-value surfaces.

**Reassessed after FF150-source inspection (2026-06-29, dropped):**
- **#9 DOMRect — dropped for camoufox (self-harming).** `DOMRect::SetLayoutRect` is the `getBoundingClientRect`/`getClientRects` chokepoint and has no RFP hook in FF150, so perturbing there is mechanically possible — but camoufox is automation-driven and `goapi/{actions,element,modal,wait}.go` compute click/scroll coordinates from `getBoundingClientRect` + `Page.getContentQuads`. Noising DOMRect corrupts camoufox's own click targeting. A privacy browser tolerates this; an automation browser cannot. Only a sub-pixel-below-click-precision variant would be safe, and its detection benefit is unproven — not worth the regression risk.
- **#16 mediaDevices deviceId/groupId/labels — dropped (already handled by FF150).** `MediaDevices.cpp:473` runs `AnonymizeDevices` (per-origin deviceId SHA) and `:504-509` gate `mID`/`mGroupID`/label behind `exposeInfo`/`exposeLabel` (permission). camoufox's count-control fake devices flow through this pipeline, so deviceId is per-origin-anonymized and labels are perm-gated already. The doc's premise ("counts-only leaves all three wrong") is false for FF150; only a minor groupId in/out-coherence gap remains (low entropy).

**Re-scoped:**
- **#2/#15 webgl param ↔ renderer coherence** — the goapi generator already derives fonts/voices/screen/webgl-renderer from one preset, but presets carry **no** webGl `parameters`/`extensions`/`shaderPrecision` data, so a per-renderer bundle can't be generated in Go without new data. Needs a per-renderer template dataset (out of pure-Go scope).
- **Batch C (C++ Gecko patches: #1-full, #6, #7, #9, #10, #16)** — each is source-tree-gated (the local network blocks `mozilla.org`, so `make fetch` can't pull FF150 source) and verifiable only via a ~3h CI build. #10's `ReadPixels` stub (`canvas-spoofing.patch:496`) is explicitly blocked on inspecting the FF150 `ClientWebGLContext::ReadPixels` ArrayBufferView accessor; authoring any of these blind risks compile/crash in graphics/IPC paths. Pending a decision to either enable `mozilla.org` for local source access or CI-iterate.

## Priority table

| # | Surface | Status | Priority | Effort | Mechanism |
|---|---------|--------|----------|--------|-----------|
| 1 | WebGPU adapter info / limits / features | missing | **P0** | S→L | pref now (`dom.webgpu.enabled=false`) → C++ patch + CAMOU keys later |
| 2 | Cross-signal coherence (one base profile) | partial | **P0** | M | build/fingerprint-generator discipline; subsumes #15 |
| 3 | Timezone/locale auto-bind to proxy IP | covered/harden | **P0** | S | goapi `WithGeoIP` wiring + config |
| 4 | `navigator.webdriver` false under Juggler | covered/verify | **P0** | S | verify C++ patch |
| 5 | Enable FPP with curated `overrides` allow-list | missing | **P1** | M | pref (`privacy.fingerprintingProtection`) |
| 6 | Media codec / `mediaCapabilities` HW-decode matrix | missing | **P1** | M | FPP `+MediaCapabilities` + C++ patch + CAMOU keys |
| 7 | WebRTC `getCapabilities` codec / SDP / fmtp | missing | **P1** | M–L | C++ patch (canonical per-OS SDP profile) |
| 8 | CSS media features (gamut/HDR/prefers-\*/forced-colors) | partial | **P1** | M | FPP `+CSS*` + CAMOU keys |
| 9 | DOMRect / `getClientRects` sub-pixel geometry | missing | **P1** | M | C++ patch (RFP-rounding or seed noise) |
| 10 | WebGL `readPixels` pixel-readback noise | partial (stub) | **P1** | M | C++ patch — wire existing TODO |
| 11 | Keyboard layout (`KeyboardEvent.code/key`) | missing | **P1** | S | FPP `+KeyboardEvents` |
| 12 | Math fdlibm (trig LSB) | missing | **P1** | S | pref (`use_fdlibm_for_sin_cos_tan`) |
| 13 | SpeechSynthesis voices ↔ OS/UA consistency | partial (no OS binding) | **P1** | M | bind `voices` CAMOU key to OS profile + goapi field |
| 14 | Emoji / font-glyph OS-shape leak (canvas + DOMRect) | missing | **P1** | L | bundle OS emoji/font files + C++ fallback routing + CAMOU key |
| 15 | WebGL parameters/extensions ↔ renderer coherence | partial (no validation) | **P1** | M | per-renderer template in fingerprint generator (req. of #2) |
| 16 | mediaDevices `deviceId`/`groupId`/label behavior | partial | **P1** | M | C++ patch (per-origin SHA, perm-gated labels) + CAMOU key |
| 17 | Canvas `measureText`/TextMetrics rounding ↔ fonts | partial | **P1** | M | C++ canvas hook (seed rounding tied to font template) |
| 18 | `StorageManager.estimate()` quota | missing | **P2** | S | FPP `+DiskStorageLimit` |
| 19 | Display refresh rate (rAF cadence) | missing | **P2** | S | FPP `+FrameRate` |
| 20 | `screen.orientation` type/angle | missing | **P2** | S–M | FPP `+ScreenOrientation` + CAMOU key |
| 21 | Battery `getBattery` exposure audit | partial/likely-wrong | **P2** | S | keep API absent for content (audit `battery:*` keys) |
| 22 | Permissions API coherence + supported-name set | partial | **P2** | M | C++ patch (align query/Notification/getUserMedia) |
| 23 | Touch trio (maxTouchPoints/ontouchstart/TouchEvent) | partial | **P2** | S | derive together from device class |
| 24 | DPR vs `(resolution)`/`(-moz-device-pixel-ratio)` MQ | partial | **P2** | S | tie MQ to spoofed DPR (C++) |
| 25 | prefers-color-scheme per-profile (now globally dark) | partial | **P2** | S | per-profile pref instead of global |
| 26 | CSS pointer/hover per-profile (now hardcoded fine+hover) | partial | **P2** | S | derive from device class (replace force-default-pointer) |
| 27 | DOM property set / key-order parity | partial | **P2** | M | constraint on all new spoofs |
| 28 | plugins/mimeTypes content parity | covered/verify | **P2** | S | assert FF 5-entry set |
| 29 | Intl `resolvedOptions` / formatting consistency | partial/verify | **P2** | S–M | verify+extend locale patch (calendar/numberingSystem/separators) |
| 30 | Audio realism (LCG delta is detectable-as-spoofed) | partial/weak | **P2** | M | C++ patch — real-device baseline + hardware-shaped jitter |
| 31 | Canvas 2D noise distribution realism | partial/weak | **P2** | M | C++ patch — shape perturbation to real-device distribution |
| 32 | Firefox video metrics (`moz*Frames`, playback quality) | missing | **P3** | S | FPP `+VideoElementMoz*` |
| 33 | `-moz-osx-font-smoothing` normalization | missing | **P3** | S | FPP `+DOMStyleOsxFontSmoothing` |
| 34 | Timer precision pin (incl. COOP/COEP path) | partial | **P3** | S | pin `reduceTimerPrecision` prefs |
| 35 | Gamepad enumeration gate | mostly covered | **P3** | S | FPP `+Gamepad` (optional) |

---

## P0 — detectors flag it AND camoufox is missing/wrong

### 1. WebGPU adapter info / limits / features — MISSING
- **API:** `navigator.gpu.requestAdapter().info` `{vendor, architecture, device, description, subgroup*}`; `GPUAdapter.limits` (~31 numeric tiers); `GPUAdapter.features` (Set); `isFallbackAdapter`; `getPreferredCanvasFormat()`; WGSL compute output.
- **Status:** No `dom.webgpu.enabled` pref exists in `settings/camoufox.cfg`, `assets/*.mozconfig`, or any patch (the only `webgpu` hit is an unrelated upstream `#include "mozilla/webgpu/Instance.h"` in `patches/navigator-spoofing.patch:205`). The build inherits the FF150 upstream default: **WebGPU ON for Windows and Apple-Silicon macOS, off on Linux.** No WebGPU key in `settings/properties.json`.
- **Why it leaks:** `browserleaks.com/webgpu`, CreepJS, Scrapfly GPU DB read the real host GPU vendor/architecture/device + full limits vector and **cross-check it against the spoofed `UNMASKED_RENDERER_WEBGL`**. Single largest unspoofed hardware leak; an instant mismatch on any Win/Mac host.
- **OSS:** Tor & Mullvad disable it (`dom.webgpu.enabled=false`); FF RFP/FPP quantizes limits into coarse tiers (`WebGPULimits #64`, `WebGPUIsFallbackAdapter #65`, `WebGPUSubgroupSizes #66`); BotBrowser spoofs `GPUAdapterInfo`+limits+features from one coherent device profile and force-aligns to the WebGL renderer.
- **Mechanism:** **Quick win (S, pref):** `defaultPref("dom.webgpu.enabled", false)` in `settings/camoufox.cfg` — matches Tor/Mullvad/Linux-FF, removes the contradiction immediately. **Full fix (L, C++ patch + CAMOU keys + goapi):** new patch overriding `GPUAdapterInfo` getters + limits/features driven by `CAMOU_CONFIG` keys `webGpu:vendor` / `webGpu:architecture` / `webGpu:device` / `webGpu:description` / `webGpu:limits` (dict) / `webGpu:features` (array), seeded from the same BrowserForge GPU profile as `webGl:renderer`; surface via a `config.Config.WebGPU*` field set by the fingerprint generator. Must be done at the engine level like the existing WebGL patch — JS `Object.defineProperty` is itself `toString`-detectable.
- **Recommendation:** ship the pref now (closes the P0 mismatch), schedule the coherent spoof.

### 2. Cross-signal coherence — PARTIAL
- **Why it leaks:** CreepJS scores "lies" by checking whether the whole forms a believable device — Windows UA ⇒ Windows GPU string ⇒ Windows fonts/codecs/Math/timezone-for-the-IP. Partial coverage that fixes one field but not its dependents (spoofed macOS UA but Linux GPU; a `screen.orientation` value that disagrees with spoofed dims; an `Apple M2` renderer with NVIDIA-shaped `MAX_TEXTURE_SIZE`) is worse than no spoof.
- **OSS:** BotBrowser ships whole `--bot-profile`s; `daijro/browserforge` generates statistically-coherent fingerprints from real-world frequency data.
- **Mechanism:** every `CAMOU_CONFIG` value (and every new key in this doc) must be derived from one BrowserForge base OS profile in the goapi fingerprint generator. Treat **two explicit coherence units**: (a) **GPU/codec** = WebGPU(#1) ↔ `webGl:renderer` ↔ `webGl:parameters`/extensions(#15) ↔ media codecs(#6) ↔ WebRTC SDP(#7); (b) **OS-text-rendering + audio** = voices(#13) ↔ emoji/glyph shape(#14) ↔ measureText(#17) ↔ font list ↔ audio baseline(#30). **Subsumes #15** as a hard validation requirement: reject any profile whose WebGL parameter set / extension set / shader-precision dict is not drawn from the per-renderer template (no mix-and-match). Implement as a validation pass in the generator that fails the build/launch on cross-unit disagreement.

### 3. Timezone/locale ↔ proxy-IP geo-consistency — COVERED, harden
- Camoufox already spoofs `timezone` + `locale:{language,region,script,all}` coherently (`patches/timezone-spoofing.patch`, `patches/locale-spoofing.patch`). DataDome/Akamai compare JS timezone/`languages`/`Accept-Language` against exit-IP GeoIP.
- **Mechanism:** auto-derive these from the proxy IP via the existing goapi `WithGeoIP(true)` path (`goapi/options.go`) so they cannot drift from manual config; assert the derived values flow into the timezone/locale CAMOU keys.

### 4. `navigator.webdriver` false under Juggler — COVERED, verify
- FF returns `webdriver=true` under Marionette/remote automation (`dom.webdriver.enabled`); the Playwright/Juggler patch sets `Navigator::Webdriver()=false`.
- **Mechanism:** verify (test) it reports false under the Juggler launch path and that no Marionette/`@@juggler` globals leak. C++-level ⇒ no `toString` lie. No new field needed.

**P0 covered — do not regress:** `Function.prototype.toString` native-code integrity (structural advantage of C++ patching — never spoof in injected JS); WebRTC IP (`webrtc:ipv4/ipv6/localip*`, keep srflx == proxy exit); TLS JA3/JA4 + HTTP/2 + header order (genuine NSS stack — do not route through a non-FF proxy that rewrites the handshake).

---

## P1 — high-entropy gaps and OS-coherence failures

### 5. Enable FPP with a curated `overrides` allow-list — MISSING (the enabler)
- **Current:** `privacy.resistFingerprinting=false` (`settings/camoufox.cfg:336`) and no `privacy.fingerprintingProtection` set ⇒ **none** of Mozilla's per-target normalizers run.
- **Mechanism (pref):**
  `privacy.fingerprintingProtection=true` +
  `privacy.fingerprintingProtection.overrides="-AllTargets,+KeyboardEvents,+JSMathFdlibm,+ScreenOrientation,+DiskStorageLimit,+FrameRate,+MediaCapabilities,+WebGPULimits,+WebGPUIsFallbackAdapter,+CSSPrefersReducedMotion,+CSSPrefersContrast,+CSSPrefersReducedTransparency,+CSSInvertedColors,+CSSColorInfo,+CSSVideoDynamicRange,+CSSResolution,+CSSDeviceSize,+VideoElementMozFrames,+VideoElementMozFrameDelay,+VideoElementPlaybackQuality,+DOMStyleOsxFontSmoothing,+Gamepad"`.
  The build already references the `RFPTargets` enum (patches cite `RFPTarget::ScreenPixelDepth`, `CSSPointerCapabilities`). Start from `-AllTargets`; add only what camoufox does **not** already own. Explicitly **exclude** `CanvasRandomization`, `AudioContext`, `WebGLRenderInfo`, `Navigator*`, `ScreenPixelDepth` (camoufox owns these; double-normalizing fights its values).
- Resolves items 11, 12, 18, 19, 32, 33 and most of 8, partially 6. Validate each target does not clobber a camoufox-owned value before shipping.

### 6. Media codec / `mediaCapabilities` HW-decode matrix — MISSING
- **API:** `mediaCapabilities.decodingInfo()/encodingInfo()` `{supported, smooth, powerEfficient}`, `HTMLMediaElement.canPlayType()`, `MediaSource.isTypeSupported()`, `MediaRecorder.isTypeSupported()` (also on `WorkerNavigator`).
- **Why it leaks:** `decodingInfo().powerEfficient/smooth` is true only when the host can **hardware-decode** (FF bug 1569686) — HEVC `probably`+`powerEfficient` implies an Apple/Intel decoder, contradicting a spoofed Linux/AMD WebGL renderer. `canPlayType`/`isTypeSupported` answers depend on OS decoders (H.264/AAC/HEVC/AV1). A Win-UA-on-Linux profile leaks the real OS codec matrix; CreepJS/browserscan/iphey triangulate with WebGPU + WebGL.
- **OSS:** FF FPP `MediaCapabilities #38` / `WebCodecs #71` / `MediaError #50`; BotBrowser `--bot-config-media-types`; browserforge carries `videoCodecs`/`audioCodecs` dicts; apify `overrideCodecs()`.
- **Mechanism:** FPP `+MediaCapabilities` (pref, via #5) normalizes `decodingInfo` smooth/powerEfficient. For the full matrix add a **C++ patch** overriding `canPlayType`/`isTypeSupported` plus new `CAMOU_CONFIG` keys `mediaCapabilities:videoCodecs` / `mediaCapabilities:audioCodecs` (mime→`''|maybe|probably`), seeded from the OS-specific BrowserForge profile; **goapi field** `config.Config.MediaCodecs` populated by the generator (GPU/codec coherence unit, #2).

### 7. WebRTC `getCapabilities` codec / SDP / fmtp — MISSING
- **API:** `RTCRtpSender/Receiver.getCapabilities('video'|'audio')` `{codecs:[{mimeType,clockRate,channels,sdpFmtpLine}], headerExtensions:[{uri}]}`; codec order / `profile-level-id` / RTX/RED/ULPFEC / DTLS fingerprint surfaced in `createOffer()` SDP.
- **Why it leaks:** Live since FF113. Ordered codec list + `sdpFmtpLine` (e.g. H264 `profile-level-id=42e01f`, packetization-mode) + header-extension URIs vary by FF build/platform and whether HW H.264 is present — a persistent cross-origin fingerprint independent of IP. Camoufox spoofs only the IP layer (`patches/webrtc-ip-spoofing*.patch`); the codec/fmtp vector can contradict the spoofed OS/UA.
- **OSS:** double-agent `browser-codecs`; Chrome anti-detects normalize codec list/fmtp/payload-type/header-extension per version. No FF OSS tool covers it today.
- **Mechanism:** **C++ patch** normalizing the codec/extension list to a canonical per-(OS, FF-version) profile, seeded from the base profile (GPU/codec coherence unit, #2). The SDP is "authentically Firefox"; the gap is purely **cross-OS** (Win-UA-on-Linux). Optional CAMOU key `webrtc:codecProfile` to pin the template.

### 8. CSS media features family — PARTIAL
- **API:** `matchMedia` for `prefers-color-scheme`, `prefers-reduced-motion`, `prefers-contrast`, `prefers-reduced-transparency`, `inverted-colors`, `forced-colors`, `color-gamut: srgb|p3|rec2020`, `dynamic-range|video-dynamic-range: high`, `monochrome`, `update`.
- **Why it leaks:** `color-gamut:p3`/`dynamic-range:high` betray a wide-gamut/HDR monitor even when screen dims are spoofed; `prefers-*` leak OS accessibility settings and host theme. FingerprintJS reads each as a discrete source. Camoufox's Playwright patch wires `prefers-reduced-motion`/`prefers-contrast`/`forced-colors`/color-scheme as Playwright `emulateMedia` knobs (`patches/playwright/0-playwright.patch`) but these are **not** CAMOU_CONFIG keys and **not** normalized by default; gamut/HDR/update are unhandled.
- **Mechanism:** FPP `+CSSColorInfo/+CSSVideoDynamicRange/+CSSPrefers*/+CSSInvertedColors/+CSSResolution/+CSSDeviceSize` (pref, via #5) for normalization, plus per-profile **CAMOU keys** `cssMedia:colorGamut` / `cssMedia:dynamicRange` / `cssMedia:prefersColorScheme` so they track the spoofed monitor/OS rather than a fixed global; **goapi field** on the generated profile.

### 9. DOMRect / `getClientRects` sub-pixel geometry — MISSING
- **API:** `Element.getClientRects()/getBoundingClientRect()`, `Range.getBoundingClientRect()` — fractional `{x,y,width,height}` of laid-out text/emoji.
- **Why it leaks:** CreepJS/browserleaks measure fractional widths encoding font metrics + rasterizer + DPI; survives canvas spoofing and reveals the real OS font rendering despite a spoofed platform.
- **OSS:** Tor/RFP rounds rects to integer CSS px; Brave farbles; BotBrowser `--bot-config-noise-client-rects`/`-text-rects`; gologin/multilogin expose a "Client Rects" toggle.
- **Mechanism:** **C++ patch** on `DOMRect` output — RFP-style integer rounding or deterministic per-`fonts:spacing_seed` noise. Note this rounds *position/size* only; it does **not** fix glyph *shape* (see #14).

### 10. WebGL `readPixels` pixel-readback noise — PARTIAL (confirmed stub)
- **API:** `WebGLRenderingContext.readPixels()`, WebGL2 `getBufferSubData()/copyBufferSubData()`, `toDataURL()/toBlob()` on a GL-backed canvas.
- **Status:** `patches/canvas-spoofing.patch:469` carries `// TODO(canvas-spoofing P3): wire ReadPixels perturbation`; `:497` `MOZ_ASSERT(false, "canvas-spoofing P3 stub: ReadPixels not yet wired")`. A rendered-3D pixel hash is **stable/real** and cross-checkable against both the spoofed renderer string and WebGPU, in **both main and worker contexts** (the worker 2D path is already covered at `canvas-spoofing.patch:402-433`, but GL readback is not).
- **OSS:** Brave farbles `readPixels`/`getBufferSubData`/`copyBufferSubData` per session+eTLD+1; BotBrowser `--bot-config-noise-webgl-image`; gologin separates "WebGL Image" from "WebGL Metadata".
- **Mechanism:** **C++ patch** — finish wiring the existing `ClientWebGLContext::ReadPixels` hook with the canvas seed.

### 11. Keyboard layout (`KeyboardEvent.code/key`) — MISSING
- **Why it leaks:** Detectors infer the physical layout (AZERTY/Dvorak/non-US) from `.code` vs `.key`; the real host layout contradicts a spoofed `navigator.language`/locale and reveals the true region/OS.
- **Mechanism:** FPP `+KeyboardEvents` (RFP target #3, pref via #5) spoofs a US-QWERTY layout from physical keycode; later extend to derive from page locale.

### 12. Math fdlibm trig — MISSING
- **Why it leaks:** `Math.sin/cos/tan(...)` LSBs fall through to the host libm under a cross-OS profile, betraying Linux-vs-Windows-vs-macOS. (The broader V8-vs-SpiderMonkey Math fingerprint is **covered** — authentic FF.)
- **Mechanism:** **one pref** — `defaultPref("javascript.options.use_fdlibm_for_sin_cos_tan", true)` (RFP target `JSMathFdlibm #23`). Cheapest fix in this doc.

### 13. SpeechSynthesis voices ↔ OS/UA consistency — PARTIAL (no OS binding)
- **API:** `speechSynthesis.getVoices()` → `[{name, lang, localService, default, voiceURI}]`.
- **Status:** Camoufox **already spoofs voices** — `patches/voice-spoofing.patch`, `patches/speech-voices-spoofing.patch`, keys `voices` / `voices:blockIfNotDefined` / `voices:fakeCompletion` / `voices:fakeCompletion:charsPerSecond` (`settings/properties.json:94-97`) — loading a config-driven list via `MaskConfig::MVoices()` into `nsSynthVoiceRegistry`. But the list has **no OS binding**.
- **Why it leaks:** `getVoices()` is high-entropy and strongly OS-specific. A macOS-UA profile must expose Apple voices (Alex/Samantha/…), Windows the SAPI Microsoft David/Zira/Mark set, Linux eSpeak — and real Firefox exposes **only local voices** (`localService:true`, no Google network voices). A voice list disagreeing with spoofed `platform`/UA, or `fakeCompletion` cadence that doesn't match the claimed voices' synthesis speed, is a clean cross-surface tell (Scrapfly/CreepJS).
- **Mechanism:** in the goapi fingerprint generator, **select the `voices` array (and `voices:fakeCompletion:charsPerSecond`) from a per-OS voice table keyed by the same BrowserForge profile as `navigator.platform`/UA** (OS-text-rendering coherence unit, #2); enforce local-only voices. Expose `config.Config.Voices` populated automatically; optional `WithVoiceProfile(os)` `Option`. No new C++ — the loader already exists; this is a data-binding + validation fix.

### 14. Emoji / font-glyph OS-shape leak — MISSING
- **API:** any canvas/SVG/DOM text draw of emoji or fallback glyphs; read back via canvas hash, `getClientRects`, or `measureText`.
- **Why it leaks:** The biggest unaddressed cross-surface trap. Canvas seed-noise (#31) and DOMRect rounding (#9) perturb pixels and rects but **do not change glyph shape**. Segoe UI Emoji (Win) vs Apple Color Emoji (Mac) vs Noto/Twemoji (Linux), plus OS-specific font fallback and subpixel AA, rasterize to *structurally* different glyphs. A Linux host claiming macOS renders Noto emoji + noise → instantly OS-inconsistent; noise cannot hide it. Detectors draw emoji/fallback glyphs specifically for this.
- **Mechanism:** **heavy, must not be buried under "canvas covered."** Bundle the target OS's emoji/font files (Apple Color Emoji / Segoe UI Emoji / Noto) into the per-profile font set and route gfx/SpiderMonkey font fallback to them via a **C++ patch**, OR apply a shape-level transform; new `CAMOU_CONFIG` keys `fonts:emojiSet` / `fonts:osFallback` selected from the same OS profile as the UA; **goapi field** on the generated font set. Until shipped, treat any macOS/Windows-UA-on-Linux profile as glyph-detectable.

### 15. WebGL parameters/extensions ↔ renderer internal coherence — PARTIAL (no validation)
- **API:** `getParameter()` (`MAX_TEXTURE_SIZE`, `MAX_VIEWPORT_DIMS`, …), `getSupportedExtensions()`, `getShaderPrecisionFormat()`.
- **Status:** `webGl:parameters`, `webGl:supportedExtensions`, `webGl2:supportedExtensions`, `webGl:shaderPrecisionFormats` (`settings/properties.json:76-89`) are **100% config-driven with no validation** that they match the claimed renderer string or each other — `patches/webgl-spoofing.patch` has no consistency logic. A `renderer="Apple M2"` with NVIDIA-shaped parameters / extension set (or default placeholders) is an instant mismatch detectors hash.
- **Mechanism:** make this an **explicit requirement under #2**: ship a per-renderer template (parameters + extension sets + shader-precision dict bundled together, keyed by `webGl:renderer`) in the goapi generator and **reject mix-and-match**; do not allow a profile to set `webGl:renderer` without pulling the matching parameter bundle. Pure generator/validation work — no new C++ surface.

### 16. mediaDevices `deviceId`/`groupId`/labels — PARTIAL → P1
- **API:** `navigator.mediaDevices.enumerateDevices()` → `[{deviceId, groupId, kind, label}]`.
- **Status:** Counts are covered (`mediaDevices:micros/webcams/speakers`, `media-device-spoofing.patch`); `deviceId`/`groupId`/labels are not. Cheap and hard-flagged by iphey/browserscan **today**.
- **Why it leaks:** Real FF emits a stable per-origin 44-char base64 SHA `deviceId` that resets across origins, groups one physical device's input+output under one `groupId`, and keeps labels **empty until getUserMedia permission**. Counts-only spoofing leaves all three wrong.
- **Mechanism:** extend the **C++ patch** to emit per-origin SHA `deviceId`, coherent `groupId` grouping, and permission-gated empty labels; new `CAMOU_CONFIG` key `mediaDevices:deviceIdSeed`; **goapi field** so the seed is per-profile-stable (Brave model).

### 17. Canvas `measureText`/TextMetrics ↔ fonts — PARTIAL → P1
- **API:** `measureText().width` + `actualBoundingBox*` / `fontBoundingBox*`.
- **Why it leaks:** `measureText().width` is FingerprintJS's **primary font-enumeration mechanism** — no pixel readback, so canvas noise (#31) is irrelevant to it. If metrics aren't consistent with the spoofed font list **and** the claimed OS's metrics, fonts are trivially enumerated. `patches/font-list-spoofing.patch` has **no OS mapping** (list is purely config-supplied), so today the metrics can disagree with the claimed platform.
- **Mechanism:** seed-stable rounding in the **C++ canvas hook**, with metric values drawn from the per-OS font-metric template tied to the spoofed font list (OS-text-rendering coherence unit, #2). Cannot rely on pixel noise.

**P1 covered — strengths to preserve:** canvas2D pixel pipeline keys (`canvas:seed/noiseDensity/noiseStrength/aaOffset/aaCapOffset`; worker path closed at `canvas-spoofing.patch:402-433`), AudioContext keys (`audio:seed`+sampleRate/latency/channels — but see #30 caveat), WebGL metadata (renderer/vendor/contextAttributes), installed font list (but see #14/#17 coherence), screen/window geometry, hardwareConcurrency, languages, JA3/JA4 + HTTP/2 + header order, mediaDevices counts.

---

## P2 — consistency hardening and detectable-as-spoofed surfaces

- **18. `StorageManager.estimate()` quota** — missing. `quota` ≈ 10–50% of free disk ⇒ leaks disk size + is a known incognito detector. FPP `+DiskStorageLimit` (#70, pref via #5). **S.**
- **19. Display refresh rate** — missing. rAF-callback cadence recovers 60/120/144/165 Hz, correlating "different person, same machine". FPP `+FrameRate` (#46) clamps to 60. **S.**
- **20. `screen.orientation` type/angle** — missing. `screen-spoofing.patch` adds `ScreenDimensionManager` but leaves `ScreenOrientation.{h,cpp}` unmodified; type/angle reflect the real host and can disagree with spoofed (portrait) dims or a touch profile. FPP `+ScreenOrientation` (#4) → landscape-primary/0, plus a CAMOU key `screen:orientation` derived from spoofed dims for mobile/portrait profiles. **S–M.**
- **21. Battery `getBattery` exposure** — partial/likely-wrong. **FF removed `getBattery` from web content (~FF52); real FF returns `navigator.getBattery === undefined`.** If camoufox's `battery:*` keys cause `getBattery`/`BatteryManager` to be exposed to page JS, that exposure is itself a non-FF tell. **Audit:** keep the API absent for content; only honor `battery:*` if deliberately emulating an older FF. **S.**
- **22. Permissions API coherence** — partial. **C++:** align `permissions.query('notifications').state` with `Notification.permission`; keep `camera`/`microphone` states consistent with the spoofed mediaDevices set (#16) and getUserMedia; match the FF accepted-name set (no `clipboard-read`/`accelerometer`); querying an unsupported name must throw the FF way. **M.**
- **23. Touch trio** — partial. `maxTouchPoints` is spoofed but `'ontouchstart' in window` and `window.TouchEvent` presence must agree (desktop FF: 0 + absent). Derive all three from device class in the generator. **S.**
- **24. DPR vs resolution MQ** — partial. `window.devicePixelRatio` is spoofed but `matchMedia('(resolution)')`/`(-moz-device-pixel-ratio)` may still reflect the real scale. **C++:** tie the MQ to the spoofed DPR. **S.**
- **25. prefers-color-scheme per-profile** — partial. `ui.systemUsesDarkTheme=1` (`camoufox.cfg:49`) forces **every** instance to report dark — a tell if the profile should be light. **Pref:** switch to a per-profile `layout.css.prefers-color-scheme.content-override` (set from `cssMedia:prefersColorScheme`, #8). **S.**
- **26. CSS pointer/hover per-profile** — partial. `patches/force-default-pointer.patch` hardcodes `Fine|Hover` globally; a profile with `maxTouchPoints>0` then contradicts `(pointer:coarse)`/`(hover:none)`. Replace the hardcode with a value derived from device class. **S.**
- **27. DOM property set / key order** — partial. Detectors (double-agent `browser-dom-environment`) diff `Object.getOwnPropertyNames(navigator/screen)` and **key order** vs reference FF150. Constraint on #1/#6/#7/#16/#20: add spoofs at native prototype placement, never as bolt-on own-properties or data-property-over-getter. **M.**
- **28. plugins/mimeTypes content parity** — covered/verify. FF ≥100 hardcodes 5 PDF pseudo-plugins + 2 mimeTypes gated by `pdfViewerEnabled`. Assert contents/structure (named-property access, `enabledPlugin` back-refs) match stock FF. **S.**
- **29. Intl `resolvedOptions` / formatting consistency** — partial/verify. No Intl patch exists in-tree (only `locale-spoofing.patch` + `timezone-spoofing.patch`). `Intl.DateTimeFormat().resolvedOptions()` `{timeZone, locale, calendar, numberingSystem}`, `Intl.NumberFormat` decimal/grouping separators, `Intl.Collator` ordering, and formatted date strings must agree with the spoofed locale **and** timezone; detectors cross-check `resolvedOptions().timeZone` against `Date.getTimezoneOffset()`. Likely partially inherited from FF's LocaleService, but `numberingSystem`/`calendar`/separator leaks are unverified. **Mechanism:** verify; if leaking, extend `locale-spoofing.patch` (C++) to bind `calendar`/`numberingSystem`/separators to the spoofed locale via LocaleService. **S–M.**
- **30. Audio realism (detectable-as-spoofed)** — partial/weak. `patches/audio-fingerprint-manager.patch:57-83` applies a **deterministic LCG transform** to the float/byte buffers. Two detector exploits: (a) post-Safari-17 fingerprinters collect multiple samples + round to defeat injected noise — a constant per-seed delta survives and yields a stable but non-hardware value; (b) the perturbed FFT values match no real-device distribution → exactly the "bad audio result ⇒ system-level tampering" signal CreepJS scores. **Mechanism (C++ patch):** anchor to a real-device audio baseline (from the OS profile) + hardware-shaped jitter seeded from `audio:seed`, stable under multi-sample+round collection — not a raw LCG delta. **M.**
- **31. Canvas 2D noise distribution realism** — partial/weak. Independent of #14, the seed-deterministic 2D perturbation is itself a CreepJS "lie"/distribution-anomaly signal. **Mechanism (C++ patch):** shape the perturbation toward a real-device pixel-noise distribution while keeping seed determinism; do not change the existing key surface. **M.**

---

## P3 — low marginal entropy / niche

- **32. Firefox video metrics** (`mozParsedFrames`/`mozDecodedFrames`/`getVideoPlaybackQuality().droppedVideoFrames`) — missing; leak decode performance. FPP `+VideoElementMozFrames/+VideoElementMozFrameDelay/+VideoElementPlaybackQuality` (pref via #5). **S.**
- **33. `-moz-osx-font-smoothing`** — missing; distinguishes macOS at the CSS layer. FPP `+DOMStyleOsxFontSmoothing` (pref via #5). **S.**
- **34. Timer precision** — partial. FF default ~1ms clamp is inherited but not explicitly pinned; COOP/COEP cross-origin-isolated contexts can unlock finer timers. **Pref:** pin `privacy.reduceTimerPrecision`(+`.unconditional`/`.microseconds`). **S.**
- **35. Gamepad** — mostly covered (FF gates enumeration behind user interaction). Optional FPP `+Gamepad` (pref via #5). **S.**
- **Covered / authentic-FF (no action):** native system colors (`use_standins_for_native_colors=true`, `camoufox.cfg:550`), storage presence flags, DNT/GPC, motion/orientation sensors (desktop), `navigator.vendor`=''/`productSub`=20100101, `history.length`.

---

## N/A for Firefox — keep ABSENT (presence would be the lie)

A FF profile must **not** expose these Chromium-only surfaces; their absence is correct, and the only risk is the inverse mismatch (a profile claiming a Chrome UA without them). Do not add shims.

- `navigator.userAgentData` + `Sec-CH-UA*` headers
- `navigator.deviceMemory`
- `navigator.connection` / NetworkInformation (`dom.netinfo.enabled=false`)
- `navigator.keyboard.getLayoutMap()` / `navigator.keyboard`
- `window.chrome` (runtime/app/csi/loadTimes)
- `performance.memory`
- WebUSB / WebSerial / WebHID / WebBluetooth
- **CDP `Runtime.enable`/`Console.enable` side-effects, `cdc_*` globals, `--enable-automation`** — Chrome/CDP-specific; camoufox drives FF via Juggler (non-CDP). The *hygiene principle transfers*: never leak Marionette globals / `@@juggler` markers / `dom.webdriver.enabled` (see #4).
- **Window-size letterboxing / `RoundWindowSize`** — deliberate philosophy difference: camoufox spoofs exact, internally-consistent per-profile screen/window/DPR from real BrowserForge fingerprints (blend-as-real-device) rather than Tor's anonymity-set bucketing. Not a gap.

---

## Consistency invariants — which signals must cross-agree

Every spoof below must derive from **one BrowserForge base OS profile** and be validated together in the goapi fingerprint generator. Violating any invariant trades a value leak for a CreepJS "lie", which is worse.

1. **GPU/codec unit:** WebGPU adapter (`webGpu:*`, #1) ↔ `webGl:renderer`/`webGl:vendor` ↔ `webGl:parameters`/`webGl*:supportedExtensions`/`webGl:shaderPrecisionFormats` (#15) ↔ `mediaCapabilities:*` HW-decode matrix (#6) ↔ WebRTC codec/SDP/fmtp (#7). All must name the same GPU/decoder family and the same OS.
2. **OS-text-rendering + audio unit:** `navigator.platform`/UA ↔ `voices` list (#13, local-only, OS-specific set) ↔ emoji/font-glyph shape (#14) ↔ `measureText`/TextMetrics (#17) ↔ installed font list ↔ audio baseline distribution (#30). Detectors check these against `platform`/UA cheaply — they must never disagree.
3. **Geo unit:** exit-IP GeoIP ↔ `timezone` ↔ `Intl.*.resolvedOptions().timeZone` + `Date.getTimezoneOffset()` (#29) ↔ `locale`/`navigator.languages` ↔ `Accept-Language` ↔ `KeyboardEvent` layout (#11). Auto-derive from the proxy IP (#3).
4. **Display unit:** spoofed screen/window dims ↔ `devicePixelRatio` ↔ `(resolution)`/`(-moz-device-pixel-ratio)` MQ (#24) ↔ `screen.orientation` type/angle (#20) ↔ `color-gamut`/`dynamic-range` MQ (#8) ↔ refresh rate (#19).
5. **Input-class unit:** device class ⇒ `maxTouchPoints` ↔ `'ontouchstart' in window` ↔ `window.TouchEvent` (#23) ↔ `(pointer)`/`(hover)` MQ (#26) ↔ `screen.orientation` (#20).
6. **Permission/theme unit:** `permissions.query()` state set ↔ `Notification.permission` ↔ mediaDevices labels/getUserMedia (#16, #22); `prefers-color-scheme` (#25) ↔ `cssMedia:prefersColorScheme` (not a fixed global dark).
7. **Structural integrity (applies to every new spoof):** added at native prototype placement preserving FF150 `Object.getOwnPropertyNames` membership **and key order** (#27); implemented in C++ so `Function.prototype.toString` stays native-coded — never injected JS.