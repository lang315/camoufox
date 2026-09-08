# Bringing `fix/44-fonts-h2` (PR #84) to a mergeable state — design

**Status:** approved in conversation on 2026-09-08; this document records the design.

## Context

`fix/44-fonts-h2` (tip `eacfb9f`, 77 commits over `55b4195`) gates four font read
paths per context (CSS `@font-face`, codepoint fallback, worker/OffscreenCanvas,
face-name lookup) and adds a large smoke-workflow regression guard (arms (a)–(j2)).
A merge-readiness review on 2026-09-08 (`.superpowers/sdd-sync-beta31/review-fix44.md`)
returned **Ready to merge: No** with four Critical findings:

- **C1** two `font-list-spoofing.patch` hunks (`GlobalFontFallback`, anchors
  `@@ -1468` / `@@ -1492`) collide with hunks main's beta.31 `font-hijacker.patch`
  now owns at the same anchors. Different patch files, so git reports no conflict;
  the reject only appears at `make dir`.
- **C2** the branch still writes `font.system.whitelist`
  (`Preferences::SetCString(kFontSystemWhitelistPref, …)`); main removed that hunk
  via upstream `70a22d8` (daijro/camoufox#695, chrome tofu on Windows/macOS). This
  is the one conflict git does report.
- **C3** `CamouIsFontAllowed`'s launch-level fallback duplicates
  `MaskConfig::IsFontAllowed` without main's chrome exemption, at provider-less
  call sites — on beta.31 it re-creates #695 by a second route.
- **C4** arm (h) is `UNEXPECTED RED` and absent from `EXPECTED_RED`, so the `#44`
  smoke step aborts and takes the four steps below it with it.

Main moved from beta.29 to beta.31 (`3782198`, PR #86) while this branch was
being bisected, so every run id in PR #84 is a beta.29 measurement and none of it
transfers.

## Scope

Mergeable means: the scope PR #84 already declares (arms (e)/(f)/(g)/(i) plus the
guard), rebased in substance onto beta.31, with both required test suites run and
a PR body whose every claim is read back from state. Plan Tasks 7–9 stay out.

Assumptions accepted by the user: no other session commits to `fix/44-fonts-h2`
or this checkout from now on; service-tester runs against the proxy the user
supplied on 2026-09-08 (gitignored `service-tester/proxies.txt`).

## Integration: merge, not rebase

Merge `3782198` into `fix/44-fonts-h2` with a real merge commit. A rebase would
force-push PR #84's head, which this project does not do on a shared branch
without an explicit request; a merge keeps #84 and its history, and lets C1, C2
and C3 land together, which the review says they must (the tree does not build
with only some of them).

## Design

### A. Merge and conflict resolution

- `upstream.sh`: `release=beta.31`.
- `patches/font-hijacker.patch`: **delete** fix/44's hunk `@@ -313,6 +314,16 @@`
  (the `kFontSystemWhitelistPref` write) — a deliberate delete-ours recorded in
  the merge commit message (C2). Keep main's five new `gfxPlatformFontList.cpp`
  hunks, its `gfxPlatformFontList.h` and `gfxUserFontSet.cpp` hunks unchanged.
  `FontFace.cpp` and `FontFaceImpl.cpp`: take fix/44's versions
  (`CamouFontListContextId` + `AutoFontListContext`, `GetFamilyName()`).
  `FontFaceImpl.h`: fix/44's per-context branch first, then
  `return MaskConfig::IsFontAllowed(...)` as on main — no inlined copy of the
  launch-level list.
- `.github/workflows/smoke.yml` merges cleanly; verify the `#57` sweep step and
  the `#44` guard step both survive, do not rewrite.
- `CLAUDE.md`: keep the branch's six lessons (superset of main's three).

### B. Patches on the beta.31 tree (C1, C3)

1. Run `make dir` (`CAMOU_PATCH=/opt/homebrew/bin/gpatch`) immediately after the
   merge and expect it to go **red** on exactly the two `GlobalFontFallback` hunks.
   That red is the C1 proof; record the `.rej` names.
2. `make workspace ./patches/font-list-spoofing.patch`, re-derive the two hunks
   against the tree that already carries `font-hijacker.patch`, placing the
   per-context check **after** `MaskedFontListBlocks` so main's chrome exemption
   answers first. Write the workspace back to the patch.
3. `CamouIsFontAllowed` answers only the per-context question:
   context has a list → `FontListManager::IsFontAllowed(ctx, key)`; otherwise
   `return true`. The launch-level question belongs to
   `MaskedFontListBlocks` / `MaskConfig::IsFontAllowed` at the provider-carrying
   sites. Remove the duplicated static launch list.
4. Recount `-start` for every drifted `gfxPlatformFontList.cpp` hunk.
5. Gates, in this order: `python3 .superpowers/sdd-sync-beta31/check_hunks3.py`
   on both patches; `gpatch -p1 --forward -l --binary --dry-run` after
   `font-hijacker.patch` is applied; `scripts/rehearse-patch.sh`;
   `make dir` with `0 FAILED` in the log.

### C. Bisect cleanup

Smoke run `34193143221` measures attempt 4 (`eacfb9f`). If it reads as the commit
predicted (Geneva GREEN, arm (h) RED), the whole bisect series (attempt 0 through
attempt 4, commits `32fa884`…`eacfb9f`) is reverted in `font-list-spoofing.patch`
to the pre-bisect state of `ca29ceb`: no cell turned any arm red→green, and the
plan's own rule is that a gate whose probe was never red proves nothing. Any other
result stops the work and goes back to the user.

### D. Arm (h): one diagnostic build, then decide

Add a temporary, never-merged log at the `src: local()` resolution path
(`font-list-spoofing.patch:271` region, `LookupLocalFont` / face-name lookup)
printing `FontListManager::GetCurrentContext()`, `HasFontList(ctx)` and the key.
Build linux from the merged branch, run the smoke workflow, read the log.

- `ctx == 0` at that site → CLAUDE.md lesson 5 fail-open. Fix: establish an
  `AutoFontListContext` at the `gfxUserFontSet` local-face resolution site from
  the provider available there. The fix ships in the final candidate build (E);
  expected reading: (h) GREEN, Geneva GREEN.
- `ctx != 0` → scope (h) out: open an issue that records the measurement
  (375.7 / 448.4 / 507.5 widths, four runs, the bisect table, the Geneva pixel
  result) and states the mechanism is **not established**; add
  `EXPECTED_RED["(h)"]` worded as undiagnosed; state the residual exposure in
  the PR body (closed in the launch-`fonts` shape by main's `gfxUserFontSet`
  guard, open in the bare-launch / per-context-only shape).

Budget: one diagnostic build. The fix, if any, rides the final build.

### E. Final verification

- Dispatch linux-x86_64 and macos-arm64 builds from the candidate in parallel.
- Smoke on the linux build: read every arm (a)–(j2) from the log; the `#44` step
  must pass with only `EXPECTED_RED` arms red, and the `#57` step must still pass.
- Locally on the macOS binary: `build-tester` headful (`DISPLAY=:0`,
  `playwright==1.55.0`, recreated `build-tester/.venv`) compared against main's
  beta.31 baseline 1061/1070 (PR #86); `service-tester` with the supplied proxy.
- A whole-branch code review before merge.

### F. Record

- Rewrite PR #84's body: correct the three false claims ("Tasks 5–9 not in this
  PR", "`IsFontAllowed` byte-identical", "four hunks at fuzz 0"); every number a
  beta.31 run id; a NOT-verified section for anything not run; the (h) outcome;
  and the note that the plan's Task 8 flip (stop writing `font.system.whitelist`)
  landed on main through upstream `70a22d8`, not through this plan's gate — the
  plan's "BLOCKED on #83 / no flip without a native-Windows arm" is now a
  plan-vs-reality contradiction and cannot be un-flipped.
- File a main-side issue for the native-Windows arm (plan Task 7) that the
  already-landed flip still lacks.

### G. Process

Subagent-driven development in this checkout — the branch is checked out here so
no worktree is possible — with sequential implementers, a review after each task,
a ledger at `.superpowers/sdd-44/progress.md`, and a final whole-branch review.
Plan: `docs/superpowers/plans/2026-09-08-44-fonts-h2-merge.md`.

## Success criteria

1. `git merge-base --is-ancestor 3782198 fix/44-fonts-h2` is true; `upstream.sh`
   says beta.31; `make dir` applies all patches with `0 FAILED`.
2. `grep -c kFontSystemWhitelistPref patches/font-hijacker.patch` is 0 (the
   constant appears only in upstream code the patch no longer touches) and
   `CamouIsFontAllowed` has no launch-level list.
3. Smoke on the candidate's linux build: `#44` step green with only
   `EXPECTED_RED` arms red; `#57` step green.
4. build-tester Grade A, no check regressed against 1061/1070; service-tester
   scored (not 0/0) against the supplied proxy.
5. PR #84 body read back from state, with run ids, and a NOT-verified section.

## Out of scope

Plan Tasks 7–9 (native-Windows arm, the flip, pythonlib docs); #82 and #83
themselves; any change to `build-tester` or `service-tester` harnesses.
