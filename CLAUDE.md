@AGENTS.md

## Fork notes (lang315/camoufox)

The repository rules are in `AGENTS.md`. Everything below is specific to this fork.

### Building

The build system is designed for **Linux**, and `browser/multibuild.py` cross-compiles
Windows from it. **macOS is not cross-compiled** — `.github/workflows/build.yml`
runs the macOS legs natively on `macos-26` runners, because FF150 hard-requires
the macOS 26 SDK (`mac_sdk_min_version()` is 26.5 on FF156 and FF158 (26.2 on FF152) and `widget/cocoa/nsCocoaWindow.mm`
uses `NSGlassEffectView`; a macos-15 runner fails with `use of undeclared
identifier 'NSGlassEffectView'`). That SDK is universal, so the macOS x86_64 leg
cross-compiles on the arm64 runner. `make -C browser setup-macos-sdk` downloads the SDK only
when the host is not Darwin. (`browser/scripts/install-deps.sh` covers macOS/Linux host
dependencies for local `make -C browser dir` + bootstrap experimentation.)

**Dispatch a build rather than building locally.** `gh workflow run build.yml
--repo <fork> -f build_target=macos-arm64` (targets: `full`, `linux-x86_64`,
`linux-arm64`, `windows-x86_64`, `windows-i686`, `macos-x86_64`,
`macos-arm64`) uploads `CamoufoxBuilds-<target>-<arch>` with a 14-day retention,
fetched with `gh run download <run-id> -n <name>`. Before dispatching, check
whether an existing run already covers the commit you care about: a run whose
diff against yours touches nothing the `resolve` step of `.github/workflows/tests.yml`
matches (`browser/patches/`, `browser/additions/`, `browser/settings/`,
`browser/assets/`, `browser/scripts/`, `browser/bundle/fontconfig/`,
`browser/upstream.sh`, `browser/Makefile`) is the same browser. A cold macOS leg is ~2h.

**The launchers install this fork's browser by default.** `python/src/camoufox/repos.yml` defaults to
`lang315/camoufox` alone, whose releases carry Windows and macOS packages only: on Linux the fetch
raises `MissingRelease`, by design, because a second repo in that entry would install upstream's
unpatched browser there.

**Releasing a fork build is manual.** `release.yml` runs only on `daijro/camoufox`.
Dispatch `build.yml` from `main` for each target, download the artifacts, then
`gh release create v<version>-<release>-fork.<n> --target <main sha>` with the
packages attached. `build.yml` runs only when dispatched, so creating that tag
starts no build (#203).

### Record every bug fix in `docs/bug-fixes.md`

A PR that fixes a bug adds an entry to [`docs/bug-fixes.md`](docs/bug-fixes.md) in
the same PR, newest first. The entry gives:

- the symptom as first seen;
- the root cause, with the code that causes it;
- the fix, and any alternative that was tried and failed;
- the red-to-green evidence;
- what misled the investigation.

Read the file before investigating a bug: a symptom seen before has its cause
and its traps written down there. A settled decision still goes in
`ci/tribal-rules.yml`, and the entry links to it.

### Patches: hand-written hunks

**Balance the context lines in every hunk you hand-write.** GNU `patch` (what
`browser/scripts/patch.py` shells out to) charges the *difference* between leading and trailing
context against a max-2 fuzz budget, so a hunk with 7 leading and 1 trailing context line
is REJECTED even at the exactly correct line of a pristine file. Verified with a minimal
repro: same file, same position, 7/1 fails with `Hunk #1 FAILED`, 7/7 applies cleanly.
This cost one ~1h20m build (run 33245117873, `.rej` on `gfxPlatformFontList.cpp`).

`git apply --check` is **not** a valid pre-flight here — it accepts hunks GNU patch
rejects (also verified). Dry-run with the invocation the build actually uses, from
the Firefox tree (`browser/camoufox-<version>-<release>/`):

```bash
patch -p1 --forward -l --binary --dry-run < ../patches/your.patch
```

`make -C browser workspace ./patches/x.patch` is unsafe when a LATER patch also edits that patch's files (e.g. `font-list-spoofing.patch`): it wrongly reports the patch as "not applied", moves the `first-checkpoint` tag onto the full stack, and re-applies with fuzz, duplicating hunks. Rebuild the tree at the patch's own position instead — reset to `unpatched`, apply patches 1..N in `browser/scripts/patch.py`'s order, checkpoint, then edit — and prove the baseline by regenerating the unedited patch byte-for-byte before editing (#131).

### Testing additions

- **`browser/tests/build-tester/`** — the raw binary directly, bypassing the Python package:
  eight fingerprint profiles, injected via `generate_context_fingerprint` +
  `addInitScript` and `CAMOU_CONFIG`. **This is the anti-detect suite** — run it
  when changing patches, C++, or the JS browser layer.
  ```bash
  cd browser/tests/build-tester && ./run_tests.sh /path/to/camoufox-binary
  # or, what CI runs:
  python3 -m ci.run_build_tester --binary /path/to/camoufox-bin
  ```
  build-tester runs **headful** (#195): `scripts/runner.py` refuses to start on
  Linux without a `DISPLAY`, `run_tests.sh` borrows one from `xvfb` and exits
  with an error when `xvfb-run` is missing, and CI runs it under `xvfb-run`.
  A WebGL check that finds no WebGL fails; it used to pass on "WebGL not
  available", which scored a run without a GL context as green (issue #75).
- **`browser/tests/playwright/patches/`** — one standalone guard per shipped spoofing behaviour
  (isolated evaluate, trusted events, fonts, mouse trajectories, touchscreen).
  The most direct evidence a Firefox bump did not neuter a patch that still
  *applies* cleanly.
  ```bash
  python3 -m ci.run_patch_guards --binary /path/to/camoufox-bin
  ```
- **Playwright** — upstream playwright-python, fetched fresh at the tag
  `ci/versions.py` resolves for the browser, with `ci/skiplist.yml` applied and
  `browser/tests/playwright/camoufox/` overlaid. This is the automation-contract check, not the
  stealth check. It runs **isolated-world first** (what users ship) and re-runs
  only the failures with isolation off; those are counted and named as
  main-world fallbacks rather than hidden, so the size of the isolated-world
  gap is visible per run.
  ```bash
  make -C browser tests     # or: python3 -m ci.run_playwright --binary ...
  ```
- **`smoke.yml`** — dispatch-only, never on a PR; runs against an existing build:
  `gh workflow run smoke.yml --repo <fork> -f run_id=<build run id>` (the run must
  hold `CamoufoxBuilds-linux-x86_64`). The font arms and the Playwright 1.55 video
  guard live here.
- **`browser/tests/native/`** — leaks, context lifetime, and the repo's own conventions.
- **`e2e/`** — user journeys through the package, bare Playwright and goapi,
  against local pages (`live` marker: real sites, dispatch only). Expectations
  come from quoted docs, Playwright's own Firefox, or coherence rules with a
  negative control; filed findings are in `e2e/known.py`, scoped per host.
  ```bash
  python3 -m ci.run_e2e --binary /path/to/camoufox-bin      # what CI runs
  gh workflow run e2e.yml --repo <fork> -f release=<tag>    # Linux/macOS/Windows
  gh workflow run e2e.yml --repo <fork> -f run_id=<build> -f k=fifty_contexts -f mozlog=true
  ```
  `mozlog=true` uploads a `MOZ_LOG` capture (`mozlog-<target>`) of the
  fingerprint and fifty-contexts journeys (#171). `e2e/probes/` holds one-off
  measurements, not collected by pytest: `emoji_timing.py` is #165's and
  `other_names_stall.py` is #253's. Run one by hand against a binary, or on all
  three OSes with `gh workflow run e2e.yml --repo <fork> -f run_id=<build> -f probe=other_names_stall.py`
  (a probe that takes `--zip`).
  With `run_id`, only the leg of that build's OS tests anything: the other two
  legs find no browser and pass green having tested nothing. Name them in any
  report.
- **The suites isolate the launcher cache** (TypeScript #269, Python #280) and
  fail before any test if a cache path escapes the temp root. On macOS a launched
  browser still creates an empty `~/Library/Caches/camoufox` by itself, so check
  the file count, not whether the directory exists.

## Verifying spoofing claims (learned the hard way)

Lessons from the #44 fonts work and after, most of which produced green CI and
a wrong conclusion. They generalise; read them before asserting that a spoof is
safe, complete, or unreachable.

**1. Never assert a safety bound you have not read the code for.**
The #44 union-whitelist approach was chosen on the claim "host fonts are deleted
at startup, so a missed read path can only leak *bundled* fonts — a tell with a
known ceiling." That ceiling does not exist. `browser/Makefile`'s package targets
deliberately bundle every OS *except* the target's own (`package-macos:
--fonts windows linux`), because the host supplies its own. And upstream
`ApplyWhitelist()` filters by font *name*, not by origin. So a whitelist
containing all three OSes' names keeps the **host's real fonts** alive on native
Windows and macOS. The claim was plausible, repeated in a PR body, a plan
document and a shipped docstring, and never checked against `browser/Makefile`.

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
reasons: it runs on **Linux CI**, where `browser/bundle/fontconfig/linux/fonts.conf`
excludes host fonts so the host-leak is vacuous there; and it probes by **family
name**, so it never exercises codepoint fallback (`SystemFindFontForChar` /
`GlobalFontFallback`), which no patch gates. When a spoof is host- or
platform-sensitive, a Linux-only measurement is not evidence about Windows or
macOS. State what a guard cannot see, next to what it proves.

**4. A reference is only a control if it is guaranteed to differ.**
This one cost more than the other three combined. Six times in the #44 fonts
work, and once since, an arm was scored against a reference that could equal
the value under test, and every time the result looked like a finding:

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
- The Composite revert (cd6b4c0) matched smoke's guard in page, viewport and
  duration, and ran Playwright 1.62 where the guard pins 1.55. Those versions
  take different Juggler recording paths (`Page.startScreencast` against
  `Browser.setVideoRecordingOptions`), so the "same axis" table compared two
  mechanisms, and main shipped empty videos for Playwright <=1.57 until #136.
  The client library's version is part of what a measurement is about.

The general form: **a cross-thread, cross-process, cross-world or cross-context
reference is not a control unless something establishes that the two sides are
comparable.** Before trusting a red or a green, state what would produce it
*wrongly* and show that did not happen. Three of the #44 six were caught only by
contradiction with a fact already known to be true — not by the result looking
wrong.

**5. The font gate fails open, by construction — for the per-context half.**
`gfxFontGroup` caches its user context id once in its constructor, through
`FontListManager::ContextIdFor`: provider → `GetDocument()` → the document's
principal (`RoverfoxStorageManager::UserContextId`), or, when the provider has
no document, the current worker's origin attributes — each hop failing silently
to 0. `CamouIsFontAllowed` treats context 0 as
"no per-context list" and **returns `true`, allowing every family**. It never
consults the launch-level `fonts` key: that question is answered separately by
`MaskedFontListBlocks` / `MaskConfig::IsFontAllowed`, at the sites that carry a
`FontVisibilityProvider`. So a failed context id is not caught further down —
nothing re-asks the question this gate could not answer. The class is narrower
than that reads (#105): every live lookup site asks `MaskedFontListBlocks`
*first*, and the four sites that do not (five before #150 paired the face-name
lookup) are reached only by chrome, or dormant while `gfx.e10s.font-list.shared` is true — so what a
misresolved context loses is only its own per-context list (measured on the
codepoint-fallback path, by reading the callers elsewhere). Refusal is read from
the browser's fallback and gate lines, never from pixels: a missing glyph is a
hexbox carrying its own codepoint's digits. The check that generalises: before
calling a fail-open gate a leak, enumerate every gate above it and which one
asks first — a short-circuited pair, or a caller that refuses the whole lookup,
can make the fail-open unreachable for the case you care about, and a bare "the
gate allows everything" reading will not show you either. The four sites, their
line numbers and the `(ctx105)` measurement are in
[`docs/fonts-gating.md`](docs/fonts-gating.md).

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
(beta.31 pristine `gfxFcPlatformFontList.cpp:2437`) *before*
the call reaches the base `gfxPlatformFontList::FindAndAddFamiliesLocked` where
`CamouIsFontAllowed` sits. The recon had declared "no cache above the gate"
after reading only the base class. Whichever context populated the memo first
answered for every context after it, negatives included. Fixed on
`fix/fonts-round2` (PR #93) by keying the memo and `mGenericMappings` on the
context id and flushing both from `FontListManager::SetFontList`; since #188,
every other process flushes them from `FontListManager::OnFontListStored`. When a gate
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
`python/src/camoufox/utils.py:_generate_fontconfig` does changed the premise of
four arms and one number in every table, and cost nine Phase 0 smoke runs to
re-baseline. It also introduced its own blind spot, which has to be stated with
the result: the guard pins the **Linux** conf, whose generics alias to
Tinos/Arimo/Cousine and are refused under a mac or win list, while a shipped
session picks the conf by the **spoofed** OS and gets generics its list allows.
The rule: before a font measurement is evidence, say which font universe it was
taken in, and check that it is the one the product ships.

**9. A log is not a measurement until you know which binary produced it.**
Three published claims in the #95/#97/#44 pass were each overturned by a single
readback, and all had one shape: the number was right and what it was *about* was
assumed. A checksum "moved under this patch" when the earlier run had consumed a
build of a different branch carrying two other PRs' browser code; a control that
showed the *probe* was comparable across runs was offered as if it showed the
*binaries* differed only by the patch; and an independence argument read as being
about a build without an unmerged patch that every run in fact carried.

- **Resolve every run id to its build, and that build's branch, before quoting it.**
- **Say which comparability a control establishes** — the probe's, or the
  binaries'. Lesson 4 says a reference must be guaranteed to differ; this is its
  other half: it must also be guaranteed to be about the same thing.
- **Grep the arms you did not change.** The highest-value finding in that review
  came out of logs already on disk.
- **Name the launcher too.** The same binary read a font universe of 318 under
  upstream's launcher and 319 under this fork's (#278): the fork's `utils.py`
  sets `font.name-list.*` prefs upstream lacks. A count compared across runs is
  about the binary *and* the launcher that configured it.

*Corollary, about guards.* In a long single-step guard, register a failing check
(`tripwires.append`, triaged at the end of the step) and never assert in place: an
inline assert decides that every arm below it is worth less than an early exit,
and on a control build it erases exactly the readings the control run exists to
capture. The shape recurs — check for it whenever adding a check.

**Font read paths: what is gated, measured, or still open.** The ledger — what
PR #84, PR #93, round 3 and #131 closed, whether by measurement or by reading,
and what is still ungated — is [`docs/fonts-gating.md`](docs/fonts-gating.md).
Read it before assuming a font change is complete. One rule from it applies to
every log: `CAMOU-FL default-unfiltered` fires only on fail-open, so **zero is
the healthy count** and a non-zero one is a finding.

## Constraints when editing this repo

- The `browser/camoufox-*/` source directory is regenerated — persist changes as patches, never as edits committed to that tree.
- Keep the `browser/Makefile` diff clean against `main` unless a change genuinely belongs there — dependency setup lives in `browser/scripts/install-deps.sh`, not the Makefile.
- Every PR must be tied to a GitHub issue and pass the full pipeline (see `CONTRIBUTING.md` and `ci/README.md`).
- `gh` here resolves to upstream `daijro/camoufox` and 403s on writes: pass
  `--repo lang315/camoufox` on every call.
- `gh run view --log` truncates long (smoke) logs with no marker; read a job with
  `gh api --allow-escape-sequences repos/<fork>/actions/jobs/<job-id>/logs`.
- On any repo but `daijro/camoufox`, `tests.yml` always builds, never fetches.
  The browser cache is keyed on compiled inputs only (`ci/browser_inputs.py`), so a
  change that misses them, Juggler JS included, restores main's browser in ~1 min.
- NEVER poll a backgrounded job (`sleep`/`ps`/`pgrep`/`top`) — do other work or end your reply and you will be woken with its output.
