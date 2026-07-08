# Spoofing-patch hardening — P0 (correctness gate) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix the confirmed B1 directory bug in `webrtc-ip-spoofing2.patch`, re-anchor the two draft spoofing patches onto real FF152.0.4 source so they apply at the correct location, and prove — with ground-truth build-tester checks — that the canvas and WebRTC spoofs actually fire in the built binary.

**Architecture:** Validation models the *real production apply* (sibling patches applied first, production `patch` flags, reject+fuzz+offset measured) rather than isolated pristine files. A new rehearsal script drives that. Two new build-tester collectors replace the existing false-passing checks (known-answer canvas probe across all four readback surfaces; IPv6/fe80-aware WebRTC collector). P0 ships as its own PR(s); P1/P2/P3 get separate plans.

**Tech Stack:** Firefox source patches (unified diff, GNU `patch`), Python 3.11+ / `scripts/patch.py`, hg raw-file fetch, TypeScript (build-tester checks), GitHub Actions (`build.yml`).

## Global Constraints

- Firefox pinned: `version=152.0.4`, `release=beta.25` (`upstream.sh`). Fetch source from `https://hg.mozilla.org/releases/mozilla-release/raw-file/FIREFOX_152_0_4_RELEASE/<path>`.
- Production patch command (must be mirrored by any verification): `patch -p1 --forward -l --binary` with GNU maxfuzz 2 (`scripts/patch.py` `_apply_and_check`; `CAMOU_PATCH` may point to `gpatch` on macOS).
- Patches are applied in `list_patches` order = **basename sort**, non-roverfox first, roverfox last (`scripts/_mixin.py`).
- Every PR: tied to a GitHub issue; **both** `build-tester/` and `service-tester/` pass; PR body carries concrete evidence (command output + exit status), never prose-only (repo rule + `CLAUDE.md`).
- Surgical changes only: touch only what the task requires; keep the `Makefile` diff clean.
- `bash` network allowlist excludes `hg.mozilla.org`/`archive.mozilla.org` — fetch via the context-mode `ctx_fetch_and_index`/`ctx_execute` path or a runner with open egress, not raw `curl` in the sandbox.

---

### Task 1: Patch-rehearsal harness

Builds the objective gate every later re-anchor task depends on: fetch a patch's real FF152 target files, apply the prerequisite patches then the target with production flags, and report rejects + fuzz + offset per hunk.

**Files:**
- Create: `scripts/rehearse-patch.sh`
- Create: `scripts/rehearse-patch.README.md`

**Interfaces:**
- Produces: `scripts/rehearse-patch.sh <patch-basename>` → exits 0 iff the patch applies with `rejects==0 AND fuzz==0 AND max|offset|<=2`; prints a per-hunk table `file | hunk | offset | fuzz | reject` and leaves the applied tree at `.rehearse/<patch-basename>/tree` for the grep step. Consumed by Tasks 5, 6, 7.

- [ ] **Step 1: Write the harness**

Create `scripts/rehearse-patch.sh`:

```bash
#!/usr/bin/env bash
# Rehearse a single patch against a realistically-sequenced FF152 tree.
# Usage: scripts/rehearse-patch.sh <patch-basename>   e.g. canvas-spoofing.patch
set -euo pipefail

PATCH="${1:?usage: rehearse-patch.sh <patch-basename>}"
REPO_ROOT="$(git rev-parse --show-toplevel)"
PATCH_DIR="$REPO_ROOT/patches"
WORK="$REPO_ROOT/.rehearse/$PATCH"
TREE="$WORK/tree"
HG="https://hg.mozilla.org/releases/mozilla-release/raw-file/FIREFOX_152_0_4_RELEASE"
PATCH_BIN="${CAMOU_PATCH:-patch}"   # gpatch on macOS

# 1. Collect every file path the *target* and its prerequisites touch, so the
#    tree is populated before any apply. Prereqs = every patch that sorts
#    before $PATCH in basename order AND edits a file $PATCH also edits.
mapfile -t TARGET_FILES < <(grep -E '^\+\+\+ b/' "$PATCH_DIR/$PATCH" | sed 's|^+++ b/||')

# Prereq patches: those earlier in basename order that share any target file.
ORDER=$(ls "$PATCH_DIR"/*.patch "$PATCH_DIR"/**/*.patch 2>/dev/null | xargs -n1 basename | sort)
PREREQS=()
for p in $ORDER; do
  [ "$p" = "$PATCH" ] && break
  pf="$PATCH_DIR/$p"; [ -f "$pf" ] || pf=$(find "$PATCH_DIR" -name "$p" | head -1)
  for tf in "${TARGET_FILES[@]}"; do
    if grep -qE "^\+\+\+ b/$(printf '%s' "$tf" | sed 's/[.[\*^$/]/\\&/g')$" "$pf"; then
      PREREQS+=("$pf"); break
    fi
  done
done

# 2. Fetch all files touched by target + prereqs into $TREE.
rm -rf "$WORK"; mkdir -p "$TREE"
declare -A SEEN
fetch_targets() { grep -E '^\+\+\+ b/' "$1" | sed 's|^+++ b/||'; }
{ for pf in "${PREREQS[@]}" "$PATCH_DIR/$PATCH"; do fetch_targets "$pf"; done; } |
while read -r f; do
  [ -n "${SEEN[$f]:-}" ] && continue; SEEN[$f]=1
  # A /dev/null-created file has no upstream source; skip fetch (patch creates it).
  if grep -qE "^--- /dev/null" "$PATCH_DIR/$PATCH"; then :; fi
  mkdir -p "$TREE/$(dirname "$f")"
  if ! ctx-fetch "$HG/$f" > "$TREE/$f" 2>/dev/null; then
    echo "WARN: could not fetch $f (created-from-/dev/null is fine)" >&2
  fi
done

# 3. Apply prereqs (ignore their fuzz — we only measure $PATCH), then target.
cd "$TREE"
for pf in "${PREREQS[@]}"; do
  "$PATCH_BIN" -p1 --forward -l --binary -i "$pf" >/dev/null 2>&1 || true
done

# 4. Apply target, capturing per-hunk offset/fuzz/reject.
OUT="$WORK/apply.out"
"$PATCH_BIN" -p1 --forward -l --binary -i "$PATCH_DIR/$PATCH" > "$OUT" 2>&1 || true

REJECTS=$(find "$TREE" -name '*.rej' | wc -l | tr -d ' ')
FUZZ=$(grep -Eo 'with fuzz [0-9]+' "$OUT" | grep -Eo '[0-9]+' | sort -rn | head -1 || echo 0)
OFFSET=$(grep -Eo 'offset -?[0-9]+' "$OUT" | grep -Eo '\-?[0-9]+' | sed 's/-//' | sort -rn | head -1 || echo 0)
echo "=== $PATCH: rejects=$REJECTS fuzz=${FUZZ:-0} max|offset|=${OFFSET:-0} ==="
grep -E 'Hunk|FAILED|offset|fuzz' "$OUT" || true

[ "$REJECTS" = "0" ] && [ "${FUZZ:-0}" = "0" ] && [ "${OFFSET:-0}" -le 2 ]
```

`ctx-fetch` is a shim for the allowed fetch path (context-mode); document in the README that in CI it is `curl -fsSL`.

- [ ] **Step 2: Write the README**

Create `scripts/rehearse-patch.README.md` with: purpose (models production apply, unlike a pristine per-file dry-run), the pass gate (`rejects==0 AND fuzz==0 AND max|offset|<=2`), why offset matters (fuzz==0 ≠ correct location — a hunk can roam far with zero fuzz), and the `ctx-fetch` vs `curl` note.

- [ ] **Step 3: Smoke-test the harness on an already-clean patch**

Run: `bash scripts/rehearse-patch.sh css-media-spoofing.patch`
Expected: prints `=== css-media-spoofing.patch: rejects=0 fuzz=0 max|offset|=0 ===` and exits 0 (this patch was rebased to FF152 in 26d60e7, so it must be clean; a non-zero result means the harness itself is wrong).

- [ ] **Step 4: Commit**

```bash
git add scripts/rehearse-patch.sh scripts/rehearse-patch.README.md
git commit -m "test(patches): add production-apply rehearsal harness (reject/fuzz/offset gate)"
```

---

### Task 2: Fix B1 — retarget webrtc2's WebRTCIPManager hunks to dom/base/

The class is created at `dom/base/WebRTCIPManager.{h,cpp}` by `webrtc-ip-spoofing.patch`, but `webrtc-ip-spoofing2.patch` edits `dom/media/webrtc/jsapi/WebRTCIPManager.{h,cpp}`. No patch creates the jsapi path → reject / undefined-symbol. Retarget the two hunks.

**Files:**
- Modify: `patches/webrtc-ip-spoofing2.patch` (the `WebRTCIPManager.h` and `WebRTCIPManager.cpp` hunk headers)

**Interfaces:**
- Produces: a `webrtc-ip-spoofing2.patch` whose `WebRTCIPManager` hunks target `dom/base/`. Consumed by Task 7 (re-anchor/verify).

- [ ] **Step 1: Retarget the header hunk**

In `patches/webrtc-ip-spoofing2.patch`, replace the `.h` hunk's file paths:

```
diff --git a/dom/media/webrtc/jsapi/WebRTCIPManager.h b/dom/media/webrtc/jsapi/WebRTCIPManager.h
--- a/dom/media/webrtc/jsapi/WebRTCIPManager.h
+++ b/dom/media/webrtc/jsapi/WebRTCIPManager.h
```
becomes
```
diff --git a/dom/base/WebRTCIPManager.h b/dom/base/WebRTCIPManager.h
--- a/dom/base/WebRTCIPManager.h
+++ b/dom/base/WebRTCIPManager.h
```

- [ ] **Step 2: Retarget the cpp hunk**

Same substitution for the `.cpp`:
```
diff --git a/dom/base/WebRTCIPManager.cpp b/dom/base/WebRTCIPManager.cpp
--- a/dom/base/WebRTCIPManager.cpp
+++ b/dom/base/WebRTCIPManager.cpp
```

- [ ] **Step 3: Verify the header-only edit didn't touch hunk bodies**

Run: `git diff patches/webrtc-ip-spoofing2.patch`
Expected: only the four `diff --git`/`---`/`+++` path lines changed; every `@@`, context, `+`, and `-` line unchanged.

- [ ] **Step 4: Commit**

```bash
git add patches/webrtc-ip-spoofing2.patch
git commit -m "fix(patches): retarget webrtc2 WebRTCIPManager hunks to dom/base (B1)"
```

---

### Task 3: Known-answer canvas collector (build-tester)

Replaces the false-passing perturbation gate. `canvasNoiseDetection` only proves determinism (an unpatched browser passes it). This proves perturbation *fired* on each of the four readback surfaces, is deterministic, and is cross-surface consistent.

**Files:**
- Modify: `build-tester/src/lib/checks/collectors.ts` (add `checkCanvasPerturbation`)
- Modify: `build-tester/src/lib/checks/index.ts` (wire into `runAllChecks`)
- Modify: `build-tester/src/lib/types.ts` (add `CanvasPerturbationResult`)

**Interfaces:**
- Produces: `export async function checkCanvasPerturbation(): Promise<CanvasPerturbationResult>` where
  `CanvasPerturbationResult = { passed: boolean; surfaces: Record<"getImageData"|"toDataURL"|"offscreen"|"webgl", { perturbed: boolean; deterministic: boolean }>; crossSurfaceConsistent: boolean; detail: string }`. Consumed by Task 5 and Task 8.

- [ ] **Step 1: Add the result type**

In `build-tester/src/lib/types.ts` add:

```typescript
export interface CanvasPerturbationResult {
  passed: boolean;
  surfaces: Record<
    "getImageData" | "toDataURL" | "offscreen" | "webgl",
    { perturbed: boolean; deterministic: boolean }
  >;
  crossSurfaceConsistent: boolean;
  detail: string;
}
```

- [ ] **Step 2: Write the collector**

Append to `build-tester/src/lib/checks/collectors.ts`. It renders a solid fill (known answer = every RGB channel exactly 128) and checks each surface deviates from 128 (perturbed) yet is byte-identical on re-read (deterministic):

```typescript
import type { CanvasPerturbationResult } from "../types";

const FILL = 128; // known-answer solid fill value

function solid2d(): CanvasRenderingContext2D {
  const c = document.createElement("canvas");
  c.width = 64; c.height = 64;
  const ctx = c.getContext("2d", { willReadFrequently: true })!;
  ctx.fillStyle = `rgb(${FILL},${FILL},${FILL})`;
  ctx.fillRect(0, 0, 64, 64);
  return ctx;
}

function rgbDeviates(bytes: Uint8ClampedArray | Uint8Array): boolean {
  for (let i = 0; i < bytes.length; i++) {
    if ((i & 3) === 3) continue; // skip alpha
    if (bytes[i] !== FILL) return true;
  }
  return false;
}

export async function checkCanvasPerturbation(): Promise<CanvasPerturbationResult> {
  const surfaces: CanvasPerturbationResult["surfaces"] = {
    getImageData: { perturbed: false, deterministic: false },
    toDataURL: { perturbed: false, deterministic: false },
    offscreen: { perturbed: false, deterministic: false },
    webgl: { perturbed: false, deterministic: false },
  };

  // getImageData
  try {
    const a = solid2d().getImageData(0, 0, 64, 64).data;
    const b = solid2d().getImageData(0, 0, 64, 64).data;
    surfaces.getImageData.perturbed = rgbDeviates(a);
    surfaces.getImageData.deterministic = a.every((v, i) => v === b[i]);
  } catch {}

  // toDataURL (PNG, lossless) — compare two renders' data URLs
  try {
    const c1 = solid2d().canvas.toDataURL("image/png");
    const c2 = solid2d().canvas.toDataURL("image/png");
    // perturbed iff the encoded image differs from a truly-native solid fill:
    // detect via non-uniform pixels after decode.
    const img = new Image(); img.src = c1;
    await img.decode();
    const dc = document.createElement("canvas"); dc.width = 64; dc.height = 64;
    const dctx = dc.getContext("2d")!; dctx.drawImage(img, 0, 0);
    surfaces.toDataURL.perturbed = rgbDeviates(dctx.getImageData(0, 0, 64, 64).data);
    surfaces.toDataURL.deterministic = c1 === c2;
  } catch {}

  // OffscreenCanvas
  try {
    const oc = new OffscreenCanvas(64, 64);
    const octx = oc.getContext("2d")!;
    octx.fillStyle = `rgb(${FILL},${FILL},${FILL})`; octx.fillRect(0, 0, 64, 64);
    const od = octx.getImageData(0, 0, 64, 64).data;
    surfaces.offscreen.perturbed = rgbDeviates(od);
    const oc2 = new OffscreenCanvas(64, 64);
    const octx2 = oc2.getContext("2d")!;
    octx2.fillStyle = `rgb(${FILL},${FILL},${FILL})`; octx2.fillRect(0, 0, 64, 64);
    surfaces.offscreen.deterministic = od.every((v, i) => v === octx2.getImageData(0, 0, 64, 64).data[i]);
  } catch {}

  // WebGL readPixels — clear to the known fill, read back
  try {
    const gc = document.createElement("canvas"); gc.width = 64; gc.height = 64;
    const gl = gc.getContext("webgl")!;
    gl.clearColor(FILL / 255, FILL / 255, FILL / 255, 1);
    gl.clear(gl.COLOR_BUFFER_BIT);
    const px = new Uint8Array(64 * 64 * 4);
    gl.readPixels(0, 0, 64, 64, gl.RGBA, gl.UNSIGNED_BYTE, px);
    surfaces.webgl.perturbed = rgbDeviates(px);
    const px2 = new Uint8Array(64 * 64 * 4);
    gl.readPixels(0, 0, 64, 64, gl.RGBA, gl.UNSIGNED_BYTE, px2);
    surfaces.webgl.deterministic = px.every((v, i) => v === px2[i]);
  } catch {}

  const all = Object.values(surfaces);
  const perturbedAll = all.every((s) => s.perturbed);
  const deterministicAll = all.every((s) => s.deterministic);
  const crossSurfaceConsistent = surfaces.getImageData.perturbed === surfaces.toDataURL.perturbed;
  const passed = perturbedAll && deterministicAll && crossSurfaceConsistent;
  return {
    passed, surfaces, crossSurfaceConsistent,
    detail: passed
      ? "All four surfaces perturbed, deterministic, cross-consistent"
      : `perturbedAll=${perturbedAll} deterministicAll=${deterministicAll} crossConsistent=${crossSurfaceConsistent}`,
  };
}
```

- [ ] **Step 3: Wire into runAllChecks**

In `build-tester/src/lib/checks/index.ts`, import and run it as a new phase; add `canvasPerturbation` to the returned `TestResults` (add the field to `TestResults` in `types.ts` too):

```typescript
  const { collectFingerprints, checkWebRTC, checkCanvasPerturbation } = await import("./collectors");
  // ... after webrtc phase:
  const canvasPerturbation = await checkCanvasPerturbation();
  onPhaseComplete?.({ phase: "canvasPerturbation" });
  // ... include `canvasPerturbation` in the returned object
```

- [ ] **Step 4: Build build-tester to typecheck**

Run: `cd build-tester && npm install && npm run build`
Expected: compiles with no TypeScript errors (the new field is present on `TestResults`).

- [ ] **Step 5: Commit**

```bash
git add build-tester/src/lib/checks/collectors.ts build-tester/src/lib/checks/index.ts build-tester/src/lib/types.ts
git commit -m "test(build-tester): known-answer canvas perturbation collector (4 surfaces)"
```

---

### Task 4: IPv6/fe80-aware WebRTC collector (build-tester)

`checkWebRTC` matches IPv4 RFC1918 only and its candidate regex needs a fully-expanded 8-group IPv6, so it cannot see a compressed `fe80::…` leak. Add a collector that forces host candidates on and asserts no host fe80 IID leaks.

**Files:**
- Modify: `build-tester/src/lib/checks/collectors.ts` (add `checkWebRTCLinkLocal`)
- Modify: `build-tester/src/lib/checks/index.ts` (wire in)
- Modify: `build-tester/src/lib/types.ts` (add `WebRTCLinkLocalResult`)
- Modify: `build-tester/scripts/presets.py` or the launch prefs used by `run_tests.py` to set `media.peerconnection.ice.obfuscate_host_addresses=false` for this test (find the pref-injection point; see Step 1).

**Interfaces:**
- Produces: `export async function checkWebRTCLinkLocal(): Promise<WebRTCLinkLocalResult>` where
  `WebRTCLinkLocalResult = { passed: boolean; linkLocalCandidates: string[]; detail: string }`. Consumed by Task 5 and Task 8.

- [ ] **Step 1: Find where run_tests sets prefs, add the obfuscation-off pref**

Run: `grep -rn "obfuscate_host_addresses\|user.js\|prefs\|set_pref\|CAMOU" build-tester/scripts/*.py`
Then add `user_pref("media.peerconnection.ice.obfuscate_host_addresses", false);` to the profile the runner launches (so real host `fe80:` candidates surface). Document the exact file/line you changed in the commit body.

- [ ] **Step 2: Add the result type**

In `build-tester/src/lib/types.ts`:

```typescript
export interface WebRTCLinkLocalResult {
  passed: boolean;
  linkLocalCandidates: string[];
  detail: string;
}
```

- [ ] **Step 3: Write the collector**

Append to `build-tester/src/lib/checks/collectors.ts`. Compressed-IPv6-aware fe80 match; fail if any fe80 candidate carries a host-shaped (EUI-64 `ff:fe`) IID:

```typescript
import type { WebRTCLinkLocalResult } from "../types";

export async function checkWebRTCLinkLocal(): Promise<WebRTCLinkLocalResult> {
  const res: WebRTCLinkLocalResult = { passed: true, linkLocalCandidates: [], detail: "" };
  try {
    if (typeof RTCPeerConnection === "undefined") return { ...res, detail: "no RTCPeerConnection" };
    const pc = new RTCPeerConnection();
    const found = new Set<string>();
    const done = new Promise<void>((resolve) => {
      const t = setTimeout(resolve, 5000);
      pc.onicecandidate = (e) => {
        if (!e.candidate) { clearTimeout(t); resolve(); return; }
        // fe80::/10 — compressed or expanded
        const m = e.candidate.candidate.match(/fe80:[0-9a-fA-F:]+/i);
        if (m) found.add(m[0]);
        if (e.candidate.address && /^fe80:/i.test(e.candidate.address)) found.add(e.candidate.address);
      };
    });
    pc.createDataChannel("x");
    await pc.setLocalDescription(await pc.createOffer());
    await done;
    pc.close();
    res.linkLocalCandidates = Array.from(found);
    // Host EUI-64 IID contains ':ff:fe' in the middle 64 bits. Any such candidate = MAC leak.
    const leak = res.linkLocalCandidates.some((ip) => /ff:fe/i.test(ip));
    res.passed = !leak;
    res.detail = leak
      ? "EUI-64 host IID leaked in fe80 candidate: " + res.linkLocalCandidates.join(", ")
      : res.linkLocalCandidates.length
        ? "fe80 present but fabricated (no ff:fe host IID): " + res.linkLocalCandidates.join(", ")
        : "no fe80 candidates";
  } catch (e: any) {
    res.detail = "link-local check failed: " + e.message;
  }
  return res;
}
```

- [ ] **Step 4: Wire into runAllChecks + TestResults** (same pattern as Task 3 Step 3), field `webrtcLinkLocal`.

- [ ] **Step 5: Build to typecheck**

Run: `cd build-tester && npm run build`
Expected: no TypeScript errors.

- [ ] **Step 6: Commit**

```bash
git add build-tester/src/lib/checks/collectors.ts build-tester/src/lib/checks/index.ts build-tester/src/lib/types.ts build-tester/scripts/
git commit -m "test(build-tester): IPv6/fe80-aware WebRTC link-local leak collector"
```

---

### Task 5: Prove the bug first (baseline against the current binary)

Do not manufacture a fix for a non-bug. Run the new collectors against the *existing* FF152 binary and record which spoofs are already inert.

**Files:**
- Create: `docs/superpowers/plans/p0-baseline.md` (evidence artifact)

**Interfaces:**
- Consumes: the current CI artifact `CamoufoxBuilds-macos-arm64` (run 28855741707) or a fresh Linux build; Tasks 3 & 4 collectors.

- [ ] **Step 1: Get a current binary**

Run: `gh run download 28855741707 --repo lang315/camoufox --name CamoufoxBuilds-macos-arm64 -D ~/Downloads/camoufox-mac` (or dispatch a fresh Linux build if arch mismatch).

- [ ] **Step 2: Run build-tester with the new collectors against it**

Run: `cd build-tester && python scripts/run_tests.py <path-to-camoufox-bin>`
Record: `canvasPerturbation.passed`, per-surface `perturbed`, and `webrtcLinkLocal.passed`.

- [ ] **Step 3: Record the branch decision**

Write `docs/superpowers/plans/p0-baseline.md` capturing the raw results and the conclusion:
- If a surface is already perturbed → its re-anchor task (6/7) reduces to deleting `<verify>`/placeholder lines + a clean re-anchor, no behavior change.
- If inert → full re-anchor needed.
Commit:

```bash
git add docs/superpowers/plans/p0-baseline.md
git commit -m "docs(p0): baseline canvas/webrtc spoof state on current FF152 binary"
```

---

### Task 6: Re-anchor canvas-spoofing.patch onto FF152

Rewrite each edit hunk with fabricated context onto the real fetched source; the rehearsal harness is the objective gate. (Anchor bytes are discovered against fetched source — this is third-party-source patch work, not a placeholder; the pass condition is objective.)

**Files:**
- Modify: `patches/canvas-spoofing.patch` (the 4 edit hunks into `CanvasRenderingContext2D.cpp`, `HTMLCanvasElement.cpp`, `OffscreenCanvas.cpp`, `ClientWebGLContext.cpp`; the new-file and moz.build hunks stay)

**Interfaces:**
- Consumes: `scripts/rehearse-patch.sh` (Task 1). Produces: a `canvas-spoofing.patch` that passes the rehearsal gate.

- [ ] **Step 1: Measure the current state**

Run: `bash scripts/rehearse-patch.sh canvas-spoofing.patch`
Expected initially: FAIL — non-zero fuzz/offset or rejects on the four `.cpp` edit hunks (they carry `// (existing snapshot/copy code…)` / `<verify…>` fake context). Note each failing hunk from `.rehearse/canvas-spoofing.patch/tree/**/*.rej`.

- [ ] **Step 2: Delete placeholder lines and re-anchor each failing hunk**

For each of `GetImageData`, `ExtractData`, `OffscreenCanvas::ConvertToBlob`, `ClientWebGLContext::ReadPixels`: open the fetched file under `.rehearse/canvas-spoofing.patch/tree/…`, find the real insertion point (right after the pixel buffer is populated / mapped for encode / read back), and rewrite the hunk's context lines (the ` `-prefixed lines and the `@@` counts) to match the real source. Remove every `// (existing …)` and `// <verify …>` line. Keep all `+`-added spoof lines byte-for-byte.

- [ ] **Step 3: Re-run the gate until clean**

Run: `bash scripts/rehearse-patch.sh canvas-spoofing.patch`
Expected: `rejects=0 fuzz=0 max|offset|<=2`, exit 0.

- [ ] **Step 4: Structural grep — spoof calls land inside their functions**

Run:
```bash
T=.rehearse/canvas-spoofing.patch/tree
grep -n "CanvasSeedManager::Perturb" "$T/dom/canvas/CanvasRenderingContext2D.cpp" "$T/dom/canvas/HTMLCanvasElement.cpp" "$T/dom/canvas/OffscreenCanvas.cpp" "$T/dom/canvas/ClientWebGLContext.cpp"
grep -n "CanvasSeedManager.cpp" "$T/dom/base/moz.build"
```
Expected: each `Perturb` call appears inside the intended function body (verify by surrounding lines); `CanvasSeedManager.cpp` is in the `UNIFIED_SOURCES` block of `dom/base/moz.build`.

- [ ] **Step 5: Commit**

```bash
git add patches/canvas-spoofing.patch
git commit -m "fix(patches): re-anchor canvas-spoofing onto FF152 (0 fuzz/offset, verified)"
```

---

### Task 7: Re-anchor webrtc-ip-spoofing2.patch onto FF152

After the B1 retarget (Task 2), re-anchor the remaining hunks (the `#include` block with the `<verify>` note, `isSpecialIP`, `getMaskForIP`, and the retargeted `dom/base/WebRTCIPManager` hunks).

**Files:**
- Modify: `patches/webrtc-ip-spoofing2.patch`

**Interfaces:**
- Consumes: Task 1 harness, Task 2 output. Produces: a `webrtc-ip-spoofing2.patch` that passes the gate and whose `getMaskForIP` calls resolve to symbols added by the same patch.

- [ ] **Step 1: Measure**

Run: `bash scripts/rehearse-patch.sh webrtc-ip-spoofing2.patch`
Expected initially: FAIL (the `#include` hunk carries `<verify exact line — include block … insert next to the other mozilla/* headers>`).

- [ ] **Step 2: Re-anchor + delete placeholders** — rewrite the `#include`, `isSpecialIP`, and `getMaskForIP` hunk context against the fetched `PeerConnectionImpl.cpp`; confirm the `dom/base/WebRTCIPManager.{h,cpp}` hunks apply onto the class body created by `webrtc-ip-spoofing.patch`. Delete every `<verify …>` line.

- [ ] **Step 3: Gate**

Run: `bash scripts/rehearse-patch.sh webrtc-ip-spoofing2.patch`
Expected: `rejects=0 fuzz=0 max|offset|<=2`, exit 0.

- [ ] **Step 4: Structural grep — symbol linkage**

Run:
```bash
T=.rehearse/webrtc-ip-spoofing2.patch/tree
grep -n "GetLocalIPv4\|GetLocalIPv6" "$T/dom/media/webrtc/jsapi/PeerConnectionImpl.cpp" "$T/dom/base/WebRTCIPManager.h"
```
Expected: `getMaskForIP` calls `GetLocalIPv4/v6` AND those methods are declared in `dom/base/WebRTCIPManager.h` (call site + declaration both present → no undefined symbol).

- [ ] **Step 5: Commit**

```bash
git add patches/webrtc-ip-spoofing2.patch
git commit -m "fix(patches): re-anchor webrtc-ip-spoofing2 onto FF152 (0 fuzz/offset, verified)"
```

---

### Task 8: CI gate — build + prove the fix end-to-end

**Files:**
- (no source changes) — dispatch + evidence collection

**Interfaces:**
- Consumes: all prior tasks on the branch; `.github/workflows/build.yml` (`workflow_dispatch`, `build_target`).

- [ ] **Step 1: Push the branch and dispatch a Linux build**

```bash
git push -u origin spec/spoofing-patch-hardening
gh workflow run "Build and Release" --repo lang315/camoufox -f build_target=linux-x86_64 --ref spec/spoofing-patch-hardening
```

- [ ] **Step 2: Confirm patch-apply stage passed (no rejects at `make dir`)**

Poll: `gh run view <run-id> --repo lang315/camoufox --log | grep -iE "hunk|reject|FAILED" || echo "clean apply"`
Expected: `clean apply` (the rehearsal already guaranteed this, but the real `make dir` is the authoritative check — the sibling patches shift context and only the full run proves it).

- [ ] **Step 3: Run build-tester against the artifact**

```bash
gh run download <run-id> --repo lang315/camoufox --name CamoufoxBuilds-linux-x86_64 -D /tmp/cf
cd build-tester && python scripts/run_tests.py /tmp/cf/<camoufox-bin>
```
Expected: `canvasPerturbation.passed == true` (all four surfaces perturbed + deterministic + cross-consistent) and `webrtcLinkLocal.passed == true` (no `ff:fe` host IID in any fe80 candidate).

- [ ] **Step 4: Run service-tester (repo rule: both suites per PR)**

Run: `cd service-tester && <its documented run command>`
Expected: pass. Capture output.

- [ ] **Step 5: Open the PR with evidence**

```bash
gh pr create --repo lang315/camoufox --base main --head spec/spoofing-patch-hardening \
  --title "P0: fix + re-anchor canvas/webrtc spoofing patches (FF152)" \
  --body "$(cat <<'BODY'
Closes #<issue>.

## What
- B1: retarget webrtc2 WebRTCIPManager hunks dom/media/webrtc/jsapi -> dom/base (they rejected/compiled-undefined before).
- Re-anchor canvas-spoofing + webrtc-ip-spoofing2 onto FF152 (0 fuzz/offset, structural grep verified).
- New ground-truth build-tester collectors (known-answer canvas 4-surface; IPv6/fe80 WebRTC).

## Evidence
- rehearse-patch.sh: canvas + webrtc2 => rejects=0 fuzz=0 max|offset|<=2 [paste]
- make dir on CI: clean apply [link]
- build-tester: canvasPerturbation.passed=true, webrtcLinkLocal.passed=true [paste]
- service-tester: pass [paste]
- baseline (pre-fix) vs post-fix: [link to p0-baseline.md]
BODY
)"
```

---

## Self-Review

**Spec coverage (P0 slice of spec r2):**
- B1 directory bug → Task 2. ✓
- Production-apply rehearsal (reject/fuzz/offset, not pristine dry-run) → Task 1 + used in 6/7. ✓
- Delete `<verify>`/placeholders + re-anchor 4 canvas + webrtc2 hunks → Tasks 6, 7. ✓
- Ground-truth canvas known-answer 4-surface collector → Task 3. ✓
- fe80/IPv6 WebRTC collector + obfuscation-off pref → Task 4. ✓
- Prove-bug-first branch → Task 5. ✓
- Structural grep (call inside function, source registered) → Tasks 6.4, 7.4. ✓
- CI gate + both test suites + evidence PR → Task 8. ✓
- Out of P0 scope (own plans): C++ coherence chokepoint, goapi Validate(), orientation/media-codec, system-color patch, P2 coverage, P3 persistence, P4 noise mitigation. Stated in header.

**Placeholder scan:** the re-anchor tasks (6/7) intentionally discover anchor bytes against fetched source — the deliverable is objectively gated by the rehearsal harness (0 reject/fuzz/small offset) + structural grep, not a "TODO". No `TBD`/"handle edge cases"/"similar to Task N". Collector and harness code is complete.

**Type consistency:** `CanvasPerturbationResult` / `WebRTCLinkLocalResult` defined in Task 3/4 Step 1 and consumed with the same field names in Tasks 5 & 8. `checkCanvasPerturbation` / `checkWebRTCLinkLocal` names consistent across index.ts wiring and CI assertions. Harness contract (`rehearse-patch.sh <basename>` → exit 0 iff gate) consistent across Tasks 6/7.

**One open dependency to resolve at execution:** Task 4 Step 1 must locate the runner's pref-injection point (`grep` provided); if `run_tests.py` has no pref hook, add a `user.js` to the launched profile — do not skip the obfuscation-off pref or the fe80 collector is unfalsifiable.
