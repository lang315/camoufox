# P0 Task 8 — webrtc-ip-spoofing2 root cause (why B1 is inert) + fix recipe

Investigated with real FF152 source (bash `curl` reaches `hg.mozilla.org` — the earlier
"allowlist excludes hg" note was stale) + `gpatch` locally + the rehearsal harness.

## Root cause: the ENTIRE webrtc2 patch is a silent no-op

`webrtc-ip-spoofing2.patch` carries an all-zero pre-image git `index` line on **every** hunk's
file header:
```
diff --git a/dom/media/webrtc/jsapi/PeerConnectionImpl.cpp ...
index 0000000000..0000000001 100644      <-- all-zero old hash
--- a/dom/media/webrtc/jsapi/PeerConnectionImpl.cpp
```
GNU `patch`/`gpatch` reads an all-zero old hash as **"this hunk creates the file."** All three
targets (`PeerConnectionImpl.cpp`, `dom/base/WebRTCIPManager.{h,cpp}`) already exist (real FF152 /
created by `webrtc-ip-spoofing.patch`), so gpatch prints **"would create the file … which already
exists! Skipping patch"** and skips — with **no `.rej`**. `scripts/patch.py` gates only on `.rej`
and ignores the return code, so `make dir` reports clean while **none of webrtc2 applies**.

Empirically confirmed (isolated gpatch test): all-zero index on an edit hunk over an existing file →
"already exists, skipping"; drop the index line → "patching file …". This is exactly why the
runtime build-tester showed **B1 local-IP inert** (`10.11.12.13` never emitted) — and it also means
the fe80 link-local masking + the `isSpecialIP` change never took effect either.

## Three defect classes (all verified)

1. **All-zero `index` lines (F3)** on all 3 file headers → every hunk skipped. **Fix:** delete the
   `index 0000000000..…` lines. Verified: flips gpatch skip → apply.
2. **Malformed `@@` counts** (hand-written, never exercised because the hunks always skipped).
   Recomputed from the actual bodies:
   - `-500,12 +500,32` → `-500,8 +500,36`  (isSpecialIP)
   - `-534,18 +554,38` → `-534,19 +554,38`  (getMaskForIP)
   - `-25,6 +25,12`   → `-25,6 +25,13`    (WebRTCIPManager.h)
   - `-90,6 +90,46`   → `-90,3 +90,52`    (WebRTCIPManager.cpp)
   **Fix:** recount (drop-index + recount script in the session history). Verified: eliminates
   "malformed patch" errors.
3. **Fabricated context in 2 hunks** (must be re-anchored to real source):
   - the `#include` hunk keeps two `// <verify exact line — include block …>` placeholder lines as
     *context* → never matches real `PeerConnectionImpl.cpp`. Delete them; anchor `+#include
     "mozilla/HashFunctions.h"` to the real include block.
   - the `WebRTCIPManager.h` hunk's context is `GetIPv6` then `SetIPv6` then a blank then
     `IsFunctionEnabledForWebIDL`, but `webrtc-ip-spoofing.patch` actually creates the header
     **Set-before-Get with Doxygen comment blocks** and `GetIPv6` followed by blank lines then a
     `/** … */` block. Re-anchor the GetLocalIPv4/v6 insert after the real `GetIPv6` declaration.

## Why the last mile needs the build env

Re-anchoring defect (3) faithfully needs the **pre-webrtc2 tree** = real FF152 + the full patch
stack applied in order (what `make dir` produces). The rehearsal harness only applies the
file-sharing prereqs, so `webrtc-ip-spoofing.patch`'s include-block + moz.build edits partially
reject in the reconstructed tree → webrtc2's anchors (webrtc1's additions) are missing there. A
faithful reconstruction is essentially `make dir`, which the 14 GB-free sandbox can't run. So:
- defects (1) + (2) are mechanical and done/verified here;
- defect (3) must be re-anchored against a real `make dir` tree (or a full-stack reconstruction on
  a build host), then gated by `scripts/rehearse-patch.sh` (rejects==0, skipped==0, wrongpath==0)
  and confirmed by build-tester `webrtcLinkLocal.passed=true` on a fresh build.

## Do NOT commit a partial fix

Committing (1)+(2) without (3) flips webrtc2 from **silent skip** (build green, spoof inert) to a
**hard reject at make-dir** (build broken). Left as-is until (3) lands with it, so the build stays
green. The reverted patch is unchanged on the branch.

## Harness improvements landed this task (verified)
- Treat files a prereq **creates** (`/dev/null`) as never-fetch / never-wrongpath — so a patch that
  edits a prereq-created file (webrtc2 edits `WebRTCIPManager.*`) isn't falsely flagged wrongpath.
- Clear `.rej` after the best-effort prereq applies, before applying the target, so the reject count
  reflects only the target patch (not partial-prereq pollution like `dom/base/moz.build.rej`).
