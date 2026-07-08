# Spoofing-patch hardening — design

Date: 2026-07-08
Status: approved (design), pending implementation plan
Source review: `plan/review-spoofing-patches.md`

## Problem

Five fork-only spoofing patches extend upstream daijro/camoufox. A review found two
classes of defect:

1. **Correctness (P0):** `canvas-spoofing.patch` and `webrtc-ip-spoofing2.patch` are drafts
   — they carry fabricated diff context lines (`// (existing snapshot/copy code…)`) and
   `<verify exact line>` TODO markers, and target FF150. `scripts/_mixin.py:list_patches`
   applies every `patches/**/*.patch` with `patch -p1 --forward -l --binary` (fuzz 2). The
   FF152 build passed only because fuzz found a no-reject slot for these hunks — which means
   the perturbation/masking calls may be spliced at the wrong location, so the canvas and
   WebRTC spoofs may be silently inert or mis-scoped in the shipped binary. Unverified.
2. **Coherence + coverage (P1–P3):** the correctly-applied patches (css-media, media-codec,
   screen-orientation) push cross-signal coherence onto the goapi config layer, which does not
   yet enforce it, and leave fingerprint bits uncovered.

## Goal / success criteria

- Both draft patches apply against real FF152.0.4 with **0 rejects and 0 fuzz**, with every
  `<verify>`/placeholder comment removed.
- `build-tester` confirms, against a built binary, that canvas readback is perturbed and stable
  on re-read, that the canvas lie-detector still passes, and that no `fe80:` host interface ID
  leaks over WebRTC.
- goapi emits **coherent** spoof config: orientation type↔angle is a legal pair and matches
  screen aspect; the three media-codec APIs agree; prefers-color-scheme matches rendered system
  colors.
- New coverage: the remaining color/display media features are spoofed; the fabricated fe80 IID
  matches the spoofed OS's IID policy.
- Canvas seed is stable per persistent profile across launches; worker/offscreen canvases are
  perturbed.

Non-goals: touching upstream's own patches; changing the Python (`pythonlib`) layer; any
refactor beyond what these fixes require.

## Architecture — layers touched

- **Browser patch layer** (`patches/*.patch` → Firefox C++): canvas-spoofing,
  webrtc-ip-spoofing2, css-media-spoofing, screen-orientation-spoofing.
- **Config accessor** (`additions/camoucfg/MaskConfig.hpp`): existing getters `GetString`,
  `GetUint32`, `GetDouble`, `GetMediaCanPlayType`, `GetMediaDecodingInfo`. New getters added in
  P2 for the extra media features.
- **Config source of truth** (`goapi/pkg/config/config.go` + `goapi/pkg/fingerprint/generator.go`):
  the `Config` struct serializes to the `CAMOU_CONFIG` JSON the patches read. Coherence
  derivation happens in `generator.go`; the struct already declares every relevant field
  (`ScreenOrientation` + `ScreenOrientationAngle`, `MediaCanPlayType` + `MediaDecodingInfo`,
  `CanvasSeed`, `CSSColorGamut/DynamicRange/PrefersColorScheme`, `WebRTCLocalIPv4/v6`).
- **Tests**: `goapi/pkg/**/{coherence,drift,fingerprint}_test.go` (Go, local, fast) and
  `build-tester/src/lib/checks/*.ts` run against a built binary on CI (existing collectors:
  `canvasHash`, `canvasContextIntegrity`, `canvasNoiseDetection`, `checkWebRTC`).

Each phase ships as one PR tied to a GitHub issue, passing both test suites with evidence in the
PR body (per `CONTRIBUTING.md` and the repo's PR-evidence rule).

## Build/verify loop (chosen: A)

Re-anchoring uses a **targeted hg fetch**: pull only the touched FF152.0.4 files from
`hg.mozilla.org/releases/mozilla-release/raw-file/FIREFOX_152_0_4_RELEASE/<path>` (the method
already used this session to rebase css-media and media-codec), `patch --dry-run` against them to
measure reject/fuzz, re-anchor, then gate end-to-end on CI (Linux leg — fastest) running
`build-tester`. No full local source tree (disk-blocked); no slow CI-only edit loop.

## Phase 0 — Re-anchor the two draft patches (correctness gate; blocks P1–P3)

Files: `patches/canvas-spoofing.patch`, `patches/webrtc-ip-spoofing2.patch`.

Targets to fetch (FF152.0.4): `dom/canvas/CanvasRenderingContext2D.cpp`,
`dom/canvas/HTMLCanvasElement.cpp`, `dom/canvas/OffscreenCanvas.cpp`,
`dom/canvas/ClientWebGLContext.cpp`, `dom/media/webrtc/jsapi/PeerConnectionImpl.cpp`.

Steps:
1. For each edit hunk whose context is fabricated, find the real insertion point in the fetched
   source (the actual pixel-buffer-ready line in `GetImageData`; the real `ScopedMap` in
   `ExtractData`; `OffscreenCanvas::ConvertToBlob`'s encode path; `ClientWebGLContext::ReadPixels`;
   `PeerConnectionImpl`'s include block, `isSpecialIP`, and `getMaskForIP`). Rewrite the context
   lines from real source; keep the added spoof code byte-for-byte. New-file hunks
   (`CanvasSeedManager.cpp/.h`, `--- /dev/null`) are unaffected.
2. Delete every `<verify …>` and `// (existing …)` placeholder line.
3. Dependency check: confirm `RoverfoxStorageManager` and `FontSpacingSeedManager` symbols
   (referenced by the canvas patch) exist at FF152 from the roverfox/font patches, and that the
   `dom/base/moz.build` EXPORTS/UNIFIED_SOURCES anchors still match.
4. Verify apply: `patch -p1 --dry-run` per file against the fetched tree → 0 reject AND 0 fuzz.
   Fuzz > 0 means still mis-anchored — re-anchor until clean.
5. CI gate: dispatch a Linux build, run `build-tester`; assert `canvasNoiseDetection` observes
   perturbation, `canvasContextIntegrity` passes (perturbation is native C++, not a JS-proto
   patch), re-read of the same canvas is byte-identical (deterministic), and `checkWebRTC` shows
   no `fe80:` candidate carrying the host IID.

Exit: both patches 0-fuzz; build-tester canvas + WebRTC assertions green.

## Phase 1 — Coherence enforcement in goapi

Files: `goapi/pkg/fingerprint/generator.go`, `goapi/pkg/config/config.go`,
`goapi/pkg/config/drift_test.go` / `goapi/pkg/fingerprint/coherence_test.go`; possibly
`patches/css-media-spoofing.patch` for system colors.

1. **Orientation:** derive `ScreenOrientationAngle` from `ScreenOrientation` + the device-natural
   orientation inside `generator.go` (single source), rather than two independently-set fields.
   Coherence test: `(type, angle)` is a spec-legal pair and `type` matches the spoofed
   `screen.width/height` aspect.
2. **Media-codec:** generate `MediaCanPlayType` and `MediaDecodingInfo` from one per-OS codec
   table; set `powerEfficient = true` for hardware-decoded codecs. Coherence test: for every
   codec, `canPlayType != "" ⟺ decodingInfo.supported == true ⟺ isTypeSupported == true`.
3. **prefers-color-scheme ↔ system colors:** extend the spoof so Gecko system colors
   (`Canvas`/`CanvasText`/`AccentColor`, scrollbars, form controls) match the spoofed scheme —
   via the PreferenceSheet path in `css-media-spoofing.patch` or a `ui.systemUsesDarkTheme`-style
   pref in `settings/camoufox.cfg`. Decide the mechanism during the implementation plan; if the
   PreferenceSheet change is large, it may split into its own PR.

Exit: `go test ./...` in `goapi/` green; build-tester shows scheme-consistent system colors.

## Phase 2 — Coverage gaps

Files: `patches/css-media-spoofing.patch`, `additions/camoucfg/MaskConfig.hpp`,
`goapi/pkg/config/config.go` + `generator.go`; `patches/webrtc-ip-spoofing2.patch`.

1. Confirm whether the `dynamic-range` media feature shares `Gecko_MediaFeatures_VideoDynamicRange`
   with `video-dynamic-range`; if it has a separate backing function, add a spoof block so real
   HDR does not leak.
2. Add config-gated spoof blocks (mirroring the existing block shape) for `prefers-contrast`,
   `forced-colors`, `inverted-colors`, and `monochrome`/color-depth, with matching config keys,
   `MaskConfig` getters, and goapi `Config` fields.
3. Shape the fabricated fe80 IID to the spoofed OS's policy (classic EUI-64 with `ff:fe` +
   U/L bit, vs RFC 7217 / random IID) so the link-local address is coherent with the OS.

Exit: `matchMedia` returns the spoofed value for each new feature; build-tester extended checks
green; fe80 shape matches OS.

## Phase 3 — Persistence + worker coverage

Files: `goapi` (seed derivation), `patches/canvas-spoofing.patch` (offscreen/worker seed).

1. goapi pins a stable `canvas:seed` derived from the persistent profile identity (not random per
   launch), so a site storing the canvas hash sees it persist rather than drift (drift is an
   anti-persistence signal).
2. Perturb offscreen/worker WebGL contexts: resolve the seed via `WorkerPrivate`'s origin
   attributes (the plumbing already exists in `OffscreenCanvas::GetCanvasSeed`), removing the
   main-thread-vs-worker hash mismatch.

Exit: canvas hash stable across sessions for one profile and distinct across profiles; worker
canvas hash perturbed.

## Testing strategy

- **goapi:** `go test ./...` from `goapi/` — coherence, drift, and fingerprint tests. Fast, local,
  gates every goapi change.
- **build-tester:** CI Linux build + `python scripts/run_tests.py <binary>` — canvas, WebRTC,
  CSS-media, orientation, codec checks against the real binary.
- **PR evidence:** each phase's PR body carries the `patch --dry-run` output (0 reject/fuzz),
  `go test` output, and the build-tester grade.

## Risks / assumptions

- **A1 (P0 dependency):** the canvas patch assumes `RoverfoxStorageManager` and
  `FontSpacingSeedManager` exist at FF152. Verified in P0 step 3; if a symbol moved, the canvas
  patch needs a follow-up hunk.
- **A2 (dry-run scope):** the 5-file targeted fetch is sufficient because the two patches touch
  only those files (plus new files). True by inspection of the diffs.
- **R1 (system-color size):** the prefers-color-scheme↔system-color fix may require a larger
  PreferenceSheet patch; scoped to P1 and may split into its own PR.
- **R2 (build cost):** each CI gate is a full browser build (Linux fastest, ~tens of minutes);
  phases batch their build-tester assertions to minimize dispatches.

## Sequencing

P0 first — it is the only correctness gap (the spoof may not run today) and gates trust in the
canvas/webrtc layer. P1 next — incoherence is what modern oracles (iphey, creepjs) actually flag.
P2 and P3 are hardening. Each phase lands with its test assertion as PR evidence.
