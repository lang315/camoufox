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
