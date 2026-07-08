# P0 Task 6 — prove-bug-first baseline

Date: 2026-07-08. Method: logical inference from the last successful build (run 28855741707,
`build (macos, arm64)` = success, 26 steps) — the CI make-dir log was not retrievable
(`gh run view --log` returned empty), but the conclusion is airtight without it.

## Conclusion: the canvas + webrtc2 local-IP spoofs are INERT in the shipped binary

`scripts/patch.py` gates only on `.rej` files and ignores the `patch` process return code
(`patch.py:137-148`). A hunk whose target file is missing, or whose context cannot be located,
is silently skipped (no `.rej`) → make-dir reports clean.

The fabricated `canvas-spoofing.patch` edit hunks reference identifiers that do not exist at their
targets in FF152:
- `dom/canvas/HTMLCanvasElement.cpp` → the path is **404** (real file is `dom/html/`), so that hunk
  cannot apply at all.
- the `GetImageData` hunk references `data`/`length` locals absent from the real function;
- the `OffscreenCanvas` hunk calls `OffscreenCanvas::GetDocument()`, which does not exist.

If any of these had **applied**, the added `CanvasSeedManager::Perturb(...)` / `GetDocument()` calls
would reference undefined symbols → **compile failure**. The build compiled and succeeded →
therefore those hunks did **not** apply — they were silently skipped. Same reasoning applies to the
pre-fix `webrtc-ip-spoofing2.patch` `WebRTCIPManager` hunks (targeted the nonexistent
`dom/media/webrtc/jsapi/` path → skipped → the local-IP spoof never landed; this is the B1 bug,
fixed in commit fdb060e).

**Net:** the last shipped binary is "green" but its canvas perturbation and webrtc2 local-IP
replacement never ran. This is exactly the silent-inert failure P0 exists to eliminate, and it
confirms the full scope is required:
- Task 2 (B1 dir fix) — DONE.
- Task 7 (reimplement canvas at the real anchors — see `p0-task7-ff152-anchors.md`) — build env.
- Task 8 (re-anchor webrtc2 + drop the all-zero `index` lines) — build env.
- Task 9 (build + build-tester `canvasPerturbation`/`webrtcLinkLocal` + service-tester) — build env.

## Empirical confirmation step (build env)

Once Task 7/8 land, a fresh CI build's make-dir log must show `canvas-spoofing.patch` and
`webrtc-ip-spoofing2.patch` applying with **no** "can't find file" / "Hunk ignored" lines (use
`scripts/rehearse-patch.sh` first to guarantee this before burning the build), and build-tester must
report `canvasPerturbation.passed=true` + `webrtcLinkLocal.passed=true`.
