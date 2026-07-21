# FB Tracking "Mô Phỏng Đầy Đủ" — Design Spec

**Date:** 2026-07-21
**Status:** SUPERSEDED at execution. Both device-coherence premises this spec was
built on turned out to be **measurement artifacts, not bugs**: dpr (draft 1-2) was a
Marionette-bypasses-Juggler artifact; window geometry (this draft, WS2/WS3) was a
stale-venv artifact — `cloverlabs-camoufox` shadowed the editable install and ran
pre-#647/#666 code (commit `643ea83`). On current pythonlib the coherence audit is
**12/12 PASS** across all OSes. Net delivered: the audit harness (WS1) + the identity
hygiene doc (WS4). WS2/WS3 need no code; WS5 was skipped. See the PR for the honest
end-state. The workstream text below is kept for provenance, not as open work.

**Status (original):** re-grounded after empirical measurement (see §Measurement log) — the
first two drafts' dpr-fix premise was overturned by measuring the real launch path.
**Depends on:** Plan A (FB observer verify + recon, PR #34, branch `feat/fb-fingerprint-observer`)

## Goal

Make camoufox present a coherent, real-browser identity against Facebook's
**observed** client-side tracking, grounded in what the real `pythonlib` launch
actually produces — not in what a non-representative harness suggested. Concretely:
build a coherence audit that launches the real Playwright path, fix the genuine
incoherences it finds (window geometry), document the identity/cookie hygiene FB's
persistent cookies demand, and spot-check the behavioral surface.

## Measurement log (why this spec was rewritten)

Every device axis was measured against the real `camoufox` pythonlib + Playwright
launch (editable install, `executable_path` → the local beta.28 binary, headful
where the host's real value differs so a leak can't hide). Scripts in
`build-tester/observer/`.

- **dpr is NOT a leak — dropped.** Through the real pythonlib launch, `window.devicePixelRatio`
  is coherent and host-independent: NewContext synthetic = 1, a preset claiming dpr=2 = 2,
  default `Camoufox()` = 1 — on a Retina host whose real dpr is 2, and `getter == matchMedia`
  in every case. The earlier "dpr leaks host 2.0" result came from a **Marionette** probe,
  which bypasses Juggler's `overrideDPPX`/`device_scale_factor` — the exact channel that
  controls dpr for real users. No real pythonlib user leaks dpr. **The dpr-fix workstream
  had no genuine scope and is removed.** (Also confirmed: forcing the `window.devicePixelRatio`
  MaskConfig key produces a getter-vs-matchMedia split-brain — a second reason not to.)
- **Window geometry IS incoherent — the real target.** Multi-sample (4×/OS, headless, the
  real scraping mode) via `Camoufox(os=…)`:
  - **Windows: 3/4 broken** — `outerWidth = availWidth + 16 > screen.width` (e.g. screen 1920,
    outer 1936). A window reported wider than its own screen is physically impossible.
  - **macOS: 3/4 broken** — the synthetic screen is frequently `960×540` (implausibly small for
    a Mac), so the fixed headless window (`inner 1280×720`) and `outer 1728` dwarf it.
  - **Linux: 0/4** — clean.
  The config-level clamp `clamp_window_dimensions` (`fingerprints.py:376`) IS called
  (`utils.py:775`, gated only by `not _user_set_screen_window`) and `window.outerWidth` IS a
  spoofed key (`fingerprint-injection.patch`), yet the runtime still reports impossible
  geometry — so the fix requires root-causing the config→runtime gap, not just re-running a clamp.

This confirms, again, the project's saturation finding: the genuine device-coherence
surface is nearly closed. The one real gap is window geometry.

## Workstreams

### WS1 — Coherence audit harness (test)

**File:** `build-tester/observer/audit_coherence.py` (new)

Launch via the **real Playwright `Camoufox()` / `NewContext()`** path (editable pythonlib
install per `build-tester/run_tests.sh:60-61` — not the stale `requirements.txt` pin;
`executable_path` → the local binary; `ff_version=152` to skip the not-installed-browser
check; place `settings/properties.json` next to the binary so `validate_config` finds it).
Multi-sample per OS; for each, `page.evaluate` FB's read surface and assert:

1. **Geometry nesting:** `inner ≤ outer ≤ avail ≤ screen` on **both** axes. (Fails today for
   Windows/macOS — the failing test that drives WS2/WS3.)
2. **dpr coherence:** `window.devicePixelRatio == expected` (1 synthetic, preset value for
   presets) **and** `matchMedia('(resolution: …dppx)')` agrees. (Passes today — a regression
   guard, catching any future split-brain.)
3. **navigator consistency:** `platform` ↔ `userAgent` OS ↔ `oscpu`; `maxTouchPoints == 0`
   for desktop `MacIntel`/`Linux x86_64`.

Report a per-OS pass/fail truth table + committed JSON. Headless is the primary mode (real
scraping); dpr assertions additionally verified headful once (headless floors dpr to 1).

**Verify:** run it → geometry fails for Windows/macOS pre-fix, all green post-WS2/WS3.

### WS2 — Fix window-geometry incoherence (root-cause + fix)

**Files:** `pythonlib/camoufox/fingerprints.py` / `utils.py` (the clamp + browserforge
mapping). This is a **systematic-debugging** task, not a pre-scripted edit — the config clamp
is already called yet runtime geometry is still impossible, so Task 1 first instruments
config-vs-runtime to locate the gap. Leads: is `window.outerWidth` populated for the synthetic
path (browserforge may omit it, as it did dpr)? Is a real-window chrome offset (~16px) added
after the spoof? Does `clamp_window_dimensions`'s `outer > outer_cap` check use the right cap
when `avail == screen`? Fix so `outerWidth ≤ screen.width` holds at **runtime**.

**Verify:** WS1 geometry assertion flips FAIL→PASS for Windows; the existing `build-tester`
fingerprint suite (≥1000) does not regress.

### WS3 — Fix implausible headless screens (macOS `960×540`)

**Files:** `pythonlib/camoufox/fingerprints.py` / `utils.py` (screen generation —
`get_screen_cons`, the headless screen constraint at `utils.py:755`). Determine whether the
tiny macOS screen is a browserforge data quirk or a headless `get_screen_cons` behavior, then
ensure generated/selected screens are ≥ the headless window (no `screen < inner`). Reject or
regenerate implausibly-small desktop screens.

**Verify:** WS1 geometry passes for macOS across samples; no regression.

### WS4 — Identity/cookie hygiene (docs)

**File:** `docs/observer/fb-identity-hygiene.md` (new)

Playbook for FB's linkage cookies (`datr`/`sb`/`fr`) — the ephemeral default
(`persistent_context=False`, `sync_api.py:87`) already handles the common case. Rules mapped
to verified pythonlib kwargs (grep-checked): one identity = one fresh profile; distinct
`user_data_dir` if persisting; one egress IP per identity (`proxy=`); don't route TLS through
a ClientHello-rewriting proxy (genuine FF JA3 is a strength, `plan/device-faking-targets.md:140,218`).
Also note (provenance): dpr is confirmed coherent via `overrideDPPX` (narrows
`device-faking-targets.md:56` #24), and `docs/observer/README.md:106` still carries a stale
"canvas-only observer" claim (all 7 surfaces are wired).

**Verify:** every option name exists in `pythonlib`.

### WS5 — Behavioral spot-check (recon addendum)

**File:** `build-tester/observer/recon_fb_behavioral.py` (new, small)

One logged-out interaction pass (scroll + hover) + longer settle vs `recon_fb_live.py`, to see
whether `audio`/`fonts`/`webrtc` (untouched on the homepage) activate and whether a `/tr`
beacon fires. A still-light result is a valid, honestly-reported negative.

**Verify:** `recon_fb_behavioral.json` (surface delta); honest negative if that's the result.

## Global constraints

- **Build-free.** No rebuild, no new C++ patch. All fixes are pythonlib-level (`fingerprints.py`/
  `utils.py`); they persist as normal edits (not the regenerated `camoufox-*/` tree). If root-
  causing WS2/WS3 shows the fix genuinely needs a C++/Juggler change or touches the `no_viewport`/
  #666 window-strategy, that is a STOP-and-escalate, not a forced patch.
- **WS1 uses the editable pythonlib + real Playwright**, not Marionette — Marionette bypasses
  Juggler and mismeasured dpr; it is banned as a coherence oracle here.
- **Recon logged-out only:** no credentials, single session, no automated loops.
- **Evidence in the PR:** each workstream's verification output (the audit truth table is WS2/WS3's
  real gate; the Marionette fingerprint suite is a regression backstop only).
- Repo `lang315/camoufox`; standard commit/PR footers.

## Out of scope

- No dpr code change (measured coherent).
- No login/credentialed FB flows.
- No new C++/patches, no rebuild.
- WebGL-renderer↔OS coherence (data-gated; observe-only).
- Canvas/webgl determinism (already covered by `build-tester/src/lib/checks/collectors.ts:434-456`).

## Measurement scripts (grounding, committed under `build-tester/observer/`)

`probe_dpr.py` (Marionette dpr — the misleading result that bypasses Juggler),
`probe_split.py` (MaskConfig-key getter-vs-matchMedia split-brain), `geom_multi.py`
(real-pythonlib multi-sample: dpr coherent + geometry impossible for Windows/macOS).
These are the evidence for every claim above.
