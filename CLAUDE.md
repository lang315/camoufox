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

Five failures from the #44 fonts work, each of which produced green CI and a
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
`FontFaceImpl::SetStatus` consults `IsFontAllowed` with no `AutoFontListContext`,
so it answers for the launch OS in every context. This was dismissed as
unreachable after checking only `FontFace::Load()` — which the fork rewrites to
resolve immediately, so it genuinely is safe. But CSS `@font-face` rules reach
`SetStatus` through `FontFaceSet::InsertRuleFontFace` during style flush, which
is *not* wrapped (only `Check` and `Add` are). Enumerate the callers before
declaring a path dead; "I checked the obvious one" is not a reachability proof.

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
"no per-context list" and falls through to the launch-level `fonts` key, which
under a launch that sets no `fonts` is empty and therefore **allows every
family**. Two separate hops of that chain have already been found failing
(`OffscreenCanvas::GetDocument()` off-main-thread, and whatever #83 turns out to
be). Fixing individual hops does not close the class: a gate that cannot
establish who is asking should deny.

**Font read paths known to be ungated** (as of the #44 review; check before
assuming a font change is complete): `SystemFindFontForChar` /
`GlobalFontFallback` / `CommonFontFallback`; `FontFaceSet::InsertRuleFontFace`;
worker + `OffscreenCanvas` (`GetDocument()` is null off-main-thread, so the
context id falls to 0); `LookupLocalFont` / `LookupInFaceNameLists` (matched by
full/PostScript name, not family key).

## Constraints when editing this repo

- The `camoufox-*/` source directory is regenerated — persist changes as patches, never as edits committed to that tree.
- Keep the `Makefile` diff clean against `main` unless a change genuinely belongs there — dependency setup lives in `scripts/install-deps.sh`, not the Makefile.
- Every PR must be tied to a GitHub issue and pass both test suites (see `CONTRIBUTING.md`).
