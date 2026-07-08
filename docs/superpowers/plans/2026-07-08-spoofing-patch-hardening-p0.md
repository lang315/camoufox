# Spoofing-patch hardening — P0 (correctness gate) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix the confirmed B1 directory bug in `webrtc-ip-spoofing2.patch`, re-anchor the two draft spoofing patches onto real FF152.0.4 so they apply at the correct location, and prove — with reachable, falsifiable, positively-graded build-tester checks — that the canvas and WebRTC (incl. B1 local-IP replacement) spoofs actually fire in the built binary.

**Architecture:** Validation models the real production apply (sibling patches first, production flags, reject+fuzz+offset). Two new build-tester collectors are wired into `grading.py` so their pass/fail counts toward the exit code, and `run_tests.py` gains `--json` so their booleans are observable. The canvas collector probes only patched paths (known-answer solid fill, per surface); the WebRTC collector is a *positive* known-answer test (asserts emitted values equal the fabricated per-userContext addresses — the only runtime exercise of the B1 fix). P0 ships as its own PR(s); P1–P4 get separate plans.

**Tech Stack:** Firefox source patches (unified diff, GNU `patch`/`gpatch`), Python 3.11+ / `scripts/patch.py`, hg raw-file fetch, TypeScript (build-tester), GitHub Actions.

## Global Constraints

- Firefox pinned: `version=152.0.4`, `release=beta.25` (`upstream.sh`). Fetch from `https://hg.mozilla.org/releases/mozilla-release/raw-file/FIREFOX_152_0_4_RELEASE/<path>`.
- Production patch command any verification MUST mirror: `patch -p1 --forward -l --binary`, GNU maxfuzz 2 (`scripts/patch.py:129-130`). On macOS use `gpatch` (BSD `patch` mis-parses fuzz/offset). **`patch.py` gates only on `.rej` files and ignores the process return code (`patch.py:137-148`)** — a hunk whose target file is missing is silently skipped with no `.rej`; this is how B1 hid. Any rehearsal must therefore also check exit status.
- Apply order = `sorted(list_files, key=os.path.basename)` (`scripts/_mixin.py:78`) — pure basename sort (no roverfox special-case for the current patch set).
- Tooling floor: harness needs **bash ≥ 4** (uses `mapfile`, `declare -A`, `globstar`) and `gpatch`; state this in the README and fail fast if unmet.
- Every PR: tied to a GitHub issue (create it in Task 0); **both** `build-tester/` and `service-tester/` pass; PR body carries concrete evidence (command output + exit status), never prose-only.
- Surgical: `git add` exact files, never a whole directory; keep the `Makefile` diff clean.
- Egress: the sandbox bash allowlist excludes `hg.mozilla.org`. Fetch runs on a host/runner with open egress (`curl -fsSL`) or via a context-mode tool outside bash — never assume `curl` works in the sandbox.

---

### Task 0: Tracking issue + gitignore hygiene

**Files:**
- Modify: `.gitignore`

- [ ] **Step 1: Open the tracking issue**

Run: `gh issue create --repo lang315/camoufox --title "P0: fix + re-anchor canvas/webrtc spoofing patches (FF152)" --body "Correctness gate — B1 dir fix, re-anchor draft patches, ground-truth build-tester collectors. Spec: docs/superpowers/specs/2026-07-08-spoofing-patch-hardening-design.md"`
Record the issue number `N`; every P0 PR closes `#N`.

- [ ] **Step 2: Ignore rehearsal litter**

Add to `.gitignore`:
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

### Task 1: Patch-rehearsal harness (portable, exit-status-aware)

**Files:**
- Create: `scripts/rehearse-patch.sh`
- Create: `scripts/rehearse-patch.README.md`

**Interfaces:**
- Produces: `scripts/rehearse-patch.sh <patch-basename>` → exits 0 iff `rejects==0 AND all target hunks applied (no skip) AND fuzz==0 AND max|offset|<=2`; prints a per-hunk table; leaves the applied tree at `.rehearse/<patch>/tree`. Requires env `FETCH` = a fetch command (`FETCH="curl -fsSL"` on an egress host). Consumed by Tasks 6, 7, 8.

- [ ] **Step 1: Write the harness**

Create `scripts/rehearse-patch.sh`:

```bash
#!/usr/bin/env bash
# Rehearse ONE patch against a realistically-sequenced FF152 tree.
# Usage: FETCH="curl -fsSL" scripts/rehearse-patch.sh <patch-basename>
set -euo pipefail
shopt -s globstar

command -v gpatch >/dev/null || { echo "need gpatch"; exit 3; }
[ "${BASH_VERSINFO:-0}" -ge 4 ] || { echo "need bash>=4"; exit 3; }
: "${FETCH:?set FETCH, e.g. FETCH='curl -fsSL'}"

PATCH="${1:?usage: rehearse-patch.sh <patch-basename>}"
ROOT="$(git rev-parse --show-toplevel)"; PDIR="$ROOT/patches"
WORK="$ROOT/.rehearse/$PATCH"; TREE="$WORK/tree"
HG="https://hg.mozilla.org/releases/mozilla-release/raw-file/FIREFOX_152_0_4_RELEASE"
PB="${CAMOU_PATCH:-gpatch}"

pf() { local n="$1"; [ -f "$PDIR/$n" ] && echo "$PDIR/$n" || find "$PDIR" -name "$n" | head -1; }
# edited (a/ -> b/, non /dev/null) vs created (--- /dev/null) target files of a patch
edited() { awk '/^--- \/dev\/null/{skip=1;next} /^\+\+\+ b\//{if(!skip)print substr($0,7);skip=0}' "$1"; }
created() { awk '/^--- \/dev\/null/{g=1;next} /^\+\+\+ b\//{if(g)print substr($0,7);g=0}' "$1"; }

mapfile -t TARGET_EDIT < <(edited "$PDIR/$PATCH")
mapfile -t TARGET_NEW  < <(created "$PDIR/$PATCH")

# prereqs = earlier-in-basename-order patches that EDIT a file $PATCH also edits
mapfile -t ORDER < <(ls "$PDIR"/**/*.patch | xargs -n1 basename | sort -u)
PREREQS=()
for p in "${ORDER[@]}"; do
  [ "$p" = "$PATCH" ] && break
  ppath="$(pf "$p")"
  for tf in "${TARGET_EDIT[@]}"; do
    if edited "$ppath" | grep -qxF "$tf"; then PREREQS+=("$ppath"); break; fi
  done
done

rm -rf "$WORK"; mkdir -p "$TREE"
# Fetch every EDITED file (target + prereqs). NEVER fetch created files — patch makes them.
declare -A SEEN
for src in "${PREREQS[@]}" "$PDIR/$PATCH"; do
  while read -r f; do
    [ -z "$f" ] && continue; [ -n "${SEEN[$f]:-}" ] && continue; SEEN[$f]=1
    for nf in "${TARGET_NEW[@]}"; do [ "$f" = "$nf" ] && continue 2; done
    mkdir -p "$TREE/$(dirname "$f")"
    $FETCH "$HG/$f" -o "$TREE/$f" || { echo "FETCH FAIL $f"; exit 4; }
  done < <(edited "$src")
done

cd "$TREE"
for p in "${PREREQS[@]}"; do "$PB" -p1 --forward -l --binary -i "$p" >/dev/null 2>&1 || true; done

OUT="$WORK/apply.out"
set +e; "$PB" -p1 --forward -l --binary -i "$PDIR/$PATCH" >"$OUT" 2>&1; RC=$?; set -e

REJ=$(find "$TREE" -name '*.rej' | wc -l | tr -d ' ')
SKIP=$(grep -ciE 'can.?t find file|ignored|Skipping' "$OUT" || true)
FUZZ=$(grep -oE 'with fuzz [0-9]+' "$OUT" | grep -oE '[0-9]+' | sort -rn | head -1); FUZZ=${FUZZ:-0}
OFF=$(grep -oE 'offset -?[0-9]+' "$OUT" | grep -oE -- '-?[0-9]+' | tr -d - | sort -rn | head -1); OFF=${OFF:-0}
echo "=== $PATCH: rc=$RC rejects=$REJ skipped=$SKIP fuzz=$FUZZ max|offset|=$OFF ==="
grep -E 'Hunk|FAILED|ignored|offset|fuzz|find file' "$OUT" || true
[ "$REJ" = 0 ] && [ "$SKIP" = 0 ] && [ "$FUZZ" = 0 ] && [ "$OFF" -le 2 ]
```

- [ ] **Step 2: Write the README** — purpose (models production apply, not pristine per-file), the gate (`rejects==0 AND skipped==0 AND fuzz==0 AND max|offset|<=2`), why `skipped` matters (patch.py ignores return code, so a missing-target hunk vanishes silently — the B1 failure mode), why offset matters (fuzz==0 ≠ correct location), and the `FETCH`/bash4/gpatch requirements.

- [ ] **Step 3: Smoke-test on an already-clean patch**

Run: `FETCH="curl -fsSL" bash scripts/rehearse-patch.sh css-media-spoofing.patch`
Expected: `rc=0 rejects=0 skipped=0 fuzz=0 max|offset|=0`, exit 0 (rebased to FF152 in 26d60e7 → must be clean; non-zero ⇒ harness bug).

- [ ] **Step 4: Commit**

```bash
git add scripts/rehearse-patch.sh scripts/rehearse-patch.README.md
git commit -m "test(patches): production-apply rehearsal harness (reject/skip/fuzz/offset gate)"
```

---

### Task 2: Fix B1 — retarget webrtc2's WebRTCIPManager hunks to dom/base/

The class is created at `dom/base/WebRTCIPManager.{h,cpp}` by `webrtc-ip-spoofing.patch:5,157`, but `webrtc-ip-spoofing2.patch:121,139` edits `dom/media/webrtc/jsapi/WebRTCIPManager.{h,cpp}`. Retarget.

**Files:**
- Modify: `patches/webrtc-ip-spoofing2.patch`

- [ ] **Step 1: Retarget the .h hunk** — replace `dom/media/webrtc/jsapi/WebRTCIPManager.h` → `dom/base/WebRTCIPManager.h` in that hunk's `diff --git`, `---`, `+++` lines.

- [ ] **Step 2: Retarget the .cpp hunk** — same for `WebRTCIPManager.cpp`.

- [ ] **Step 3: Verify header-only edit**

Run: `git diff patches/webrtc-ip-spoofing2.patch`
Expected: only the six path lines changed; every `@@`/context/`+`/`-` line untouched.

- [ ] **Step 4: Commit**

```bash
git add patches/webrtc-ip-spoofing2.patch
git commit -m "fix(patches): retarget webrtc2 WebRTCIPManager hunks to dom/base (B1)"
```

---

### Task 3: Grade + expose the new collectors (unblocks assertions)

`build-tester/scripts/grading.py:count_all_checks` is hardcoded per result key; new collectors won't count toward pass/total or the exit code, and nothing prints their booleans. Wire them in and add `--json`.

**Files:**
- Modify: `build-tester/scripts/grading.py:36-68`
- Modify: `build-tester/scripts/run_tests.py`

**Interfaces:**
- Consumes: result keys `canvasPerturbation`, `webrtcLinkLocal` (Tasks 4/5). Produces: `run_tests.py --json <path>` dumps the raw `results` dict; both collectors counted in `count_all_checks`.

- [ ] **Step 1: Count the collectors in count_all_checks**

In `grading.py`, after the WebRTC block (line 47), add:

```python
    # Canvas perturbation (P0 ground-truth)
    total_checks += 1
    if results.get("canvasPerturbation", {}).get("passed"):
        pass_count += 1

    # WebRTC link-local (P0 ground-truth)
    total_checks += 1
    if results.get("webrtcLinkLocal", {}).get("passed"):
        pass_count += 1
```

- [ ] **Step 2: Add --json to run_tests.py**

Find where the `results` dict is obtained from the page: `grep -n "results\b\|argparse\|add_argument\|__testResults__" build-tester/scripts/run_tests.py`. Add an arg and dump:

```python
    parser.add_argument("--json", help="write raw results dict to this path")
    # ... after `results` is populated:
    if args.json:
        import json
        with open(args.json, "w") as fh:
            json.dump(results, fh, indent=2)
        print(f"wrote raw results to {args.json}")
```

- [ ] **Step 3: Typecheck-free smoke (Python import)**

Run: `cd build-tester && python -c "import scripts.grading"`
Expected: no error.

- [ ] **Step 4: Commit**

```bash
git add build-tester/scripts/grading.py build-tester/scripts/run_tests.py
git commit -m "test(build-tester): grade canvasPerturbation + webrtcLinkLocal, add --json dump"
```

---

### Task 4: Known-answer canvas collector (patched paths only, reachable)

Proves perturbation *fired* per surface (unpatched → exact fill value → red). Probes only paths `canvas-spoofing.patch` covers: `getImageData` (2D w/ canvas element), `toDataURL` (PNG, lossless), OffscreenCanvas via **`convertToBlob`** (the patched offscreen path — NOT offscreen `getImageData`, which is unpatched and a P3 item), WebGL `readPixels`. No cross-surface *equality* claim in P0 — RGBA-vs-BGRA seed divergence is a known P3 limitation.

**Files:**
- Modify: `build-tester/src/lib/checks/collectors.ts`
- Modify: `build-tester/src/lib/checks/index.ts`
- Modify: `build-tester/src/lib/types.ts`

**Interfaces:**
- Produces: `checkCanvasPerturbation(): Promise<CanvasPerturbationResult>`, `CanvasPerturbationResult = { passed: boolean; surfaces: Record<"getImageData"|"toDataURL"|"offscreenBlob"|"webgl", {perturbed:boolean; deterministic:boolean}>; detail: string }`.

- [ ] **Step 1: Type** — in `types.ts`:

```typescript
export interface CanvasPerturbationResult {
  passed: boolean;
  surfaces: Record<"getImageData" | "toDataURL" | "offscreenBlob" | "webgl",
    { perturbed: boolean; deterministic: boolean }>;
  detail: string;
}
```

- [ ] **Step 2: Collector** — append to `collectors.ts` (256×256 so E[perturbed]≈98 at density 5e-4 → zero-perturbation false-fail ≈ e⁻⁹⁸ ≈ 0):

```typescript
import type { CanvasPerturbationResult } from "../types";

const CPX = 256, FILL = 128;
function solidCtx(): CanvasRenderingContext2D {
  const c = document.createElement("canvas"); c.width = CPX; c.height = CPX;
  const x = c.getContext("2d", { willReadFrequently: true })!;
  x.fillStyle = `rgb(${FILL},${FILL},${FILL})`; x.fillRect(0, 0, CPX, CPX);
  return x;
}
function devi(b: Uint8ClampedArray | Uint8Array): boolean {
  for (let i = 0; i < b.length; i++) { if ((i & 3) === 3) continue; if (b[i] !== FILL) return true; }
  return false;
}
async function blobToData(blob: Blob): Promise<Uint8ClampedArray> {
  const bmp = await createImageBitmap(blob);
  const c = document.createElement("canvas"); c.width = bmp.width; c.height = bmp.height;
  const x = c.getContext("2d")!; x.drawImage(bmp, 0, 0);
  return x.getImageData(0, 0, bmp.width, bmp.height).data;
}

export async function checkCanvasPerturbation(): Promise<CanvasPerturbationResult> {
  const s: CanvasPerturbationResult["surfaces"] = {
    getImageData: { perturbed: false, deterministic: false },
    toDataURL: { perturbed: false, deterministic: false },
    offscreenBlob: { perturbed: false, deterministic: false },
    webgl: { perturbed: false, deterministic: false },
  };
  try {
    const a = solidCtx().getImageData(0, 0, CPX, CPX).data;
    const b = solidCtx().getImageData(0, 0, CPX, CPX).data;
    s.getImageData.perturbed = devi(a);
    s.getImageData.deterministic = a.every((v, i) => v === b[i]);
  } catch {}
  try {
    const u1 = solidCtx().canvas.toDataURL("image/png");
    const u2 = solidCtx().canvas.toDataURL("image/png");
    const img = new Image(); img.src = u1; await img.decode();
    const dc = document.createElement("canvas"); dc.width = CPX; dc.height = CPX;
    const dx = dc.getContext("2d")!; dx.drawImage(img, 0, 0);
    s.toDataURL.perturbed = devi(dx.getImageData(0, 0, CPX, CPX).data);
    s.toDataURL.deterministic = u1 === u2;
  } catch {}
  try {
    const oc = new OffscreenCanvas(CPX, CPX);
    const ox = oc.getContext("2d")!;
    ox.fillStyle = `rgb(${FILL},${FILL},${FILL})`; ox.fillRect(0, 0, CPX, CPX);
    const d1 = await blobToData(await oc.convertToBlob({ type: "image/png" }));
    const d2 = await blobToData(await oc.convertToBlob({ type: "image/png" }));
    s.offscreenBlob.perturbed = devi(d1);
    s.offscreenBlob.deterministic = d1.every((v, i) => v === d2[i]);
  } catch {}
  try {
    const gc = document.createElement("canvas"); gc.width = CPX; gc.height = CPX;
    const gl = gc.getContext("webgl")!;
    gl.clearColor(FILL / 255, FILL / 255, FILL / 255, 1); gl.clear(gl.COLOR_BUFFER_BIT);
    const p1 = new Uint8Array(CPX * CPX * 4), p2 = new Uint8Array(CPX * CPX * 4);
    gl.readPixels(0, 0, CPX, CPX, gl.RGBA, gl.UNSIGNED_BYTE, p1);
    gl.readPixels(0, 0, CPX, CPX, gl.RGBA, gl.UNSIGNED_BYTE, p2);
    s.webgl.perturbed = devi(p1);
    s.webgl.deterministic = p1.every((v, i) => v === p2[i]);
  } catch {}
  const all = Object.values(s);
  const passed = all.every((x) => x.perturbed && x.deterministic);
  return { passed, surfaces: s,
    detail: passed ? "all 4 patched surfaces perturbed + deterministic"
      : JSON.stringify(s) };
}
```

- [ ] **Step 3: Wire in** — in `index.ts` import `checkCanvasPerturbation`, run it as a phase, add `canvasPerturbation` to the returned object; add the field to `TestResults` in `types.ts`.

- [ ] **Step 4: Build** — `cd build-tester && npm install && npm run build` → no TS errors.

- [ ] **Step 5: Commit**

```bash
git add build-tester/src/lib/checks/collectors.ts build-tester/src/lib/checks/index.ts build-tester/src/lib/types.ts
git commit -m "test(build-tester): reachable known-answer canvas collector (256px, patched paths)"
```

---

### Task 5: Positive known-answer WebRTC collector (exercises the B1 fix)

The old `checkWebRTC` is IPv4-only; a naive fe80 check passes on zero candidates and on RFC-7217 (no `ff:fe`) hosts. This sets spoof config and asserts the *emitted* candidates equal the *fabricated* per-context values — the only runtime test of the B1-fixed `GetLocalIPv4/v6` path.

**Files:**
- Modify: `build-tester/scripts/constants.py:22` (prefs) — set `media.peerconnection.ice.obfuscate_host_addresses=False`
- Modify: `build-tester/scripts/runner.py` — inject `webrtc:localipv4/localipv6` + a public `webrtc:ipv4/ipv6` into `CAMOU_CONFIG` for this test (find the existing `CAMOU_CONFIG`/`generate_context_fingerprint` injection at `runner.py:288`)
- Modify: `build-tester/src/lib/checks/collectors.ts`, `index.ts`, `types.ts`

**Interfaces:**
- Produces: `checkWebRTCLinkLocal(): Promise<WebRTCLinkLocalResult>`, `WebRTCLinkLocalResult = { passed: boolean; candidates: string[]; expectedLocal: string; detail: string }`. The expected fabricated local IP is passed to the page (e.g. via a `<meta>` or `window.__expectedLocalIP__` the runner injects from the same value it put in `CAMOU_CONFIG`).

- [ ] **Step 1: Prefs** — in `constants.py` `FIREFOX_WEBGL_PREFS` add:
```python
    "media.peerconnection.ice.obfuscate_host_addresses": False,
```
Caveat to document: `webrtc-ip-spoofing.patch:692` forces `default_address_only` when spoof is active, which suppresses host candidate gathering. So the positive test must assert on the **masked default candidate** (public `webrtc:ipv4/ipv6`) — not rely on host fe80 gathering. Set the spoof so the emitted default candidate is the known public value; assert it equals that value and never the host IP.

- [ ] **Step 2: Inject the known config + expected value** — at `runner.py:288`, extend the `CAMOU_CONFIG` for this test with `webrtc:ipv4=203.0.113.7`, `webrtc:localipv4=10.11.12.13`, and expose `10.11.12.13` / `203.0.113.7` to the page as `window.__expectedWebRTC__ = {local:"10.11.12.13", public:"203.0.113.7"}` via an init script.

- [ ] **Step 3: Collector** — append to `collectors.ts`:

```typescript
import type { WebRTCLinkLocalResult } from "../types";

export async function checkWebRTCLinkLocal(): Promise<WebRTCLinkLocalResult> {
  const exp = (window as any).__expectedWebRTC__ || { local: "", public: "" };
  const res: WebRTCLinkLocalResult = { passed: false, candidates: [], expectedLocal: exp.local, detail: "" };
  try {
    if (typeof RTCPeerConnection === "undefined") return { ...res, detail: "no RTCPeerConnection" };
    const pc = new RTCPeerConnection({ iceServers: [{ urls: "stun:stun.l.google.com:19302" }] });
    const ips = new Set<string>();
    const done = new Promise<void>((r) => {
      const t = setTimeout(r, 6000);
      pc.onicecandidate = (e) => {
        if (!e.candidate) { clearTimeout(t); r(); return; }
        const m = e.candidate.candidate.match(/(?:\d{1,3}\.){3}\d{1,3}|[0-9a-f:]{2,}/i);
        if (m) ips.add(m[0]);
        if (e.candidate.address) ips.add(e.candidate.address);
      };
    });
    pc.createDataChannel("x");
    await pc.setLocalDescription(await pc.createOffer());
    await done; pc.close();
    res.candidates = Array.from(ips);
    // Positive assertion: emitted candidates carry ONLY the spoofed values, never a host IP.
    const host = /(?:^127\.)|(?:^10\.)|(?:^192\.168\.)|(?:^172\.(1[6-9]|2\d|3[01])\.)|(?:^fe80:)/i;
    const emittedSpoofed = res.candidates.some((ip) => ip === exp.public || ip === exp.local);
    const leakedHost = res.candidates.some((ip) => host.test(ip) && ip !== exp.local);
    res.passed = emittedSpoofed && !leakedHost && res.candidates.length > 0;
    res.detail = res.passed
      ? `spoofed candidates emitted (${res.candidates.join(",")})`
      : `FAIL emittedSpoofed=${emittedSpoofed} leakedHost=${leakedHost} cands=${res.candidates.join(",")}`;
  } catch (e: any) { res.detail = "webrtc link-local check failed: " + e.message; }
  return res;
}
```

- [ ] **Step 4: Type + wire** — add `WebRTCLinkLocalResult` to `types.ts`, `webrtcLinkLocal` to `TestResults`, run in `index.ts`.

- [ ] **Step 5: Build** — `cd build-tester && npm run build` → no TS errors.

- [ ] **Step 6: Commit**

```bash
git add build-tester/scripts/constants.py build-tester/scripts/runner.py build-tester/src/lib/checks/collectors.ts build-tester/src/lib/checks/index.ts build-tester/src/lib/types.ts
git commit -m "test(build-tester): positive known-answer WebRTC collector (exercises B1 local-IP)"
```

---

### Task 6: Prove the bug first — empirical current-state baseline

Determine what actually ships today, and whether `make dir` silently skipped webrtc2's mis-targeted hunks.

**Files:**
- Create: `docs/superpowers/plans/p0-baseline.md`

- [ ] **Step 1: Inspect the last successful build's apply log** — download the `make dir` log of run 28855741707 (or dispatch a fresh Linux build of current `main`): `gh run view <id> --repo lang315/camoufox --log | grep -iE "WebRTCIPManager|can.?t find file|ignored|webrtc-ip-spoofing2"`. Record whether webrtc2's `WebRTCIPManager` hunks were skipped (patch.py's return-code blindness) — this resolves the "build succeeded yet B1 is a bug" contradiction: a silent skip means the local-IP spoof was simply absent, not that the build broke.

- [ ] **Step 2: Run the new collectors against the current binary** — `cd build-tester && python scripts/run_tests.py <current-bin> --json /tmp/base.json`; read `canvasPerturbation`, `webrtcLinkLocal` from `/tmp/base.json`.

- [ ] **Step 3: Record branch decision** — write `docs/superpowers/plans/p0-baseline.md`:
  - Per canvas surface already-perturbed → its re-anchor (Task 7) is a placeholder-cleanup only; verify the re-anchored call lands at the **same effective site** (don't regress a working fuzz-placed spoof).
  - webrtc2 skipped/inert → full B1 fix + re-anchor needed (expected).
  Commit:

```bash
git add docs/superpowers/plans/p0-baseline.md
git commit -m "docs(p0): empirical baseline of canvas/webrtc spoof state + webrtc2 apply status"
```

---

### Task 7: Re-anchor canvas-spoofing.patch onto FF152 (+ identifier check)

**Files:**
- Modify: `patches/canvas-spoofing.patch`

- [ ] **Step 1: Measure** — `FETCH="curl -fsSL" bash scripts/rehearse-patch.sh canvas-spoofing.patch`. Expected initially: FAIL (fake context in the 4 `.cpp` edit hunks).

- [ ] **Step 2: Re-anchor + delete placeholders** — for `GetImageData`, `ExtractData`, `OffscreenCanvas::ConvertToBlob`, `ClientWebGLContext::ReadPixels`, rewrite each hunk's context to the real fetched source; delete every `// (existing …)` / `// <verify …>` line; keep `+` lines byte-for-byte.

- [ ] **Step 3: Gate** — re-run Step 1 until `rejects=0 skipped=0 fuzz=0 max|offset|<=2`, exit 0.

- [ ] **Step 4: Identifier + registration check (pre-build, catches PB6)** — the added blocks reference source-local names (`data`,`length` in GetImageData; `snapshot`,`OwnerDoc()`,`map.GetData()` in ExtractData). Verify each referenced identifier exists in the fetched function body, and the new source is registered:
```bash
T=.rehearse/canvas-spoofing.patch/tree
grep -n "CanvasSeedManager::Perturb" "$T"/dom/canvas/*.cpp
grep -n "GetImageData\|GetOwnerDocument\|GetDataSurface" "$T"/dom/canvas/CanvasRenderingContext2D.cpp "$T"/dom/canvas/HTMLCanvasElement.cpp
grep -n "CanvasSeedManager.cpp" "$T"/dom/base/moz.build
grep -n "RoverfoxStorageManager\|FontSpacingSeedManager" "$T"/dom/base/*.h 2>/dev/null || echo "note: linkage confirmed only at compile (Task 9)"
```
Expected: every `Perturb` call sits inside its target function; referenced identifiers present; `CanvasSeedManager.cpp` registered. Remaining linkage (Roverfox/FontSpacing signatures) is proven by the compile in Task 9.

- [ ] **Step 5: Commit**

```bash
git add patches/canvas-spoofing.patch
git commit -m "fix(patches): re-anchor canvas-spoofing onto FF152 (0 fuzz/skip/offset, identifiers verified)"
```

---

### Task 8: Re-anchor webrtc-ip-spoofing2.patch onto FF152

**Files:**
- Modify: `patches/webrtc-ip-spoofing2.patch`

- [ ] **Step 1: Measure** — `FETCH="curl -fsSL" bash scripts/rehearse-patch.sh webrtc-ip-spoofing2.patch`. Expected initially: FAIL (the `#include` hunk carries a `<verify>` note).

- [ ] **Step 2: Re-anchor + delete placeholders** against the fetched `PeerConnectionImpl.cpp`; confirm the retargeted `dom/base/WebRTCIPManager.{h,cpp}` hunks land on the class body created by `webrtc-ip-spoofing.patch`.

- [ ] **Step 3: Gate** — re-run until `rejects=0 skipped=0 fuzz=0 max|offset|<=2`, exit 0.

- [ ] **Step 4: Symbol-linkage grep**
```bash
T=.rehearse/webrtc-ip-spoofing2.patch/tree
grep -n "GetLocalIPv4\|GetLocalIPv6" "$T"/dom/media/webrtc/jsapi/PeerConnectionImpl.cpp "$T"/dom/base/WebRTCIPManager.h
```
Expected: call site (PeerConnectionImpl) AND declaration (`dom/base/WebRTCIPManager.h`) both present.

- [ ] **Step 5: Commit**

```bash
git add patches/webrtc-ip-spoofing2.patch
git commit -m "fix(patches): re-anchor webrtc-ip-spoofing2 onto FF152 (0 fuzz/skip/offset, linkage verified)"
```

---

### Task 9: CI gate — build + prove end-to-end (both suites, JSON evidence)

**Files:** none (dispatch + evidence)

- [ ] **Step 1: Push + dispatch Linux build**

```bash
git push -u origin spec/spoofing-patch-hardening
gh workflow run "Build and Release" --repo lang315/camoufox -f build_target=linux-x86_64 --ref spec/spoofing-patch-hardening
```

- [ ] **Step 2: Confirm clean production apply** — poll the run; the real `make dir` is authoritative (sibling patches shift context):
```bash
gh run view <id> --repo lang315/camoufox --log | grep -iE "FAILED|\.rej|can.?t find file|ignored" || echo "clean apply"
```
Expected: `clean apply`. (Grep only hard-failure tokens — `Hunk … succeeded … (offset N)` is a production-valid apply, not a failure.)

- [ ] **Step 3: build-tester with JSON assertions**

```bash
gh run download <id> --repo lang315/camoufox --name CamoufoxBuilds-linux-x86_64 -D /tmp/cf
cd build-tester && python scripts/run_tests.py /tmp/cf/<bin> --json /tmp/p0.json
python -c "import json; r=json.load(open('/tmp/p0.json')); assert r['canvasPerturbation']['passed'], r['canvasPerturbation']; assert r['webrtcLinkLocal']['passed'], r['webrtcLinkLocal']; print('P0 ground-truth PASS')"
```
Expected: `P0 ground-truth PASS`. If the build itself fails (undefined symbol = PB6/linkage), fix the re-anchor and re-dispatch — the compile is the semantic gate the rehearsal cannot provide.

- [ ] **Step 4: service-tester** — `cd service-tester && <documented run command>`; capture pass output.

- [ ] **Step 5: PR with evidence**

```bash
gh pr create --repo lang315/camoufox --base main --head spec/spoofing-patch-hardening \
  --title "P0: fix + re-anchor canvas/webrtc spoofing patches (FF152)" \
  --body "$(cat <<'BODY'
Closes #N.

## What
- B1: retarget webrtc2 WebRTCIPManager hunks dom/media/webrtc/jsapi -> dom/base.
- Re-anchor canvas-spoofing + webrtc-ip-spoofing2 onto FF152 (0 reject/skip/fuzz/offset, identifiers+linkage verified).
- Reachable known-answer canvas collector (patched paths); positive known-answer WebRTC collector (exercises B1 local-IP); both graded + JSON-dumped.

## Evidence
- rehearse-patch.sh: canvas + webrtc2 => rc=0 rejects=0 skipped=0 fuzz=0 max|offset|<=2 [paste]
- make dir on CI: clean apply [link]
- build-tester JSON: canvasPerturbation.passed=true, webrtcLinkLocal.passed=true [paste /tmp/p0.json excerpt]
- service-tester: pass [paste]
- baseline (pre-fix) vs post-fix: [link p0-baseline.md]
BODY
)"
```

---

## Self-Review

**Spec coverage (P0 slice of spec r2):** B1 dir fix → Task 2; production-apply rehearsal w/ skip+offset → Task 1 (+ used 7/8); prove-bug-first + patch.py return-code blindness → Task 6; re-anchor 4 canvas + webrtc2 hunks → 7/8; dependency-by-linkage → Task 7.4 (identifiers pre-build) + Task 9 (compile); ground-truth canvas (reachable, patched paths) → Task 4; positive fe80/local-IP collector → Task 5; structural grep → 7.4/8.4; results graded+observable → Task 3; both suites + evidence PR + issue → Tasks 0, 9. P1–P4 excluded (own plans).

**Blockers fixed vs r1:** PB1 offscreen via `convertToBlob` (reachable) + 256px (Task 4); PB2/PB5 positive known-answer WebRTC exercising B1 (Task 5); PB3 gpatch default + `FETCH` env + bash4 guard + no-fetch-of-created-files (Task 1); PB4 grading + `--json` (Task 3); PB6 identifier pre-build check + compile-is-semantic-gate (Task 7.4, 9.3); PB7 empirical baseline + return-code note (Task 6); MED: grep only hard-fail tokens (Task 9.2), no cross-surface-equality claim (Task 4), pref via dict not user.js (Task 5.1), `.gitignore`+issue (Task 0).

**Placeholder scan:** re-anchor tasks (7/8) discover anchor bytes against fetched source — objectively gated (rehearsal + identifier grep), not a TODO. Task 3.2 / 5.2 name a `grep` to locate the exact injection line (bounded, not open-ended). No `TBD`/"handle edge cases".

**Type consistency:** `CanvasPerturbationResult` (surfaces incl. `offscreenBlob`), `WebRTCLinkLocalResult` (`candidates`,`expectedLocal`) defined in Tasks 4/5 Step 1 and consumed identically in Task 9's JSON assertions and grading.py keys (`canvasPerturbation`,`webrtcLinkLocal`). Harness gate string identical across Tasks 1/7/8.

**Known limitation recorded (not a P0 gap):** RGBA-vs-BGRA cross-surface seed divergence and offscreen-`getImageData`/worker perturbation are P3; P0 asserts per-surface firing only.
