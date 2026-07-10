# Spoofing-patch hardening — P0 (correctness gate) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Revision:** r3 — after a second multi-subagent review that fetched real FF152 source and found `canvas-spoofing.patch` is **fabricated, not merely drafted**: `OffscreenCanvas::GetDocument()` does not exist, `ConvertToBlob` has none of the patched shape (real encode goes through `CanvasRenderingContextHelper::ToBlob`), the `HTMLCanvasElement.cpp` hunk targets `dom/canvas/` which is a **404** (real path `dom/html/HTMLCanvasElement.cpp`), and `GetImageData`'s buffer is a `Span<uint8_t> aData` inside `GetImageDataArray` (not `data`/`length`). Only `ClientWebGLContext::ReadPixels` has real anchors. So the canvas half of P0 is a **reimplementation** against real FF152 semantics, not a re-anchor (Task 7). r3 also fixes the WebRTC test to positively exercise B1, corrects the JSON evidence path, injects `canvas:seed`, and makes perturbation detection quantization-robust.

**Goal:** Fix the confirmed B1 directory bug in `webrtc-ip-spoofing2.patch`; reimplement the canvas perturbation hunks against real FF152 source so they compile and fire; and prove — with reachable, falsifiable, positively-graded build-tester checks — that the canvas and WebRTC (incl. B1 local-IP replacement) spoofs actually run in the built binary.

**Architecture:** Validation models the real production apply (sibling patches first, production flags, reject+fuzz+offset+skip+wrongpath). Two build-tester collectors are wired into `grading.py` (counted toward the exit code) and `runner.py` gains a `--json` dump of the full per-profile result. Perturbation is detected as **non-uniformity** of a solid readback (immune to GL float→byte quantization), per patched surface. The WebRTC collector is a *positive* known-answer test that **requires** the fabricated local value to appear — the only runtime exercise of the B1 fix. P0 ships as its own PR(s); P1–P4 get separate plans.

**Tech Stack:** Firefox source patches (unified diff, GNU `gpatch`), Python 3.11+ / `scripts/patch.py`, hg raw-file fetch, TypeScript (build-tester), GitHub Actions.

## Global Constraints

- Firefox pinned: `version=152.0.4`, `release=beta.25` (`upstream.sh`). Fetch from `https://hg.mozilla.org/releases/mozilla-release/raw-file/FIREFOX_152_0_4_RELEASE/<path>`.
- Production patch command any verification MUST mirror: `patch -p1 --forward -l --binary`, GNU maxfuzz 2 (`scripts/patch.py:129-130`). Use `gpatch` on macOS.
- **`patch.py` gates only on `.rej` files and ignores the process return code (`patch.py:137-148`)** — a hunk whose target file is missing is silently skipped with no `.rej` (this is how B1 hid). It does NOT suppress stdout (`patch.py:129` uses `stdout=sys.stdout`), so "can't find file" text reaches the CI log; the blindness is in pass/fail bookkeeping only. Any rehearsal must check exit status, skip text, and wrong-path (404) targets.
- Apply order = `sorted(list_files, key=os.path.basename)` (`scripts/_mixin.py:78`), pure basename sort.
- Tooling floor: harness needs **bash ≥ 4** (`mapfile`, `declare -A`, `globstar`) and `gpatch`; fail fast if unmet.
- Every PR: tied to a GitHub issue (Task 0); **both** `build-tester/` and `service-tester/` pass; PR body carries concrete evidence (command output + exit status).
- Surgical: `git add` exact files, never a whole directory.
- Egress: the sandbox bash allowlist excludes `hg.mozilla.org`. Fetch runs on a host/runner with open egress (`curl`) via the `FETCH` env, or a context-mode tool outside bash.

---

### Task 0: Tracking issue + gitignore hygiene

**Files:** Modify `.gitignore`

- [ ] **Step 1: Open the tracking issue**

Run: `gh issue create --repo lang315/camoufox --title "P0: fix + reimplement canvas/webrtc spoofing patches (FF152)" --body "Correctness gate — B1 dir fix, reimplement fabricated canvas hunks, positive ground-truth collectors. Spec: docs/superpowers/specs/2026-07-08-spoofing-patch-hardening-design.md"`
Record issue number `N`.

- [ ] **Step 2: Ignore rehearsal litter** — add to `.gitignore`:
```
.rehearse/
*.rej
```

- [ ] **Step 3: Commit**
```bash
git add .gitignore
git commit -m "chore: ignore patch-rehearsal artifacts (.rehearse/, *.rej)"
```

---

### Task 1: Patch-rehearsal harness (portable, exit-status + wrong-path aware)

**Files:** Create `scripts/rehearse-patch.sh`, `scripts/rehearse-patch.README.md`

**Interfaces:** `FETCH="curl -fsSL" scripts/rehearse-patch.sh <patch-basename>` → exit 0 iff `rejects==0 AND skipped==0 AND wrongpath==0 AND fuzz==0 AND max|offset|<=2`; leaves applied tree at `.rehearse/<patch>/tree`. Consumed by Tasks 7, 8.

- [ ] **Step 1: Write the harness**

Create `scripts/rehearse-patch.sh`. Key r3 change vs r2: a 404 on an EDITED target = the patch names a nonexistent FF152 file (B1-class wrong-path bug) → reported as `wrongpath`, distinct from a network error.

```bash
#!/usr/bin/env bash
# FETCH="curl -fsSL" scripts/rehearse-patch.sh <patch-basename>
set -euo pipefail; shopt -s globstar
command -v gpatch >/dev/null || { echo "need gpatch"; exit 3; }
[ "${BASH_VERSINFO:-0}" -ge 4 ] || { echo "need bash>=4"; exit 3; }
: "${FETCH:?set FETCH, e.g. FETCH='curl -fsSL'}"
PATCH="${1:?usage: rehearse-patch.sh <patch-basename>}"
ROOT="$(git rev-parse --show-toplevel)"; PDIR="$ROOT/patches"
WORK="$ROOT/.rehearse/$PATCH"; TREE="$WORK/tree"
HG="https://hg.mozilla.org/releases/mozilla-release/raw-file/FIREFOX_152_0_4_RELEASE"
PB="${CAMOU_PATCH:-gpatch}"
pf(){ local n="$1"; [ -f "$PDIR/$n" ] && echo "$PDIR/$n" || find "$PDIR" -name "$n" | head -1; }
edited(){ awk '/^--- \/dev\/null/{s=1;next} /^\+\+\+ b\//{if(!s)print substr($0,7);s=0}' "$1"; }
created(){ awk '/^--- \/dev\/null/{g=1;next} /^\+\+\+ b\//{if(g)print substr($0,7);g=0}' "$1"; }
mapfile -t TARGET_EDIT < <(edited "$PDIR/$PATCH")
mapfile -t TARGET_NEW  < <(created "$PDIR/$PATCH")
mapfile -t ORDER < <(ls "$PDIR"/**/*.patch | xargs -n1 basename | sort -u)
PREREQS=()
for p in "${ORDER[@]}"; do [ "$p" = "$PATCH" ] && break
  ppath="$(pf "$p")"
  for tf in "${TARGET_EDIT[@]}"; do edited "$ppath" | grep -qxF "$tf" && { PREREQS+=("$ppath"); break; }; done
done
rm -rf "$WORK"; mkdir -p "$TREE"; WRONG=0
declare -A SEEN
for src in "${PREREQS[@]}" "$PDIR/$PATCH"; do
  while read -r f; do
    [ -z "$f" ] && continue; [ -n "${SEEN[$f]:-}" ] && continue; SEEN[$f]=1
    for nf in "${TARGET_NEW[@]}"; do [ "$f" = "$nf" ] && continue 2; done
    mkdir -p "$TREE/$(dirname "$f")"
    code=$($FETCH -w '%{http_code}' -o "$TREE/$f" "$HG/$f" 2>/dev/null || echo 000)
    if [ "$code" = 404 ]; then
      # only a wrong-path bug if THIS patch edits it (not a prereq-only file)
      for tf in "${TARGET_EDIT[@]}"; do [ "$f" = "$tf" ] && { echo "WRONGPATH: $PATCH edits nonexistent FF152 file $f"; WRONG=$((WRONG+1)); }; done
      rm -f "$TREE/$f"
    elif [ "$code" != 200 ]; then echo "FETCH FAIL $f ($code)"; exit 4; fi
  done < <(edited "$src")
done
cd "$TREE"
for p in "${PREREQS[@]}"; do "$PB" -p1 --forward -l --binary -i "$p" >/dev/null 2>&1 || true; done
OUT="$WORK/apply.out"; set +e; "$PB" -p1 --forward -l --binary -i "$PDIR/$PATCH" >"$OUT" 2>&1; RC=$?; set -e
REJ=$(find "$TREE" -name '*.rej' | wc -l | tr -d ' ')
SKIP=$(grep -ciE 'can.?t find file|ignored|Skipping' "$OUT" || true)
FUZZ=$(grep -oE 'with fuzz [0-9]+' "$OUT" | grep -oE '[0-9]+' | sort -rn | head -1); FUZZ=${FUZZ:-0}
OFF=$(grep -oE 'offset -?[0-9]+' "$OUT" | grep -oE -- '-?[0-9]+' | tr -d - | sort -rn | head -1); OFF=${OFF:-0}
echo "=== $PATCH: rc=$RC rejects=$REJ skipped=$SKIP wrongpath=$WRONG fuzz=$FUZZ max|offset|=$OFF ==="
grep -E 'Hunk|FAILED|ignored|offset|fuzz|find file' "$OUT" || true
[ "$REJ" = 0 ] && [ "$SKIP" = 0 ] && [ "$WRONG" = 0 ] && [ "$FUZZ" = 0 ] && [ "$OFF" -le 2 ]
```
(`curl -fsSL -w '%{http_code}' -o file url` works; the leading `FETCH` flags precede the `-w`/`-o` this script appends.)

- [ ] **Step 2: README** — document the gate (`rejects==0 AND skipped==0 AND wrongpath==0 AND fuzz==0 AND max|offset|<=2`), why each term exists (skip = patch.py return-code blindness; wrongpath = B1-class nonexistent target; offset = fuzz==0 ≠ correct location), and the `FETCH`/bash4/gpatch floor.

- [ ] **Step 3: Smoke-test** — `FETCH="curl -fsSL" bash scripts/rehearse-patch.sh css-media-spoofing.patch` → `rc=0 rejects=0 skipped=0 wrongpath=0 fuzz=0 max|offset|=0`, exit 0.

- [ ] **Step 4: Commit**
```bash
git add scripts/rehearse-patch.sh scripts/rehearse-patch.README.md
git commit -m "test(patches): rehearsal harness (reject/skip/wrongpath/fuzz/offset gate)"
```

---

### Task 2: Fix B1 — retarget webrtc2's WebRTCIPManager hunks to dom/base/

The class is created at `dom/base/WebRTCIPManager.{h,cpp}` (`webrtc-ip-spoofing.patch:5,157`); `webrtc-ip-spoofing2.patch:121,139` edits `dom/media/webrtc/jsapi/WebRTCIPManager.{h,cpp}`. Retarget.

**Files:** Modify `patches/webrtc-ip-spoofing2.patch`

- [ ] **Step 1/2:** In both `WebRTCIPManager.h` and `.cpp` hunks replace `dom/media/webrtc/jsapi/WebRTCIPManager` → `dom/base/WebRTCIPManager` in the `diff --git`, `---`, `+++` lines (six lines total).
- [ ] **Step 3:** `git diff patches/webrtc-ip-spoofing2.patch` → only the six path lines changed.
- [ ] **Step 4: Commit** — `git commit -m "fix(patches): retarget webrtc2 WebRTCIPManager hunks to dom/base (B1)"`

---

### Task 3: Grade + expose collectors (JSON dumped in runner.py, not run_tests.py)

`grading.py:count_all_checks` is hardcoded per key; new collectors won't count. And the raw `results` object lives **per-profile inside `runner.py`** (assembled into `full_result` before the return near `runner.py:370`) — NOT in `run_tests.py:main()`. Wire both.

**Files:** Modify `build-tester/scripts/grading.py:44-47`, `build-tester/scripts/runner.py`, `build-tester/scripts/run_tests.py`

- [ ] **Step 1: Count both collectors** — in `grading.py`, after the WebRTC block (line 47):
```python
    total_checks += 1
    if results.get("canvasPerturbation", {}).get("passed"):
        pass_count += 1
    total_checks += 1
    if results.get("webrtcLinkLocal", {}).get("passed"):
        pass_count += 1
```

- [ ] **Step 2: Dump full_result from runner.py** — thread a `json_path` param from `run_tests.py` argparse into `runner.run_tests(...)`; immediately before the final `return` (~`runner.py:370`, where `full_result` holds `profiles/crossProfile/overallGrade/...`):
```python
    if json_path:
        import json
        with open(json_path, "w") as fh:
            json.dump(full_result, fh, indent=2)
        print(f"wrote raw results to {json_path}")
```
In `run_tests.py`: `parser.add_argument("--json")` and pass `args.json` through to `run_tests(...)`.

- [ ] **Step 3: Smoke** — `cd build-tester && python -c "import scripts.grading, scripts.runner"` → no error.

- [ ] **Step 4: Commit**
```bash
git add build-tester/scripts/grading.py build-tester/scripts/runner.py build-tester/scripts/run_tests.py
git commit -m "test(build-tester): grade canvas/webrtc collectors, dump full_result via --json"
```

---

### Task 4: Non-uniformity canvas collector (quantization-robust, seed injected)

Perturbation = a solid readback becomes **non-uniform** (sparse ±1 outliers). Native readback is uniform whatever its quantized value (127 or 128) — so this is immune to the `clearColor(128/255)` float→byte truncation that a "differs-from-128" test trips on. Requires a non-zero `canvas:seed` (Perturb no-ops on seed 0) — inject it. Probes only patched surfaces; the offscreen surface is covered once Task 7 reimplements it (until then, expect `offscreen*` red — that is the signal Task 7 isn't done).

**Files:** Modify `build-tester/scripts/runner.py` (inject `canvas:seed` for the test profile), `build-tester/src/lib/checks/collectors.ts`, `index.ts`, `types.ts`

**Interfaces:** `checkCanvasPerturbation(): Promise<CanvasPerturbationResult>`, `CanvasPerturbationResult = { passed:boolean; surfaces:Record<"getImageData"|"toDataURL"|"offscreenBlob"|"webgl",{perturbed:boolean;deterministic:boolean}>; seedPresent:boolean; detail:string }`.

- [ ] **Step 1: Ensure a canvas seed** — confirm the test preset carries a non-zero `canvas:seed` (grep `runner.py`/`presets.py` for `canvas:seed`/`setCanvasSeed`); if absent, add `"canvas:seed": 424242` to the CAMOU_CONFIG/initScript the runner injects for the profile the JSON dump targets, and expose `window.__canvasSeedSet__ = true`.

- [ ] **Step 2: Type** (`types.ts`):
```typescript
export interface CanvasPerturbationResult {
  passed: boolean;
  surfaces: Record<"getImageData"|"toDataURL"|"offscreenBlob"|"webgl", {perturbed:boolean; deterministic:boolean}>;
  seedPresent: boolean;
  detail: string;
}
```

- [ ] **Step 3: Collector** (`collectors.ts`) — 256px; `nonUniform` replaces the FILL-constant test:
```typescript
import type { CanvasPerturbationResult } from "../types";
const CPX = 256, FILL = 128;
function solidCtx(): CanvasRenderingContext2D {
  const c = document.createElement("canvas"); c.width = CPX; c.height = CPX;
  const x = c.getContext("2d", { willReadFrequently: true })!;
  x.fillStyle = `rgb(${FILL},${FILL},${FILL})`; x.fillRect(0, 0, CPX, CPX); return x;
}
function nonUniform(b: Uint8ClampedArray | Uint8Array): boolean {
  let ref = -1;
  for (let i = 0; i < b.length; i++) { if ((i & 3) === 3) continue;
    if (ref < 0) ref = b[i]; else if (b[i] !== ref) return true; }
  return false;
}
async function blobData(bl: Blob): Promise<Uint8ClampedArray> {
  const bmp = await createImageBitmap(bl);
  const c = document.createElement("canvas"); c.width = bmp.width; c.height = bmp.height;
  const x = c.getContext("2d")!; x.drawImage(bmp, 0, 0);
  return x.getImageData(0, 0, bmp.width, bmp.height).data;
}
export async function checkCanvasPerturbation(): Promise<CanvasPerturbationResult> {
  const s = { getImageData:{perturbed:false,deterministic:false}, toDataURL:{perturbed:false,deterministic:false},
              offscreenBlob:{perturbed:false,deterministic:false}, webgl:{perturbed:false,deterministic:false} };
  try { const a = solidCtx().getImageData(0,0,CPX,CPX).data, b = solidCtx().getImageData(0,0,CPX,CPX).data;
        s.getImageData.perturbed = nonUniform(a); s.getImageData.deterministic = a.every((v,i)=>v===b[i]); } catch {}
  try { const u1 = solidCtx().canvas.toDataURL("image/png"), u2 = solidCtx().canvas.toDataURL("image/png");
        const im = new Image(); im.src = u1; await im.decode();
        const dc = document.createElement("canvas"); dc.width=CPX; dc.height=CPX;
        const dx = dc.getContext("2d")!; dx.drawImage(im,0,0);
        s.toDataURL.perturbed = nonUniform(dx.getImageData(0,0,CPX,CPX).data); s.toDataURL.deterministic = u1===u2; } catch {}
  try { const oc = new OffscreenCanvas(CPX,CPX); const ox = oc.getContext("2d")!;
        ox.fillStyle=`rgb(${FILL},${FILL},${FILL})`; ox.fillRect(0,0,CPX,CPX);
        const d1 = await blobData(await oc.convertToBlob({type:"image/png"}));
        const d2 = await blobData(await oc.convertToBlob({type:"image/png"}));
        s.offscreenBlob.perturbed = nonUniform(d1); s.offscreenBlob.deterministic = d1.every((v,i)=>v===d2[i]); } catch {}
  try { const gc = document.createElement("canvas"); gc.width=CPX; gc.height=CPX;
        const gl = gc.getContext("webgl")!; gl.clearColor(FILL/255,FILL/255,FILL/255,1); gl.clear(gl.COLOR_BUFFER_BIT);
        const p1 = new Uint8Array(CPX*CPX*4), p2 = new Uint8Array(CPX*CPX*4);
        gl.readPixels(0,0,CPX,CPX,gl.RGBA,gl.UNSIGNED_BYTE,p1); gl.readPixels(0,0,CPX,CPX,gl.RGBA,gl.UNSIGNED_BYTE,p2);
        s.webgl.perturbed = nonUniform(p1); s.webgl.deterministic = p1.every((v,i)=>v===p2[i]); } catch {}
  const seedPresent = !!(window as any).__canvasSeedSet__;
  const all = Object.values(s);
  const passed = seedPresent && all.every(x=>x.perturbed && x.deterministic);
  return { passed, surfaces: s, seedPresent, detail: passed ? "all 4 surfaces non-uniform + deterministic" : JSON.stringify({seedPresent, s}) };
}
```

- [ ] **Step 4: Wire** — import + run in `index.ts`; add `canvasPerturbation` to `TestResults` (`types.ts`).
- [ ] **Step 5: Build** — `cd build-tester && npm install && npm run build` → no TS errors.
- [ ] **Step 6: Commit** — `git commit -m "test(build-tester): quantization-robust canvas collector (non-uniformity, seed injected)"`

---

### Task 5: Positive WebRTC collector — REQUIRES the fabricated local value (exercises B1)

r3 fixes: (a) hard-require `exp.local` in the emitted candidates (the value only the B1 `GetLocalIPv4` branch produces) — an OR over {public,local} let the pre-existing public path pass without B1; (b) drive the public spoof via the **real** mechanism `setWebRTCIPv4(WEBRTC_TEST_IP=203.0.113.1)` (`GetIPv4` has no MaskConfig fallback, so the CAMOU_CONFIG `webrtc:ipv4` key is inert); (c) ensure a private candidate is actually gathered so the local branch fires — do NOT rely on the masked default candidate; (d) skip (not fail) when the profile has no expected-value injection, so `count_all_checks` (which counts this for every profile) doesn't false-negative the profiles that never configured it.

**Files:** Modify `build-tester/scripts/constants.py` (prefs), `build-tester/scripts/runner.py` (inject local key + expected values + expose to page for the test profile), `collectors.ts`, `index.ts`, `types.ts`

**Interfaces:** `checkWebRTCLinkLocal(): Promise<WebRTCLinkLocalResult>`, `WebRTCLinkLocalResult = { passed:boolean; skipped:boolean; candidates:string[]; expectedLocal:string; detail:string }`.

- [ ] **Step 1: Prefs** — in `constants.py` `FIREFOX_WEBGL_PREFS` add `"media.peerconnection.ice.obfuscate_host_addresses": False`. Caveat: `webrtc-ip-spoofing.patch` forces `default_address_only` when spoof is active, which restricts gathering to the single default-route candidate. To exercise the local branch you must make that default candidate an RFC1918 address (so `getMaskForIP`'s `isLocal` path runs) — confirm on the CI runner that the default route is private (containerized Linux runners are typically NAT'd/10.x); if not, the collector must `skipped=true` rather than fail.

- [ ] **Step 2: Inject for the test profile** — for the profile whose results the JSON dump targets, set the public spoof via the existing `setWebRTCIPv4` init path with `WEBRTC_TEST_IP` (`constants.py:20` = `203.0.113.1`), set `webrtc:localipv4=10.11.12.13` via CAMOU_CONFIG, and expose `window.__expectedWebRTC__ = {local:"10.11.12.13", public:"203.0.113.1"}`. Do not invent a second public value.

- [ ] **Step 3: Collector** (`collectors.ts`):
```typescript
import type { WebRTCLinkLocalResult } from "../types";
export async function checkWebRTCLinkLocal(): Promise<WebRTCLinkLocalResult> {
  const exp = (window as any).__expectedWebRTC__;
  const res: WebRTCLinkLocalResult = { passed:false, skipped:false, candidates:[], expectedLocal: exp?.local ?? "", detail:"" };
  if (!exp) { res.skipped = true; res.passed = true; res.detail = "skipped (no __expectedWebRTC__)"; return res; }
  try {
    if (typeof RTCPeerConnection === "undefined") { res.skipped = true; res.passed = true; res.detail = "no RTCPeerConnection"; return res; }
    const pc = new RTCPeerConnection({ iceServers: [{ urls: "stun:stun.l.google.com:19302" }] });
    const ips = new Set<string>();
    const done = new Promise<void>((r) => { const t = setTimeout(r, 6000);
      pc.onicecandidate = (e) => { if (!e.candidate) { clearTimeout(t); r(); return; }
        const m = e.candidate.candidate.match(/(?:\d{1,3}\.){3}\d{1,3}/); if (m) ips.add(m[0]);
        if (e.candidate.address) ips.add(e.candidate.address); }; });
    pc.createDataChannel("x"); await pc.setLocalDescription(await pc.createOffer()); await done; pc.close();
    res.candidates = Array.from(ips);
    const host = /^(?:127\.|10\.|192\.168\.|172\.(1[6-9]|2\d|3[01])\.|fe80:)/i;
    const localEmitted = res.candidates.includes(exp.local);          // ONLY the GetLocalIPv4 branch emits this
    const leakedHost = res.candidates.some((ip) => host.test(ip) && ip !== exp.local);
    res.passed = localEmitted && !leakedHost && res.candidates.length > 0;
    res.detail = res.passed ? `local spoof emitted (${res.candidates.join(",")})`
      : `FAIL localEmitted=${localEmitted} leakedHost=${leakedHost} cands=${res.candidates.join(",")}`;
  } catch (e:any) { res.detail = "webrtc check failed: " + e.message; }
  return res;
}
```

- [ ] **Step 4: Type + wire** — add `WebRTCLinkLocalResult` to `types.ts`, `webrtcLinkLocal` to `TestResults`, run in `index.ts`.
- [ ] **Step 5: Build** — `cd build-tester && npm run build` → no TS errors.
- [ ] **Step 6: Commit** — `git commit -m "test(build-tester): positive WebRTC collector requiring fabricated local IP (B1)"`

---

### Task 6: Prove the bug first — empirical current-state baseline

**Files:** Create `docs/superpowers/plans/p0-baseline.md`

- [ ] **Step 1: Read the last build's apply log** — `gh run view 28855741707 --repo lang315/camoufox --log | grep -iE "WebRTCIPManager|HTMLCanvasElement|can.?t find file|ignored|webrtc-ip-spoofing2|canvas-spoofing"`. Record which hunks were silently skipped (patch.py return-code blindness) — this resolves the "build succeeded yet the patch is broken" contradiction: skipped hunks mean the spoof was simply absent, not that the build broke.
- [ ] **Step 2: Baseline the current binary** — `cd build-tester && python scripts/run_tests.py <current-bin> --json /tmp/base.json`; read `canvasPerturbation`/`webrtcLinkLocal` at `r['profiles'][i]['results']`.
- [ ] **Step 3: Record + commit** `docs/superpowers/plans/p0-baseline.md` (expected: canvas surfaces inert / webrtc2 skipped → confirms the full reimplementation + B1 fix are needed).
```bash
git add docs/superpowers/plans/p0-baseline.md
git commit -m "docs(p0): empirical baseline of canvas/webrtc spoof state"
```

---

### Task 7: Reimplement canvas-spoofing.patch against real FF152 (NOT a re-anchor)

The four edit hunks are fabricated (see Revision note). This is a reimplementation: the added spoof code (the `CanvasSeedManager::Perturb(...)` calls + the seed accessor) is largely reusable, but every insertion point, buffer variable, and the offscreen seed-resolution must be rebuilt against real FF152. Anchor map (verified against `FIREFOX_152_0_4_RELEASE`):

| Surface | Real target (fetch + locate the function) | Note |
|---|---|---|
| getImageData | `dom/canvas/CanvasRenderingContext2D.cpp` → `GetImageDataArray` | buffer is `Span<uint8_t> aData` inside a lambda — perturb that span, not `data`/`length` |
| toDataURL / toBlob | **`dom/html/HTMLCanvasElement.cpp`** → `ExtractData` | patch currently targets `dom/canvas/…` = 404; fix the path |
| OffscreenCanvas.convertToBlob | `dom/canvas/CanvasRenderingContextHelper.cpp` → `ToBlob` (the shared encode) | real `OffscreenCanvas::ConvertToBlob` has no `snapshot`/`ExtractDataAsync`; perturb in the shared helper |
| WebGL readPixels | `dom/canvas/ClientWebGLContext.cpp` → `ReadPixels` | already real — keep as-is |
| seed resolution | replace fictional `OffscreenCanvas::GetDocument()` | use `GetOwnerGlobal()`/`GetRelevantGlobal()` → window → `GetExtantDoc()`, plus the existing `GetCurrentThreadWorkerPrivate()` worker path |

**Files:** Modify `patches/canvas-spoofing.patch` (rewrite the 4 edit hunks + the `GetCanvasSeed` body + the `HTMLCanvasElement` target path; the new-file `CanvasSeedManager.{cpp,h}` and `dom/base/moz.build` hunks stay).

- [ ] **Step 1: Fetch + study the real functions** — fetch the five files above from hg; read each target function to find the exact post-readback insertion point (where the client-visible pixel buffer is populated but before it is returned/encoded).
- [ ] **Step 2: Rewrite each edit hunk** against real context; fix the `HTMLCanvasElement.cpp` path to `dom/html/`; rewrite `GetCanvasSeed` to resolve the document via `GetOwnerGlobal()` (no `GetDocument()`); delete every `// (existing …)` / `<verify …>` placeholder; keep the `Perturb`/`GetNoiseDensity`/`GetNoiseStrength` calls.
- [ ] **Step 3: Gate** — `FETCH="curl -fsSL" bash scripts/rehearse-patch.sh canvas-spoofing.patch` → `rejects=0 skipped=0 wrongpath=0 fuzz=0 max|offset|<=2`, exit 0. `wrongpath=0` now proves the `dom/html/` path fix.
- [ ] **Step 4: Identifier check (pre-build, catches fabricated names)**:
```bash
T=.rehearse/canvas-spoofing.patch/tree
grep -n "CanvasSeedManager::Perturb" "$T"/dom/canvas/CanvasRenderingContext2D.cpp "$T"/dom/html/HTMLCanvasElement.cpp "$T"/dom/canvas/CanvasRenderingContextHelper.cpp "$T"/dom/canvas/ClientWebGLContext.cpp
grep -n "GetImageDataArray\|Span<uint8_t>" "$T"/dom/canvas/CanvasRenderingContext2D.cpp
grep -n "GetOwnerGlobal\|GetCurrentThreadWorkerPrivate" "$T"/dom/canvas/OffscreenCanvas.cpp
grep -n "CanvasSeedManager.cpp" "$T"/dom/base/moz.build
```
Expected: each `Perturb` inside its real function; no reference to `GetDocument`/`ExtractDataAsync`/`data`/`length` that doesn't exist in the fetched source. Full linkage proven by compile (Task 9).
- [ ] **Step 5: Commit** — `git commit -m "fix(patches): reimplement canvas-spoofing against real FF152 (4 surfaces + offscreen seed)"`

---

### Task 8: Re-anchor webrtc-ip-spoofing2.patch onto FF152

**Files:** Modify `patches/webrtc-ip-spoofing2.patch`

- [ ] **Step 1: Measure** — `FETCH="curl -fsSL" bash scripts/rehearse-patch.sh webrtc-ip-spoofing2.patch` (initially FAIL: the `#include` hunk carries a `<verify>` note).
- [ ] **Step 2: Re-anchor + delete placeholders** against fetched `PeerConnectionImpl.cpp`; confirm the retargeted `dom/base/WebRTCIPManager.{h,cpp}` hunks land on the class body created by `webrtc-ip-spoofing.patch`.
- [ ] **Step 3: Gate** — re-run until `rejects=0 skipped=0 wrongpath=0 fuzz=0 max|offset|<=2`, exit 0.
- [ ] **Step 4: Linkage grep**:
```bash
T=.rehearse/webrtc-ip-spoofing2.patch/tree
grep -n "GetLocalIPv4\|GetLocalIPv6" "$T"/dom/media/webrtc/jsapi/PeerConnectionImpl.cpp "$T"/dom/base/WebRTCIPManager.h
```
Expected: call site (PeerConnectionImpl) AND declaration (`dom/base/WebRTCIPManager.h`) both present.
- [ ] **Step 5: Commit** — `git commit -m "fix(patches): re-anchor webrtc-ip-spoofing2 onto FF152 (0 fuzz/skip/offset)"`

---

### Task 9: CI gate — build + prove end-to-end (both suites, correct JSON path)

**Files:** none (dispatch + evidence)

- [ ] **Step 1: Push + dispatch**
```bash
git push -u origin spec/spoofing-patch-hardening
gh workflow run "Build and Release" --repo lang315/camoufox -f build_target=linux-x86_64 --ref spec/spoofing-patch-hardening
```
- [ ] **Step 2: Confirm clean apply** — `gh run view <id> --repo lang315/camoufox --log | grep -iE "FAILED|\.rej|can.?t find file|ignored" || echo "clean apply"` → `clean apply` (grep only hard-fail tokens; `Hunk … succeeded … (offset N)` is production-valid).
- [ ] **Step 3: build-tester with correct JSON path** — the collectors live per-profile:
```bash
gh run download <id> --repo lang315/camoufox --name CamoufoxBuilds-linux-x86_64 -D /tmp/cf
cd build-tester && python scripts/run_tests.py /tmp/cf/<bin> --json /tmp/p0.json
python - <<'PY'
import json
r = json.load(open("/tmp/p0.json"))
prof = [p for p in r["profiles"] if "canvasPerturbation" in p.get("results", {})]
assert prof, "no profile ran the collectors"
res = prof[0]["results"]
assert res["canvasPerturbation"]["passed"], res["canvasPerturbation"]
wl = res["webrtcLinkLocal"]
assert wl["passed"] and not wl.get("skipped"), wl   # must be a real pass, not skipped
print("P0 ground-truth PASS")
PY
```
Expected: `P0 ground-truth PASS`. A build failure (undefined symbol) = a fabricated identifier survived — fix the reimplementation (Task 7) and re-dispatch; the compile is the semantic gate the rehearsal cannot provide.
- [ ] **Step 4: service-tester** — `cd service-tester && <documented run command>`; capture pass output.
- [ ] **Step 5: PR** — `gh pr create ... --body` with: rehearse-patch output (canvas + webrtc2 all-zero), CI clean-apply link, `/tmp/p0.json` excerpt (`canvasPerturbation.passed=true`, `webrtcLinkLocal.passed=true, skipped=false`), service-tester pass, baseline link. `Closes #N`.

---

## Self-Review

**Spec coverage (P0 slice):** B1 dir fix → Task 2; production-apply rehearsal (+skip+wrongpath+offset) → Task 1 (used 7/8); prove-bug-first → Task 6; canvas **reimplementation** against real FF152 → Task 7; webrtc2 re-anchor → Task 8; reachable+robust canvas collector (non-uniformity, seed injected) → Task 4; positive WebRTC collector requiring the fabricated local IP → Task 5; results graded + JSON at correct path → Tasks 3, 9; both suites + evidence PR + issue → Tasks 0, 9. P1–P4 excluded.

**Round-2 blockers fixed:** RB1 canvas re-scoped as reimplementation with the verified real anchor map (Task 7); RB2 WebRTC now hard-requires `exp.local` (Task 5 Step 3); RB3 public spoof via real `setWebRTCIPv4`/`203.0.113.1` mechanism (Task 5 Step 2); RB4 JSON dumped from `runner.py` as `full_result`, asserted at `r['profiles'][i]['results']` (Tasks 3, 9); RB5 collector `skipped=true` when unconfigured so per-profile grading can't false-negative (Task 5 Step 3); RB6 `canvas:seed` injected + `seedPresent` gate (Task 4); RB7 non-uniformity detection immune to `clearColor` quantization (Task 4 `nonUniform`); RB8 harness reports `wrongpath` for 404 targets (Task 1).

**Placeholder scan:** Task 7 reimplementation discovers hunk bytes against fetched source — objectively gated by rehearsal (0 reject/skip/wrongpath/fuzz/offset) + identifier grep + compile; the anchor map names the real functions so it is not a blind hunt. No `TBD`.

**Type consistency:** `CanvasPerturbationResult` (adds `seedPresent`), `WebRTCLinkLocalResult` (adds `skipped`) defined in Tasks 4/5 and consumed identically in Task 9's assertions + `grading.py` keys (`canvasPerturbation`,`webrtcLinkLocal`).

**Known limitations (P3/P4, not P0 gaps):** cross-surface RGBA-vs-BGRA seed coherence; cross-launch seed stability; worker (off-main-thread) perturbation; fe80 EUI-64 fabrication realism. P0 asserts per-surface firing + B1 local replacement only.

**Residual risk to flag at execution:** Task 5 depends on the CI runner's default route being RFC1918 so the B1 local branch fires; if it is public, the collector must `skipped=true` and B1's runtime proof falls back to a local run on a NAT'd host — do not weaken the `localEmitted` requirement to force green.
