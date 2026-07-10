# Spoofing-patch hardening — P4 (deferred: known-answer canvas-noise mitigation) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Revision:** r1.

**Status: DEFERRED.** Recorded in the design (`docs/superpowers/specs/2026-07-08-spoofing-patch-hardening-design.md`, Phase 4) as an accepted limitation for r2, not scheduled. Per the spec and the owner decision baked into it, **do not execute this plan speculatively** — start it only when a known-answer canvas detector using this exact technique is observed in the wild (Task 0 records the trigger evidence). This document exists so the mitigation is designed and ready to execute quickly once that happens, not so it ships now.

**Hard dependency:** P0 Task 7 (`docs/superpowers/plans/2026-07-08-spoofing-patch-hardening-p0.md`) — the reimplementation of `patches/canvas-spoofing.patch` against real FF152 source — must be **landed on `main`** before this plan starts. Today `patches/canvas-spoofing.patch` still carries `<verify …>` placeholders and a fictional `OffscreenCanvas::GetDocument()` call (confirmed at plan-write time: `grep -c '<verify' patches/canvas-spoofing.patch` = 2, non-zero); this plan's tasks edit the *landed, real* `CanvasSeedManager::Perturb` and its four real call sites, which do not exist yet. Task 0 gates on this.

**Goal:** Close the specific known-answer extraction vector recorded in the design doc — a solid `fillRect(128)` readback currently yields sparse deterministic 127/129 outlier pixels (the `CanvasSeedManager::Perturb` LSB noise fires independently of local pixel content), which (a) no real renderer produces on a flat fill and (b) is a fixed function of `(seed, content-hash, byte-index)`, so the noise *position* stream is recoverable by an attacker who already knows the input. Make flat/locally-uniform regions read back native while leaving noise intact on textured content, and prove it with a build-tester collector that attempts the attack and asserts it fails.

## Design decision — mitigation approach comparison

The spec names two candidate mitigations. Both are evaluated below against the actual `Perturb` implementation (`patches/canvas-spoofing.patch`, `CanvasSeedManager::Perturb`, `dom/base/CanvasSeedManager.cpp`):

```cpp
// current (pre-P4) loop, unconditional on content:
for (size_t i = 0; i < length; ++i) {
  if ((i & 3u) == 3u) continue;               // skip alpha
  s = s * 1103515245u + 12345u;
  if (s < kThreshold) {                        // density gate only — no content check
    int32_t delta = ((s >> 16) & 1u) ? +strength : -strength;
    data[i] = clamp(data[i] + delta);
  }
}
```

**Option A — Skip perturbation on locally-uniform (flat) regions (recommended).**
Add a neighborhood-uniformity check that only runs on bytes that already passed the density gate (i.e. the ≈0.05%-of-channels candidate set, not the whole buffer): if the current pixel's channel equals the same channel on its immediate left/right/up/down neighbors (clamped at borders), the region is locally flat and the byte is left untouched.
- **Pros:** minimal, surgical — one helper + a 3-argument signature extension + plumbing width/stride into 4 already-landed call sites (P0 Task 7). The density-gate-first ordering means the neighbor check only runs on the rare candidate bytes, so it does not change the hot-loop's big-O on textured canvases. It closes exactly the documented attack: a `fillRect` has no local gradient anywhere, so every candidate byte in it is locally uniform and the whole readback stays byte-identical to native. Preserves every existing invariant (determinism, per-`userContextId` divergence, config-driven density/strength).
- **Cons:** an attacker who probes with *any* non-flat known content (e.g. a two-pixel-wide gradient strip) still sees the sparse ±1 tell there — this closes the solid-fill vector the spec documents, not a general textured known-answer attack. It also removes protection from flat sub-regions of otherwise-textured real canvases (e.g. the solid background behind rendered text), very slightly shrinking the entropy contributed by those pixels.

**Option B — Content-adaptive / stochastic-but-coherent noise model.**
Replace the sparse independent-channel bit-flip with a spatially-correlated field (e.g. blue-noise dither or a small-amplitude smooth field) applied to every pixel, including flat ones, so a solid fill is never byte-uniform but also never sparse-and-independent — it should read like natural sensor/rasterizer variance instead of a synthetic tell.
- **Pros:** closes the general class of known-answer attacks (flat *and* textured probes), keeps full-canvas noise coverage.
- **Cons:** a full redesign of the noise engine (new generation algorithm, new density/strength semantics, touches every byte instead of a sparse fraction — real per-readback cost increase), and it does not obviously *remove* a detectable statistical signature, it *relocates* one: a correlated field has its own fingerprint (autocorrelation, frequency spectrum) that a sufficiently motivated detector can characterize the same way the current sparse-independent one was. Verifying "this doesn't have its own tell" is a research effort (statistical/perceptual test suite), not a build-tester assertion — out of proportion for a phase the spec explicitly scopes to "when observed in the wild."

**Recommendation: Option A.** It is the smallest change that closes the exact, named vulnerability, it is objectively verifiable with a straightforward collector (Task 5), and it does not touch the noise model's core threat properties. Option B is left as a documented idea for a *future* phase if a textured/non-flat known-answer detector is later observed — the same "scope when observed" gating this phase itself is under, so it is out of scope here.

## Architecture

- **`additions/camoucfg/MaskConfig.hpp`:** studied — **no change needed**. `GetBool`/`GetDouble`/`GetUint32` are already generic key/value accessors (used today by `CanvasSeedManager::GetNoiseDensity`/`GetNoiseStrength`); the new `canvas:skipFlatNoise` key follows the same `MaskConfig::GetBool(...)` pattern used elsewhere in this file, so it is consumed, not modified.
- **`patches/canvas-spoofing.patch`** (post-P0-Task7, real FF152 anchors): the mitigation lives entirely in `CanvasSeedManager::Perturb` + a new `IsLocallyUniform` helper (`dom/base/CanvasSeedManager.{cpp,h}` hunks), plus geometry (width/height/stride) plumbed into the same four call sites P0 Task 7 already wires: `CanvasRenderingContext2D.cpp` (`GetImageDataArray`), `dom/html/HTMLCanvasElement.cpp` (`ExtractData`), `dom/canvas/CanvasRenderingContextHelper.cpp` (`ToBlob`), `dom/canvas/ClientWebGLContext.cpp` (`ReadPixels`, already-real, unmodified by Task 7).
- **Schema:** `settings/camoucfg.jvv` + `settings/properties.json` — register `canvas:skipFlatNoise` (bool) in both, following the existing `canvas:aaCapOffset` bool entry as the format template.
- **build-tester:** a new collector (`checkCanvasKnownAnswerResistance`) that positively attempts the known-answer attack and asserts it fails, plus a required edit to P0's existing `checkCanvasPerturbation` (`build-tester/src/lib/checks/collectors.ts`) — see Task 5 for why P0's own solid-fill probe becomes incompatible with this mitigation and must move to textured content.

## Tech Stack

Firefox source patch (unified diff, GNU `gpatch`), the `scripts/rehearse-patch.sh` harness built in P0 Task 1, TypeScript (build-tester), Python (`build-tester/scripts/grading.py`), JSON schema (`.jvv`/`.json`).

## Global Constraints

- Firefox pinned: `version=152.0.4`, `release=beta.25` (`upstream.sh`) — same target as P0.
- Reuse, do not re-create, `scripts/rehearse-patch.sh` (P0 Task 1): `FETCH="curl -fsSL" bash scripts/rehearse-patch.sh canvas-spoofing.patch` must gate `rejects==0 AND skipped==0 AND wrongpath==0 AND fuzz==0 AND max|offset|<=2` before any build.
- Every PR: tied to a GitHub issue; **both** `build-tester/` and `service-tester/` pass; PR body carries concrete evidence (command output + exit status) — repo rule, `CONTRIBUTING.md`.
- Surgical: this phase touches only `CanvasSeedManager`'s noise decision and its call sites' geometry arguments — do not touch density/strength defaults, seed resolution, or the WebRTC/media/orientation work from other phases.
- `patches/canvas-spoofing.patch` is the only patch file in scope. Do not hand-edit the generated `camoufox-*/` tree — all changes are patch-file edits per `CLAUDE.md`.

---

### Task 0: Trigger + dependency gate, tracking issue

**Files:** none (verification + issue only)

- [ ] **Step 1: Confirm the dependency.** `grep -n "<verify\|GetDocument()" patches/canvas-spoofing.patch` must return **no matches** (proves P0 Task 7 landed the real-FF152 reimplementation this plan edits). If it still matches, **stop** — this plan cannot execute until P0 Task 7 is merged to `main`.
- [ ] **Step 2: Record the trigger.** Per the spec's owner decision, this phase is scoped to start "when a detector using known-answer analysis is observed in the wild." Attach the concrete evidence (bot-detection vendor writeup, a captured fingerprinting script performing a solid-fill-then-readback probe, or an internal detection report) to the tracking issue body. Do not open this issue "just in case" — its existence signals the trigger fired.
- [ ] **Step 3: Open the tracking issue.**
```bash
gh issue create --repo lang315/camoufox --title "P4: known-answer canvas-noise mitigation (flat-region skip)" --body "Deferred hardening, now triggered — see attached known-answer detector evidence. Spec: docs/superpowers/specs/2026-07-08-spoofing-patch-hardening-design.md (Phase 4). Depends on P0 Task 7 (landed)."
```
Record issue number `N`.

---

### Task 1: `CanvasSeedManager::Perturb` — locally-uniform skip + config toggle

**Files:** Modify `patches/canvas-spoofing.patch` (the `dom/base/CanvasSeedManager.cpp` / `CanvasSeedManager.h` new-file hunks)

**Interfaces:**
```cpp
// CanvasSeedManager.h
static void Perturb(uint8_t* data, size_t length, uint32_t seed, double density,
                     uint32_t strength, uint32_t width, uint32_t height, uint32_t stride);
static bool GetSkipFlatNoise();  // MaskConfig-backed, default true

// CanvasSeedManager.cpp — private helper
static bool IsLocallyUniform(const uint8_t* data, uint32_t width, uint32_t height,
                              uint32_t stride, size_t byteIndex);
```

- [ ] **Step 1: `IsLocallyUniform`.** Given a candidate byte index, derive `channel = byteIndex % 4`, `pixel = byteIndex / 4`, `row = pixel / width`, `col = pixel % width`. Compare `data[byteIndex]` against the same channel at the left/right/up/down neighbor pixels (using `stride` for row offsets, clamped at the buffer edges — an edge pixel with fewer neighbors is uniform iff all *existing* neighbors match). Return `true` iff every sampled neighbor equals the current value.
- [ ] **Step 2: Extend `Perturb`'s signature** to `(data, length, seed, density, strength, width, height, stride)`. Inside the existing density-gated branch (`if (s < kThreshold)`), add the gate **after** the threshold check (so the neighbor check only runs on the already-rare candidate set, not every byte):
```cpp
if (s < kThreshold) {
  if (GetSkipFlatNoise() && IsLocallyUniform(data, width, height, stride, i)) {
    continue;  // flat region — leave native so a solid fill reads native
  }
  int32_t delta = ((s >> 16) & 1u) ? +static_cast<int32_t>(strength) : -static_cast<int32_t>(strength);
  ...
}
```
- [ ] **Step 3: Add `GetSkipFlatNoise()`**, mirroring `GetNoiseDensity`/`GetNoiseStrength`'s existing pattern:
```cpp
/* static */ bool CanvasSeedManager::GetSkipFlatNoise() {
  if (auto v = MaskConfig::GetBool("canvas:skipFlatNoise")) return v.value();
  return true;  // default on: closes the documented known-answer vector out of the box
}
```
- [ ] **Step 4: Update the header doc comment** on `Perturb` (currently states "Same (data, length, seed) → same output... density: 0..1 fraction of channels to perturb") to note the new geometry params and the accepted residual limitation: flat *sub-regions* of textured content, and the whole buffer for a solid fill, no longer carry noise; non-flat known-answer probes (e.g. gradients) are unaffected and out of scope for this phase (see Design decision, Option B).
- [ ] **Step 5: Commit**
```bash
git add patches/canvas-spoofing.patch
git commit -m "fix(patches): CanvasSeedManager — skip perturbation on locally-uniform regions"
```

---

### Task 2: Plumb width/height/stride through the four call sites

**Files:** Modify `patches/canvas-spoofing.patch` (the `CanvasRenderingContext2D.cpp`, `dom/html/HTMLCanvasElement.cpp`, `dom/canvas/CanvasRenderingContextHelper.cpp`, `dom/canvas/ClientWebGLContext.cpp` hunks landed by P0 Task 7)

Each `CanvasSeedManager::Perturb(...)` call site gains three trailing arguments. Confirm the exact local variable names against the landed P0 Task 7 diff at execution time (P0 Task 7 was itself gated by rehearsal + identifier grep + compile, not a blind hunt — this task inherits that same discipline).

- [ ] **Step 1: `ClientWebGLContext::ReadPixels`** (already real pre-P0, unmodified by Task 7 — concrete today): the function signature already carries `GLsizei width, GLsizei height`; `pii->elementsPerPixel` / `pii->bytesPerElement` are already in scope at the perturb call site (visible in the current patch, line ~469). Pass `width`, `height`, and `stride = width * pii->bytesPerElement * pii->elementsPerPixel`.
- [ ] **Step 2: `CanvasRenderingContext2D::GetImageDataArray`** (the real anchor for `getImageData`, per P0 Task 7's anchor map): the `Span<uint8_t> aData` buffer backs an `ImageData` of known `aWidth`/`aHeight`; ImageData pixel buffers are tightly packed RGBA8, so `stride = aWidth * 4`. Pass `aWidth`, `aHeight`, `aWidth * 4`.
- [ ] **Step 3: `HTMLCanvasElement::ExtractData`** and **`CanvasRenderingContextHelper::ToBlob`**: both use a `gfx::DataSourceSurface::ScopedMap` in `READ_WRITE` mode (already the shape sketched in the pre-Task-7 draft, which is standard Gecko gfx API, not part of what Task 7 found fabricated). Pull `width`/`height` from `snapshot->GetSize()` (or the surface's own `GetSize()`) and `stride` from `map.GetStride()` — **do not assume `stride == width * 4`** here; unlike the tightly-packed `ImageData` case, surface-backed maps can carry platform row padding.
- [ ] **Step 4: Rebuild the length argument consistently** — `length` passed to `Perturb` must still equal `stride * height` at each site (unchanged from the pre-P4 calls); only the three new trailing geometry args are additive.
- [ ] **Step 5: Commit**
```bash
git add patches/canvas-spoofing.patch
git commit -m "fix(patches): pass canvas geometry (width/height/stride) into Perturb at all 4 surfaces"
```

---

### Task 3: Register `canvas:skipFlatNoise` in both config schemas

**Files:** Modify `settings/camoucfg.jvv`, `settings/properties.json`

Per the repo's coherence-chokepoint rule, a config key not registered in **both** files is rejected by the jvv validator. Follow the existing `canvas:aaCapOffset` bool entry as the template in each file.

- [ ] **Step 1: `settings/camoucfg.jvv`** — next to the existing `"canvas:aaOffset": "int",` / `"canvas:aaCapOffset": "bool",` pair (around line 280), add:
```
"canvas:skipFlatNoise": "bool",
```
- [ ] **Step 2: `settings/properties.json`** — next to the existing `{ "property": "canvas:aaCapOffset", "type": "bool" }` entry (around line 91), add:
```json
{ "property": "canvas:skipFlatNoise", "type": "bool" },
```
- [ ] **Step 3: Smoke** — confirm both files remain valid JSON/jvv (`python3 -c "import json; json.load(open('settings/properties.json'))"`; run the project's jvv validator if one is invoked in CI, otherwise a JSON parse is the practical smoke test available locally).
- [ ] **Step 4: Commit**
```bash
git add settings/camoucfg.jvv settings/properties.json
git commit -m "chore(settings): register canvas:skipFlatNoise in camoucfg.jvv + properties.json"
```

---

### Task 4: Rehearsal gate (reuse P0's harness)

**Files:** none (verification only)

- [ ] **Step 1: Gate.** `FETCH="curl -fsSL" bash scripts/rehearse-patch.sh canvas-spoofing.patch` → `rejects=0 skipped=0 wrongpath=0 fuzz=0 max|offset|<=2`, exit 0.
- [ ] **Step 2: Identifier check** (mirrors P0 Task 7 Step 4 — catches a fabricated name before burning a CI build):
```bash
T=.rehearse/canvas-spoofing.patch/tree
grep -n "IsLocallyUniform\|GetSkipFlatNoise" "$T"/dom/base/CanvasSeedManager.cpp "$T"/dom/base/CanvasSeedManager.h
grep -n "CanvasSeedManager::Perturb(" "$T"/dom/canvas/CanvasRenderingContext2D.cpp "$T"/dom/html/HTMLCanvasElement.cpp "$T"/dom/canvas/CanvasRenderingContextHelper.cpp "$T"/dom/canvas/ClientWebGLContext.cpp
```
Expected: every `Perturb(` call now carries 8 arguments (was 5); `IsLocallyUniform`/`GetSkipFlatNoise` defined once, used at every candidate-byte branch. Full linkage proven by compile (Task 6).
- [ ] **Step 3:** no commit — this task is a gate, not a code change.

---

### Task 5: build-tester — known-answer-resistance collector + reconcile P0's `checkCanvasPerturbation`

P0 Task 4 shipped `checkCanvasPerturbation`, which renders a solid `fillRect(128)` (`solidCtx()`) and **requires** `nonUniform(...)` to be `true` on all 4 surfaces to pass. That assumption is now backwards: this phase's entire point is to make a solid fill read back **uniform**. Left as-is, P4 would make P0's own ground-truth collector fail. Both concerns are fixed in this task, in the same files, to avoid a two-PR ordering hazard on `collectors.ts`.

**Files:** Modify `build-tester/src/lib/checks/collectors.ts`, `index.ts`, `types.ts`, `build-tester/scripts/grading.py`

**Interfaces:**
```typescript
export interface CanvasKnownAnswerResult {
  passed: boolean;
  flatFillUniform: boolean;       // solid fillRect(128) readback IS uniform — attack surface closed
  texturedStillPerturbed: boolean; // non-flat probe still shows noise — skip isn't over-broad
  detail: string;
}
```

- [ ] **Step 1: Add a textured probe helper** next to the existing `solidCtx()` in `collectors.ts` — content with both a flat sub-region and a hard edge, so it cannot be fully suppressed by the flat-region skip:
```typescript
function texturedCtx(): CanvasRenderingContext2D {
  const c = document.createElement("canvas"); c.width = CPX; c.height = CPX;
  const x = c.getContext("2d", { willReadFrequently: true })!;
  x.fillStyle = `rgb(${FILL},${FILL},${FILL})`; x.fillRect(0, 0, CPX, CPX);
  const g = x.createLinearGradient(0, 0, CPX, CPX);
  g.addColorStop(0, "rgb(40,40,40)"); g.addColorStop(1, "rgb(220,220,220)");
  x.fillStyle = g; x.fillRect(0, 0, CPX, CPX / 2);
  return x;
}
```
- [ ] **Step 2: New collector `checkCanvasKnownAnswerResistance`** in `collectors.ts` — reuses `nonUniform` (already defined for P0's collector):
```typescript
export async function checkCanvasKnownAnswerResistance(): Promise<CanvasKnownAnswerResult> {
  const flat = solidCtx().getImageData(0, 0, CPX, CPX).data;
  const textured = texturedCtx().getImageData(0, 0, CPX, CPX).data;
  const flatFillUniform = !nonUniform(flat);
  const texturedStillPerturbed = nonUniform(textured);
  const passed = flatFillUniform && texturedStillPerturbed;
  return { passed, flatFillUniform, texturedStillPerturbed,
    detail: passed ? "flat fill native + textured content still perturbed"
      : `FAIL flatFillUniform=${flatFillUniform} texturedStillPerturbed=${texturedStillPerturbed}` };
}
```
- [ ] **Step 3: Reconcile `checkCanvasPerturbation`** (P0's collector, same file) — swap every `solidCtx()` call for `texturedCtx()` in its 4 surface probes (`getImageData`, `toDataURL`, `offscreenBlob`, `webgl`), keeping `nonUniform`/`deterministic` logic unchanged. This keeps P0's ground-truth guarantee ("perturbation fires on all 4 surfaces") true using content the mitigation does **not** suppress, instead of content it now deliberately does.
- [ ] **Step 4: Type + wire** — add `CanvasKnownAnswerResult` to `types.ts`, `canvasKnownAnswerResistance` to `TestResults`; run `checkCanvasKnownAnswerResistance` in `index.ts` alongside the existing `checkCanvasPerturbation` call.
- [ ] **Step 5: Grade** — in `grading.py`, after the existing `canvasPerturbation` block:
```python
    total_checks += 1
    if results.get("canvasKnownAnswerResistance", {}).get("passed"):
        pass_count += 1
```
- [ ] **Step 6: Build** — `cd build-tester && npm run build` → no TS errors.
- [ ] **Step 7: Commit**
```bash
git add build-tester/src/lib/checks/collectors.ts build-tester/src/lib/checks/index.ts build-tester/src/lib/checks/types.ts build-tester/scripts/grading.py
git commit -m "test(build-tester): known-answer-resistance collector; move checkCanvasPerturbation off solid fill"
```

---

### Task 6: CI gate — build + both suites, PR evidence

**Files:** none (dispatch + evidence)

- [ ] **Step 1: Push + dispatch**
```bash
git push -u origin spec/spoofing-patch-hardening
gh workflow run "Build and Release" --repo lang315/camoufox -f build_target=linux-x86_64 --ref spec/spoofing-patch-hardening
```
- [ ] **Step 2: Confirm clean apply** — `gh run view <id> --repo lang315/camoufox --log | grep -iE "FAILED|\.rej|can.?t find file|ignored" || echo "clean apply"` → `clean apply`.
- [ ] **Step 3: build-tester** — `python scripts/run_tests.py <binary> --json /tmp/p4.json`, then assert both `canvasPerturbation.passed` (Task 5's reconciled, textured-content version) and `canvasKnownAnswerResistance.passed` (new) are `true` at `r['profiles'][i]['results']` (same JSON-dump path P0 Task 3/9 wired). A `flatFillUniform=false` failure means the flat-skip did not fire — check Task 1's `GetSkipFlatNoise()` default and Task 2's geometry plumbing before re-dispatching.
- [ ] **Step 4: service-tester** — `cd service-tester && <documented run command>`; capture pass output.
- [ ] **Step 5: PR** — `gh pr create ... --body` with: rehearse-patch output (Task 4, all-zero), CI clean-apply link, `/tmp/p4.json` excerpt (both collectors `passed=true`), service-tester pass, and a one-line pointer to the Design decision section above (why Option A, not B). `Closes #N`.

---

## Self-Review

**Spec coverage (P4 slice):** flat-region skip mitigation (Option 1 in the task brief) → Tasks 1–2; comparison against a content-adaptive/stochastic model (Option 2) with a recommendation → Design decision section; known-answer-attack collector that attempts the attack and asserts it fails → Task 5; both suites + evidence PR + issue → Tasks 0, 6.

**Dependency + trigger discipline:** Task 0 makes both the "P0 Task 7 must be landed" and "only start when a detector is observed" conditions concrete, falsifiable gates (a grep and an issue-body evidence requirement) rather than prose reminders — consistent with this being a deferred, not-scheduled phase.

**Coherence catch:** P0 Task 4's `checkCanvasPerturbation` asserts a solid fill is non-uniform on all 4 surfaces — the literal opposite of what this phase ships. Task 5 fixes that in the same commit as the new collector so the two never coexist in a broken state on `main`.

**Known limitation (explicitly out of scope, not a gap):** non-flat known-answer probes (a gradient or two-pixel-wide known pattern) still expose the sparse ±1 tell; Option B (content-adaptive noise) is the documented follow-up if that is observed, per the same "scope when observed" rule this phase itself is under.

**Placeholder scan:** no `TBD`; every task names real files/functions already established by the P0 Task 7 anchor map, with call-site variable names explicitly flagged "confirm against the landed diff" only where P0 Task 7 itself has not yet fixed the exact identifiers (`GetImageDataArray`'s span, `ExtractData`'s surface map) — consistent with how P0 hedged the same not-yet-landed code.
