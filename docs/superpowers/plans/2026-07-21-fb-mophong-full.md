# FB "Mô Phỏng Đầy Đủ" Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a coherence audit for FB's client-side read surface via the real pythonlib+Playwright launch, fix the genuine incoherences it finds (window geometry), and document identity/cookie hygiene.

**Architecture:** Evidence-first, measured against the real launch path (Marionette is banned as an oracle — it bypasses Juggler and mismeasured dpr). WS1 builds the audit harness; WS2/WS3 are systematic-debugging tasks the harness gates; WS4/WS5 are docs + recon.

**Tech Stack:** Python, `camoufox` pythonlib (editable in-tree install), Playwright 1.55.0, the pre-built FF152/beta.28 binary, Marionette (WS5 recon only).

## Global Constraints

- **Build-free.** No rebuild, no new C++ patch. All fixes are pythonlib-level (`fingerprints.py`/`utils.py`), persisting as normal edits (not the regenerated `camoufox-*/` tree). If root-causing WS2/WS3 shows the fix needs a C++/Juggler change or touches the `no_viewport`/#666 window-strategy, **STOP and escalate** — do not force a patch.
- **WS1 launches via editable pythonlib + real Playwright**, never Marionette (Marionette bypasses Juggler and mismeasures dpr/geometry).
- **dpr is measured coherent — no dpr code change** (any dpr work is a regression guard only).
- **Recon (WS5) is logged-out only:** no credentials, single session, no automated loops.
- **Evidence in the PR:** each workstream's verification output. The WS1 audit truth table is WS2/WS3's real gate; the Marionette `build-tester` fingerprint suite is a regression backstop only.
- Repo `lang315/camoufox`; commit messages end with the `Co-Authored-By` + `Claude-Session` footers; PR body ends with the Claude Code footer.

## Environment setup (once, before Task 1)

```bash
cd build-tester
uv pip install -e ../pythonlib -p .venv        # editable in-tree camoufox (shadows any stale copy)
uv pip install playwright==1.55.0 -p .venv      # preserve the pin (pythonlib allows <1.61)
cp ../settings/properties.json \
   /tmp/cfx_sync4/app/Camoufox.app/Contents/MacOS/properties.json   # validate_config reads it next to the binary
```
Verify: `.venv/bin/python -c "from importlib.metadata import version; print(version('playwright'), version('camoufox'))"` → `1.55.0 0.5.4`.

## File Structure

- `build-tester/observer/audit_coherence.py` (create) — the multi-sample coherence audit (WS1). One responsibility: launch each OS via real pythonlib, assert FB's read-surface coherence.
- `pythonlib/camoufox/fingerprints.py` / `pythonlib/camoufox/utils.py` (modify) — the geometry + screen-generation fixes (WS2/WS3), scoped to the clamp/screen functions.
- `docs/observer/fb-identity-hygiene.md` (create) — the cookie/identity playbook (WS4).
- `build-tester/observer/recon_fb_behavioral.py` (create) — the behavioral spot-check (WS5).

---

### Task 1: Coherence audit harness

**Files:**
- Create: `build-tester/observer/audit_coherence.py`
- Reference (grounding): `build-tester/observer/geom_multi.py`

**Interfaces:**
- Consumes: `camoufox.sync_api.Camoufox` (`executable_path`, `os`, `ff_version`, `i_know_what_im_doing`), `page.evaluate`.
- Produces: `audit_coherence.json` (list of per-sample rows) + a printed PASS/FAIL truth table + non-zero exit on any incoherence. WS2/WS3/WS5 consume the JSON.

- [ ] **Step 1: Write the audit harness**

```python
"""Cross-layer coherence audit for FB's read surface, via the REAL pythonlib +
Playwright launch (Marionette is banned here -- it bypasses Juggler and
mismeasures dpr). Asserts geometry nesting, dpr coherence, and navigator
consistency. Headless is the primary (real scraping) mode; headless floors dpr
to 1, so the dpr assertion expects 1 here and a headful spot-check covers >1.
See the module docstring in geom_multi.py for the one-time env setup."""
import json, os, sys
from pathlib import Path
from camoufox.sync_api import Camoufox

HERE = Path(__file__).parent
BIN = os.environ.get("CFX_BIN", "/tmp/cfx_sync4/app/Camoufox.app/Contents/MacOS/camoufox")
SAMPLES = 4
OSES = ("windows", "macos", "linux")

READ = """() => {
  const dpr = window.devicePixelRatio, near = q => matchMedia(q).matches;
  return {
    dpr, mmCoherent: near(`(min-resolution: ${dpr-0.05}dppx)`) && near(`(max-resolution: ${dpr+0.05}dppx)`),
    sw: screen.width, sh: screen.height, aw: screen.availWidth, ah: screen.availHeight,
    ow: outerWidth, oh: outerHeight, iw: innerWidth, ih: innerHeight,
    plat: navigator.platform, ua: navigator.userAgent, touch: navigator.maxTouchPoints,
  };
}"""

def coherence_fails(d, expected_dpr):
    f = []
    if not (d["iw"] <= d["ow"] <= d["aw"] <= d["sw"]):
        f.append(f"width nest: inner={d['iw']} outer={d['ow']} avail={d['aw']} screen={d['sw']}")
    if not (d["ih"] <= d["oh"] <= d["ah"] <= d["sh"]):
        f.append(f"height nest: inner={d['ih']} outer={d['oh']} avail={d['ah']} screen={d['sh']}")
    if expected_dpr is not None and abs(d["dpr"] - expected_dpr) > 0.05:
        f.append(f"dpr {d['dpr']} != expected {expected_dpr}")
    if not d["mmCoherent"]:
        f.append(f"dpr getter {d['dpr']} disagrees with matchMedia (split-brain)")
    ua_os = "Windows" if "Windows" in d["ua"] else "Mac" if "Macintosh" in d["ua"] else "Linux" if "Linux" in d["ua"] else "?"
    plat_os = "Windows" if d["plat"] == "Win32" else "Mac" if d["plat"] == "MacIntel" else "Linux" if "Linux" in d["plat"] else "?"
    if ua_os != plat_os:
        f.append(f"platform {d['plat']} != UA OS {ua_os}")
    if d["plat"] in ("MacIntel", "Linux x86_64") and d["touch"] != 0:
        f.append(f"maxTouchPoints={d['touch']} on desktop {d['plat']}")
    return f

def launch(os_name):
    with Camoufox(headless=True, executable_path=BIN, os=os_name, ff_version=152, i_know_what_im_doing=True) as b:
        p = b.new_context().new_page(); p.goto("about:blank"); return p.evaluate(READ)

def main():
    results = []
    for os_name in OSES:
        for i in range(SAMPLES):
            d = launch(os_name)
            fails = coherence_fails(d, expected_dpr=1.0)
            results.append({"os": os_name, "i": i, "fails": fails, **d})
            print(f"[{'PASS' if not fails else 'FAIL'}] {os_name}#{i}: "
                  f"screen={d['sw']}x{d['sh']} outer={d['ow']}x{d['oh']} inner={d['iw']}x{d['ih']} dpr={d['dpr']}")
            for x in fails: print("     -", x)
    (HERE / "audit_coherence.json").write_text(json.dumps(results, indent=2))
    bad_oses = sorted({r["os"] for r in results if r["fails"]})
    print("---")
    print(f"{sum(1 for r in results if not r['fails'])}/{len(results)} coherent")
    if bad_oses:
        print("AUDIT FAIL:", ", ".join(bad_oses)); sys.exit(1)
    print("AUDIT PASS")

main()
```

- [ ] **Step 2: Run it — expect FAIL for windows + macos**

Run: `cd build-tester && .venv/bin/python observer/audit_coherence.py`
Expected: exit 1; `AUDIT FAIL: macos, windows`; linux samples PASS; the width-nest / tiny-screen lines print. (This is the failing test that WS2/WS3 must turn green.)

- [ ] **Step 3: Commit**

```bash
git add build-tester/observer/audit_coherence.py
git commit -m "test(fb): cross-layer coherence audit harness (real Playwright launch)"
```

---

### Task 2: Root-cause + fix window-geometry incoherence (Windows `outer > screen`)

> **This is a systematic-debugging task, not a pre-scripted edit.** `clamp_window_dimensions` is already called (`utils.py:775`) and `window.outerWidth` is a spoofed key (`fingerprint-injection.patch`), yet runtime geometry is still impossible — so the exact fix depends on the root cause, which Step 1 finds. Follow superpowers:systematic-debugging.

**Files:**
- Modify: `pythonlib/camoufox/fingerprints.py` (`clamp_window_dimensions` ~L376, `handle_screenXY` ~L953, `from_browserforge` ~L978) and/or `pythonlib/camoufox/utils.py` (the clamp call site ~L774-775).
- Test: `build-tester/observer/audit_coherence.py` (Task 1) is the failing test.

**Interfaces:**
- Consumes: the `audit_coherence.json` width-nest failures.
- Produces: no signature change — the same config keys, now coherent at runtime.

- [ ] **Step 1: Root cause — instrument config vs runtime.** For a `Camoufox(os="windows")` launch, print the generated `config` window/screen keys (`launch_options(...)` return, or add a temporary `debug=True`) and compare to what `audit_coherence.py` reads at runtime. Answer: is `window.outerWidth` present in the config and already ≤ `screen.width` (⇒ the spoof key is not applied at runtime → a C++/consumer gap → **escalate**), or is `window.outerWidth` absent for the synthetic path (⇒ browserforge omits it like it did dpr → the clamp's `if outer and …` no-ops and the browser reports the real window → fix in Python by populating/clamping it)? Write the finding into the task report before any edit.

- [ ] **Step 2: Write/adjust the failing assertion** if Step 1 shows a narrower invariant (e.g. `outer ≤ screen` specifically). The Task 1 harness already asserts nesting; only add to it if Step 1 reveals a sub-case it misses.

- [ ] **Step 3: Implement the minimal fix at the root-caused site.** Most likely candidate (confirm via Step 1): in the synthetic path, ensure `window.outerWidth/outerHeight` are populated from the generated window and clamped so `outer ≤ avail ≤ screen` survives to runtime — mirroring how `handle_screenXY` (fingerprints.py:953-961) already clamps `outerWidth > screen.width`, but for whichever field/path Step 1 shows is leaking. Keep it surgical; do not touch the `no_viewport`/#666 logic.

- [ ] **Step 4: Run the audit — windows must go green**

Run: `cd build-tester && .venv/bin/python observer/audit_coherence.py`
Expected: windows samples PASS (no width/height-nest failures); macos may still fail (Task 3).

- [ ] **Step 5: Regression guard + commit**

Run the existing fingerprint suite once: `cd build-tester && python scripts/run_tests.py /tmp/cfx_sync4/app/Camoufox.app/Contents/MacOS/camoufox` — confirm still ≥1000 (playwright==1.55.0 pin).
```bash
git add pythonlib/camoufox/ build-tester/observer/audit_coherence.py
git commit -m "fix(fingerprints): clamp window geometry to screen at runtime (#<issue>)"
```

---

### Task 3: Root-cause + fix implausible headless screens (macOS `960×540`)

> Systematic-debugging task. Follow superpowers:systematic-debugging.

**Files:**
- Modify: `pythonlib/camoufox/fingerprints.py` / `pythonlib/camoufox/utils.py` — the screen generation (`get_screen_cons` constraint at `utils.py:755`, `generate_fingerprint(screen=…)`).
- Test: `build-tester/observer/audit_coherence.py`.

- [ ] **Step 1: Root cause.** Determine whether the tiny `960×540` macOS screen comes from (a) `get_screen_cons(headless=True)` deliberately constraining to a small screen in headless (an intentional headless behavior that then breaks `screen ≥ inner`), or (b) a browserforge macOS data pool that ships implausibly small screens. Sample `get_random_preset("macos")` and `generate_fingerprint(os="macos", screen=get_screen_cons(True))` directly (pure Python, no browser) and print the screen dims across ~20 draws. Record which source produces `< 1280`-wide screens and how often.

- [ ] **Step 2: Implement the minimal fix at the root-caused site.** If (a): raise the headless screen-constraint floor so the generated screen is ≥ the headless window (`inner` ~1280×720) — no `screen < inner`. If (b): reject/regenerate draws whose screen width is implausibly small for a desktop (`< 1280`) before they reach the config. Keep it a data/constraint fix, not a window-strategy change.

- [ ] **Step 3: Run the audit — macos must go green**

Run: `cd build-tester && .venv/bin/python observer/audit_coherence.py`
Expected: `AUDIT PASS` (all OSes, all samples coherent).

- [ ] **Step 4: Regression guard + commit** (same suite command as Task 2 Step 5).
```bash
git add pythonlib/camoufox/ && git commit -m "fix(fingerprints): reject implausibly small headless screens (#<issue>)"
```

---

### Task 4: Identity/cookie hygiene docs

**Files:**
- Create: `docs/observer/fb-identity-hygiene.md`

- [ ] **Step 1: Write the doc** (verify every kwarg named exists in `pythonlib` via grep before writing it — no invented flags):

```markdown
# Facebook identity / cookie-linkage hygiene

FB's client-side tracking (measured logged-out, `build-tester/observer/recon_fb_live.json`)
sets these `.facebook.com` cookies: `datr` (browser-identity / anti-abuse, ~2yr),
`sb` (secure browser id), `fr` (ad targeting), plus `dpr`/`wd` (device signals it
stores) and `ps_l`/`ps_n` (login state). `datr`/`sb`/`fr` are **identity linkage** —
reused across sessions, they cross-link your identities regardless of a clean fingerprint.

## Default is already safe
Camoufox's Python API defaults to `persistent_context=False` (`sync_api.py:87`), an
ephemeral profile — every launch starts with no `datr`/`sb`/`fr`. Keep it unless you
have a reason not to.

## Rules
1. **One identity = one fresh profile.** Do not share `persistent_context=True` /
   `user_data_dir=` across identities.
2. **If you must persist,** use a distinct `user_data_dir=` per identity, never cross-used.
3. **One egress IP per identity** (`proxy=`). `datr` + IP correlate; reusing an IP across
   identities links them server-side even with different cookies.
4. **Don't route TLS through a ClientHello-rewriting proxy.** Camoufox's JA3 is a genuine
   Firefox handshake — a strength (`plan/device-faking-targets.md:140,218`); a rewriting
   proxy regresses it.

## Notes
- `devicePixelRatio` is coherent through the real Playwright launch (via Juggler
  `overrideDPPX`), host-independent — this narrows `plan/device-faking-targets.md:56` #24.
- Window geometry (`wd` cookie) coherence is enforced by the coherence audit
  (`build-tester/observer/audit_coherence.py`).
- `docs/observer/README.md:106` still claims a stale "canvas-only" observer scope; all 7
  surfaces are wired (`build-tester/observer/recon_fb_live.json`).
```

- [ ] **Step 2: Verify + commit.** Grep-confirm `persistent_context`, `user_data_dir`, `proxy` are real pythonlib kwargs (`grep -rn "persistent_context\|user_data_dir\|proxy" pythonlib/camoufox/sync_api.py`).
```bash
git add docs/observer/fb-identity-hygiene.md
git commit -m "docs(fb): identity/cookie-linkage hygiene playbook"
```

---

### Task 5: Behavioral spot-check (recon addendum)

**Files:**
- Create: `build-tester/observer/recon_fb_behavioral.py`
- Reference: `build-tester/observer/recon_fb_live.py`, `harness.py`

- [ ] **Step 1: Write the behavioral recon** (extends the Marionette recon — this task is recon, not a coherence oracle, so Marionette is fine here):

```python
"""Behavioral spot-check: one logged-out interaction pass (scroll + hover) + a
longer settle vs recon_fb_live.py, to see whether audio/fonts/webrtc (untouched
on the homepage) activate and whether a /tr beacon fires. Logged-out, single
session, no loops. A still-light result is a valid, honestly-reported negative."""
import collections, json, sys, time
from pathlib import Path
HERE = Path(__file__).parent
sys.path.insert(0, str(HERE))
import harness

URL = "https://www.facebook.com/"

def main():
    with harness.Session() as s:
        s.navigate(URL)
        time.sleep(6)
        for y in (400, 1200, 2000):          # one human-paced scroll pass
            s.eval_content(f"window.scrollTo(0, {y});")
            time.sleep(1.5)
        s.eval_content("var e=document.querySelector('a,button'); if(e){e.dispatchEvent(new MouseEvent('mouseover',{bubbles:true}));}")
        time.sleep(6)
        snap = s.snapshot()
    surfaces = {}
    for row in snap:
        for name, n in row["surfaces"].items():
            surfaces[name] = surfaces.get(name, 0) + n
    hosts = collections.Counter(r["host"] for row in snap for r in row["requests"])
    out = {
        "url": URL,
        "surfaces_touched": dict(sorted(surfaces.items())),
        "new_vs_homepage": sorted(set(surfaces) - {"canvas", "webgl", "screen", "navigator"}),
        "tr_beacon": any("/tr" in r["url"] for row in snap for r in row["requests"]),
        "request_host_counts": dict(hosts.most_common()),
    }
    (HERE / "recon_fb_behavioral.json").write_text(json.dumps(out, indent=2))
    print(json.dumps(out, indent=2))

main()
```

- [ ] **Step 2: Run it + commit the honest result**

Run: `cd build-tester && .venv/bin/python observer/recon_fb_behavioral.py`
Expected: a JSON. `new_vs_homepage` may be `[]` (audio/fonts/webrtc did not activate logged-out) — that is a valid negative; report it as-is, do not chase it.
```bash
git add build-tester/observer/recon_fb_behavioral.py build-tester/observer/recon_fb_behavioral.json
git commit -m "recon(fb): behavioral spot-check (logged-out interaction pass)"
```

---

## Self-Review

- **Spec coverage:** WS1→Task 1, WS2→Task 2, WS3→Task 3, WS4→Task 4, WS5→Task 5. All five covered.
- **Placeholder scan:** Task 1/4/5 carry complete code/content. Task 2/3 are deliberately systematic-debugging tasks (the fix depends on a root cause the harness reveals) — they carry the failing test, the investigation method, candidate sites with file:line, and the escalate boundary, which is the honest maximum for an un-root-caused runtime bug. `#<issue>` in Task 2/3 commit messages is filled at execution (every PR ties to an issue per CONTRIBUTING.md).
- **Type/interface consistency:** the harness reads the same keys (`sw/sh/aw/ah/ow/oh/iw/ih/dpr`) it asserts; `Camoufox(executable_path, os, ff_version, i_know_what_im_doing)` matches the measured-working signature; `harness.Session` matches the existing recon usage.
- **Escalate boundary is explicit:** WS2/WS3 stop rather than force a `no_viewport`/#666 or C++ change — preserving the build-free premise.
