# Review: fork spoofing patches — ưu/nhược + fix plan

Scope: 5 fork-only spoofing patches vs upstream daijro/camoufox.
- `canvas-spoofing.patch` (+490)
- `webrtc-ip-spoofing2.patch` (+192)
- `css-media-spoofing.patch` (+63) — rebased FF152 (26d60e7)
- `media-codec-spoofing.patch` (+131) — rebased FF152 (26d60e7)
- `screen-orientation-spoofing.patch` (+38)

Patcher applies **every** `patches/**/*.patch` (`scripts/_mixin.py:list_patches`), non-roverfox
first, roverfox last, with `patch -p1 --forward -l --binary` (fuzz 2, whitespace-insensitive).

---

## Per-patch verdict

### 1. canvas-spoofing.patch — MECHANISM GOOD, DELIVERY BROKEN

**Ưu**
- Deterministic ±1 LSB noise at the readback boundary (`GetImageData`, `ToDataURL`/`ToBlob`,
  `OffscreenCanvas.ConvertToBlob`, `ClientWebGLContext.ReadPixels`). Same (seed, content) →
  same output, so re-read/re-render can't diff-detect the noise.
- Per-`userContextId` seed → contexts diverge; content-hash mix (FNV over first 1024 B).
- Alpha channel untouched; C++-level so invisible to page JS; setter self-destructs.

**Nhược**
- **[P0] Draft, not rebased.** Hunks into `CanvasRenderingContext2D::GetImageData` and
  `HTMLCanvasElement::ExtractData` use *fabricated context lines* — literally
  `// (existing snapshot/copy code that fills data array)` and `// <verify exact line in
  FF150 source>`. Author never confirmed insertion points. Build passed only because `patch`
  fuzz found *a* slot with no reject — which means the perturbation call may be spliced at the
  **wrong location** (or against variables `data`/`length` that don't exist there) → spoof
  silently inert or mis-scoped. Unverified.
- **[P0] FF150-targeted.** Comments say FF150; we're on FF152.0.4. Same drift class that broke
  css-media/media-codec.
- **[P2] Seed persistence.** Seed lives in `RoverfoxStorageManager` (session) + `CAMOU_CONFIG`
  fallback. If goapi doesn't pin a stable `canvas:seed` per persistent profile, the canvas hash
  drifts every launch → anti-persistence signal (a site storing your hash sees it change).
- **[P3] Worker/offscreen gap** (self-admitted): offscreen WebGL contexts with no owner doc stay
  unperturbed → a worker-rendered WebGL hash is un-noised while the main-thread one is noised =
  internal incoherence.

### 2. webrtc-ip-spoofing2.patch — REAL LEAK FIX, DELIVERY BROKEN

**Ưu**
- **Genuine leak closed:** `fe80::/10` link-local IPv6 was in `isSpecialIP` (never masked).
  fe80 IIDs are EUI-64-derived → embed host MAC = hardware identity leak. Patch routes fe80
  through `getMaskForIP` → per-context fabricated replacement. Correct catch.
- `isLinkLocalIPv6` range check (fe8/fe9/fea/feb) correctly covers fe80–febf.
- Separates LOCAL (RFC1918/ULA) slot from public spoof — right SDP model; wires the
  previously-dead `webrtc:localipv4/6` config keys.

**Nhược**
- **[P0] Same draft smell:** fake `index 0000000000..0000000001` + `<verify exact line — include
  block … insert next to the other mozilla/* headers>` on the `#include` hunk. Applied via fuzz;
  unverified against real `PeerConnectionImpl.cpp`.
- **[P1] EUI-64 realism:** fabricated IID is fully random low-64 (`fe80::hhhh:hhhh:hhhh:hhhh`).
  Fine for OSes using RFC 7217/random IIDs (Win10+, Android), but incoherent for a spoofed OS
  that uses classic EUI-64 (has `ff:fe` in the middle, U/L bit set). Coherence depends on spoofed
  OS.
- **[P2] type-field blind:** local-vs-public only; no check that fabricated fe80 stays structurally
  coherent with the fabricated routable v6. Low detection value.

### 3. css-media-spoofing.patch — CLEAN, INCOMPLETE

**Ưu**
- Properly rebased FF152 (real context, no fuzz risk). Small, reads `MaskConfig`, falls through
  to real value when unset (no forced tell).
- Covers real bits: `color-gamut` (P3/Rec2020 monitor), `prefers-color-scheme`,
  `video-dynamic-range` (HDR).

**Nhược**
- **[P1] scheme ↔ system-color incoherence:** spoofs the `prefers-color-scheme` MQ only. Does NOT
  repaint Gecko system colors (`Canvas`/`CanvasText`/`AccentColor` keywords, scrollbars, form
  controls). Report "dark" but render light system colors → detectable mismatch.
- **[P2] coverage gaps:** missing `dynamic-range` (verify whether it shares
  `Gecko_MediaFeatures_VideoDynamicRange`; if separate, real HDR leaks), `prefers-contrast`,
  `forced-colors`, `inverted-colors`, `monochrome`/color-depth. Each is a fingerprint bit left
  at host value.

### 4. media-codec-spoofing.patch — RIGHT API SET, COHERENCE ON CONFIG

**Ưu**
- Covers the coherent trio `canPlayType` + `isTypeSupported` + `MediaCapabilities.decodingInfo`
  from one config layer — these three MUST agree and now do (structurally).
- EME/`keySystemConfiguration` queries fall through to the real resolver → DRM
  `MediaKeySystemAccess` stays correct. Smart.
- Rebased FF152 (real context).

**Nhược**
- **[P1] powerEfficient default = false.** For a HW-decoded codec (H.264/AV1 on any modern GPU)
  real `powerEfficient` is true. If config leaves it false, "no codec is power-efficient" is a
  VM/spoof tell. Needs realistic per-OS data.
- **[P1] two getters, one truth:** `GetMediaCanPlayType` and `GetMediaDecodingInfo` are separate
  MaskConfig calls. If not backed by ONE table they can contradict (canPlayType "probably" vs
  MediaCapabilities supported=false). Must assert single source.
- **[P2] `mType` blind:** spoof keys off content-type only, ignores `type` (file/media-source/
  webrtc). WebRTC codec support ≠ file support in reality → minor incoherence.

### 5. screen-orientation-spoofing.patch — CLEAN, COHERENCE ON CONFIG

**Ưu**
- Real context (real index), small. Spoofs `orientation.type` + `.angle`; falls through when unset.

**Nhược**
- **[P1] type↔angle split into two independent keys** (`screen:orientation`,
  `screen:orientationAngle`). Spec ties them (portrait-primary=0°, landscape-primary=90° on
  phone-native; 0° on landscape-native). Two keys let goapi emit an impossible pair → detectable.
  Derive angle from type + device-natural in ONE place.
- **[P1] orientation ↔ screen dims:** `type=landscape` must match `screen.width>height` and
  `innerWidth/innerHeight`. Patch doesn't enforce; a desktop profile forced to portrait is a big
  tell. Config's job — needs a coherence guard.

---

## Fix plan (priority order)

### P0 — Make the two draft patches real (blocks trust in canvas + webrtc2)
1. Fetch the real FF152.0.4 targets from hg (same method used for css-media/media-codec):
   `dom/canvas/CanvasRenderingContext2D.cpp`, `dom/canvas/HTMLCanvasElement.cpp`,
   `dom/canvas/OffscreenCanvas.cpp`, `dom/canvas/ClientWebGLContext.cpp`,
   `dom/media/webrtc/jsapi/PeerConnectionImpl.cpp`.
2. Locate the real insertion points (the actual pixel-buffer-ready line in `GetImageData`; the
   real `ScopedMap` in `ExtractData`; the real `#include` block + `isSpecialIP`/`getMaskForIP` in
   `PeerConnectionImpl`). Rewrite each hunk with real context. Delete every `<verify …>` comment
   and every `// (existing …)` placeholder.
3. Verify apply: `patch --dry-run` against extracted FF152 → **0 rejects, 0 fuzz** (fuzz>0 means
   still mis-anchored).
4. Prove it fires: `build-tester` canvas test (canvas/WebGL hash perturbs and is *stable* on
   re-read) + a WebRTC test asserting no `fe80:` candidate leaks the host IID. Evidence in PR
   (CLAUDE.md).

### P1 — Coherence enforcement
5. **orientation:** collapse to one source — goapi derives `angle` from `type` + device-natural
   orientation; drop the standalone angle key OR assert `(type,angle)` is a legal pair in
   `pkg/config/drift_test.go`. Add guard: `type` matches spoofed `screen.width/height` aspect.
6. **media-codec:** back `GetMediaCanPlayType` and `GetMediaDecodingInfo` with ONE codec table in
   MaskConfig; set `powerEfficient=true` for HW-decoded codecs per spoofed OS. Add coherence test:
   for each codec, canPlayType≠"" ⟺ isTypeSupported=true ⟺ MediaCapabilities.supported=true.
7. **css-media:** repaint Gecko system colors to match spoofed `prefers-color-scheme` (extend the
   patch to the PreferenceSheet/system-color path), or document the hole. Add a coherence test
   (scheme dark ⟹ `Canvas` keyword renders dark).

### P2 — Coverage gaps
8. **css-media:** confirm `dynamic-range` backing func; if separate from video-dynamic-range, add
   a spoof block. Add `prefers-contrast`, `forced-colors`, `inverted-colors`, `monochrome`/color
   depth as config-gated spoofs (mirror existing block shape).
9. **webrtc2:** optional — shape fabricated fe80 IID to match spoofed OS IID policy (EUI-64 vs
   RFC 7217).

### P3 — Persistence
10. **canvas:** goapi pins a stable `canvas:seed` per persistent profile so the hash doesn't drift
    across launches; perturb offscreen/worker WebGL contexts (resolve seed via WorkerPrivate origin
    attrs — the plumbing already exists in `OffscreenCanvas::GetCanvasSeed`).

## Sequencing
P0 first (correctness — the spoof may not even run today). P1 next (incoherence is what modern
oracles like iphey/creepjs actually flag). P2/P3 are hardening. Each step lands with a
build-tester/drift-test assertion as PR evidence.
