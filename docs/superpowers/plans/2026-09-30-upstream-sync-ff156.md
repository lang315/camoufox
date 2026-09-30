# Upstream sync to Firefox 156 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Merge upstream `daijro/camoufox` `2f30fea` into fork `main` (`c6e0ae9`), porting the fork's patch stack from Firefox 152.0.4 (beta.31) to 156.0.1 (beta.32) so every patch applies with zero rejects and the fork's spoofing guards still pass.

**Architecture:** One merge commit takes upstream's version of every conflicted patch file and resolves the non-patch files textually. The fork's deltas are then re-derived on a Firefox 156 tree, one patch per commit, in `scripts/patch.py` order (basename sort), and each patch is regenerated from that tree. Nothing is hand-edited inside a `.patch`. After that come a GNU-patch dry run of the full stack, local gates, a Linux build, patch guards and build-tester, and a PR merged as a merge commit.

**Tech Stack:** GNU patch (`gpatch` on macOS), git, `make setup` / `scripts/patch.py`, `gh` with `--repo lang315/camoufox`, pytest, `go test`.

**Spec:** No separate design doc. The decisions below were taken with the user on 2026-09-30 from three recon reports (font patches, other patches, non-patch files).

## Global Constraints

- Every `gh` call takes `--repo lang315/camoufox`. Never push to `main`. Merge the PR without `--auto`, only after the checks are green, as a **merge commit** (not squash).
- Never hand-edit a `.patch`. Edit the source tree, then regenerate with `git add -A && git diff --cached <base>`, because plain `git diff` drops new files.
- Dry-run with `gpatch -p1 --forward -l --binary --dry-run`. `git apply --check` and BSD `patch` are not valid pre-flights.
- Keep hunk context balanced (same leading and trailing context) in anything written by hand.
- Decisions (fixed):
  - D1 WebRTC: **keep the fork model** (per-context `WebRTCIPManager`, `webrtc-ip-spoofing2.patch`). Do not take upstream's srflx fabrication.
  - D2 font-spacing seed: **take upstream's removal** of `setFontSpacingSeed` / `FontSpacingSeedManager`, and delete every fork user.
  - D3 timezone: **take upstream's** per-realm `timezone-spoofing.patch`. Drop the fork's `SetNewDocument` / global `JS::SetTimeZoneOverride` hunk.
  - D4 `GlobalFontFallback`: **take upstream's** platform fallback, and add `CamouIsFontAllowed(key)` to `fallbackBlocked` so per-context lists still gate.
- Makefile: take upstream's version. The fork's net Makefile delta is zero.
- `release.yml` must not run on the fork: guard it before the branch can reach `main`.

## Paths and variables used by every task

```bash
WT=/Users/lang/GolandProjects/github.com/lang315/camoufox/.claude/worktrees/sync+upstream-2f30fea
SRC=$WT/camoufox-156.0.1-beta.32        # created by Task 2; gitignored
MB=5e59b70                               # merge-base
FORK=c6e0ae9                             # fork main before the sync
UP=2f30fea                               # upstream main
mkdir -p $WT/.ci-work/bin && ln -sf /opt/homebrew/bin/gpatch $WT/.ci-work/bin/patch
export PATH=$WT/.ci-work/bin:$PATH       # GNU patch for scripts/patch.py and make targets
```

"Tree at position N" (the #131 procedure, **not** `make workspace`):

```bash
at_position() {   # $1 = basename of the patch to edit
  cd $SRC && git reset -q --hard unpatched && git clean -fdq
  for p in $(cd $WT && python3 -c "import sys;sys.path.insert(0,'scripts');from _mixin import list_patches;print('\n'.join(list_patches('patches')))"); do
    [ "$(basename $p)" = "$1" ] && break
    patch -p1 --forward -l --binary -s -i $WT/$p || { echo "FAILED at $p"; return 1; }
  done
  git add -A && git commit -qm "stack before $1" && git tag -f base-$1
}
regen() {         # $1 = repo path of the patch, e.g. patches/foo.patch
  cd $SRC && git add -A && git diff --cached base-$(basename $1) > $WT/$1
}
```

---

### Task 0: Issue

- [ ] **Step 1:** Open the tracking issue.

```bash
gh issue create --repo lang315/camoufox --title "Sync fork main with upstream daijro/camoufox 2f30fea (Firefox 156.0.1)" \
  --body "Upstream is 21 commits ahead (Firefox 152.0.4 -> 156.0.1, #779, #787, #785, #789, #806, #808, #810). A dry-run merge conflicts in 33 files, 16 of them patches. Plan: docs/superpowers/plans/2026-09-30-upstream-sync-ff156.md on branch sync/upstream-2f30fea. Decisions: keep fork WebRTC model; drop font-spacing seed; take upstream timezone; upstream GlobalFontFallback plus per-context gate."
```

Record the issue number as `$ISSUE`.

### Task 1: The merge commit (non-patch resolutions and workflow safety)

**Files:** the 17 non-patch conflicts, the 16 patch conflicts (taken from upstream), `.github/workflows/release.yml`, `scripts/copy-additions.sh`, `upstream.sh`.

- [ ] **Step 1:** `cd $WT && git merge --no-ff --no-commit upstream/main`. Expect conflicts.
- [ ] **Step 2: Patch files.** Take upstream's version now; Tasks 3 to 5 port the fork's deltas.

```bash
git checkout --theirs -- patches/anti-font-fingerprinting.patch patches/browser-init.patch patches/chromeutil.patch \
  patches/cross-process-storage.patch patches/font-hijacker.patch patches/font-list-spoofing.patch \
  patches/navigator-spoofing.patch patches/network-patches.patch patches/playwright/0-playwright.patch \
  patches/screen-spoofing.patch patches/speech-voices-spoofing.patch patches/timezone-spoofing.patch \
  patches/webgl-spoofing.patch patches/window-setter-seal.patch patches/windows-theming-bug-modified.patch
git checkout --ours -- patches/webrtc-ip-spoofing.patch      # D1
git add patches/
```

- [ ] **Step 3: Deletions accepted.**

```bash
git rm -q additions/camoucfg/MouseTrajectories.hpp pythonlib/camoufox/webgl/sample.py settings/camoucfg.jvv
```

- [ ] **Step 4: Non-patch files.** Resolve each file as the table says, then `git add` it.

| File | Resolution |
|---|---|
| `.github/workflows/build.yml` | Keep the fork's copy (`git checkout --ours`, `git add`). It is the fork's only dispatchable build; `e2e.yml` and `smoke.yml` consume its artifacts. |
| `.github/workflows/tests.yml` | Take upstream, then union the `needs:` / `required=` lists with the fork's `e2e`, keep the fork's `e2e` job and `setup-go`, and **restore `push: branches: [main]`**. |
| `.github/workflows/release.yml` (clean merge, new) | Add `if: github.repository == 'daijro/camoufox'` to every job that has no `needs:` (the roots: `tests`, `plan`, and any other). |
| `CLAUDE.md` | Line 1 `@AGENTS.md`, then the fork-only sections: build dispatch, the patch-context rule, Testing additions, "Verifying spoofing claims" lessons 1-9, and "Constraints when editing this repo". Remove every mention of `make edits`, `developer.py`, `legacy/`, `jsonvv/` and `camoucfg.jvv`. Tag FF152 line numbers as beta.31 where they are not already. |
| `ci/README.md`, `ci/tests/test_ci.py` | Take upstream, then add the fork's `e2e` entry. |
| `native-tests/test_contexts_vs_browsers.py` | Upstream's `test_two_browsers_get_different_fingerprints`, plus the fork's `CANVAS_HASH`, `_launch_probe` and `test_two_browsers_on_one_preset_still_differ`. |
| `pythonlib/camoufox/async_api.py`, `sync_api.py` | Take upstream, then re-apply the fork's Xvfb-leak `try/except` (#363) inside upstream's `_launch`. Check `git diff $MB $FORK -- <f>` for `_resolve_proxy_geo` and `determine_ua_os`, and re-add anything upstream dropped that the fork added. |
| `pythonlib/camoufox/fingerprints.py` | Take upstream, then re-port #169: skip presets without WebGL in `get_random_preset`, and the "No WebGL data" guard, now in `webgl.py`. Do not re-add `fontSpacingSeed` (D2). |
| `pythonlib/camoufox/utils.py` | Take upstream, then re-port `_bundle_version` / `_bundle_verstr` (macOS bundle layout), the #102 Playwright-floor warning and `executable_path` without a managed install. Upstream's `resolve_verstr` stays the public name and reads through the fork helper. |
| `pythonlib/camoufox/fonts.json` | Take upstream. |
| `settings/properties.json` | Union: upstream plus the fork's `cssMedia:*`, `window.scrollMin/Max*`, `screen.page*Offset`, `screen:orientation*`, `canvas:noise*`. Drop `fontSpacingSeed` (D2). |
| `tests/patches/search-service-init.py`, `touchscreen-digitizer.py` | Take upstream, but keep the fork's `obj-*` glob next to upstream's `CAMOUFOX_EXECUTABLE_PATH` read, for macOS hosts. |
| `upstream.sh` (clean) | Confirm `version=156.0.1`, `release=beta.32`, and no `closedsrc_rev`. |

- [ ] **Step 5: Manifest collision.** Delete the `firefox.exe.manifest` → `camoufox.exe.manifest` move in `scripts/copy-additions.sh` (around lines 60-65); upstream's `windows-exe-manifest.patch` now creates that file.
- [ ] **Step 6: Check for leftover markers.**

```bash
git diff --name-only --diff-filter=U        # expect: empty
git grep -n -E '^(<<<<<<<|>>>>>>>)' -- . ':!*.patch' ; echo "markers: $?"   # expect: markers: 1
```

- [ ] **Step 7: Local gates on the merged tree.**

```bash
python3 -m pytest ci/tests -q
python3 -m ci.run_native --subset rules     # displayfd fails on macOS (no Xvfb); that is a known host artifact
(cd pythonlib && python3 -m pytest tests -q)
(cd goapi && go test ./...)
```

Expected: everything green except `displayfd-not-lockfile-scan`. Anything else that is red is either fixed here or recorded for the PR body with the reason.

- [ ] **Step 8:** Commit the merge.

```bash
git commit -m "Merge upstream/main (daijro/camoufox 2f30fea, Firefox 156.0.1) into fork main

Patch conflicts take upstream's Firefox 156 version; the fork's deltas are
re-ported one patch per commit on this branch. webrtc-ip-spoofing keeps the
fork's model. release.yml is guarded to daijro/camoufox, build.yml is kept,
and tests.yml keeps push: main.

Refs #$ISSUE

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

### Task 2: Firefox 156 source tree and the first full-stack reading

- [ ] **Step 1:** `cd $WT && make setup` fetches the 156.0.1 tarball, extracts it, copies additions and tags `unpatched`. Check that the `camoufox-*` directory is gitignored: `git check-ignore -q camoufox-156.0.1-beta.32 && echo ok`.
- [ ] **Step 2:** Apply the whole stack and record every patch that rejects. Do not stop at the first failure.

```bash
cd $SRC && git reset -q --hard unpatched && git clean -fdq
for p in $(cd $WT && python3 -c "import sys;sys.path.insert(0,'scripts');from _mixin import list_patches;print('\n'.join(list_patches('patches')))"); do
  out=$(patch -p1 --forward -l --binary -i $WT/$p 2>&1) || echo "REJ $(basename $p): $(echo "$out" | grep -c FAILED) hunks"
done | tee $WT/.ci-work/stack-reading-1.txt
find . -name '*.rej' | wc -l
```

- [ ] **Step 3:** Compare the list with what is expected. From recon, likely: `canvas-spoofing` (FontSpacingSeed context), `webrtc-ip-spoofing`, `webrtc-ip-spoofing2`, `css-media-spoofing`, `cmap-unicode-ucs4-fallback`, `screen-orientation-spoofing`. Any patch that rejects and is **not** assigned to a task below gets its own step in Task 5.

### Task 3: Font patches (anti-font, font-hijacker, font-list-spoofing), in that order

For each patch, first run `at_position <patch>`. Then apply upstream's version, the fork delta `git diff $MB $FORK -- patches/<patch>`, and read the fork commits `git log --oneline $MB..$FORK -- patches/<patch>`. Port by editing `$SRC`, then `regen`, then dry-run the patch again from `base-<patch>`.

- [ ] **Step 1: `anti-font-fingerprinting.patch`.** Upstream's version is the base. Re-add the fork's `ContentChild::InitXPCOM` hunk that starts the storage mirror early. Upstream's equivalent entry point is `RoverfoxStorageManager::EnsureMirror()`: make it public and call it from `InitXPCOM`, in place of the fork's old call. Commit: `fix(patches): start the per-context storage mirror at content-process init on FF156`.
- [ ] **Step 2: `font-hijacker.patch`.** Upstream's version is the base. Keep the fork's `AutoFontListContext` in `FontFace::Load` (the `CamouFontListContextId` helper). Do not re-add the fork's forced `useCmaps` (D4). Commit: `fix(patches): keep the per-context font scope in FontFace::Load on FF156`.
- [ ] **Step 3: `font-list-spoofing.patch`.** Start from the fork's FF152 patch: `git show $FORK:patches/font-list-spoofing.patch > $WT/.ci-work/fls-152.patch`. Run `patch -p1 --forward -l --binary --merge -i` on it at position, then resolve every conflict region by hand, source file by source file. Pay attention to `gfxFontGroup::FindFontForChar` (`ff.Generic()` is now `mFonts[i].Generic()`) and to `GlobalFontFallback`.
  - D4: in `fallbackBlocked`, next to the `MaskedFontListBlocks` check, add `|| !CamouIsFontAllowed(<same family key>)`. Keep upstream's empty-key pass-through.
  - Delete the fork's cmap-only diagnostics that no longer have a code path.
  - `regen`. Commit: `fix(patches): port per-context font gating to FF156 and gate the platform fallback pick`.
- [ ] **Step 4:** Apply all three patches back to back from `unpatched`: 0 `.rej`.

### Task 4: The other conflicted patches

Same procedure (`at_position`, port, `regen`, commit). One commit per patch, each named `fix(patches): port <what> to FF156`.

- [ ] `browser-init.patch`: put the fork's #192 single `resizeTo` inside upstream's GNOME-maximize block, which uses the same variables.
- [ ] `chromeutil.patch`: re-add the `AccessObserver` include and `camouDrainAccessRecords`. Upstream already dropped `camouGetMouseTrajectory`.
- [ ] `navigator-spoofing.patch`: re-add the `Disable*Function` for the #57 setters and the observer hooks.
- [ ] `network-patches.patch`: #296, where the Accept-Encoding override moves from `SetAcceptLanguages` to `SetAcceptEncodings`.
- [ ] `screen-spoofing.patch`: re-add the `Disable*Function` and observer hooks.
- [ ] `speech-voices-spoofing.patch`: #149 per-process `sDisabledIds`.
- [ ] `window-setter-seal.patch`: upstream's version, plus the fork's `setCanvasSeed`. No font-spacing (D2). Update the seal count to match the setter list.
- [ ] `playwright/0-playwright.patch`: re-add the fork's package-manifest entries and `nsDocShell::DisableSpoofSetters` (#57). Check its order against upstream's new `popup-blocker-parity.patch` `nsDocShell` hunks. Drop `FontSpacingSeedManager::DisableFunction` (D2). Drop the `overrideTimezone` → `TimezoneManager` store hunk (D3); Task 7 checks with build-tester whether the timezone checks still pass without it.
- [ ] Untouched, taken as upstream: `cross-process-storage`, `timezone-spoofing`, `webgl-spoofing`, `windows-theming-bug-modified`.

### Task 5: Fork-only patches that reject on FF156

- [ ] `webrtc-ip-spoofing.patch` then `webrtc-ip-spoofing2.patch` (D1). Port the fork's FF152 versions onto 156 with `--merge`, as in Task 3 Step 3. Read upstream's #774 (ICE gathering completes behind a proxy) and carry that fix over if the fork's model has the same bug. Commit each.
- [ ] `canvas-spoofing.patch`: remove the `FontSpacingSeedManager.h` include and the `setFontSpacingSeed` context. Re-anchor on the FF156 `nsGlobalWindowInner` / `Window.webidl` / `ClientWebGLContext.cpp`.
- [ ] Every other patch in `stack-reading-1.txt`: port it the same way.
- [ ] Commit one patch per commit.

### Task 6: D2 and trajectory orphans outside patches

- [ ] Find every remaining reference: `git grep -n -i -E 'fontspacingseed|FontSpacingSeed|MouseTrajector|camouGetMouseTrajectory|test_mouse_trajectories'`. Expected hits: `goapi/pkg/config/config.go` (`FontsSpacingSeed`), build-tester presets and `src/lib/checks/index.ts`, `.github/workflows/smoke.yml` setter lists (about lines 258 and 1384), `additions/camoucfg/test_mouse_trajectories.cpp`, `test_stubs/`, `moz.build`, `AccessObserver.hpp`, `additions/juggler/.../PageHandler.js` near line 540, and `tests/patches/humanize-*.py`.
- [ ] Remove each one, or point it at upstream's replacement (`additions/juggler/input/CursorTrajectory.js`, `MouseDispatch.sendTrajectoryAcked`). Re-run the grep and expect no hits outside `docs/` and git history.
- [ ] Gates: `(cd goapi && go test ./...)`, `python3 -m pytest ci/tests -q`, and `python3 scripts/check-input-dispatch.py`.
- [ ] Commit: `chore: remove the font-spacing seed and C++ trajectory leftovers upstream deleted`.

### Task 7: Full-stack proof, build, browser suites, PR

- [ ] **Step 1: Full dry run from pristine.**

```bash
cd $SRC && git reset -q --hard unpatched && git clean -fdq
for p in $(cd $WT && python3 -c "import sys;sys.path.insert(0,'scripts');from _mixin import list_patches;print('\n'.join(list_patches('patches')))"); do
  patch -p1 --forward -l --binary -s -i $WT/$p || echo "FAIL $p"
done; echo "rej: $(find . -name '*.rej' | wc -l)"     # expect no FAIL lines, rej: 0
```

Then run `cd $WT && make dir` for real and expect `_READY`.
- [ ] **Step 2: Platform facts.**
  - `grep -rn mac_sdk_min_version $SRC/build/moz.configure/*.configure`: compare with the macos-26 runner in `build.yml` and update CLAUDE.md if it moved.
  - `python3 -c "import ci.versions as v; print(v.__dict__.get('resolve', v))"`, or read `ci/versions.py`, to confirm a Playwright tag resolves for 156. Also check the `build-tester` Playwright pin, which is 1.55.0 for 152.
- [ ] **Step 3:** Push the branch (`git push -u origin sync/upstream-2f30fea`). Dispatch **one** Linux build, after checking that no run already covers this head: `gh run list --repo lang315/camoufox --branch sync/upstream-2f30fea`, then `gh workflow run build.yml --repo lang315/camoufox --ref sync/upstream-2f30fea -f build_target=linux-x86_64`. Compile errors come back here: fix them in the owning patch (same procedure), push, and re-dispatch.
- [ ] **Step 4:** On the artifact:
  - `python3 -m ci.run_patch_guards --binary <bin>`
  - `python3 -m ci.run_build_tester --binary <bin>` (headful, under xvfb on Linux)
  - `gh workflow run smoke.yml --repo lang315/camoufox -f run_id=<build run>`
  - The D3 timezone checks and the D1 WebRTC checks decide whether a dropped hunk has to come back.
  - Before quoting any run id, resolve it to its branch and head sha.
- [ ] **Step 5: Docs.** In `docs/fonts-gating.md`, tag the line numbers as beta.31. In `docs/superpowers/plans/2026-09-26-open-e2e-findings.md`, add a note that W1-W4 were written against FF152 and need re-anchoring. Commit.
- [ ] **Step 6: PR.** `gh pr create --repo lang315/camoufox --base main --head sync/upstream-2f30fea`. Follow the #128 body shape:
  - measured state (ahead/behind counts, conflict count);
  - a conflicts-and-resolution table;
  - D1-D4 with reasons;
  - evidence (every command above, with output and exit status);
  - "Not verified", listing macOS/Windows builds not run and the W1-W4 staleness;
  - `Closes #$ISSUE`.
- [ ] **Step 7:** Once the checks are green: `gh pr merge <n> --repo lang315/camoufox --merge --delete-branch` (no `--auto`). Then check that the push to `main` started no `release.yml` job that did any work: `gh run list --repo lang315/camoufox --workflow release.yml -L 3` should show skipped jobs only.
