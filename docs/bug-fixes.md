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

## #397: goapi GrantPermissions forwarded Playwright's names to Juggler, which denied them silently

**Fixed by:** the PR that translates the names in `goapi/permissions.go`. **Found by:** the e2e geolocation arm (#385), whose `go` driver read `denied` after a grant.

**Symptom.** `GrantPermissions(ctx, origin, []string{"geolocation"})` returned nil, then `navigator.permissions.query({name: "geolocation"})` read `denied` and `getCurrentPosition` failed with code 1.

**Root cause.** The names went to `Browser.grantPermissions` unchanged. Juggler uses its own (`ALL_PERMISSIONS` in `TargetRegistry.js`: `geo`, `desktop-notification`, `local-network`, `loopback-network`), and `grantPermissionsToOrigin` allows the listed ones and denies every other name of that list, with no error for a name it does not know. Playwright's Firefox client translates and throws on an unknown name (playwright v1.62.0 `ffBrowser.ts`, `doGrantPermissions`); goapi, which mirrors the Playwright API, did neither.

**Fix.** `jugglerPermissions` maps `geolocation`, `notifications` and `local-network-access` once, and any other name is an error (Juggler's own `geo` included, so a caller sees the API's names only). Playwright's `persistent-storage`, `push` and `screen-wake-lock` are refused too: Juggler has no permission to grant for them.

**Evidence.** `goapi/permissions_test.go` captures the `Browser.grantPermissions` request on a scripted connection. Before the fix: `GrantPermissions([geolocation]) sent [geolocation], want [geo]`, and `GrantPermissions("camera") sent [camera] and returned no error`. After: both tests pass, `go test ./...` in `goapi` passes. Against the macOS arm64 build, granting `geolocation` through the e2e `go` driver reads `granted` and the page gets the position set with `SetGeolocation`.

**What misled the investigation.** A grant that returns nil and then reads `denied` looked like geolocation being broken in goapi, not a name that never reached a permission.

## #333: a Linux claim's generics ignored the shipped fonts.conf

**Fixed by:** the PR that refs #333 (the Latin page; other language groups are #389). **Found by:** the realism review of #325.

**Symptom.** A Linux identity drew `serif` as Nimbus Roman, `sans-serif` as Nimbus Sans, `monospace` as Cousine and `cursive` as Nimbus Sans. A Linux host with the same bundle and conf draws Noto Serif, Noto Sans, DejaVu Sans Mono and Z003 (`fc-match -s`, e2e run 41633068315).

**Root cause.** `gfxPlatformFontList::CamouGenericCandidate` (`font-list-spoofing.patch`) answers a generic from OS-agnostic rows (`kCamouSerifRow`, `kCamouSansSerifRow`, `kCamouMonospaceRow`) whenever a launch mask or a per-context list applies. The rows start with `Times`, `Helvetica` and `Courier New`, which the #325 alias rewrite turns into Nimbus Roman, Nimbus Sans and Cousine. The launcher also wrote `font.name-list.*` for Linux from three hand-synced copies (Cousine, Tinos, Arimo); the browser never read them, because the table answers first.

**Fix.** `gen-font-aliases.py` writes the conf's chain for each generic into `FontAliasesLinux.hpp`, read as `FindGenericFamilies` reads it. For a Linux claim `CamouGenericCandidate` takes the first chain family the list admits, on every host. The Linux entry is removed from the three launcher copies and their tests.

**Alternatives.** Removing the rows for Linux and letting fontconfig answer would have left a Linux claim on Windows or macOS with no fontconfig at all (the host pref path), so the same claim would have drawn different faces on different hosts.

**Evidence.** See the PR.

**What misled the investigation.** The three prefs copies looked like the fix already shipped, and then like dead code. They are read only on the Linux pref path, but that path is what drew the symptom on a Linux host: with the prefs present, `AddGenericFonts` takes the base pref path, whose table step resolves the row key `times` through the virtual lookup and draws Nimbus Roman; without them it takes `FindGenericFamilies`, whose table step resolves the key through the scope-qualified base lookup, finds no family called `times` on a GTK host, and falls into fontconfig's own loop, which gives the conf. So deleting the prefs alone moves a Linux host to the conf, and the browser change is what fixes Windows and macOS hosts, where the alias rewrite makes the row key resolve. `fc-match -s` also lists host-order fallbacks past the third family (Cascadia Code, FreeSerif), which Gecko never reads: it stops at `max_generic_substitutions`.

## #390: a Playwright shard errored at setup when the upstream test server could not bind its port

**Fixed by:** the PR that makes `ci/pw_camoufox_plugin.py` bind the upstream test servers on kernel-chosen ports. **Found by:** Tests run 41633372099, job `Playwright 2/6` (job 125920147366), on #382.

**Symptom.** The first pytest invocation of the shard ended `278 errors in 13.93s`, every one at setup of the session fixture `start_server`: `twisted.internet.error.CannotListenError: Couldn't listen on 127.0.0.1:41247: [Errno 98] Address already in use.` The three later invocations of the job, each with its own server, passed. No test body ran, so the browser and the PR were not involved.

**Root cause.** playwright-python v1.62.0 `tests/server.py` draws a server's port in `Server.__init__` (`find_free_port`: bind 0, read the number, close; `:56-60`, `:166`) and listens only in `start()` (`:293`, `:326`). Nothing holds the number in between, and `tests/server.py` builds `TestServer()` (an HTTP and an HTTPS server) at import, so the gap runs from collection to the first test. Two things can take the number in it:

- the other server: the HTTP server draws, closes, the HTTPS server draws and can get the same number, and the second `listen` fails exactly as in the log (HTTP listens first, `:369`). Measured on Linux (kernel 7.2, Python 3.12, port range 32768-60999): 400000 consecutive `find_free_port()` calls returned 38 equal neighbours, about 1 in 10000, and every port was odd (14115 candidates);
- another process opening a socket in the gap. Measured on the same host: every outgoing connection's source port out of 20000 was even, so a source port cannot be the odd 41247. Only another `bind(0)` or an explicit bind of that number could.

The log does not name the holder. 41247 is odd, which fits a `bind(0)` draw (the same one twice) and does not fit a connection's source port.

**Fix.** `install_kernel_chosen_ports` (called from `pytest_configure`) wraps `Server.start`: it sets the server's port to 0 for that call, so the first `listenTCP` or `listenSSL` asks the kernel for it, then reads the bound number back and rewrites `PORT`, `EMPTY_PAGE`, `PREFIX` and `CROSS_PROCESS_PREFIX` before anything uses them. The `::1` listen then reuses that number. No port is held or drawn ahead, so neither candidate has a window. Upstream's files are untouched; the plugin asserts the shape it relies on (`start` not overridden, both reactor calls present, the URLs carrying the drawn port, a port read back) and fails the run if a Playwright bump changes it. Not done: retrying, or catching `CannotListenError`, which would hide the same clash in the next server.

**Evidence.** `ci/tests/test_pw_server_ports.py` runs a stand-in of upstream's server shape on real sockets. With the fix switched off, the same-port case fails with `CannotListenError: Couldn't listen on 127.0.0.1:41247` and the taken-port case with `Address already in use`. Against the real upstream `tests/server.py` v1.62.0 with twisted 25.5.0 on Linux, both servers drawn 41247: unfixed `CannotListenError Couldn't listen on 127.0.0.1:41247: [Errno 98] Address already in use.`; fixed, the two servers listen on 43795 and 34769. See the PR for the Tests run.

**What misled the investigation.** The issue offered "another process took it as a source port" as one of two equal readings. On Linux, `bind(0)` and `connect()` take opposite port parities, so the odd number settles which kind of draw produced it.

## #310: the observer and goapi browser tests never ran on macOS or Windows

**Fixed by:** the PR that adds both gates to the macOS and Linux legs of `e2e.yml` (Windows follows #345). **Found by:** the observer harness failing on its first Windows run.

**Symptom.** `ci.run_observer` (#303) and `ci.run_goapi` (#301) ran only on Linux, in `tests.yml`, and a pull request never builds macOS or Windows, so a regression in the observer or the Go launcher on those hosts reached a release unseen.

**Root cause.** The runners were wired to the Linux jobs alone. The first Windows run (e2e run 40615989606, `e2e (windows-x86_64)`) then failed three of the four observer tests (`[observer] 1 passed, 3 failed (4 collected)`), after they printed their PASS lines: `PermissionError: [WinError 32] ... observer\gecko.log`. `marionette_driver` writes `./gecko.log` and deletes the old one when it starts the next browser, and Windows will not delete a file the previous browser still holds. The scripts start a second session after the first closes (armed, then disarmed), so each of those hit it at the second start (`test_readout.py` starts one session and passed).

**Fix.** `e2e.yml` gets three steps ahead of the journeys, on every leg but Windows: unpack the browser (`e2e/util.py --zip|--release` prints its path; the journeys' `binary` fixture now calls the same `fetch_release` and `unpack`), `ci.run_observer`, `ci.run_goapi`. A red gate does not skip the journeys (they run `!cancelled()`), and a dispatch with `probe` or `k` leaves the gates out. `harness.Session` gives each session a gecko log in its own temp directory, which also stops the tests writing `gecko.log` into the source tree. No dependency is added: `marionette_driver` is already in `browser/tests/build-tester/requirements.txt`. The gates stay off the Windows leg: for an identity that is not Windows, every browser process spends about 6 CPU-seconds indexing the bundled fonts (#345), and on a loaded runner goapi's 30 s main-context wait expires (`TestScrollToBottom`, `TestScrollToAndBy`, job 123480161524). Raising the timeout would hide it.

**Evidence.** See the PR.

**What misled the investigation.** The Windows log showed PASS lines before the traceback, which reads as a passing test with noisy teardown; the exit code and the `PermissionError` frame are what failed the run.

## #317: Math.pow of a negative number to the power 0.5 or -0.5 had the wrong NaN sign on Apple silicon

**Fixed by:** the PR that closes #317. **Found by:** the `windows-crt-math` guard in the macOS parity run (41565897021), `FAIL: cold pow: 3 of 1396`.

**Symptom.** `windows-crt-math.py` on macOS arm64, for a Windows identity: 3 of 1396 `Math.pow` results and the same 3 of `**`, cold and hot, differ from stock Firefox on Windows. `sin`, `cos` and `tan` match 1677 of 1677.

**Root cause.** Not rounding, and not FMA contraction. The three pairs are `x < 0` with `y` of 0.5 or -0.5, and the result is NaN with the other sign bit: Windows `fff8000000000000`, the macOS app `7ff8000000000000`. `js::ecmaPow` (`js/src/builtin/Math.cpp`) answers a finite non-zero `x` with `y == 0.5` as `std::sqrt(x)` and `y == -0.5` as `1.0 / std::sqrt(x)` before it reaches `pow_libm_or_fdlibm`, so before the hook that calls `ucrt_pow`. Its comment calls the square root bit-deterministic across platforms, which holds for every result except a NaN: the sign of the NaN a square root of a negative number returns is the CPU's, `SQRTSD` on x86-64 gives `fff8…` and `FSQRT` on arm64 gives `7ff8…`. A standalone C program on the M1 prints `7ff8000000000000` for `sqrt(-2.5)` and for `1.0 / sqrt(-2.5)`. Linux x86-64 was green only because it has the same instruction as Windows. The JIT has the same shortcut: `MPow::foldsConstantPower` (`js/src/jit/MIR.cpp`) turns a constant exponent of 0.5 into `MPowHalf`, which emits `sqrtsd` or `fsqrt` inline.

**Fix.** In `windows-crt-math.patch`, with `javascript.options.use_ucrt_math` on, `ecmaPow` leaves a negative `x` to `pow`, and `MPow::foldsConstantPower` keeps a call to `ecmaPow` for both exponents, since the sign of `x` is not known at compile time. `ucrt_pow(-2.5, 0.5)` and the three failing pairs return `fff8000000000000` (compiled with `-ffp-contract=off` on the M1), the value Windows gives. A positive `x` keeps the square root, as stock Firefox on Windows does. Not tried: a fixed NaN constant at the call site, which would be a special case for one pair of inputs. The probe now also runs the literal exponents `Math.pow(x, 0.5)` and `Math.pow(x, -0.5)` hot, so the `MPowHalf` path is compared with the Windows results; before this the probe passed its exponents from an array and Ion never compiled a square root.

**Evidence.** On the fork.2 macOS arm64 app the guard prints `cold pow: 1393/1396`, `hot pow: 1393/1396`, `literal exponent +-0.5, every call: 3/6` and exits 1. On a macOS arm64 build of this branch (build run 41600986722) it prints `cold pow: 1396/1396`, `hot pow: 1396/1396`, `literal exponent +-0.5, every call: 6/6`, `constant-folded: 6/6`, sin, cos and tan 1677/1677 cold and hot, the `use_ucrt_math` off control still differing, and exits 0. On a build of this branch with the `MIR.cpp` hunk removed and the `ecmaPow` hunk kept (probe branch, build run 41643031690) cold and hot pow are 1396/1396 but the literal arm is `3/6` and the guard exits 1, so the arm reaches the `MPowHalf` path and the hunk is needed. The arm calls each literal function 100000 times per pair, far above `javascript.options.ion.threshold` (1500), and keeps every result.

**What misled the investigation.** The issue called it a last-bit difference in `Math.pow` and `Math.exp`. The probe's `exp` is `a ** b` on the same inputs, not `Math.exp`, so there is one failure, and the printed hex shows it is a sign bit; the likely causes for a last-bit difference (FMA contraction, a libm fall-through) were all ruled out by reading the bits first. The patch comment saying SpiderMonkey's square-root shortcuts are the same on every platform was true for numbers only.

## #378: the Python and TypeScript launchers handed a symlinked or ".." executable path to the macOS app

**Fixed by:** the PR that closes #378. **Found by:** reading both launchers for the shape of #362, then launching the fork.2 macOS arm64 app through bare Playwright 1.58.

**Symptom.** `[err] Couldn't load XPCOM.` from `playwright.firefox.launch(executable_path=...)` for a symlink to the binary and for a path with a `..` component. An absolute path and a plain relative path launched.

**Root cause.** Python's `launch_options` converted only a `str`, with `os.path.abspath`: absolute, `..` collapsed, symlinks kept, and a `Path` argument untouched (`python/src/camoufox/utils.py`, the `isinstance(executable_path, str)` check). TypeScript used `path.resolve` (`typescript/src/utils.ts`): the same, minus the `Path` case. The launchers read `application.ini`, `properties.json` and the fonts from beside that path, so a symlink kept outside the build also failed earlier, with a missing file, which hid the XPCOM error.

**Fix.** Python resolves the value once where it enters, for `str` and `Path` alike, with `os.path.realpath`. It sits above the version read, the GPU probe and the returned `executable_path`, which all use the one value. TypeScript uses `fs.realpathSync(path.resolve(p))` when the file exists, and leaves a missing binary to the existing read of its files, which names `application.ini`. The Python function imports `realpath` and `fspath` by name, because `launch_options` has an `os` parameter that shadows the module; a first attempt with `os.path.realpath` failed on that.

**Evidence.** Python `tests/test_executable_path_resolution.py` (symlink and `..`, each as `str` and as `Path`) and TypeScript `executable_path resolution` in `tests/launch.test.ts` (symlink, `..`, a missing binary), none of them needing a browser. On main: Python 3 of 4 red (symlink as `str` and `Path`, `..` as `Path`; `..` as `str` already passed), TypeScript 1 of 3 red (the symlink; `..` and the missing binary already passed). After the fix all pass.

**What misled the investigation.** The goapi fix for #362 was written from a test that used `..` and called it a relative path, so the same shape looked like it applied to a plain relative path in the other launchers too. It does not: only `..` and symlinks fail, and each launcher already normalized one of them.

## #338: stock-gpu-parity crashed on a hosted Windows runner

**Fixed by:** the PR that refs #338; #338 stays open for `windows-crt-math` on macOS (#317) and the macOS runner's GPU spelling. **Found by:** e2e run 41584656260, `stock-gpu-parity.py` on the Windows x86_64 build of main.

**Symptom.** The guard died with a traceback, not a verdict: `KeyError: '{"vendor":"Google Inc. (Microsoft)","renderer":"ANGLE (Microsoft, Microsoft Basic Render Driver (0x0000008C) Direct3D11 vs_5_0 ps_5_0), or similar"}'` from `webgl._pin`.

**Root cause.** Three layers, each hidden by the one above.
1. `nearest_device` looked up the host GPU's own recorded devices. The earlier gate (`utils.plan_rendering`: a software renderer matches any GPU) let Microsoft Basic Render Driver through, but fpgen never recorded it on Windows, so the lookup raised. Linux's llvmpipe is recorded, which is why no Linux run ever reached this.
2. Once a device came from the whole OS, its disagreement count was `sum(stock.get(k) != v for k, v in recorded.items())`: it counted only the device's own keys. A device with no WebGL2 records fewer values, so it looked closest to a stock that has WebGL2, and the probe page threw `ReferenceError: WebGL2RenderingContext is not defined` and never reported (`did not report within 120s`).
3. The guard then expected Camoufox to claim the host's GPU. `webgl_for_gpu` refuses a GPU fpgen never recorded (`ValueError: No recorded WebGL data for vendor 'Google Inc. (Microsoft)'`), so the identity is the chosen device's GPU, and its `7937` renderer string differs from stock's by construction.

**Fix.** `nearest_device` takes the OS's recorded devices when the host GPU is not recorded, and counts a value stock reports and the device lacks as a disagreement (`stock.keys() | recorded.keys()`). For an unrecorded host GPU the guard expects the chosen device's GPU and does not compare the renderer string `7937`. A recorded GPU, including llvmpipe, takes the same path as before. Tried and rejected: pinning the host's own vendor and renderer (`launch_options` raises, layer 3).

**Evidence.**
- Red to green, `python/tests/test_stock_gpu_parity_device.py`: the unrecorded Basic Render Driver raised `KeyError` on the first commit's parent; a stock with half its WebGL2 values changed picked a device without WebGL2 until the count included missing keys.
- Windows, same build (41570521384), guard alone: `KeyError` (run 41584656260), then `WebGL2RenderingContext is not defined` (41595395212), then a wrong claimed GPU (41595985110), then `ValueError` from the host-GPU pin (41596630988), then `1/1 guards passed` (41598036743).

**What misled the investigation.** Each failure looked like the last one's cause fixed: the lookup crash hid the missing-key count, which hid the claim. The guard's own docstring said a software renderer "is not gated here", which made the first crash read as an oversight in one line rather than a path never run on a host whose software GPU is unrecorded. This guard passes on Windows only because the identity differs from the host, so green here says the browser-owned values follow stock, not that the host's GPU is claimed.

## #375: the Skiplist audit failed on every run once pip 26.3 came out

**Fixed by:** the PR that closes #375. **Found by:** Tests run 41553986984 on PR #374, `Skiplist audit`, with no code in the PR that could reach it.

**Symptom.** `ci.run_skiplist_audit` died while installing the upstream suite's requirements: `ERROR: Distributions from PyPI cannot declare direct URL dependencies. autobahn depends on web3[ipfs] @ git+https://github.com/ethereum/web3.py.git#v6.0.0-beta.9#egg=web3 ; extra == "all"`. The same job had passed on main about nine hours earlier (run 41475235918).

**Root cause.** `make_venv` in `ci/suite.py` ran `pip install --upgrade pip` in the fresh venv, so the suite's install ran under whichever pip PyPI had that day. playwright-python v1.62.0 pins `autobahn==23.1.2` in `local-requirements.txt`, and that release lists a `git+https` dependency in its `all` extra, which nothing in the suite selects. pip 26.3 (published 2026-11-02 20:34Z, between the two runs) applies PyPI's direct-URL rule to extras as well: "Apply PyPI's direct URL dependency restriction to extras and cached wheels" (pypa/pip#14341). Earlier pip checked only the dependencies it installed.

**Fix.** `make_venv` installs `pip==PIP_VERSION` (26.2.2) instead of upgrading. The constant carries the reason, and says to raise it once a venv for the current tag installs under the newer pip. Alternatives rejected: skipping the audit or letting the install fail quietly (the audit is the check), `--no-deps` (drops the suite's real dependencies), and a constraint on autobahn (the pin is upstream's, and a different autobahn is not the suite the tag shipped with).

**Evidence.**
- Same `local-requirements.txt` (v1.62.0), fresh venvs, this host: `pip install --upgrade pip` gave pip 26.3 and the install exited 1 with the error above; `pip==26.2.2` exited 0 with autobahn 23.1.2, pytest 9.0.3 and Twisted 25.5.0 installed.
- Red to green: `test_the_suite_venv_pins_pip` records the commands `make_venv` runs. On the old `ci/suite.py` the pip install is a bare `pip` (`assert ['pip'] == ['pip==26.2.2']`); with the fix it passes.

**What misled the investigation.** The failing step is the audit, so the audit's skiplist looked like the suspect, but the error came from `pip` before any test ran. Nothing in the PR under test could have caused it: a red check with no related diff is a change in the environment, and an unpinned tool is where one comes in.

## #316: the stalled-apt tests failed on a loaded macOS host

**Fixed by:** the PR that closes #316. **Found by:** `python -m pytest ci/tests/test_apt_install.py` on a macOS host that was also running a patch-guard run.

**Symptom.** `test_a_stalled_update_fails_the_step_and_names_the_command` failed with `assert [] == ['update']` and `test_a_stalled_install_fails_the_step_and_names_the_command` with `assert 'apt-get install' in '::error::apt-get update did not finish in 1s\n'`. Linux CI never failed them.

**Root cause.** Both tests ran the real script with `APT_TIMEOUT=1` and a stand-in `apt-get` shell script, and expected the 1 s budget to expire on a command that was already running. `ci/apt_install.py` hands the budget to `subprocess.run(["sudo", "apt-get", *args], timeout=LIMIT)`, and that timer starts when `sudo` is spawned, not when the stand-in has written its first line. The stand-in has to start two shells and append to the call log inside the budget. When that takes longer than 1 s, the process is killed before it records anything (`calls == []`), and in the install test the healthy `update` step is the one that runs out of time, so the message names `update`. The script was right in both cases. The test measured its host's process start-up time against a fixed second. A chain of `sudo` and `apt-get` stand-ins took up to 0.49 s to start on an idle machine.

**Fix.** The two stall tests no longer wait for a timer. They replace `subprocess.run` with one that raises `TimeoutExpired` for the command under test, and assert what the script does with it: it passes `LIMIT` as the timeout, exits 124, prints `::error::apt-get <command> did not finish in <LIMIT>s`, and does not run the install after a stalled update. The other three tests, which run the real script with a 900 s budget, are unchanged. Alternatives that were rejected: a longer budget in the test (still a race against start-up time, and a loosened timeout), and a retry (hides the fault). What the new tests do not check is that Python kills a real child at the deadline. That is `subprocess.run`'s documented behaviour, not this script's.

**Evidence.**
- Red, deterministic: the old tests with a `sleep 1.5` before the stand-in's first line fail both, with the issue's exact output (`assert [] == ['update']` and `apt-get update did not finish in 1s`).
- Red, under load: 60 busy loops and 4 pytest processes at a time, 20 runs of the old file gave 19 runs with a failure (5 with one failing test, 14 with two).
- Green: the same load, 20 runs of the new file, 20 passes.
- The new tests can fail: without `timeout=LIMIT` in `apt()` two of them fail, and with the exit check removed so the install runs after a stalled update three do.

**What misled the investigation.** The message `apt-get update did not finish in 1s` in the install test reads like a stall in the script's own update step, but the update there is `exit 0`. Nothing stalled; the budget was simply shorter than the time to start the stand-in.

## #359: getter-cost-parity was red on the hosted macOS runner

**Fixed by:** the PR that closes #359. **Found by:** the macOS leg of the guard, red on and off with no code change.

**Symptom.** `getter-cost-parity.py` failed intermittently on the hosted macOS runner, on getters that differed from run to run, and passed on Linux.

**Root cause.** Two causes, one in the browser and one in the measurement.
- The browser. `navigator.hardwareConcurrency` did a per-context store read and a config lookup on every call, in `Navigator::HardwareConcurrency` and `WorkerNavigator::HardwareConcurrency`. Stock does neither. On the Linux runner the worker getter cost 20-26 ns more than its untouched control, and the main-thread one 16-20 ns more. A launch-level identity (store miss, then config lookup) cost 4-12 ns more than a context identity (store hit, early return), which is the gap the guard compares two columns across. The config lookup itself measured 3-6 ns natively (2.7 ns on a miss, 5.7 ns on a hit, M1 Pro, standalone benchmark), so the rest was the store read and the thread-local memo behind it, on every call.
- The measurement. The guard's docstring said: "Each figure is the fastest of several rounds over two launches, so a busy runner inflates both browsers rather than one." That does not hold on a hosted macOS VM. Two launches of the same browser differ there by 15-30 ns per getter (Linux: 1-3 ns), and the quietest launch of one browser against the quietest of the other is a comparison of two noise draws, with 30 ns as the gap being decided. A minimum over two cannot be stable at that spread.

**Fix.**
- `zz-stock-cost-parity.patch` now resolves the spoofed hardwareConcurrency once per `RoverfoxStorageManager` generation per navigator, in the `nsScreen::CamouSpoofed` pattern: `Navigator` and `WorkerNavigator` keep `{generation, user context id, value}` and refill only when the generation or the context id changes. A launch identity and a context identity take the same single comparison, so the two paths cost the same and there is no skip branch. Stock's work still runs first. The generation is an atomic: `BumpGeneration` is `fetch_add(release)` and `Generation()` is `load(acquire)`.
- The guard compares medians of `LAUNCHES = 6` launches, and scales Camoufox's cost by stock's control cost over Camoufox's control cost before the slower test (`verdict()`). `SLOWER_FACTOR` 2.0, `FASTER_FACTOR` 2.0 and `MIN_GAP_NS` 30 are unchanged. The same N runs on every OS. The cold first read keeps the fastest launch, because a lookup that blocks on the parent does so every time. A control that differs from stock by the slower test fails the run as not comparable, unscaled.
- A new guard arm launches with an explicit `navigator.hardwareConcurrency` that is not the host's core count (the launcher snaps an unset value to the host's, which would make the arm vacuous) and requires the main thread and a worker to report it on the first read.

What the guard compares across: separate processes (stock Firefox against Camoufox, and launch against context), on one page and one machine. Two things make them comparable: an untouched control getter in each scope (`screen.orientation.type` in a window, `navigator.onLine` in a worker) whose ratio between the browsers scales the rest, and the control failing the run when it differs. The first establishes that the probe and the machine's speed moved together, not that the binaries differ only by the patch.

How N was chosen. Simulation over every pair of N-subsets of 8 launches per browser, on fresh data from the fixed build (Linux run 41408378219, macOS e2e run 41434368730 on build 41408406642), six getters, both arms: 0.0% false failures at N = 4, 6 and 8 on both OSes. The 3x negative control (Camoufox values times 3) was caught in 100% of cells except mac `wkHW` N=4 launch (99.5%). N=4 reaches 2.01x on mac `innerHeight` (a gap of +24 saves it), N=6 peaks at 1.79x / +20 ns (mac) and 1.55x / +34 ns (Linux, a worker getter whose ratio stays under 2), N=8 at 1.53x / +13 ns. N=6 is the smallest where each limit holds on its own. The subsets are drawn from the same 8 launches, so they are not independent draws. About +5 minutes on macOS over two launches.

**Evidence** (Linux run 41408378219, median of 8 launches, Camoufox minus stock, launch / context):
- main `hardwareConcurrency` +29 / +32, against controls `screen.orientation.type` +19 / +22 and `navigator.onLine` +18 / +18, and untouched `innerWidth` +28 / +28;
- worker `hardwareConcurrency` +12 / +14, against its control `navigator.onLine` -1 / -1;
- launch minus context: 0 ns on every getter and control but one (worker `onLine`, -1 ns).
- macOS (e2e 41434368730) worker `hardwareConcurrency` +10 / +9 against a control +3 / +2, where the build before the fix had +47 / +24.
- Red to green: `ci/tests/test_getter_cost_verdict.py` holds `verdict()` against a getter at three times its control against stock's one times (fails), a uniformly 2.2x slower build (passes), equal costs (pass), a ratio over 2 under 30 ns (passes), and an early-return getter (still fails FASTER). Replacing the scaled cost by the raw one turns the uniform-build test red; removing the gap clause of the faster test turns the early-return test red. The real-browser negative control, a slow getter added on a probe branch and run through Linux CI, was never in this PR.

**What the guard can see.** A regression of about 3x its control (99.5-100% of simulated cells on the fixed build's data; 88-100% on the pre-fix mac data at N=4). Not an excess of 20-30 ns: run on the build before the fix, the same rule fails mac `wkHW` 4.5% of the time at N=4 (2.27x, +60 ns), 0.5% at N=6 (2.04x, +51 ns) and 0% at N=8. The evidence that the fix removed that excess is the probe tables above, not the guard going green.

**Residual, stated as measured.** The worker `hardwareConcurrency` still costs about 12-15 ns over its control on Linux (+12 / +14 against -1 / -1), main-thread about 10-14 ns over its controls: under `MIN_GAP_NS` (30), not zero. The normalised cost of Camoufox's getters against stock's is still about 1.5-1.86x on the runner. The config lookup measured 3-6 ns; the rest of the per-getter excess also sits on getters the fork does not touch: `innerWidth`, `innerHeight` and `screen.orientation.type` read +17 to +33 ns over stock on Linux. That it comes from the build having no PGO or LTO is inferred from the mozconfig, not isolated by a build with them. No PGO issue is filed: one machine pair is not cross-machine evidence.

**What misled the investigation.**
- A control-normalised ratio per launch does not tighten the spread (its CV was equal or looser), which is why the fix is a median and not a better ratio. It was tried first.
- Mac local runs showed a FASTER failure (39 ns against 71) that was a loop artefact: `colorDepth` and `pixelDepth` share `nsScreen::PixelDepth`, and `pixelDepth` read 85 ns in the same launch.
- The new guard arm failed once (`first page read=8 first worker read=8` for a requested 3, probe run 41438746894, job 125272343860) while the same browser passed in the PR's run. Not the browser: with no `os`, the launcher draws a random identity, and on an Apple Silicon draw `coherence.py` snaps the user's core count up to 8 (`appleSiliconCores`, `_repair_apple_silicon_cores`). The arm now launches as `windows`.
- The first fix read is not a fail-open: a navigator that has not resolved a value returns stock's, so the guard's new arm needs an explicit value to be non-vacuous.

## #362: the macOS app exited with "Couldn't load XPCOM." when the executable path had a "..", or was a symlink

**Fixed by:** the PR that references #362. **Found by:** a developer Mac, where every launching goapi test failed with `camoufox: Browser.enable: juggler: EOF` after 0.01 s.

**Symptom.** `Browser.enable: juggler: EOF` at once, and with `WithDebug(true)` the single line `Couldn't load XPCOM.`. The same app started from a shell with an absolute path.

**Root cause.** The macOS app finds libxul from the path it is started with. `Launch` handed `WithExecutablePath`'s value to `exec.CommandContext` unchanged. Started by hand, `Camoufox.app/Contents/MacOS/camoufox --headless --version` printed the version for the absolute path and `Couldn't load XPCOM.` for each of: a path with a `..` component and a symlink to the binary. A plain relative path (`Camoufox.app/Contents/MacOS/camoufox`) launches. The first write-up of this entry said a relative path fails too; it had tested `../x/Camoufox.app/...`, which has a `..`, and the mistake was found while checking the Python launcher (#378). The reporter's own spelling is not recorded in the issue, so that one of these three was the reporter's is an inference; the symptom and the output match.

**Fix.** Just before it starts the browser, `Launch` resolves the path the way `exec` does (`exec.LookPath`: a bare name is searched on PATH, a path with a separator is checked as given), then makes it absolute and resolves symlinks (`filepath.Abs`, `filepath.EvalSymlinks`). A missing binary now fails with `camoufox: resolve executable path: ...` instead of the browser's start error. A first version used `filepath.Abs` alone and turned a bare `camoufox` into `<cwd>/camoufox`, which broke a name found on PATH; the `path` subtest covers it. The Linux launch uses the same path, so the fontconfig lookup in `launchEnv` also gets the real location.

**Evidence.** `TestLaunchResolvesTheExecutablePath` launches through four spellings (a plain relative path as a control that works unresolved, `..`, symlink, bare name on PATH). Red before the fix: `..` and symlink with `Browser.enable: juggler: EOF` (the bare name went red only against the first version of the fix, which used `filepath.Abs` alone); green after, 4 of 4, three runs in a row, with the fork.2 macOS arm64 app (macOS 15.7.4, Go 1.27.3, scratch HOME). The existing launching tests passed with a clean absolute path before and after.

**What misled the investigation.** The issue ruled out the environment, the arguments and the inherited pipes, and it did. A path that is spelled differently is none of those, and a shell test used an absolute path while `go test` was driven with whatever `CAMOUFOX_BIN` held. My first attempt to reproduce passed for the same reason: it used a clean absolute path. The failure appeared only when a probe test took its path from `$PWD/../..`.

## #371: TestWatchMutations raced the page's own timer

**Fixed by:** the PR that closes #371. **Found by:** `goapi (browser)` in Tests run 41405543370 on PR #364, whose diff did not touch the test. It failed again on main at 4ab01128 (Tests run 41425224297, job 125231861359, 8.71 s), so it was not rare.

**Symptom.** `mutation_test.go:72: timed out waiting for mutation`, `--- FAIL: TestWatchMutations (9.60s)`. The same test passed on the previous head of that PR and on two other PRs running at the same time.

**Root cause.** The test page appended its `<div>` from `setTimeout(..., 100)`, which starts at load. The test armed `WatchMutations` only after `Goto(DOMContentLoaded)` returned. When arming took longer than 100 ms, the append had already happened, nothing mutated afterwards, and the test waited out its 5 s.

**Fix.** The timer is out of the page. The test appends with `p.Evaluate` after `WatchMutations` returns, so the mutation is ordered strictly after the observer exists. The DOM is shared across worlds, so an isolated-world append still mutates. Raising the timer's delay would only have moved the threshold.

**Evidence.** Old test with a 300 ms `time.Sleep` between `Goto` and `WatchMutations`: timed out 3 of 3 runs. Fixed test, no sleep: passed 3 of 3. Fixed test with the same 300 ms sleep: passed.

**Checked and left alone.** `wait_test.go` (200 ms timer) uses `WaitFor`, which polls state, so a timer that fires before the call is armed leaves the element already visible. `binding_test.go` (1500 ms timer) is a negative control: a slower runner only makes the late listener later.

**What misled the investigation.** Nothing; the log line named the wait. The red run was not available from CI, so the gap was injected to make the race deterministic.

## #358: the Windows build lacked chrome://global/content/defaultagent/, a page could tell it from Firefox

**Fixed by:** the PR that closes #358. **Found by:** `contentaccessible-parity` on the fork.2 Windows build, the first run of that guard on Windows after #338.

**Symptom.** The guard reported one difference from stock Firefox 158.0.1 on Windows: `omni.ja|content|global: MISSING vs stock -- chrome/toolkit/content/global/defaultagent/default-browser-notification-privacy-image.svg`. A page can load that file from stock Firefox (`<img src="chrome://global/content/defaultagent/default-browser-notification-privacy-image.svg">`) and not from Camoufox.

**Root cause.** `browser/assets/base.mozconfig` sets `--disable-default-browser-agent`. `toolkit/moz.build` then skips the directory that holds the file: `if CONFIG["MOZ_DEFAULT_BROWSER_AGENT"]: DIRS += ["mozapps/defaultagent"]`. That directory's `jar.mn` is what registers `content/global/defaultagent/...svg` in `toolkit.jar`, so the file never reaches `omni.ja`. The `global` package is `contentaccessible=yes`. The agent's gate is `CC_TYPE == "clang-cl"`, which the Windows cross build satisfies (target `x86_64-pc-windows-msvc`), so the stock Windows build has the file and no other OS does.

**Fix.** `contentaccessible-parity.patch` lists the same file again in `toolkit/content/jar.mn` under `#ifdef XP_WIN`, from the same source path (`/toolkit/mozapps/defaultagent/assets/`). The agent stays disabled. This is the same shape as the crash reporter pages in that patch. The bytes match the recorded Windows manifest: SHA-256 `049284011a35af8bfead24032f90d214f13db34d371abcf66ad37c9451421c47`. The alternative, building the agent's directory without the agent, was not tried: that directory's `moz.build` also compiles the agent.

**Evidence.** Red: e2e run 41051584695, job 124048727857, on a probe branch that ran the guard. Green: see the PR for run and job ids.

**What misled the investigation.** Nothing was misleading, but the guard could not run on Windows before #338, so the difference sat unmeasured since the mozconfig line was written. A Linux or macOS green says nothing about it (lesson 3).

## #353: the build-tester crashed on Windows printing box-drawing characters

**Fixed by:** the PR that closes #353. **Found by:** a probe run of the build-tester against a Windows build zip on a GitHub Windows runner.

**Symptom.** `python -m ci.run_build_tester` exited 1 on Windows before grading, and the gate reported `build-tester exited 1 without writing build-tester-result.json`. The child's traceback ended in `UnicodeEncodeError: 'charmap' codec can't encode characters in position 2-61` at `print(f"\n{'─' * 60}")` in `scripts/runner.py`.

**Root cause.** The suite's report is written with box-drawing characters, check marks and em dashes (`runner.py`, `certificate.py`). Python takes the encoding of a piped stdout from the Windows locale, which is cp1252 and has none of them. On Linux and macOS it is UTF-8, so the suite never failed there.

**Fix.** `scripts/run_tests.py`, the one entry point of the suite, reconfigures stdout and stderr to UTF-8 before it prints anything, so every print in the suite is covered. The alternative, dropping the non-ASCII characters, would have changed the certificate and every message that uses them for one platform's locale. Setting `PYTHONUTF8=1` in the caller would hide the crash for that caller only, and the next one to run the suite would hit it again.

**Evidence.** `test_build_tester_prints_box_drawing_under_a_cp1252_stdout` runs `run_tests.main` in a child with `PYTHONIOENCODING=cp1252` and a stand-in suite that prints a box-drawing line. Without the fix it fails with the `UnicodeEncodeError` above; with it, it passes and the bytes on stdout decode as UTF-8.

**What misled the investigation.** Nothing; the cause was in the traceback. The class is the same as #311 and #314: a script that assumed Linux and macOS defaults.

## #338: eleven patch guards could not run, or measured nothing, on Windows and macOS

**Fixed by:** the PR that closes #338. **Found by:** runs of the guards on the fork.1 macOS app and on e2e probe branches against the fork.2 Windows and macOS builds.

**Symptom.** On Windows, `input-ack-backstop` died on `signal.SIGKILL`, `contentaccessible-parity` and `stock-gpu-parity` called `unzip` and `gpg` in ways Git's msys builds mishandle, `worker-config-reads` ran 1-5 contexts in 60 s, and the guards that needed Xvfb or `/proc` failed before measuring. On macOS the guards that need Linux tools started a virtual display that does not exist, and `windows-keyboard` and `system-font-alias-stall` read the host and compared nothing.

**Root cause.** Each guard assumed Linux. `os.kill(pid, signal.SIGKILL)` has no Windows spelling. Git's msys `gpg` prefixes the working directory to an absolute Windows path. Git's msys `unzip` reported "filename not matched" for patterns that match, for a cause not found. Four spinning workers on a 4-vCPU Windows runner starve the start of a new content process (61 s). `contentaccessible-parity` had one manifest, recorded from Linux Firefox, so it could not be compared with any other OS.

**Fix.** `ci/run_patch_guards.py` keeps `LINUX_ONLY` (five guards whose subject is Linux) and adds `NOT_ON` for the two guards that do not apply on one platform for that platform's reason; the runner counts them apart from the passes and prints the reason. Guards that only needed a display use the host's. `input-ack-backstop` kills with psutil, `worker-config-reads` uses two workers on Windows, `stock-gpu-parity` and `contentaccessible-parity` unpack with 7-Zip, `hdiutil` or `zipfile` and run `gpg` from a relative path, and the manifest generator reads jars with `zipfile` and has one manifest per OS (`contentaccessible-manifest-macos.json`, `-windows.json`). `windows-keyboard` gains a macOS arm that measures the editor caret with a control (`input:windowsKeyboard` off). `windows-crt-math` skips its control on a Windows host, where the host libm is the CRT. `stock-gpu-parity` now applies the launcher's own rule (`utils.plan_rendering`: a software renderer matches any GPU, a hardware GPU must be recorded) and says why it fails.

**Not fixed, filed.** Windows `contentaccessible-parity` finds a real difference, the missing `defaultagent` resource (#358). `getter-cost-parity` fails on the hosted macOS runner (#359). `stock-gpu-parity` failed on both hosted runners: its gate demanded a recorded GPU even from a software renderer, which the launcher does not (Windows runner: Microsoft Basic Render Driver); on the macOS runner stock says `Apple Inc.` where fpgen has `Apple`, so the launcher too treats that GPU as unrecorded. `windows-crt-math` on macOS is #317.

**Evidence.** See the PR for run and job ids.

**What misled the investigation.** A Linux green said nothing about the other two OSes (lesson 3). `webdriver-bidi-tabs` hung on one developer Mac for the fork.1 and the fork.2 apps and passed on the CI macOS runner; it was a condition of that Mac, not of the browser. A log is only about the binary the run unpacked, so every probe prints the BuildID it ran against.

## #356: Vietnamese text drew with the wrong glyphs in the window of a Camoufox on a Mac

**Fixed by:** the PR that closes #356. **Found by:** a goapi session on a macOS host with a Windows identity, whose window showed garbled Vietnamese while its screenshots were correct.

**Symptom.** On a macOS host with a Windows or Linux identity, Vietnamese text (and any text drawn from a bundled face such as Segoe UI or Arial) appeared in the window with wrong glyphs: the right letters in the DOM, other outlines on screen. `Page.screenshot`, the screencast and Marionette captures of the same page were correct, so nothing the automation could read showed it.

**Root cause.** On macOS, WebRender rasterizes glyphs in the GPU process. Content does not send it a font: it sends a descriptor made of a PostScript name and a file path (`UnscaledFontMac::GetFontDescriptor`, `ScaledFontMac.cpp:373-412`), and `add_native_font` (`gfx/wr/wr_glyph_rasterizer/src/platform/macos/font.rs:272-325`) looks the font up by that name and then adds the path as `kCTFontURLAttribute`, ignoring a failure (`if let Ok`). CoreText ignores the URL for a file that is not registered in the calling process, and falls back to another font (`Helvetica.ttc` here), whose outlines are then drawn with the bundled font's glyph ids. The bundle is registered only with `kCTFontManagerScopeProcess`, by `CoreTextFontList::ActivateFontsFromDir`, which only the `CoreTextFontList` constructor called. The GPU process never creates a `gfxPlatform` (`gfxPlatform.cpp:788` asserts it), so it never had a font list and never registered the bundle. A Windows or Linux host is not affected by reading: WebRender gets a file path there (`bindings.rs:2996-3011`, `UnscaledFontFreeType.cpp:69-78`).

**Fix.** `font-hijacker.patch` splits the gate and the activation out of the constructor into `CoreTextFontList::ShouldActivateBundledFonts` (pref `gfx.bundled-fonts.activate` not 0 and spoofed OS not macOS) and `ActivateBundledFonts` (nullable family set), and `GPUParent::RecvInit` calls them right before `wr::RenderThread::Start`. The directory comes from `gfxVars::GREDirectory()`, because `NS_GetSpecialDirectory(NS_GRE_DIR)` fails in the GPU process: the first version of the fix used it, built green, and registered nothing. Alternatives that were not taken: resolving the font by name in WebRender (refuted below), and leaving it to the user to turn the GPU process off (`layers.gpu-process.enabled=false` draws correctly, and is the reference of the test).

**Evidence.** `e2e/journeys/test_10_bundled_fonts_in_the_window.py` captures the real window (by window id, never the screen) in three launches: default, GPU process off, GPU process off again. It requires the rows to differ from a blank window's crop (else VACUOUS), the two GPU-off launches to be equal (else NOT COMPARABLE), and default equal to GPU-off. Red before the fix, locally and on CI (runs 41023853587 and 41025002946, job 123960947661, BuildID 20261027060636): the first two checks ok, the third failing. Green after: run 41098518733 on build 41064214560 (head 364090f2), both drivers, all three checks ok, 316138 bytes against 316138. `MOZ_LOG=fontlist:4` on that build reads `bundled-fonts gate gfx.bundled-fonts.activate=1 native-identity=0` and `bundled-fonts activating .../Contents/Resources/fonts` in the parent, the GPU process and every content process, for Windows, Linux and macOS-platform identities, and no `no fonts directory` line. On build 41026066613 (the NS_GRE_DIR version) the GPU process read `no fonts directory`. With `gfx.bundled-fonts.activate=0` in the profile the gate line reads 0 in every process, no activation follows, and the window draws legible system-font Vietnamese. The guard is `bundled-fonts-registered-in-the-macos-gpu-process` in `ci/tribal-rules.yml`.

**What this does not cover.** Canvas text under accelerated or remote canvas may reach the same lookup (`RecordedEventImpl.h:1511-1525`), but a non-host identity reads canvas back randomized, so it could not be measured. The `go` driver is excluded from the journey, because goapi applies prefs after the browser starts and `layers.gpu-process.enabled` is read at startup.

**What misled the investigation.** Every capture path that avoids WebRender (`Page.screenshot`, `drawSnapshot`, `CrossProcessPaint`, the screencast) paints the page correctly, so a clean screenshot said nothing; only a capture of the window shows it, and `remote.screenshot.use_readback` is not supported on macOS. The first hypothesis, that WebRender resolves the PostScript name to another copy of a duplicated name, was refuted: with the files registered, 9 of 9 name-plus-URL lookups returned the requested file, and unregistered ones all returned `Helvetica.ttc`. goapi's `WithFirefoxUserPref("layers.gpu-process.enabled", false)` had no effect, which made the first GPU-off reference invalid until the pref went into the profile's `user.js`. A stale window position (read before the window settled) shifted the crop by 50 px and was caught by the off-against-off control. And a green build said nothing about the GPU process: only its own log line showed the directory lookup failing.

## #354: a macOS build hung in mach's terminal-notifier and was cancelled at the 6 hour job limit

**Fixed by:** the PR that closes #354. **Found by:** `build.yml` run 40983620975 (`build (macos, arm64)`, job 123829360348).

**Symptom.** The `Build` step ran from 01:29Z, mach finished compiling at 03:34:50Z, and the step then produced no output until GitHub cancelled the job at 07:05:10Z. No artifact and no cache were saved.

**Root cause.** After a successful build mach calls `BuildBase.notify` (`python/mozbuild/mozbuild/base.py`), which runs `terminal-notifier` on macOS and waits for it. The last log lines are `105:02.68 /opt/homebrew/lib/ruby/gems/3.4.0/bin/terminal-notifier -title 'Mozilla Build System' -group mozbuild -message 'Build complete'` and then nothing; in the passing run 40882163721 the next line, `To view a profile of the build`, follows 1.3 seconds later. The function returns first when `MOZ_NOSPAM` or `MOZ_AUTOMATION` is set, and `build.yml` set neither.

**Fix.** The `Build` step sets `MOZ_NOSPAM=1` and has `timeout-minutes: 240`, 52 minutes over the slowest passing Build step (188 minutes, macOS arm64), so any other hang fails in four hours instead of six. `MOZ_AUTOMATION` was not used because it changes more than notifications.

**Evidence.** `test_the_build_step_cannot_hang_on_mach_s_notifier_or_run_to_the_job_limit` in `ci/tests/test_fork_workflow.py` failed on main (`MOZ_NOSPAM` absent) and passes with the change. The effect is read from the Firefox 158.0.1 source, `python/mozbuild/mozbuild/base.py`, `BuildBase.notify`: line 652 is `if "MOZ_NOSPAM" in os.environ or "MOZ_AUTOMATION" in os.environ:`, line 653 is `return`, and `terminal-notifier` is looked up at line 657 and run at line 663, after that return. No macOS build has run with the change, so the fix is unexercised until the first macOS build from main after the merge; that build's log must show no `terminal-notifier` line after `Build complete`.

**What misled the investigation.** The REST logs endpoint returned the job without any `Build` step output, which made the run look like it died in setup; `gh run view --log --job` has the step. The ccache miss rate (99.98%) looked like the cause of the long run, but the compile had finished in 105 minutes.

## #348: goapi pages raced on their handler list, and closed pages kept their handlers

**Symptom.** Under `go test -race`, a `BrowserContext.OnPage` handler that calls `Page.OnDialog` while the browser detaches the page is reported as a data race on `Page.subs`. Separately, a page that had been closed still received events for its session: handlers set with `OnDialog`, `OnConsole`, `OnPageError`, `OnCrash`, `OnRequest`, `OnResponse` and `OnFileChooser` stayed registered on the connection, and with them the `*Page` they captured, for the life of the browser.

**Root cause.** `Page.subs` was appended to at ten internal sites (`page.go`, `frame.go`, `dialog.go`) with no lock, while `finish()` ranged over it and set it to nil with no lock, on the read loop. `BrowserContext.publish` calls the `OnPage` handlers outside `pagesMu`, so a handler can register handlers while a detach runs `finish()`; an append after `finish()` was never deregistered. The public `On*` methods returned their subscription to the caller and never recorded it in `p.subs`, so `finish()` could not remove it.

**Fix.** One helper, `Page.own`, records a subscription under `p.mu`, and deregisters it at once when the page has already finished. Every internal registration and every public `On*` goes through it. `finish()` swaps the slice out under `p.mu` and deregisters outside the lock. The public methods still return the `Subscription`, and `p.Off` still works; deregistering a subscription twice does nothing.

**Evidence.** Red, then green, in `goapi/page_subs_test.go`, which drives a scripted connection and needs no browser: `TestOnPageHandlerRegisteringHandlersRacesDetach` reported `WARNING: DATA RACE` between `Page.finish` and `Page.OnDialog` and failed with `500 dialog handlers registered during the detach still run after the page closed`; `TestPageClosingDeregistersItsPublicHandlers` failed for `OnDialog`, `OnConsole`, `OnPageError`, `OnCrash`, `OnRequest` and `OnResponse` with `ran 2 times; it ran again after the page closed`. Both pass with `-race` after the fix. The leak test delivers each event once while the page is open first, so a handler that was never called cannot pass for a deregistered one.

**What misled.** The tests do not count handlers on the connection, which would have needed an accessor on `juggler.Connection` only for tests; they check what the leak does, which is call the handler of a closed page. `OnFileChooser` has the same fix but no test: its registration makes a blocking call that the scripted connection does not answer.

## #311, #314: the patch-guard runner and several guards failed on Windows and saw nothing on macOS

**Fixed by:** the PR that closes both. **Found by:** a run of the spoofing group on real Windows 10 against the fork.1 build.

**Symptom.** `python -m ci.run_patch_guards` died after its first guard with `AttributeError: module 'os' has no attribute 'sysconf'`. Run guard by guard, `context-lists-across-processes.py` and `system-font-alias-stall.py` raised `UnicodeDecodeError: 'charmap' codec can't decode byte 0x9d`, and `ipv4-only-network.py`, `webgl-live-state.py` and `webgl-renderer-pair.py` failed for lack of `unshare`, `ip` and a virtual display.

**Root cause.** Three assumptions that Linux CI satisfied. `leftover_browsers` read `/proc` and called `os.sysconf("SC_CLK_TCK")`: that raises on Windows, and on macOS there is no `/proc`, so the loop found nothing and reported every guard clean, which made the check vacuous rather than failing. `read_text()` and `open()` without `encoding=` use the locale codec, cp1252 on Windows, which cannot decode bytes in `fonts.json`. And three guards build a Linux network namespace or an Xvfb display, which have no counterpart elsewhere.

**Fix.** `leftover_browsers` lists processes with psutil (already in `ci/requirements.txt`) that run from the binary's directory, and raises when no process can be read at all. Every `read_text`, `write_text` and text-mode `open` in the guards, `ci/` and `e2e/` names `encoding="utf-8"`. `LINUX_ONLY` in `ci/run_patch_guards.py` makes the runner report those three guards as not applicable off Linux, counted apart from the passes ([tribal rule](../ci/tribal-rules.yml) `linux-only-guards-are-not-applicable-elsewhere`). Not taken: reading `/proc`, `ps` and PowerShell separately (three code paths for one list), and per-guard skips (a skip reads as green).

**Evidence.** Red then green in `ci/tests/test_ci.py`: `test_text_files_are_read_and_written_as_utf_8` listed 51 call sites before the change and none after; `test_leftover_browsers_sees_a_process_started_from_the_browsers_directory` returned an empty list on macOS before the change; `test_a_linux_only_guard_is_not_applicable_elsewhere_and_not_a_pass` ran `ipv4-only-network` on a darwin stand-in before the change and skipped it after.

**What misled the investigation.** The leftover check passing on macOS read as "no leftovers"; it could not see any process. A first version of its test read the child's executable too early: on a macOS framework Python the launcher re-executes into `Python.app`, so the path differs until the script runs.

## #335: the macOS build failed in "Setup and bootstrap" because patch.py ran `~/.cargo/bin/rustup`

**Fixed by:** the PR that makes `browser/scripts/patch.py` run `rustup` from `PATH`. **Found by:** `build.yml` run 40813393344, job 123249229239 (`build (macos, arm64)`, image `macos-26-arm64` 20261021.0445.8).

**Symptom.** `sh: /Users/runner/.cargo/bin/rustup: No such file or directory`, `make: *** [set-target] Error 1`, then `fatal error: command '~/.cargo/bin/rustup target add "x86_64-apple-darwin"' failed`. Job 123236045061 of run 40809437503, on image 20261013.0424.1, passed the same step.

**Root cause.** `add_rustup()` in `browser/scripts/patch.py` ran `~/.cargo/bin/rustup target add "<target>"`, a path only a rustup-installed toolchain has. Every other rustup call in the build, including the `build.yml` steps before it, uses `rustup` from `PATH`, so a runner whose own rustup lives elsewhere passes them and fails here.

**Fix.** `add_rustup()` runs `rustup target add` from `PATH`. A leg without rustup on `PATH` still fails the build, with `fatal error: command 'rustup target add ...' failed`: `ci/tests/test_patch_rustup.py` pins both cases. Where rustup comes from on each leg that runs `patch.py`: the Linux runner legs (Linux, and Windows cross-compiled) and the macOS runner both run bare `rustup` in the `build.yml` steps ahead of "Setup and bootstrap"; `browser/Dockerfile` puts `/root/.cargo/bin` on `PATH`; `browser/scripts/install-deps.sh` sources `~/.cargo/env` after installing it.

**Evidence.** See the PR.

**What misled the investigation.** The `build.yml` comment at the macOS install step already named image 20261021 and its rustup, and pinned the toolchains through `PATH`, so the image was thought handled. The log line `info: self-update is disabled for this build of rustup` appears on the passing image too, so it does not tell the images apart. That the older image had `~/.cargo/bin/rustup` is inferred from the two outcomes, not read: no job printed `command -v rustup`.
## #325: a Linux claim on a Windows or macOS host drew the Apple and Microsoft faces for Linux names

**Fixed by:** the PR that adds `browser/patches/zzz-linux-font-aliases.patch`, `browser/additions/camoucfg/FontAliasesLinux.hpp` and `browser/scripts/gen-font-aliases.py`. **Found by:** the face log (`CAMOU-FL face`, #327) read on a Windows host.

**Symptom.** A launch with `os="linux"` on Windows or macOS measured text in the Apple and Microsoft files of the flat package. `Helvetica` drew `Helvetica`, `Arial` drew `Arial`, `Courier New` drew `Courier New`, and `serif`, `sans-serif` and `monospace` drew `Times`, `Helvetica` and `Courier New`. A Linux host draws `Nimbus Sans`, `Arimo`, `Cousine`, `Nimbus Roman`, `Nimbus Sans` and `Cousine` for the same requests with the same font list.

**Root cause.** On Linux, fontconfig answers a named lookup through the aliases in `browser/bundle/fontconfig/linux/fonts.conf`, and Gecko takes every family before the sentinel (`gfxFcPlatformFontList.cpp:2564-2608`). DirectWrite and CoreText have no fontconfig, and the flat Windows and macOS packages hold the Apple and Microsoft files under those exact names, so the lookup found them. The generic path (`CamouGenericCandidate`) follows the same name resolution, so the generics drew them too.

**Fix.** The browser applies the conf's answer itself. `gen-font-aliases.py` reads each Linux name no Linux face carries through `fc-pattern` against the staged bundle and writes `FontAliasesLinux.hpp`. `zzz-linux-font-aliases.patch` rewrites such a name to its admitted targets in `gfxPlatformFontList::FindAndAddFamiliesLocked` when the context claims Linux, and in `gfxDWriteFontList` before the DirectWrite substitution. A target that is itself an alias key is skipped, so the rewrite cannot recurse. `test_font_aliases_table.py` fails when the header differs from the bundle, and prints the diff.

**Not tried / failed.** Removing the Apple and Microsoft files from a Linux claim's list was not possible: the allowlist filters by family name, and the same files serve the Windows and macOS contexts of the same package. Reading the answer from `fc-match` on the Windows host was not possible either, because it has no fontconfig. The generics' realism when no row key resolves is a separate gap (#333).

**Evidence.** `e2e/journeys/test_09_linux_claim_fonts.py` reads the drawing face from the face log. Red: e2e run 40837110717 (job 123324742569) on the Windows build 40809452153 of main 0190fa38 fails with `Helvetica: drew 'Helvetica', the Linux host draws 'Nimbus Sans'` and nine more requests. Green: e2e run 40837114640 (job 123326864251) on the Windows build 40809427405 of the branch, 1 passed. The same test passes on the Linux leg of the branch's Tests run, which proves the expected table is what fontconfig draws.

**What misled the investigation.** Ink quantization and `fc-match` output looked like a verdict and were not: neither reads the face that drew. The first Linux-host reference was itself a leak (#329). The first drift failure of the table test looked like a fontconfig version dependence and was a trailing blank line: the committed header ended in two newlines and the generator writes one, so the diff was one empty line, found only once the test printed it.

## #313: on Windows the first `voiceschanged` carried no spoofed voices

**Fixed by:** the PR that moves the `MaskConfig::MVoices` block of `voice-spoofing.patch` ahead of the speech services. **Found by:** `spoofed-voice-speaks.py` on the `v158.0.1-beta.34-fork.1` Windows build.

**Symptom.** On real Windows a launch with `voices` in `CAMOU_CONFIG` read 0 voices on its first `voiceschanged`: `speechSynthesis.getVoices()` was empty at that event and held the spoofed voices only at the second.

**Root cause.** `nsSynthVoiceRegistry::GetInstance()` (`dom/media/webspeech/synth/nsSynthVoiceRegistry.cpp:167` at FIREFOX_158_0_1_RELEASE) started the services with `NS_CreateServicesFromCategory(NS_SPEECH_SYNTH_STARTED, ...)` before the patch added the `MVoices`. `SapiService` registers its voices synchronously inside that call and then `NotifyVoicesChanged()` (`SapiService.cpp:239-248`), so the content process got its first `voiceschanged` (`SpeechSynthesis.cpp:317-324`) from the host's voices alone, and the spoofed ones came with the second.

**Fix.** The `MVoices` block runs before `NS_CreateServicesFromCategory`, in `voice-spoofing.patch`. Regenerated by the #131 procedure: both blob hashes match the patch's `index` line, the unedited baseline regenerates byte-for-byte, and `CAMOU_PATCH=gpatch scripts/patch.py 158.0.1 beta.34` applies the whole stack with exit 0 and no fuzz. `e2e.yml` runs `spoofed-voice-speaks.py` on every leg, unedited.

**Evidence.** See the PR.

**What misled the investigation.** The first reading took the voices after the first event and concluded that spoofed voices never reach the page on Windows. The page does get them, at the second event; the defect is the first. The timelines (`[ms, count]` per event) show it: before, 1 fake voice gave `[[5,0],[5,1]]`; after, `[[5,1],[5,1]]`.

## #331: the launchers named the fonts/ parent when groups.json or the OS's group directories were missing

**Fixed by:** the PR that makes `utils._generate_fontconfig`, `typescript/src/utils.ts` and `goapi/fontconfig.go` raise in that case. **Found by:** the #329 review.

**Symptom.** A bundle with no `groups.json`, or with a `readBy` list whose directories were all absent, launched without error and with `<dir>fonts</dir>` in the runtime conf. fontconfig scans a `<dir>` recursively, so every OS's faces were on the search path, the universe leak of #329 reached through a different door.

**Root cause.** Each launcher ended its scan-directory selection with a last resort: Python `scan_dirs = [fonts_dir]`, TypeScript `scanDirs = [fontsDir]`, goapi `return []string{fontsDir}, nil`. A damaged `groups.json` already raised (#186); an absent one, or one whose directories do not exist, did not.

**Fix.** All three raise, naming the OS and the path, when neither a group directory nor `fonts/<os>/` exists. The legacy `fonts/<os>/` branch stays: upstream's Linux releases up to `152.0.4-beta.29` (2026-08-21) ship `fonts/{linux,macos,windows}` with no `groups.json`, grouped bundles start at `156.0.1-beta.32` (2026-09-28), and `repos.yml` lists upstream as the "Official" repo a user can select, so the layout is still installable. The `bundle-old` golden fixture in TypeScript pins that layout.

**Evidence.** Red then green in each launcher. Python: `test_no_groups_json_and_no_per_os_directory_fails_instead_of_naming_the_parent` and `test_a_groups_json_whose_directories_are_missing_fails_instead_of_naming_the_parent` failed on main (2 failed, 3 passed) and pass after (5 passed). TypeScript: the two `(#331)` cases in `tests/utils.test.ts` failed (2 failed, 22 passed) and pass. Go: `TestFontconfigEnvLegacyBundleLayout` (its last assertion was `expected the fonts/ root`, now expects an error) and `TestFontconfigEnvFailsWhenNoReadByDirectoryExists` failed on main and pass. One fixture relied on the fallback: `test_executable_path_bundle.py` made an empty `fonts/` and asserted the parent was named; it now builds a one-group bundle and asserts the group is named and the parent is not.

**What misled the investigation.** A comment in each launcher said a damaged `groups.json` must not widen the scan, which read as the fallback being closed; it covered the damaged file only.

## #329: on a Linux host, bundle activation added every font group, bypassing the per-OS directory gate

**Fixed by:** the PR that adds `browser/patches/linux-bundled-fonts-toplevel.patch`. **Found by:** the #325 face-log measurement.

**Symptom.** A Linux launch on a Linux host drew files from `fonts/M/` for names its font list admits: `Helvetica` drew `M/27__Helvetica.ttc`, `Arial` drew `M/0__arial.ttf`, `Times` drew `M/69__Times.ttc`, and the generics `serif`, `sans-serif` and `monospace` drew `M/69__Times.ttc`, `M/27__Helvetica.ttc` and `M/910__Courier New.ttf`. `fc-match -s` against the generated `FONTCONFIG_FILE` listed only `L` and `LW` files, with Nimbus Sans first for `Helvetica`.

**Root cause.** `gfxFcPlatformFontList::ActivateBundledFonts()` (`gfxFcPlatformFontList.cpp:3095-3117` at FIREFOX_158_0_1_RELEASE) called `FcConfigAppFontAddDir` on `<GRE>/fonts`, and fontconfig scans that recursively. `browser/settings/camoufox.cfg` keeps `gfx.bundled-fonts.activate` at 1. Every group of every OS therefore sat on the application font list, past the group directories `utils._generate_fontconfig` names, and the allowlist filters by family name, not by origin (CLAUDE.md lesson 1).

**Fix.** Add only the files directly in `fonts/` (Firefox's own `TwemojiMozilla.ttf`) with `FcConfigAppFontAddFile`. Which groups an OS reads stays decided in one place, the launcher's generator. build-tester now sets `FONTCONFIG_FILE` from that generator, and `smoke.yml` calls it instead of substituting the `fonts/` parent into the conf by hand.

**Not tried / failed.** Setting `gfx.bundled-fonts.activate=0` through `custom_fonts_only=True` changed nothing, because the launcher applies that pref at runtime and the font list reads it at startup; it would also drop Firefox's own faces. Reading `groups.json` in C++ was rejected: it would be a second copy of the group choice.

**Evidence.** Face log (`CAMOU-FL face`), same preset font list, Linux host. Red, the build of PR #328 (Tests run 40781286151, probe run 40791200138): `Helvetica` `M/27__Helvetica.ttc`. Green, this change's build (Tests run 40785905651, probe run 40791218227): `Helvetica` `L/openadd-NimbusSans-Regular.otf`, `Times` `L/openadd-NimbusRoman-Regular.otf`, `Courier` `L/openadd-NimbusMonoPS-Regular.otf`, `Arial` `L/z__Arimo[wght].ttf`, `Times New Roman` `L/z__Tinos-Regular.ttf`, `Courier New` `L/z__Cousine-Regular.ttf`. `Twemoji Mozilla` draws `fonts/TwemojiMozilla.ttf` in both builds. Removing `fonts/M`, `fonts/W` and `fonts/MW` from the red build moved every row the same way (probe run 40780901666).

One guard moved: `system-ui-font-spoofing.py`, arm "macos context in a windows launch". Its precondition scored `Helvetica` against the width of `monospace`. In the red build that `monospace` drew `M/35__Menlo.ttc` inside a Windows launch, so the width differed from Arial's by accident of the leak; in the green build it draws `MW/382__arial.ttf`, the same face the `Helvetica` to `Arial` rewrite gives, so the control equalled the value under test. The arm is scored on the `step=system-ui key=arial` line, which both builds write; the width precondition is removed.

**What misled the investigation.** `fc-match -s` against the generated conf looked right and was the wrong universe: it does not see application fonts. The `activate=0` arm read as "the mechanism is something else"; it only showed the pref had not reached startup. Every Linux font measurement since the groups were introduced was taken with the M and W faces on the path (CLAUDE.md lesson 8). The rule is in `ci/tribal-rules.yml`: `fc-activates-only-firefox-own-bundled-fonts`.

## #321: a `windows` identity on a Windows host differed from stock Firefox 158.0.1 on the first legacy-name lookups

**Fixed by:** the PR that makes `browser/patches/font-other-names-sync.patch` leave a Windows claim on a Windows host on the stock path. **Found by:** the #319 review; measured against stock 158.0.1 on windows-2025.

**Symptom.** With `launch_options(os="windows", fonts=[...])` on a Windows host, two legacy names of one base family in the same page (for example `Segoe UI Light` and `Segoe UI Semibold`) read differently from stock Firefox. Width of `HxmW0 .8Qgy` at 72 px, `"<name>", monospace`, first reading, `all` arm (Semibold, Light, Semilight, Calibri Light, Franklin Gothic Medium): stock `[457.92, 435.42, 435.42, 420, 439.42]`, fork.1 `[457.92, 439.75, 449.02, 415.43, 439.42]`. Fork.1 showed the settled face of the later names at once; stock showed its not-yet-resolved fallback until the font loader had run. A page can compare the two.

**Root cause.** The first lookup of each name is identical in stock and Camoufox (single-name arms agree). The difference is the second lookup of a name with the same base. `FontList::FindFamily` has an `#ifdef XP_WIN` branch (`SharedFontList.cpp:1234-1317`) that strips the last word, reads the base family's face names once (`mFaceNamesRead[match]`) and answers an alias hit with the base family. A later lookup of another name with that base finds the base "already read" and returns `nullptr`, so the caller reaches `InitOtherFamilyNames`. Stock defers that read to an idle task (`mayDefer`). #247 had forced a synchronous read there for every masked page, so a Windows claim resolved the second name at once. After #319 only Linux and macOS claims looked up primary names; the #247 `mayDefer = false` still applied to a Windows claim.

**Fix.** One predicate, computed once in `FindAndAddFamiliesLocked` and used at both sites (the primary-names-only lookup and `mayDefer`): the page is masked and not already initialised, and on `XP_WIN` the claim (`GetSpoofedOS(ContextIdFor(provider))`) is Linux or macOS. A Windows claim on a Windows host therefore takes stock Firefox's code path, base-first answer and idle deferral included. Elsewhere every masked page still reads the names at once, as before. See `ci/tribal-rules.yml`, `legacy-family-names-windows-claim-stock-path`.

**Not tried.** Setting `gfx.font_loader.delay` (the cost recorded under #247), and keeping the forced read and emulating the base answer by hand.

**Evidence.** Probe run 40694052562 (job 122836062937, windows-2025, 10.0.26100) with the red build `v158.0.1-beta.34-fork.1` (BuildID `20261027085446`) and the fix build, run 40676976006 (job 122777829509, `windows-x86_64`, headSha `2fe0e61f1bec505b1de546eb15910920031e4908`; the docs commits after it touch none of the paths that decide a rebuild). Stock is Firefox 158.0.1 `win64/en-US` (installer sha256 `3259a2f8508e58cf2e383b6c99bfc64d6ddc86d1407b7c2f86f660af955b5d10`, checked against the https-served `SHA256SUMS`). Launcher: `camoufox` from this branch.

Regression arm (`legacy-family-names-first-measure.py`, `windows_host_parity`, Windows host only): identity `windows`, fonts `Segoe UI Semibold`, `Segoe UI Light` and a never-installed name in one page and pass. The control is the never-installed name; Light's own width (439.75) differs from absent's (468.08), but that is not guaranteed on every host, so the arm asserts Light's first width equals the never-font's and its settled width is its own.

| Reading, monospace | fork.1 (red) | fix build |
|---|---|---|
| Segoe UI Semibold first | 457.92 | 457.92 |
| Segoe UI Light first | 439.75 | 468.08 (= never-font) |
| never-font first | 468.08 | 468.08 |

The guard itself, run at head `ec821a8078671abd4bb4ba406d53624413bedb53` on windows-2025 (probe run 40711684052, job 122898388041; an earlier probe, run 40694052562, ran a copy of the guard without this arm, so its numbers below are from `e2e/probes/t02_resolve321.py`, not the guard). Host arm, monospace, `host first` / `host settled`:

| Check | fork.1 (exit 1) | fix build (exit 0, `PASS`) |
|---|---|---|
| first lookup of the base family's second legacy name reads as the never-font | `[FAIL]` 439.75 (expected 468.08) | `[ok  ]` 468.08 |
| first lookup of the base family's first legacy name answers | `[ok  ]` | `[ok  ]` |
| second legacy name settled on a width other than the never-font's | `[ok  ]` | `[ok  ]` |
| second legacy name settled on its own face (same width under both generics) | `[ok  ]` 439.75 | `[ok  ]` 439.75 |
| DejaVu arm: first width was not the settled width | `[FAIL]` `['DejaVu Sans Condensed']` | `[ok  ]` `[]` |

Host first, fork.1: Semibold 457.92, Light 439.75, never-font 468.08; fix: 457.92, 468.08, 468.08. Settled on both: 473.82, 439.75, 468.08. The two generics' fallbacks are not a usable control: the settled never-font reads 468.08 under both, so a check that they differ failed on both builds (run 40709865242) and was replaced by the settled Light-against-never-font check above.

`t02_resolve321.py`, 5 launches each, identical: fork.1 `Light=439.75 never=468.08`, fix `Light=468.08 never=468.08`. Time for Light to resolve after the first reading: 0.5 to 0.7 s on the fix build, with one 5.6 s outlier on fork.1 (run 0); the margin between "first" and "resolved" is small, but the first reading is one synchronous call and the assertion is on that call.

Name-order parity, `all` arm, monospace row, widths in px (the three lists are the five names in the order above):

| | first | at 15 s |
|---|---|---|
| stock 158.0.1 | 457.92, 435.42, 435.42, 420, 439.42 | 473.82, 439.75, 449.02, 415.43, 439.42 |
| fix build | 457.92, 435.42, 435.42, 420, 439.42 | 473.82, 439.75, 449.02, 415.43, 439.42 |
| fork.1 | 457.92, 439.75, 449.02, 415.43, 439.42 | 473.82, 439.75, 449.02, 415.43, 439.42 |

The sans-serif row differs between stock and the fix build by one constant: unresolved names read the generic fallback, 468.08 in stock and 457.92 under the Windows identity, for every name alike. The same holds in all single-name arms and in `Light` then `Calibri Light` in either order (stock `[457.92, 420]` and `[420, 457.92]`, fix the same). So the rows match name by name; the generic's own width is not the same object in the two browsers and is not claimed equal.

#319 proofs on the fix build, `DejaVu Sans Condensed` first reading, 3 launches each: `os=linux` 468.17, `os=macos` 468.17 (fork.1 520.45); the `windows` row unchanged (Semibold absent first, 473.82 settled).

**Not explained.** Stock `only:Calibri Light` returned no reading in run 40674899610 (no POST within 60 s). In run 40694052562 it returned in 3 of 3 repeats (first `[420, 468.08]`, settled 415.43), but `only:Segoe UI Semibold` returned nothing (`proc.poll=1`: the stock process had exited). Two different stock arms failed to report once each; I did not establish why, and the camoufox arms never failed to report. `MOZ_LOG=fontinit:5` printed no `OtherFamilyNames` lines for any Camoufox arm, so the idle task's timing is read from widths, not from the log.

**What misled the investigation.**
- The issue's "=absent" and "=base" verdicts used the identity's generic fallback as the reference. On this font set the generic can equal `Segoe UI`'s width, so a resolved name and an unresolved one could read the same. Raw widths, and the invariant "a resolved name has the same width under monospace and sans-serif", were the control (lesson 4). The comparator in the probe is itself confounded by the state change between its monospace and sans passes, and was not used for conclusions.
- #247's and #319's guards ran a non-Windows identity on the Windows leg, so the Windows-claim path on a Windows host had no arm at all.

## #319: on a Windows host, a `linux` or `macos` identity measured `DejaVu Sans Condensed` as `DejaVu Sans` on the first lookup

**Fixed by:** the PR that makes `browser/patches/font-other-names-sync.patch` look up primary names only for a Linux or macOS claim. **Found by:** the first assertion of `legacy-family-names-first-measure.py` failing on the Windows leg (run 40643268942).

**Symptom.** On windows-2025 with `v158.0.1-beta.34-fork.1`, `launch_options(os="linux" or "macos", fonts=[the three legacy DejaVu names, ...])` measured `"DejaVu Sans Condensed", monospace` at 520.45 px on the first lookup of a fresh browser, and 468.17 px after 12 s. 520.45 is `DejaVu Sans`'s width; the fallback is 475.2. Identical in all 6 launches (3 per OS).

**Root cause.** #247 made the first lookup read the other family names at once (`mayDefer` false). On Windows that code is never reached for a legacy name: `SharedFontList()->FindFamily(key)` in `gfxPlatformFontList::FindAndAddFamiliesLocked` has an `#ifdef XP_WIN` branch (`SharedFontList.h:146`, `aPrimaryNameOnly` false) that answers a legacy (GDI name ID 1) name with its base family's regular face until the loader has filled `AliasFamilies`. `DejaVu Sans Condensed` is answered as `DejaVu Sans`, so `family` is non-null and the `InitOtherFamilyNames` block below it is skipped.

**Fix.** Under `#ifdef XP_WIN`, the lookup passes `aPrimaryNameOnly = true` when the page is masked (`CamouGenericTableApplies`) and the claimed OS is Linux or macOS (`NavigatorManager::GetSpoofedOS(ContextIdFor(provider))`: the context's platform, else the launch's). A primary-names-only miss falls into the existing #247 block, which reads the names and finds the family. A Windows claim keeps the stock branch, because real Windows Firefox is base-family-first. The gate is Windows-only because that is where the bug and the branch it bypasses are: primary-names-only also skips the alias table (`SharedFontList.cpp:1221-1225`), which on a macOS host holds single-face aliases such as Osaka-Mono published at startup (`gfxMacPlatformFontList::InitAliasesForSingleFaceList`), and a masked macOS or Linux claim there would have lost them and paid the synchronous load. Linux hosts set `mOtherFamilyNamesInitialized` at init. The hunk adds the `mozilla/dom/NavigatorManager.h` include, and `system-ui-font-spoofing.patch` no longer adds it; see the patch-order trap below. `patch-dependencies.md` records the new dependencies.

**Not tried.** Forcing `gfx.font_loader.delay=0` (the cost already recorded under #247), and calling the loader synchronously on a Windows host only.

**Evidence.** Build 40661180714 (`windows-x86_64`, branch `fix/319-dejavu-first-lookup`, headSha `92d555c082ee8ae8ed8fdb137f005d85589df58c`, BuildID `20261028091235`) against `v158.0.1-beta.34-fork.1` (BuildID `20261027085446`) as the red; both on windows-2025 (10.0.26100), launcher `camoufox` from this branch, probe run 40666976745, job 122744151446. Width of `HxmW0 .8Qgy` at 72 px, `"DejaVu Sans Condensed", monospace`, first reading, 3 launches per cell, all identical:

| Arm | fork.1 (red) | fix build |
|---|---|---|
| `os=linux` launch | 520.45 | 468.17 |
| `os=macos` launch | 520.45 | 468.17 |
| `os=windows` launch, Segoe UI Semibold first / settled | absent / 473.82 | absent / 473.82 (the whole row unchanged) |
| Linux launch, `windows` context | 520.45 | 520.45 (stock base-first, as intended) |
| Linux launch, `macos` context | 520.45 | 468.17 |

The regression test is the guard itself. `legacy-family-names-first-measure.py` now launches a `linux` identity on a Windows host (a `windows` one uses the host fonts, which hold no DejaVu), and `windows` elsewhere. On the same job: fork.1 `[FAIL] legacy names whose first width was not their settled width: ['DejaVu Sans Condensed'] (expected [])`, exit 1; fix build `PASS`, exit 0.

Cost of the fix, `other_names_stall.py --os linux --runs 6` on the same two binaries, first call in ms per run: fork.1 6327, 6341, 6317, 6333, 7555, 9466; fix 7288, 6474, 6336, 6370, 6331, 6310. Second calls were 2 to 4 ms on fork.1 and 0 to 1 ms on the fix. The first call takes about 6.3 s on both builds, so that time is not the synchronous load, and the fix adds none measurable over it. What the 6.3 s is was not established.

**What misled the investigation.**
- #247's guard was green on Windows only because a `windows` identity there uses the host's fonts, not the bundle. The one arm that would hit the Windows branch (a non-host identity) was not on the Windows leg's path.
- A filtered dry-run hid a failure. The first fix build (40647125718) failed on `system-ui-font-spoofing.patch` with `Reversed (or previously applied) patch detected! 9 out of 9 hunks ignored` and a `.rej`: both patches added the same include, so GNU patch took the later patch's first hunk as already applied and skipped the whole file. The dry-run output had been piped through a filter that dropped that line. Read the full dry-run for `Reversed`, `FAILED`, `fuzz`, `.rej` and the exit code.

**Known limit.** `mOtherFamilyNamesInitialized` is process-wide. Once a Linux or macOS context has forced the load, every later lookup in that process, a `windows` context included, finds the real face and not the base-first one. That is a limit of mixed-OS browsers (see `docs/fonts-gating.md`), and it is not engineered around. Open parity gap: #322, a `windows` identity on a non-Windows host answers a legacy face at once (measured since; see `docs/fonts-gating.md`). #321, a `windows` identity on Windows differing from stock, is the entry above. Windows 10 was not tested.

## #307: getter-cost-parity failed once on `history.length`, a getter Camoufox does not spoof

**Fixed by:** the PR that removes `history.length` from the guard's `WINDOW` list and prints the host CPU on a failure. **Found by:** run 40441871195, job 122011451961, on the 158.0.1 sync.

**Symptom.** `getter-cost-parity.py` failed on `history.length`: 83 ns in Camoufox against 32 ns in stock, in both Camoufox arms. A re-run of that job (122015141243) on the same commit and browser input key passed, and the guard has passed since.

**Root cause.** `history.length` is not a spoofed getter. `window.history.length` has been `removed` in `browser/settings/properties.json` since 156.0.1-beta.32, no patch, hook or pref sits on its path, and in Firefox 158.0.1 `History.length` is `nsHistory::GetLength` (`dom/base/nsHistory.cpp:61`), then `ChildSHistory::Count` (`docshell/shistory/ChildSHistory.cpp:74`: `mLength` plus the pending deltas), with no pref or docShell-flag branch. The guard's `WINDOW` list ("spoofed getters") still carried it, so the guard measured the build-wide cost of Camoufox's binary against stock's (1.2-1.4x on getters the fork never touches, `history.length` at the top of that band, 1.4-1.75x across the CPUs sampled) against a 2x line. Four arms on one runner (AMD EPYC 7763, 8 launches each) showed the session-history prefs are not involved: stock with Camoufox's prefs read like stock (31.7 ns each), Camoufox with stock's prefs read like Camoufox (46.4 against 48.8 ns).

**Fix.** `"history.length"` is deleted from `WINDOW`; no other entry and no threshold changes. This removes an entry that was out of the guard's scope, it does not loosen a bound. The guard also prints one `host CPU:` line on a failure, read from `/proc/cpuinfo` and omitted where that file does not exist; it never affects pass/fail. Alternatives not taken: listing `history.length` as a control (controls fail at the same 2x and 30 ns, so the red would only be renamed, and a 1.2-1.5x band next to a 2x line makes a flaky sanity check), and diffing the build flags (the band is uniform across getters, so ratios to a same-browser control do not move).

**Not explained.** The 83 ns reading itself. Its stock figure (32 ns) matches the EPYC 7763's 31.7, but Camoufox read 83 ns there against 49 ns in all 8 launches on that CPU, with the run's own controls normal. A per-host ratio does not cover that, nothing found can force the state, and it has not recurred, so removing the entry stops the guard from measuring it rather than explaining it.

**Evidence.** No red: deleting a list entry has no meaningful red. Green is the guard passing in the PR's CI.

**What misled the investigation.** The list's name. `WINDOW` is "spoofed getters", so a slow read looked like a fork cost, and the first guess was a session-history pref (`max_total_viewers`, `fission.bfcacheInParent`). The code read and the four-arm split ruled that out. Upstream's copy of this guard carries the same stale entry, so the next sync must keep the deletion.

## #305: test_observer_records could not see a surface missing from harness.SURFACE_NAMES

**Fixed by:** the PR that parses the surface ids from `AccessObserver.hpp`. **Found by:** the red proof for #303: deleting `7: "audio"` from the dict left `ci.run_observer` at 4 passed.

**Symptom.** A surface the observer records but the harness does not list is never checked, and the run stays green.

**Root cause.** `test_observer_records.py` set `EXPECTED = set(harness.SURFACE_NAMES.values())`, and `SURFACE_NAMES` was a hand copy of `enum class SurfaceId` in `browser/additions/camoucfg/AccessObserver.hpp`. The expected set was derived from the thing that had to be checked. The harness comment said to extend the copy by hand.

**Fix.** `harness.parse_surface_names()` reads the enum (`Name = N`, lowercased) and raises on a member without an explicit value or a missing enum, so a shape it cannot read fails loudly. The hand copy and its comment are deleted. The test also asserts that every surface `probe_all_surfaces.html` pokes is in the parsed set, because a parse that silently loses a member would otherwise shrink the expected set and pass. Alternative not taken: exporting the ids from C++ to JS, which would need a browser change for a test-only need.

**Evidence** (fork.4, BuildID 20261025104645, `ci.run_observer`):
- Red (a): `Battery = 8` added to the enum, probe page unchanged: `AssertionError: surfaces NOT recorded: ['battery']`.
- Red (b): `Audio` dropped from the parse, with only the parse change in place it stayed green (`PASS: all 6 surfaces recorded`); with the probe cross-check: `AssertionError: probe page pokes surfaces missing from the SurfaceId enum parse: ['audio']`.
- Green: both reverted, `PASS: all 7 surfaces recorded`, `4 passed, 0 failed`.

**What misled the investigation.** Red (b) first stayed green: the cross-check against the probe page was added because of it.

## #303: CI never ran the tracking observer's tests

**Fixed by:** the PR that adds `ci.run_observer` and the `observer` job. **Found by:** two earlier observer regressions (#291 and the Firefox 156 regression) that no check saw.

**Symptom.** `browser/tests/build-tester/observer/test_*.py` passed on one Mac and nowhere else. A change that broke the observer left every CI check green, and the entries for #291 and for the Firefox 156 regression both record that nothing in CI runs the observer harness.

**Root cause.** The four tests are scripts (`main()` runs at import), so pytest does not collect them, and no workflow or `ci/` runner invoked them. `harness.py` also defaulted to `BIN_DEFAULT`, a scratch path on one Mac: run anywhere else without `CFX_BIN` it tested whatever stale build sat there, or nothing.

**Fix.** `ci/run_observer.py` runs each `test_*.py` as its own process with `CFX_BIN` set and takes the exit code as the verdict. A missing browser or a missing `marionette_driver` fails the gate instead of skipping. `tests.yml` gets an `observer` job under `xvfb-run -a`, listed in `summary`, `All tests passed`, `required=` and `ci/summarize.py`. `marionette_driver` was already pinned by `browser/tests/build-tester/requirements.txt`, which the job installs, so no dependency is added. On Linux the first CI run failed `test_observer_records.py` with `webgl: TypeError: can't access property "getParameter", g is null`: the harness hardcoded `headless=True`, and headless Firefox on Linux has no GL context (the same reason build-tester runs headful, #195). The harness now launches headful when `$DISPLAY` is set, as under `xvfb-run`; macOS, with no `DISPLAY`, stays headless. `BIN_DEFAULT` is deleted: `default_binary()` now exits with an error when `CFX_BIN` is unset.

**Evidence.**
- Red: with `harness.py` changed so it never sets `CAMOU_OBSERVE`, `python3 -m ci.run_observer` on fork.4 (BuildID 20261025104645): `0 passed, 4 failed`, e.g. `AssertionError: surfaces NOT recorded: ['audio', 'canvas', ...]`. The change was reverted.
- Green: the same command unchanged: `4 passed, 0 failed`.
- Not a valid red: deleting `7: "audio"` from `SURFACE_NAMES` stays green, because `test_observer_records.py` derives its expected set from that dict. The harness comment already says so; the dict is a hand copy of the C++ enum.

**What misled the investigation.** The harness comment suggests a dropped surface is caught; it is not.

## #295: goapi's browser tests skipped in CI, so a skip passed as green

**Fixed by:** the PR that adds the `goapi` job to `tests.yml`. **Found by:** the review of #289, whose `TestEvaluateMainWorld` was green in CI without ever launching a browser.

**Symptom.** 21 goapi test files started with `if os.Getenv("CAMOUFOX_BIN") == "" { t.Skip(...) }`, and `goapi.yml` runs `go test ./...` with no browser, so every browser-driven goapi test skipped and the job reported success.

**Root cause.** AGENTS.md says a missing prerequisite fails in CI. The TypeScript and Python suites follow it (`typescript/tests/prereq.ts`, `e2e/util.py`: fail when `CI` is set unless the job lists the name in `CAMOUFOX_TEST_ALLOW_MISSING`); goapi had its own inline skip, repeated in every file, and nothing in `tests.yml` ran it against the browser the run built.

**Fix.** `goapi/browser_test.go` has one helper, `browserBinary(t)`, that follows that convention with the name `browser`; the inline skips are gone. `goapi.yml` keeps its browserless run and allows the gap by name. A new `goapi` job in `tests.yml` runs `ci.run_goapi` under `xvfb-run` with the built browser, feeds the `goapi_browser` gate to `summary`, and is in the `All tests passed` needs.

**Evidence.**
- Red, on origin/main with `CI=true` and no binary: `--- SKIP: TestEvaluateMainWorld`, `--- SKIP: TestFillForm`, `--- SKIP: TestKeyboardPressEnter`, `ok`.
- Green: the same run on the fix reports `--- FAIL` with `test prerequisite missing in CI: browser`; with `CAMOUFOX_TEST_ALLOW_MISSING=browser`, or without `CI`, it skips.

**What misled the investigation.** The unit tests in the same package passed, so the job looked meaningful.

## #298: goapi `Keyboard.Press("Enter")` sent a composition keydown and did not submit forms

**Fixed by:** the PR that ports Playwright's US keyboard layout into goapi. **Found by:** a login form that never submitted after `Press("Enter")`.

**Symptom.** `Press(ctx, "Enter")` returned nil, the page saw `keydown:Process:Enter:229` and no `keypress`, `keyup:Enter` arrived twice, and the form did not submit.

**Root cause.** `namedKeys["Enter"]` in `goapi/keyboard.go` sent `text: "\r"`. In `PageAgent.js` `_dispatchKeyEvent` a keydown whose `text` differs from `key` goes through `tip.commitCompositionWith`, which dispatches the IME-style `Process`/229 keydown. Playwright's own client clears it: `ffInput.js` `RawKeyboardImpl.keydown` (playwright-core 1.58.0, lines 62-64) does `if (text === "\r") text = ""`, and 1.62.0 does the same in `lib/coreBundle.js`. The agent is right; the client was wrong, so Juggler is unchanged.

**Fix.** `Down` clears `"\r"` the same way. The key table is now a port of `usKeyboardLayout.ts` (see #297).

**Evidence.**
- Red, on origin/main with the installed fork.3 (BuildID 20261024021008): `TestKeyboardPressEnter` got `keydown:Process:Enter:229 keyup:Enter:Enter:13 keyup:Enter:Enter:13` and `submitted = undefined`.
- Green: `keydown:Enter:Enter:13 keypress:Enter:Enter:13 keyup:Enter:Enter:13`, `submitted = 1`. Playwright 1.58 `page.keyboard.press("Enter")` on the same binary logs the same three events and submits once.
- `goapi.yml` runs no browser (#295), so these tests skip in CI; the local run is the evidence.

**What misled the investigation.** The `keyup` that arrived twice looked like a second bug; it is the composition path's own keyup plus the explicit one.

## #297: goapi `Keyboard.Press` failed on punctuation, so `Type(..., WithDelay)` dropped the rest of the text

**Fixed by:** the PR that ports Playwright's US keyboard layout into goapi. **Found by:** a password ending in `{}` that was typed without them.

**Symptom.** `Type("a{b}c", WithDelay(d))` wrote `a` and returned `key Down "{": ... NS_ERROR_ILLEGAL_VALUE [nsITextInputProcessor.keydown]`. Every character after the first non-alphanumeric one was lost.

**Root cause.** `resolveKey` knew letters, digits and space. Any other rune got `code: codeForRune(r)` = `"Unidentified"` and `keyCode: charKeyCode[r]` = 0, and `nsITextInputProcessor.keydown` rejects that. `Down` also paired the shifted text with the unshifted key's code.

**Fix.** `goapi/keyboard_layout.go` is the table from playwright-core `usKeyboardLayout.ts`, with `buildLayoutClosure`'s lookup rules (code, key value, shifted value, aliases). `Down`/`Up` send its code, keyCode and location. `Type` follows `input.ts` `Keyboard.type`: a character in the layout is pressed, anything else (CJK, emoji) goes through `Page.insertText`. `charKeyCode`, `codeForRune`, `shiftChar` and the per-key `namedKeys` are gone. An unknown key is now an error instead of a made-up code.

**Evidence.**
- Red, on origin/main with fork.3: `TestKeyboardTypeWithDelayPunctuation`, `TestKeyboardPressBrace` and `TestKeyboardTypeLogMatchesPlaywright` failed with the `NS_ERROR_ILLEGAL_VALUE` above.
- Green: the same tests pass. `Press("{")` logs `keydown:Shift:ShiftLeft:16 keydown:{:BracketLeft:219 keypress:{:BracketLeft:123 keyup:{:BracketLeft:219 keyup:Shift:ShiftLeft:16`, identical to Playwright 1.58 on the same binary, and so does `Type("a{b}c")` event for event.

**What misled the investigation.** The issue suggested adding the unshifted code to the old map. Playwright's layout already holds all of it, and the agent adds Shift itself.

## #291: the armed observer logged "Property 'handleEvent' is not callable" once per window

**Fixed by:** the PR that adds `handleEvent()` to `TrackingObserverChild`. **Found by:** `CAMOU_OBSERVE=1` on the installed fork.3 app, which printed it 14 times in one session.

**Symptom.** `JavaScript error: , line 0: TypeError: Property 'handleEvent' is not callable.` on the browser console, once per window, whenever the observer is armed.

**Root cause.** `TrackingObserver.sys.mjs` registers the child actor with `events: { DOMWindowCreated: {} }`. For each such event `JSWindowActorProtocol::HandleEvent` creates the actor with `GetActor` when none exists (`dom/ipc/jsactor/JSWindowActorProtocol.cpp:174-193`, `createActor` defaults to true), then builds an `EventListener` on the actor object and calls it (`:200-204`). `TrackingObserverChild` had `actorCreated()` but no `handleEvent`, so the call threw.

**Fix.** `TrackingObserverChild` gets an empty `handleEvent()`. The event stays: it is what creates the actor in every window, so the drain timer in `arm()` runs without anything calling `getActor`. Dropping the event would have stopped the actor from existing.

**Evidence.**
- Red: `browser/tests/build-tester/observer/test_observer_console.py` on the installed fork.3 (BuildID 20261024021008), armed: `armed: the console logged 15 handleEvent error(s)`.
- Green: the same test on a copy of that app with only `TrackingObserverChild.sys.mjs` replaced in `omni.ja`: `armed: actor = registered | handleEvent console messages: []`, and the disarmed run (`CAMOU_OBSERVE` unset) reports `No such JSWindowActor 'TrackingObserver'`. `test_observer_records.py` on the same copy: `PASS: all 7 surfaces recorded` and `PASS: getImageData and readPixels recorded on a covered launch`.
- Nothing in CI runs the observer harness, so the PR's Tests run does not exercise this.

**What misled the investigation.** Nothing; the Firefox source names the call.
## #288: goapi could not evaluate in the main world, and `mw:` was silently ignored

**Fixed by:** the PR that adds `WithMainWorldEval` to goapi. **Found by:** running a React-fiber selector through goapi on a live React page.

**Symptom.** On a page whose scripts define `window.require` and whose React tree sets `__reactFiber$*` on DOM nodes, `p.Evaluate(ctx, "typeof window.require")` returned `"undefined"` and no element had a fiber key. The same expressions prefixed with `mw:`, with `allowMainWorld` set through `WithConfig`, returned the same values and no error.

**Root cause.** Juggler serves `mw:` only in `Runtime.callFunction`, and only in Playwright's call shape: a declaration naming `utilityScript.evaluate`, called with `[utilityScript, isFunction, returnByValue, expression, argCount]` (`isMainWorldRequest`, `browser/additions/juggler/content/Runtime.js:67`). `Page.Evaluate` sent `Runtime.evaluate`, where `mw:` is a JavaScript label, so `mw: <expr>` ran `<expr>` in the isolated world. Its doc comment said "main world", which it never was.

**Fix.** `WithMainWorldEval(true)` sets `allowMainWorld`. `Page.Evaluate` sends an `mw:` expression as `Runtime.callFunction` in Playwright's shape, through the same context wait and retry as before, and `decodeSerialized` turns the Playwright-serialized result into the plain values `Evaluate` returns otherwise. Playwright's serializer writes every object or array it reaches a second time as `{"ref": id}` (`serializeAsCallArgument`), not only cycles, so `decodeSerialized` resolves a ref to the value already decoded, as `parseEvaluationResultValue` does, and returns an error for a ref to an object still being decoded: a self-referencing Go map would overflow the stack in `fmt` (observed on Go 1.27.3), while `encoding/json` and `reflect.DeepEqual` handle one. Isolation stays the default (`ci/tribal-rules.yml`, `evaluate-is-isolated-by-default`).

**Evidence.**
- Red: before the change, on the page above, `mw:typeof window.require` returned `"undefined"` and `mw:` counted 0 elements with a `__reactFiber$` key; `window.wrappedJSObject` counted 232, so the expandos were there.
- Green: with `WithMainWorldEval(true)`, `mw:typeof window.require` returns `"function"` and the direct count is 232.
- `TestEvaluateMainWorld` (`CAMOUFOX_BIN`-gated) checks the disabled error, isolated vs main-world `window.secret`, an object round-trip and a thrown expression; `TestDecodeSerialized` covers every serialized tag the decoder maps.

**What misled the investigation.** `mw:` returned plausible values and no error, which read as "main world reached, the page has no such global". `typeof window.wrappedJSObject` being `"object"` is the tell that an evaluation is behind Xray wrappers.

## #283: e2e.yml legs with no browser passed green having tested nothing

**Fixed by:** the PR that adds the `targets` job to `.github/workflows/e2e.yml`. **Found by:** e2e runs 39970634587 and 39992077720, each with two green legs that ran no test.

**Symptom.** `gh workflow run e2e.yml -f run_id=<a one-platform build>` ended `success` with three green legs, two of which only printed `::notice::run <id> has no CamoufoxBuilds-<target>; nothing to test on this leg`.

**Root cause.** A fixed three-entry matrix started every leg (checkout, Python, Go, apt, pip, `playwright install firefox`), and only the "Which browser" step found there was no artifact. It then wrote `E2E_SKIP=1` and exited 0, and the Run and Probe steps were skipped by `if: env.E2E_SKIP != '1'`. That is the skip-as-green AGENTS.md forbids: "A missing prerequisite fails in CI; it never passes as a skip."

**Fix.** A first job, `targets`, lists the build run's non-expired artifacts (`gh api repos/<repo>/actions/runs/<id>/artifacts`) or the release's assets and keeps the targets whose `CamoufoxBuilds-<target>` or `-<asset>.zip` it holds. The e2e job takes that list as its matrix, so a leg with nothing to test never starts. An input that holds none fails in `targets` with `::error::run <id> holds no browser for ...`. `E2E_SKIP` and its two `if:` conditions are gone, and the target table lives only in `targets`. `ci/tests/test_e2e_workflow.py` runs the job's own resolver on synthetic name lists.

**Evidence.**
- Red: on `main` the five resolver tests fail because there is no `targets` job, and `test_the_skip_mechanism_is_gone` fails on `E2E_SKIP` (6 failed).
- Green: 6 passed.
- Live runs are in the PR.

**What misled the investigation.** The runs were green. A run's conclusion says nothing about which legs ran a test; read the legs' logs.
## #282: the cross-process font and voice guard could not run on macOS

**Fixed by:** the PR that gives `context-lists-across-processes.py` `*.localhost` sites. **Found by:** running the guard on a Mac while checking the upstream sync (#278).

**Symptom.** `python3 -m ci.run_patch_guards --only context-lists-across-processes` on macOS died with `Page.goto: Timeout 30000ms exceeded ... navigating to "http://127.0.0.2:<port>/"`.

**Root cause.** `HOSTS = [f"127.0.0.{n}" for n in range(1, 9)]` used eight loopback addresses as eight sites. Linux routes all of `127.0.0.0/8` to `lo`; macOS configures only `127.0.0.1` on `lo0` (`ifconfig lo0 | grep inet`), so addresses 2-8 are unreachable.

**Fix.** `HOSTS = [f"site{n}.localhost" for n in range(1, 9)]`. The server is unchanged: Firefox answers `localhost` and every name ending in `.localhost` as loopback without asking the OS resolver (`IsLoopbackHostname`, `netwerk/dns/DNS.cpp:231-244`, called from `nsHostResolver.cpp:539`, both at `FIREFOX_158_0_RELEASE`), so one list works on every OS and needs no resolver configuration on a runner.

**Evidence.**
- Red: the unchanged guard on macOS (fork.2, BuildID 20261022041804) failed at 127.0.0.2 as above.
- Green: the same command passed (`1/1 guards passed`).
- Control: the guard with its `setFontList`/`setSpeechVoices` init script removed fails on the first page (`FAIL fonts: the context list did not apply on site1.localhost (319 of the launch-level 319)`).
- The parent's `ProcessIsolation` log (`MOZ_LOG=ProcessIsolation:5`) reads the same for the names and for one repeated `127.0.0.1`: every navigation logs `Not isolating '<origin>^userContextId=6' as isolation is disabled` and stays in remote type `web=^userContextId=6`. Pages spread across the context's content-process pool in both cases; a name is no more and no less a process of its own than an address was.

**What misled the investigation.** Counting content processes with `ps` after the pages loaded read 9 for eight `*.localhost` names and 9 for one address loaded eight times: the pool is already full, so the count cannot tell the lists apart.

## #279: the Python tests could reach the developer's real camoufox cache

**Fixed by:** the PR that moves the environment redirect to the top of `python/tests/conftest.py`. **Found by:** reading `conftest.py` after the TypeScript suite wiped a real cache (#267, fixed by #269).

**Symptom.** None yet in Python. The TypeScript suite had deleted `~/Library/Caches/camoufox`; the Python suite had the same exposure.

**Root cause.** `no_browser_fetch` redirected only `addons.ADDONS_DIR`. `pkgman.py:64` (`INSTALL_DIR = Path(user_cache_dir("camoufox"))`) and `geolocation.py:31` (`GEOIP_DIR`) are computed when `camoufox` is first imported, and `multiversion.py:21-24` derives four more from `INSTALL_DIR`. `conftest.py` imports `camoufox` at module top, so a fixture that sets `HOME` runs after the constants are fixed. `multiversion.py:29-31` and `__main__.py:852` call `shutil.rmtree(INSTALL_DIR)`, so one test that reached them would delete the real cache.

**Fix.** `conftest.py` creates a temp root and points `HOME`, `USERPROFILE`, `LOCALAPPDATA` and `XDG_CACHE_HOME` at it before importing `camoufox`, so every import-time constant and every call-time `user_cache_dir()` lands inside it. `pytest_sessionstart` scans the package's module-level paths and aborts the run before any test if one with a `camoufox` component is outside the root, so a new constant is covered without being listed. An autouse fixture empties the root after each test. Alternative rejected: monkeypatching each constant per test, which needs the copies in `addons`, `multiversion`, `utils` and `__main__` kept in step by hand.

**Evidence.**
- Red: `tests/test_cache_isolation.py` against the unchanged conftest, with `HOME` at a scratch directory: 12 failed, 1 passed.
- Green: 16 passed. Pointing the guard at the wrong root makes the session abort with `cache paths outside the test root` before any test runs.
- `python3 -m ci.run_pythonlib` with the real `HOME`: 708 passed, 0 failed; the real cache held 0 files before and after.

**What misled the investigation.** Nothing; the exposure was read from the code, not reproduced.

## #275: the runtime-library install hung for the job's whole hour and printed nothing

**Fixed by:** the PR that adds `ci/apt_install.py` and uses it for every runtime-library install in the workflows. **Found by:** Tests run 39801913772, attempt 1, job "Patch guards: spoofing".

**Symptom.** The step "Install browser runtime libraries" of `.github/actions/prepare-browser/action.yml` printed its header at 15:12:11 and nothing after it until the job was cancelled at its 1 h limit (3609 s). The re-run of the same commit passed.

**Root cause.** Not established. The step ran `sudo apt-get update -qq` and then `sudo apt-get install -y ...` with no bound on either. In a healthy run `install` prints "Reading package lists..." immediately, so the stall was before `install` produced output, most likely in `update`, whose `-qq` hid its progress. The log cannot confirm that. It happened once in 900 runs of the step, so it is an environmental stall that cannot be reproduced on demand, and this fix makes it fail fast and say where; it does not remove it.

**Fix.** `ci/apt_install.py PACKAGE...` runs `apt-get update` and then `apt-get install -y --no-install-recommends`, each bounded by 600 s, and exits 124 with `::error::apt-get <command> did not finish in 600s` when one runs out of time. `-qq` is gone, so a repeat shows its stage. There is no retry: a retry would turn the stall into a slow pass. The four runtime-library installs that run on a pull request use it (`prepare-browser`, the TypeScript job's Xvfb install, the zstd install of the overlay step, and `e2e.yml`).

The limit comes from the step's own duration over 900 runs (60 Tests runs, every job using `prepare-browser`): median 9.6 s, p95 28.9 s, p99 103.5 s, slowest success 164.6 s. 600 s is 3.6 times the slowest success and 1/6 of the hour the job gave the stall. Composite action steps have no `timeout-minutes` (the metadata syntax reference lists `id`, `if`, `name`, `run`, `shell`, `uses`, `with`, `env`, `continue-on-error` and `working-directory`), so the bound is in the script.

**Evidence.**
- Red: the tests in `ci/tests/test_apt_install.py` failed before the script existed (5 failed), and `test_no_workflow_hides_the_progress_of_apt_get_update` named the `-qq` copies.
- Green: 5 passed, and `python3 -m pytest ci/tests -q`, 262 passed. A stalled `apt-get update` (a stand-in that sleeps) with `APT_TIMEOUT=2` printed `::error::apt-get update did not finish in 2s` and exited 124 without running `install`.
- The Tests run on the PR shows the new step output.

**What misled the investigation.** The slowest `prepare-browser` action in those runs, 651 s (run 39610918463), looked like an apt time. Its apt step took 9.7 s; the rest was `actions/download-artifact`. The 1 h cancel showed no output at all, which read as a hang in the step's last command, and attempt 2 passed with no change, which read as a flaky test, though no test had started.

## #273: the tests gate printed FAIL beside a tier it had allowed to be skipped

**Fixed by:** the PR that derives each tier's mark in the `gate` job of `.github/workflows/tests.yml` from the same decision that fills `problems`. **Found by:** the gate logs of runs 39793265227 and 39801913772.

**Symptom.** On every fork pull request the gate printed `FAIL  fetch-browser  skipped`, `FAIL  install  skipped` and `FAIL  sundial  skipped`, and then `every tier passed; this pull request is mergeable.`

**Root cause.** The loop that fills `problems` excuses a skipped tier through `may_skip`. The table printed after it chose its own mark with `mark = "ok  " if result == "success" else "FAIL"`, which ignores `may_skip`, so the two disagreed about the same tier.

**Fix.** The loop records one mark per tier (`ok`, `skip` or `FAIL`) and appends to `problems` only where it records `FAIL`. The table prints those marks. No second condition remains.

**Evidence.**
- Red: `ci/tests/test_fork_workflow.py::test_the_gate_marks_an_excused_skip_as_a_skip_not_a_failure` runs the gate's own script (extracted from the workflow with `_job_block`) with a synthetic `needs` and failed with `assert {'FAIL'} == {'skip'}`.
- Green: the same file, 13 passed, and `python3 -m pytest ci/tests -q`, 261 passed. The other three new tests (a skip nothing excuses, a failed tier, a `fetch-browser` skip on a run that built the browser) pass before and after: they pin the behaviour that must not change.

**What misled the investigation.** The exit code and the final line were right, so the gate looked correct. Only the table was wrong, and no test ran the script: the existing tests string-match the YAML.

## #271: "every bundled preset launches with its own GPU" followed the core count of the machine running it

**Fixed by:** the PR that pins the host core count to each preset's own in `python/tests/test_identity_salt.py::TestPinnedIdentityIsStable::test_every_bundled_preset_launches` and in the TypeScript test of the same name in `typescript/tests/launch.test.ts`. **Found by:** running `launch.test.ts` on an Apple M1 Mac with 10 logical CPUs.

**Symptom.** `macos 1: expected 'Apple M1, or similar' to be 'Intel(R) HD Graphics 400, or similar'`. The Python twin fails the same way (`AssertionError: ('macos', 1)`). Both pass on the CI runners.

**Root cause.** The launch replaces the preset's `navigator.hardwareConcurrency` with the host's, snapped into `plausibleCoreCounts` (`fix_hardware_concurrency`, `python/src/camoufox/fingerprints.py`). `coherence.drop_incoherent_source_values` then rejects a pre-Apple-Silicon Mac integrated GPU beside a count outside `intelMacIgpCores` (`[2, 4, 6, 8, 12, 16]`), and the GPU is drawn again. macOS preset 1 is that Intel GPU, so a host of 10 or 20 cores loses it and the launch names an Apple GPU instead. The result depends on the core count, not on the operating system: a Linux host faked to 10 cores fails the same way. The product behaves as documented, and `test_coherence.py` and the TypeScript test "a preset GPU is checked against the host core count" already test the drop. The defect was in the two tests, which left the host's count unpinned. The issue as filed blamed the launcher claiming the host's GPU on a Mac; that is a second path to an Apple GPU, not this one.

**Fix.** Each test pins the host core count to the preset's own `navigator.hardwareConcurrency` before launching it, so the launch keeps the preset's cores and the test asks only whether every preset can launch with its own GPU. No product code changed. A preset recorded with 2 cores is snapped up to 4 by the launcher, and 4 is in `intelMacIgpCores`, so every bundled preset still passes the coherence rule.

**Evidence.**
- Red, Python: the unchanged test with the host faked to 8, 10 and 20 cores. 8 passes; 10 and 20 fail on `('macos', 1)`.
- Red, TypeScript: the unchanged test with the same fake through `deps.fixHardwareConcurrency`. 8 passes; 10 and 20 fail with the message above.
- Green: the fixed Python test passes with the host faked to 2, 10, 20 and 56 cores, and the fixed TypeScript test and the whole of `launch.test.ts` pass on an Apple M1 Mac with 10 cores.

**What misled the investigation.** The failure appeared only on a Mac, and the filed cause (the launcher claiming the host GPU) fitted that. Faking a Linux host with 10 cores reproduced it, which showed the Mac was incidental.

## #265: the reference Firefox's service worker registration ran out of the page's 8 s budget on Windows

**Fixed by:** the PR that adds `reference_verdict` to `e2e/util.py` and gives the service worker probe in `e2e/web/pages/apps.html` its own 20 s budget. **Found by:** e2e run 39734508472, Windows leg.

**Symptom.** `test_web_apis_behave_like_the_reference` failed for `pkg`, `pw` and `go`: `serviceworker: camoufox=True reference='error: Error'`, with the page's out-of-band errors reading `reference={"serviceworker":"timeout at register",...}`. The same build passed in run 39741085315.

**Root cause.** The probe's `within(8000, ...)` (`apps.html`, `t()`) was chosen when the suite was scaffolded (fd4e47f) and never measured. It bounds the whole registration, and on a GitHub Windows runner `navigator.serviceWorker.register()` is slow and spread widely: over 40 fresh headful launches of the same Windows build (20 of Playwright's Firefox 153.0, 20 of Camoufox, alternating which went first, probe run 39788884625), the time to `register()` resolving ranged from 0.19 s to 4.55 s for both browsers (reference median 2.07 s, Camoufox median 0.51 s with a tail to 4.36 s). None passed 8 s there, but run 39734508472 did, so the tail is longer than 40 samples show. The reference is measured once per module and compared by all three drivers, so one slow registration fails all three.

**Not the cause.** A cold first launch: the first launch of each browser in the probe was not the slowest, and later launches in the same process were as slow. Camoufox: it registers faster than the reference (median 0.51 s against 2.07 s) and its slowest samples (about 4.4 s) match the reference's, so the spread belongs to the runner; the probe did not establish which part of registration is slow.

**Fix.** Two changes, neither a retry or a skip.
- The service worker step gets a 20 s budget (`t(name, fn, ms)`): the budget only tells a hang from an answer, and the observed maximum is 4.55 s.
- A reference that ran out of the page's budget while Camoufox answered is scored by `reference_verdict` as "reference-invalid" and fails with `REFERENCE INVALID ...: not a Camoufox difference`, so it is neither blamed on Camoufox nor passed silently. Equal results and real differences score as before; Camoufox timing out where the reference answered is still Camoufox's difference.

**Evidence.**
- Red: `oracle/test_oracle.py::test_a_reference_that_timed_out_is_invalid_not_a_camoufox_difference` failed with `ImportError: cannot import name 'reference_verdict'`, fed with the exact errors strings of run 39734508472. The slow registration itself cannot be forced on demand, so the red is the scoring, not the browser.
- Green: the same file, 23 passed.

**What misled the investigation.** The first guess was a cold start: the reference is the first Playwright Firefox launch of the session and Defender scans fresh binaries. The alternating-order probe showed the reference and Camoufox are equally slow at any position.

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

**Fix.** The lookup passes `mayDefer` false when `CamouGenericTableApplies` is true, the predicate the generic-family table already uses for "a Camoufox font list applies to this page" (the launch-level `fonts` list, or the current context's own). A masked page's first lookup reads the names at once. Chrome, and a launch with no font list, keep the stock deferral, and startup and the font loader are unchanged. `MOZ_LOG=fontinit:5` shows what the first lookup now does: `InitOtherFamilyNames without deferring took 2104.24 ms` on the parent's main thread, which is `ReadOtherFamilyNames` for every family. The first lookup took 2.17 to 2.24 s on all 8 launches here (macOS arm64), where fork.4's took 2 to 3 ms when it missed and 0.9 to 1.6 s when it blocked. `e2e/probes/other_names_stall.py` (#253), run on GitHub's hosted runners on the exact artifacts, read the first call at 1 to 3 ms (and 195 ms once) on Windows x64 (fork.5, BuildID `20261016091018`), 3 to 6 ms on Linux x86_64 (a `main` build at `28279bb`, BuildID `20261016130937`, not a release package) and 3.8 to 5.6 s on macOS arm64 (fork.5, BuildID `20261016094712`; 1.78 to 1.84 s on the maintainer's machine). The stall is a macOS effect, and the probe times the call without reading widths, so a fast first call on Linux or Windows is not evidence that the names resolved there. Windows has no stall for a `windows` identity because `SharedFontList::FindFamily` answers a legacy name base-family-first there (the `#ifdef XP_WIN` branch), so the first lookup never reaches the load; a `linux` or `macos` identity on Windows does take it, see #319.

**Alternatives.** `gfx.font_loader.delay=0` also resolves the names (0 launches in 8 miss), but it is read in three places in `gfxPlatformFontList.cpp`: it starts the loader at once, lifts the loader's time limit and makes the other names synchronous. Launch took 1.7 s longer (9.13 s to 10.85 s, same binary, 8 alternating launches). By reading the code, the loader would also read every cmap at startup, which `fallback-miss-while-cmaps-load.py` needs pending; that guard was not run with the pref. The decision is in `ci/tribal-rules.yml`. The `#ifdef XP_WIN` branch of `SharedFontList::FindFamily` reads only the face names of the base family (milliseconds) and returns the base family's regular face first, as Windows does, and corrects it once the loader has run. It was not looked at here, and on a Windows host it is the reason this fix did not work for a `linux` or `macos` identity: see #319.

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
