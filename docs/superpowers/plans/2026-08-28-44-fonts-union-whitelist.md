# #44 fonts: union whitelist + three context-aware chokepoints

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A context created with `os="macos"` under a browser launched for Windows reports macOS fonts, without any code path ever exposing the host's real font families.

**Architecture (amended after Task 1, read this before Task 2):** Keep the deletion.

The union goes in a **new, separate** config key `fonts:whitelist`, read ONLY by
`font-hijacker.patch` when it hijacks `font.system.whitelist`. The existing
`fonts` key keeps its current meaning — this profile's random per-OS subset —
so every fallback path still narrows to a plausible list.

This separation is not cosmetic. `config['fonts']` is a RANDOM SUBSET produced by
`_generate_random_font_subset(target_os)`, not the full OS set. Had we simply
widened `fonts` to the union, every read path that falls back to the launch level
would report all 732 bundled families — a list no real machine has, and a worse
tell than the bug being fixed. With the split, a missed path reports this
profile's own subset, exactly as it does today.

Original architecture note follows. `font-hijacker.patch` writes the launch `fonts` list into `font.system.whitelist`, and upstream `ApplyWhitelist()` clears `mFontFamilies` down to that list — host families are destroyed at startup and can never leak. We widen the launch list to the *union* of the bundled per-OS sets (732 families) so every OS a context might ask for survives startup, then rely on the fork's existing per-context filter to narrow each context back to its own OS. Any read path we miss therefore shows bundled Camoufox fonts, never host fonts: the failure mode is a fingerprint tell with a known ceiling, not a deanonymising leak.

**Tech Stack:** C++ (Firefox 152.0.4 tree), the fork's `patches/*.patch`, `additions/camoucfg/`, pythonlib, goapi.

## Global Constraints

- Pinned source is **Firefox 152.0.4 / beta.29** (`upstream.sh`). Ground truth for any upstream line number: `https://raw.githubusercontent.com/mozilla-firefox/firefox/FIREFOX_152_0_4_RELEASE/<path>`.
- The `camoufox-*/` tree is generated. Persist every browser change as a `patches/*.patch` edit. Never commit edits to that tree.
- Do **not** hand-edit hunk headers. After editing any patch, re-check its arithmetic; `patches/webgl-spoofing.patch` has ONE pre-existing mismatch at `@@ -1009,6 +1009,18 @@` that is present on `main` and is NOT yours to fix.
- Bundled font sets live in `pythonlib/camoufox/fonts.json`: `win` 107, `mac` 574, `lin` 134, union **732**.
- A C++ change costs a ~1h20m build. Batch C++ edits; never spend a build on one line.
- Never run `gofmt -w` on `goapi/pkg/config/config.go` or `goapi/options.go` — both are non-gofmt-clean at HEAD.
- Tests must never call `launch_options` without `executable_path` (downloads ~312MB).
- `playwright==1.55.0` exactly. Use `build-tester/.venv/bin/python`; never plain `pip`.
- `service-tester/proxies.txt` holds a real proxy, is gitignored, and must never be committed.

## Prior decisions this plan must not re-litigate

- The **fonts half of #44 was previously accepted as a limit** (H3+H4): warn, and run one browser per OS. This plan supersedes that only for the browser layer; PR #73's warning and per-OS grouping stay until Task 5 says otherwise.
- H2 ("stop deleting, filter at lookup") was **rejected**: it trades safe-by-construction for safe-by-enumeration across ~25 `mFontFamilies` readers and ~20 `SharedFontList()` sites, and must be re-audited on every Firefox uplift. Do not implement it.
- `__camoufoxMissingSetters` is **closed as #58** — do not reintroduce it.

## What already exists (verified, do not rebuild)

`patches/font-list-spoofing.patch` already ships the whole per-context mechanism:

- `dom/base/FontListManager.{h,cpp}` — `SetFontList(ctxId, list)`, `HasFontList(ctxId)`, `IsFontAllowed(ctxId, key)`, `SetCurrentContext`, `GetCurrentContext`, and `MOZ_RAII AutoFontListContext`.
- `gfxPlatformFontList::FindAndAddFamiliesLocked` — consults `GetCurrentContext()` and returns false for a family this context disallows. **This is the text-measurement path and it is already correct.**
- `gfxFontGroup::EnsureFontList` — `AutoFontListContext autoFontListCtx(mUserContextId)`.
- `layout/style/FontFaceSet.cpp` — derives `mUserContextId` from the owner window's `BrowsingContext` and scopes it.
- `window.setFontList` is emitted per context by `pythonlib/camoufox/fingerprints.py:826`.

The gap is only: (a) the launch whitelist deletes every family outside ONE OS, so a context can never widen back; (b) three read paths answer from launch-level state instead of the context.

---

### Task 1: Prove the per-context filter narrows under a union whitelist

**This task is the gate. It needs NO build** (one ~8 min smoke run on CI) — it measures an existing binary. If it fails, stop and report; Tasks 2-4 are worthless without it.

**Files:**
- Create: `/tmp/font-union-probe.py` (throwaway — do NOT add to the repo)

**Interfaces:**
- Consumes: any linux x86_64 Camoufox artifact.
- Produces: a verdict — "the filter narrows correctly, proceed" or "the filter does not narrow, stop".

**Why this is the gate:** the union plan assumes `FindAndAddFamiliesLocked`'s per-context filter is what decides which fonts a context can measure. If instead the launch whitelist is doing all the work, widening it widens every context and fixes nothing while making fingerprints worse.

- [ ] **Step 1: Decide where this runs — it is NOT the dev machine**

The artifacts are **linux x86_64** and this repo is developed on macOS, so the
probe runs on CI, where a linux binary and `xvfb` both exist. The measurement
also needs a real GL-less-but-headful display, which `smoke.yml` already sets up.

Mechanism (used twice already this week, see runs 33156606998 and 33157170634):
`workflow_dispatch` only offers workflows that exist on the **default branch**,
so a new diagnostic workflow file cannot be dispatched from a branch. Instead,
on a throwaway `diag/*` branch, replace the BODY of `.github/workflows/smoke.yml`
with the measurement job, keeping the `name: Smoke Fingerprint` line and its
`run_id` input. Delete that branch when the measurement is recorded; never merge it.

- [ ] **Step 2: Write the probe**

Create `/tmp/font-union-probe.py`:

```python
"""Does the per-context filter narrow a UNION launch whitelist back to one OS?

Launch with the union of all three bundled sets. Then create two contexts,
call setFontList() with a mac-only and a win-only list, and measure which
families each context can actually resolve. Measurement uses text width:
a family that is filtered out falls back to the default face and matches
the width of a deliberately absent family.
"""
import json, os, sys
from playwright.sync_api import sync_playwright

FONTS = json.load(open("pythonlib/camoufox/fonts.json"))
UNION = sorted(set(FONTS["win"]) | set(FONTS["mac"]) | set(FONTS["lin"]))

MAC_ONLY = ["Helvetica Neue", "PingFang HK", "Geneva"]
WIN_ONLY = ["Segoe UI", "Tahoma"]

# Width of a string in a named family vs in a family that cannot exist.
# Equal widths => the named family did not resolve.
MEASURE = """(families) => {
  const c = document.createElement('canvas').getContext('2d');
  const probe = 'mmmmmmmmmmlliWWWWWWW@#$%^&*()_+';
  const base = (f) => { c.font = '72px "' + f + '", monospace'; return c.measureText(probe).width; };
  const absent = base('__NoSuchFamily__12345');
  const out = {};
  for (const f of families) out[f] = (base(f) !== absent);
  return out;
}"""

def ctx_report(browser, font_list, probes):
    ctx = browser.new_context()
    ctx.add_init_script(
        'if (typeof window.setFontList === "function") window.setFontList(%s);'
        % json.dumps(",".join(font_list)))
    page = ctx.new_page()
    page.goto("data:text/html,<h1>f</h1>")
    got = page.evaluate(MEASURE, probes)
    ctx.close()
    return got

with sync_playwright() as pw:
    b = pw.firefox.launch(
        executable_path=os.environ["CAMOUFOX_BIN"], headless=False,
        env={**os.environ, "CAMOU_CONFIG": json.dumps({"fonts": UNION})})
    mac = ctx_report(b, FONTS["mac"], MAC_ONLY + WIN_ONLY)
    win = ctx_report(b, FONTS["win"], MAC_ONLY + WIN_ONLY)
    b.close()

print("launch whitelist: union of %d families" % len(UNION))
print("mac context:", mac)
print("win context:", win)

mac_ok = all(mac[f] for f in MAC_ONLY) and not any(mac[f] for f in WIN_ONLY)
win_ok = all(win[f] for f in WIN_ONLY) and not any(win[f] for f in MAC_ONLY)
print()
if mac_ok and win_ok:
    print("VERDICT: filter narrows correctly under a union whitelist -- proceed")
    sys.exit(0)
if all(mac[f] for f in MAC_ONLY) and all(mac[f] for f in WIN_ONLY):
    print("VERDICT: STOP. Union widened every context; the per-context filter")
    print("does not gate measurement. The union approach cannot work as designed.")
    sys.exit(1)
print("VERDICT: STOP. Mixed result -- report the two dicts above verbatim.")
sys.exit(1)
```

- [ ] **Step 3: Run it on CI**

In the swapped `smoke.yml`, after unpacking the binary the way the real workflow
does, install `playwright==1.55.0` and run the probe headful under xvfb:

```yaml
      - name: "Does the per-context filter narrow a union whitelist? (#44 gate)"
        run: |
          pip install --quiet 'playwright==1.55.0'
          xvfb-run -a --server-args="-screen 0 1920x1080x24" python /tmp/font-union-probe.py
        env:
          CAMOUFOX_BIN: ${{ steps.bin.outputs.bin }}
          LIBGL_ALWAYS_SOFTWARE: "1"
```

Write the probe with a heredoc in an earlier step, and read
`pythonlib/camoufox/fonts.json` from the checkout rather than a local path.

Dispatch with a binary that already exists — `-f run_id=33157594770` (linux
x86_64) — so the gate costs a smoke run (~8 min), not a build (~1h20m).

Expected on success: `VERDICT: filter narrows correctly under a union whitelist -- proceed`

- [ ] **Step 4: Also assert the default context is not widened**

The default context (`userContextId` 0) must still report a plausible subset,
not all 732. If it reports the union, the `fonts:whitelist` split is not being
honoured and that is a STOP.

- [ ] **Step 4b: Record the verdict**

Append the three printed lines to the report file. If the verdict is STOP, the task ends here with status DONE_WITH_CONCERNS and the plan halts — do not start Task 2.

---

### Task 2: Widen the launch whitelist to the union, in both producers

**Files:**
- Modify: `pythonlib/camoufox/fingerprints.py` (emit `fonts:whitelist` beside `fonts`; the `fonts` assignments are at :725, :735 and :898, and `_load_os_fonts()` at :55 already loads and caches fonts.json)
- Modify: `goapi/pkg/fingerprint/fonts.go` (alongside `RandomFontSubset`, :36)
- Modify: `goapi/pkg/config/config.go` (add the `fonts:whitelist` json tag; do NOT run `gofmt -w` on this file)
- Modify: `settings/camoucfg.jvv` (register `"fonts:whitelist": "array[str]"` beside the existing `"fonts"`)
- Modify: `settings/properties.json` (register it, or `TestProducerSchemaDrift` fails)
- Test: `pythonlib/tests/test_font_union_whitelist.py` (create)
- Test: `goapi/pkg/fingerprint/fonts_test.go` (extend)

**Interfaces:**
- Consumes: Task 1's verdict.
- Produces: launch config carries `fonts` = union of the bundled sets; the per-context list stays exactly the requested OS's set.

**Why here and not in C++:** the producers already own the bundled sets. Computing the union in C++ would need the sets compiled into the binary, which they are not.

- [ ] **Step 1: Write the failing test**

```python
def test_launch_whitelist_is_the_union_not_one_os():
    from camoufox.utils import _launch_font_whitelist
    import json, pathlib
    fonts = json.loads((pathlib.Path(__file__).parents[1] /
                        "camoufox" / "fonts.json").read_text())
    got = set(_launch_font_whitelist())
    # and `fonts` must NOT have been widened along with it
    from camoufox.fingerprints import _generate_random_font_subset
    subset = _generate_random_font_subset("windows")
    assert len(subset) < 732, "the per-profile `fonts` subset must stay a subset"
    assert len(got) == 732, f"expected the 732-family union, got {len(got)}"
    for os_key in ("win", "mac", "lin"):
        missing = set(fonts[os_key]) - got
        assert not missing, f"{os_key} families absent from the launch whitelist: {sorted(missing)[:5]}"
```

- [ ] **Step 2: Run it, confirm it fails**

Run: `build-tester/.venv/bin/python -m pytest pythonlib/tests/test_font_union_whitelist.py -q`
Expected: FAIL — `ImportError: cannot import name '_launch_font_whitelist'`

- [ ] **Step 3: Implement in pythonlib**

Add to `pythonlib/camoufox/utils.py`, and use it wherever the launch config's `fonts` key is set:

Emit it as `fonts:whitelist`, leaving `fonts` untouched:

```python
def _launch_font_whitelist() -> List[str]:
    """Every bundled family, across all OSes -- the value of `fonts:whitelist`.

    NOT the value of `fonts`, which stays this profile's random per-OS subset.
    Widening `fonts` itself would make every launch-level fallback report all
    732 bundled families, which no real machine has.

    font-hijacker.patch writes this into font.system.whitelist, and upstream
    ApplyWhitelist() then deletes every family outside it from mFontFamilies.
    Narrowing it to one OS is what made a per-context setFontList() unable to
    widen back (#44): the families were already gone. The union keeps all
    bundled families alive at startup; the per-context filter in
    FindAndAddFamiliesLocked narrows each context to its own OS.

    Host families are still deleted, so a read path that misses the
    per-context filter shows bundled fonts -- a fingerprint tell with a known
    ceiling -- never the host's real font list.
    """
    fonts = _load_bundled_fonts()
    return sorted(set().union(*(set(v) for v in fonts.values())))
```

- [ ] **Step 4: Run the test, confirm it passes**

Same command as Step 2. Expected: `1 passed`.

- [ ] **Step 5: Mirror it in goapi**

`goapi/pkg/fingerprint/fonts.go` — the launch path must emit the union while `cfg.Fonts` for a context keeps the per-OS set. Add the Go equivalent and a test asserting `len(union) == 732` and that each per-OS set is a subset.

- [ ] **Step 6: Run the Go tests**

Run: `cd goapi && go test ./pkg/fingerprint/ -run Font -v`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add pythonlib/camoufox/utils.py pythonlib/tests/test_font_union_whitelist.py \
        goapi/pkg/fingerprint/fonts.go goapi/pkg/fingerprint/fonts_test.go
git commit -m "fix(#44): launch font whitelist becomes the union of bundled sets"
```

---

### Task 3: Make the three launch-level read paths context-aware

All three are C++. **Do them in one commit so they share one build.**

**Files:**
- Modify: `patches/font-hijacker.patch` (the `IsFontAllowed` helper in `layout/style/FontFaceImpl.h`)
- Modify: `patches/font-list-spoofing.patch` (add hunks for `GetFontList` and `GetFontFamilyList` in `gfx/thebes/gfxPlatformFontList.cpp`)

**Interfaces:**
- Consumes: `FontListManager::GetCurrentContext()` / `HasFontList()` / `IsFontAllowed()`, already defined.
- Produces: `document.fonts` and both enumeration entry points answer per context.

**Upstream anchors in FIREFOX_152_0_4_RELEASE `gfx/thebes/gfxPlatformFontList.cpp`:**
`GetFontList` at **:1175**, `GetFontFamilyList` at **:1213**. `GetFontList` has TWO paths — a `SharedFontList()` branch that returns early at the top, and the `mFontFamilies` loop below it. **Both need the filter**; filtering only the second one leaves the shared-list path unfiltered.

- [ ] **Step 0: Teach the hijacker to prefer `fonts:whitelist`**

In `patches/font-hijacker.patch`, the constructor currently reads
`MaskConfig::GetStringList("fonts")`. Read `fonts:whitelist` first and fall back
to `fonts` when it is absent, so an old config still behaves exactly as before:

```cpp
  std::vector<std::string> fontValues =
      MaskConfig::GetStringList("fonts:whitelist");
  if (fontValues.empty()) {
    fontValues = MaskConfig::GetStringList("fonts");
  }
  if (!fontValues.empty()) {
    // ... existing join + Preferences::SetCString, unchanged
  }
```

- [ ] **Step 1: Chokepoint 3 — `IsFontAllowed` in `FontFaceImpl.h`**

In `patches/font-hijacker.patch`, replace the launch-level helper body so it prefers the current context and falls back to the launch list only when no context list is installed:

```cpp
inline bool IsFontAllowed(const nsACString& aFontName) {
  // Prefer this context's list. FontFaceSet.cpp scopes an AutoFontListContext
  // around the FontFaceSet entry points, so document.fonts questions arrive
  // with a context. Reading only the launch-level "fonts" key here made
  // document.fonts answer for the launch OS in every context (#44).
  if (uint32_t ctx = FontListManager::GetCurrentContext();
      ctx != 0 && FontListManager::HasFontList(ctx)) {
    nsAutoCString key(aFontName);
    ToLowerCase(key);
    return FontListManager::IsFontAllowed(ctx, key);
  }
  if (std::vector<std::string> maskValues =
          MaskConfig::GetStringListLower("fonts");
      !maskValues.empty()) {
    std::string fontName(aFontName.BeginReading(), aFontName.EndReading());
    std::transform(fontName.begin(), fontName.end(), fontName.begin(),
                   ::tolower);
    return std::find(maskValues.begin(), maskValues.end(), fontName) !=
           maskValues.end();
  }
  return true;
}
```

This needs `#include "mozilla/dom/FontListManager.h"` in that header — add it beside the existing `#include "MaskConfig.hpp"`.

- [ ] **Step 2: Chokepoints 1 and 2 — both enumeration paths**

Add to `patches/font-list-spoofing.patch` a hunk that filters `GetFontList`'s shared-list branch and its `mFontFamilies` loop, and one that filters `GetFontFamilyList`. Use the same shape the existing `FindAndAddFamiliesLocked` hunk uses:

```cpp
  uint32_t fontCtx = mozilla::dom::FontListManager::GetCurrentContext();
  const bool filterByCtx =
      fontCtx != 0 && mozilla::dom::FontListManager::HasFontList(fontCtx);
```

then skip any family whose lowercased key fails `IsFontAllowed(fontCtx, key)`. For the shared-list branch the key comes from `list->LocalizedFamilyName(&f)`; for the `mFontFamilies` loops it comes from `family->Name()` via `GenerateFontListKey`.

- [ ] **Step 3: Verify the patches still apply and the arithmetic is right**

```bash
python3 /tmp/hunkcheck.py patches/font-list-spoofing.patch
python3 /tmp/hunkcheck.py patches/font-hijacker.patch
```
Expected: `hunk mismatches: 0` for both. (If `/tmp/hunkcheck.py` is gone, rewrite it: parse each `@@ -a,b +c,d @@`, count ` `/`-` lines toward b and ` `/`+` lines toward d, report any header whose counts disagree.)

- [ ] **Step 4: Commit and build**

```bash
git add patches/font-hijacker.patch patches/font-list-spoofing.patch
git commit -m "fix(#44): document.fonts and font enumeration answer per context"
gh workflow run "Build and Release" -R lang315/camoufox --ref <branch> -f build_target=linux-x86_64
```
`build_target` is required — the `full` default fans out seven legs. Note the run id; the build takes ~1h20m.

---

### Task 4: Verify the whole thing against the rebuilt binary

**Files:**
- Modify: `.github/workflows/smoke.yml` (add a guard step)

- [ ] **Step 1: Re-run Task 1's probe against the new binary**

Same command, new `CAMOUFOX_BIN`. Expected: the same `proceed` verdict — Task 3 must not have broken measurement.

- [ ] **Step 2: Add the regression guard to `smoke.yml`**

Insert before the `record_video` step. The guard must assert BOTH directions and must fail if there is no signal at all — a probe that resolves nothing would otherwise pass vacuously:

```bash
          # #44: the launch whitelist is the union of the bundled sets, so
          # every OS survives ApplyWhitelist(); the per-context filter narrows.
          # Assert a mac context sees mac-only families and NOT win-only ones,
          # and that document.fonts agrees with measurement -- they read
          # different code paths and only both being right means it works.
```

Assert, for a mac context under a union launch: the three Apple markers resolve, `Segoe UI` and `Calibri` do not
(**not `Tahoma`** — it is in BOTH the win and mac sets; 83 families are shared
across two or more lists, so per-OS test constants must be derived as
`set(os) - set(other) - set(other)`, never eyeballed, see Task 1's report), and `document.fonts.check('12px "Helvetica Neue"')` is true while `document.fonts.check('12px "Segoe UI"')` is false. Fail if every probe returns the same value (no signal).

- [ ] **Step 3: Run the smoke workflow and read the log**

```bash
gh workflow run "Smoke Fingerprint" -R lang315/camoufox --ref <branch> -f run_id=<build run id>
```
Expected: the new step passes, and no existing step regresses.

- [ ] **Step 4: Commit**

---

### Task 5: Retire the workaround that this replaces

Only after Task 4 is green.

**Files:**
- Modify: `pythonlib/camoufox/utils.py`, `pythonlib/camoufox/async_api.py`, `pythonlib/camoufox/sync_api.py`
- Modify: `pythonlib/tests/test_launch_font_whitelist_warning.py`
- Modify: `service-tester/run_tests.py`

- [ ] **Step 1: Decide, with evidence, what is now false**

PR #73 added `warn_fonts_excluded_by_launch` because a context could not widen past the launch whitelist. If Task 4 proves it now can, that warning is factually wrong and must go — the same way `829124f` removed the earlier warning that claimed fonts had no per-context override. **Do not delete it on reasoning alone**: run the five tests in `test_launch_font_whitelist_warning.py` and show which assertions are now false.

- [ ] **Step 2: Remove or narrow the warning, and its tests, per Step 1's evidence**

If some cases still warrant a warning (e.g. a font in neither the union nor the context list), narrow it rather than deleting it, and rewrite the tests to pin the narrowed contract.

- [ ] **Step 3: Consider re-merging service-tester's per-OS groups**

`_run_os_group` exists because one process had one font environment. If that is no longer true, a single browser can serve all OS groups again. This is optional and reversible — measure with `service-tester` before and after; keep the split if the grade drops.

- [ ] **Step 4: Update `#44` and commit**

Post the measurement to the issue and close the fonts half.

---

## Self-review

- Spec coverage: Task 1 gates, Task 2 widens, Task 3 fixes all three chokepoints named in the chosen approach, Task 4 verifies, Task 5 retires the superseded workaround.
- Placeholders: none — every step has its command or its code.
- Type consistency: `_launch_font_whitelist()` (Task 2) is the only new producer symbol; `FontListManager::{GetCurrentContext,HasFontList,IsFontAllowed}` (Task 3) already exist with those exact signatures in `patches/font-list-spoofing.patch`.
- Known risk left open deliberately: enumeration paths beyond the two named (`SystemFindFontForChar`'s fallback loops at :1371/:1463) are NOT covered. They select a fallback face rather than reporting a list, and the union bounds what they can reveal to bundled families. If Task 4's measurement shows a leak through them, that is a follow-up issue, not a silent scope expansion.
