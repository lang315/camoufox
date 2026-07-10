# P0 Task 7 — verified FF152 canvas anchor map (supersedes the fabricated hunks)

Status: research complete (real FF152.0.4 source studied via hg). Writing the final hunks +
**compile-verifying** them requires the build environment — this document turns Task 7 from
"reimplement, discover anchors" into "insert perturbation at these exact verified points."

## Why the current `canvas-spoofing.patch` is fabricated (confirmed against real source)

- `dom/canvas/HTMLCanvasElement.cpp` hunk → **404**; the file is at `dom/html/HTMLCanvasElement.cpp`. But it should not be patched at all (see below).
- `OffscreenCanvas::GetDocument()` in the `GetCanvasSeed` hunk → **does not exist** in FF152.
- `OffscreenCanvas::ConvertToBlob` has no `snapshot`/`GetDataSurface`/`ExtractDataAsync` shape — the real encode goes through `CanvasRenderingContextHelper::ToBlob` → `GetImageBuffer`.
- `GetImageData` uses `data`/`length` locals that don't exist — the real buffer is a JS array from `JS_GetUint8ClampedArrayData`.

## The FF152 pixel-read topology (verified)

All canvas readback for the 2D context funnels through **two** functions in
`dom/canvas/CanvasRenderingContext2D.cpp`, and `OffscreenCanvasRenderingContext2D` **inherits**
`CanvasRenderingContext2D`, so patching the base class covers BOTH main-thread and worker/offscreen
2D contexts — no separate `OffscreenCanvas`/`HTMLCanvasElement` hunks needed.

1. **`getImageData`** → `CanvasRenderingContext2D::GetImageDataArray`. The JS-visible buffer is:
   ```cpp
   uint8_t* data = JS_GetUint8ClampedArrayData(darray, &isShared, nogc);
   ...
   uint8_t* dst = data + dstWriteRect.y * (aWidth * 4) + dstWriteRect.x * 4;   // pixels written here
   ```
   Format R8G8B8A8, length `aWidth * aHeight * 4`. **Insert perturbation on `data` after the pixel
   copy completes, before the function returns** (skip the `ImageExtraction::Placeholder` early-break path).

2. **`toDataURL` / `toBlob` / `OffscreenCanvas.convertToBlob`** → all encode via
   `CanvasRenderingContextHelper::ToBlob`/`ToDataURL` → `GetImageBuffer(...)`, which for the 2D
   context is `CanvasRenderingContext2D::GetImageBuffer`:
   ```cpp
   RefPtr<SourceSurface> snapshot = mBufferProvider->BorrowSnapshot();
   if (snapshot) {
     RefPtr<DataSourceSurface> data = snapshot->GetDataSurface();
     if (data && data->GetSize() == GetSize()) {
       *out_format = imgIEncoder::INPUT_FORMAT_HOSTARGB;
       *out_imageSize = data->GetSize();
       ret = SurfaceToPackedBGRA(data);        // ret = UniquePtr<uint8_t[]>, BGRA packed
     }
   }
   mBufferProvider->ReturnSnapshot(snapshot.forget());
   if (ret) { /* PotentiallyDumpImage ...; */ return ret; }
   ```
   Format packed BGRA, length `out_imageSize->width * out_imageSize->height * 4`. **Insert
   perturbation on `ret.get()` right after `ret = SurfaceToPackedBGRA(data)` (or just before
   `return ret`).** This ONE point covers toDataURL + toBlob + convertToBlob for html AND offscreen.

3. **WebGL `readPixels`** → `ClientWebGLContext::ReadPixels` — the current patch hunk here uses
   real identifiers (`range->data()`, `range->size_bytes()`, `GetOwnerDoc()`); **keep it as-is**,
   only re-anchor context if the rehearsal shows drift.

## Net change vs the fabricated patch

- **Remove** the `dom/canvas/HTMLCanvasElement.cpp` hunk (wrong path; unnecessary — encode is in the helper/GetImageBuffer).
- **Remove** the `OffscreenCanvas.cpp` `GetCanvasSeed`/`ConvertToBlob` hunks (fictional; base-class coverage + WebGL path suffice).
- **Rewrite** two hunks into `CanvasRenderingContext2D.cpp`: one in `GetImageDataArray` (RGBA `data`), one in `GetImageBuffer` (BGRA `ret`).
- **Keep** the new files `CanvasSeedManager.{cpp,h}` and the `dom/base/moz.build` registration, and the `ClientWebGLContext::ReadPixels` hunk.

## Seed resolution (replaces the fictional `OffscreenCanvas::GetDocument`)

`CanvasRenderingContext2D` already exposes its owner: for the html case `mCanvasElement->OwnerDoc()`,
for offscreen/worker via `GetParentObject()`/the worker global. Resolve the userContextId there and
call the existing `CanvasSeedManager::SeedFromDocument(doc)` (or a new `SeedFromContext(this)` helper
on `CanvasRenderingContext2D` that handles both). The reusable spoof API from the current patch is
unchanged:
```cpp
CanvasSeedManager::Perturb(buf, len, seed,
    CanvasSeedManager::GetNoiseDensity(), CanvasSeedManager::GetNoiseStrength());  // no-op when seed==0
```
Both insertion points guard with `if (seed != 0)`.

## Execution (build env)

1. Fetch the two files from hg (`dom/canvas/CanvasRenderingContext2D.cpp`, `dom/canvas/ClientWebGLContext.cpp`); the helper/OffscreenCanvas/HTMLCanvasElement files are only needed for reference, not patched.
2. Write the two `CanvasRenderingContext2D.cpp` hunks + the `SeedFromContext` glue at the real anchors above.
3. Rehearsal gate: `scripts/rehearse-patch.sh canvas-spoofing.patch` → `rc=0 rejects=0 skipped=0 wrongpath=0 fuzz=0 max|offset|<=2`.
4. **Compile** (`make build`) — the semantic gate the rehearsal cannot provide; fix any type/linkage error against real signatures.
5. build-tester `checkCanvasPerturbation` (Task 4) must go green: all surfaces non-uniform + deterministic (offscreen now covered via the shared GetImageBuffer path).

## Coverage note vs Task 4 collector

Task 4's collector probes `offscreenBlob` via `OffscreenCanvas.convertToBlob` — which routes through
`GetImageBuffer` (covered here). `getImageData`/`toDataURL`/`webgl` all map to the anchors above.
So all four collector surfaces become reachable once these two hunks land — no P3-deferred worker
gap for the *encode* path (true off-main-thread worker `getImageData` remains P3).

## DONE (2026-07-09) — patch re-anchored against real FF152, applies clean

`patches/canvas-spoofing.patch` fully rewritten from the real FF152.0.4 source (fetched via
`curl hg.mozilla.org`, the earlier "no hg access" assumption was stale). What changed vs the
fabricated draft:

- **Dropped every all-zero `index 000..00N` line on the edit hunks** (the F3 silent-skip defect —
  same bug as webrtc2; gpatch read them as "create → already exists → Skipping"). New-file hunks
  keep `--- /dev/null` + `new file mode 100644` (correct creation form).
- **Fixed the malformed creation `@@` counts** — the draft's `CanvasSeedManager.cpp`/`.h` headers
  claimed `+1,168`/`+1,72` over 162/66-line bodies (masked because the whole hunk was being
  skipped). Regenerated from the real bodies via `diff -u`.
- **Removed** the `dom/canvas/HTMLCanvasElement.cpp` hunk (path is 404 in FF152 — real file is
  `dom/html/`) and both `dom/canvas/OffscreenCanvas.cpp` hunks (`GetDocument()`/`GetCanvasSeed()`
  are fictional). `OffscreenCanvasRenderingContext2D` inherits `CanvasRenderingContext2D`, so the
  base-class `GetImageBuffer`/`GetImageDataArray` anchors cover offscreen 2D encode + readback.
- **Rewrote the two 2D hunks at verified anchors:** `GetImageBuffer` after
  `ret = SurfaceToPackedBGRA(data)` (BGRA, `w*h*4`); `GetImageDataArray` inside the
  `do{}while(false)` after the Swizzle/Unpremultiply into `data` (RGBA, `len.value()`), where the
  `Placeholder` early-break naturally excludes the placeholder path.
- **Seed resolution** mirrors real in-file patterns (no fictional `OffscreenCanvas::GetDocument`):
  `mCanvasElement->OwnerDoc()` (html, cf. line 1298) else
  `mOffscreenCanvas->GetOwnerWindow()->GetExtantDoc()` (offscreen main-thread, cf. line 5389) →
  `CanvasSeedManager::SeedFromDocument` (0-safe; worker → null → no-op = P3).
- **Anchored the `setCanvasSeed` WebIDL setter on vanilla-stable symbols**
  (`nsGlobalWindowInner::StoreSharedWorker` decl+def, Window.webidl EOF) rather than the draft's
  `SetFontSpacingSeed` neighbour — so the *setter* hunks carry no cross-patch coupling.
- **Kept** the `ClientWebGLContext::ReadPixels` hunk, re-anchored to the real FF152 context (after
  the `RandomizeElements`/`hasAlphaChannel` block, non-Placeholder branch).

## Anchoring target = the POST-PREREQ tree, not vanilla

The patch is generated against the tree `make dir` actually presents to `canvas-spoofing.patch`:
vanilla FF152 with the three earlier patches that touch these files applied first
(`0-playwright.patch`, `anti-font-fingerprinting.patch`, `audio-fingerprint-manager.patch`).
This matters for the two `#include` hunks: `anti-font` inserts `#include "FontSpacingSeedManager.h"`
immediately after `nsIDOMStorageManager.h`, and a prereq inserts `#include "mozilla/dom/BrowsingContext.h"`
immediately after `mozilla/dom/Document.h` — i.e. right at the include anchors. A vanilla-generated
diff there rejects in `make dir` (the trailing context no longer matches). Generating against the
post-prereq tree makes every hunk match exactly. (A first pass anchored on vanilla passed a vanilla
dry-run but the make-dir-faithful rehearsal caught both include hunks rejecting — the reason this
step is gated by `rehearse-patch.sh`, which applies the prereqs, and not by a bare vanilla apply.)

**Evidence — `scripts/rehearse-patch.sh canvas-spoofing.patch` (fetches FF152 + applies the 3
prereqs, then the target):**
`rc=0 rejects=0 skipped=0 wrongpath=0 fuzz=0 max|offset|=0` — the strict gate, fully green.

**Still build-env only:** `make build` compile-verify (semantic gate — real signatures) and
build-tester `checkCanvasPerturbation` green on a fresh binary (Task 9). No further re-anchoring
needed.
