# Measure-Before-Fix: #51, #44/#45, and the virtual-display video path

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Establish, by measurement, what is actually broken in #51 and #44/#45 — and verify the virtual-display default that the beta.29 merge adopted on upstream's reasoning.

**Architecture:** None of these three is ready for an implementation plan. #51's root cause is unknown and its evidence has two uncontrolled variables. #44/#45's original plan was HALTED with its central premise disproven. The virtual-display default was adopted on upstream's argument, not on a local measurement. Each task below therefore produces a **measurement and a decision**, not a code change — except Task 1, which reverts text already shipped on a branch that is known to be factually wrong.

**Tech Stack:** Go (`goapi`), Python (`pythonlib`), GitHub Actions, a fork-built Camoufox binary.

## Global Constraints

- **A fork-built binary is mandatory** for every measurement here. The per-context setters (`setFontList`, `setWebGLRenderer`, `setScreenDimensions`) are defined by fork patches — `patches/font-list-spoofing.patch`, `patches/webgl-spoofing.patch`, `patches/screen-spoofing.patch` — and are absent from upstream builds. Measuring against an upstream binary is what produced the false conclusion in #44/#45 the first time.
- Available artifacts: `CamoufoxBuilds-macos-arm64` from run `32645949575`, `CamoufoxBuilds-linux-x86_64` from run `32684286173`. Both beta.29. Artifacts expire — re-dispatch `build.yml` if they are gone.
- Do not run `goapi` browser tests on a machine with poisoned profiles unless #50 is fixed first; `dom.w3c_touch_events.enabled` leaks between launches and will corrupt results. See `2026-08-24-goapi-profile-isolation.md`.
- `service-tester/proxies.txt` contains a real proxy and is gitignored. Never commit it.
- Tests must never call `launch_options` without `executable_path` — it downloads ~312MB into the user cache.
- `build-tester` runs on a uv-managed venv pinned to `playwright==1.55.0`. Do NOT use `build-tester/run_tests.sh`; it runs `pip install -e ../pythonlib playwright`, which upgrades past the pin. Invoke `.venv/bin/python scripts/run_tests.py <binary>` directly.

---

### Task 1: Revert the factually wrong warning text on `fix/context-os-coherence`

**Files:**
- Modify: `pythonlib/camoufox/utils.py:297` (the warning string, verified present at branch HEAD)
- Modify: `pythonlib/tests/test_context_os_coherence.py:48,71` (two tests asserting that string)

Branch: `fix/context-os-coherence`, HEAD `76ab1ac`. The commits that introduced the warning are `d28786b` and `c3b7fc0`.

**Why this is first:** the branch carries a shipped user-facing warning saying fonts "have no per-context override, so this context will report the ...". The halted execution ledger records that as disproven: `setFontList` exists at `pythonlib/camoufox/fingerprints.py:822` and is provided by `patches/font-list-spoofing.patch`, a fork patch. Two tests assert the false string, so they must change with it. This is the one change here that needs no new measurement.

- [ ] **Step 1: Read the ledger's finding**

Run: `sed -n '/PLAN PREMISE DISPROVEN/,/Task 2 stands/p' .superpowers/sdd/progress.md`
Expected: the block stating the controller's claim in #44 was wrong and that Tasks 3–4 rest on the same disproven premise.

- [ ] **Step 2: Confirm the wrong text is still present**

Run: `git show fix/context-os-coherence:pythonlib/camoufox/utils.py | sed -n '290,300p'`
Expected: line 297 contains `have no per-context override, so this context will report the `.

If it is absent, a later commit already fixed it — stop and skip to Task 2.

- [ ] **Step 3: Decide revert vs rework, and record the decision**

The warning's *mechanism* claim is false. Its *symptom* (a context whose OS differs from the launch OS can be incoherent) is unverified until Task 2. Therefore remove the warning entirely rather than reword it — a reworded warning would assert a symptom that has not been measured.

Do NOT use `git revert` on `d28786b`/`c3b7fc0`: `76ab1ac` and `9c70c11` land on top of the same lines and the revert will conflict. Edit the current state directly:

1. In `pythonlib/camoufox/utils.py`, delete the `warnings.warn(...)` call containing that string, and any now-unused local built solely to construct it.
2. In `pythonlib/tests/test_context_os_coherence.py`, delete the two tests whose `pytest.warns(RuntimeWarning, match="no per-context override")` blocks assert it (lines 48 and 71). They assert a false claim; they are not evidence of anything.
3. Leave every other test in that file alone — Task 2 of the original halted plan stands on its own merits per the ledger.

- [ ] **Step 4: Verify the suite still passes**

Run: `cd pythonlib && python -m pytest tests/ -q`
Expected: `186 passed, 5 skipped` or better. Any test asserting the removed warning text must be removed in the same commit — it asserted a false claim.

- [ ] **Step 5: Commit**

```bash
git add -A pythonlib/
git commit -m "revert(pythonlib): drop the per-context font warning whose premise was disproven (#44)"
```

---

### Task 2: Re-measure #44/#45 against a fork binary

**Files:**
- Create: `/tmp/ctx-os-probe.py` (throwaway — do NOT add to the repo)

**Interfaces:**
- Consumes: the reverted state from Task 1.
- Produces: a decision — either "#44/#45 are not defects, close them" or "the defect is real, write an implementation plan".

- [ ] **Step 1: Get a fork binary**

Run:
```bash
mkdir -p /tmp/forkbin && cd /tmp/forkbin
gh run download 32645949575 -R lang315/camoufox -n CamoufoxBuilds-macos-arm64 -D .
unzip -q camoufox-*-mac.arm64.zip -d cf
cp cf/Camoufox.app/Contents/Resources/properties.json cf/Camoufox.app/Contents/MacOS/properties.json
```
Expected: `cf/Camoufox.app/Contents/MacOS/camoufox` exists. The `properties.json` copy is required — on macOS pythonlib looks for it next to the binary.

- [ ] **Step 2: Write the single-variable probe**

Create `/tmp/ctx-os-probe.py`:

```python
"""#44/#45: does NewContext(os=X) actually carry X's fonts and WebGL renderer?

Single variable: the SAME browser hosts one macos and one windows context.
If the per-context setters work, each context reports its own OS's values.
"""
import json
from camoufox.sync_api import Camoufox

BIN = "/tmp/forkbin/cf/Camoufox.app/Contents/MacOS/camoufox"

READ = """() => {
  const c = document.createElement('canvas');
  const gl = c.getContext('webgl');
  const dbg = gl && gl.getExtension('WEBGL_debug_renderer_info');
  const has = n => document.fonts.check('12px "' + n + '"');
  return {
    platform: navigator.platform,
    ua: navigator.userAgent,
    renderer: dbg ? gl.getParameter(dbg.UNMASKED_RENDERER_WEBGL) : '',
    appleFonts: ['Helvetica Neue','Geneva','Menlo'].filter(has),
    winFonts: ['Calibri','Cambria','Segoe UI'].filter(has),
  };
}"""

with Camoufox(headless=True, executable_path=BIN, i_know_what_im_doing=True) as b:
    out = {}
    for os_name in ("macos", "windows"):
        ctx = b.new_context(os=os_name)
        page = ctx.new_page()
        page.goto("about:blank")
        out[os_name] = page.evaluate(READ)
        ctx.close()
    print(json.dumps(out, indent=2))
```

- [ ] **Step 3: Run it**

Run: `cd build-tester && .venv/bin/python /tmp/ctx-os-probe.py`
Expected: JSON with one object per OS.

- [ ] **Step 4: Apply the decision rule**

Read the output against this rule and write the verdict into the issue:

| observation | verdict |
|---|---|
| `macos.platform` is `MacIntel` AND `macos.appleFonts` non-empty AND `macos.renderer` contains `Apple`, while `windows.platform` is `Win32` AND `windows.winFonts` non-empty AND `windows.renderer` does not contain `Apple` | **Not a defect.** The originals were measured against an upstream binary lacking the fork's setters. Close #44 and #45 with this output pasted in. |
| Both contexts report the same fonts or the same renderer | **Defect confirmed.** Record which signal failed, then write a separate implementation plan; do not fix inline. |

- [ ] **Step 5: Post the measurement**

Run: `gh issue comment 44 -R lang315/camoufox --body-file <(echo '...paste the JSON and the verdict...')`
Repeat for #45. The raw JSON must be in the comment — a verdict without its data is what caused the first wrong conclusion.

---

### Task 3: Separate platform from display-presence in #51

**Files:**
- Create: `/tmp/world-probe/` (throwaway)

**Interfaces:**
- Consumes: nothing.
- Produces: a 2×2 result table identifying whether the main-world divergence tracks the OS or the presence of a display server.

**Why:** the current evidence compares macOS-without-display against Linux-under-`xvfb-run`. Two variables moved at once. Until they are separated, "macOS behaves differently from Linux" is not established — it may be "no-display behaves differently from display".

- [ ] **Step 1: Build the probe as a Go test**

Create `/tmp/world-probe/probe_test.go` and copy it into `goapi/` as `zz_probe_test.go` when running (remove it afterwards — do NOT commit):

```go
package camoufox_test

import (
	"context"
	"fmt"
	"net/http"
	"net/http/httptest"
	"os"
	"testing"
	"time"

	camoufox "github.com/lang315/camoufox/goapi"
)

func TestWorldProbe(t *testing.T) {
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Content-Type", "text/html")
		_, _ = w.Write([]byte(`<html><body><div id="out">dom</div>
<script>window.pageGlobal="main-world-value";document.getElementById('out').textContent='script-ran';</script>
</body></html>`))
	}))
	defer srv.Close()

	ctx, cancel := context.WithTimeout(context.Background(), 60*time.Second)
	defer cancel()
	b, err := camoufox.Launch(ctx,
		camoufox.WithExecutablePath(os.Getenv("CAMOUFOX_BIN")),
		camoufox.WithHeadless(true))
	if err != nil {
		t.Fatal(err)
	}
	defer b.Close()
	bc, _ := b.NewContext(ctx)
	p, err := bc.NewPage(ctx)
	if err != nil {
		t.Fatal(err)
	}
	if err := p.Goto(ctx, srv.URL, camoufox.GotoOptions{WaitUntil: camoufox.WaitUntilLoad, Timeout: 15 * time.Second}); err != nil {
		t.Fatal(err)
	}
	for _, q := range []string{
		`document.getElementById('out').textContent`,
		`typeof window.pageGlobal`,
	} {
		v, err := p.Evaluate(ctx, q)
		fmt.Printf("WORLDPROBE %-46s => %v (err=%v)\n", q, v, err)
	}
}
```

- [ ] **Step 2: Fill the 2×2 matrix**

Run each cell and record `typeof window.pageGlobal`:

| cell | command |
|---|---|
| macOS, no display | `cd goapi && CAMOUFOX_BIN=/tmp/forkbin/cf/Camoufox.app/Contents/MacOS/camoufox go test -run TestWorldProbe -v .` |
| Linux, under xvfb | in CI: `xvfb-run -a go test -run TestWorldProbe -v .` |
| Linux, no xvfb | in CI: `go test -run TestWorldProbe -v .` (no xvfb-run wrapper) |
| macOS, with display | run the same macOS command from a normal desktop session, `WithHeadless(false)` |

The two Linux cells run via `smoke.yml`; add a temporary step or dispatch a branch build. Record all four before drawing any conclusion.

- [ ] **Step 3: Apply the decision rule**

| pattern | conclusion |
|---|---|
| both Linux cells show `string`, both macOS cells show `undefined` | divergence tracks **platform**. Investigate the platform-specific juggler/page-agent code path. |
| both display-present cells show `string`, both no-display cells show `undefined` | divergence tracks **display presence**, not OS. Retitle #51 accordingly — the current title is wrong. |
| any other pattern | neither variable alone explains it; record the table in #51 and stop before theorising. |

- [ ] **Step 4: Determine the leak direction — the part that actually matters**

Whichever way Step 3 lands, the security-relevant question is unanswered: can the **page** see automation, or only automation see the page? Only the former is a detectability problem.

On the platform where `Evaluate` reaches the main world, load a page that inventories its own globals before any automation call, then again after one, and diff:

Do the diff inside the page so no Go helper is needed:

```go
	// Snapshot the page's own global names into a page-side variable, run an
	// automation call, then ask the page which names appeared since. If
	// Evaluate leaves artifacts in the main world, they show up here.
	_, _ = p.Evaluate(ctx, `window.__before = Object.getOwnPropertyNames(window).slice()`)
	_, _ = p.Evaluate(ctx, `1+1`)
	added, err := p.Evaluate(ctx, `(() => {
		const before = new Set(window.__before);
		return Object.getOwnPropertyNames(window)
			.filter(n => !before.has(n) && n !== '__before')
			.join(',');
	})()`)
	fmt.Printf("LEAKPROBE added=%v (err=%v)\n", added, err)
```

Expected on a clean isolation boundary: `added=` (empty). Any automation-looking name (anything juggler-, agent-, or binding-related) is a live fingerprinting surface.

- [ ] **Step 5: Record and decide**

Post the 2×2 table and the leak-direction result to #51. If automation artifacts appear in the page's own global list, raise the severity — that is a live fingerprinting surface — and write a separate implementation plan. If nothing leaks into the page, downgrade #51 to a capability inconsistency, not a detectability bug.

---

### Task 4: Verify the virtual-display video path adopted in the beta.29 merge

**Files:**
- Modify (temporarily): `.github/workflows/smoke.yml`

**Why:** the merge adopted upstream's defaults — Xvfb screen `1x1x24` and Composite off — dropping two fork guarantees (#93, #458). The in-code reasoning was checked and the load-bearing claim verified (`pythonlib/camoufox/utils.py:884` skips `clamp_screen_to_display` for virtual displays). But `record_video` under `headless="virtual"` was never actually run. It is Linux-only, so it cannot be verified from macOS.

- [ ] **Step 1: Write the check**

Add a step to `smoke.yml` after the existing binary-locate step:

```yaml
      - name: Virtual-display video capture (#93/#458 regression check)
        run: |
          cd pythonlib
          python - <<'PY'
          import os, glob
          from camoufox.sync_api import Camoufox
          out = "/tmp/vid"
          os.makedirs(out, exist_ok=True)
          with Camoufox(headless="virtual",
                        executable_path=os.environ["CAMOUFOX_BIN"],
                        i_know_what_im_doing=True) as b:
              p = b.new_page(record_video_dir=out)
              p.goto("data:text/html,<h1 style='font-size:200px'>hello</h1>")
              p.wait_for_timeout(2000)
              p.close()
          vids = glob.glob(out + "/*.webm")
          assert vids, "no .webm produced under headless='virtual'"
          size = os.path.getsize(vids[0])
          print("video:", vids[0], size, "bytes")
          assert size > 10_000, f"video suspiciously small ({size} bytes) -- likely blank frames"
          PY
        env:
          CAMOUFOX_BIN: ${{ steps.bin.outputs.bin }}
```

- [ ] **Step 2: Run it**

Run: `gh workflow run smoke.yml -R lang315/camoufox --ref <branch> -f run_id=32684286173`
Expected: the new step passes.

- [ ] **Step 3: Apply the decision rule**

| result | action |
|---|---|
| step passes | the 1x1 + Composite-off default is safe. Keep the step permanently — it is the regression guard the removed fork tests used to be. Commit it. |
| no `.webm`, or a tiny file | the fork's #93/#458 concern is live under beta.29. Revert the virtual-display defaults to the fork's values (screen `1920x1080x24`, Composite on) in `pythonlib/camoufox/virtdisplay.py`, and reopen the question with this measurement attached. |

- [ ] **Step 4: Commit whichever outcome applies**

```bash
git add .github/workflows/smoke.yml
git commit -m "test(ci): verify record_video under headless=virtual (#93/#458)"
```

---

## Self-review notes

**Why no TDD implementation tasks for #51 and #44/#45:** an implementation plan requires knowing the fix. For #51 the root cause is unknown and the evidence is confounded; for #44/#45 the original plan's premise was disproven and recorded as such in the execution ledger. Writing exact code for either would be invention. Each is therefore scoped to produce a measurement and a decision, which is the honest deliverable at this stage. Task 1 and Task 4 do contain concrete changes, because those are known.

**Ordering:** Task 1 has no dependencies and removes a false statement already on a branch — do it first. Task 2 needs a fork binary. Task 3 is independent but should follow the #50 profile fix, since leaked prefs corrupt goapi measurements. Task 4 is independent and can run in parallel.

**Expected follow-on plans:** up to two, written only if Task 2 or Task 3 confirms a real defect.
