# Stealth invariants and how they were measured

Properties this fork exists to hold, each with the measurement that establishes
it. They are here because every one of them broke silently at least once: the
automation kept working, it just stopped being hidden, and no test noticed.

Each has a guard in `.github/workflows/smoke.yml`. Run it against a build
artifact with `gh workflow run smoke.yml -f run_id=<build run id>`.

## `page.evaluate()` runs in its own compartment

`Frame._onGlobalObjectCleared` in `additions/juggler/content/FrameTree.js` puts
the world Playwright names `''` in a `Cu.Sandbox` rather than on the page
window. Page globals are invisible to automation, automation's writes are
invisible to the page, and page-installed traps never fire.

Upstream Playwright puts that context on the page window itself. Every sync
from upstream can quietly reintroduce that, which is what makes this the
easiest invariant in the fork to lose.

It has been lost twice. `03c1230` ("migrate Juggler modules from JSM to ESM")
took upstream's sources wholesale — a two-line flip inside a diff full of
module-format churn. And **the fork shipped it broken in beta.28**, restored in
beta.29. Measured on the beta.28 artifact (run `32982384237`):

```
FAIL page global                             -> 41 (expected None)
FAIL page expando on element                 -> 'page-owned' (expected None)
FAIL page cannot see evaluate's window write -> 'string' (expected 'undefined')
FAIL page cannot see evaluate's global       -> 'string' (expected 'undefined')
FAIL window.eval untouched                   -> '11' (expected '0')
```

The last line is the one that matters most: a trap the *page* installed on
`window.eval` fired eleven times. The page was not merely able to see
automation artifacts, it could hook and count them.

beta.29 passes all 17 assertions. Guard: `tests/patches/isolated-evaluate.py`,
run by the smoke step *"page.evaluate() is isolated from the page"*.

The `mw:` prefix is the deliberate escape hatch out of this, gated on
`main_world_eval=True`. It is opt-in precisely because it gives up the property
above.

## No spoofing setter reaches a page

The 14 setters (`setCanvasSeed`, `setWebGLRenderer`, …) exist only so an init
script can apply a per-context fingerprint. A page that can read
`typeof window.setCanvasSeed` identifies the browser in one line.

The trap: **a setter self-destructs as a side effect of being called**, not as
a cleanup step. So the number left on `window` equals the number of fields the
config never set — and in a context with no init script at all, that is all 14:

```
default context (no init script) : 14/14 survive
context calling exactly one      : 13/14 survive
```

`Camoufox(...)` then `browser.new_page()` is the first thing anyone writes, and
it is the 14/14 case.

Juggler therefore calls `docShell.disableSpoofSetters()` immediately after the
init-script loop — measured as the right slot: init scripts run at 52ms and the
page's own inline script at 55ms on the same time origin. `about:blank` is
skipped so init scripts added between opening a page and its first real
navigation still apply.

The teardown only *writes* the per-`userContextId` disabled flags that all 17
WebIDL `Func` guards already read, so no guard changes. The entry point is
chrome-only XPCOM, the same shape as `overrideTimezone`: a teardown exposed as
a page-visible function would just be the fifteenth artifact.

## Per-context values outrank the launch config

A context asking for its own timezone, renderer, or font set must get it, even
when `CAMOU_CONFIG` set a different one at launch. Two ways this has broken:

**Reading the launch config first.** `TimezoneManager::GetTimezone` reads
per-context storage before `MaskConfig`, and `ClientWebGLContext::GetParameter`
does the same for the renderer. Reversing that order would silently make the
launch value win everywhere.

**Clobbering on the next navigation.** Timezone overrides are process-global in
this build — the Playwright patch disables per-realm overrides outright
(`Realm::dateTimeInfo()` returns `nullptr`). So `nsDocShell::OverrideTimezone`
records the per-context value into the store that `SetNewDocument` reads;
without that, the next navigation re-applies the launch value over it. The
smoke guard asserts both directions for exactly this reason.

The remaining limit is inherent to a process-global override: with two contexts
on different timezones, whichever navigated last owns the global.

## Spoof state must not outlive the process

`RoverfoxStorageManager` is per-session scratch space. It once wrote **user**
prefs, which Firefox serialises to `prefs.js`, so a reused profile inherited the
previous session's values *and* its `*_disabled_*` self-destruct flags. The
flags are the damaging half — they hide the setters, so the init script's
`typeof` check skips them and the profile can never be fingerprinted again:

```
launch 1  config tz=Europe/London  -> Europe/London
launch 2  config tz=Asia/Tokyo     -> UTC
```

Launch 2 got neither the new value nor the stale one. Both write sites and all
read sites now use `PrefValueKind::Default`: process-lifetime, never
serialised. Reads target the default branch explicitly so a profile already
poisoned by an older build is healed rather than merely spared — a user value
outranks a default one on every later launch.

Only reused profiles were ever affected: `persistent_context=True`, an explicit
`user_data_dir`, or `-profile`.

## Measuring these

Two environment facts cost several wasted runs each:

**CI headless has no WebGL.** Every renderer read returns `(no webgl)`, so a
measurement can look like a clean negative while never reaching the thing under
test. Install `libgl1-mesa-dri` and run under `xvfb-run` with
`LIBGL_ALWAYS_SOFTWARE=1`.

**Init scripts run per document, not per page.** They fire once on
`about:blank` and again on the real page. A probe that records "the setter was
undefined" is often reading the second run, after the first already called it
and it self-destructed correctly. Record from all three vantage points — init
script, page script, and `evaluate` — before concluding anything about a
setter's visibility.

Also: `launch_options()` calls `installed_verstr()` even when
`executable_path` is given, so pointing a script at a CI artifact fails with
`CamoufoxNotInstalled` unless `ff_version` is passed too.
