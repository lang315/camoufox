# FB Fingerprint Observer — Recon Report

Plan A ("FB observer verify + recon") final deliverable. Synthesizes Tasks 2-5: does the
built-in Tracking Observer actually record at runtime, what does Facebook's real
fingerprinting code touch, and where does an un-spoofed camoufox leak a real device value.
Numbers below are quoted from the committed artifacts — `recon_fb.json` and
`leak_evidence.json` — plus the printed truth tables from Tasks 2 and 3 (which produced no
separate JSON, only the test/gate output). No number here is invented.

## 1. Runtime gate

The one genuinely-unverified premise going into this plan: do all 7 wired observer
surfaces actually produce records at runtime, or only canvas (as the module's own README
claims)? Task 2 built a probe page that pokes all 7 and read the result back.

| Surface   | Poke | Recorded | Count |
|-----------|------|----------|-------|
| canvas    | ok   | yes      | 1     |
| webgl     | ok   | yes      | 1     |
| webrtc    | ok   | yes      | 1     |
| navigator | ok   | yes      | 1     |
| screen    | ok   | yes      | 1     |
| fonts     | ok   | yes      | 1     |
| audio     | ok   | yes      | 1     |

**7/7 surfaces recorded. No KNOWN-GAP.** This resolves `docs/observer/README.md`'s
"Scope / status" section, which currently states only canvas is wired end-to-end and the
other six are "follow-on work" — that claim is stale; runtime behavior shows all 7 already
recording.

**Readout method.** Content tabs cannot navigate to `chrome://` URLs at all — a categorical
restriction, not a misconfiguration — and the `chrome://camoufox` panel itself is compiled
privileged-only (no `contentaccessible=yes`), so scraping the panel from an automated
content-tab session is impossible by construction. The observer's records live in the
parent-process `Collector`, which is only reachable from chrome-privileged script.
Marionette's `using_context("chrome")` provides that directly: the harness switches into
chrome context and runs
`ChromeUtils.importESModule("resource://gre/modules/TrackingObserver.sys.mjs").getCollector().snapshot()`,
which returns rows keyed by `(site, userContextId)` with a `surfaces:{id:count}` map (ids
1-7 map to canvas/webgl/webrtc/navigator/screen/fonts/audio) and a parallel `requests` list
from the observer's NetHook.

**Detail worth noting.** The WebGL `Record()` call site lives on the pixel-*readback* path
inside `readPixels` (`dom/canvas/ClientWebGLContext.cpp`, next to the RFP canvas-noise
injection code), not in `getParameter()`. A probe that only calls `getParameter(VENDOR)` /
`getExtension()` never reaches that hook and would misread as a gap — the truth table above
reflects a probe that also does a `clear()` + `readPixels()` call, the WebGL analogue of the
canvas poke's `toDataURL()` readback.

## 2. What Meta's code reads

Task 4 drove the 7-surface observer against a local page embedding Meta's real
`fbevents.js` and `sdk.js` (dummy all-zero pixel ID, `fbq('init', ...)` followed by
`fbq('track', 'PageView')`). Full committed `recon_fb.json`:

```json
{
  "observer_surfaces": [
    { "site": "127.0.0.1", "surfaces": { "navigator": 1 } }
  ],
  "fb_request_hosts": ["connect.facebook.net"],
  "fb_request_count": 3,
  "cookie_names": []
}
```

Of the 7 instrumented surfaces, only `navigator` was touched, and only once. All 3 captured
requests went to `connect.facebook.net` (the bootstrap `fbevents.js`, `sdk.js`, and `sdk.js`'s
own secondary `bundle/sdk.js/` fetch); no request to a `/tr` beacon endpoint appeared, and no
cookie was set (`cookie_names: []`).

**Caveat — read before drawing any conclusion from this section.** This result is thin and
likely unrepresentative of Meta's real tracking surface, for two independent reasons:

1. The dummy pixel ID almost certainly gates Meta's `/tr` beacon and whatever heavier
   fingerprint reads ride on it. A real, registered pixel ID firing a real beacon may consult
   surfaces this stimulus never reached.
2. The observer is structurally blind to anything outside its 7 spoofed surfaces. If Meta's
   code reads `deviceMemory`, `hardwareConcurrency`, or any other un-spoofed value, that read
   is invisible here by construction — not because it didn't happen.

**Do not read this section as "Meta reads navigator only."** The honest statement is: of the
7 surfaces this observer instruments, this specific dummy-ID stimulus touched `navigator`
once. That is not the same claim as "navigator is Meta's full tracking surface." The
optional manual, logged-out facebook.com spot-check the plan permits (at most one,
human-paced, no automated loops) was not run in this task; it remains an operator-only
follow-up.

## 3. Leak evidence — the load-bearing result

Task 5 probed 8 un-spoofed `navigator`-adjacent surfaces directly (independent of the FB
stimulus) to determine which expose a real, device-varying value with no `MaskConfig` spoof
key — the actual scope for a follow-on Plan B. Full committed `leak_evidence.json`:

| Surface | Value | Present | Empty | Has MaskConfig key |
|---|---|---|---|---|
| `deviceMemory` | `<<absent>>` | no | yes | no |
| `plugins` | `["PDF Viewer","Chrome PDF Viewer","Chromium PDF Viewer","Microsoft Edge PDF Viewer","WebKit built-in PDF"]` | yes | no | no |
| `mimeTypes` | `["application/pdf","text/pdf"]` | yes | no | no |
| `vendor` | `""` | yes | yes (empty string) | no |
| `userAgentData` | `<<absent>>` | no | yes | no |
| `connection` | `<<absent>>` | no | yes | no |
| `battery` (`getBattery`) | `<<absent>>` | no | yes | yes |
| `devices` (`enumerateDevices`) | `["audioinput:","videoinput:"]` | yes | no | yes |

Mechanical classification (present + non-empty + no MaskConfig key ⇒ candidate), as printed
by the probe:

- **Plan-B candidates (raw):** `plugins`, `mimeTypes`
- **Skip (absent or empty constant — nothing to spoof):** `deviceMemory`, `vendor`,
  `userAgentData`, `connection`, `battery`
- **Observe-only (already has a MaskConfig key):** `battery`, `devices`

**The honest reading, not just the mechanical one.** `deviceMemory`, `userAgentData`, and
`connection` are absent because Firefox does not implement these Chromium-only APIs (Device
Memory, User-Agent Client Hints, Network Information) at all on FF152 — there is no value to
leak because there is no API. `vendor` is a spec-mandated permanent empty string in Gecko,
not a per-device signal. `getBattery` is absent because Firefox restricted/removed the
Battery Status API for fingerprinting reasons, and it already carries a MaskConfig key
regardless of its absence.

That leaves `plugins` and `mimeTypes` as the only surfaces that are both present and
un-spoofed. But both are Firefox's fixed, built-in PDF-viewer shim — a constant list
identical across every install of a given Firefox version, i.e. a **browser-family
constant**, not a value that varies per device or per user. Counting them as a generic
"leak" overstates what they are.

**Net for Plan B: the genuine device-value-leak spoof scope is effectively empty.** The
thing this recon was built to hunt for — a real, per-device value read off an un-spoofed
surface, with `deviceMemory` as the prime suspect — does not exist on Firefox 152. This is
the evidence gate paying off exactly as designed: spoofing `deviceMemory` would have been
wasted engineering effort chasing a surface that was never actually leaking anything,
because Firefox never implemented it in the first place. If `plugins`/`mimeTypes` are worth
touching in a future Plan B at all, the justification is browser-family consistency with a
fingerprint preset's claimed identity (matching what *that* browser/version would show), not
closing a device-level leak — stated plainly rather than dressed up as one.

## 4. Scope caveat

Verbatim, as required to appear in this report:

> This observes fingerprint-surface consultations at the JS/WebIDL boundary — presence +
> count, per (site, userContextId). It does NOT capture values, hashes, or FB's scoring. It
> is structurally blind to: TLS ClientHello / JA3-JA4 / HTTP-2 SETTINGS / TCP, WASM
> internals, Web/Service Workers, OffscreenCanvas, pure-CSS @media probes, timing
> side-channels, and anything FB computes server-side (datr linkage, egress IP, header
> order, encrypted beacon payloads). Silence in the panel ≠ the surface was not read, for
> anything unhooked.

## 5. Timing parity

Task 3 measured wall-clock timing for two ops, armed (`CAMOU_OBSERVE=1`) vs. unarmed, 3 runs
per arm, comparing per-op medians:

- **`toDataURL`** (canvas readback — the op that IS on the observer's `Record()` path):
  ratio ≈ 1.0 across all three runs (1.004, 0.982, and the final committed run's **0.997**)
  — comfortably inside the `<1.5x` pass band, indistinguishable from parity.
- **`getParameter`** (WebGL metadata query — deliberately *not* on an instrumented path,
  consistent with the Section 1 finding that WebGL's `Record()` site is in `readPixels`, not
  `getParameter`): both arms floored to exactly `0.0000ms` in every run, hitting Firefox's
  `privacy.reduceTimerPrecision` 1ms clamp before the loop produces a measurable duration.
  This is a probe-resolution floor, not a timing signal, so the gate reports `SKIP`
  (unmeasurable in both arms) rather than computing a division-by-zero ratio.

**Conclusion:** on the one operation that actually exercises the observer's
lock+hash+ring-buffer hot path, there is no measurable timing overhead. The observer's
page-invisible, C++-level design holds — nothing observed here would let page-side JS
distinguish an armed build from an unarmed one via `toDataURL` timing.

---

This report, together with the committed `recon_fb.json` and `leak_evidence.json`, is the
evidence gate that a follow-on Plan B (observe + spoof confirmed leaks) would be scoped
against. It is not written here. Per the plan's own framing, the headline result is that the
confirmed device-leak surface is smaller than assumed going in — not empty of nuance, but
empty of an actual per-device leak.
