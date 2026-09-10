# Fonts round 3 — design

Branch `fix/fonts-round3` off `main` @ `c8c42ef` (PR #93 merged). One PR, one commit per issue.
Issues: #82, #87, #88, #90, #91, #92, and #94 (filed from this round's recon).
Recon: `.superpowers/sdd-fonts3/recon.md` (git-ignored; its verdicts are restated here where they bind).

## Decisions taken with the user

1. One branch, one PR, commit per issue; #90 (speech) rides the same PR because it shares `smoke.yml` and the build.
2. #92 maps a generic to a family with a static ordered table intersected with the context's list (no fontconfig spacing queries).
3. #90 is measured first; fixed in-branch only if the arm goes RED.
4. #82 closes on a RED-first control. If the PR #84 artifact cannot go RED (expected — #94 shadows the cache), one diagnostic build with the #82 read gate reverted supplies the RED, then the real build supplies the GREEN.
5. The smoke launches with `FONTCONFIG_FILE` pointing at the bundle's `fonts.conf`, the way `pythonlib/camoufox/utils.py` ships it. Every existing number is re-baselined in Phase 0 before any new arm is scored.
6. #94 (pref-font path) is fixed in this round; #82 is not measurable without it.

## What the recon established (binding facts)

- `gfxFontGroup::FindFontForChar` step 2, `WhichPrefFontSupportsChar` (`gfxTextRun.cpp:3924-4028`), walks `mLangGroupPrefFonts[lang][generic]` / `mEmojiPrefFont` with no gate. Both memos are process-global and built while the thread-local context is 0. Consumers of the memo: that function, and `gfxPlatformFontList::AddGenericFonts` (`gfxPlatformFontList.cpp:2688`). (#94)
- `gfxFontGroup::GetDefaultFont` (`gfxTextRun.cpp:2201-2320`) opens no `AutoFontListContext`; `GetDefaultFontForPlatform` therefore memoizes generics under `:0`. Its shared-list last-resort walk (`:2237-2263`) and `GetDefaultFontLocked`'s two last resorts (`gfxPlatformFontList.cpp:2966-2970`) are ungated. Callers: `GetFirstValidFont` (scoped) and `FindFontForChar`'s `fontListLength == 0` branch (unscoped). (#88)
- `gfxFcPlatformFontList::FindGenericFamilies` is gated and context-keyed; when every fontconfig candidate is refused the empty list is memoized and the group falls to the default font. DWrite and CoreText have no `FindGenericFamilies`; their generics come through the #94 memo. (#92)
- `FontListManager` (`dom/base/FontListManager.h:14-26`) exposes membership tests only. No enumeration is added: "first allowed family" is computed by walking `SharedFontList()->Families()` through the gate.
- Windows `PlatformGlobalFontFallback` re-resolves DWrite's answer through the gated `FindFamily`, so #87's codepoint arm needs no Windows-specific C++. macOS `CoreTextFontList::PlatformGlobalFontFallback` returns the system font through `FindSystemFontFamily` with no gate — recorded as NOT-verified, out of scope (no macOS host).
- #91's four couplings reproduce on the tree; `CamouHasNonLocalSource()` is visible at `FontFace.cpp:285`, `:314` and `FontFaceImpl.cpp:370` only.
- Bundle scan (all faces, all cmap subtables): U+FFFD absent from macOS `Helvetica Neue`, `Helvetica`, `Geneva`, `Courier`, `Avenir Next`, `Times`; present in `Menlo`, `Lucida Grande`. Windows: absent from `Arial`, `Calibri`, `Consolas`, `Courier New`, `Times New Roman`; present in `Segoe UI`, `Tahoma`, `Verdana`. DejaVu is in no bundle.
- The smoke today launches the raw binary without `FONTCONFIG_FILE`, so the runner's host fonts are in every measurement.

## A. C++ (all in `patches/font-list-spoofing.patch` unless stated)

### A1. #94 — pref-font path
- `gfxPlatformFontList::GetPrefFontsLangGroupLocked`: wrap the population (`ResolveGenericFontNames` / `GetFontFamiliesFromGenericFamilies`) in `AutoFontListContext ctx(0)` so the memo is always the unfiltered-by-context set. The launch mask still applies through the provider, which is process-wide anyway.
- Both consumers filter at read with the calling group's context: `gfxFontGroup::WhichPrefFontSupportsChar` skips a family unless `CamouIsFontAllowed(key)` under `AutoFontListContext(mUserContextId)`; `gfxPlatformFontList::AddGenericFonts` does the same under the thread-local context its caller (`EnsureFontList`) already opened. Same for `mEmojiPrefFont`.
- New log `CAMOU-FL pref-fallback ctx=%u key=%s allowed=%d` at the read filter.
- Context 0 stays fail-open (lesson 5). Out of scope.

### A2. #88 + #92 — default font and generics, one mechanism
- `gfxFontGroup::GetDefaultFont` opens `AutoFontListContext ctx(mUserContextId)` at entry so everything below it (`GetDefaultFontForPlatform`, the fontconfig generic loop) resolves and memoizes under the group's context.
- A base-class helper `gfxPlatformFontList::CamouGenericCandidate(StyleGenericFontFamily, nsACString& aKeyOut)`: for a context with a list, walk the static table for the generic and return the first name `CamouIsFontAllowed` accepts; if none, walk `SharedFontList()->Families()` and return the first family key the gate accepts; return false when the context has no list (ctx 0 or no list installed) so callers keep upstream behaviour. Table (ordered, OS-agnostic; the intersection with the context's list is what makes it OS-correct):
  - monospace: `Menlo, Monaco, Consolas, Courier New, Courier, Cousine, Liberation Mono, DejaVu Sans Mono, Noto Sans Mono`
  - sans-serif, cursive, fantasy, system-ui, none: `Helvetica Neue, Helvetica, Segoe UI, Arial, Arimo, Liberation Sans, DejaVu Sans, Noto Sans`
  - serif: `Times, Times New Roman, Georgia, Tinos, Liberation Serif, DejaVu Serif, Noto Serif`
- `gfxFcPlatformFontList::FindGenericFamilies`: when the fontconfig loop produced an empty `PrefFontList` and `CamouGenericCandidate` returns a key, resolve that key through the gated `FindAndAddFamiliesLocked` and memoize the result instead of the empty list. (#92)
- `gfxPlatformFontList::GetDefaultFontLocked`: before the two ungated last resorts, try `CamouGenericCandidate(SansSerif)`; the last resorts themselves become "first family the gate accepts" walks. `gfxFontGroup::GetDefaultFont`'s shared-list walk skips families the gate refuses. (#88)
- The `CAMOU-FL default` line stays; add `CAMOU-FL generic-map ctx=%u generic=%d key=%s` where the table answers.
- Windows/macOS generics are covered by A1 (the memo filter), not by A2's fontconfig branch; the `GetDefaultFontLocked` change is platform-neutral. Their behaviour is measured only where a native arm runs (#87, Windows).

### A3. #91 — real `FontFaceLoadStatus` for non-local faces (`patches/font-hijacker.patch`)
- `FontFaceImpl::SetStatus`: if `CamouHasNonLocalSource()`, run the upstream body verbatim (equal early-out, backwards-transition guard, `mStatus = aStatus`, notifications, `UpdateOwnerPromise()`); otherwise the current gated body.
- `FontFace::Status()`: for a non-local face return `mImpl->Status()`; otherwise the current gated computation.
- `FontFace::Load()`: for a non-local face run the upstream body (`mImpl->Load()`, `UpdateOwnerKeepAlive()`, return `mLoaded`) so the real load happens and the promise resolves or rejects from `mStatus`; otherwise the current body.
- `FontFaceImpl::Load` / `CreateUserFontEntry` / `DoLoad` regain their caller through that path; no other change.

### A4. #90 — only if RED (`patches/speech-voices-spoofing.patch`)
- Replace `sVoicesMap` with `RoverfoxStorageManager::PutString(VoicesKeyForUserContext(id), joined list)` / `GetString`, the shape `WebGLParamsManager` uses; `HasVoices` becomes a `GetString` success test. Keep the WebIDL one-shot flag as is.

### A5. #82 — no new code. The read gate landed in #93. This round supplies the measurement (B4) and, if needed, the diagnostic revert (B6).

## B. Guard (`.github/workflows/smoke.yml`)

Phase 0 is workflow-only and runs against Linux build `34432908522` (@`163ee25`, identical patches to `main`) and the PR #84 artifact `34236331658` (@`8990915`, pre-#93). Phase 1 runs against the round-3 build.

### B0. Launch and triage
- Every launch sets `FONTCONFIG_FILE` to a `fonts.conf` generated the way `pythonlib/camoufox/utils.py:_generate_fontconfig` does it (bundle `fonts/` dir, cwd prefix resolved to the extracted artifact). First Phase 0 run re-baselines every existing numeric expectation; a second run adds the new arms.
- Fix the triage routing: an arm whose setup is invalid must report `SETUP-INVALID` (fails the step), never fall into `KNOWN_UNMEASURABLE`. `KNOWN_UNMEASURABLE` is reserved for arms whose entry in that table names the run that established the structural reason.
- New log kinds `pref-fallback` and `generic-map` join the per-kind counter table.

### B1. #94 arm — RED-first
Mac context (list excludes every fontconfig/pref family); CSS stack names one allowed family that lacks the codepoint under test; the codepoint is chosen so the only families covering it in the bundle are outside the mac list. RED = width equals that outside family's width measured by name in a bare context, and no `pref-fallback ... allowed=0` line; GREEN = width equals the tofu floor of the stack's first font (a PUA codepoint in the same stack) or a listed family, and the log carries `pref-fallback ctx=N key=<outside family> allowed=0`.

### B2. #92 arm — equal-width
Same mac context: `monospace` on `iiiii` and `mmmmm` must be equal (within 0.01); `sans-serif` on the same strings must differ (control — without it the arm is vacuous). Also print all three generics' widths and the `generic-map` lines. RED today (`monospace` is proportional). GREEN needs the `generic-map` line to name a family in the mac list and the width to match that family named directly.

### B3. #88 predicate
Extend arm (h): after `facename ... key=segoe ui allowed=0`, the following `default ctx=6 family=X` must name a family in the mac list, and arm (h)'s width must equal `X` named directly in the same context. RED today (X = host/bundle default).

### B4. #82 fixture
Donor context list `[Helvetica Neue, Menlo]`; victim list `[Helvetica Neue, Geneva]`; both stacks `"Helvetica Neue"` only (no generic in the stack; the appended generic maps to Helvetica Neue under A2). Donor renders U+FFFD first in one page, victim in a new page, same process (assert content pid). Preconditions read from the log: donor `sys-fallback ctx=D ch=U+FFFD resolved=Menlo` (cache populated); victim `fffd-cache ctx=V key=menlo hit=1 allowed=0`. Width verdict: victim width must equal victim's own tofu floor (PUA codepoint) and must differ from Menlo's U+FFFD width measured by name in a bare context. RED = victim width equals the Menlo width (leak). On the pre-#93 artifact the arm is expected to report the exit that answered instead (no `fffd-cache` line, width = a pref family); that report is the B6 trigger. If instead the donor's pref path answers with Menlo (`pref-fallback ctx=D key=menlo allowed=1`, no `sys-fallback` line), the arm reports that and the fixture moves the donor's U+FFFD family to one the pref candidates cannot reach (`Lucida Grande`); the arm never asserts on a precondition it did not observe.

### B5. #90 arm
Two contexts, different voice lists installed by the init script, `speechSynthesis.getVoices()` read after `goto()` and after `voiceschanged`; content pids sampled between `new_page()` and `goto()` (the #83 shape). DOM hand-off for every page-world value. RED = a context reads the other's list or an empty list while its pid set changed; GREEN = each reads its own.

### B6. #82 RED control (conditional)
If B4 on the #84 artifact reports "answered before the cache", a diagnostic commit reverts only the `fffd-cache` gate (the `MaskedFontListBlocks` + `CamouIsFontAllowed` check on the hit branch) on top of A1–A3, one build, one smoke: B4 must be RED with `fffd-cache ... hit=1` and the leaked width. The revert is then dropped and the real build must be GREEN. The diagnostic commit never reaches `main`.

### B7. #91 arm
CSS `@font-face` with an allowed family name and `src: url(...)` to a 404 on the smoke's HTTP server, plus a valid control font served the same way. Read `FontFace.status` from `document.fonts` after `document.fonts.ready`. RED today: 404 face reports `loaded`. GREEN: 404 face `error`, control face `loaded` and its width differs from the fallback.

### B8. #87 codepoint arm (native Windows, `build-tester/scripts/probe_windows_fonts.py`)
Add a codepoint arm: scan the host's cmaps with fontTools, pick a codepoint whose covering host families are all off the launch list and none bundled; tofu floor = a PUA codepoint in the same stack; positive control = a codepoint covered only by an in-list host family renders identically bare vs masked. Run against the Windows baseline build `34450188525` (@`c8c42ef`, pre-fix) — RED is a #94-shaped finding there — and against the round-3 Windows build.

## C. Evidence and closure

- #94, #92, #88, #91: close on the round-3 smoke GREEN for their arm with the RED from Phase 0 on the same arm.
- #82: close on B4 GREEN plus the B6 RED. If B6 cannot go RED either, #82 stays open with the reason written.
- #90: close on the measurement, with the fix only if it was RED.
- #87: close on the codepoint arm GREEN on the round-3 Windows build, with the macOS host stated as unmeasured.
- PR body under 65,536 bytes; evidence appendix as a comment from the start. CLAUDE.md "Still ungated" paragraph rewritten in the same PR; a lesson 8 only if this round produces one.

## D. Out of scope, stated
- Context 0 fail-open (lesson 5).
- macOS host measurement; `CoreTextFontList::FindSystemFontFamily`'s ungated return.
- DWrite non-shared substitution branch (dormant while `gfx.e10s.font-list.shared` is true).
- `mFontFamilies` last-resort order beyond "first allowed".
- Unbounded per-context memo growth.
