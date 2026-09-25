# End-to-end user-journey suite: design

**Date:** 2026-09-24
**Status:** approved in chat, written for review before the implementation plan

## Goal

Add a black-box end-to-end suite that uses Camoufox the way a real user does,
and derives every expectation from user-visible behaviour, not from reading the
patches.

The existing suites were all written by someone who had read the code they
test. `build-tester/` injects fingerprints through internal hooks,
`tests/patches/` has one guard per patch, `native-tests/` checks leaks and repo
conventions, and `pythonlib/tests/` tests the package internals. A spoof can
pass all of them and still break a user journey, for example a form that no
longer submits, a download that arrives empty, or a UA that disagrees with the
header the server received. This suite exists to catch those failures.

## Decisions taken

| # | Question | Decision |
|---|---|---|
| 1 | Which entry point does the user come in through? | All three: the `camoufox` Python package, bare Playwright with `CAMOU_CONFIG`, and `goapi` |
| 2 | Which sites? | Local realistic pages (the gate), plus real public sites (a separate `live` suite) |
| 3 | Which platforms? | Linux on the PR gate. Linux, macOS and Windows on GitHub Actions by dispatch. The same command also runs by hand on any machine. |
| 4 | Which journeys? | All eight (see "Journeys") |
| 5 | Where do expected values come from? | Three oracles: A (public docs), B (a differential against Playwright's Firefox, behaviour only) and C (internal coherence) |
| 6 | Layout | One `e2e/` suite. Each scenario is written once and run through all three drivers. |

## Layout

```
e2e/
  conftest.py          fixtures: binary, site, proxy, stun, drv (parametrized pkg|pw|go)
  pytest.ini           markers: live, slow, oracle_b
  drivers/
    base.py            the driver interface (below)
    pkg.py             camoufox.sync_api.Camoufox
    pw.py              playwright.firefox.launch + camoufox.utils.launch_options
    go.py              JSON-lines client for goapi/cmd/e2edriver
  site/
    server.py          ThreadingHTTPServer, two origins, request recorder
    ws.py              minimal RFC 6455 echo (stdlib only)
    proxy.py           HTTP CONNECT and SOCKS5, optional auth, traffic recorder
    stun.py            UDP STUN binding responder
    pages/             login, shop, upload, download, frames, apps, fp, echo
  oracle/
    docs.py            oracle A: each expectation with its quoted public source
    coherence.py       oracle C: rules plus one negative control per rule
    reference.py       oracle B: the same scenario on Playwright's Firefox
  journeys/
    test_01_install_launch.py ... test_08_lifecycle.py
  live/
    test_live_sites.py marker `live`, prints aggregate results only
goapi/cmd/e2edriver/main.go
.github/workflows/e2e.yml
```

The suite uses the stdlib and packages the repo already depends on
(`camoufox`, `playwright`, `pytest`). It adds no new dependency.

## 1. Drivers

A scenario takes the `drv` fixture and does not know which driver is behind it.
The interface is deliberately small:

```
launch(os=None, headless=True | "virtual", humanize=False, proxy=None,
       geoip=False, locale=None, fonts=None, extra={}) -> Browser
Browser.new_context() -> Ctx ; Browser.close()
Ctx.new_page() -> Page ; Ctx.cookies() ; Ctx.close()
Page.goto(url) ; eval(js) ; click(sel) ; type(sel, text) ; upload(sel, path)
Page.download(click_sel) -> bytes ; screenshot() -> png ; on_dialog(accept)
```

- **`pkg`** calls `Camoufox(executable_path=..., **opts)` with the options passed
  through unchanged.
- **`pw`** builds the config with `camoufox.utils.launch_options(...)`, which is
  what the README tells a bare-Playwright user to do, then calls
  `playwright.firefox.launch(**that)`.
- **`go`** drives `goapi/cmd/e2edriver`, a small binary (about 150 lines) that
  reads one JSON command per stdin line and answers on stdout by calling only the
  public `camoufox.Launch` API. The Python side is a thin RPC proxy.

If a driver cannot express an option, the test calls
`pytest.skip("<driver>: no <option>")`. It never silently drops the option.
The goapi README still says "No Windows pipe transport" while
`pipe_windows.go` exists, so whether goapi works on Windows is a measurement
this suite makes, not an assumption. A failure there is a finding, not a test
bug.

**Binary selection**, in precedence order:

1. `--binary PATH`
2. `CAMOUFOX_EXECUTABLE_PATH`
3. `--release TAG`, which downloads the platform zip from the fork's release,
   the way a user would

Every run prints the resolved path, the `application.ini` BuildID and the SHA-256
of the zip when one was downloaded (lesson 9: know which binary produced a log).

## 2. Local site, proxy and STUN

One session-scoped server process serves two origins:

- `http://127.0.0.1:P`, the primary origin
- `http://localhost:P2`, a second origin for cross-origin frames and popups

`localhost` counts as a secure context, so Service Worker, clipboard and
geolocation work without TLS.

| Page | Contents | Journeys |
|---|---|---|
| `/login` | Form with client-side validation, POST, redirect, `Set-Cookie` | 4, 5 |
| `/shop` | pushState SPA, infinite scroll, hover menu | 4 |
| `/upload`, `/download` | Multipart receiver; files with known SHA-256 | 4 |
| `/frames` | Cross-origin iframe, `postMessage`, `window.open` popup, `alert`/`confirm`/`prompt` | 4 |
| `/apps` | WS echo, SW offline cache, IndexedDB, bundled short `<video>` and `<audio>`, canvas drawing, a WebGL triangle, clipboard, geolocation | 6 |
| `/fp` | JSON of everything an ordinary page can read: UA, platform, screen, timezone, locale, fonts by width measurement, WebGL vendor, voices, and the same values from dedicated, shared and service workers | 2, 3, 5 |
| `/echo` | The headers (in order), source IP and body hash the server received | 2, 3 |

The server records every request. Scenarios read that record back to compare
what the page reported with what arrived on the wire.

**Proxy.** `proxy.py` implements HTTP CONNECT and SOCKS5 with optional
username/password, and records whether each request crossed it. A test proves
it is not vacuous by asserting the recorder saw the page load.

**Geoip.** The local proxy's egress is loopback, which cannot be geolocated. The
geoip journey therefore passes an explicit public IP (`geoip="<ip>"`), and
expects the timezone and locale that the package's own geoip database maps that
IP to. This checks coherence without depending on the network.

**STUN.** `stun.py` answers binding requests, so the page gathers a
server-reflexive candidate. The expectation is that no candidate carries a LAN
address of the host (enumerated by the test with `socket`), and that the srflx
candidate carries the configured WebRTC IP when one is set.

## 3. Oracles

**A: public documentation.** Every expectation in `oracle/docs.py` carries the
sentence it comes from, quoted, with its file (README, `pythonlib/README.md`, an
API docstring). An expectation with no quotable source does not get written.
This is what keeps the suite from being derived from patch code.

**B: differential against Playwright's Firefox.** Stock Firefox cannot be driven
by Playwright, so the reference is the Firefox build Playwright bundles
(`playwright install firefox`), whose engine version differs from 152. B
therefore compares **behavioural** outcomes only:

- Does the API work?
- Does the form submit?
- Does the downloaded file hash match?
- Does the WS echo arrive?
- Does the SW serve offline?

It never compares numeric or fingerprint values (font widths, canvas hashes),
because those legitimately differ across engine versions and the comparison
would not be about the same thing (lesson 9). Every run prints
`oracle-B: playwright-firefox <version>`. B runs under the `oracle_b` marker and
reuses the `pw` driver pointed at the reference binary.

**C: internal coherence.** About 15 rules, each comparing two independent
sources:

- JS UA matches the UA header the server received.
- `navigator.platform` matches the OS in the UA.
- `navigator.language` matches `Accept-Language`.
- The JS timezone matches `Intl`, and matches geoip when geoip is set.
- The screen is at least the viewport, and `devicePixelRatio` is in a plausible
  range.
- Dedicated, shared and service worker values match the main thread. This rule
  only flags disagreement and is never read as an absolute truth; see lesson 4
  on cross-thread references.
- Reported fonts belong to the spoofed OS. This is measured with the existing
  rendered/refused method: two fallbacks whose widths are checked to differ
  first, and a row with equal floors is INVALID, not a pass.
- WebGL vendor and renderer are plausible for the spoofed OS.
- Voices are plausible for the spoofed OS.
- Two contexts differ in fingerprint, and two pages of one context agree.

**No rule is trusted until it has been seen red.** Each rule has a negative
control that deliberately creates the mismatch (for example a wrong UA injected
through `extra_http_headers`) and asserts the rule fails. A rule whose control
does not go red is reported `VACUOUS` and counts as a failure of the suite.

## 4. Journeys

Each journey runs on every driver unless it states otherwise. "Expect" lines
name their oracle.

1. **Install and launch.** In a fresh venv, `pip install camoufox` (from
   `pythonlib/`), then use the chosen binary. Launch headless, headful and (on
   Linux) `headless="virtual"`; open `/login`; close. Expect: page title read
   back (A); no orphaned browser process after close (checked with `psutil` if
   already installed, else the OS process list); launch time is printed, not
   asserted.
2. **Fingerprint coherence.** For each of `os="windows"`, `"macos"` and
   `"linux"`, open `/fp` and `/echo`. Expect: every rule in C holds, and each
   rule is non-vacuous.
3. **Proxy, geoip and WebRTC.** Load `/fp` through the HTTP proxy and through
   SOCKS5 (with auth). Expect: the proxy recorder saw the traffic; geoip gives
   the timezone and locale the database maps the IP to (A, C); no LAN IP appears
   in the ICE candidates.
4. **Human-like automation.** Log in on `/login` with `humanize=True`; add an
   item on `/shop` after hover and scroll; upload a file and check its hash on
   the server; download a file and check its hash; send `postMessage` across the
   frames; handle a popup and all three dialog kinds. Expect: every step has the
   same outcome as on the reference (B); the page records `isTrusted === true`
   for the input events; a global set by `page.eval` is not visible to page
   script (A: the isolated-world claim in the README).
5. **Multiple contexts and browsers.** Two contexts in one browser, and two
   browsers at once. Expect: cookies and storage do not cross (a login in one
   leaves the other logged out); fingerprints differ between contexts (C).
6. **Ordinary web APIs still work.** Run every widget on `/apps`. Expect: the
   same pass/fail per widget as the reference (B); canvas and WebGL produce a
   non-blank image (the pixel sum is compared with a blank canvas drawn in the
   same page, so the control is guaranteed to differ).
7. **Real sites (`live` marker, never on the PR gate).**
   - Public detector pages (CreepJS, BrowserScan, sannysoft, pixelscan).
   - A Cloudflare-challenge page, Google search and YouTube.

   Expect: the page loads and is not blocked. For the detector pages, only an
   aggregate result is printed: a grade, or a pass count and a total. This repo
   is public and per-vector detail stays out of it, the same rule
   `ci/run_sundial.py` follows. A network failure yields SKIP, never PASS or
   FAIL.
8. **Lifecycle and resilience (`slow` marker).**
   - Open and close 50 contexts in a row.
   - A ten-minute session that navigates the local pages in a loop.
   - Kill the browser process mid-page, then launch again.

   Expect: no errors; the relaunch works; memory growth is printed. A threshold
   is only asserted where `native-tests/test_memory_growth.py` already defines
   one, and that value is reused rather than invented.

## 5. CI and running by hand

**By hand:**

```bash
python3 -m pytest e2e --binary /path/to/camoufox          # local suite, all drivers
python3 -m pytest e2e --release v152.0.4-beta.31-fork.1   # download the release first
python3 -m pytest e2e -m live                              # real sites
```

**PR gate.** Add an `e2e` job to `tests.yml`. It needs `build`, runs on
`ubuntu-24.04` under `xvfb-run`, excludes `live`, and includes `slow`. It sets up
Go for the goapi driver, runs `playwright install firefox` for oracle B, and
uploads results in the existing `.ci-work/results/` format so `summary` reports
it. It joins `gate`.

**`e2e.yml` (dispatch only).** Inputs are `run_id` (a `build.yml` run) or
`release` (a tag), plus `live` (bool). The matrix is:

- `ubuntu-24.04`, with the Linux artifact
- `macos-26` (arm64), with the macOS artifact
- `windows-2025` (x86_64), with the Windows artifact

The macOS and Windows legs cost more runner minutes, so they run only on
dispatch. Each leg prints the host OS next to the result, since a Linux result
is no evidence about Windows or macOS (lessons 3 and 8).

## Error handling

- A missing binary, or a server that cannot bind, fails the session at once with
  the reason.
- An unsupported option on a driver is a SKIP naming the option.
- A network error in `live` is a SKIP.
- A failing check inside a multi-step journey is collected and reported at the
  end of that test (the deferred form from lesson 9's corollary), so one failure
  does not hide the steps after it.

## Out of scope

- Per-vector stealth scores in any output.
- Proxy egress from a real public IP (geoip is tested through an explicit IP).
- Replacing any existing suite. This suite adds to them.
