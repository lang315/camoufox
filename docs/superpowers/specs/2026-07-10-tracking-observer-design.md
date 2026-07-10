# Tracking Observer — design (v2, post-review)

Date: 2026-07-10
Status: revised after 4-way adversarial review → next: user re-review → implementation plan
Branch: `feat/tracking-observer`

## Changelog

- **v2 (this doc)** supersedes v1's *config-getter chokepoint → live panel* design.
  Four independent adversarial reviews (Gecko-feasibility, anti-detection
  security, correctness/data-model, simplicity) rejected v1: the chokepoint
  cannot attribute a read to an origin, is wrong for engine-cached surfaces,
  blind to un-spoofed ones, and the panel/actor plumbing was both a
  self-detection + chrome-XSS risk. v2 = **Option Y: faithful per-surface
  observer**, chosen by the operator for a trustworthy per-origin signal that
  can also stay below the trackers' detection threshold.

## Goal

Privacy-audit data source: while browsing, observe what a site *actually reads*
from the machine (fingerprint surfaces) and what it *sends back*, correlated per
site, shown live — so the operator can verify what facebook.com /
instagram.com / threads.net collect. Deepest layer (C++), page-invisible,
observe-only.

## Why Option Y (and not v1's chokepoint, and not the cheap proxy)

- **Chokepoint (`MaskConfig::Get*`) rejected** — `GetString(const std::string&
  key)` (`MaskConfig.hpp:94`) carries no window / userContextId, and
  `nsIObserverService` is process-global + principal-less, so per-origin
  attribution is unsound (a fb like-button iframe on nytimes.com is
  mis-tagged). It is also called once-at-init for engine-cached surfaces and
  never for un-spoofed ones.
- **Cheap `printf_stderr` proxy rejected** by the operator — it inherits the
  same cached/un-spoofed blind spots *and* a per-read `stderr` syscall is itself
  a timing tell. Fine for a rough audit, not for a trustworthy one.
- **Option Y** hooks each surface at its **DOM-operation boundary**, where the
  code already holds a `BrowsingContext`/userContextId, and carries that context
  **into the emit**. A thread-safe, allocation-free ring buffer drained
  asynchronously keeps the read path timing-identical to stock Firefox. This is
  the only design that is both correct (real per-origin reads) and stealth-safe
  (no measurable getter slowdown).

## Non-goals (v1 of Y)

- Decoding/deobfuscating tracker payloads.
- Response-body capture (deferred; highest-sensitivity, hardening-gated).
- Page-side JS shims (detectable, blind to native reads).
- Blocking/altering tracking. Observe-only.

## Architecture / event flow

```
CONTENT PROC (C++, per surface)                 PARENT PROC (registered once, profile-after-change)
 page calls a fingerprint DOM op
   → surface hook computes spoof value
     → AccessObserver::Record(                  ┌──────────────────────────────────────┐
          userContextId, principal/site,        │  Collector (memory-only, per-site)     │
          surfaceId)      ── O(1) push ──▶ [ thread-safe ring buffer ]                   │
                                                │           ▲                            │
   (async, OFF hot path)                        │           │ batched sendAsyncMessage   │
     TrackingObserverChild (JSWindowActor) ─ drains buffer ─┘  (native actor messaging)  │
                                                │                                        │
 http-on-modify-request (parent) ──────────────┼─▶ NetHook (read-only) ─────────────────┤
                                                │           join on (site, userContextId)│
                                                └──────────────────┬─────────────────────┘
                                                                   ▼
                                                    chrome://camoufox panel tab
                                                    (textContent + strict CSP, live)
```

Hot path = one O(1) ring-buffer push (a few ns, low variance, callable from any
thread). All cross-process/JS/serialize work happens on an async drain,
decoupled from the read.

## Components

### 1. `AccessObserver` (new, `additions/camoucfg/`) — thread-safe emit + ring buffer
- **Interface:** `AccessObserver::Record(uint32_t userContextId, const nsACString& site, SurfaceId surface)`.
- **Hot path:** if instrumentation not armed → single always-not-taken branch, return. Else push a fixed-size POD record `{userContextId, siteHash, surface, ts}` into a **mutex-guarded/lock-free bounded ring buffer**. No allocation, no IPC, no observer-service, no main-thread dispatch → **callable from worker threads** (solves the OMT problem; canvas/webgl/audio worker reads are captured, not dropped).
- **Drain:** exported accessor lets the content-side actor pull + clear batches on a low-frequency timer/idle callback.
- **Gate:** **compile-time flag** (`--enable-camou-observe` mozconfig / `#ifdef`) preferred — production/default binaries contain zero instrumentation, hot path byte-identical. Runtime fallback if needed: `CAMOU_OBSERVE` read **once** into a `static const bool` via `std::call_once` (mirror `GetJson()`, `MaskConfig.hpp:50`) — never `getenv` per call.
- **Dep note:** today `MaskConfig.hpp` has zero XPCOM deps; the ring buffer keeps it that way (no `GetObserverService` inline into every TU).

### 2. Per-surface hook sites + surface inventory
Emit at the **DOM-operation boundary** (one emit per JS-observable op → counts mean reads), passing the `userContextId` + top-site the site already has in scope. Inventory drives the rollout and the honest UI labels:

| Surface | Hook site (evidence) | Fires per read? | Context in scope? | Category |
|---|---|---|---|---|
| Canvas | `CanvasRenderingContext2D::GetImageBuffer`/`GetImageDataArray`, `ClientWebGLContext::ReadPixels` (`canvas-spoofing.patch`) | yes | yes (`bc->OriginAttributesRef().mUserContextId`, `:151`) | per-access spoofed |
| WebGL | `getParameter`/`getSupportedExtensions` boundary (dedup the `:376/:531/:536` fan-out) | yes (after dedup) | yes (`GetParentObject`) | per-access spoofed |
| WebRTC | `getMaskForIP` (`webrtc-ip-spoofing2.patch`) | yes | yes (userContextId param) | per-access spoofed |
| Navigator UA/platform/oscpu/hwConcurrency | per-access C++ getters (`navigator-spoofing.patch`) | yes | yes | per-access spoofed |
| Screen | screen getters (`screen-spoofing.patch`) | yes | partial (id-less keys `:52-75`) | per-access spoofed |
| Fonts | font list/hijacker | yes | yes | per-access spoofed |
| Audio | audio worklet/offline (`audio-fingerprint-manager.patch`) | yes | worker (OMT) | per-access spoofed |
| **Timezone / locale / Intl** | realm/ICU override set **once** (`navigator-spoofing.patch:210`, `timezone-spoofing.patch:157`) | **NO — engine-cached** | n/a | **engine-cached: needs JS-read-path hook (`getTimezoneOffset`/`resolvedOptions`), separate work item** |
| **navigator.vendor, plugins, deviceMemory, userAgentData, enumerateDevices, battery, connection** | **not gated by any getter today** | reads real value | n/a | **un-spoofed: not observable without new dedicated read hooks** |

The last two rows are the honest blind spots. They are **enumerated in the panel
UI** so the operator never reads silence as "site didn't touch this / safe."

### 3. `TrackingObserverChild` (JSWindowActor child) — async drain
- Drains the C++ ring buffer on a timer/idle callback, batches records, and forwards to the parent via **native `JSWindowActorChild.sendAsyncMessage`** (NOT juggler's `SimpleChannel` — that drags automation coupling; `JugglerFrameChild` is itself a plain `JSWindowActorChild`).
- Because context is carried in the record, the child does **not** reconstruct origin from its own window.

### 4. Registration component (`profile-after-change`, once per process)
- Registers the JSWindowActor (`ActorManagerParent.addJSWindowActors`), the `http-on-modify-request` observer, and the Collector **once** — via a `profile-after-change` XPCOM component modeled on juggler (`components.conf` + `Juggler.js:21`). Runs at every manual-browse startup, not under `--juggler`.
- **Not** `browser-init.js` for registration — that runs per-window → double-registration throw + N-fold duplicate net events + panel opening in every window. Only the guarded panel-open action (menu item / operator gesture) may live window-side.

### 5. `Collector` (parent, memory-only)
- Bounded per-site ring buffer keyed on `(site, userContextId)`. Merges access + net events, broadcasts deltas to the panel.
- **Memory-only, cleared on shutdown. Never written to disk/console/profile.** (Holds the operator's real browsing targets — sensitive.)

### 6. `NetHook` (parent, read-only)
- `http-on-modify-request` observer. **Strictly read-only** — capture `{host, url, method}` + `channel.loadInfo.originAttributes.userContextId` + top-site via `loadInfo.browsingContext?.top?.currentWindowGlobal?.documentPrincipal` (or `partitionKey`). **Never** call `setRequestHeader`/`cancel`/`redirectTo` — any mutation is a page-observable fingerprint. Return immediately; push to the same async buffer.

### 7. `chrome://camoufox` panel (new jar)
- New **non-content-accessible** `jar.mn` (`% content camoufox %content/`) + `moz.build`, modeled on juggler's jar (NOT branding's `contentaccessible=yes`).
- `tracking.html` + js: live table, one row per `(site, userContextId)`, surface badges + per-op counts, #requests, top third-party hosts; expand → timeline; fb/ig/threads pinned; **blind-spot surfaces listed explicitly as "not observable".**
- **Security:** render every captured string (host/url/site) via `document.createElement` + `textContent` **only** — never `innerHTML`/interpolation (chrome-privileged XSS = full compromise). Strict CSP: `default-src 'none'; script-src chrome://camoufox/…; style-src 'self'; object-src 'none'`, no inline, no eval.

## Data model

```
access = { type:"access", ts, userContextId, site, surface, /* count derived */ }
net    = { type:"net",    ts, userContextId, site, host, url, method }
```

- Emit carries `userContextId` + `site` from the C++ hook site (not reconstructed in JS).
- **Attribution granularity = site (eTLD+1) + userContextId**, the best achievable under Fission (one content process ≈ one site). The panel labels it "site", not "origin", so the operator isn't misled about sub-origin precision.
- **Join key = `(site, userContextId)`** for access↔net correlation (content side gives site; net side's `partitionKey` is also site → they string-match).
- Count = emits per JS-observable op (fan-out deduped) → a real read count.

## Security requirements (non-negotiable, from review)

1. **Timing parity** — observe-armed getter latency + variance within measurement noise of the disarmed build. Guaranteed by the ring-buffer hot path (no sync IPC/observer/alloc). **Enforced by a timing-parity test.**
2. **Default build inert** — compile-time flag (or cached bool); OFF path issues no `getenv` per call and is behaviorally identical to today. No actor/observer/panel exists when unarmed.
3. **Panel** — `textContent` only, strict CSP, escaping test with markup-laden hostnames.
4. **NetHook read-only** — request headers + ordering byte-identical armed vs disarmed (tested).
5. **Memory-only** capture; no persistence.
6. **OMT** — worker canvas/webgl/audio reads captured via the thread-safe buffer (not dropped, not dispatched per-read, no off-main-thread observer-service call).

## Testing

- Env/flag OFF ⇒ zero emits + byte-identical hot path (assert).
- **Timing-parity:** `getParameter`/`toDataURL` latency+variance within noise of disarmed build (the test that actually defends anti-detection).
- NetHook: headers + request ordering identical armed vs disarmed.
- Panel: XSS escaping test (hostnames/URLs carrying markup render inert).
- Attribution: cross-origin iframe (fb widget on a third-party page) lands in the correct `(site, userContextId)` row.
- Per modified patch: rehearse `rc=0 rejects=0 skipped=0 wrongpath=0 fuzz=0 max|offset|=0` (`scripts/rehearse-patch.sh`).
- CI `Build` green. Runtime: `CAMOU_OBSERVE`/flag on → visit a canvas-FP tester + facebook.com → correct access + net rows; blind-spot surfaces shown as "not observable".
- ponytail self-check: feed synthetic access+net records → assert `(site,userContextId)` grouping + fb/ig/threads highlight + per-op counts.

## Risks

1. **Scope** — faithful coverage = ~7 per-access surfaces (patches + rehearsal cycles each) + the infra. Engine-cached (timezone/locale) + un-spoofed surfaces need *additional* dedicated read hooks; sequenced late, labeled as blind spots until then.
2. **Ring-buffer drain latency** — batched async drain means the panel lags reads by the drain interval (fine for audit; not a correctness issue).
3. **Site-level (not origin-level) attribution** under Fission — documented in UI.

## Rollout (within Y)

1. **Infra:** AccessObserver ring buffer + compile-time gate; `profile-after-change` registration component; native JSActor; Collector; `chrome://camoufox` jar + hardened panel skeleton; read-only NetHook. Ship end-to-end with **one** surface (canvas) wired → prove the pipeline + timing-parity + XSS tests.
2. **High-value per-access surfaces:** webgl, webrtc, fonts, navigator (UA/platform/hwConcurrency), screen, audio.
3. **Engine-cached surfaces:** timezone/locale/Intl via JS-read-path hooks.
4. **Un-spoofed surfaces:** add dedicated read hooks for vendor/plugins/deviceMemory/userAgentData/enumerateDevices/battery.
5. **Phase 2 (deferred):** real-vs-spoofed value diff per surface; network response bodies (inert-text, capped/redacted).

## Scope defaults (confirmed)

Gated off by default (compile-time preferred); all listed surfaces targeted per
rollout; all sites observed, panel highlights fb/ig/threads; site+userContextId
attribution; blind spots enumerated in UI, never silent.
