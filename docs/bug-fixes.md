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
