# Fonts round 2 — design

Closes the font issues left open after PR #84 (`fix/44-fonts-h2`, merged as `f1b60a6`):
#80 (URL web fonts refused), #82 (U+FFFD fallback cache leaks across contexts), #83
(per-context list not enforced in the process that renders), plus the measurement work
for #87 (native Windows) and #88 (the 375.7 face), and the admin left on #81 and #89.

One branch, `fix/fonts-round2`, one PR, "part of #44". Budget: two CI builds (one Linux,
one Windows, dispatched together at the fix tip) plus one more Linux build only if the
#83 gate in Phase B goes the unexpected way. Every measurement runs in the existing
`#44` smoke workflow (`.github/workflows/smoke.yml`, `workflow_dispatch` with a build
`run_id`), so every claim in the PR is a run id plus a log line.

Recon backing this design (file:line for everything below):
`.superpowers/sdd-fonts2/code-recon.md` (untracked scratch; the facts it cites are
repeated here where a task depends on them).

## Global constraints

Copied verbatim into the plan; every task inherits them.

- Patches are edited through the workspace flow, never by hand: `make revert`, apply the
  stack up to the target patch (`.superpowers/sdd-44/apply_upto.py <patch>` reproduces
  `scripts/patch.py`'s order and sets `first-checkpoint`), edit the tree, then regenerate
  with `git add -A && git diff --cached first-checkpoint` inside the source dir (the patch
  creates new files, so `git diff` alone misses them). Hand-written hunks must have
  balanced leading/trailing context; dry-run with
  `patch -p1 --forward -l --binary --dry-run` (GNU patch; `gpatch` on macOS), never
  `git apply --check`. `0 FAILED` is not a placement proof: read the tree after applying.
- Never `git add -A` in the repo root. Never commit `_READY`, `camoufox-*/`, `.venv`,
  `.superpowers/`, `firefox-*.tar.xz`, `service-tester/proxies.txt`. Never print or quote
  `service-tester/proxies.txt` or any log line containing the proxy host.
- No force-push on shared branches. Commits end with
  `Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>`.
- Every number, sha, run id and file line that goes into a commit message, an issue, or
  the PR body is read back from the actual state first (CLAUDE.md lesson 6).
- Smoke verdicts obey CLAUDE.md lesson 4: a reference is a control only if it is
  guaranteed to differ from the value under test. Every new or repaired arm states, in a
  comment above it, what would produce its GREEN wrongly and how the arm rules that out.
- `CamouIsFontAllowed` keeps failing open on context 0 (CLAUDE.md lesson 5). Changing
  that default is a non-goal here and is stated as NOT-verified in the PR.
- Both test suites run against the final binary: `build-tester` headful
  (`DISPLAY=:0`, playwright pinned 1.55.0, `checks-bundle.js` rebuilt from source) and
  `service-tester` with `service-tester/proxies.txt` supplied by the user.

## Phase A — admin, no build

1. Comment on #81: the clear-on-install fix (`FontListManager::SetFontList` →
   `ClearCodepointsWithNoFonts`, `dom/base/FontListManager.cpp:47-55`) covers the sequence
   it was measured on and not the ordinary one. When both contexts install their lists
   before either renders, A's gated miss is written to `mCodepointsWithNoFonts`
   (`gfx/thebes/gfxPlatformFontList.cpp:1403`) after B's clear already ran, and B reads
   tofu for a codepoint its own list covers. The read-path fix lands with #82 (Phase C).
   #81 stays open until that lands and arm (i) plus the new ordering arm are green.
2. Close #89: the harness fix (`8f8503e`) is in `main`; the final #84 service-tester run
   scored 384/384 on it. Note that every earlier claim citing service-tester on a
   camoufox-152 binary remains unsupported.
3. File one issue: `SpeechVoicesManager` stores its per-context value in a process-local
   `static nsTHashMap` (`dom/base/SpeechVoicesManager.cpp:12-13`) while its one-shot
   disable flag goes through `RoverfoxStorageManager` (cross-process) — the same shape as
   #83's top hypothesis. Measurement, not fix, is the ask; link it to #83.
4. File one issue for the #80 half this PR does not fix: `FontFaceImpl::SetStatus` ignores
   `aStatus` for every face (patch `font-hijacker.patch`, `FontFaceImpl.cpp` hunk), so a
   `url()` face whose download fails still reports `loaded`. Restoring real status
   interacts with `FontFace::Status()`, `UpdateOwnerPromiseSync`, the fork's
   immediate-resolve `FontFace::Load()`, and the deleted backwards-transition guard; it
   needs its own build and its own arm.

## Phase B — measure without a rebuild

Branch edits to `.github/workflows/smoke.yml` only. Run against build artifact
`34236331658` (head `8990915`; the delta to `main` `f1b60a6` is documentation only).
Each arm below keeps the existing arm intact and adds a sibling, so the old and new
shapes are compared in one log.

### (b2r) — #83 discriminator

Same two contexts as arm (b2) (donor A alive, recipient B), with three changes:

1. `page = ctx.new_page()` **before** `ctx.add_init_script(...)`, then `page.goto(...)`,
   so the only init-script invocation runs on the final document in its final process.
2. Before scoring, assert the list landed on the document under test: read the
   `data-fl` attribute the init script writes (`smoke.yml:922-927`) after `goto`, and
   fail the arm as "setup invalid" if it is absent. Without this, a context whose
   init script never applied has no list, everything is allowed, and a false "H1 refuted"
   prints identically to a real one.
3. Sample `pgrep -af contentproc` (the block at `smoke.yml:2540-2621` already does this
   after each `goto`) once more between `new_page()` and `goto()`, for both contexts, and
   read `data-fl` at about:blank as well as after `goto`.

Verdict: leak present in (b2) and absent in (b2r) → hypothesis H1 confirmed (list
process-local, disable flag cross-process). Leak present in both → H1 refuted, H2
(`gfxFontGroup::mUserContextId == 0`) is decided by the `MOZ_LOG` line in Phase C.

### (j)/(j2) repaired — #82

Both arms currently score their own validity branch: `tofu = named['Arial']` and the
value under test both route through U+FFFD system fallback, so the floor can equal the
measurement. Repair, applied to both arms:

1. Donor A's list is exactly `["Tahoma"]` (renders U+FFFD at 46.617 in run
   `34240575679`; Verdana and Segoe UI collide at 44.533 and cannot be told apart).
   Recipient B keeps `["Arial","Calibri","Times New Roman"]`, none of which cover U+FFFD.
2. Launch with `gfx.font_rendering.fallback.async=false` so `GlobalFontFallback` cannot
   take the `StartCmapLoadingFromFamily` skip (`gfxPlatformFontList.cpp:1581-1587`).
3. Assert A's own `final == 46.617` before scoring B. If A's fallback did not land on
   Tahoma, the arm reports "setup invalid" and stops.
4. Positive identification: B's `final == 46.617` is the leak; anything else is a block.
   No "differs from a floor" comparison remains.
5. A renders first and stays open; B is created and probed afterwards; both contexts at
   the same `FontVisibility` level.
6. Assert both contexts share a content process from the pid samples; if they do not,
   report "unmeasured: different processes" rather than GREEN. Try
   `fission.autostart=false` alongside `dom.ipc.processCount=1`; #83's own measurement
   (`83.md:176`) shows the latter alone does not collapse them.

Expected before the fix: (j)/(j2) RED with B reading 46.617. That is the control the
Phase C fix is measured against.

### (k) — #80 render probe

The existing #80 evidence measures 761.33 in both launches, so only the `status` half is
established; the render half is unmeasured. Arm (k) fixes that:

1. Build a font with no bundled twin at workflow time with fontTools `fontBuilder`
   (already installed for the cmap bisect): family `CamouProbeK`, one glyph for `a` with
   advance 2000 units, unitsPerEm 1000, so a 48px string of 20 `a`s measures 1920 if and
   only if that face rendered. Embed as a `data:` URI `@font-face` with a bareword
   family name.
2. Read `document.fonts` status for the face and `measureText` width, in a context with
   a per-context list that does not contain `CamouProbeK`, and in a bare launch.
3. Expected before the fix: status `error`, width equal to the fallback (not 1920).
   Expected after: `loaded`, 1920, in both launches.

### (h') — #88 identification and MN8

1. In the mac context of arm (h), measure at 48px every family the mac bundle carries
   (enumerate from `bundle/fonts/macos` at workflow time) plus the generics, and print
   the one(s) within 0.01 of 375.70001220703125. No rebuild.
2. MN8: extend the (h) tripwire so the mac-context refusal is also checked against the
   mac context's own generic widths, the mirror of what `h_ref_clash` does on the win
   side.
3. If no family matches, #88 falls back to its method 2 (log the resolved
   `gfxFontEntry` after refusal in `LookupInSharedFaceNameList`) in the Phase C build.

### Gate

Phase C is dispatched only after the Phase B run completes and its arms are read:

- H1 confirmed → Phase C carries the #83 fix.
- H1 refuted → Phase C carries #80 and #82 only, plus a `MOZ_LOG` line in
  `CamouIsFontAllowed` (`gfxPlatformFontList.cpp:1232`, module `fontlist`, zero cost
  when disabled) printing `ctx`, `HasFontList(ctx)` and the key, and the final smoke
  runs with `MOZ_LOG=fontlist:5` so H2 is decided by the same build.

## Phase C — the fixes, one Linux + one Windows build

### #80 — `url()` faces skip the family gate

`patches/font-hijacker.patch` only. Add one public member to `FontFaceImpl`, declared
next to `GetFamilyName()` (`layout/style/FontFaceImpl.h:142`) and defined beside
`GetAttributesFromRule` in `FontFaceImpl.cpp`, where `Servo_FontFaceRule_GetSources` is
already in scope:

```cpp
// Camoufox: true when this face's bytes come from the page rather than from a
// host-installed font -- any url() source, or an ArrayBuffer face. Read from the
// descriptor block, not from mUserFontEntry, which is null on the JS FontFace
// path until the face is added to a set.
bool FontFaceImpl::CamouHasNonLocalSource() const {
  if (mSourceType == eSourceType_Buffer) {
    return true;
  }
  StyleLockedFontFaceRule* data = GetData();
  if (!data) {
    return false;  // cannot tell -> keep the gate
  }
  AutoTArray<StyleFontFaceSourceListComponent, 8> sources;
  Servo_FontFaceRule_GetSources(data, &sources);
  for (const auto& s : sources) {
    if (s.IsUrl()) {
      return true;
    }
  }
  return false;
}
```

Consult it at the three refusal sites: `FontFaceImpl::SetStatus`, `FontFace::Status()`
(`FontFace.cpp:277`) and `FontFace::Load()` (`FontFace.cpp:304`), short-circuiting the
family gate when it returns true. Test `IsUrl()`, not `!IsLocal()`: the source list
interleaves format-hint and tech-flag components. The `local()` refusal in
`gfxUserFontSet.cpp:460-483` is untouched, so a mixed `src: local(X), url(Y)` rule still
cannot reach a host font; it will, however, report `loaded` for a family the context's
list excludes — stated in the PR. `SetStatus` keeps discarding `aStatus` (Phase A item 4).

### #82 and the #81 generalisation — read-path gating

`patches/font-list-spoofing.patch`, `gfx/thebes/gfxPlatformFontList.cpp`, inside
`SystemFindFontForChar`:

1. In the `aCh == 0xFFFD` block (`:1328-1348`), before returning the cached
   `mReplacementCharFallbackFamily[level]`, build the cached family's key — shared:
   `GenerateFontListKey(fallbackFamily.mShared->Key().AsString(SharedFontList()), key)`,
   unshared: `GenerateFontListKey(fallbackFamily.mUnshared->Name(), key)` — and ask
   `CamouIsFontAllowed(key)`. On refusal fall through to the slow path
   (`CommonFontFallback` / `GlobalFontFallback`, already gated at `:1486`, `:1578`,
   `:1617`). The cache is kept, not cleared.
2. Negative cache: when the current context has a per-context list
   (`FontListManager::HasFontList(ctx)`), do not honour a `mCodepointsWithNoFonts` hit
   in `SkipFontFallbackForChar` and do not record a miss at `:1403`. The process-wide
   negative cache stays authoritative for contexts without a list. The #81
   clear-on-install stays in place; it is harmless and covers the pre-list case.

Both changes inherit the context-0 fail-open.

### #83 — list stored cross-process (only if H1 confirmed)

`patches/font-list-spoofing.patch`, `dom/base/FontListManager.cpp/.h`:

1. `SetFontList(aId, list)` writes the list through
   `RoverfoxStorageManager::PutString(key, joinedList)` the way
   `WebGLParamsManager.cpp:26,38` does, in addition to the process-local parsed set.
2. `HasFontList(aId)` / `IsFontAllowed(aId, key)` consult the process-local set first;
   on a miss they read the cross-process string, parse it once into the local set under
   `sFontListMutex`, and answer from that. A process that never ran `SetFontList` for
   that id therefore still enforces the list.
3. Consequence, stated in the PR: such a process never runs the #81 clear-on-install.
   That is why the #82/#81 fix above is read-path shaped and does not depend on the
   clear.
4. Lock order: the pref read must not be taken while holding `gfxPlatformFontList::mLock`
   in the other order than the existing read paths (`mLock` → `sFontListMutex`). The
   cross-process read happens under `sFontListMutex` only.

### Patch hygiene

Regenerating `font-list-spoofing.patch` through the workspace flow removes the four
fuzz-1 hunks left by #84 for free. `window-setter-seal.patch`'s `FontListManager.cpp`
hunk offset moves again; it applies without fuzz and is noted in the PR body.

### Dispatch

`gh workflow run build.yml -f build_target=linux-x86_64` and `windows-x86_64` at the
same commit, together. The Windows artifact feeds Phase E.

## Phase D — verify

1. Final smoke on the Linux artifact. Expected: (b2), (b2r), (j), (j2), (k), (i) GREEN;
   `EXPECTED_RED` updated so no triaged red remains for #80/#82/#83; no `UNEXPECTED RED`
   line. If H1 was refuted, the `MOZ_LOG` output names `ctx=0` (H2) or something new, and
   the PR reports #83 as measured-not-fixed.
2. `build-tester` on the new binary: denominator equal to `main`'s, only the known fails.
3. `service-tester` with the user-supplied proxy: grade A, no new failed checks.

## Phase E — #87 native Windows

Runs on the user's Windows build PC against the Phase C Windows artifact. Order matters:

1. The user opens the SSH master to `buildpc` (password auth; repeated failures trip a
   lockout, so no automated retries). The session verifies `MASTER_UP` before anything
   else.
2. Check for a native Windows Python 3.11+ and Playwright 1.55.0 (`python`, `py`,
   `pip show playwright`). WSL does not count: the host-font question is about Windows
   `C:\Windows\Fonts`. If absent, install into a venv under `D:\`.
3. Probe script `build-tester/scripts/probe_windows_fonts.py` (new, standalone
   Playwright, the smoke probe body lifted out of the workflow): family-name lookup,
   codepoint fallback through U+FFFD, bare launch and a launch carrying a `fonts` key,
   and one host-installed family chosen at run time from `C:\Windows\Fonts` that is in
   neither the bundle nor the launch list. Post-flip expectation: that family is not
   reachable by content in either launch.
4. Results (run log, widths, the family chosen) go into #87 as a comment and into the PR
   body. NOT-verified stays explicit: macOS host (`package-macos: --fonts windows linux`
   means the host supplies its own), and anything not on the Windows machine's font set.

## Phase F — PR

- Title ties to #44 as "part of #44"; the WebGL half stays open; no auto-close keyword
  for #44 or #83 unless its arm is green.
- Body sections per issue, each with run id + log lines, then NOT-verified: macOS host,
  context-0 fail-open, #80 over HTTP / with a quoted family / through
  `document.fonts.add`, real load status (the new issue), and #83 if H1 was refuted.
- superpowers final review, then `gh pr merge --merge`.

## Non-goals

- Changing the context-0 fail-open default of `CamouIsFontAllowed`.
- Restoring real `FontFaceLoadStatus` for `url()` faces (new issue).
- Fixing `SpeechVoicesManager` (new issue, measurement first).
- The dormant non-shared branches (`LookupInFaceNameLists`, `CommonFontFallback` `else`)
  and `LookupLocalFont` on the macOS/Windows platform font lists.
