# Upstream sync to a3ab502 (repository restructure) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Merge upstream `daijro/camoufox` `a3ab502` into fork `main` (`cd06626`), keeping every fork feature that still applies on upstream's new `browser/` + `python/` + `typescript/` layout. Upstream's patch stack has been refactored (shared cross-process storage, per-principal context ids, one setter seal), and the fork's patches must be re-ported onto it with zero rejects and the fork's guards still passing.

**Architecture:** One merge commit (`-X find-renames=30%`) takes the layout move and resolves every conflict textually. For each conflicted patch it takes the side whose delta is larger. The other side's delta is then re-derived on a Firefox 156.0.1 tree, one patch per commit, in `list_patches` order (basename sort), and each patch is regenerated from that tree. Path fixes, launchers, CI and docs follow as separate commits. Then come a GNU-patch run of the full stack, local gates, a Linux build, patch guards, build-tester, Tests, smoke, and a PR merged as a merge commit.

**Tech Stack:** GNU patch (`/opt/homebrew/bin/gpatch`), git, `browser/scripts/patch.py`, `gh --repo lang315/camoufox`, pytest, `go test`, pnpm/vitest.

**Spec:** No separate design doc. The decisions below were taken with the user on 2026-10-12, from three read-only recon reports covering font patches, other patches plus additions, and non-patch files. Issue #188.

## Global Constraints

- Every `gh` call takes `--repo lang315/camoufox`. Never push to `main`. Merge the PR without `--auto`, only after the checks are green, as a **merge commit**.
- Never hand-edit a `.patch`. Edit the Firefox tree, then regenerate with `git add -A && git diff --cached base-<name>`, because plain `git diff` drops new files.
- Apply patches with `gpatch -p1 --forward -l --binary`. `git apply --check` and BSD `patch` are not valid pre-flights. Keep hand-written hunk context balanced.
- Tasks 4-6 share the one `$SRC` tree, so they run in one agent, in order. Other tasks may run in parallel subagents that only edit files, and the controller makes every commit, because the worktree shares one index.
- The Firefox pin is unchanged (`browser/upstream.sh`: `version=156.0.1`, `release=beta.32`). Any reject is caused by a patch-on-patch interaction, never by the tree.
- Settled decisions from #178, not reopened: the fork WebRTC model (per-context `WebRTCIPManager`, `webrtc-ip-spoofing2.patch`, no srflx fabrication); the font-spacing seed is removed; upstream's per-realm timezone; upstream `GlobalFontFallback` plus `CamouIsFontAllowed(key)` in `fallbackBlocked`; per-OS font grouping; the fork values composite-on (#140), `DISPLAYFD_READ_TIMEOUT_S = 30.0` (#157) and `media.peerconnection.ice.no_host = true`.
- Decisions taken for this sync:
  - **L1 layout:** `goapi/`, `e2e/` and `plan/` stay at the repository root. Every upstream deletion is taken (example/, ROADMAP.md, vendored TS fpgen/pyrandom/locale, the GUI, librewolf patches, `browser-init.patch`, `pin-addons`, `global-style-sheets`, `windows-theming-bug-modified`).
  - **C1 canvas (hybrid):** take upstream's rendering model (`plan_rendering` / `planRendering`). On the host's OS a context claims the host's GPU. On any other OS or GPU, the RFP canvas targets cover readback, and a non-covered browser raises on a cross-OS context. The fork's seeded per-context canvas noise is kept **only where the launch is not covered**, because it is the fork's answer to cross-context linkability on one host, which upstream does not address. Mechanism: the launcher draws `canvas:seed` and calls `setCanvasSeed` only when `plan_rendering` does not cover canvas. With no seed, the patch is inert. Read on the fork patch: `CanvasSeedManager::GetSeed` returns 0 when the context has no seed and `canvas:seed` is unset, and `Perturb` and all three call sites skip on 0. This changes the per-context contract, and the docs and PR body must say so: under upstream's `context_identity`, `new_context(os=<non-host>)` on a launch that claims the host's OS raises unless the browser was launched with `canvas_noise=True`.
  - **F1 font-list storage:** take upstream's shared-store font list (914b575). Flush the fork's per-process caches (#81 `ClearCodepointsWithNoFonts`, #83 `ClearFontNameCaches`) in **every** content process from `RoverfoxStorageManager`'s main-thread storage-pref callback when a `fontlist_<id>` key arrives, after the storage mutex is released. If that callback does not run in every process before its first lookup, fall back to a per-process "seen" flag that `SetFontList`'s own init-script call sets (hybrid). Never flush from `EnsureFontList`: it runs under `mLock`, which would invert `mLock -> sFontListMutex`.
  - **F2 system-ui:** use upstream's `SystemUISpoofedOS` / `GetSystemUIFontFamilies` (Linux -> Ubuntu, a native identity keeps the host font). The fork's worker branch stays, so a worker answers with its context's OS. The fork's own Mac/Win step in `AddGenericFonts` is removed in favour of upstream's helper.
  - **F3 context id:** use `RoverfoxStorageManager::UserContextId(...)` at every lookup site (font ctor, FontFaceSet Load/Check, FontFace::Load, setters, canvas, webrtc). The fork's worker branch in the `gfxFontGroup` ctor stays.
  - **P1:** drop #57 `nsDocShell::DisableSpoofSetters` and every `*Manager::Disable*Function` it calls (it has no caller and does not compile on upstream). Fix `docs/stealth-invariants.md:63`.
  - **P2:** fork-only setters (`setCanvasSeed`, `setWebRTCIPv4/6`) gate through upstream's `IsSetterOffered` / `MarkSetterUsed` / `RemoveSetter`. This is required: without it `setWebRTCIPv4/6` are offered to page script (the #57 leak class).
  - **P3:** keep the fork's https-only `headers.Accept-Encoding` override (stock Firefox sends different lists per scheme).
  - **P4:** take upstream's WebRTC ephemeral-port hunks (`nr_socket_prsock.cpp`, `transport/common.build`) into the fork's `webrtc-ip-spoofing.patch`.
  - **P5:** accept upstream `CamoufoxWindow.sys.mjs` sizing, dropping the fork's unconditional 1280x1040 default.
  - **P6:** drop the fork's `no-search-engines` throw removal (unreachable) and the speech #149 per-process ids (superseded by the shared store).
  - **N1:** guard upstream's `install` job to `github.repository == 'daijro/camoufox'`, and drop `install` from `required=` under the fork guard. Fork tags (`v152.0.4-beta.31-fork.1`) never match `release.py`'s pin pattern.
  - **N2:** take upstream's screen/avail model (baseline protection, `launcher-constants.json`). Fork screen code that upstream superseded (`fix_screen_no_taskbar` consumers, the macOS menu-bar floor) is dropped; the dpr1 resample is kept only if its test still applies on upstream's model.
  - **N3:** keep the fork's #169 `_webgl_samplable` preset filter.
  - **N4:** where a fork guard and an upstream guard test the same bug, keep upstream's and delete the fork's, after reading both and confirming upstream's asserts at least as much (`context-list-every-process` vs `context-lists-across-processes`; `worker-navigator-spoofing` vs `worker-config-reads`). Keep `local-font-source` (no upstream twin).
  - **N5:** service tester: take upstream's file layout, import `collect_results` from build-tester's `runner.py`, keep the fork's one-browser-per-OS `_run_os_group`, and do **not** call `adjust_cross_os_font_checks` (#45).
  - **N6:** take upstream's `webgpu-follows-the-claimed-device` rule; drop the fork's `defaultPref("dom.webgpu.enabled", false)`.
  - **N7:** dated `docs/superpowers/{plans,specs}/*` and `plan/*` keep their old paths as records. Only living docs are updated.

## Review Focus

1. A context that never set a fork setter still has no `setCanvasSeed` / `setWebRTCIPv4` / `setWebRTCIPv6` on `window`, in the first document and after navigation. Owner: Task 6, guard `fingerprint-setter-seal.py` extended.
2. A canvas in a `DOMParser` / `document.implementation.createHTMLDocument()` document of a non-covered launch reads its own context's seed, not 0. Owner: Task 4, guard added to the canvas guard.
3. A context's font list is enforced in a second content process (FF156 gives every container its own pool), and the #83 memo leak stays closed. Owner: Task 5, guards `context-lists-across-processes.py` + the #83 smoke arm.
4. `NewContext(os=<non-host>)` on a non-covered browser fails loudly (upstream `ValueError`), never silently. A covered launch never draws `canvas:seed`. Owner: Task 8, pythonlib tests.
5. CI builds the merged browser instead of restoring main's: the browser cache key covers `browser/patches` and friends. Owner: Task 10, readback of the `resolve` step in the first Tests run.

## Paths and variables used by every task

```bash
WT=/Users/lang/GolandProjects/github.com/lang315/camoufox/.claude/worktrees/sync-upstream-a3ab502
SRC=$WT/camoufox-156.0.1-beta.32   # pristine FF156, git tag `unpatched`; gitignored
MB=2f30fea; FORK=cd06626; UP=a3ab502
```

`$SRC` was built from `https://archive.mozilla.org/pub/firefox/releases/156.0.1/source/firefox-156.0.1.source.tar.xz`. It was extracted, then `git init && git add -A && git commit -m unpatched && git tag unpatched`.

`$WT/.ci-work/applystack.sh` (gitignored, reproduced here) applies a stack the way `browser/scripts/patch.py` does. It copies `additions/` but skips the `lw/` settings copy and the `version.txt` rewrite of `copy-additions.sh`, so CI's `make dir` remains the only full-fidelity check. On 2026-10-12 it applied both `$FORK`'s stack and `$UP`'s stack to `$SRC` with `FAILED_PATCHES=0`.

```bash
#!/bin/bash
# usage: applystack.sh <tree> <root-with-additions-and-patches> [stop-before-basename]
set -u
tree=$(cd "$1" && pwd); root=$(cd "$2" && pwd); stop=${3:-}
cd "$tree" || exit 2
git reset -q --hard unpatched && git clean -fdqx
cp -r "$root"/additions/* .
fail=0
for p in $(cd "$root" && find patches -name '*.patch' | awk -F/ '{print $NF"\t"$0}' | LC_ALL=C sort | cut -f2); do
  b=$(basename "$p")
  [ -n "$stop" ] && [ "$b" = "$stop" ] && break
  out=$(/opt/homebrew/bin/gpatch -p1 --forward -l --binary -i "$root/$p" 2>&1)
  rc=$?
  if [ $rc -ne 0 ] || echo "$out" | grep -qE 'FAILED|Reversed|fuzz'; then
    echo "== $p rc=$rc"; echo "$out" | grep -E 'FAILED|Reversed|fuzz|can.t find|No file' | head -8
    [ $rc -ne 0 ] && fail=$((fail+1))
  fi
done
find . -name '*.rej' -not -path './.git/*' | head -20
echo "FAILED_PATCHES=$fail"
```

"Tree at position N" (the #131 procedure, never `make workspace`):

```bash
bash .ci-work/applystack.sh camoufox-156.0.1-beta.32 browser <basename-of-patch-N>
cd camoufox-156.0.1-beta.32 && git add -A && git commit -qm "stack before <name>" && git tag -f base-<name>
# apply patch N itself, edit the tree, then regenerate:
git add -A && git diff --cached base-<name> > ../browser/patches/<path-of-N>
```

Before editing, prove the baseline: regenerate patch N unedited and confirm it is byte-identical to the committed file, apart from `index` lines.

---

### Task 1: The merge commit

**Files:** every conflicted path from the trial merge (77 at `-X find-renames=30%`).

- [ ] **Step 1:** `git merge --no-ff --no-commit -X find-renames=30% upstream/main`. Expect 77 conflicts.
- [ ] **Step 2: patches.** Take the side with the larger delta now. Later tasks port the other side.
  - Take **upstream** (`git checkout --theirs`): `audio-fingerprint-manager`, `chromeutil`, `cross-process-storage`, `navigator-spoofing`, `no-search-engines` (P6, final), `screen-spoofing`, `speech-voices-spoofing` (P6, final), `timezone-spoofing`, `webgl-spoofing` (final), `window-setter-seal`, `patch-dependencies.md`.
  - Take the **fork** (`git checkout --ours`): `font-list-spoofing` (fork delta 423 lines vs upstream 119), `webrtc-ip-spoofing` (settled model).
  - Fork-only patches (`canvas-spoofing`, `cmap-unicode-ucs4-fallback`, `css-media-spoofing`, `screen-orientation-spoofing`, `webrtc-ip-spoofing2`) land at `browser/patches/` as git suggests.
  - `patches/browser-init.patch` (UD): `git rm` (P5).
- [ ] **Step 3: additions.** Accept git's suggested `browser/additions/camoucfg/` location for `AccessObserver.hpp`, `AccessObserverDom.hpp` and `test_access_observer.cpp`, and move `additions/observer/` to `browser/additions/observer/` if it was not moved. Confirm `browser/additions/juggler/Helper.js` is the fork's blob (upstream's is byte-identical to `$MB`).
- [ ] **Step 4: tests and tools.**
  - Fork-only files under renamed dirs go to their mapped paths: `browser/tests/{build-tester,native,service,playwright}/…`, `browser/scripts/rehearse-patch.*`, `python/tests/*`.
  - `python/tests/test_geoip_config.py` (add/add): keep upstream's file, and save the fork's as `python/tests/test_geoip_merge.py`.
  - `python/tests/conftest.py`: keep both autouse fixtures (`no_browser_fetch` and `no_host_gpu_probe`). Re-root `repo_get_path` and `repo_version` to `browser/bundle`, `browser/settings` and `browser/upstream.sh`.
  - `test_identity_salt.py`, `test_launch_geometry.py`, `test_voices.py`, `test_webgl_screen_consistency.py`: upstream's import style plus the fork's mocks.
  - `pythonlib/README.md`: `git rm`.
  - `service-tester/_bundle.py`, `service-tester/_grading.py`: `git rm`; Task 11 re-ports what they held.
  - `build-tester/requirements.txt`: `git rm`, then append `marionette_driver` to `browser/tests/build-tester/requirements.txt`.
  - `browser/tests/build-tester/run_tests.sh`: upstream's path plus the fork's `playwright<1.63` cap and the xvfb block (#75).
- [ ] **Step 5: repository files.**
  - `.gitignore`: take upstream and append the fork block (`.claude/`, `.memsearch/`, `/goapi/*` artifacts, `/local/`, `/CLAUDE-FABLE-5.md`, `.rehearse/`, `*.rej`, `.harness-work/`).
  - `CONTRIBUTING.md`: take upstream, and move the fork's headful/xvfb paragraph into `browser/tests/build-tester/README.md`.
  - `.github/workflows/tests.yml`: take upstream, then re-apply the fork's additions by hand:
    - `push: branches: [main]`;
    - the fork guard as the first line of the resolve step, above `if [ "${{ github.event_name }}"`;
    - the `e2e` job, with `pip install -e 'python[geoip]'`;
    - `e2e` in `summary.needs`, the gate's `needs` and `required=`;
    - the guard comment's `python/src/camoufox/repos.yml`.
  - `typescript/scripts/golden/launch_golden.py`: take upstream's scenarios now; Task 9 re-records.
- [ ] **Step 6:** `git diff --name-only --diff-filter=U` prints nothing, and `git grep -lE '^(<<<<<<<|>>>>>>>)'` finds nothing. `git grep -nE 'pack_vs|search-config|chrome\.css' browser/scripts/copy-additions.sh` must also find nothing. Upstream deleted those files, so a copy line left by the auto-merge fails `make dir` on CI, and `applystack.sh` would not notice.
- [ ] **Step 7:** Commit: `Merge upstream daijro/camoufox a3ab502 into fork main (#188)`. The body lists which side each conflicted patch took and states that the stack is not buildable until Tasks 3-7.

### Task 2: Paths that the move broke

**Files:** `.github/workflows/{build,e2e,goapi,smoke}.yml`; `goapi/pkg/fingerprint/data_drift_test.go`, `goapi/pkg/config/drift_test.go`, `goapi/fontconfig_test.go`, `goapi/additions_timer_import_test.go`; `e2e/pytest.ini`, `e2e/journeys/test_01_install_launch.py`, `e2e/oracle/docs.py`; `ci/tribal-rules.yml` evidence paths; `ci/tests/test_fork_workflow.py` docstring.

- [ ] **Step 1: build.yml.**
  - Run the `make` steps and `multibuild.py` with `working-directory: browser`.
  - Change `find patches` to `find browser/patches`, and `dist/*` to `browser/dist/*`.
  - Change `hashFiles('upstream.sh')` (three keys) to `hashFiles('browser/upstream.sh')`. The old form is silent: it hashes a missing file to a constant.
  - Change the source tarball cache path to `browser/firefox-*.source.tar.xz`.
- [ ] **Step 2: smoke.yml.**
  - `pip install -e pythonlib` becomes `python`; drop `cd pythonlib`.
  - `tests/patches/` becomes `browser/tests/playwright/patches/`.
  - `pythonlib/camoufox/fonts.json` becomes `python/src/camoufox/fonts.json`.
  - `bundle/fonts/macos` becomes `browser/bundle/fonts/macos` (silent `os.walk`).
  - `e2e.yml`: `-e "python[geoip]"`.
  - `goapi.yml` `paths:`: add `browser/additions/**`, `browser/settings/properties.json`, `browser/bundle/fontconfig/**` and `python/src/camoufox/fonts.json`.
- [ ] **Step 3: goapi tests.** Re-root the five paths. Change `additions_timer_import_test.go`'s `t.Skipf` on a missing directory to `t.Fatalf`, because a missing prerequisite fails.
- [ ] **Step 4: e2e.**
  - `pytest.ini`: `pythonpath = . ../python/src`.
  - `test_01`: `pip install REPO/"python"`.
  - `oracle/docs.py`: `python/src/camoufox/…` and `browser/bundle/fontconfig/linux/fonts.conf`.
- [ ] **Step 5: verify.** Run the following and expect each to pass:
  - `go test ./...` in `goapi/`. Before Task 7, the drift test may fail on content but never on a path.
  - `python3 -m pytest ci/tests -q`.
  - `git grep -nE '(^|[^/a-z])(pythonlib/|native-tests/|service-tester/|build-tester/)' -- .github ci goapi e2e CLAUDE.md docs/fonts-gating.md docs/stealth-invariants.md docs/observer goapi/README.md` must return nothing.
- [ ] **Step 6:** Commit `fix: follow upstream's browser/ and python/ layout in fork workflows, goapi and e2e (#188)`.

### Task 3: Additions

**Files:** `browser/additions/camoucfg/MaskConfig.hpp`, `browser/additions/camoucfg/moz.build`, `browser/additions/juggler/input/CursorTrajectory.js`.

- [ ] **Step 1:** Re-apply the fork's four `MaskConfig.hpp` changes on upstream's file:
  - the `GetString` / `GetStringList` type guards (print `ERROR:` and return empty);
  - `GetMediaCanPlayType` / `GetMediaDecodingInfo`, adding `#include <cctype>`;
  - `const auto&` in `GetNested` and `MVoices`;
  - an updated `GetNested` comment (the cited `GetAttribute` no longer exists).
- [ ] **Step 2:** Re-add the two `AccessObserver*.hpp` `EXPORTS` lines to `moz.build`. In `CursorTrajectory.js`, merge the comment: the fork's wording with upstream's `2356`.
- [ ] **Step 3:** Commit `fix(camoucfg): carry the fork's MaskConfig guards and media helpers onto upstream (#188)`.

### Task 4: Patch re-ports, `0-playwright` through `cmap-unicode-ucs4-fallback`

Each step below is: build the tree at that patch's position, prove the baseline, edit, regenerate, apply the stack up to and including it with `applystack.sh`, and commit `fix(patches): <name> on upstream's stack (#188)`.

- [ ] **`playwright/0-playwright.patch`** (upstream taken by auto-merge): drop the `DisableSpoofSetters` hunks in `nsDocShell.cpp` and `nsIDocShell.idl` (P1). Keep the observer `package-manifest.in` / `toolkit.mozbuild` hunks.
- [ ] **`anti-font-fingerprinting.patch`**: take upstream's principal-based `gfxFontGroup` ctor. The fork's `EnsureMirror` change moves to `cross-process-storage.patch` (below).
- [ ] **`audio-fingerprint-manager.patch`** (upstream): re-port the fork's AccessObserver hooks, as one `RecordSurfaceFromDocument(..., SurfaceId::Audio)` in `AnalyserNode::NoisedOutput()` plus one in each time-domain getter, through `OwnerWindow(GetParentObject())->GetExtantDoc()`.
- [ ] **`canvas-spoofing.patch`** (fork-only; regenerate):
  - Move the `nsGlobalWindowInner.cpp` include anchor to a block no later patch straddles, and the `.h` decl next to `SetAudioFingerprintSeed`, away from timezone's `SetTimezone`.
  - Switch `SeedFromDocument`, `IsFunctionEnabledForWebIDL` and `SetCanvasSeed` to `UserContextId`. The gate is `IsSetterOffered(aObj, "canvas")`; the setter calls `MarkSetterUsed` and `RemoveSetter("setCanvasSeed")` (P2, F3).
  - Fold the three hand-rolled AccessObserver sites into `RecordSurfaceFromDocument`.
  - Fix the stale `ReadPixels` "RFP is disabled" comment.
  - Add to the canvas guard: a `DOMParser` document's canvas reads the context's seed (Review Focus 2). Confirm the guard is red on the pre-port patch. Add a second arm: on a covered launch, two reads of one canvas differ (RFP placeholder) and no fork perturb runs. Read that from the patch's own canvas log line, not from pixels.
- [ ] **`chromeutil.patch`** (upstream): re-port `CamouDrainAccessRecords`. Put it after `IsCamouDebug` and its include away from `MaskConfig.hpp`, so `window-setter-seal` hunk 1 still applies with no fuzz.
- [ ] **`cmap-unicode-ucs4-fallback.patch`**: unchanged, except the `bundle/fonts/macos/` comment path, which becomes `browser/bundle/fonts/macos/`.

### Task 5: Patch re-ports, `cross-process-storage` through `font-list-spoofing` (fonts)

- [ ] **`cross-process-storage.patch`** (upstream):
  - Make `RoverfoxStorageManager::EnsureMirror()` public, and call it from `ContentChild::InitXPCOM` (fork 03223c0), so a worker's first lookup sees the mirror.
  - Add the F1 flush: in the storage-pref callback, after the cache mutex is released and the new key starts with `fontlist_`, call `gfxPlatformFontList::PlatformFontList()->ClearCodepointsWithNoFonts()` and `ClearFontNameCaches()`, and drop the per-process parsed copy of that context's list.
  - Measure whether the callback fires in a second content process before that process's first lookup. Log a `CAMOU-FL flush` line and read it on a two-process run (see the FF156 per-container pools note). If it does not fire first, use the hybrid per-process flag instead, and record which one shipped in the commit body.
- [ ] **`css-media-spoofing.patch`**: confirm it applies unchanged.
- [ ] **`font-hijacker.patch`** (auto-merged): re-port the fork's `FontFace::Load` `AutoFontListContext`, using `RoverfoxStorageManager::UserContextId(aGlobal->GetAsInnerWindow())` instead of `CamouFontListContextId` (F3).
- [ ] **`font-list-spoofing.patch`** (fork taken; port upstream's delta onto it):
  - `FontListManager.cpp`: upstream's storage-backed list, `MarkSetterUsed("fontlist")` and `IsSetterOffered`; remove `sDisabledIds`.
  - `SetFontList`: `UserContextId(this)` plus `RemoveSetter("setFontList")`.
  - `FontFaceSet::Load/Check`: `UserContextId(GetOwnerWindow())`, keeping the AccessObserver call.
  - The `gfxTextRun` ctor: rebase the fork's worker branch onto upstream's `UserContextId(doc)`, and rename the `hop=` diagnostics to `provider-null`, `doc-null`, `principal` and `worker`. Update every parser of `hop=` in the same commit: `smoke.yml` (around lines 2077, 2173-2176 and 2342-2359) reads `hop=bc` as "not fail-open" and must read `principal` or `worker` instead, and `context-list-every-process.py` and `system-ui-font-spoofing.py` parse it too. Otherwise smoke reads every healthy lookup as fail-open. Run `git grep -n 'hop=' -- .github browser/tests` afterwards.
  - Drop upstream's inline gate at `FindAndAddFamiliesLocked` (:1790). The fork's `CamouIsFontAllowed(key)` after `MaskedFontListBlocks` remains the only per-context gate in that function.
  - Remove the fork's system-ui step from `AddGenericFonts` (F2); `system-ui-font-spoofing.patch` owns it now.
- [ ] Run `browser/tests/playwright/patches/context-lists-across-processes.py` and the fork's `context-list-every-process.py` on Task 13's build. Delete the fork's guard per N4 only if upstream's asserts at least as much.

### Task 6: Patch re-ports, `media-codec-spoofing` through `window-setter-seal`

- [ ] **`media-codec-spoofing.patch`** (auto-merged): confirm the fork's `MediaCapabilities`, `HTMLMediaElement::CanPlayType` and `MediaSource::IsTypeSupported` hunks sit on upstream's `GetBool` hunks.
- [ ] **`navigator-spoofing.patch`**, **`screen-spoofing.patch`** (upstream): re-port the AccessObserver one-liners (4 and 2). Do not re-port `Disable*Function` (P1).
- [ ] **`network-patches.patch`**: confirm the fork's https-only scope survived (P3).
- [ ] **`screen-orientation-spoofing.patch`**: confirm it applies unchanged.
- [ ] **`system-ui-font-spoofing.patch`** (upstream): regenerate on top of the ported `font-list-spoofing`. Remove the duplicate `NavigatorManager.h` include, and keep the #94 `AutoFontListContext(0)` inside upstream's per-OS cell code. Add the worker fallback to `SystemUISpoofedOS`: off the main thread, read the worker's `GetOriginAttributes().mUserContextId` (F2). Run the fork's `system-ui-font-spoofing.py`, and upstream's `system-ui-font-spoofing.py` and `context-os-system-font.py`.
- [ ] **`timezone-spoofing.patch`** (upstream): confirm it applies on top of the regenerated canvas patch with no fuzz. Re-anchor only if it does not.
- [ ] **`webrtc-ip-spoofing.patch`** (fork):
  - Replace the private `webrtc_ipv{4,6}_disabled_<ctx>` keys with `IsSetterOffered(aObj, "webrtc_v4" / "webrtc_v6")`, `MarkSetterUsed` and `RemoveSetter("setWebRTCIPv4" / "setWebRTCIPv6")` (P2).
  - Replace the 8 `GetBrowsingContext()` lookups with `UserContextId(...)` (F3).
  - Add upstream's `nr_socket_prsock.cpp` ephemeral-port and `transport/common.build` hunks (P4).
  - Keep edits out of the regions `webrtc-ip-spoofing2.patch` anchors on (`IPv6KeyForUserContext`, `SetIPv6`, the class `public:` blocks).
- [ ] **`webrtc-ip-spoofing2.patch`**: confirm it applies unchanged after the webrtc rewrite.
- [ ] **`window-setter-seal.patch`** (upstream): add `"setCanvasSeed"` to `kCamouFingerprintSetters`. Extend `fingerprint-setter-seal.py` to assert that `setCanvasSeed`, `setWebRTCIPv4` and `setWebRTCIPv6` are absent in a context that set none of them, before and after a navigation (Review Focus 1). Confirm it is red with the webrtc gate reverted.
- [ ] **`patch-dependencies.md`** (upstream): re-add the fork's webrtc row, and add rows for `canvas-spoofing` (`canvas:seed`, `canvas:noiseDensity`, `canvas:noiseStrength`), `css-media-spoofing` (`cssMedia:*`), `screen-orientation-spoofing` (`screen:orientation*`) and `media-codec-spoofing` (`mediaCapabilities:*`).
- [ ] **Full stack:** `bash .ci-work/applystack.sh camoufox-156.0.1-beta.32 browser` prints `FAILED_PATCHES=0` and no `.rej`. Record the fuzz lines in the PR body.

### Task 7: `properties.json` and the config schema

**Files:** `browser/settings/properties.json`, `goapi/pkg/config/drift_test.go`, `typescript/tests/fixtures/launch/bundle/properties.json`.

- [ ] **Step 1:** Add the 7 fork-only keys (`canvas:noiseDensity`, `canvas:noiseStrength`, `cssMedia:{colorGamut,dynamicRange,prefersColorScheme}`, `screen:{orientation,orientationAngle}`).
- [ ] **Step 2:** Remove the `removed` marker from every key a shipped fork patch reads: `canvas:seed`, `webrtc:localipv4`, `webrtc:localipv6`. Keep the marker on `disableTheming` and `webGl*:contextAttributes`, whose patches upstream deleted or rewrote. Confirm with `git grep -F '"<key>"' -- browser/patches browser/additions` for each.
- [ ] **Step 3:** `TestProducerSchemaDrift` skips entries carrying `removed`. Write that check first, confirm it is red on the merged file, then make it pass.
- [ ] **Step 4:** Keep the TypeScript fixture in step with `browser/settings/properties.json`, as the existing fixture test asserts.
- [ ] **Step 5:** Run `go test ./pkg/config/...`, `python3 -m pytest browser/tests/native/test_tribal_rules.py -q -k "config_keys or properties"`, and `pnpm -C typescript test -- launch`.
- [ ] **Step 6:** Commit `fix(config): declare the fork's live keys on upstream's properties.json (#188)`.

### Task 8: Python launcher

**Files:** `python/src/camoufox/{utils,fingerprints,sync_api,async_api,virtdisplay,server}.py`, `python/tests/*`.

- [ ] **Step 1 (C1, test first):** add `python/tests/test_canvas_seed_follows_rendering_plan.py`:
  - a non-covered launch (host OS) sends a `canvas:seed` that differs per context;
  - a covered launch (another OS, `canvas_noise` default) has no launch-level `canvas:seed` in `CAMOU_CONFIG`, and no context's init script calls `setCanvasSeed`. Assert both, separately;
  - `NewContext(os=<non-host>)` on a non-covered browser raises upstream's `ValueError`.
  Confirm the test is red, then plumb the seed from the `plan_rendering` result only, and confirm it is green. Rework the fork's `TestCanvasSeed` in `test_identity_salt.py` to the same rule.
- [ ] **Step 2:** re-port onto upstream's `NewBrowser` shape: `_check_writable_dirs`, `attach_launch_fonts`, `warn_fonts_excluded_by_launch`, and the fork's `_camou_config_blob` (fails loudly on a corrupt config).
- [ ] **Step 3:** take upstream's `resolve_verstr` (`pkgman.build_file`), delete the fork `_bundle_*` code it covers, and re-port #102 so `warn_if_executable_predates_playwright` reads the build's own `application.ini`. Check `build_file` on the macOS `Contents/Resources` layout.
- [ ] **Step 4:** keep the fork values in `virtdisplay.py`: composite on, and `DISPLAYFD_READ_TIMEOUT_S = 30.0`. Keep #169 `_webgl_samplable` (N3). Drop fork screen code upstream superseded (N2), and keep the dpr1 resample only if `test_screen_dpr_coherence.py` still describes upstream's model.
- [ ] **Step 5:** `python3 -m ci.run_pythonlib` passes. Commit `fix(python): fork launcher features on upstream's rendering plan (#188)`.

### Task 9: TypeScript

**Files:** `typescript/src/{fingerprints,utils}.ts`, `typescript/scripts/golden/{launch,identity}_golden.py`, `typescript/tests/*`.

- [ ] **Step 1:** port the canvas seed onto `python-random`, gated on `planRendering` exactly like Task 8 step 1. The TS launch golden is byte-equal to Python's, so the gating must match.
- [ ] **Step 2:** re-record both goldens with `MODULE_SEED = 20261001` kept. Run `pnpm -C typescript test` and `pnpm -C typescript typecheck`.
- [ ] **Step 3:** commit `fix(ts): canvas seed on python-random, gated by planRendering (#188)`.

### Task 10: Workflows and CI runners

**Files:** `.github/workflows/tests.yml`, `ci/run_build_tester.py`, `ci/run_patch_guards.py`, `ci/tests/test_ci.py`, `browser/settings/camoufox.cfg`.

- [ ] **Step 1 (N1):** add `if: github.repository == 'daijro/camoufox'` to the `install` job, and drop `install` from `required=` under the fork guard. Extend `ci/tests/test_fork_workflow.py` to assert both, red first.
- [ ] **Step 2:** `run_build_tester.py`: keep the fork's `_LOW_ENTROPY = ("uniqueCanvas",)` bucket on upstream's paths. `run_patch_guards.py`: union the fork's surviving guards into upstream's `GROUPS` (after N4). In `test_ci.py`, required suites include both `install` and `e2e`.
- [ ] **Step 3:** `camoufox.cfg`: keep the fork's `no_host` block, and drop `defaultPref("dom.webgpu.enabled", false)` (N6).
- [ ] **Step 4:** `python3 -m pytest ci/tests -q`. Commit `ci: fork jobs and guards on upstream's workflow (#188)`.

### Task 11: Service tester, tribal rules, docs

- [ ] **Service (N5):** in `browser/tests/service/run_tests.py`, import `collect_results` from `runner` instead of waiting on `window.__testComplete__` (upstream's page no longer sets it, so it hangs). Re-port `_run_os_group`, and remove the `adjust_cross_os_font_checks` call. Verify with a local run against Task 13's build.
- [ ] **Tribal rules:**
  - Keep `composite-extension-on` and `displayfd-read-timeout` (30 s).
  - Take upstream's six new rules except where C1 changes them.
  - **Measure before writing the canvas note.** The fork's `canvas-noise-entropy-is-lower-than-audio` measured 16 distinct of 24, before the seed was restored, and has not been re-measured since. Read `uniqueCanvas` on Task 13's build-tester run for same-OS contexts first. If same-OS contexts still collide, the hybrid's only justification is measured false. Then stop and bring the number to the user, with "adopt upstream" as the alternative. If they do not collide, write the divergence note on `cross-os-canvas-is-the-rfp-placeholder` from the number. It must state the trade plainly: the fork applies keyed noise on launches that claim a real host GPU, which upstream rejected because no current Firefox produces it, and does so for cross-context unlinkability on one host. Update the entropy rule's evidence with the new measurement.
  - Drop upstream's `test_no_canvas_seed_is_declared_or_sent` again, and replace it with a test that a covered launch sends no seed.
  - Prefix the fork rules' evidence paths with `browser/` or `python/src/`.
  - Add a rule for F1 (where the font list lives and where its caches flush), citing the guard.
- [ ] **Docs:**
  - `docs/fonts-gating.md`: lesson 5's chain becomes provider -> document -> principal plus the worker branch, the five-site table is re-read on the ported tree, and the #149 paragraph follows F1.
  - `CLAUDE.md` fork notes:
    - lesson 5;
    - the paths;
    - `make -C browser …`;
    - the "same browser" rule's dir list, which must match the `resolve` regex including `browser/bundle/fontconfig/`.
  - `docs/per-context-patches.md`: re-apply the fork paragraphs to upstream's rewrite. Do not copy upstream's stale `BrowsingContext` lines (:90, :129-134). Wherever it promises a per-context OS, add the condition: on a launch that claims the host's OS, `new_context(os=<non-host>)` raises unless the browser was launched with `canvas_noise=True`.
  - `docs/stealth-invariants.md:63` (P1), `docs/observer/*`, `goapi/README.md`.
- [ ] Commit per area.

### Task 12: e2e and goapi behaviour

- [ ] **e2e test_05 (C1):** under a covered launch (`os="windows"` on Linux CI), canvas readback is RFP's random placeholder, so canvas leaves the "two pages of one context agree" tuple. Add a separate assertion that the covered launch's canvas is the placeholder (two reads differ), quoting `cross-os-canvas-is-the-rfp-placeholder`. Re-check test_02 and test_03 for canvas-hash assumptions.
- [ ] **goapi:** goapi has no rendering plan, so it keeps sending `canvas:seed` and gets no RFP cover on a cross-OS launch. Record this gap in `e2e/known.py`, scoped to goapi, and open a follow-up issue to port `plan_rendering` to goapi. Do not port it in this PR. The same note records the contract difference: goapi still allows a cross-OS context on a native-OS launch, and the Python and TypeScript launchers no longer do.
- [ ] `python3 -m ci.run_e2e --binary …` on Task 13's build. Commit.

### Task 13: Build, guards, PR

- [ ] **Step 1:** push the branch and dispatch `gh workflow run build.yml --repo lang315/camoufox --ref sync/upstream-a3ab502 -f build_target=linux-x86_64`. Record the run id.
- [ ] **Step 2:** on the artifact, run `python3 -m ci.run_patch_guards --binary …` (all groups) and `python3 -m ci.run_build_tester --binary …`, with `make -C browser stage-fonts` first.
- [ ] **Step 3:** open the PR (`Closes #188`) and let Tests run. Read the `resolve` step's log: the browser must be **built**, not restored (Review Focus 5). Dispatch `smoke.yml -f run_id=<build run>`.
- [ ] **Step 4:** in the PR body, report every run id resolved to its head sha, the `applystack` result, each decision above, and what was not verified (macOS/Windows not built; goapi rendering gap).
- [ ] **Step 5:** when `All tests passed` and smoke are green, merge as a merge commit without `--auto`.
