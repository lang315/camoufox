# FB Fingerprint Observer — Verify + Extend (Recon + Spoof) Design

**Date:** 2026-07-20
**Status:** Design — approved direction: **observe + spoof**
**Related:** built-in Tracking Observer (commit `bf5f076`, PR #18); `docs/observer/README.md`; `docs/superpowers/specs/2026-07-10-tracking-observer-design.md`

## Goal

Confirm the built-in Tracking Observer actually records fingerprint-surface reads at
runtime, drive it against Facebook's real fingerprinting code to see which surfaces FB
consults, and close the highest-value blind spots — surfaces that today leak a **real
device value** with no spoof and no observation — by adding **both** a MaskConfig-driven
spoof **and** an observe `Record()` hook, but only for surfaces empirically confirmed to
leak a device-varying value on FF152.

## Why this shape (adversarial-review outcome)

Four independent reviewers rejected the originally-proposed external main-world recon
harness and converged on this design:

1. **Detectability (observer effect).** A main-world `Proxy`/monkey-patch is detectable by
   ≥6 structural vectors a `toString` spoof never fixes (stray `window.__recon` global,
   own-property/descriptor probes, `.name`/`.length`, injected stack frames, the
   cross-realm iframe `toString` oracle, `Proxy` invariants). Detection **poisons** the
   data, possibly via a silent server-side flag. The only non-poisoning vantage is
   **below the JS line** — exactly where the C++ Observer already sits.
2. **Build-vs-reuse.** `build-tester/` already enumerates the whole fingerprint surface;
   the fork already ships the Observer. Building a new harness duplicates both.
3. **Completeness.** "Everything FB does" is structurally unobservable client-side (TLS/JA3,
   WASM, workers, CSS, server-side scoring). The design must carry an honest scope caveat.
4. **Viability/authorization.** Live logged-out facebook.com automated loads hit
   login-walls / blocks and yield unrepresentative data. A local Meta-Pixel/SDK surrogate
   runs the same collection code with zero ToS/CAPTCHA/IP exposure.

## Verified starting state (not assumptions — checked against the beta.28 build)

- Observer is **compiled + packaged** in the current build (`cfx_sync4`): JS modules at
  `resource://gre/modules/TrackingObserver{,Child,Parent}.sys.mjs`, panel at
  `chrome://camoufox/content/tracking.{html,js,css}`, C++ symbols `CAMOU_OBSERVE` +
  `camouDrainAccessRecords` present in `XUL`. The wiring the task-3 report flagged
  "CI-must-verify" (the `resource://gre/modules/` mapping + `/observer` DIRS) **works**.
- **All 7** `SurfaceId` surfaces have `Record()` call sites — canvas + webgl
  (`canvas-spoofing.patch`), webrtc (`webrtc-ip-spoofing.patch`), navigator ×4
  (`navigator-spoofing.patch`), screen ×2 (`screen-spoofing.patch`), fonts ×2
  (`font-list-spoofing.patch`), audio ×4 (`audio-fingerprint-manager.patch`). The README's
  "Step 1: canvas only" line is **stale**.
- `build-tester/observer/timing_parity_probe.js` already exists (detectability check).
- Already spoofable via MaskConfig (`settings/properties.json`): `battery:*`,
  `mediaDevices:*` (enumerateDevices), `navigator.oscpu`, `navigator.productSub`,
  `webGl:vendor`. `navigator-spoofing.patch` already masks
  UA/platform/oscpu/appVersion/timezone (+ hardwareConcurrency/languages).

## Surface coverage matrix (drives Phase 3 scope)

| Surface | Spoofed today | Observed today | FF152 leaks real device value? | Action |
|---|---|---|---|---|
| canvas, webgl, webrtc, navigator(UA/platform/oscpu/appVersion/hwConcurrency/lang), screen, fonts, audio | yes | yes (7 SurfaceId) | n/a (masked) | **Phase 1** verify records at runtime |
| `battery:*` | yes (MaskConfig) | no | n/a | **Phase 3** add observe hook *iff* FB reads it |
| `mediaDevices` / `enumerateDevices` | yes (MaskConfig) | no | n/a | **Phase 3** add observe hook *iff* FB reads it |
| `navigator.deviceMemory` | **no** | no | **likely yes** (real, rounded) | **Phase 3** evidence-gate → spoof + observe |
| `navigator.plugins` / `mimeTypes` | **no** | no | **verify** (FF152 mostly standardized) | **Phase 3** evidence-gate → spoof + observe *iff* leaks |
| `navigator.vendor` | no | no | **no** (FF = `""` constant) | **skip** (spoof would break FF consistency) |
| `navigator.userAgentData` | no | no | **no** (FF = undefined) | **skip** |
| `navigator.connection` | no | no | **no** (FF undefined by default) | **skip** |
| timezone, locale / `Intl` | yes (masked) | **no** (engine-cached, no per-read hook) | n/a | **defer** (unobservable per-read) |
| worker / OffscreenCanvas | partial | no (off main thread) | — | **defer** |

The evidence gate matters: most README-listed "leaks" are already spoofable (battery,
mediaDevices) or constant/undefined on FF152 (vendor, userAgentData, connection). Spoofing
a constant is wasted work and risks tripping build-tester lie-detection. **Confirm the leak
before writing any spoof.**

## Non-goals / honest scope boundary (must appear in the final recon report)

This observes fingerprint-surface **consultations at the JS/WebIDL boundary** — presence +
drain-window count, per `(site, userContextId)`. It does **not** capture values, hashes, or
FB's scoring. It is structurally blind to: TLS ClientHello / JA3-JA4 / HTTP-2 SETTINGS / TCP
(camoufox does not even spoof this layer), WASM internals, Web/Service Workers,
`OffscreenCanvas`, pure-CSS `@media` probes, timing side-channels, and anything FB computes
server-side (datr linkage, egress IP, header order, encrypted beacon payloads). **Silence in
the panel ≠ the surface was not read** for anything unhooked. This project maps client-side
collection and closes real-value leaks; it does **not** attempt to defeat or observe FB's
server-side risk engine.

## Architecture — three phases

### Phase 1 — Runtime gate + first regression test

The one genuinely-unverified thing: do the 7 wired surfaces actually produce records at
runtime? Reuse `build-tester/scripts/runner.py` launch plumbing.

- Launch `cfx_sync4` with `CAMOU_OBSERVE=1`; serve a local probe page that touches all 7
  surfaces (canvas readback, WebGL `getParameter`, `RTCPeerConnection`, a navigator read,
  a screen read, a font-metrics probe, an `AudioContext` render).
- Read the drained records and assert each surface recorded ≥1. **Readout method** (resolve
  in the implementation plan): either (a) navigate a second tab to
  `chrome://camoufox/content/tracking.html` and scrape rendered rows, or (b) a test-only
  privileged path to call `ChromeUtils.camouDrainAccessRecords()` directly. Prefer whichever
  works headless without loosening the observer's chrome-only boundary.
- Run the existing `observer/timing_parity_probe.js` to confirm armed readback stays within
  the unarmed timing band.
- **Deliverable:** a committed `build-tester` functional observer test + a surface truth
  table. **Gate:** all 7 surfaces record; timing parity holds.

### Phase 2 — Facebook stimulus (recon proper)

- Local surrogate page on `127.0.0.1` embedding the Meta Pixel (`fbevents.js`) and the FB
  JS SDK (`connect.facebook.net/en_US/sdk.js`). Load under `CAMOU_OBSERVE=1`; drain; report
  which surfaces Meta's real code touches per `(site, userContextId)`.
- **Optional** single, human-paced, logged-out, no-interaction facebook.com spot-check on a
  residential IP to confirm the surrogate's read-set ≈ the real landing bundle (datr
  issuance + pre-login fingerprint). **No automated loops against facebook.com.**
- **Deliverable:** recon report — "Meta reads {surfaces}; not-observable {blind-spot list}" —
  carrying the scope boundary above verbatim.

### Phase 3 — Close confirmed leaks (observe + spoof)

For each candidate, **evidence-gate first**, then act only on confirmed leaks:

1. **Evidence probe.** Run `cfx_sync4` and record the candidate's actual FF152 value across
   configs; confirm it returns a real, device-varying value (not undefined/constant).
2. **Spoof** (confirmed leaks only, prime suspect `deviceMemory`, verify `plugins`):
   - add the MaskConfig key + schema entry (`settings/properties.json`);
   - C++ getter patch: read MaskConfig, return spoofed value, call `AccessObserver::Record`
     (reuse `SurfaceId::Navigator`, or a new `SurfaceId` if a distinct badge is wanted —
     keep the enum in sync with `tracking.js`'s `SURFACE_NAMES`);
   - **pythonlib passthrough**: BrowserForge presets must supply a value consistent with the
     preset's device class (never a constant — an 8 GB `deviceMemory` under a 2-core mobile
     UA is a lie-detection tell);
   - build-tester coverage for the new spoof.
3. **Observe-only** for already-spoofed-but-unobserved surfaces (`battery`, `mediaDevices`)
   **iff** Phase 2 shows FB reads them: add the `Record()` call, no new spoof.
4. Update the stale `docs/observer/README.md` (canvas-only → all-7 + newly-hooked surfaces;
   correct the battery/mediaDevices blind-spot claims).
5. **Defer** (document, don't build): engine-cached timezone/locale per-read observation,
   worker/OffscreenCanvas.

## Data flow (existing observer, unchanged)

```
page reads a fingerprint surface (canvas readback, deviceMemory getter, ...)
  → C++ AccessObserver::Record(userContextId, site, SurfaceId, tsMillis)   [ring-buffer push]
  → TrackingObserverChild drains via ChromeUtils.camouDrainAccessRecords() on a 500ms timer
  → sendAsyncMessage → TrackingObserverParent → Collector                  [parent, memory-only]
network: http-on-modify-request (read-only) → Collector.ingestNet(...)
Collector change → Services.obs notify → chrome://camoufox panel re-renders
```

## Risks & error handling

- **build-tester regression (highest risk).** Any navigator-getter change can trip the
  lie-detection checks in `build-tester/src/lib/checks/core.ts`. Precedent: a prior
  principal-elevation attempt (PR #21 G2) broke build-tester to **0/0 Grade F**. Every
  Phase-3 spoof must keep build-tester **≥1000** using the **`playwright==1.55.0`** pin
  (newer → false 0/0 regression on camoufox-152).
- **Consistency.** Spoofed values must come from the BrowserForge preset, matched to the
  device class — not hard-coded constants.
- **Detectability.** A new `Record()` on a hot getter must keep armed timing within the
  `timing_parity_probe.js` band.
- **facebook.com viability.** Automated logged-out loads may be walled/blocked; the surrogate
  is primary, the FB spot-check is best-effort.
- **Build path.** Full builds are Linux/Docker/CI; local macOS `make build` is not the path.
  Verify via CI artifacts + `cfx_sync4` for runtime probes.

## Testing (both suites gate, per repo policy)

- Phase 1: committed functional observer test in `build-tester` (7-surface truth table).
- Phase 3: `build-tester` ≥1000 after **each** spoof; `timing_parity_probe.js` green;
  per-surface evidence probes recorded in the PR body.
- Each PR references the relevant daijro/observer issue and carries command output as
  evidence (never a success claim without the output).

## Tech stack

Python + Playwright (`build-tester` plumbing) for drivers/tests; C++ patches (MaskConfig +
WebIDL getters) for spoof + `Record()`; the existing JS actor/panel for readout;
`fbevents.js` + `sdk.js` as the local FB stimulus.
