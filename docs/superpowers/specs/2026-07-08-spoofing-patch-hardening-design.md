# Spoofing-patch hardening — design

Date: 2026-07-08
Status: revised after adversarial panel review (4 reviewers + moderator); ready for implementation plan
Source review: `plan/review-spoofing-patches.md`
Revision: r2 — folds in 13 panel amendments + 2 owner decisions (system-color = PreferenceSheet
C++ patch; deterministic-noise known-answer risk = documented, mitigation deferred to P4).

## Problem

Five fork-only spoofing patches extend upstream daijro/camoufox. Review + panel found three
defect classes:

1. **Confirmed code bug (B1):** `webrtc-ip-spoofing2.patch` edits
   `dom/media/webrtc/jsapi/WebRTCIPManager.{h,cpp}` as real edit hunks, but the class is *created*
   by `webrtc-ip-spoofing.patch` at `dom/base/WebRTCIPManager.{h,cpp}` — a different directory. No
   patch creates the jsapi path. At real `make dir` those hunks reject or cause an
   undefined-symbol compile failure (the `getMaskForIP` hunk calls `GetLocalIPv4/v6`, added only by
   the unappliable hunk), so the local-IP spoof never lands.
2. **Draft delivery (P0):** `canvas-spoofing.patch` and `webrtc-ip-spoofing2.patch` carry
   fabricated context lines (`// (existing snapshot/copy code…)`) and `<verify exact line>` TODOs,
   target FF150, and apply only via `patch` fuzz (fuzz==0 does **not** imply correct location —
   `offset` is a separate measure). They may be spliced at the wrong site → spoof silently inert.
3. **Coherence + coverage (P1–P3):** the correctly-applied patches push cross-signal coherence
   onto a config layer that only *defaults* (does not *enforce*) it, and enforcement in goapi is
   bypassed by the primary pythonlib path; several fingerprint bits are uncovered.

A FF152.0.4 binary already builds and "passes". Whether the canvas/webrtc spoofs actually fire in
it is **unverified** — so P0 begins by proving the bug, not assuming it (see Phase 0 step 0).

## Goal / success criteria

- webrtc2's `WebRTCIPManager` hunks target the directory where the class actually exists
  (`dom/base/`); the local-IP spoof lands and compiles.
- Both draft patches apply against a **realistically-sequenced** FF152.0.4 tree with 0 rejects,
  0 fuzz, and small offset on every hunk, every `<verify>`/placeholder removed, and each spoof
  call verified (by grep of the applied tree) to sit inside its target function with each new
  source registered in the correct `moz.build`.
- Ground-truth `build-tester` checks prove, against a built binary, that canvas readback is
  perturbed on a **known-answer** input, deterministic on re-read, and consistent across all four
  readback surfaces; and that no `fe80:` host EUI-64 IID leaks over WebRTC (new IPv6-aware
  collector).
- Spoof config is **coherent by construction at the C++ read chokepoint** (`MaskConfig` / patch
  getters), so goapi *and* pythonlib *and* raw `CAMOU_CONFIG` all get coherent values: orientation
  angle derived from type; the three media-codec APIs agree.
- New coverage: remaining color/display + form-factor media features spoofed; fe80 IID matches the
  spoofed OS policy and the global IPv6 IID.
- Canvas, audio, and font-spacing seeds are stable per persistent profile across launches;
  worker/offscreen canvases perturbed.

Non-goals: touching upstream's own patches; modifying pythonlib generation logic (the C++
chokepoint design deliberately needs no pythonlib change); a stochastic canvas-noise model that
survives known-answer analysis (recorded as P4, out of scope now).

## Architecture — layers touched

- **Browser patch layer** (`patches/*.patch` → Firefox C++): canvas-spoofing,
  webrtc-ip-spoofing2, css-media-spoofing, screen-orientation-spoofing, plus a **new**
  system-color PreferenceSheet patch (P1.3).
- **Coherence chokepoint** (`additions/camoucfg/MaskConfig.hpp` + the patch getters): the single
  point every front-end reads through. Orientation-angle derivation and the unified media-codec
  lookup live here so no upstream producer can desync them.
- **Config source of truth** (`goapi/pkg/config/config.go` + `goapi/pkg/fingerprint/generator.go`
  + a new `Config.Validate()`): the `Config` struct serializes to `CAMOU_CONFIG`. generator.go
  supplies coherent *defaults*; `Validate()` is a **fail-fast dev guard** (non-authoritative — it
  does not protect the pythonlib path) hooked into the existing `leakWarnings`/`Launch` flow
  (`goapi/warnings.go:20`).
- **Schema** (`settings/camoucfg.jvv` + `settings/properties.json`): every new config key must be
  registered in **both** or the jvv validator rejects it.
- **Tests**: `goapi/pkg/**/*_test.go` (Go, local, fast); `build-tester/src/lib/checks/*.ts` (vs
  built binary, CI) — several required collectors do **not exist yet** and are scoped as in-phase
  deliverables (see each phase); `service-tester/` must also pass per PR (repo rule).

Each phase ships as one or more PRs tied to a GitHub issue, passing **both** build-tester and
service-tester with evidence in the PR body (`CONTRIBUTING.md` + the repo PR-evidence rule).

## Build/verify loop (chosen: A, corrected)

Re-anchoring uses a **targeted hg fetch** of the touched FF152.0.4 files, but validation models the
**real production apply**, not isolated pristine files (11 sibling patches edit the shared files —
`dom/base/moz.build`, `nsGlobalWindowInner.cpp/.h`, `dom/webidl/Window.webidl` — before canvas/webrtc
in basename order, so a pristine per-file dry-run is a false pass):

1. Fetch **all** files the two patches touch, plus their prerequisites' targets.
2. Apply the patches in `scripts/patch.py` basename order with the **production flags**
   (`patch -p1 --forward -l --binary`, GNU maxfuzz 2) — prerequisites (`webrtc-ip-spoofing.patch`,
   roverfox/font/anti-font/audio patches that share the files) applied first.
3. Per hunk require **rejects==0 AND fuzz==0 AND |offset| small** (offset flags a roamed anchor
   that fuzz alone misses).
4. **Grep the applied tree**: each spoof call sits inside its intended function body; each new
   source (`CanvasSeedManager.cpp`) is registered in the correct `moz.build` SOURCES/EXPORTS block.
5. Final gate: CI Linux build + `build-tester` ground-truth checks (Phase 0 step 5).

No full local source tree (disk-blocked); no slow CI-only edit loop.

## Phase 0 — Fix + re-anchor the draft patches (correctness gate)

Files: `patches/canvas-spoofing.patch`, `patches/webrtc-ip-spoofing2.patch`; fetch targets
(FF152.0.4): `dom/canvas/CanvasRenderingContext2D.cpp`, `dom/canvas/HTMLCanvasElement.cpp`,
`dom/canvas/OffscreenCanvas.cpp`, `dom/canvas/ClientWebGLContext.cpp`,
`dom/media/webrtc/jsapi/PeerConnectionImpl.cpp`, **`dom/base/WebRTCIPManager.{h,cpp}`**,
`dom/base/moz.build`, `dom/base/nsGlobalWindowInner.cpp/.h`, `dom/webidl/Window.webidl`.

0. **Prove the bug first.** Run `build-tester` + the new known-answer probe (step 5) against the
   *current* FF152 binary. Record which spoofs are already inert. If a spoof already fires, its P0
   work collapses to deleting the `<verify>`/placeholder lines + a clean re-anchor (no behavior
   change) — do not manufacture a fix for a non-bug.
1. **B1 — fix webrtc2's target directory.** Move webrtc2's `WebRTCIPManager.{h,cpp}` hunks from
   `dom/media/webrtc/jsapi/` to `dom/base/` (where `webrtc-ip-spoofing.patch` creates the class).
   This is a bug fix, not a re-anchor.
2. Re-anchor every edit hunk with fabricated context onto the real fetched source (real insertion
   points: the pixel-buffer-ready line in `GetImageData`; the `ScopedMap` in `ExtractData`;
   `OffscreenCanvas::ConvertToBlob`'s encode path; `ClientWebGLContext::ReadPixels`;
   `PeerConnectionImpl` include block + `isSpecialIP` + `getMaskForIP`). Keep added spoof code
   byte-for-byte. Delete every `<verify …>` / `// (existing …)` line.
3. Dependency check by **linkage, not existence**: confirm `RoverfoxStorageManager` and
   `FontSpacingSeedManager` signatures/scope are usable from `CanvasSeedManager.cpp`, and that the
   `dom/base/moz.build` EXPORTS/UNIFIED_SOURCES insert lands in the right block after the 11 sibling
   inserts.
4. Verify with the production-apply rehearsal (Build/verify loop steps 2–4): 0 reject, 0 fuzz,
   small offset, structural grep green.
5. **CI ground-truth gate** (replaces the false-passing checks; new collectors are P0 deliverables):
   - **Canvas perturbation-positive probe (new):** render a solid `fillRect` at a fixed value; read
     back via **each** of the four surfaces (`getImageData`, `toDataURL`, `OffscreenCanvas`/worker,
     WebGL `readPixels`) and assert (a) readback deviates from the exact native constant (proves
     perturbation fired on that surface), (b) re-read is byte-identical (deterministic), (c) the four
     surfaces agree with each other. Keep the existing `canvasNoiseDetection` as a determinism check
     only — it is **not** the perturbation gate. `canvasContextIntegrity` stays (methods look native).
   - **WebRTC fe80 collector (new):** force `media.peerconnection.ice.obfuscate_host_addresses=false`,
     collect candidates with a **compressed-IPv6-aware** regex, assert no `fe80:` carries the host
     EUI-64 IID and the emitted value equals the fabricated per-context address.

Exit: B1 fixed; both patches 0-fuzz/small-offset with structural grep green; the four-surface
known-answer canvas probe and the fe80 collector pass; service-tester green.

## Phase 1 — Coherence at the C++ chokepoint (+ goapi guard)

Runs in **parallel with P0** for the orientation/media-codec parts (goapi + already-clean patches,
no dependency on the canvas/webrtc re-anchor). The system-color patch (P1.3) is a new C++ patch and
sequences after P0 establishes the rehearsal method.

Files: `additions/camoucfg/MaskConfig.hpp`, `patches/screen-orientation-spoofing.patch`,
`patches/media-codec-spoofing.patch`, `goapi/pkg/fingerprint/generator.go`,
`goapi/pkg/config/config.go` (new `Validate()`), `goapi/warnings.go`, relevant `_test.go`; new
`patches/system-color-spoofing.patch`.

1. **Orientation (chokepoint):** in `ScreenOrientation::GetAngle`, when `screen:orientation` is
   spoofed but `screen:orientationAngle` is absent, **derive angle from the spoofed type** instead
   of falling through to the native host angle. **Keep both config keys** — dropping the angle key
   un-spoofs the angle. In `generator.go` fix the hardcoded `angle=0` (`:133-135`) to compute angle
   from type for the desktop-landscape presets (0 for `*-primary`, 180 for the `-secondary` pair);
   add a natural-orientation field to `config.go` before supporting mobile/portrait-natural (until
   then, portrait presets are out of scope). Coherence test: `(type, angle)` legal pair + `type`
   matches spoofed `screen.width/height` aspect.
2. **Media-codec (chokepoint):** back `GetMediaCanPlayType` + `GetMediaDecodingInfo` with one
   per-type lookup so they cannot disagree. In `generator.go` fix the regen guard (`:103`, currently
   `len(canPlayType)==0 && len(decodingInfo)==0`) so a one-sided map cannot leave the other empty
   (the empty map falls through to the real host decoder). Coherence test (table-driven over the
   generated map keys): `canPlayType != "" ⟺ decodingInfo.supported ⟺ isTypeSupported`.
3. **prefers-color-scheme ↔ system colors — new PreferenceSheet C++ patch** (owner decision):
   `patches/system-color-spoofing.patch` repaints Gecko system colors (`Canvas`/`CanvasText`/
   `AccentColor`, scrollbars, form controls) to match the spoofed scheme. New patch → subject to the
   Phase-0 rehearsal/re-anchor method; its own PR. Collector (new, P1 deliverable): assert
   `CanvasText`/`AccentColor` render dark when scheme=dark.
4. **goapi `Config.Validate()` (fail-fast dev guard, non-authoritative):** reject illegal
   `(type, angle)` pairs, `type`↔aspect mismatch, and one-sided media maps; call it on the final cfg
   via `leakWarnings`/`Launch`. Spec-note: this guards goapi callers only; the real guarantee is the
   C++ chokepoint (pythonlib/raw-config bypass Validate()).

Exit: `go test ./...` green (table-driven coherence tests); chokepoint derivation covered;
build-tester system-color collector green; service-tester green.

## Phase 2 — Coverage gaps

Files: `patches/css-media-spoofing.patch`, `patches/webrtc-ip-spoofing2.patch`,
`additions/camoucfg/MaskConfig.hpp`, `goapi/pkg/config/config.go` + `generator.go`, **and for every
new key both `settings/camoucfg.jvv` and `settings/properties.json`** (jvv rejects unregistered keys).

1. Confirm whether `dynamic-range` shares `Gecko_MediaFeatures_VideoDynamicRange`; if it has a
   separate backing function, add a spoof block (bounded spike — result is add-one-block or nothing).
2. Add config-gated spoof blocks (mirroring the existing shape) for `prefers-contrast`,
   `forced-colors`, `inverted-colors`, `monochrome`, and the **form-factor** features
   `pointer`/`hover`/`any-pointer`/`any-hover`/`update` (the sharpest desktop↔mobile signals;
   build-tester already probes pointer/hover). Handle `screen.colorDepth` **separately** — it is not
   a media feature; do not fold it into `monochrome`.
3. `forced-colors`/`prefers-contrast` are coherence-laden (must agree with scheme + repainted system
   colors) — schedule them **with** P1's css-media/system-color edits (same patch files) to avoid a
   rebase and to give them a coherence owner; extend `Validate()` + the coherence test accordingly.
4. Shape the fabricated fe80 IID to the spoofed OS's policy (EUI-64 `ff:fe`+U/L bit vs RFC 7217/
   random) **and** match it to the fabricated global IPv6 IID (SLAAC hosts share one IID).

Exit: `matchMedia` returns the spoofed value for each new feature (new build-tester CSS-media
collector, P2 deliverable); fe80 shape/IID coherent; jvv+properties registered; service-tester green.

## Phase 3 — Persistence + worker coverage (depends on P0)

Files: `goapi/options.go` (+ new profile-identity input), `goapi/pkg/fingerprint/generator.go`,
`patches/canvas-spoofing.patch`.

1. **Define the profile-identity source first** (it does not exist today — no `--profile`/
   user-data-dir option; `make run` wipes `~/.camoufox`): add `WithProfileID(string)` /
   `WithUserDataDir` and derive `canvas:seed = hash(id)` so the hash persists across launches
   (drift is an anti-persistence signal) and differs across profiles.
2. **Extend to `audio:seed` + `fonts:spacing_seed`** — they drift identically (`generator.go:78-86`);
   pinning only canvas is itself incoherent under a multi-signal revisit oracle.
3. Perturb offscreen/worker WebGL: resolve the seed via `WorkerPrivate` origin attributes (plumbing
   exists in `OffscreenCanvas::GetCanvasSeed`).

Exit: canvas/audio/font-spacing hashes stable across sessions for one profile, distinct across
profiles; worker canvas hash perturbed (new persistence/worker collectors, P3 deliverables);
service-tester green.

## Phase 4 — (deferred, documented) Known-answer canvas-noise mitigation

Recorded, not scheduled now (owner decision). Deterministic ±1 LSB noise is extractable by a
known-answer render: a solid `fillRect(128)` readback yields sparse 127/129 pixels no real renderer
produces, and determinism makes the PRNG position stream recoverable. Accepted limitation for r2.
Future mitigation: skip perturbation on locally-uniform (flat) regions so solid fills read native,
or move to a content-adaptive/stochastic-but-coherent model. Scope when a detector using
known-answer analysis is observed in the wild.

## Testing strategy

- **goapi:** `go test ./...` — table-driven coherence, drift, fingerprint, and `Validate()` tests.
- **build-tester:** CI Linux build + `python scripts/run_tests.py <binary>`. New collectors are
  in-phase deliverables (canvas known-answer + four-surface, fe80/IPv6, system-color, CSS-media,
  persistence/worker) — the existing `canvasNoiseDetection`/`checkWebRTC` are insufficient.
- **service-tester:** required to pass on every PR (repo rule); its output is part of each phase's
  evidence, alongside the production-apply rehearsal log (0 reject/fuzz/small offset), `go test`
  output, and the build-tester grade.

## Risks / assumptions

- **A1 (P0 linkage):** canvas patch assumes usable linkage (not just existence) of
  `RoverfoxStorageManager`/`FontSpacingSeedManager` at FF152 — verified by compile in P0.
- **A2 (corrected):** the earlier claim "patches touch only the fetched files" was false — they edit
  11-way-shared files applied after siblings; validation now models the sequential production apply.
- **R1 (system-color patch size):** the new PreferenceSheet patch has its own re-anchor/drift risk
  and ships as its own PR.
- **R2 (build cost):** each CI gate is a full browser build (Linux fastest); the cheap pre-build
  structural grep (Build/verify step 4) catches path/anchor bugs before burning a build.
- **R3 (backward-compat):** existing `screen:orientationAngle` consumers keep working — the key is
  retained; only the *default* becomes type-derived. Note in each PR.
- **Rollback:** patch-layer changes revert by dropping the patch; goapi changes revert by commit.
  Each phase PR is independently revertible.

## Sequencing

P0 (correctness, incl. B1) and P1-orientation/media-codec (goapi + clean patches) run in **parallel**
— they are independent. P1.3 system-color (new C++ patch) and P3 (canvas seed) depend on P0's
rehearsal method / canvas re-anchor. P2 coverage after P1 (shared css-media/system-color patch
files). P4 deferred. Each phase lands with its ground-truth test assertion + both test suites as PR
evidence.
