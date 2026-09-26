# Fixing the open e2e findings (#162, #163, #164, #165, #166, #171): design

Date: 2026-09-26. Status: proposed.

## Goal

The e2e user-journey suite (`e2e/`, PRs #168 and #175) found six defects that
users hit on the documented paths. It ledgers each one in `e2e/known.py`. This
spec fixes all six, or, for the two whose cause is not yet known, measures them
until the fix is determined. Each fix is proven by the ledger entry that
records the bug: the entry is removed and the check goes green, with the same
check's negative control still going red.

## Non-goals

- New spoofing surfaces. This is repair work on the documented paths, not new
  coverage.
- A per-context outer-window setter (`setWindowDimensions`). #164 is fixed
  without it (W3). Add one only if a user needs a context whose window differs
  from the launch window.
- Publishing a Linux asset on the fork release. The Linux leg of `e2e.yml`
  skips until one exists, and the PR gate covers Linux from a fresh build.
  Tracked separately.

## Root causes (read from the code)

Three read-only surveys produced these findings. The load-bearing claims were
re-read by hand, and those are marked (verified). Line numbers are on `main`
at c6e0ae9 and the beta.31 tree. Re-read each one before editing (CLAUDE.md
lesson 6).

| # | Cause | Where |
|---|---|---|
| 163 | **No C++ code reads the launch-level `webrtc:ipv4`/`webrtc:ipv6` keys.** `WebRTCIPManager::GetIPv4`/`GetIPv6` read per-context storage only (`webrtc_ipv4_<ucid>`), and `ShouldSpoofCandidateIP()` gates every rewrite on those getters. The only `MaskConfig` reads are for `webrtc:localipv4`/`localipv6` (`webrtc-ip-spoofing2.patch:196,215`), and those sit behind the same gate. So `Camoufox(geoip=…)` and all of goapi leak the real address. (verified) | `patches/webrtc-ip-spoofing.patch:65-83` |
| 163b | `NewContext` without `webrtc_ip` stores `setWebRTCIPv4("")`, and `RoverfoxStorageManager::GetString` returns true for an empty stored value. (verified) Inferred: spoofing is then on with an empty replacement, and a stored empty value would also shadow any config fallback. | `pythonlib/camoufox/fingerprints.py:1071-1073` |
| 162 | **A launch-only mask never reaches Camoufox's generic table.** `CamouGenericCandidate` returns false when the context has no per-context list (verified, `font-list-spoofing.patch:596-600`). Generics then resolve through the **host** OS's `font.name-list.*` prefs (Menlo on a mac host, Consolas on a Windows host). The launch mask refuses those names when the spoofed OS differs from the host, the generic comes back empty, and `GetDefaultFontLocked`'s "first allowed family" walk picks Arial (win list) or Arimo (lin list). That is why only mismatched spoofs collapse, matching the host matrix in #162's comment. | `patches/font-list-spoofing.patch:596`, and its callers at `:353` and `:1006` |
| 162b | goapi on a Linux host never sets `FONTCONFIG_FILE` (verified: no `FONTCONFIG` in `goapi/`), so it resolves generics against the host's system fontconfig. pythonlib does set it (`utils.py:303-332`), and its comment "matching the Go launcher" is false. | `goapi/launch.go` env builder (~`:164-180`) |
| 164a | `generate_context_fingerprint` sets the Playwright viewport to the context preset's screen (`width = sw`, `height = sh - 28`), while `window.outerWidth/Height` stay process-wide launch values (`MaskConfig`). There is no per-context outer-size setter. So whenever the context screen is wider than the launch window, the result is inner > outer. (verified) | `pythonlib/camoufox/fingerprints.py:1259-1265` |
| 164b | Bare Playwright + `launch_options()` gets Playwright's default 1280x720 viewport. `launch_options` cannot carry a context option, and neither README mentions `no_viewport=True`. | `README.md`, `pythonlib/README.md` |
| 166.1 | `Download.Path()` joins `downloadsDir` (always `""`) with the suggested name. The browser saves the file as `<dir>/<uuid>`. (verified) | `goapi/download.go:60-62,149` |
| 166.2 | goapi's `applyPreset` sets `screen.*` but never `window.outer*`/`inner*`, so the browser falls back to `resizeTo(1280, 1040)`. (verified: no `WindowOuter` assignment in `goapi/pkg/fingerprint`) pythonlib clamps with `fix_screen_no_taskbar`, `clamp_window_dimensions` and `clamp_window_position`. | `goapi/pkg/fingerprint/generator.go` `applyPreset` |
| 166.3 | Juggler's proxy filter calls `newProxyInfo(type, host, port, '', '', …)` and drops the SOCKS credentials. (verified, `NetworkObserver.js:629`) Credentials are used only in `promptAuth` for HTTP `AUTH_PROXY`, and SOCKS never triggers that. Firefox supports `newProxyInfoWithAuth` for SOCKS. | `additions/juggler/NetworkObserver.js:629` |
| 166.4 | goapi never sets `voices:blockIfNotDefined` (verified: the field is declared, `config.go:165`, and never assigned), and its linux voice list is empty and `omitempty`. So neither C++ gate fires and the host SAPI voices show. pythonlib always forces the flag (`utils.py:1278-1294`). | `goapi/pkg/fingerprint/generator.go:53-74` |
| 166.5 | `Goto` polls `MainFrameID()` for a fixed 2 s. `NewPage` waits 5 s for context-ready and then continues silently. Inferred: under load the first `frameAttached` is just late, since 5 + 2 s plus overhead matches the observed 7.5 s. | `goapi/page.go:78-83,198-216` |
| 165 | **Not known.** Hypothesis: the emoji pref list is compiled per host (`all.js`: Apple Color Emoji on mac, Segoe UI Emoji on Windows). When the mask refuses the host's emoji family, the codepoint goes to global fallback, which in a content process skips families whose cmaps are not loaded yet (`gfx.font_rendering.fallback.async`, `gfxPlatformFontList.cpp:1472-1477`). A reflow then swaps the face. Unverified. | measure first (W4) |
| 171 | **Not known.** Linux, Playwright client only. The browser sent no request for the stalled navigation. | measure first (W4) |

## Design

Five workstreams, each one PR tied to its issue(s). W2 and W3 need no browser
build. W1 is a single browser build, with all its fixes landing together to
share the ~40-95 min loop. W4 is measurement that feeds W5.

### W1. Browser (patches + Juggler): #163, #162 (C++), #166.3

**#163: launch-level fallback in `WebRTCIPManager`.** `GetIPv4`/`GetIPv6` follow
the `TimezoneManager::GetTimezone` pattern: per-context storage first, then
`MaskConfig::GetString("webrtc:ipv4")`/`("webrtc:ipv6")`. The difference from
the timezone code is that **an empty stored value counts as unset** (it falls
through to the config). The config value is not written back into storage, so
a later per-context set still wins. `pythonlib` stops emitting
`setWebRTCIPv4("")` (`fingerprints.py:1071-1073`) and emits nothing when no IP
is given.

- **Process check before editing:** the rewrite code (`ShouldSpoofCandidateIP`,
  `getMaskForIP`) must be able to reach `MaskConfig` in whichever process it
  runs in. It already does for `webrtc:localipv4` in `getMaskForIP`, so the
  same process reads config today. Confirm by reading it, not by assuming.
- **What the fix must not change:** `NewContext(webrtc_ip=X)` over a launch-level
  `Y` must still give `X`. W1 adds that case to
  `test_webrtc_does_not_reveal_lan_address`.

**#162 (A): the generic table serves a launch-only mask.** `CamouGenericCandidate`
and its two callers (`FindGenericFamilies`, `AddGenericFonts`) currently gate on
`HasFontList(ctx)`. They will also take the table path when the launch mask
applies (the predicate `MaskedFontListBlocks` already consults. The survey named it
`MaskedFontListAppliesTo`, which is unverified, so read the site before
naming it). The row is resolved
against the launch list exactly as it is against a per-context list today.

- **Contexts affected:** unchanged for contexts with their own list. This is
  new behaviour for context 0 and for launch-only contexts. The lesson 5
  fail-open, where context 0 with no mask allows everything, must stay exactly
  as it is when no launch list exists.
- **Before editing:** per lesson 5, enumerate every generic-resolution entry
  point (`docs/fonts-gating.md`) and name which ones this changes. Per lesson 7,
  check `gfxFcPlatformFontList`, `gfxDWriteFontList` and
  `gfxMacPlatformFontList` for an override that answers generics before the base
  class. The Linux fontconfig path is the known one: `FindGenericFamilies` on
  `gfxFcPlatformFontList`.
- **Hunk hygiene:** balance the context lines and dry-run with
  `patch -p1 --forward -l --binary --dry-run`. Do not use
  `make workspace` on `font-list-spoofing.patch`; rebuild at the patch's own
  position (#131).

**#166.3: SOCKS credentials.** When `proxy.type` starts with `socks` and a
username is set, `NetworkObserver.js:629` uses
`protocolProxyService.newProxyInfoWithAuth(type, host, port, username, password, '', '', flags, …)`.
HTTP proxies keep their current path. Playwright's client still refuses SOCKS
auth up front, so only goapi benefits. That is expected, and it is stated in
the PR.

**W1 verification:**
- **e2e ledger:** the strict #163 entries (Darwin, Linux, Windows) must flip to
  `FIXED?` on the dispatched `e2e.yml` run; they are then removed. The goapi
  `test_proxy[go-socks5]` xfail (strict) must flip.
- **#162 must be measured without W3's prefs, or W3 hides it (lesson 4).** Add a
  patch guard under `tests/patches/` that launches the raw binary with
  `CAMOU_CONFIG` holding only a mismatched-OS `fonts` list and no
  `font.name-list.*` prefs. It asserts `monospace` i-width == m-width, with a
  negative control of `sans-serif` i ≠ m. It must go red on the main build,
  which is the RED-first build, and green on W1's build. Name both run ids and
  their builds in the PR (lesson 9).
- **Hosts covered:** that guard runs on Linux CI only (lesson 3). The macOS and
  Windows evidence is the `e2e.yml` dispatch on W1's build, with W3's prefs
  disabled for that run by the flag described in W3.
- **Other gates:** `build-tester`, the patch guards and the Playwright suite
  stay green. `CAMOU-FL default-unfiltered` stays at zero.

### W2. goapi: #166.1, #166.2, #166.4, #166.5, #162b, plus the goapi half of #162 (B)

- **#166.1:** `SetDownloadOptions` records the directory on the context.
  `OnDownload` copies it into the `Download`, which keeps the `uuid` from
  `downloadCreated`. `Path()` returns `filepath.Join(dir, uuid)`, and `""` when
  no directory was set (the browser saved nothing). A goapi unit test covers
  both cases.
- **#166.2:** port pythonlib's `fix_screen_no_taskbar`,
  `clamp_window_dimensions` and `clamp_window_position` into `applyPreset`,
  so that `outer ≤ avail ≤ screen` and inner = outer minus the chrome delta.
  The port is a line-for-line translation with the Python source cited in a
  comment. The unit test is the invariant over every preset in
  `goapi/pkg/fingerprint/data`, for all three OSes.
- **#166.4:** `applyPreset` always sets `VoicesBlockIfNotDefined = true`, which
  mirrors `utils.py:1278-1294`.
- **#166.5:**
  - `Goto` waits on a frame-attached signal bounded by its own timeout, not a
    fixed 2 s.
  - `NewPage` returns an error when context-ready never arrives, instead of
    continuing.
  - Unit test: a fake Juggler that delays `frameAttached` by 3 s. `Goto` with a
    30 s timeout succeeds, and with a 1 s timeout it fails with a timeout error.
- **#162b:** on a Linux host, goapi's env builder sets `FONTCONFIG_FILE` to the
  bundle's `fontconfig/<spoofed os>/fonts.conf`, resolved the way
  `utils.py:303-332` does it. The false "matching the Go launcher" comment is
  corrected in the same PR.
- **#162 (B, goapi half):** see W3 for the shared pref table.

**W2 verification:**
- **Unit tests:** `go test ./...` passes, with each new test shown going red
  before its fix.
- **e2e, strict entries:** these must flip to `FIXED?`, then be removed:
  - `test_upload_and_download[go]` (strict xfail).
  - The Linux goapi #162 entries.
  - The Windows `go-linux` voices entry.
- **e2e, non-strict entry:** the `go` #166 `screen_contains_viewport` entry is
  non-strict. It is removed only after `test_fingerprint_is_coherent[go-*]` is
  green on 3 consecutive dispatches on all three hosts.
- **#166.5 check:** the goapi 50-context loop on Windows (`main frame not
  attached`) is green on 3 consecutive Windows dispatches.

### W3. pythonlib: #164, #162 (B), and the pythonlib half of #163

- **#164a:** `NewContext` stops setting a viewport and passes
  `no_viewport=True`, so inner follows the real launch window. The context
  preset is then sampled with the constraint `screen ≥ launch outer` and
  `avail ≥ launch outer`. The launch window is recorded on the browser the way
  `_camoufox_launch_fonts` is (`utils.py:748`).
  - **No preset fits:** after a bounded number of draws with no fitting
    preset, it uses the launch screen and warns. It never silently produces an
    impossible geometry.
  - **Unit test:** 1,000 draws over mismatched launch and context OSes, each
    satisfying `inner ≤ outer ≤ avail ≤ screen`.
- **#164b:** both READMEs document `browser.new_context(no_viewport=True)`
  for bare Playwright with `launch_options()`, with the reason. The e2e `pw`
  driver follows the README: it passes `no_viewport=True`, because the suite
  measures the documented path. The pw #164 entries are then removed. The PR
  states this plainly, so it does not read as a test changed to pass.
- **#162 (B):** both launchers set `font.name-list.{monospace,serif,sans-serif}`
  for the `x-western` and `x-unicode` lang groups to the spoofed OS's families.
  These must be families that `fonts.json` lists for that OS:

  | OS | monospace | serif | sans-serif |
  |---|---|---|---|
  | win | Consolas, Courier New | Times New Roman | Arial |
  | mac | Menlo, Courier New | Times | Helvetica |
  | lin | Cousine | Tinos | Arimo |

  - **Known ceiling:** other lang groups (CJK, Cyrillic and so on) keep the
    host default until W1 lands. The table carries a `ponytail:` comment
    saying so.
  - **pythonlib test:** it asserts that every family in the table is in that
    OS's `fonts.json` list, which catches drift.
  - **Opt-out flag:** a `CAMOUFOX_NO_GENERIC_PREFS=1` environment variable, read
    by both launchers, turns B off. It exists **only** so W1 can be measured
    without B (lesson 4). It is documented as a test hook, not a feature.
- **#163 (pythonlib half):** remove the `setWebRTCIPv4("")` emission (W1 makes
  the empty value harmless in C++; this removes it at the source).

**W3 verification:**
- **Unit tests:** pythonlib's tests pass, with the new tests shown red first.
- **e2e, #164:** the pkg #164 `test_new_context_fingerprint_is_coherent` entry
  is non-strict. It is removed after 3 consecutive green dispatches on all
  three hosts.
- **e2e, #162 (B):** the #162 entries for the pkg and pw drivers (macOS,
  Windows) go green on the **released** binary. That is the point of B.

### W4. Measure first: #165, #171

**#165.**
- **The cheap test first:** add `font.name-list.emoji` per spoofed OS to W3's
  pref table (win: `Segoe UI Emoji, Twemoji Mozilla`; mac:
  `Apple Color Emoji`; lin: `Twemoji Mozilla`). All of these are in
  `fonts.json`.
- **Measurement:** re-run the emoji timing probe (`measureText('😃')` at 0,
  0.3, 0.8, 1.5 and 3 s) on macOS and Linux, 10 fresh contexts each, with and
  without that pref. Capture `MOZ_LOG=fontlist:4` for the first second of one
  failing context.
- **Decision rule:** fix is the pref, if the pref alone makes the widths
  constant in 10/10 on both hosts and the log shows the pref family chosen at
  t=0. Otherwise the log decides whether the fix is gating the async fallback
  in C++ (W1-style build). That second branch gets its own spec section
  appended here before any code is written.

**#171.**
- **Capture:** add a capture mode to `test_fifty_contexts_in_a_row` behind
  `E2E_MOZ_LOG=1`. It sets `MOZ_LOG=nsHttp:3,nsSocketTransport:3`
  with a per-context `MOZ_LOG_FILE` under the job's work dir (not `/tmp`,
  per memory). On a stall it uploads the log of the stalled context as an
  artifact.
- **Runs:** dispatch until 2 stalls are captured on Linux, then compare against
  a healthy context's log.
- **Output:** a comment on #171 naming where the navigation stops. Either no
  channel was opened, or it was opened and never connected, or it connected and
  got no response. The fix then gets its own spec section appended here.

### W5. Fixes that W4 determines

Written after W4's data, as an amendment to this document, and reviewed before
any code.

## Order

1. W2 and W3 in parallel: no build, both fast loops. W3's
   `CAMOUFOX_NO_GENERIC_PREFS` flag must land before W1 is measured, because W1's
   macOS and Windows evidence depends on it.
2. W1: one browser build. Its RED-first control is the new #162 patch guard on
   `main`'s build, and the #163 e2e entries on the fork.1 release.
3. W4 runs alongside W1's build, since it uses the released binary. W5 follows
   it.

## Error handling and honesty rules

- **Removing a ledger entry:** an entry is removed only by the `FIXED?` it
  produces (strict), or after N=3 consecutive greens (non-strict). The PR quotes
  the run ids, and each run id is resolved to its build and branch
  (lesson 9).
- **Stating the gap:** every fix states what its verification cannot see. For
  example, W1's #162 guard runs on Linux only, and B leaves non-Latin lang
  groups uncovered.
- **Correcting published claims:** where an issue body turns out wrong (as #166
  was about Windows), post a correction comment. Do not silently edit the
  issue.

## Testing summary

| Workstream | Offline | Browser |
|---|---|---|
| W1 | patch dry-run; `tests/patches` guard RED on main build | e2e dispatch on W1 build (with and without B); gate |
| W2 | `go test ./...` (new tests red first) | e2e dispatch on fork.1 release |
| W3 | pythonlib tests (new tests red first) | e2e dispatch on fork.1 release; gate |
| W4 | none | probe and MOZ_LOG runs; issue comments |
