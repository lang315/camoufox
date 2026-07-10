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

## Runtime validation (2026-07-09) — real macOS-arm64 binary

Ran `build-tester` (8 profiles) against `CamoufoxBuilds-macos-arm64` (run 28953374857,
HEAD 084d0cb). Overall grade A, 1041/1064. New-collector results:

- **canvasPerturbation: passed=false on ALL 8 profiles** — `seedPresent=true` but every surface
  (getImageData/toDataURL/offscreenBlob/webgl) `perturbed=false, deterministic=true`. The canvas
  seed IS injected, yet readback is uniform → **the canvas spoof is inert at runtime**, empirically
  confirming Task 6 (the fabricated hunks are skipped; no Perturb call runs). The Task 4 collector
  is validated: it correctly detects the inert state and the seed presence.
- **webrtcLinkLocal:**
  - per-context profiles: `skipped=true` (no `__expectedWebRTC__` injected there) — the RB5
    skip-when-unconfigured fix works (no false negative).
  - **global profiles: passed=false.** Candidates = the spoofed public IPv4 `203.0.113.1` (so the
    pre-existing public-IP mask WORKS) **plus a real global IPv6 (host's actual address)**, and the
    B1 fabricated local `10.11.12.13` is **absent** (`localEmitted=false`). So **B1's local-IP
    replacement is still inert** — the retarget (Task 2) alone did not make webrtc2 effective; Task 8
    must confirm the patch actually applies (F3 all-zero `index` "already exists → skipping") and that
    `webrtc:localipv4` is wired.

### New actionable findings (feed the handoff)
- **Task 8:** B1 local-IP spoof does not fire at runtime → verify webrtc2 actually applies (drop the
  all-zero `index` lines) and that a private candidate is gathered so `getMaskForIP`'s isLocal branch runs.
- **P2 / collector gap:** a real global IPv6 leaks over WebRTC and the `checkWebRTCLinkLocal`
  `leakedHost` regex (IPv4-private + fe80 only) does NOT flag it. Extend the collector to fail on any
  candidate that is neither the spoofed public nor local value; and the spoofing itself must mask
  global IPv6 (currently only IPv4 public + fe80 are handled).
