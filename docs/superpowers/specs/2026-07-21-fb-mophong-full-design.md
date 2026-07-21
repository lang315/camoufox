# FB Tracking "Mô Phỏng Đầy Đủ" — Design Spec

**Date:** 2026-07-21
**Status:** approved for planning
**Depends on:** Plan A (FB observer verify + recon, PR #34, branch `feat/fb-fingerprint-observer`)

## Goal

Make camoufox present a coherent, real-browser identity against Facebook's
**observed** client-side tracking: close the one confirmed device-signal leak
(devicePixelRatio), audit the rest of FB's read surface for internal
coherence, document the identity/cookie-linkage hygiene FB's persistent
cookies demand, and extend the behavioral recon to the surfaces the
logged-out homepage never exercised.

This is evidence-first: every workstream traces to a fact already measured
against the real browser, not to a hypothesized threat.

## Grounding evidence (all measured this session)

Live recon — real `https://www.facebook.com/`, logged out, one navigation
(`build-tester/observer/recon_fb_live.json`):

- **Device surfaces read:** `canvas`×1, `webgl`×1, `screen`×1, `navigator`×2.
- **Cookies set** (`.facebook.com`): `datr`, `sb`, `fr` (identity/anti-abuse/ad
  linkage) + `dpr`, `wd` (device signals: devicePixelRatio, window dimensions)
  + `ps_l`, `ps_n` (login-state).
- **Requests:** `static.xx.fbcdn.net`×22, `www.facebook.com`×5,
  `www.instagram.com`×1 (cross-Meta pixel).

Empirical dpr leak (`build-tester/observer/probe_dpr.py`, **headful** — headless
forces dpr=1.0 and masks the leak):

- Arm A (no config): `dpr=2 screen=1512x982 platform=MacIntel` (real Retina host).
- Arm B (Windows 1920×1080 config): `dpr=2 screen=1920x1080 platform=Win32` —
  screen + platform spoof correctly, **dpr stays host 2.0**.
- Verdict: `devicePixelRatio` is **host passthrough, not config-controlled** —
  it varies by host hardware and contradicts the spoofed screen/profile.

Root cause (source): the C++ override key exists —
`patches/fingerprint-injection.patch` hooks
`nsGlobalWindowInner::GetDevicePixelRatio` on
`MaskConfig::GetDouble("window.devicePixelRatio")` — but the generator
**deliberately never sets it**: `pythonlib/camoufox/browserforge.yml` comments
out the `devicePixelRatio` mapping ("Any value other than 1.0 is suspicious").
The presets carry real scraped dpr values (`fingerprint-presets-v150.json`:
`devicePixelRatio` 2 / 1 / 2.6087) that are dropped before reaching the browser.

Build-free confirmation (`scratchpad/probe_dpr_key.py`): setting
`window.devicePixelRatio=3.0` on the **existing beta.28 binary** →
`window.devicePixelRatio` reads `3`. The override is already compiled in, so
the fix is a pythonlib mapping change only — no patch, no rebuild.

Profile default (source): `pythonlib` defaults `persistent_context=False`
(`sync_api.py:87`, `async_api.py:85`) → ephemeral profile, so `datr`/`sb`/`fr`
are wiped each launch by default. `fingerprints.py:350-379` already clamps
screen avail/outer/inner dims for coherence — dpr is the single axis skipped.

## Decision (approved)

**WS2 maps the preset's dpr into the browser**, overriding upstream's
"1.0-only" skip. Rationale: the comment is stale (Retina / 4K@200% legitimately
report 2.0, and the presets themselves are scraped with dpr=2); leaking the
host value is *worse* than a coherent preset value (it varies by host and
mismatches the spoofed screen); and FB demonstrably reads dpr (stores it in a
cookie). `overrideDPPX` is a safe reporting override with no real-display
dependency.

## Workstreams

### WS1 — Coherence audit (test-only)

**File:** `build-tester/observer/audit_coherence.py` (new)

Exercise the **real pythonlib fingerprint→config path** (the `browserforge.yml`
mapping where the dpr bug lives — not a hand-built `CAMOU_CONFIG`), then assert
FB's read surface is internally coherent. Assertions:

1. `devicePixelRatio` (as launched) == the fingerprint's claimed
   `screen.devicePixelRatio`. **Fails before WS2** (leak), passes after — this
   is the failing test that drives WS2.
2. `screen.width/height` == claimed screen (confirms the existing mapping).
3. `navigator.platform` is consistent with `navigator.userAgent` OS
   (`Win32` ⇒ "Windows NT" in UA; `MacIntel` ⇒ "Macintosh"); `oscpu` matches.

WebGL-renderer↔OS coherence is **observe-only** (data-gated — needs a
per-renderer parameter dataset, out of pure-scope per the saturation audit);
the audit may record it but must not assert or gate on it.

**Feasibility (Task 1, step 1):** confirm the `camoufox` pythonlib is importable
in the `build-tester` venv and can generate a config against the local binary.
If a full `Camoufox()` launch is impractical, fall back to applying the
`browserforge.yml` mapping to a preset directly (a pure unit assert that the
generated config contains `window.devicePixelRatio` == the preset value) plus a
Marionette end-to-end read of the launched browser. Either way the assertion
must flow through `browserforge.yml` — a hand-built `CAMOU_CONFIG` would not
catch the bug.

**Verify:** run the audit → assertion 1 FAIL pre-WS2, PASS post-WS2; 2 & 3 pass
throughout. Output printed truth table + committed JSON.

### WS2 — dpr-fix (generator mapping)

**File:** `pythonlib/camoufox/browserforge.yml` (uncomment/replace the skipped
`devicePixelRatio` line under `screen:` with an active
`devicePixelRatio: window.devicePixelRatio` mapping + a comment recording this
decision and its rationale).

The C++ key is already compiled in (confirmed build-free), so the preset's dpr
now flows to `window.devicePixelRatio` → the DOM override. No patch, no rebuild.

**Verify:** (a) WS1 audit assertion 1 flips FAIL→PASS; (b) direct check —
launch with a dpr=1 preset on this Retina host, browser reports dpr=1 (not host
2.0); (c) **regression guard** — run the existing `build-tester` fingerprint
suite (playwright==1.55.0 pin) to confirm adding the key breaks nothing
(≥1000 baseline). Evidence: all three outputs.

### WS3 — Identity/cookie hygiene (docs)

**File:** `docs/observer/fb-identity-hygiene.md` (new)

Operational playbook for FB's linkage cookies (`datr`/`sb`/`fr`) — not a code
change; the ephemeral default already handles the common case. Rules, each
mapped to the exact pythonlib knob (verified by grep, no invented flags):

1. One identity = one fresh profile. Don't share `persistent_context` /
   `user_data_dir` across identities.
2. If persistence is required, a distinct `user_data_dir` per identity, never
   cross-used.
3. One egress IP/proxy per identity (`proxy=`) — `datr` + IP correlate;
   reusing an IP links identities server-side regardless of cookies.
4. Don't route TLS through a proxy that rewrites the ClientHello — camoufox's
   JA3 is genuine Firefox, a strength (per `plan/device-faking-targets.md`
   lines 140/218).
5. Post-WS2, `dpr`/`wd` device signals cohere with the claimed profile.

**Verify:** every option name referenced exists in `pythonlib` (grep-checked).

### WS4 — Behavioral/beacon deep-dive (recon)

**File:** `build-tester/observer/recon_fb_behavioral.py` (new)

Extend `recon_fb_live.py`: after load, one logged-out interaction pass (scroll +
hover) and a longer settle, then snapshot — to see whether the surfaces the
homepage never touched (`audio`/`fonts`/`webrtc`) activate and whether a `/tr`
beacon fires. A still-light result is a valid negative and is reported as such,
not hidden.

**Verify:** produces `recon_fb_behavioral.json` (surface delta vs homepage +
request hosts); honest reporting of what did/didn't activate.

## Global constraints

- **Build-free.** No rebuild, no new patch (`window.devicePixelRatio` already
  compiled — verified dpr=3.0). WS2 is pythonlib-only; it persists as a normal
  file edit (not the regenerated `camoufox-*/` tree).
- **Recon is logged-out only:** no credentials, single session, no automated
  loops, human-paced (≤1 interaction pass). Real `facebook.com` navigation is
  the operator spot-check Plan A's REPORT deferred.
- **Evidence in the PR:** each workstream's verification output (command +
  result), per repo rule. No success claim without output.
- **WS1 is the gate for WS2** (TDD). The `build-tester` fingerprint suite is a
  regression guard for WS2 (it changes generated config for every fingerprint).
- Repo `lang315/camoufox`; standard commit/PR footers.

## Out of scope

- No login/credentialed FB flows.
- No new C++/patches, no rebuild.
- WebGL-renderer↔OS coherence assertion/fix (data-gated; observe-only).
- No change to the existing fingerprint suite beyond adding the coherence audit.
