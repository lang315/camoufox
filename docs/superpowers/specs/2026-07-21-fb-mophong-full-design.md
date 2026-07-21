# FB Tracking "Mô Phỏng Đầy Đủ" — Design Spec

**Date:** 2026-07-21
**Status:** revised after 4-agent adversarial review (see §Review log)
**Depends on:** Plan A (FB observer verify + recon, PR #34, branch `feat/fb-fingerprint-observer`)

## Goal

Make camoufox present a coherent, real-browser identity against Facebook's
**observed** client-side tracking: close the devicePixelRatio + window-geometry
coherence gaps FB reads, audit the rest of FB's read surface for **cross-layer**
internal coherence, document the identity/cookie-linkage hygiene FB's persistent
cookies demand, and spot-check the behavioral surface the homepage never
exercised.

Evidence-first: every workstream traces to a fact measured against the real
browser. The adversarial review below overturned the first draft's fix — read
§"The dpr mechanism" before touching code.

## Grounding evidence

Live recon — real `https://www.facebook.com/`, logged out, one navigation, n=1
(`build-tester/observer/recon_fb_live.json`):

- **Device surfaces read:** `canvas`×1, `webgl`×1, `screen`×1, `navigator`×2.
- **Cookies set** (`.facebook.com`): `datr`, `sb`, `fr` (identity/anti-abuse/ad
  linkage) + `dpr`, `wd` (device signals: devicePixelRatio, window dimensions)
  + `ps_l`, `ps_n` (login-state).
- **Requests:** `static.xx.fbcdn.net`×22, `www.facebook.com`×5, `www.instagram.com`×1.

> **Caveat (carried forward from `build-tester/observer/REPORT.md:72`):** this is
> one logged-out load. It is thin and likely unrepresentative of Meta's full
> tracking surface — a registered pixel firing `/tr`, or a logged-in/challenge
> flow, may read more. The per-surface counts are a categorical bucket
> (`SURFACE_NAMES` in `harness.py`), **not** per-property: `navigator:2` means
> "navigator was touched twice", not "these two properties". Do not read this as
> "FB reads only canvas/webgl/screen/navigator."

dpr leak (`build-tester/observer/probe_dpr.py`, **headful** — headless forces
dpr=1.0 and masks it): a Windows-1080p config still reports the host's dpr=2.0.
**Caveat:** this probe drives Marionette + `CAMOU_CONFIG`, which **bypasses the
Playwright/Juggler layer** — so it measures only the MaskConfig channel, not a
real `Camoufox()` launch. See below.

Split-brain proof (`build-tester/observer/probe_split.py`, **headful**, host
dpr=2, forcing the MaskConfig key `window.devicePixelRatio=1`):

```
{"getter": 1, "mm_1dppx": false, "mm_2dppx": true, "mm_min15": true}
```

The JS getter reads the forced `1`, but `matchMedia('(resolution: 2dppx)')` still
matches the host `2`. **The MaskConfig key patches only the JS getter and leaves
every layout-derived surface at the host value.**

## The dpr mechanism (corrected)

camoufox has **two independent dpr channels** that do not talk to each other:

1. **JS-getter channel** — `patches/fingerprint-injection.patch:124` early-returns
   `MaskConfig::GetDouble("window.devicePixelRatio")` from
   `nsGlobalWindowInner::GetDevicePixelRatio`, *before* `GetPresContextForRatio`.
   Changes only `window.devicePixelRatio` the number.
2. **Layout channel** — `additions/juggler/TargetRegistry.js:611`
   (`overrideDPPX = zoom * (deviceScaleFactor || _initialDPPX)`), a Gecko
   `BrowsingContext` RDM override that drives `nsPresContext`'s CSS-to-device
   scale — which is what `matchMedia('(resolution)')`, CSS `resolution`,
   canvas backing-store, and `Page.screenshot` scaling all read.

The first draft mapped the preset dpr onto channel 1 (the MaskConfig key). The
review + `probe_split.py` prove that manufactures a **page-verifiable
contradiction** (getter ≠ matchMedia) that is **strictly worse** than the
host-passthrough leak — pre-fix, both channels read the same host presContext
value, so they at least agreed.

**The correct fix drives channel 2.** Because `GetDevicePixelRatio` falls through
to `GetPresContextForRatio` when the MaskConfig key is unset, setting
`overrideDPPX` (via Playwright `device_scale_factor`) moves **both** the getter
and matchMedia together → coherent. `additions/juggler/protocol/PageHandler.js:339`
(`overrideDPPX || window.devicePixelRatio`) confirms the layout channel already
takes precedence for privileged reads. So: **set `device_scale_factor`, leave the
MaskConfig `window.devicePixelRatio` key unset.**

**Why WS2 is still needed** (the leak is real despite channel 2 existing): there
are three fingerprint→config paths and only one wires dpr correctly —

| Path | Entry | dpr → `device_scale_factor`? |
|---|---|---|
| `from_browserforge()` (synthetic) | `Camoufox(fingerprint=…)` | **No** — `browserforge.yml:40` mapping is commented out |
| `from_preset()` (real scraped) | `Camoufox(fingerprint_preset=…)` | **No** — hand-rolled `fingerprints.py:502-598`, never reads dpr |
| `generate_context_fingerprint()` | `NewContext()` / `AsyncNewContext()` | preset branch **yes** (`fingerprints.py:731-732,861-863`); synthetic branch **no** — hardcodes `devicePixelRatio: None` at `fingerprints.py:803` |

`plan/device-faking-targets.md:56` (#24) already claims "dpr already tracked" —
true **only** for the `NewContext()` preset branch. This spec narrows that claim:
the default `Camoufox()` launch (both `from_preset` and `from_browserforge`) and
the synthetic `NewContext()` branch still leak.

## Decision (revised)

**WS2 drives each fingerprint path's dpr into `context_options['device_scale_factor']`**
(→ `overrideDPPX` → coherent across getter + matchMedia + layout + screenshots).
Do **not** use the `window.devicePixelRatio` MaskConfig key. Build-free
(`device_scale_factor`/`overrideDPPX` are already compiled into Juggler).

## Workstreams

### WS1 — Cross-layer coherence audit (test-only)

**File:** `build-tester/observer/audit_coherence.py` (new)

Launch via the **real Playwright `Camoufox()`** path (the editable pythonlib
install per `build-tester/run_tests.sh:60-61` — **not** `requirements.txt`'s stale
`cloverlabs-camoufox==0.6.0`, which is a different package). Marionette cannot be
used: it bypasses Juggler and so cannot observe the `overrideDPPX`/matchMedia
channel where the bug lives. Read FB's surface back via `page.evaluate` and
assert:

1. **dpr cross-layer coherence (the load-bearing assert):**
   `window.devicePixelRatio === claimedDpr` **AND**
   `matchMedia('(resolution: ' + claimedDpr + 'dppx)').matches === true`. Both
   arms required — the second is what catches the split-brain. **Fails before WS2**
   for the leaking paths, passes after.
2. **All three paths:** run assertion 1 for `fingerprint=` (synthetic),
   `fingerprint_preset=` (real preset), and `NewContext()` — each has different
   wiring (table above), so each is a distinct case.
3. **Window geometry (`wd` cookie):** `window.outerWidth/outerHeight/innerWidth/`
   `innerHeight/screenX/screenY` are present and satisfy
   `inner ≤ outer ≤ avail ≤ screen` on both axes. (0/312 presets carry these;
   `from_preset()` never sets them → host passthrough today — same bug class as dpr.)
4. **screen/dpr sanity:** `availWidth/Height ≤ width/height`; the claimed dpr is a
   plausible scale factor (rounds to a real OS DPI step, or `width×dpr` is
   integral) — some presets carry back-computed irrational dpr (`1.7647…`) that is
   itself a rare tell.
5. **navigator consistency:** `platform` ↔ `userAgent` OS ↔ `oscpu`;
   `maxTouchPoints === 0` when `platform ∈ {MacIntel, Linux x86_64}`;
   `hardwareConcurrency` in a per-OS plausible range.

Assertion 5's property choice is superset coverage, **not** evidence-traced (the
recon is categorical, not per-property — see grounding caveat). WebGL-renderer↔OS
coherence and canvas/webgl determinism are **not** re-checked here:
determinism is already gated by `build-tester/src/lib/checks/collectors.ts:434-456`;
renderer↔OS is data-gated (per the saturation audit) — observe-only.

**Feasibility (Task 1, step 1):** confirm the editable `camoufox` package launches
the local `/tmp` binary via Playwright (point it at the binary; `build-tester/`
scripts already `from camoufox.fingerprints import …` successfully, so import is
proven). If a full Playwright launch is genuinely impossible in the harness, the
fallback is (a) a pure-Python assert that `from_preset()`/`generate_context_`
`fingerprint()` **emit** a non-None `device_scale_factor`/dpr for a dpr-bearing
preset — call the real functions, do **not** re-implement the yml mapping — **plus**
(b) a Marionette end-to-end. But (b) cannot see the matchMedia channel, so the
fallback is explicitly weaker and must be labeled as not covering assertion 1's
second arm.

**Verify:** run the audit → assertion 1 (both arms) FAIL pre-WS2 for the leaking
paths, PASS post-WS2; others pass. Committed truth table + JSON.

### WS2 — dpr-fix (via device_scale_factor / overrideDPPX)

**Files:** `pythonlib/camoufox/fingerprints.py` — wire each leaking path's dpr into
`context_options['device_scale_factor']`:
- synthetic `generate_context_fingerprint`: replace the hardcoded
  `'devicePixelRatio': None` (`:803`) with the generated screen's dpr;
- `from_preset()` (`:502-598`): thread `preset['screen']['devicePixelRatio']` into
  the emitted config the same way the working `NewContext` preset branch does;
- confirm the default `Camoufox()` launch path actually applies
  `device_scale_factor` to the context it creates (trace it — if the default
  launch never makes a context with this option, that path needs the wiring too).

Do **not** map the `window.devicePixelRatio` MaskConfig key (the split-brain
trap). Leave `browserforge.yml:40` commented, with a note pointing here.

**Verify:** (a) WS1 assertion 1 (both arms) flips FAIL→PASS for every path;
(b) **headful, host-dpr ≠ preset-dpr:** launch a dpr=1 preset on this Retina host →
`window.devicePixelRatio === 1` **and** `matchMedia('(resolution: 1dppx)').matches`
`=== true` (the single most important test — proves coherence, not just the getter);
(c) regression: the existing `build-tester` fingerprint suite still ≥1000
(note: it is Marionette-based and cannot itself catch a matchMedia split — (a)/(b)
are the real gate). Evidence: all three.

### WS3 — Identity/cookie hygiene + reconciliation (docs)

**File:** `docs/observer/fb-identity-hygiene.md` (new)

Operational playbook for FB's linkage cookies (`datr`/`sb`/`fr`) — the ephemeral
default (`persistent_context=False`, `sync_api.py:87`) already handles the common
case. Rules, each mapped to a verified pythonlib kwarg (grep-checked, no invented
flags): one identity = one fresh profile; distinct `user_data_dir` per identity if
persisting; one egress IP per identity (`proxy=`) — `datr` + IP correlate; don't
route TLS through a ClientHello-rewriting proxy (genuine FF JA3 is a strength,
`plan/device-faking-targets.md:140,218`); post-WS2, `dpr`/`wd` cohere with the
profile.

Also (cheap, provenance): note that `plan/device-faking-targets.md:56` #24's
"dpr already tracked" is now narrowed (true only for `NewContext` preset), and
that `docs/observer/README.md:106` still claims a stale "canvas-only" observer
scope (all 7 surfaces are wired — `recon_fb_live.json` proves it). Fix or flag.

**Verify:** every option name exists in `pythonlib` (grep-checked).

### WS4 — Behavioral spot-check (recon addendum, shrunk)

**File:** `build-tester/observer/recon_fb_behavioral.py` (new, small)

Per the review, this is **downgraded from a headline workstream to a spot-check**:
audio/font fingerprinting (`OfflineAudioContext`, glyph metrics) fire at page load
without a gesture, and WebRTC needs an actual call feature — so a logged-out
scroll/hover pass will **probably** report "nothing new beyond WS1's recon", which
is a valid, honestly-reported negative, not a finding to chase. One logged-out
interaction pass + longer settle; if it surfaces nothing, that closes the question
cheaply rather than leaving it open.

**Verify:** `recon_fb_behavioral.json` (surface delta vs homepage); honest negative
if that's the result.

## Global constraints

- **Build-free.** No rebuild, no new patch — the fix routes through the
  already-compiled `overrideDPPX`/`device_scale_factor` channel. WS2 is
  pythonlib-only (`fingerprints.py`), persists as a normal edit (not the
  regenerated `camoufox-*/` tree).
- **WS1 must use the editable pythonlib install** (`run_tests.sh` path), launched
  via **real Playwright**, not Marionette — the bug is invisible to Marionette.
- **Recon is logged-out only:** no credentials, single session, no automated loops.
- **Evidence in the PR:** each workstream's verification output. WS2's real gate is
  WS1 assertion 1 (both arms) + the headful matchMedia test — the Marionette
  fingerprint suite is a regression backstop only.
- Repo `lang315/camoufox`; standard commit/PR footers.

## Out of scope

- No login/credentialed FB flows.
- No new C++/patches, no rebuild. (If tracing reveals the default `Camoufox()`
  launch genuinely cannot carry `device_scale_factor` without a Juggler/C++
  change, that is a STOP-and-escalate — it breaks the build-free premise.)
- WebGL-renderer↔OS coherence (data-gated; observe-only).
- Canvas/webgl determinism (already covered by `collectors.ts:434-456`).
- `TargetRegistry.js.bak` stale-copy cleanup (noted, not in scope).

## Review log (4-agent adversarial pass, 2026-07-21)

- **CRITICAL, all 4 agents + `probe_split.py`:** first-draft WS2 (MaskConfig key)
  is a getter-only override → page-verifiable split-brain vs matchMedia, worse than
  the leak. → Fix redirected to the `overrideDPPX`/`device_scale_factor` layer.
- **CRITICAL, 3 agents:** WS2's `browserforge.yml` edit misses `from_preset()` and
  the synthetic `:803` hardcode → the flagship "real preset" path still leaks. →
  WS2 rescoped to `fingerprints.py`, all three paths; WS1 tests each.
- **IMPORTANT:** WS1/WS2 verification was same-layer circular (never probed
  matchMedia); Marionette can't see the Juggler channel; build-tester installs a
  stale package. → WS1 uses editable install + real Playwright + a matchMedia
  assertion.
- **IMPORTANT:** `wd`-cookie window geometry is the same host-passthrough bug for
  presets; navigator `maxTouchPoints`/`hardwareConcurrency` unchecked; some preset
  dpr values are implausible. → added to WS1.
- **IMPORTANT:** n=1 recon over-generalized; assertion 3 not evidence-traced;
  contradicts `device-faking-targets.md:56` #24. → caveats added, #24 narrowed.
- **MINOR:** WS4 likely theater; stale `README.md`; `.bak` clutter. → WS4 shrunk;
  README/`.bak` noted in WS3/out-of-scope.
