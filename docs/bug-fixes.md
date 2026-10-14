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
