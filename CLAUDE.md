# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

Camoufox is an anti-detect fork of Firefox for web scraping and automation. This repo is **not the Firefox source** — it is a *build system* that fetches upstream Firefox, applies a stack of patches + code additions, and produces a hardened, fingerprint-spoofing browser. The distinguishing design choice is that fingerprint spoofing happens at the **C++/Juggler implementation level**, not via injected JavaScript, so it is invisible to page-side inspection.

The actual Firefox tree lives in `camoufox-<version>-<release>/` (e.g. `camoufox-150.0.2-beta.25/`), created by the build. That directory is generated — never edit it directly to make lasting changes; changes there are captured as patches (see "Making patches" below).

`upstream.sh` pins `version` / `release`, and is sourced+exported by the `Makefile`, so those variables flow into every script.

## Build commands

The build system is designed for **Linux**. Windows and macOS binaries are **cross-compiled from Linux** — they are never built natively. (`scripts/install-deps.sh` covers macOS/Linux host dependencies for local `make dir` + bootstrap experimentation; a full production build path is Linux/Docker.)

```bash
bash scripts/install-deps.sh   # install host build deps (Python ≥3.11, Rust, aria2, p7zip, go, msitools, wget, sqlite)
make dir                       # fetch Firefox source, extract, copy additions/settings, apply all patches → touches _READY
make bootstrap                 # install system deps (apt/dnf/pacman) + run `mach bootstrap` (one-time)
make build                     # ./mach build in the source dir
make run                       # run the built browser (wipes ~/.camoufox profile)
make run args="--headless https://test.com"
python3 multibuild.py --target linux windows macos --arch x86_64 arm64 i686   # full cross-platform build + package
```

`make dir` is the pipeline that matters: `setup` (fetch tarball via `aria2c` → extract → `copy-additions.sh`) → `python3 scripts/patch.py` (applies every patch, writes `mozconfig`) → `_READY`. `mach` requires **Python ≥ 3.11** (stdlib `tomllib`); older `python3` crashes with `ModuleNotFoundError: No module named 'tomllib'`.

Docker is the portable path: `docker build -t camoufox-builder .` then `docker run -v "$(pwd)/dist:/app/dist" camoufox-builder --target <os> --arch <arch>`.

Packaging: `make package-linux|package-macos|package-windows arch=<arch>` (wraps `scripts/package.py`). Launcher (Go): `make build-launcher arch=<arch> os=<os>`.

## Working with patches (the core workflow)

Almost all browser-behavior changes are `patches/*.patch` (~49 patches: `fingerprint-injection.patch`, `webgl-spoofing.patch`, `navigator-spoofing.patch`, `webrtc-ip-spoofing.patch`, the `playwright/` and `librewolf/` and `ghostery/` subdirs, etc.). Do not hand-edit patch files.

Use the developer UI instead:

```bash
make edits          # launches scripts/developer.py — apply/undo/create/manage patches
```

- **New patch:** in the UI "Reset workspace" → edit files in `camoufox-*/` → `make build` / `make run` to test → "Write workspace to patch".
- **Edit existing patch:** "Edit a patch" (resets workspace to that patch's state) → edit → "Write workspace to patch" to overwrite.

**Balance the context lines in every hunk you hand-write.** GNU `patch` (what
`scripts/patch.py` shells out to) charges the *difference* between leading and trailing
context against a max-2 fuzz budget, so a hunk with 7 leading and 1 trailing context line
is REJECTED even at the exactly correct line of a pristine file. Verified with a minimal
repro: same file, same position, 7/1 fails with `Hunk #1 FAILED`, 7/7 applies cleanly.
This cost one ~1h20m build (run 33245117873, `.rej` on `gfxPlatformFontList.cpp`).

`git apply --check` is **not** a valid pre-flight here — it accepts hunks GNU patch
rejects (also verified). Dry-run with the invocation the build actually uses:

```bash
patch -p1 --forward -l --binary --dry-run < patches/your.patch
```

Note also that several patches on `main` carry pre-existing off-by-one hunk headers in
their LAST hunk (`webgl-spoofing`, `font-hijacker`, `font-list-spoofing`). They apply
fine and are not yours to fix; just don't add a new one.

Low-level equivalents: `make patch ./patches/x.patch`, `make unpatch ./patches/x.patch`, `make workspace ./patches/x.patch`, `make revert` (reset to `unpatched` tag), `make diff` (diff against `first-checkpoint`). The source dir is a git repo with `unpatched` / `first-checkpoint` / `checkpoint` tags used by these targets.

## Repository layout (the parts that require cross-file understanding)

- **`patches/`** — the diffs applied to Firefox source. This is where browser behavior is changed.
- **`additions/`** — whole files copied *into* the source tree (not diffs) by `scripts/copy-additions.sh`:
  - `additions/camoucfg/` — the C++ config layer. `MaskConfig.hpp` reads the spoofing config (from `CAMOU_CONFIG` env var / `camoufox.cfg`) that the patches consult at the C++ level; `MouseTrajectories.hpp` is the human-cursor algorithm.
  - `additions/juggler/` — Camoufox's patched **Juggler** (Firefox's Playwright automation protocol, the Firefox analog of CDP). This is where Playwright is made undetectable — the page agent runs in an isolated scope so injected automation JS is not visible to the page.
- **`settings/`** — `camoufox.cfg`, `chrome.css`, `properties.json`, `camoucfg.jvv`, prefs/policies. Copied into the source's `lw/` dir by `copy-additions.sh`. Edit the built config with `make edit-cfg`.
- **`scripts/`** — `patch.py` (the patcher, LibreWolf-derived), `developer.py` (the `make edits` UI), `package.py`, `copy-additions.sh`, `install-deps.sh`.
- **`pythonlib/`** — the `camoufox` PyPI package: the Playwright-compatible Python interface that generates + injects fingerprints via BrowserForge and launches the binary. `fingerprint-presets-v150.json` holds real scraped fingerprints. This is the user-facing API; the browser binary is the backend.
- **`jsonvv/`** — JSON-with-validation format library used for `camoucfg.jvv` (config schema).
- **`legacy/launcher/`** — Go launcher binary.
- **`assets/`** — `base.mozconfig` and other build inputs.

## Testing

Two suites, **both required for PRs** (they cover different layers):

- **`build-tester/`** — tests the raw binary directly (bypasses the Python package); fingerprints injected via `generate_context_fingerprint` + `addInitScript` and `CAMOU_CONFIG`. Run when changing patches / C++ / JS browser layer:
  ```bash
  cd build-tester && ./run_tests.sh /path/to/camoufox-binary
  ```
  `run_tests.sh` installs deps and runs **headful** (under `xvfb` when there is no
  display). Headless Firefox has no GL context and the WebGL checks fail *open* —
  `passed: true` on "WebGL not available" — so a headless run scores 5 checks for
  free and drops 12 more from the denominator (issue #75). Calling
  `python scripts/run_tests.py` directly needs a `DISPLAY`; it now refuses rather
  than silently launching a run that verifies nothing.
- **`service-tester/`** — tests the Python package / service layer.
- **`tests/`** — Playwright tests, run via `make tests` (add `headful=true` for headful): points at `camoufox-*/obj-*/dist/bin/camoufox-bin`.

`ccache` is enabled in the build config — install it for fast incremental rebuilds (cold ~40 min, incremental ~5 min).

## Verifying spoofing claims (learned the hard way)

Seven failures from the #44 fonts work, each of which produced green CI and a
wrong conclusion. They generalise; read them before asserting that a spoof is
safe, complete, or unreachable.

**1. Never assert a safety bound you have not read the code for.**
The #44 union-whitelist approach was chosen on the claim "host fonts are deleted
at startup, so a missed read path can only leak *bundled* fonts — a tell with a
known ceiling." That ceiling does not exist. `Makefile`'s package targets
deliberately bundle every OS *except* the target's own (`package-macos:
--fonts windows linux`), because the host supplies its own. And upstream
`ApplyWhitelist()` filters by font *name*, not by origin. So a whitelist
containing all three OSes' names keeps the **host's real fonts** alive on native
Windows and macOS. The claim was plausible, repeated in a PR body, a plan
document and a shipped docstring, and never checked against `Makefile`.

**2. "Unreachable" is a claim about ALL paths, not the one you looked at.**
`FontFaceImpl::SetStatus` consults `IsFontAllowed` with no `AutoFontListContext`
of its own. This was dismissed as unreachable after checking only
`FontFace::Load()` — which the fork rewrites to resolve immediately, so it
genuinely is safe. But CSS `@font-face` rules reach `SetStatus` through
`FontFaceSet::InsertRuleFontFace` during style flush, which is *not* wrapped.
On the beta.31 tree exactly two entry points carry an `AutoFontListContext`:
`FontFaceSet::Load` (`layout/style/FontFaceSet.cpp:137`, scope at `:152`) and
`FontFaceSet::Check` (`:182`, scope at `:195`). `FontFaceSet::Add` (`:250`) and
`FontFaceSet::InsertRuleFontFace` (`:391`) carry none, so whatever context the
CSS-rule path answers in, it is covered by measurement and not by a scope.
Enumerate the callers before declaring a path dead; "I checked the obvious one"
is not a reachability proof.

**3. A guard only answers the question it was asked.**
The #44 guard was genuinely well built — real tripwires, verified it could go
red, 16/16 green. It still could not see either bug above, for two structural
reasons: it runs on **Linux CI**, where `bundle/fontconfig/linux/fonts.conf`
excludes host fonts so the host-leak is vacuous there; and it probes by **family
name**, so it never exercises codepoint fallback (`SystemFindFontForChar` /
`GlobalFontFallback`), which no patch gates. When a spoof is host- or
platform-sensitive, a Linux-only measurement is not evidence about Windows or
macOS. State what a guard cannot see, next to what it proves.

**4. A reference is only a control if it is guaranteed to differ.**
This one cost more than the other three combined. Six times in the #44 fonts
work an arm was scored against a reference that could equal the value under
test, and every time the result looked like a finding:

- CSS `@font-face` compared against `document.fonts` keyed by bare family name,
  while `FontFace.family` serialises *with* quotes, so every face read `error`.
- Two CJK faces were assumed to have different advances; both are full-width, so
  the widths agreed no matter which font resolved.
- A context's own `monospace`/`sans-serif` refs were used as the "nothing
  rendered" floor for U+FFFD — but those generics resolve *within* that
  context's allowed list, which covers U+FFFD, so a correct resolution read as
  tofu. Three investigations were declared invalid on that.
- A worker's font widths were compared against a main-thread baseline. Cross
  thread, and `GetDefaultGeneric` special-cases workers, so a false red would
  have printed identically to a real one.
- A `window.__x` global set by an init script was read back with
  `page.evaluate()`, which runs in an **isolated world** — the fork's own core
  feature, guarded by the first step of the same workflow. It reported "absent"
  for every context including the first of a fresh launch.
- The same instrumentation, once fixed, read the **second** init-script
  invocation. Playwright runs init scripts on every navigation and `new_page()`
  lands on `about:blank` first, so a one-shot setter is already consumed by the
  time the probe navigates. That produced, and I published, a false conclusion
  that the entire per-context mechanism had never run.

The general form: **a cross-thread, cross-process, cross-world or cross-context
reference is not a control unless something establishes that the two sides are
comparable.** Before trusting a red or a green, state what would produce it
*wrongly* and show that did not happen. Three of the six were caught only by
contradiction with a fact already known to be true — not by the result looking
wrong.

**5. The font gate fails open, by construction.**
`gfxFontGroup` caches its user context id once in its constructor, through
`mFontVisibilityProvider->GetDocument()` → inner window → `BrowsingContext` —
four hops, each failing silently to 0. `CamouIsFontAllowed` treats context 0 as
"no per-context list" and **returns `true`, allowing every family**. It never
consults the launch-level `fonts` key: that question is answered separately by
`MaskedFontListBlocks` / `MaskConfig::IsFontAllowed`, at the sites that carry a
`FontVisibilityProvider`. So a failed context id is not caught further down —
nothing re-asks the question this gate could not answer. Two separate hops of
that chain have already been found failing
(`OffscreenCanvas::GetDocument()` off-main-thread, and whatever #83 turns out to
be). Fixing individual hops does not close the class: a gate that cannot
establish who is asking should deny.

**6. Read the state back before you name it.**
Three times in one day of the #44 work, a specific detail was asserted without
reading it: a commit sha quoted from memory that existed nowhere in the repo
(twice), a claim that a file "no longer appears" in rehearsal output that had
been truncated with `tail` before the filename lines, and a duplicate 90-minute
build dispatched because a subagent's idle notification was read as "has not
acted" instead of checking the run list. None changed a conclusion, but two went
into commit messages on a pushed branch and one wasted a build.

The cost here is asymmetric: reading back a sha, an output tail, or a run list
takes seconds, and this repo's feedback loops are 40-95 minutes. Anything that
goes into a commit message, an issue, or a PR body is a claim someone will act
on later — check it against the actual state rather than against what you
remember doing.

**7. A platform subclass can answer above the base-class gate.**
The #83 leak (one context rendering another context's allow/deny pattern) was
`gfxFcPlatformFontList::mFcSubstituteCache`: a process-global memo of family
name → resolved family, consulted in its `FindAndAddFamiliesLocked` override
(pristine `gfxFcPlatformFontList.cpp:2437`) *before*
the call reaches the base `gfxPlatformFontList::FindAndAddFamiliesLocked` where
`CamouIsFontAllowed` sits. The recon had declared "no cache above the gate"
after reading only the base class. Whichever context populated the memo first
answered for every context after it, negatives included. Fixed on
`fix/fonts-round2` (PR #93) by keying the memo and `mGenericMappings` on the
context id and flushing both from `FontListManager::SetFontList`. When a gate
lives in a base class, grep every platform subclass (`gfxFcPlatformFontList`,
`gfxDWriteFontList`, `gfxMacPlatformFontList`) for an early return on the same
lookup before calling the gate complete.

**8. Measure the font universe that ships, not the one the runner has.**
For two rounds the smoke guard launched with the GitHub runner's own fontconfig,
so every font measurement was taken in a universe that also held Ubuntu's host
fonts — one no Camoufox ships. Four published findings came out of that. The unidentified face
in #88, `375.70001220703125` px, and #92's monospace-on-a-proportional-face are
both DejaVu Sans, a host font; so is the U+FFFD width `49.2166` in run
34431222344. And bundled `Geneva.ttf` passed arm (b) twice: confined to the
bundle it measures exactly the absent-family reference (width 1333, pixel
checksum 2482840822) and does not render at all, so the two greens were the
wrong answer — that is #95. Setting `FONTCONFIG_FILE` the way
`pythonlib/camoufox/utils.py:_generate_fontconfig` does changed the premise of
four arms and one number in every table, and cost nine Phase 0 smoke runs to
re-baseline. It also introduced its own blind spot, which has to be stated with
the result: the guard pins the **Linux** conf, whose generics alias to
Tinos/Arimo/Cousine and are refused under a mac or win list, while a shipped
session picks the conf by the **spoofed** OS and gets generics its list allows.
The rule: before a font measurement is evidence, say which font universe it was
taken in, and check that it is the one the product ships.

**9. A log is not a measurement until you know which binary produced it.**
The #95/#97/#44 pass published three claims that a single readback overturned,
and all three had the same shape: a number was correct, and what it was a
number *about* was assumed.

- **The "absent reference moved" finding was not this patch's.** An earlier
  revision of PR #98's body reported the probe's absent-family checksum moving
  `2482840822 → 1610098690` and offered a mechanism for it. The earlier figure
  came from run 34477369394, which consumed build **34432908522** — a build of
  #93's own branch at `163ee251`, already carrying all of #93's patch work. PR
  #96 landed between that build and this branch's base and changed fallback
  gating (`font-hijacker.patch`, `font-list-spoofing.patch`), and the branch adds
  #95 on top, so the delta was two PRs of browser code presented as one patch's.
  A proper control (`main` build 34658266360 vs the branch build 34578327006,
  both smoke runs on the same smoke.yml commit) reads `1610098690` on **both**.
  The reference does not move under *this* patch — #96 is what moved it — and
  the mechanism offered was an explanation invented for a movement this patch
  never caused, which is exactly how several lessons above were earned.
- **The stated control did not control what the sentence needed.** The defence
  offered was that `helvetica_neue` read `2304685864` in both runs. That is a
  real control and it is not nothing — it shows the **probe** is comparable
  across the two runs. It says nothing about whether the two **binaries** differ
  only by the patch under test. Lesson 4 says a reference must be guaranteed to
  differ; this is its other half: a reference must also be guaranteed to be
  *about the same thing*. State which of the two a control establishes.
- **All four #44 runs ran on a build carrying an unmerged patch.** PR #100's
  independence argument read as a forward-looking hypothetical about a build
  without #95 when every run already had it (`gh run download "34578327006"`,
  branch `fix/95-cmap-unicode-ucs4`). The argument survived on its merits, but
  it rested on an implied provenance that was false.

Two standing steps, both cheap, both of which would have caught all three before
they reached a PR body: **resolve every run id to its build, and that build's
branch**, before quoting the run; and **grep the arms you did not change**, since
the highest-value finding in that review came out of logs already sitting on disk.

*Corollary to 9, about guards.* The fix for "this arm has no assert" was an
inline `assert` placed where the values were computed (`a9f1682`) — 4319 lines
above arm j2 in the same step. On the control build it **would have** raised
before j2 could report, erasing j2's U+FFFD global-fallback reading — the one
thing a control run against a patch-less build exists to capture. That is a
deduction from the code (`geneva == absent` on that build, so `_dead` is
non-empty), not an observation: the only run ever dispatched on `a9f1682`,
34665048721, was cancelled at step 4 once the layout was checked, and the assert
never executed in CI. It is the same defect the #44 headline arm had been fixed
for **earlier in the same batch** (`3c49ff7`, "let the known-red #44 arm report
without erasing the run"). In a long single-step guard, a failing check must be
*registered* (`tripwires.append`, triaged at the end of the step) and never
asserted in place; an assert mid-step is a decision that every arm below it is
worth less than an early exit. The deferred form is **measured**, not reasoned:
on run 34665134880 j2 reported, then `(cmap95)` was triaged `UNEXPECTED RED`,
and the step still went red. The shape recurs — check for it whenever adding a
check.

**Font read paths known to be ungated** (as of the #44 review; check before
assuming a font change is complete): `SystemFindFontForChar` /
`GlobalFontFallback` / `CommonFontFallback`; `FontFaceSet::InsertRuleFontFace`;
worker + `OffscreenCanvas` (`GetDocument()` is null off-main-thread, so the
context id falls to 0); `LookupLocalFont` / `LookupInFaceNameLists` (matched by
full/PostScript name, not family key).

`fix/44-fonts-h2` (PR #84) closed four of those entries: codepoint fallback
through `CommonFontFallback` and `GlobalFontFallback`, which
`SystemFindFontForChar` reaches — smoke arm (f); the CSS `@font-face` path,
gated in `FontFaceImpl::SetStatus`, which `FontFaceSet::InsertRuleFontFace`
reaches during style flush — arm (e); the worker and `OffscreenCanvas` context
id, given a real value from `WorkerPrivate` — arm (g); and face-name lookup
through `LookupInSharedFaceNameList` — arm (h).

The `@font-face` entry is closed **in the shape arm (e) measures**, not by a
scope — `InsertRuleFontFace` still carries no `AutoFontListContext`, per lesson
2 above. What backs it is smoke run 34213805428, where the same three CSS rules
got opposite per-context `FontFace.status` answers: the mac context reported
`Segoe UI` error and `Helvetica Neue` loaded, the win context the reverse, both
matching arm (b)'s per-context ground truth. The arm's own discriminator in that
run named the defect a quoted family key rather than a missing context scope.
Treat any different shape as unmeasured.

PR #93 gated the two fallback caches by reading — `mCodepointsWithNoFonts` per
context, and the U+FFFD `mReplacementCharFallbackFamily` hit — and removed the
`@font-face` gate for faces that carry a `url()` source (#80).

Round 3 (`fix/fonts-round3`) closed four more, and the distinction between
"gated and measured" and "gated by reading" matters for each:

- **The pref-font memo read path (#94).** `GetPrefFontsLangGroupLocked`
  populates under `AutoFontListContext ctx(0)`, so the memo's per-context
  contents no longer depend on who missed first; the launch mask still applies
  at population. Both consumers filter at read.
  `WhichPrefFontSupportsChar` is **measured** on Linux (smoke arm (n1), run
  34544934746: the probe moves from Tinos's own 33 to its own floor 43 with
  `pref-fallback ctx=6 key=tinos allowed=0`). `AddGenericFonts`' half is
  **gated by reading only** — on the runner it is reached for `system-ui` and
  `x-math` alone.
- **Generic family to family map under a per-context list (#92).**
  `CamouGenericCandidate` resolves an ordered table intersected with the
  context's list, consulted by `FindGenericFamilies` before the fontconfig loop
  and by `AddGenericFonts` on the DWrite/CoreText path. **Measured** on Linux
  (arm (n2): 215/215/215 becomes 215/305/280 with one `generic-map` line per
  generic). `system-ui` (`generic=7`) is asked for in **no** run of that round,
  so that row is unmeasured, and a generic under a list now yields one family
  where upstream gave up to three.
- **`gfxFontGroup::GetDefaultFont`'s scope and shared-list walk, plus
  `GetDefaultFontLocked`'s two last resorts (#88).** What is **measured** is
  that a refusing context never reaches `GetDefaultFont` at all (arm (h3), shape
  B: no `default` line for the context, `generic-map` naming three in-list
  families). The gated walks themselves are **reasoned from the code**:
  `default` and `default-unfiltered` both read 0 run-wide.
- **`FontFaceLoadStatus` for non-local faces (#91).** **Measured**, three
  observables: the 404 face goes `loaded` to `error`, the control stays `loaded`
  at 1920, and `/nope.ttf` joins the fetched-path list.

Every gate-approved last-resort walk now has an **unfiltered tail**: if the walk
finds nothing it returns the unfiltered family upstream would have returned and
logs `CAMOU-FL default-unfiltered`. That line therefore fires only on fail-open,
so **zero is the healthy count** and a non-zero one is a finding. The tail is
deliberate: a gate that finds nothing must not turn `family.IsNull()` into a
release-build null dereference at `gfxTextRun.cpp:2207-2221`.
`GetFontFamilyList`'s existing unfiltered refill is the precedent.

Still ungated after round 3: `CoreTextFontList::FindSystemFontFamily`'s return
on the macOS system-font path; the DWrite non-shared substitution branch and the
non-shared `LookupInFaceNameLists` / `CommonFontFallback` `else` branches, all
dormant while `gfx.e10s.font-list.shared` is true; `LookupLocalFont` on the
macOS and Windows platform font lists, which a Linux guard cannot see; and the
**context-0 fail-open**, which no round has changed (lesson 5). The macOS host
is unmeasured entirely. #82 is closed by measurement on Linux — arm (n4) GREEN
on run 34544934746 against a RED on run 34544937587, a build differing by one
statement — but arm (j2), its bare-donor variant, is still unmeasurable on this
bundle, so it rests on one arm.

## Constraints when editing this repo

- The `camoufox-*/` source directory is regenerated — persist changes as patches, never as edits committed to that tree.
- Keep the `Makefile` diff clean against `main` unless a change genuinely belongs there — dependency setup lives in `scripts/install-deps.sh`, not the Makefile.
- Every PR must be tied to a GitHub issue and pass both test suites (see `CONTRIBUTING.md`).
