# Tracking Observer — operator guide

A privacy-audit tool built into this camoufox fork. When armed, it shows you —
live, in a browser tab — **what a website actually reads from your machine**
(fingerprint surfaces) and **what it sends back** (network requests), correlated
per site. Built to answer "what do facebook.com / instagram.com / threads.net
actually collect about me."

It is **observe-only**: it never blocks or alters anything. Spoofing is handled
by the other patches; this feature only *reports*.

## Enabling it

The observer is **off by default** and gated by an environment variable, read
once at startup and cached (so a default profile does zero observer work).

```bash
CAMOU_OBSERVE=1 /path/to/camoufox-bin
```

With the variable unset (or `0`), nothing registers: no actor, no network
observer, no panel, and the C++ ring buffer is never touched.

## Reading the results

Open the panel in a tab:

```
chrome://camoufox/content/tracking.html
```

(There is deliberately no toolbar button or auto-open — navigate to the URL.)

Each row is one `(site, userContextId)` pair, showing:

- **surface badges + counts** — which fingerprint APIs the page read and how
  many times (e.g. `canvas:3`, `webgl:12`, `fonts:1`, `webrtc:2`).
- **request count** — how many network requests that site issued.
- **top third-party hosts** it talked to.

`facebook.com`, `instagram.com`, `threads.net` are pinned and highlighted.

## What it CANNOT see (read this — silence is not safety)

The panel lists a **"Not observable"** section for a reason. A surface being
absent from a row does **not** mean the site didn't read it. The observer is
blind to:

- **Engine-cached surfaces** — timezone, locale / `Intl`. These are resolved
  once per process into the JS engine, so page reads touch no hook. A count here
  would be fiction; they are not shown.
- **Un-spoofed surfaces** — `navigator.vendor`, `plugins` / `mimeTypes`,
  `deviceMemory`, `userAgentData` (Client Hints), `mediaDevices.enumerateDevices`,
  `getBattery`, `navigator.connection`. These return the **real** device value
  without consulting any spoof config, so there is nothing to hook. This is the
  most important blind spot: it is exactly where the real value leaks.
- **Worker / OffscreenCanvas** reads that happen off the main thread with no
  owning document.

Treat the panel as "spoofed-surface consultations," not "everything they read."

## Attribution granularity

Rows are keyed by **site (eTLD+1) + userContextId**, not full origin. Under
Firefox's process isolation (Fission) a content process is roughly one site, so
site-level is the honest granularity. A cross-origin widget (e.g. a Facebook
"like" button embedded on another page) is attributed to its own site, joined to
network activity on the same `(site, userContextId)` key.

## Detectability caveat

Observe-mode is an **audit tool, not a stealth mode.**

- The C++ record path is a single lock-guarded, allocation-free ring-buffer push
  (no IPC/observer/serialize on the fingerprint read), designed to stay below
  timing-measurement noise. The `timing_parity_probe.js` in `build-tester`
  checks this: armed readback latency/variance must stay within the unarmed
  build's own run-to-run band.
- Even so, if you are auditing a site whose specific goal is to detect
  instrumentation, do not assume observe-mode is invisible. Use it to *learn what
  a site collects*, then browse that site normally (observer off) when staying
  hidden matters.
- The default (unarmed) binary is unaffected: the gate is a cached boolean, so
  the fingerprint hot path is byte-identical to a build without this feature.

## Data handling

All captured data (visited sites, third-party hosts, per-surface counts) lives
in an in-memory, bounded ring buffer in the parent process and is **never
written to disk, the console, or the profile.** It is cleared on shutdown.

## How it works (brief)

```
page reads a fingerprint surface (canvas readback, ...)
  → C++ AccessObserver::Record(userContextId, site, surface, ts)   [ring buffer push]
  → TrackingObserverChild drains via ChromeUtils.camouDrainAccessRecords() on a timer
  → sendAsyncMessage → TrackingObserverParent → Collector          [parent, memory-only]
network: http-on-modify-request (read-only) → Collector.ingestNet(...)
Collector change → Services.obs notify → chrome://camoufox panel re-renders
```

The read path does only the ring-buffer push; all IPC, JSON, and rendering
happen asynchronously off that path.

## Scope / status

This is Step 1: infrastructure + the **canvas** surface wired end-to-end. Other
per-access surfaces (webgl, webrtc, fonts, navigator, screen, audio) and the
engine-cached / un-spoofed surfaces are follow-on work; until then they appear in
the "Not observable" list.
