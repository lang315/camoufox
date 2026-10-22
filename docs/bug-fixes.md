# Bug fixes: what broke, why, and how the fix was proven

One entry per fixed bug, newest first. An entry records what a reader cannot get
from the diff:

- the symptom as first seen;
- the root cause, with the code that causes it;
- the fix, and any alternatives that were tried and failed;
- the red-to-green evidence;
- what misled the investigation.

The issue and the PR hold the full record. This file is the short version a
later change should read first.

## #267: the TypeScript tests used, and could wipe, the real camoufox cache on macOS

**Fixed by:** the PR that adds `typescript/tests/cache-home.ts` and `typescript/tests/isolate-cache.ts`. **Found by:** running five TypeScript test files on a Mac whose `~/Library/Caches/camoufox` held `addons/` and `Profiles/`.

**Symptom.** After the run, `addons/` and `Profiles/` were gone from the real cache, and `browsers/`, `config.json`, `repo_cache.json` and `.0.5_FLAG` had appeared in it. With only `HOME` redirected to protect the cache, the tests shared one directory and failed on each other's leftovers (`multiversion.test.ts` "removeVersion prunes empty parents and re-points the active version", and three tests in `browser-pin.test.ts`).

**Root cause.** `userCacheDir` in `typescript/src/paths.ts` reads `XDG_CACHE_HOME` on Linux only; on macOS the directory is `os.homedir()/Library/Caches/camoufox` and on Windows it comes from `LOCALAPPDATA`. `INSTALL_DIR` is computed from it once, at import. Eight test files copied the same setup (set `XDG_CACHE_HOME`, `vi.resetModules()`, import), so on a Mac they imported the real directory, and `removeIncompatibleData()` (`pkgman.ts`) deletes the whole directory when `.0.5_FLAG` is missing. `launch-host.ts` and `launch-golden.test.ts` redirected the same single variable, and the Python golden script `launch_golden.py` asserted a Linux-only path, so the golden setup could not run on a Mac at all.

**Fix.** The tests changed, not the product: `paths.ts` keeps following `platformdirs`, so the TypeScript and Python launchers still share one install directory. `cache-home.ts` has one function, `isolateCacheAt(root)`, which sets `HOME`, `USERPROFILE`, `LOCALAPPDATA` and `XDG_CACHE_HOME` under `root`, re-imports `paths.ts` and throws unless `INSTALL_DIR` is under `root`. `isolate-cache.ts` is a vitest setup file that calls it for every test file, so a file that forgets to isolate itself still cannot reach the real cache. `freshCachePerTest()` gives each test of a file an empty directory and replaces the eight copies. `launch_golden.py` redirects the same variables and reads `INSTALL_DIR` back instead of assuming a Linux path. An alternative that was rejected: making `paths.ts` honour `XDG_CACHE_HOME` on every OS, which would move real users' installs and drift from Python.

**Evidence.**
- Red, on the Mac, before the fix, with `~/Library/Caches/camoufox` empty before and after: `tests/cache-isolation.test.ts` computed the path and wrote nothing, and failed with `INSTALL_DIR is /Users/lang/Library/Caches/camoufox`.
- Green: the same file, four tests, including one that leaves a file for the next test to look for, and a negative control that makes `INSTALL_DIR` fall outside the directory and expects `isolateCacheAt` to reject.
- The whole suite on the Mac with the real `HOME`: the real cache listing was empty before and after. 589 passed, 138 skipped and 1 failed. The failure, `launch.test.ts` "every bundled macos preset launches with its own GPU" (`Apple M1` where the preset says `Intel(R) HD Graphics 400`), also fails on `main` with `HOME` redirected, so it is not caused by this change.

**What misled the investigation.** Redirecting `HOME` looked like the whole fix, and it made the cache safe but not the suite: tests that share a directory fail on each other's leftovers, so each test needs a directory of its own, not only a different one from the real cache. The tests that already redirected `XDG_CACHE_HOME` passed on Linux CI, so nothing there suggested the variable was Linux-only.

## #266: the launchers installed upstream's browser, and a fork release that reused a version could not replace another

**Fixed by:** the PR that adds the `lang315` entry to `repos.yml`, makes it the default, and makes `camoufox fetch` compare the asset's sha256. **Found by:** reading the repository list while planning how a fork install should pair with a browser.

**Symptom.** `camoufox fetch` and every launch without `executable_path` installed `daijro/camoufox`'s browser, which has none of this fork's patches. And once the default named the fork, a machine holding `v158.0-beta.33-fork.1` printed "Camoufox binaries up to date!" and never reached `fork.2`, because both ship `camoufox-158.0-beta.33-<os>.<arch>.zip`.

**Root cause.**
- `python/src/camoufox/repos.yml` set `default.browser: Official`, and `Official` is `daijro/camoufox, camoufox/camoufox`. `browser-pin.json` is not the lever: `main` carries `{}` by design (`browser_pin.py`, `test_browser_pin.py`), and `ci.release stamp` writes the real pin only in `release.yml`, which runs only on `daijro/camoufox`.
- `CamoufoxFetcher.get_asset` (`pkgman.py`) tries the next repository whenever one yields no matching asset, not only on an error. The fork publishes no Linux package, so a comma list in the fork's entry would install upstream's unpatched browser on Linux without a word.
- `CamoufoxUpdate.is_updated_needed` (`__main__.py`, and `isUpdatedNeeded` in `__main__.ts`) compared only the `version-build` string. The install folder is keyed by the asset's sha256 (`browsers/<repo>/<version>-<build>-<sha8>`), so the two fork releases land in different folders, but the decision to install never got that far.

**Fix.** The `lang315` entry names `lang315/camoufox` alone and is the default; Linux raises `MissingRelease`, which now names the repositories it looked in. `update_needed` (`pkgman.py`, `pkgman.ts`) replaces the comparison and takes the sha256 into account when both sides know it, for every repository: no fork-only branch. The entry has no browser bounds: fork releases are stable and their builds sit between the library's floor (`alpha.1`) and ceiling (`1`), which `Version.is_supported` still enforces at install. Tried and rejected: a comma list with upstream behind the fork (the Linux fallback above), and stamping `browser-pin.json` (not the lever, and `main` must keep `{}`). The rule is `launcher-default-browser-is-the-fork-alone` in `ci/tribal-rules.yml`.

What the change does not do: an installed upstream browser is kept. Installs are scoped by repository name (`browsers/official/...` against `browsers/lang315/...`), and `remove_incompatible_data()` removes the cache only when the versioned-layout flag is missing, not when the default changes. A machine whose active browser is an upstream one keeps launching it until `camoufox fetch` installs the fork's and makes it active; a launch does not update an existing install.

**Evidence.**
- Red, Python, before the change: `test_the_default_browser_is_this_forks_releases_alone`, `test_the_other_browser_sources_are_still_chosen_by_name`, `test_the_fetcher_takes_the_newest_fork_release` (mac and win), `test_linux_has_no_fork_package_and_never_falls_back_to_upstream`, `test_a_fork_release_that_reuses_the_version_and_build_still_updates`: 6 failed. Red, TypeScript: 11 failed in `fork-default-browser.test.ts`, among them Linux, where the promise resolved instead of rejecting.
- Green: the same tests, 13 Python and 12 TypeScript.
- Live, on an Apple-silicon Mac with the cache redirected to a scratch directory (`camoufox path` printed it first): `camoufox sync` listed `lang315... 11 versions`; `camoufox fetch` installed `browsers/lang315/158.0-beta.33-07328be4`, whose `version.json` holds `sha256` `07328be434daaac2e0e8b605196de539b8d106e57307b217411df7664f5af468`, the digest `gh release view v158.0-beta.33-fork.2` shows; a launch through the package with no `executable_path` ran BuildID `20261022041804`; a second `fetch` said "Camoufox binaries up to date!".
- Not run live: a machine moving from fork.1 to fork.2 (the unit tests cover the decision), and Linux and Windows.

**What misled the investigation.** The asset names suggested the two releases were indistinguishable everywhere, when the install folder already told them apart and only the up-to-date decision did not. And running the TypeScript suite on a Mac used and wiped the real cache, because `userCacheDir` ignores `XDG_CACHE_HOME` there (#267); the cache is now cleaned, and the suite ran with `HOME` pointed at a scratch directory.

## #263: under a macOS identity on a Mac, system-ui drew the default serif

**Fixed by:** the PR that adds `CamouIsNativeSystemUIName` and `CamouIsNativeSystemUIFamily` to `system-ui-font-spoofing.patch`. **Found by:** a width comparison of `system-ui` against `-apple-system` while re-checking fork.1 on a Mac. The two guards `context-os-system-font` and `system-ui-font-spoofing` had been reporting it since #188.

**Symptom.** Under `os="macos"` on a Mac, `system-ui` text drew in the default serif face while `-apple-system` on the next line drew San Francisco. Stock Firefox 158.0 on the same Mac draws both as one face (431 px for the probe string), so one width comparison told the two apart. Measured on fork.6, fork.7 and 158.0-beta.33 fork.1; by code it is in fork.1 to fork.5 as well. A launch with no `CAMOU_CONFIG` was not affected.

**Root cause.** #188 (`41b0944`) sent a native identity's `system-ui` down the pref path and filtered its family like every pref font. On a Mac that family is the hidden `.SF NS`: `LookAndFeel::GetFont(Menu)` names `-apple-system`, and `CoreTextFontList::FindAndAddFamiliesLocked` answers that name before the Camoufox mask, which is why the CSS name still drew San Francisco. No font list names `.SF NS` (`fonts.json` has 567 macOS names and `essential-fonts.json` 369, none dot-named), so `MaskedFontListBlocks` refused it in the `AddGenericFonts` pref loop: `CAMOU-FL pref-fallback ctx=6 key=.sf ns allowed=0`, then `step=system-ui key=none`. With no family, `system-ui` fell to the default serif. The same refusal happens earlier on Windows, in the name lookup in `FindAndAddFamiliesLocked`, because DirectWrite has no early answer.

**Fix.** `CamouIsNativeSystemUIName` skips both refusals at the name lookup for the name `GetSystemUIFontFamilies` gives under a native identity, and `CamouIsNativeSystemUIFamily` skips the read filter in the pref loop for the family that name resolved to. Only that family is exempt, and its `pref-fallback` line reads `allowed=1 exempt=native-system-ui`. Tried and rejected: adding `.SF NS` to the Python font lists (the hidden name varies with the macOS version and only that launcher would carry it), and exempting every `system-ui` pref family (a user-set `font.name-list.system-ui` would be exempt too). `WhichPrefFontSupportsChar` is unchanged: the family it would offer for a `system-ui` run is the one the primary lookup already tried. The rule is `native-system-ui-family-never-masked` in `ci/tribal-rules.yml`.

**Evidence.**
- Red: `test_system_ui_resolves_to_the_system_font_of_a_mac` on the fork.1 build (BuildID `20261021190420`), all three drivers: `system-ui` 391.367 with a serif fallback and 500.933 with a monospace one, `-apple-system` 431, with its negative control green. Both guards exit 1 with the new expectation (`system-ui` at the monospace baseline, `-apple-system` 624.08 at 72px).
- Green on the macOS build of the branch (BuildID `20261022041804`, run 39717616228): e2e run 39734496451, 111 passed (108 before plus the three drivers of the new test); both guards exit 0, including the mixed-OS arm (`step system-ui key=.sf ns`, `none` before). Probe: `os="macos"` 431 equal to `-apple-system` 431, `os="windows"` 425.883 as before, a launch with no `CAMOU_CONFIG` 431 as before.
- Windows, on a real Windows 10 host: stock Firefox 158.0 measures `system-ui` 425.883, equal to its `Segoe UI` row. On fork.1, the identity's own font list without `Segoe UI` makes `system-ui` fall through (391.35 and 457.6 under the two fallbacks) with no `pref-fallback` line at all: it was refused at the name lookup. On the Windows build of the branch (BuildID `20261022034911`, run 39717619720) the same list resolves `system-ui` to 425.883 with `pref-fallback ... key=segoe ui allowed=1 exempt=native-system-ui`, while the named `Segoe UI` row still falls through. `os="windows"`, `os="macos"` and a raw launch read the same as on fork.1. The e2e Windows leg on that build, run 39741085315, passed with 108 passed and 25 skipped (the new test skips off macOS). An earlier run of the same build, 39734508472, failed three tests on the reference Firefox's own `serviceworker: timeout at register` while Camoufox read `True`; that is #265, not this change.

**What misled the investigation.** "A macOS context on a Mac is native and gets no `system-ui` override" was written into #263's body and two releases' notes without a stock measurement. The two guards were read as wrong, because they expected Helvetica, when they were reporting the defect. The "bare launch" runs were `Camoufox()` with no `os=`, which draws a whole identity, not a launch with no `CAMOU_CONFIG`. And e2e and build-tester read page values and the chrome, but nothing compared `system-ui` with `-apple-system`.

## #259: on a Mac, the system UI font drew the wrong glyphs

**Fixed by:** the PR that changes `package-macos` back to `--fonts windows linux`. **Found by:** the maintainer, launching the installed fork.6 app.

**Symptom.** On a macOS host, every string in the system UI font drew wrong glyphs, mostly accented Latin letters in no meaningful order. That covered tab titles, the address bar, the urlbar popup, and page text in `system-ui` or `-apple-system`. `sans-serif`, `Helvetica` and `menu` drew correctly. It showed in two cases:
- a bare launch with a fresh profile and no `CAMOU_CONFIG`;
- a Windows identity through the Python launcher.

Affected builds: fork.6 (BuildID `20261017141913`) and fork.5 (`20261016094712`). `150.0.2-beta.25` drew correctly.

**Root cause.** Upstream #779 (6daae88) changed `package-macos` from `--fonts windows linux` to `--fonts windows macos linux`. The macOS package then carried the `M` group: 311 faces, ten of them San Francisco (`42__SFNS.ttf`, `34__SFNSItalic.ttf`, `41__SFNSMono.ttf`, ...). They are not the host's copies. The bundled `SFNS.ttf` is 7,909,644 bytes; the host's `/System/Library/Fonts/SFNS.ttf` on macOS 15.7.4 is 8,330,740.

`font-hijacker.patch` skips `ActivateBundledFonts()` only when `MaskConfig::GetSpoofedOS()` is macOS. Every other launch registers the bundle with CoreText, so the process holds a second, different SF under the system font's names, and the system UI font draws glyph ids from the wrong one. The chrome uses that font whatever the identity claims.

**Fix.** `package-macos` ships the Windows and Linux groups again: 1202 faces, `L+LM+LMW+LW+MW+W`. A macOS identity on a Mac never activates the bundle, so `M` was never read there. `browser/assets/macos.mozconfig` and `CLAUDE.md` already described the package this way. The rule is `macos-package-ships-no-macos-only-fonts` in `ci/tribal-rules.yml`, so an upstream sync cannot quietly bring the line back.

Alternative, not taken: filter the target's own OS group in `package.py`. The tribal test guards the Makefile line just as well, with no code. Changing the C++ gate needs a rebuild and does not remove the duplicate faces.

**Evidence.** All on the same Mac (arm64, macOS 15.7.4), each with a fresh profile:
- `test_the_macos_package_ships_no_macos_only_fonts` fails on `main` (`['windows', 'macos', 'linux'] == ['windows', 'linux']`) and passes after the change.
- The installed fork.6 with only `gfx.bundled-fonts.activate=0` drew correctly.
- A fork.5 copy with only the ten `*__SF*` files removed, and the bundle still on, drew correctly.
- A copy of fork.6 with the 311 `M` files removed is exactly this fix's file set (read from the pinned `fonts-bundle-v1.tar.xz`). It drew correctly both bare and under a Windows identity through the launcher. Unchanged fork.6 drew wrong glyphs in both.

The macOS arm64 package built from this branch (build run 39097137899, BuildID `20261018051233`) holds the same 1202 files. It drew correctly both bare and under a Windows identity, and its e2e run (39103040059) passed: 108 passed on macOS.

**What misled the investigation.** e2e (108 passed on macOS) and build-tester (grade A) read pages, never the chrome. Whether any of their checks draws `system-ui` text was not looked into. Two guards that read `system-ui` on a macOS host, `context-os-system-font` and `system-ui-font-spoofing`, fail on this Mac. It was tempting to blame this bug. They fail identically on the fixed file set: a macOS context on a Mac is native and gets no `system-ui` override (`('system-ui', 'none')`), while the guards expect Helvetica, as on Linux CI. That is a separate, host-dependent expectation.

## #258: the tracking panel registered a chrome package that pages can detect

**Fixed by:** the PR that deletes `browser/additions/observer/jar.mn` and the panel. **Found by:** reading the sync with upstream #847 (#256) against the observer additions.

**Symptom.** None observed in a browser. Upstream's `contentaccessible-parity.py` compares the registered chrome names of a build with a stock Firefox 156.0.1 and reports any extra one as `EXTRA vs stock -- <name> (pages can detect it)`. Camoufox registered `camoufox`.

**Root cause.** `browser/additions/observer/jar.mn` began with `% content camoufox %content/` and `0-playwright.patch` packaged `chrome/camoufox.jar` and `chrome/camoufox.manifest` in every build, whether or not `CAMOU_OBSERVE=1` was set. Content processes receive every registered chrome package, and `new Worker('chrome://camoufox/...')` returns for a registered name and throws a SecurityError for an absent one (#847, `juggler-is-not-a-chrome-package`). The only user of the package was the tracking panel, which has no button and was opened by typing its URL. No test opened it: `build-tester/observer` reads `getCollector().snapshot()` through Marionette chrome context.

**Fix.** The package, the four panel files and their unit test are deleted, along with the `camoufox` lines of `package-manifest.in` in `0-playwright.patch` and the `camoufox-observer:update` notification that only the panel listened to. The observer modules stay in `EXTRA_JS_MODULES`, so they are served from `resource://gre/modules/`, a host every Firefox registers. The rule is `additions-register-no-new-chrome-package` in `ci/tribal-rules.yml`. Alternatives, from reading the Firefox 156.0.1 sources and not run: serving the page from `resource://` does not work, because `nsChromeProtocolHandler.cpp` gives the system principal only to `chrome://` paths under `/content/` or `/skin/` and `nsResProtocolHandler.cpp` sets no owner, so the panel's `ChromeUtils` and `Services` would be undefined; a build flag keeps a second build flavor for a page nobody opens; a file in a stock package that is not contentaccessible (`mozapps`, `remote`) was not tried.

**Evidence.** `test_additions_register_no_new_chrome_package` reads every `jar.mn` under `browser/additions` and checks each `% content|locale|skin|resource` name against `browser/scripts/data/contentaccessible-manifest.json`. Before the fix it fails with `['browser/additions/observer/jar.mn: content camoufox']`; after, it passes. It reads source, so it shows the package is no longer declared, not that a built browser registers no extra name. The browser-side check is `contentaccessible-parity.py` on a build, not run for this change.

**What misled the investigation.** #847's fix and guard were written for Juggler, so the guard reads as if it closes the whole class; it only fails once a build carries the extra name. The observer's own docs say it is off by default, which is true of its data and false of its package.

## #247: a legacy font family name drew the fallback for the first seconds of a launch

**Fixed by:** the PR that adds `browser/patches/font-other-names-sync.patch`. **Found by:** explaining a width mismatch listed in #246.

**Symptom.** On the fork.4 macOS arm64 build, a Windows identity that listed `DejaVu Sans Condensed`, `DejaVu Sans Light` or `DejaVu Serif Condensed` (the `libreoffice` unit) measured them as the fallback font: 473.52 for all three, the width of a family that does not exist, under both `monospace` and `sans-serif`. A measurement a few seconds later gave the files' own advances, 468.17, 517.95 and 475.73.

**Root cause.** macOS registers these faces under their typographic family (`DejaVu Sans`, `DejaVu Serif`, name ID 16). Firefox finds the legacy name (name ID 1) through "other family names", which `gfxPlatformFontList::FindAndAddFamiliesLocked` loads lazily: the first lookup of a name whose base name exists calls `InitOtherFamilyNames(mayDefer)` with `mayDefer` true, which queues the load and returns, and the lookup answers "no such family". The name resolves once the font loader has run, 8 s after launch by default (`gfx.font_loader.delay`).

**Fix.** The lookup passes `mayDefer` false when `CamouGenericTableApplies` is true, the predicate the generic-family table already uses for "a Camoufox font list applies to this page" (the launch-level `fonts` list, or the current context's own). A masked page's first lookup reads the names at once. Chrome, and a launch with no font list, keep the stock deferral, and startup and the font loader are unchanged. `MOZ_LOG=fontinit:5` shows what the first lookup now does: `InitOtherFamilyNames without deferring took 2104.24 ms` on the parent's main thread, which is `ReadOtherFamilyNames` for every family. The first lookup took 2.17 to 2.24 s on all 8 launches here (macOS arm64), where fork.4's took 2 to 3 ms when it missed and 0.9 to 1.6 s when it blocked. `e2e/probes/other_names_stall.py` (#253), run on GitHub's hosted runners on the exact artifacts, read the first call at 1 to 3 ms (and 195 ms once) on Windows x64 (fork.5, BuildID `20261016091018`), 3 to 6 ms on Linux x86_64 (a `main` build at `28279bb`, BuildID `20261016130937`, not a release package) and 3.8 to 5.6 s on macOS arm64 (fork.5, BuildID `20261016094712`; 1.78 to 1.84 s on the maintainer's machine). The stall is a macOS effect, and the probe times the call without reading widths, so a fast first call on Linux or Windows is not evidence that the names resolved there. Why Windows has no stall is not established.

**Alternatives.** `gfx.font_loader.delay=0` also resolves the names (0 launches in 8 miss), but it is read in three places in `gfxPlatformFontList.cpp`: it starts the loader at once, lifts the loader's time limit and makes the other names synchronous. Launch took 1.7 s longer (9.13 s to 10.85 s, same binary, 8 alternating launches). By reading the code, the loader would also read every cmap at startup, which `fallback-miss-while-cmaps-load.py` needs pending; that guard was not run with the pref. The decision is in `ci/tribal-rules.yml`. Not tried: the `#ifdef XP_WIN` branch of `SharedFontList::FindFamily`, which reads only the face names of the base family (milliseconds) and returns the base family's regular face first, as Windows does, and corrects it once the loader has run. It avoids the 2.1 s stall and gives a wrong width for the first seconds; this fix gives the right one at once.

**Evidence.** `legacy-family-names-first-measure.py` launches a Windows identity whose `fonts` are the three names, measures them once, then again every 2 s until the widths stop changing, and fails if a first width differs from the settled one. On the fork.4 build (`2ab689f`, macOS arm64) it fails: the first widths are 473.52 for all three names, the settled ones 468.17, 517.95 and 475.73. On a macOS arm64 build of this branch (build run 38853342981, head `186c7e3`, whose condition is the same expression this patch now takes from `CamouGenericTableApplies`) it passes: first and settled are identical. On the Linux x86_64 build the Tests run makes from the head of the pull request it passes (see the pull request for the run). The builds differ in more than this patch (`main` moved by the font-unit rates, their script and tests, none of which is compiled into the browser).

**What the guard cannot see.** It has been seen to fail only on macOS: no build without the patch was available for Linux or Windows, so a green there says the names resolve at once, not that the guard can catch a miss. A Windows host defaults `gfx.font_loader.delay` to 60 s (`modules/libpref/init/StaticPrefList.yaml:7833` in the Firefox 156.0.1 tree), longer than the guard waits, so there a miss reads as "names never resolved" instead of a late resolution. The per-context list (`setFontList`) is not exercised on its own: a context's list is intersected with the launch-level one, which every `launch_options()` browser carries, so the launch-level arm covers the same lookup.

**What misled the investigation.** The first table in #247 measured right after launch and read a late resolution as a naming problem (name ID 1 against name ID 16), and `docs/fonts-gating.md` repeated it. `font: condensed 72px "DejaVu Sans"` measured the right width at that moment because that name needs no lazy load, which looked like a confirmation. Measuring again four seconds later in the same browser was the check that broke it. The guard's first version scored each name against the width of a name no font has, and went red on Linux without a miss: with `fonts` limited to the three names, the generics resolve to the first allowed face, so `monospace` drew `DejaVu Sans Condensed` and the "absent" reference was that face. A second arm for the per-context path never passed on any build, because the context's list was cut down to the launch-level one; it was a wrong setup, not a failure of the patch.

## #246: the Windows font units' rates had no source

**Fixed by:** the PR that adds `browser/scripts/measure-font-units.py`. **Found by:** comparing 10000 draws with 4000 fpgen Windows samples while answering #244.

**Symptom.** A Windows identity carried `HoloLens MDL2 Assets` on 59% of draws; the pinned fpgen model puts it on 29%, and on 22% to 31% in every browser subgroup (Chrome 0.31, Firefox 0.22, Edge 0.22, Opera 0.31).

**Root cause.** `font-manifests.json` gave each unit `prob` and `"measured": true` with no corpus, model or date behind it, and nothing in `browser/scripts/` computed them (`gen-font-groups.py` only copies them). The pinned model disagreed on four more: `office` 0.602 against 0.501, `web` 0.088 against 0.158, `dev` 0.038 against 0.017, `libreoffice` 0.066 against 0.075.

**Fix.** `measure-font-units.py` draws seeded Windows samples from the pinned model and writes the six units it can see, with the model's tag, into the manifest; `gen-font-groups.py` and a copy to `goapi/pkg/fingerprint/data/` follow. `ci/tests/test_font_units.py` pins the maths and fails when the manifest was measured against another model than `fpgen-model.json`'s. The first run also rewrote `cjk-tc` from 0.9 to 0.023, because its rate is conditional on `zh-TW` and the samples ignore locale; it is now skipped by `skip_reason`, with a test.

**Evidence.** The new tests failed before the script existed (5 failed or errored) and pass after (8 passed); `python/tests/test_font_distribution.py` 31 passed and `go test ./pkg/fingerprint/` ok on the new rates.

**What misled the investigation.** Counting a unit by all its fonts: `Roboto` is in `libreoffice` and `web`, so the joint rate read seven times too high until each unit was counted by the fonts only it carries. And a bundle counted by one font: `office` reads 0.626 that way, close to the old 0.602, against 0.503 at half the fonts; that may be where the old number came from, but nothing records it. Not explained by this: `hololens` reads 0.30 under any threshold, so the old 0.592 stays unexplained.

## #242: one GitHub 5xx failed a whole model or browser download

**Fixed by:** the PR that retries a transient answer in `webdl`. **Found by:** Tests run 38610977407, attempt 1, failing in setup; the same job passed when re-run.

**Symptom.** The pinned fpgen model download got an HTTP 500 from GitHub, and `python/scripts/pin-fpgen-model.py` failed the job before any test ran.

**Root cause.**
- Python `webdl` (`python/src/camoufox/pkgman.py`) made one `requests.get` and called `raise_for_status()`, so any 5xx or dropped connection ended the download.
- TypeScript `request` (`typescript/src/pkgman.ts`) retried a request that failed without a response but returned every HTTP answer, a 5xx included, to `raiseForStatus`.

**Fix.** Both retry twice, after 1 s and 2 s, on a connection error, a 429 or a 5xx, and then raise the last one. Any other 4xx is returned at once. The request is an idempotent GET of a sha256-pinned file, so a retry cannot change what is installed. `AGENTS.md` bars retrying a flaky test; a host outage is not the behaviour under test.

**Evidence.** `python/tests/test_webdl_retry.py`: 7 of 10 fail on `origin/main` (the three 4xx controls pass there), 10 pass with the fix. `typescript/tests/pkgman.test.ts`: 4 new tests fail on `origin/main`, all 34 pass with the fix.

**What misled the investigation.** Nothing. The TypeScript comment "HTTP errors are responses, never retried" stood in the way of the same fix there and was rewritten with it.

## #231: a per-context value over 4 KiB never reached other content processes

**Fixed by:** the PR that chunks oversized values in `cross-process-storage.patch`. **Found by:** `context-list-every-process.py` failing on PR #225, whose change was test-only.

**Symptom.** `FAIL flush: no content process logged CAMOU-FL flush ctx=7 with its font list live`. 1 of 13 CI runs and 1 of 15 local runs (fork.3, macOS arm64). In the failing run no content process logged any `CAMOU-FL flush`; only the parent did.

**Root cause.**
- `RoverfoxStorageManager` kept each per-context value as one `roverfox.s.<key>` pref.
- Firefox sends no string pref longer than `MAX_ADVISABLE_PREF_LENGTH` (4 KiB, `modules/libpref/Preferences.cpp:172`) to another process. `Pref::HasAdvisablySizedValues()` (`:843-860`) gates both `SerializePreferences` (`:4869`), the snapshot a new process starts with, and `Preferences::GetPreference` (`:5269`), which `ContentParent::Observe` uses for every update.
- A font list of about 280 names is over 4 KiB. In every other process the `roverfox.s.` callback never ran, so nothing flushed the font caches (`FontListManager::OnFontListStored`), updated the worker mirror (`MirrorPref`) or cleared the miss cache. A process created later had no copy in its snapshot either.
- Pages of the context still refused the probe, because `ReadValue` falls back to a sync IPC read on the main thread. A worker reads only the mirror, and a process that had missed the key before the put kept answering from its miss cache.

**Fix.**
- A value over 3 KiB is written as chunk prefs `roverfox.c.<key>.<i>`, cut on UTF-8 code point boundaries, and then `roverfox.s.<key>` as a header: `0x01`, the count, `:`, a generation. Shorter values keep the single pref.
- Only the header matches the callback. `ContentParent::Observe` (`dom/ipc/ContentParent.cpp:3920`) sends each change as an async `PreferenceUpdate` on the one PContent channel (`:3961`), or queues it and flushes the queue in order (`:1648`). So the callback runs after every chunk has arrived.
- libpref notifies only when a value changes (`Preferences.cpp:2505`). The generation makes every header new, so a second value with the same chunk count still reaches other processes.
- No stored value starts with `0x01`: numbers, `0`/`1` and the launcher's strings never do, and `StorePref` chunks any value that does. So a header cannot be mistaken for a value.
- `StorePref` and `LoadPref` are the one writer and reader: the parent's put, the IPC put, the main-thread read, the parent's IPC get, `MirrorPref` and `EnsureMirror`'s snapshot. Off the main thread reads stay mutex-only.
- Chunks a later, shorter value leaves behind are not removed. The header's count bounds every read, so they are never read.
- Rejected: a custom IPC broadcast of the value. It reaches only the processes alive at the put, so a process created later still starts without it.

**Evidence.**
- `context-list-every-process.py` now gives context A the whole Windows list from `fonts.json` (334 names, 4794 bytes) instead of a preset's draw.
- Red: against fork.3 (macOS arm64) it failed 3 of 3 runs on the flush line above, exit 1.
- Green: the PR's Tests run, which builds the Linux browser from the branch and runs the patch guards.

**What misled.** It looked like a flaky guard: it failed 1 time in 13 on CI. The only variable that tracked the failure was the length of the preset's font list: lists of 124 to 242 names passed, and the one run that drew 284 names failed.

## #183: a worker's canvas and a transferred canvas read back unnoised

**Fixed by:** the PR that gives worker and transferred canvases their context's seed in `canvas-spoofing.patch`. **Found by:** the FF156 sync review (#179), which pointed at `ImageEncoder`'s offscreen branch.

**Symptom.** On a launch the canvas placeholder does not cover (the launchers seed it), four readbacks carried no noise. A page could draw the same thing in a worker and on the page, then compare, which showed both the noise and the canvas under it. Measured on fork.3 against a launch with no seed:
- `getImageData` of a worker's `OffscreenCanvas` came back unperturbed;
- so did `readPixels` of a worker's WebGL context;
- so did `toDataURL` and `toBlob` of a canvas whose control went to a worker.

**Root cause.**
- `CanvasSeedManager::SeedFromDocument` returned 0 for a null document. A worker canvas has no document (`CanvasSeedDocumentFor` finds no owner window), and `ReadPixels` skipped the lookup without an owner document.
- A transferred canvas is read back through `OffscreenCanvasDisplayHelper`: `GetImageBuffer` for `toBlob`, and `ImageEncoder`'s offscreen branch for `toDataURL`. Both ran only Firefox's own randomisation.

**Fix.**
- `SeedFromDocument(nullptr)` on a worker thread uses the worker's user context, which is its page's (`ClientWebGLContext::GetUserContextId` already does the same). `RoverfoxStorageManager` reads are already safe off the main thread.
- `ReadPixels` asks even without an owner document.
- `MaybeRandomizePixels` adds the element's noise, except under the placeholder. `ImageEncoder`'s offscreen branch always copies, so `toDataURL` passes through it.

**Evidence.**
- `canvas-spoofing.py` arm 3: a worker's canvas must hash like the page's, and a transferred canvas's two reads must log `perturb seed=S1`.
  - On fork.3 it failed on both.
  - On this branch it passes, on Linux CI (Tests 38554469075) and on the macOS build (run 38554185647).
- A probe on the macOS build: with seed `111`, `worker_getImageData` and `main_getImageData` are both `87a6eaf0204c`, and `worker_readPixels` and `main_readPixels` are both `0131af06eef0`. Both transferred reads differ from the unseeded launch and are stable across launches with one seed.

**What misled.**
- The issue placed the gap in a worker, but `ImageEncoder`'s offscreen branch runs on the main thread, for a canvas handed to a worker. The worker's own reads were a second, separate gap.
- `toDataURL` and `toBlob` differ between launches even with no seed (Firefox's session randomisation key), so their hashes cannot show the fork's noise. The guard reads the patch's log lines for them instead.
- The arm 3 guard cannot see WebGL: headless Firefox on Linux has no GL context. `readPixels` in a worker is measured on macOS only.

## #226: the Tracking Observer recorded nothing from web pages on Firefox 156

**Fixed by:** the PR that marks the observer's window actor `safeForUntrustedWebProcess`. **Found by:** #199's covered-launch test, whose uncovered arm also failed.

**Symptom.** `browser/tests/build-tester/observer/test_observer_records.py` on `v156.0.1-beta.32-fork.3`: `observer recorded: []`, with all seven surfaces missing. The snapshot still listed the page's requests, so the parent side worked.

**Root cause.**
- The surfaces were recorded. A process script draining every content process found the page's canvas and WebGL records still in the web process's buffer.
- The page's window had no `TrackingObserverChild`, so nothing drained it. Forcing one threw `Window protocol 'TrackingObserver' doesn't match remote type 'web'`.
- Firefox 156 sets `dom.jsipc.check_safeForUntrustedWebProcess`. `JSActorProtocol::RemoteTypePrefixMatches` then refuses, in `web` and `file` processes, any actor not registered with `safeForUntrustedWebProcess: true`. `browser/additions/observer/TrackingObserver.sys.mjs` registered without it.

**Fix.** The registration sets `safeForUntrustedWebProcess: true`, as Juggler's actors already do (`browser/additions/juggler/components/Juggler.js`).

**Evidence.**
- Red on fork.3: `observer recorded: []`.
- Re-registering the actor at runtime with the flag, on the same binary, recorded `['canvas', 'webgl']` for a page that reads both.
- Green on this branch's macOS build (run 38554181799): `PASS: all 7 surfaces recorded`.

**What misled.** `REPORT.md` measured 7/7 before the Firefox 156 sync, and nothing in CI runs the observer harness, so the regression went unseen. Switching the actor's creation event from `DOMWindowCreated` to `DOMDocElementInserted` changed nothing: the actor was refused before any event could create it.

## #199: a covered launch's getImageData and readPixels went unrecorded

**Fixed by:** the PR that moves the observer record above the placeholder branch in `canvas-spoofing.patch`. **Found by:** the upstream sync review (#188).

**Symptom.** On a launch whose canvas the RFP placeholder covers, the Tracking Observer recorded no canvas read for `getImageData` and no WebGL read for `readPixels`. `toDataURL` and `toBlob` were recorded.

**Root cause.** `CanvasRenderingContext2D::GetImageDataArray` and `ClientWebGLContext::ReadPixels` take Firefox's placeholder branch before the fork's block. That block held both the perturb and `RecordSurfaceFromDocument`, so a covered read skipped the record along with the noise. #188 had already split `GetImageBuffer` this way.

**Fix.** Both functions record the read before the placeholder branch. The perturb stays off the placeholder path.

**Evidence.**
- The new covered-launch arm of `test_observer_records.py` uses `probe_readback.html`, which makes only those two reads, so a `toDataURL` record cannot stand in for them.
- On fork.3, with the #226 actor fixed at runtime: covered launch `[]`, uncovered `['canvas', 'webgl']`.
- On this branch's macOS build (run 38554181799): `observer recorded (covered launch): ['canvas', 'webgl']`.

**What misled.** The issue could not be reproduced until #226 was found: on Firefox 156 the observer recorded nothing at all, covered or not.

## #180: smoke's cross-context leak arms were green without sharing a process

**Fixed by:** the PR that moves arms (b), (b2), (b2r) and (n5) to `file:` pages. **Found by:** #179's shared-process audit.

**Symptom.** Smoke run 36884274972 (build 36837150848, Firefox 156) scored (b2), (b2r) and (n5) GREEN, while its own non-scoring audit printed `shared-process: NO` for all seven two-context pairs, e.g. `shared-process: NO  (b2)   A ['7884'] / B ['7915']`.

**Root cause.** Firefox 156 gives every `web` document the remote type `web=^userContextId=<N>` (`SharedWebRemoteType` in `dom/ipc/ProcessIsolation.cpp`), one process pool per container. These arms still loaded their pages from `data:` URLs, so `dom.ipc.processCount=1` no longer put the donor and the recipient in one process. A leak through a per-process cache (`mFcSubstituteCache`, the speech registry mirror) could not reach the recipient, so a clean recipient was guaranteed. (b2)'s re-probe gate compared `tab_pids()` before and after, which also counts processes that lay out no document.

**Fix.**
- The arms load `page_uri()` `file:` pages (the `file` remote type carries no container, `dom.ipc.processCount.file=1`) and read `docs_share_process` on both documents, as #179 did for (i), (i2), (j) and (n4).
- A pair laid out by two processes is registered as unmeasured through the arm's tripwire, after the leak verdict, so a leak seen across processes is still reported as a leak. (b2)'s re-probe half is gated on win's and the re-probe's documents sharing a process.
- The disc and pid probes use `file:` pages too and stay print-only. The audit and the dump step's `(b2)/(b2r)` slice match `/<name>.html`.
- (b2r) and (n5) check that their one-shot setter ran on the page under test. They now load a first `file:` page before adding the init script. From about:blank, the process switch spent the setter in the file process before the page under test read it.
- Arm (b) closes its donor first, and in run 38539979038 the `file` process did not outlive that, so its cross-context half is in `KNOWN_UNMEASURABLE` with run 38539979038's signature. (b2) measures the same claim with the donor alive.

**Evidence.**
- Red: run 36884274972, job 110443482493, `shared-process: NO` on (b), (b2), (b2r), (n5), disc, pid and pid2.
- First fix attempt, run 38539979038 (job 115772049528): `shared-process: yes` on (b2), (b2r), (n5), disc and pid2, and (b2) GREEN. Three arms came back unmeasured and failed the step:
  - (b): pids 6777 / 6866. The pid probe's donor-closed pair saw file process 14601 gone by the time the recipient's page loaded in 14655.
  - (b2r): `data-fl='{"saw":false,"applied":false}'` on both pages.
  - (n5): `data-sv='{"saw":false,"applied":false,"err":null}'` on both pages.
  In (b2r) and (n5) the list was installed anyway: (b2r)'s `CAMOU-FL set ctx=6 n=567` and `gate ctx=6 hasList=1 key=segoe ui allowed=0` both came from the file process (pid 8438) that laid out the page, and each n5 context read only its own half. The setter was spent on another document, not in another process or context.
- Green: a second dispatch on the fix branch against build 38495081436, run id in the PR (pending at the time of writing).

**What misled.** Each arm's own verdict read GREEN, and the EXPECTED_GREEN table explained it as #83 and #90 being fixed. Only a reading of which process wrote each document's group line showed the two contexts never met. The first fix run's final assert opens with `0 arm(s) red for a reason this guard does not already know about:`, which reads as a contradiction. That count is the `unexpected` bucket. The step failed on the second list in the same message, the arms whose own preconditions failed.

## #236: TestScrollToBottom required a scroll position the drawn window could not reach

**Fixed by:** the PR that changes `goapi/scroll_test.go`. **Found by:** smoke run 38568534252.

**Symptom.** `scroll_test.go:66: expected scrollY >= 4000, got 3722` in smoke's goapi step.

**Root cause.** The test loads a 5000 px page and required `window.scrollY >= 4000`. The furthest a page scrolls is `scrollHeight - innerHeight`, and the launch draws a random identity, so `innerHeight` varies. That run drew a window 1278 px tall: the page was at its bottom, 3722, and the bound was out of reach. The test passed only for windows at most 1000 px tall.

**Fix.** The test reads `scrollHeight - innerHeight` from the page and requires `scrollY` to reach it. It fails first if the page is not scrollable at all.

**Evidence.** Red: the run above. Green: 5 of 5 local runs on the fork.3 macOS arm64 build. A `ScrollToBottom` that did not scroll leaves `scrollY` at 0, below any bottom, so the check still fails for the bug it is about.

**What misled.** Nothing; the number alone gave it away.

## #234: the TypeScript launcher started Xvfb without Composite

**Fixed by:** the PR that turns Composite on in `typescript/src/virtdisplay.ts`. **Found by:** the #232 fix, which compared the two `virtdisplay` twins.

**Symptom.** Under `headless: "virtual"`, the TypeScript launcher started Xvfb with `-extension COMPOSITE` unless `CAMOUFOX_VIRTUAL_DISPLAY_COMPOSITE` was `1` or `true`. pythonlib has started it with `+extension COMPOSITE` since #140.

**Root cause.**
- #136 measured that Playwright 1.55 under Xvfb records a 110-byte video with no frames when Composite is off. With Composite on, it records 54370 bytes. #140 turned Composite on in pythonlib and changed nothing in TypeScript.
- The TypeScript default stayed `["1", "true"].includes((process.env[COMPOSITE_ENV_VAR] ?? "0").trim())`. Its comment said Composite on crashed the browser, which #136 found does not reproduce.
- The TypeScript package also allows Playwright below 1.63. So a TypeScript user on Playwright 1.57 or older recorded empty videos under a virtual display.

**Fix.**
- The default is now `!["0", "false"].includes((process.env[COMPOSITE_ENV_VAR] ?? "1").trim())`, which is pythonlib's expression.
- The comment points to the Python twin's measurement.
- A unit test runs pythonlib's `VirtualDisplay().composite` over nine env values (unset, `""`, `0`, ` 0 `, `false`, `False`, `1`, `true`, `no`) and requires the TypeScript launcher to give the same answers.

**Evidence.**
- Against main, two tests failed. `enables COMPOSITE by default` got `-extension`. The parity test differed on unset, `""`, `False` and `no`, where pythonlib reads on and TypeScript read off. With the fix, both pass.
- Not measured: an empty video from the TypeScript launcher itself. The mechanism is #136's measurement, made on the same binary with the same Xvfb arguments.

**What misled.** The tribal rule `composite-extension-on` is automated and was green. Its tests import only the Python module, so the rule read as covering a behaviour that half the launchers did not have.

## #232: the TypeScript launcher gave a cold Xvfb 10 s, where pythonlib gives 30

**Fixed by:** the PR that sets `DISPLAYFD_READ_TIMEOUT_MS` to 30 s. **Found by:** the `typescript` job of Tests run 38553266734 (job 115816505596).

**Symptom.** `virtdisplay.test.ts > Xvfb lifecycle > single launch returns a valid display and kill terminates Xvfb` failed with `CannotExecuteXvfb: Xvfb did not report a display within 10000ms`. It was the job's first Xvfb launch, on a PR that changed no TypeScript.

**Root cause.** #157 (d83360a) measured a cold first Xvfb launch on fresh ubuntu-24.04 runners at 603-8434 ms, and raised pythonlib's `DISPLAYFD_READ_TIMEOUT_S` from 10 to 30. It left the twin in `typescript/src/virtdisplay.ts` at `DISPLAYFD_READ_TIMEOUT_MS = 10_000`. In the failing job the next test, two `get()` calls on one display where #157 measured a warm launch at 25-39 ms, took 3039 ms, so the runner was loaded (`webgl.test.ts` ran beside it).

**Fix.**
- `DISPLAYFD_READ_TIMEOUT_MS` is 30 s and exported.
- A unit test reads `python/src/camoufox/virtdisplay.py` and requires the two bounds to match.
- The `Xvfb lifecycle` block gets a 60 s test budget. The suite's 30 s `testTimeout` equalled the new bound, so a stalled launch would have reported vitest's timeout instead of `CannotExecuteXvfb`.

**Evidence.**
- Against main's value the new test failed with `expected 10000 to be 30000`. With the fix it passes.
- Not measured: that this run's launch would have finished under 30 s. The mechanism, a bound below a healthy cold start, is #157's finding.

**What misled.** The tribal rule `displayfd-read-timeout` is automated and was green, so the bound read as enforced. Its `expect` names only `camoufox.virtdisplay`, so it never saw the TypeScript twin.


## #224: smoke's goapi step went red on two stale TestRuntimeSpoofs expectations

**Fixed by:** the PR that updates `goapi/runtime_spoof_test.go`. **Found by:** smoke run 38541963024, the first smoke on a branch carrying #215 and #219.

**Symptom.** `touch_trio` failed with `window.TouchEvent should be undefined (desktop)`, and `readpixels_deterministic` with `readPixels hash not deterministic in-context`. Smoke on main fa0cafc, the same browser, had passed.

**Root cause.** The test draws its identity with a pinned RNG. After #215 changed the preset pool, that draw is a touch device (`navigator.maxTouchPoints` 5) naming a Windows Intel GPU.
- `touchscreen-fingerprint-spoofing.patch` defines `window.TouchEvent` exactly when `navigator.maxTouchPoints` is above zero, so "always undefined" was only true of the old draw.
- #219 covers the canvas of every goapi identity naming a GPU, so both reads were RFP's random placeholder. The subtest is about the per-seed noise of an uncovered launch.

**Fix.** `touch_trio` asserts `TouchEvent` is defined exactly when `maxTouchPoints` is above zero. The test's launch passes `WithCanvasPlaceholder(false)`, so `readpixels_deterministic` measures the seeded noise again.

**Evidence.** On the fork.3 macOS arm64 build (`7b50dec4…`): the old test fails the same two subtests (`950045696 vs 1657080320`), the new one passes all ten.

**What misled.** Two unrelated subtests failing together read like one browser regression. Both came from the pinned draw moving under the test.

## #193: on a Windows host, a macOS or Linux identity rendered Windows-only families

**Fixed by:** the PR that adds `browser/patches/font-substitutes-gate.patch`. **Found by:** e2e on `windows-2025`.

**Symptom.** `fonts_no_foreign_os` failed on the Windows leg of e2e run 38274480396, in every driver. A macOS identity rendered `MS Sans Serif`, `MS Serif`, `Roman` and `Small Fonts`; a Linux identity rendered the last three.

**Root cause.** `gfxDWriteFontList::FindAndAddFamiliesLocked` (Firefox 156 `gfx/thebes/gfxDWriteFontList.cpp:2140`) swaps the requested name for its substitute before it calls the base `gfxPlatformFontList::FindAndAddFamiliesLocked` (`:2178`), where both font gates sit. The shared-list branch rewrites `keyName` (`:2159`). The non-shared branch returns the substitute family directly (`:2168`), without reaching the base gates at all. The substitutes come from `sDirectWriteSubs` (`:2086`: `MS Sans Serif` to `Microsoft Sans Serif`; `MS Serif` and `Roman` to `Times New Roman`; `Small Fonts` to `Arial`), plus `kFontSubstitutes` and the registry `FontSubstitutes` key (`GetFontSubstitutes`, `:1989`). So the gates were asked about `times new roman`, `arial` and `microsoft sans serif`, which the mac and lin lists allow, and never about the name the page asked for. `Microsoft Sans Serif` is on the mac list but not the lin list, which is why `MS Sans Serif` rendered only under the macOS identity.

**Fix.** The rule follows the context's spoofed OS, because substitution is Windows behaviour.
- When a substitution applies under a macOS, Linux or other non-Windows identity, both branches ask `CamouIsFamilyAllowed` about the requested name. If the identity's list does not allow it, the lookup is refused. A real machine of that OS does the same, because it has no font of that name.
- A Windows identity, a lookup with no identity, and chrome keep stock substitution exactly. The OS is resolved the way `system-ui-font-spoofing.patch` resolves it: `NavigatorManager::GetSpoofedOS(FontListManager::ContextIdFor(provider))`, after a chrome provider has been excluded.
- A refusal logs `CAMOU-FL dwrite-subst os=<n> key=<name> allowed=0`. The launch mask alone can refuse, and it short-circuits the `CAMOU-FL gate` line, so this line is the only record of the refusal.

**Alternative rejected.** The first version of the fix asked the gate under every identity. A Windows identity on a Windows host then refused every alias missing from the `win` list of `fonts.json`, where stock Firefox renders the substitute. That covered `Script`, 45 of the 48 entries in `kFontSubstitutes` (`StandardFonts-win10.inc`, for example `Arial CE` and `MS Shell Dlg 2`), and any alias the registry adds. A page probing those names could have told the identity from stock Windows Firefox. Adding the aliases to the font lists was also rejected: they are not fonts, only Windows' answer to a name.

**Evidence.**
- Red: e2e run 38274480396, Windows leg (strict entry in `e2e/known.py`).
- The patch applies to the tree with every earlier patch applied using GNU `patch -p1 --forward -l --binary`, with no fuzz or offset.
- Green: pending. It needs a Windows build and an e2e run on it. The strict `e2e/known.py` entry is removed, so that run fails if any of the four families still renders.

**What misled.** The issue offered two hypotheses. The first, substitution, was correct, and it explains all four names, not only `MS Sans Serif`. The second was wrong: host bitmap `.fon` fonts reached outside the whitelist. DirectWrite cannot load `.fon` fonts at all, and that is why Firefox substitutes them (bug 642093). The Firefox 152 pass was no evidence either way, because none of the four names was a marker then. Also, `font-list-spoofing.patch` already describes `gfxDWriteFontList`'s substitution tables as filled at init, never from a gate answer. That is true, but it answers only the cross-context cache question. It does not cover a name rewritten above the gate. This is CLAUDE.md lesson 7 again.


## #195: build-tester launched headless whatever display it was given

**Fixed by:** the PR that makes `browser/tests/build-tester/scripts/runner.py` launch headful. **Found by:** the upstream sync review (#188).

**Symptom.** #75 added an `xvfb` fallback to `run_tests.sh` so the WebGL checks would run against a real GL context. The browser stayed headless anyway, and with neither a display nor `xvfb-run` the script printed a warning and ran.

**Root cause.**
- `runner.py` passed `headless=True` to both `firefox.launch()` calls and never read `DISPLAY`. The `BUILDTESTER_HEADLESS` switch that `run_tests.sh` set was read by nothing.
- The WebGL checks in `src/lib/checks/extended.ts` and `workers.ts` returned `{ passed: true, detail: "WebGL not available" }`. A run with no GL context therefore scored them as green.

**Fix.**
- Both launches are `headless=False`. On Linux, `run_tests()` returns 1 before building anything when `DISPLAY` is unset.
- `run_tests.sh` drops `BUILDTESTER_HEADLESS`, runs directly off Linux, and exits 1 when Linux has neither a display nor `xvfb-run`.
- Every "WebGL not available" branch, and the render-hash `catch`, now fails its check.
- CI's `xvfb-run` gets the `1920x1080x24` screen `run_tests.sh` uses, because a headful window can see the screen.

**Evidence.**
- `test_build_tester_is_headful_and_webgl_absence_fails` in `browser/tests/native/test_tribal_rules.py`, rule `build-tester-is-headful-and-webgl-absence-fails`.
- Against main's sources it failed on `runner.py must launch every browser headful`. With only the launches fixed, it failed on `exit 1, 'ran without a display'`. With the fix it passes.
- Score before: main's Tests run 38524819436 (job 115725063597, 47ba70a), `OVERALL: [A] 1056/1064 checks passed (8 profiles)`. The after score is on the PR's Tests run.

**What misled.** The issue expected the denominator to grow, from #75's measurement: headless 124/125 against headful 136/137. Main no longer behaves like #75's headless arm. Its run above was headless under `xvfb-run`, and all 8 profiles report a WebGL render hash and a full `webglExtended` block, with no "not available" detail anywhere. Per-context profiles already score 137/138 (macOS) and 136/137 (Linux). The likely difference is that #75's headless arm had no display at all, while CI's step was already wrapped in `xvfb-run`; this was not isolated. So the fail-open was latent on CI, not live, and the after score may equal the before.


## #196: a goapi launch read the host's real canvas under a foreign identity

**Fixed by:** the PR that adds `goapi/rendering.go`. **Found by:** the upstream sync (#188), which ledgered it in `e2e/known.py`.

**Symptom.** `test_a_covered_launch_reads_the_canvas_placeholder[go]` failed on every host. A goapi launch on another OS read the same `toDataURL` twice, where the Python and TypeScript launchers return RFP's random placeholder.

**Root cause.** goapi had no rendering plan. `Generate` always drew `canvas:seed`, and the launch never set `privacy.baselineFingerprintingProtection.overrides`. So the page read the host's real pixels, with keyed noise, under an identity naming another OS and GPU.

**Fix.**
- pythonlib's `plan_rendering` covers the canvas of any identity that names a GPU, and every goapi identity names its preset's. So `Launch` turns on the placeholder by default, sends no canvas seed under it, and warns, as `LeakWarning('canvas_noise')` does.
- `WithCanvasPlaceholder(false)` keeps the host canvas with a seeded noise (`canvas_noise=False`).
- WebGPU follows `set_webgpu` with no host GPU known: enabled where Firefox ships it, with the adapter blocked.

**Evidence.**
- The ledger entry (strict) and its two oracle tests are removed, and the e2e journey must pass for go on every host.
- Unit tests cover the plan, the override merge, the WebGPU prefs and the warning.

**What misled.** goapi already has `WithCanvasNoise`, which tunes the fork's noise density and is unrelated to pythonlib's `canvas_noise`. Hence the new option's different name.

## #185: goapi's voice lists were never one real machine's

**Fixed by:** the PR that adds `goapi/pkg/fingerprint/voices.go`. **Found by:** the #185 drift review.

**Symptom.** None in a run. Measured with a test on the old code (seed 1, 2):
- a Windows `fr-FR` identity claimed 53 voices from every language pack at once;
- a Linux identity claimed none;
- every identity marked its first voice as the default.

**Root cause.** goapi read its own flat `voices.json`, which pythonlib does not have. It kept every Windows voice whatever the locale, drew a random 40-80% of macOS voices, and gave Linux nothing. pythonlib's `_generate_random_voice_subset` draws from `voice-manifests.json` instead:
- the OS base;
- the display locale's Windows pack, its legacy Desktop voices and extra packs at their measured probabilities;
- macOS downloads.

It builds each `voiceUri` the way the OS backend does and marks no voice default, as stock Firefox does.

**Fix.**
- goapi embeds pythonlib's `voice-manifests.json` and `voice-uris.json`, with drift tests, and ports the draw and `_voice_uri`.
- The locale comes from `locale:language`/`locale:region`, or else `navigator.language`.
- `voices.json` and its loader are removed.

**Evidence.**
- The same test on the new code: Windows `fr-FR` 3 voices, all French; Linux 131; no default.
- `TestVoiceURIMatchesPythonlib` checks nine URIs `_voice_uri` returned.
- `TestVoicesFollowTheManifest` checks 100 draws per case for the base, the locale's pack and no default.

**What misled.** Python NFKD-folds a macOS name outside the URI catalogue, which Go would need `golang.org/x/text` for. Every such name in the data is ASCII, so a test pins that instead of adding a dependency.

## #185: goapi's font lists were never one real machine's

**Fixed by:** the PR that adds `goapi/pkg/fingerprint/font_draw_test.go`. **Found by:** the #185 drift review.

**Symptom.** No run showed it. Measured on main's code: in 300 draws per OS, no goapi font list contained a whole OS base. Every identity claimed a partial install of its OS, which no real machine has.

**Root cause.** `RandomFontSubset` (`goapi/pkg/fingerprint/fonts.go`) was a twin of an older pythonlib draw: 30-78% of `fonts.json` over a 9-17 family essential list. pythonlib's `_generate_random_font_subset` had since become:
- one OS-version base by weight (`font-bases.json`), kept whole;
- the essential floor (`essential-fonts.json`);
- addition units at measured probabilities (`font-groups.json`);
- the marker fonts.

goapi also ignored `native` (the host's own macOS or Windows claims only its essential fonts), and its marker lists had drifted from `launcher-constants.json`.

**Fix.**
- goapi embeds pythonlib's `font-bases.json`, `font-groups.json`, `essential-fonts.json` and `launcher-constants.json`, with byte-equality drift tests, and draws as pythonlib does.
- `Options.HostOS`, set from `config.HostOS()` at launch, decides `native`.
- The taskbar and touch-point constants added in #208 now come from the same embedded file.

**Evidence.** On the old code a throwaway test read 0/300 whole-base draws on each OS. After the fix:
- `TestFontDrawIsOneMachineOfPythonlibsModel` passes for 300 draws per OS: a whole base, the essentials and markers present, and nothing outside base, unit, marker or essential lists;
- the native and Windows-10-host tests pass;
- `TestGenericFontPrefsNameOnlyFamiliesEveryIdentityClaims` still holds for 200 draws per OS, native and not.

**What misled.** Ubuntu 24.04's base is a subset of 26.04's, so a check that took the first base present in full blamed 26.04-only families as strays.

## #190: a TypeScript NewContext could report innerWidth > outerWidth

**Fixed by:** the PR that adds `typescript/tests/context-geometry.test.ts`. **Found by:** porting #164's pythonlib fix (#191).

**Symptom.** The same as #164a, through the TypeScript launcher. A `NewContext` sized its viewport from the drawn screen alone, while the window it lives in is the launch's own: one real window per process, which browser-init.patch sizes once.

**Root cause.** `generateContextFingerprint` (`typescript/src/fingerprints.ts`) had no record of the launch window. `NewBrowser` kept none, unlike pythonlib's `attach_launch_window`.

**Fix.**
- `NewBrowser` records the launch window from its own CAMOU_CONFIG (`attachLaunchWindow`).
- `NewContext` passes the record to `generateContextFingerprint`, which, as pythonlib does:
  - takes the launch inner size as the viewport;
  - when the launch has no inner size, clamps the preset viewport inside the launch outer window, keeping its scale factor;
  - claims the launch screen when the drawn screen cannot hold the window.
- An explicit `noViewport` or `viewport: null` drops the generated viewport and `deviceScaleFactor`, which Playwright rejects with a null viewport.

**Evidence.** `context-geometry.test.ts` mirrors `python/tests/test_context_geometry.py`: 7 of its 8 cases fail on the old code and all pass after the fix. The malformed-record case passes on both, as a control.

**What misled.** The identity golden still passed, because a launch with no record (the golden's path) is unchanged.

## #185: goapi drew presets pythonlib had removed

**Fixed by:** the PR that adds `TestEmbeddedPresetsMatchPythonlib`. **Found by:** a byte comparison while working on #185.

**Symptom.** None observed in a run. goapi's embedded `fingerprint-presets.json` held ten presets the pythonlib copy no longer had: macOS 5, Windows 4, Linux 1.

**Root cause.** `python/scripts/clean_presets.py` removes presets that fail the coherence checks, but it edits only `python/src/camoufox/fingerprint-presets.json`. goapi embeds its own copy (`goapi/pkg/fingerprint/data/`), and no test compared the two, so goapi could still draw an identity pythonlib refuses.

**Fix.** The goapi copy is refreshed from pythonlib's. A byte-equality test now fails on any future drift, as `TestEmbeddedFontsMatchPythonlib` already did for `fonts.json`.

**Evidence.** The test fails on the old copy and passes after the refresh. `go test ./pkg/...` and the root package's font and generic-prefs tests pass.

**What misled.** Both files carry the same `version` and `generated_at`, so they look identical until the preset lists are compared.

## #186: a corrupt groups.json widened the font scan to every OS

**Fixed by:** the PR that closes #186. **Found by:** review of the goapi twin in #179.

**Symptom.** None observed in a run. It was found by reading: the Python and TypeScript launchers caught any error reading `fonts/groups.json`.

**Root cause.**
- `_generate_fontconfig` (`python/src/camoufox/utils.py`) and `generateFontconfig` (`typescript/src/utils.ts`) caught any error reading `fonts/groups.json` and left the scan list empty.
- An empty list fell through to `fonts/<os>/`, which a grouped bundle does not have, and then to `fonts/` itself.
- fontconfig scans recursively, so every other OS's faces became glyph-fallback candidates. That is the leak the per-OS grouping exists to prevent.

**Fix.**
- A `groups.json` that exists but cannot be read or parsed now raises, as goapi's `fontScanDirs` already did.
- An absent one still means a legacy bundle and keeps the `fonts/<os>/` fallback.

**Evidence.** `python/tests/test_fontconfig_groups.py` and the matching `typescript/tests/utils.test.ts` block:
- the corrupt-file case fails on the old code (1 failed, 2 passed in each) and passes after the fix;
- the valid-file and missing-file cases pass on both versions, as controls.

**What misled.** Nothing at runtime: a shipped bundle always has a valid `groups.json`, so no run could show the fallback.

## #211: a first run's hanging filter-list download held every page for 30 s

**Fixed by:** PR #212. **Found by:** the e2e suite on macOS (#171, #210).

**Symptom.** `test_locale_option_reaches_navigator_and_intl` (`os="windows"`,
`locale="de-DE"`) timed out on macOS CI: in run 38456928453 on main, and in 2
of 8 later dispatches of journey 2 against the same build. The `/fp` page
loaded, but its `fetch("/fp-markers.json")` did not finish within 10 s. The
response ended 32 s after the request started.

**Root cause.** On Firefox, uBlock Origin holds every request that has a tab id
while it loads its filter lists:

- `platform/common/vapi-background.js` holds `onBeforeRequest` while
  `suspendDepth !== 0`.
- `src/js/storage.js` `loadFilterLists()` calls `vAPI.net.suspend()` whenever
  `vAPI.Net.canSuspend()` is true, which it always is on Firefox.

Every Camoufox launch is a first run, and on a first run uBO auto-selects a
regional list from the UI language. For `de-DE` that is `easylistgermany`. uBO
does not bundle it, so the first `loadFilterLists()` waits for a download. When
that download hangs, every page in every context waits for uBO's
`assetFetchTimeout` (30 s), once per mirror.

**Fix.** `browser/settings/distribution/policies.json` pins the list selection
through uBO's managed storage (`3rdparty` → `toOverwrite.filterLists`) to the
ten default lists it bundles. `restoreAdminSettings()` runs before
`loadSelectedFilterLists()`, so the first load needs no network.

- **Cost:** a non-English locale loses its regional list.
- **Upkeep:** when uBO changes its defaults, update the keys from its
  `assets.json`.

The decision is `ubo-lists-pinned-to-bundled` in `ci/tribal-rules.yml`.

**Tried and failed: `suspendUntilListsAreLoaded=false`.** It lifts only the
start-up hold. `loadFilterLists()` suspends again whatever the setting says, so
with it applied the regression test still timed out at 30 s.

**Evidence.** `test_a_hanging_filter_list_download_does_not_hold_pages` (journey
3) runs behind `Proxy(hang_outside=True)`, which never answers an outside host.

| Build | Result |
|---|---|
| main's build | `Page.goto: Timeout 30000ms exceeded` (pkg and pw) |
| same build, this `policies.json` | page loaded in 0.1–0.7 s |
| `exclude_addons=[DefaultAddons.UBO]` | page loaded in 0.05 s |

**What misled the investigation.**

- **A long silence on a thread in `MOZ_LOG` is not a blocked thread.** The
  parent main thread logged nothing for 30 s. That read as a freeze, but the
  thread had no nsHttp work to log. Only the waiting channel was evidence.
- **Correlation is not cause.** The longest silences followed the Widevine
  download, and GMP looked like the cause. A single-variable run with
  `media.gmp-manager.updateEnabled=false` still stalled, and that ruled it out.
- **A setting's name is not its behaviour.** `suspendUntilListsAreLoaded` reads
  like the off switch. Reading every `suspend()` call site in uBO showed it is
  not.
- **A timing-bound reproduction needs an event, not a delay.** Locally uBO starts
  the regional download about 20 s after launch. On CI it starts within about
  2 s. The first version of the test navigated too early and passed on the
  broken build. The test now navigates once a list download is held.
- **A control must hold before and after the fix.** The first control required
  a request to an `easylist` host. The fix removes that request, so the control
  went red on the fixed build. The control now checks that some filter-list
  download is held.
