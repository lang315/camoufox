# Per-Context OS Coherence Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Stop `NewContext(os=X)` from silently producing cross-signal-incoherent fingerprints, and stop service-tester from generating them by construction.

**Architecture:** The launch-level fingerprint owns fonts (and, on a fork build, may own the WebGL renderer). Per-context overrides cover navigator/screen/seeds only. Rather than inventing a browser-side font setter — which needs a new patch and a full build we cannot verify here — this plan makes the mismatch **loud** at the point it is created, makes missing browser-side setters **visible** instead of silently skipped, and fixes the one in-tree caller that creates the mismatch by construction.

**Tech Stack:** Python 3.12, pytest, Playwright 1.55.0, camoufox pythonlib (editable install).

## Global Constraints

- Firefox target is **152**; `ff_version=152` in every launch that pins one.
- `playwright==1.55.0` exactly — newer reports a false 0/0 on camoufox-152.
- Tests must never call `launch_options` without `executable_path`: without it camoufox **downloads ~312MB** into the user cache. Binary-dependent tests gate on `CFX_BIN` and skip when absent.
- The venv is uv-managed: `uv pip install -e pythonlib -p build-tester/.venv`, never plain `pip`.
- Run pytest as: `cd camoufox && PYTHONPATH=pythonlib build-tester/.venv/bin/python -m pytest <path> -q`
- Do not "fix" a test by loosening an assertion that a real device would satisfy. Prior passes in this repo shipped two false-green audits that way.

## Out of scope, and why

- **Making per-context fonts actually apply.** Needs a browser-side setter (a new entry alongside `patches/webgl-spoofing.patch`) plus a full build — ~40 min, Linux/Docker path, and unverifiable in the current environment. This plan surfaces the limitation rather than hiding it.
- **The WebGL half of #44.** `setWebGLRenderer` is defined by this fork's patches and is **absent from the upstream binary** all measurements used, so its "no effect" is an artifact of the test binary, not a proven defect. Re-test on a fork build before acting. Task 2 makes exactly this class of artifact self-reporting.

## File Structure

| File | Responsibility |
|---|---|
| `pythonlib/camoufox/utils.py` | add `launched_os(from_options)` — recover the resolved launch OS from generated launch options |
| `pythonlib/camoufox/sync_api.py` | record launch OS on the Browser; warn on OS mismatch in `NewContext` |
| `pythonlib/camoufox/async_api.py` | same two changes for the async path |
| `pythonlib/camoufox/fingerprints.py` | `_build_init_script` reports requested-but-absent setters |
| `pythonlib/tests/test_context_os_coherence.py` | new — covers Tasks 1 and 2 |
| `service-tester/run_tests.py` | group profiles by OS, one browser per group |
| `service-tester/_grading.py` | stop masking a real defect |

---

### Task 1: Warn when a context's OS differs from the browser's

**Files:**
- Modify: `pythonlib/camoufox/utils.py` (add `launched_os`, after `get_target_os` at :228-235)
- Modify: `pythonlib/camoufox/sync_api.py:127-130` (record on browser), `:192` (warn in `NewContext`)
- Modify: `pythonlib/camoufox/async_api.py:172` (`AsyncNewContext`, same warn)
- Test: `pythonlib/tests/test_context_os_coherence.py`

**Interfaces:**
- Produces: `utils.launched_os(from_options: Dict[str, Any]) -> Optional[str]` returning `'mac' | 'win' | 'lin' | None`
- Produces: attribute `browser._camoufox_os` (`str | None`) — verified assignable on a Playwright `Browser` (it has `__dict__`, no `__slots__`)

- [ ] **Step 1: Write the failing test**

```python
# pythonlib/tests/test_context_os_coherence.py
import os
import sys
import warnings

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest  # noqa: E402

from camoufox import utils  # noqa: E402


def _opts(user_agent):
    """Shape launch_options returns: chunked CAMOU_CONFIG_<n> under env."""
    import orjson
    blob = orjson.dumps({"navigator.userAgent": user_agent}).decode()
    return {"env": {"CAMOU_CONFIG_1": blob}}


def test_launched_os_reads_mac_from_generated_options():
    ua = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10.15; rv:152.0) Gecko/20100101 Firefox/152.0"
    assert utils.launched_os(_opts(ua)) == "mac"


def test_launched_os_reads_windows():
    ua = "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:152.0) Gecko/20100101 Firefox/152.0"
    assert utils.launched_os(_opts(ua)) == "win"


def test_launched_os_is_none_when_config_absent():
    assert utils.launched_os({"env": {}}) is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd camoufox && PYTHONPATH=pythonlib build-tester/.venv/bin/python -m pytest pythonlib/tests/test_context_os_coherence.py -q`
Expected: FAIL — `AttributeError: module 'camoufox.utils' has no attribute 'launched_os'`

- [ ] **Step 3: Implement `launched_os`**

Add to `pythonlib/camoufox/utils.py` immediately after `get_target_os`:

```python
def launched_os(from_options: Dict[str, Any]) -> Optional[str]:
    """The OS the browser was actually launched as, recovered from its own config.

    Needed because a Playwright Browser handle carries no camoufox identity, and
    NewContext must know whether the OS it is being asked for matches the one the
    browser's fonts were generated for.
    """
    env = (from_options or {}).get('env') or {}
    parts = [
        env[k]
        for k in sorted(
            (k for k in env if k.startswith('CAMOU_CONFIG_')),
            key=lambda k: int(k.rsplit('_', 1)[1]),
        )
    ]
    if not parts:
        return None
    try:
        config = orjson.loads(''.join(parts))
    except orjson.JSONDecodeError:
        return None
    return get_target_os(config) if config.get('navigator.userAgent') else None
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd camoufox && PYTHONPATH=pythonlib build-tester/.venv/bin/python -m pytest pythonlib/tests/test_context_os_coherence.py -q`
Expected: `3 passed`

- [ ] **Step 5: Record the launch OS on the browser**

In `pythonlib/camoufox/sync_api.py`, in `NewBrowser`, replace the two return paths (currently at :121 and :130):

```python
        # Persistent context
        if persistent_context:
            if no_viewport_default and not ('viewport' in from_options or 'no_viewport' in from_options):
                from_options = {**from_options, 'no_viewport': True}
            context = playwright.firefox.launch_persistent_context(**from_options)
            context._camoufox_os = launched_os(from_options)
            return sync_attach_vd(context, virtual_display)

        # Browser
        browser = playwright.firefox.launch(**from_options)
        browser._camoufox_os = launched_os(from_options)
        if no_viewport_default:
            attach_no_viewport_default(browser)
        return sync_attach_vd(browser, virtual_display)
```

Add `launched_os` to the existing `from .utils import (...)` line in `sync_api.py`. Make the identical change in `async_api.py`'s `AsyncNewBrowser`.

- [ ] **Step 6: Warn on mismatch in NewContext**

In `pythonlib/camoufox/sync_api.py`, at the top of `NewContext`'s body (before the proxy-geo block at :192-194):

```python
    _warn_os_mismatch(browser, os)
```

Add this module-level helper to `pythonlib/camoufox/utils.py`:

```python
_OS_TO_SHORT = {'windows': 'win', 'macos': 'mac', 'linux': 'lin'}


def _warn_os_mismatch(browser: Any, context_os: Optional[str]) -> None:
    """Per-context overrides do not cover fonts, so a context whose OS differs from
    the browser's inherits the launch OS's font set and is cross-signal incoherent
    (issue #44). Loud beats silent: there is no way to fix it from here.
    """
    if not context_os:
        return
    launch = getattr(browser, '_camoufox_os', None)
    want = _OS_TO_SHORT.get(context_os, context_os)
    if launch and launch != want:
        warnings.warn(
            f"NewContext(os={context_os!r}) on a browser launched as {launch!r}: fonts "
            "are set at launch and have no per-context override, so this context will "
            "report the launch OS's fonts under a "
            f"{context_os} platform. Launch a separate browser per OS instead.",
            RuntimeWarning,
            stacklevel=3,
        )
```

Import `warnings` in `utils.py` if absent, and call the same helper from `AsyncNewContext`.

- [ ] **Step 7: Write the mismatch test**

Append to `pythonlib/tests/test_context_os_coherence.py`:

```python
class _FakeBrowser:
    def __init__(self, launched):
        self._camoufox_os = launched


def test_warns_when_context_os_differs_from_launch_os():
    with pytest.warns(RuntimeWarning, match="no per-context override"):
        utils._warn_os_mismatch(_FakeBrowser("win"), "macos")


def test_silent_when_context_os_matches_launch_os():
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        utils._warn_os_mismatch(_FakeBrowser("mac"), "macos")


def test_silent_when_launch_os_unknown():
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        utils._warn_os_mismatch(_FakeBrowser(None), "macos")
```

- [ ] **Step 8: Run the full pythonlib suite**

Run: `cd camoufox && PYTHONPATH=pythonlib build-tester/.venv/bin/python -m pytest pythonlib/tests/ -q`
Expected: `130 passed, 5 skipped` — 124 before, plus the 3 tests from Step 1 and 3 from Step 7. No failures. If the count differs, reconcile it before committing rather than adjusting this number.

- [ ] **Step 9: Commit**

```bash
git add pythonlib/camoufox/utils.py pythonlib/camoufox/sync_api.py \
        pythonlib/camoufox/async_api.py pythonlib/tests/test_context_os_coherence.py
git commit -m "fix(pythonlib): warn when a context's OS differs from the browser's launch OS"
```

---

### Task 2: Make absent browser-side setters report themselves

**Files:**
- Modify: `pythonlib/camoufox/fingerprints.py` (`_build_init_script`, :700-730)
- Test: `pythonlib/tests/test_context_os_coherence.py`

**Interfaces:**
- Consumes: nothing from Task 1.
- Produces: the init script gains a `__camoufoxMissingSetters` array on `window`, listing setters the page did not provide.

> **Amended after Task 1 review.** The brief's `_warn_os_mismatch` began with
> `if not context_os: return`, so the warning only fired when the caller passed an
> explicit `os=`. `NewContext(browser)` with no `os=` resolves to an arbitrary OS via
> `generate_fingerprint(os=None)` and was silently exempt — the default call pattern,
> and exactly the incoherence this task exists to surface. Amended: the check now runs
> AFTER the context fingerprint is generated and compares the RESOLVED OS (derived from
> the generated `navigator.userAgent` via `determine_ua_os`) against the launch OS.
> Also amended: `launched_os` and `spoofs_window_dimensions` now share one
> `_reassemble_camou_config` helper instead of two copies that had already drifted on
> None-safety.

**Why:** every setter is emitted as `if (typeof w.setX === "function") w.setX(v)`. When the binary lacks `setX` the call vanishes with no signal. That is exactly what made a missing `setWebGLRenderer` in the upstream binary look like a broken override for hours.

- [ ] **Step 1: Write the failing test**

```python
def test_init_script_records_setters_the_page_does_not_provide():
    from camoufox.fingerprints import _build_init_script

    js = _build_init_script({"webglRenderer": "Apple M1", "canvasSeed": 7})
    assert "__camoufoxMissingSetters" in js, "no way to tell an absent setter from a working one"
    assert js.count("__camoufoxMissingSetters") >= 2, "must record, not just declare"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd camoufox && PYTHONPATH=pythonlib build-tester/.venv/bin/python -m pytest pythonlib/tests/test_context_os_coherence.py -k missing_setters -q`
Expected: FAIL — `AssertionError: no way to tell an absent setter from a working one`

- [ ] **Step 3: Implement**

In `_build_init_script`, replace the setter emission loop with:

```python
    lines.append('  w.__camoufoxMissingSetters = w.__camoufoxMissingSetters || [];')

    for key, fn_name, _template in setters:
        val = values.get(key)
        if val is not None:
            js_val = _json.dumps(val)
            lines.append(
                f'  if (typeof w.{fn_name} === "function") {{ w.{fn_name}({js_val}); }}'
                f' else {{ w.__camoufoxMissingSetters.push("{fn_name}"); }}'
            )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd camoufox && PYTHONPATH=pythonlib build-tester/.venv/bin/python -m pytest pythonlib/tests/test_context_os_coherence.py -k missing_setters -q`
Expected: `1 passed`

- [ ] **Step 5: Verify against a real browser (skips without CFX_BIN)**

```python
def _binary():
    for c in (os.environ.get("CFX_BIN"),
              "/tmp/cfx_sync4/app/Camoufox.app/Contents/MacOS/camoufox"):
        if c and os.path.exists(c):
            return c
    return None


@pytest.mark.skipif(_binary() is None, reason="needs a Camoufox binary (set CFX_BIN)")
def test_missing_setters_are_observable_in_a_real_page():
    from camoufox.sync_api import Camoufox, NewContext

    with Camoufox(headless=True, executable_path=_binary(), os="macos",
                  ff_version=152, i_know_what_im_doing=True) as b:
        ctx = NewContext(b, os="macos")
        page = ctx.new_page()
        page.goto("about:blank")
        missing = page.evaluate("() => window.__camoufoxMissingSetters || []")
        ctx.close()

    # Not an assertion about WHICH are missing -- that is binary-dependent. The
    # point is the list exists, so a missing browser-side setter is discoverable
    # instead of a silent no-op.
    assert isinstance(missing, list)
    print("setters absent from this binary:", missing)
```

- [ ] **Step 6: Run it**

Run: `cd camoufox && PYTHONPATH=pythonlib build-tester/.venv/bin/python -m pytest pythonlib/tests/test_context_os_coherence.py -k real_page -q -s`
Expected: PASS, and on the upstream binary the printed list contains `setWebGLRenderer` — which is the artifact that misled the original diagnosis. Record the output in the commit message.

- [ ] **Step 7: Commit**

```bash
git add pythonlib/camoufox/fingerprints.py pythonlib/tests/test_context_os_coherence.py
git commit -m "fix(pythonlib): record init-script setters the browser does not provide"
```

---

### Task 3: One browser per OS group in service-tester

**Files:**
- Modify: `service-tester/run_tests.py:60-66` (specs), `:107-114` (launch), `:115-125` (context loop)

**Interfaces:**
- Consumes: the warning from Task 1 (this task is what stops it firing in-tree).
- Produces: no new API.

**Why:** `all_specs` is 3 macOS + 3 Linux opened simultaneously against one browser. A single launch-level `os=` can serve only one group, so grouping is the only way both groups get their own fonts.

- [ ] **Step 1: Capture the current baseline**

```bash
cd camoufox/service-tester
../build-tester/.venv/bin/python run_tests.py \
  --executable-path "$CFX_BIN" --profile-count 6 --no-cert 2>&1 | tail -20
```
Expected: a grade at or below `B`, with `webglRendererVsPlatform` and/or `fontEnvironment` failures. Record the exact score — it is the before-number for the commit.

- [ ] **Step 2: Group the entries by OS**

Replace the launch-and-loop block (`run_tests.py:107-125`) with:

```python
    launch_kwargs = {"headless": not headful}
    if executable_path:
        launch_kwargs["executable_path"] = executable_path
        print(f"Using local binary: {executable_path}")
    elif ff_version:
        launch_kwargs["ff_version"] = ff_version

    by_os: dict = {}
    for entry in entries:
        by_os.setdefault(entry["os"], []).append(entry)

    try:
        for group_os, group in by_os.items():
            # One browser per OS: fonts are launch-level and have no per-context
            # override, so contexts must not cross the launch OS (issue #44).
            print(f"  Launching browser for {group_os} ({len(group)} profiles)...")
            async with AsyncCamoufox(**launch_kwargs, os=group_os) as browser:
                open_contexts = []
                for entry in group:
                    profile = {"name": entry["name"], "os": entry["os"],
                               "proxy_geo": entry.get("proxy_geo", {})}
                    try:
                        context = await AsyncNewContext(browser, os=entry["os"], proxy=entry["proxy"])
```

Keep the rest of the existing context body unchanged, re-indented one level. The `profile_results` list accumulates across groups exactly as before.

- [ ] **Step 3: Run and compare**

```bash
cd camoufox/service-tester
../build-tester/.venv/bin/python run_tests.py \
  --executable-path "$CFX_BIN" --profile-count 6 --no-cert 2>&1 | tail -20
```
Expected: `webglRendererVsPlatform` and `fontEnvironment: osDetection` no longer fail for any profile. Grade improves against Step 1's number.

- [ ] **Step 4: Confirm no warning fires**

Run the same command with `PYTHONWARNINGS=error::RuntimeWarning` prefixed.
Expected: still completes — Task 1's mismatch warning must never fire once grouping is correct. If it raises, the grouping is wrong; fix it rather than suppressing the warning.

- [ ] **Step 5: Commit**

```bash
git add service-tester/run_tests.py
git commit -m "fix(service-tester): launch one browser per OS group"
```

---

### Task 4: Stop masking a real defect in grading

**Files:**
- Modify: `service-tester/_grading.py:61-72`

**Interfaces:**
- Consumes: Task 3's grouping (which is what makes the masking unnecessary).

**Why:** `adjust_cross_os_font_checks` force-passes `osDetection` and `noWrongOSFonts` for any profile whose OS differs from the host, labelling them `[Cross-OS: expected]`. After Task 3 no profile is cross-OS by construction, so the masking now hides genuine breakage rather than a harness artifact. It also omits `macOSVersionDepth`, which is why that one failed while its siblings were masked.

- [ ] **Step 1: Write the failing test**

```python
# service-tester/test_grading_no_mask.py
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from _grading import adjust_cross_os_font_checks


def test_font_failures_are_not_silently_passed():
    results = {"extended": {"fontEnvironment": {
        "osDetection": {"passed": False, "detail": "No Apple marker fonts found"},
    }}}
    adjust_cross_os_font_checks("windows", results)
    check = results["extended"]["fontEnvironment"]["osDetection"]
    assert check["passed"] is False, "a real font failure must not be reported as passed"
    assert "[Cross-OS" in check["detail"], "it should be annotated, not hidden"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd camoufox/service-tester && ../build-tester/.venv/bin/python -m pytest test_grading_no_mask.py -q`
Expected: FAIL — `assert True is False`

- [ ] **Step 3: Annotate instead of force-passing**

```python
def adjust_cross_os_font_checks(os_type: str, results: dict) -> None:
    """Annotate cross-OS font failures without hiding them.

    This used to set passed=True. That was written when every profile shared one
    browser and a cross-OS font mismatch really was a harness artifact; profiles now
    get one browser per OS, so a failure here is a real defect and must stay visible.
    """
    host_os = "macos" if sys.platform == "darwin" else ("windows" if sys.platform == "win32" else "linux")
    if os_type == host_os:
        return
    font_env = results.get("extended", {}).get("fontEnvironment")
    if not font_env:
        return
    for key in ("osDetection", "noWrongOSFonts", "macOSVersionDepth"):
        check = font_env.get(key)
        if check and not check.get("passed"):
            check["detail"] = "[Cross-OS] " + check.get("detail", "")
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd camoufox/service-tester && ../build-tester/.venv/bin/python -m pytest test_grading_no_mask.py -q`
Expected: `1 passed`

- [ ] **Step 5: Re-run the suite and record the honest score**

```bash
cd camoufox/service-tester
../build-tester/.venv/bin/python run_tests.py \
  --executable-path "$CFX_BIN" --profile-count 6 --no-cert 2>&1 | tail -20
```
The score may now be **lower** than Task 3's if any real cross-OS failure was previously masked. That is the correct outcome — record both numbers and say which failures were being hidden.

- [ ] **Step 6: Commit**

```bash
git add service-tester/_grading.py service-tester/test_grading_no_mask.py
git commit -m "fix(service-tester): annotate cross-OS font failures instead of passing them"
```

---

## Verification before opening the PR

- [ ] `cd camoufox && PYTHONPATH=pythonlib build-tester/.venv/bin/python -m pytest pythonlib/tests/ -q` → no failures
- [ ] `cd camoufox/build-tester && .venv/bin/python scripts/run_tests.py "$CFX_BIN" --profile-count 2 --no-cert` → grade unchanged from `[A] 268/276` (this plan must not move build-tester)
- [ ] `cd camoufox/build-tester/observer && CFX_BIN=... ../.venv/bin/python audit_coherence.py` → `AUDIT PASS`
- [ ] service-tester before/after scores recorded, with the specific checks that changed
- [ ] PR body states plainly that the WebGL half of #44 remains **unverified** pending a fork build, and that per-context fonts are still launch-level — this plan makes that loud, it does not fix it
