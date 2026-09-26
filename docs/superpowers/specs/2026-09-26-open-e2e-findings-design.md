# Fixing the open e2e findings (#162, #163, #164, #165, #166, #171): design

Date: 2026-09-26. Status: proposed.

## Goal

The e2e user-journey suite (`e2e/`, PRs #168 and #175) found six defects that
users hit on the documented paths. It ledgers each one in `e2e/known.py`. This
spec fixes all six, or, for the two whose cause is not yet known, measures them
until the fix is determined. Each fix is proven by the ledger entry that
records the bug: the entry is removed and the check goes green, with the same
check's negative control still going red.

It also replaces the maintainer's former name and personal email with `Lãng`
across the fork's git history (W0).

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

Six workstreams (W0-W5), each one PR tied to its issue(s). W2 and W3 need no browser
build. W1 is a single browser build, with all its fixes landing together to
share the ~40-95 min loop. W4 is measurement that feeds W5.

### W0. Identity scrub: replace the former name and the personal email with "Lãng"

**Measured on 2026-09-26, from all 1,289 commits reachable from every ref:**

| Identity (author or committer) | Occurrences |
|---|---|
| former name + personal Gmail address | 928 |
| former name + GitHub noreply address (GitHub web merges) | 57 |
| `Lãng` + personal Gmail address | 2 |
| `Lãng <30039912+lang315@users.noreply.github.com>` (target, already in use) | 39 |

Scope of those numbers:
- **Commits:** 561 commits carry one of the first three identities, from
  e1b227c (2026-05-12) to 53b88db.
- **Tracked files and commit messages:** no tracked file and no commit message
  contains the name or the email.
- **Signatures:** 95 of those commits are signed (mostly GitHub web merges).
- **Refs:** 18 remote branches and 2 tags contain them.
- **Git config:** global git config is already `Lãng` +
  `30039912+lang315@users.noreply.github.com`. New commits are clean, so the
  work is only the history.

**Target identity:** `Lãng <30039912+lang315@users.noreply.github.com>`, for
author, committer and tagger. It keeps the commits linked to the GitHub account
without publishing an address. This document names neither the former name
nor the address, for the same reason.

**What a rewrite changes, stated up front, because it is irreversible once
pushed:**

- **Every commit from e1b227c onward gets a new sha**, on every branch and both
  fork tags (including `v152.0.4-beta.31-fork.1`, which the e2e suite fetches
  releases by). Upstream `daijro` history before e1b227c is untouched, so its
  shas and the merge-base with upstream stay the same.
- **About 105 sha references in 32 tracked files will point at commits that no
  longer exist on any branch.** These are in CLAUDE.md, `docs/fonts-gating.md`,
  specs and plans, and `.github/workflows/smoke.yml` (9). Issue and PR bodies,
  and Actions run records (`head_sha`), keep the old shas; they cannot be
  rewritten. CLAUDE.md lesson 9 ("resolve every run id to its build, and that
  build's branch") depends on those shas resolving.
- **The 95 signatures are lost:** the rewritten commits show as unverified.
- **GitHub will keep the old commits reachable anyway.** Each of the fork's ~104
  PRs has a read-only `refs/pull/<n>/head` that a push cannot touch, so old
  shas and their identities stay viewable by URL. Removing them needs a GitHub
  Support request for cached views and PR refs. Existing clones keep the old
  history.
- **The email has already been public.** It has been in 928 public commit
  identities since May 2026. A rewrite stops new exposure; it cannot recall
  copies already scraped or cloned.

**Procedure** (done on a fresh mirror clone, never on the working checkout):

1. **Freeze.** No open PRs, no running workflows, and every local branch
   pushed or deliberately dropped. Record `git show-ref` for heads and tags.
2. **Backup.** Keep `git bundle create camoufox-pre-scrub.bundle --all` offline,
   outside the repo and outside any synced folder. It still holds the old
   identity, so it is never uploaded.
3. **Rewrite.** Run `git filter-repo --mailmap <file>` with three lines mapping
   each old identity to the target. filter-repo rewrites authors, committers and
   tags, and writes `.git/filter-repo/commit-map` (old sha → new sha).
4. **Verify before any push:**
   - `git log --all --format='%an <%ae>%n%cn <%ce>' | sort -u` shows no old
     identity.
   - Commit messages and tracked files: a grep for the old name (with and
     without diacritics) and the address is 0. The patterns live only in the
     offline mailmap, never in the repo.
   - `git rev-list --count --all` still equals 1,289.
   - `git diff <old main> <new main>` in tree terms is empty (same tree
     hashes: `git rev-parse old^{tree} new^{tree}`).
   - The upstream commits' shas are unchanged.
5. **Keep old references resolvable.** Commit the changed part of `commit-map`
   as `docs/history-rewrite-2026-09.md`. The file holds only shas, no identity.
   Then rewrite the ~105 in-repo sha references through it with a script (not by
   hand), and grep for any 7-40 hex token that no longer resolves.
6. **Push.** This is the irreversible step, and it needs the maintainer's
   explicit go-ahead at that moment. Push `refs/heads/*` and `refs/tags/*` with
   `--force` (not `--mirror`, which would try to push `refs/pull/*`). Move the
   release tag and confirm the release still lists its assets.
7. **After the push:**
   - The `e2e.yml` dispatch against `v152.0.4-beta.31-fork.1` still fetches
     and runs.
   - `gh run list` shows new runs on the new shas.
   - Local checkouts re-clone.
   - Enable GitHub's "Keep my email addresses private" and "Block command line
     pushes that expose my email" (a platform setting, so no repo code is
     needed).
   - File the Support request for PR refs and cached views, if the maintainer
     wants those gone too.

**W0 verification:** the four checks in step 4 are pasted with their output
into the W0 PR, which carries the `docs/history-rewrite-2026-09.md` map and the
updated references. The PR merges before the force-push, so the push is the only
step left.

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

0. W0 first, while no PR is open. Every workstream after it then branches from
   the rewritten history and cites new shas. Doing it later would strand
   whatever branches were open at the time.
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
| W0 | identity, message, count and tree checks (step 4) | e2e dispatch against the moved release tag |
| W1 | patch dry-run; `tests/patches` guard RED on main build | e2e dispatch on W1 build (with and without B); gate |
| W2 | `go test ./...` (new tests red first) | e2e dispatch on fork.1 release |
| W3 | pythonlib tests (new tests red first) | e2e dispatch on fork.1 release; gate |
| W4 | none | probe and MOZ_LOG runs; issue comments |
