# Tracking Observer — design

Date: 2026-07-10
Status: approved (brainstorming) → next: implementation plan
Branch: `feat/tracking-observer`

## Goal

Give the camoufox operator a **privacy-audit data source**: when the browser is
running, observe what a website *actually reads* from the machine and what it
*sends back*, so the operator can verify exactly which fingerprint/identity
signals sites like facebook.com, instagram.com, threads.net collect.

Two correlated signals, per the operator's choice:

1. **API reads** — which fingerprint surfaces a page touches (canvas, webgl,
   navigator, screen, fonts, audio, webrtc, media, geo, timezone…). Captured at
   the **deepest layer** (C++), invisible to the page.
2. **Network exfil** — what leaves the machine to tracker hosts (request
   URL/host/method; response bodies deferred to Phase 2).

Correlated per top-level origin and shown **live in a dedicated browser tab**.

## Non-goals (v1)

- Decoding/deobfuscating tracker payloads (they are usually encrypted/packed;
  the value is knowing *which* fingerprint was read, not reversing their blob).
- Response-body capture (Phase 2).
- Page-side JS shims (detectable, and blind to native reads — rejected on
  purpose; the whole point is a native, page-invisible hook).
- Blocking/altering tracking. This is observe-only. Spoofing already exists in
  the other patches; this feature only *reports*.

## Approach

Chosen: **C — hybrid, phased.**

- **Phase 1** — chokepoint access hook + network hook + live panel. One C++
  chokepoint (instrument the config getters every surface already calls) gives
  breadth across all ~15 surfaces with ~2 files touched. Ships the full
  end-to-end pipeline (the hard plumbing) fast.
- **Phase 2** — add precise per-surface emits (real value vs spoofed value,
  per-access counts) for the surfaces fb/ig/threads actually hammer (canvas,
  webgl, fonts, webrtc), plus network response bodies.

Rejected alternatives:

- **A (chokepoint only)** — breadth but never gets real-vs-spoofed precision.
- **B (per-surface only)** — precise but ~15 patches up front, big surface, slow
  to first value, and still needs the same panel plumbing.

## Event flow

```
CONTENT PROC (C++)                         PARENT PROC (JS, always-on startup hook)
 page touches surface                       ┌──────────────────────────────┐
   → MaskConfig::Get*()   ── notify ──▶ TrackingObserverChild (JSActor)     │
     RoverfoxStorage::Get*()           ── sendAsyncMessage ──▶ Collector ───┼──▶ chrome:// panel tab
                                                                            │      (live per-origin rows)
 http-on-modify-request  ─────────────────────────────────▶ NetHook ───────┘
```

Producers write into one parent-process **Collector**; the panel subscribes to
the Collector. Cross-process content→parent uses the JSWindowActor +
`SimpleChannel.sendAsyncMessage` pattern camoufox already ships in juggler.

## Components

Each unit: what it does / its interface / what it depends on.

### `AccessObserver.hpp` (new — `additions/camoucfg/`, content C++)
- **What:** single static `Record(const char* key)`. Env-gated by
  `CAMOU_OBSERVE`. When armed, fires `nsIObserverService` topic
  `"camoufox:fp-access"` with data `{key, ts}`.
- **Interface:** `AccessObserver::Record("canvas:seed");`
- **Deps:** `nsIObserverService`, `getenv`. **Main-thread-guarded** — some
  getters run off-main-thread (workers / OMT offscreen canvas); notify only when
  `NS_IsMainThread()`, otherwise `NS_DispatchToMainThread` a lightweight
  runnable (or drop, decided in plan). Zero work when env unset.

### Getter instrumentation (Phase 1 chokepoint)
- **What:** one-line `AccessObserver::Record(key)` inside the read path of
  `MaskConfig::GetString / GetUint32 / GetBool / GetDouble / GetNested` and
  `RoverfoxStorageManager::GetString / GetUint / GetBool`.
- **Why it works:** the config **key already names the surface**
  (`canvas:seed`, `webGl:parameters`, `navigator.userAgent`,
  `webrtc:localipv4`, `font:...`). No new taxonomy needed.
- **Touched:** `additions/camoucfg/MaskConfig.hpp` + the RoverfoxStorageManager
  definition (a patch). ~2 files.

### `TrackingObserverChild` (JSWindowActor child, content JS)
- **What:** observes `"camoufox:fp-access"` in the content process, tags each
  event with `{origin, userContextId}` from its window, forwards to the parent
  actor.
- **Deps:** JSWindowActor registration; `SimpleChannel` pattern.

### `Collector` + `NetHook` (parent JS, in the always-on startup hook)
- **Collector:** receives access + net events, keeps a bounded per-origin ring
  buffer, broadcasts deltas to the panel.
- **NetHook:** `http-on-modify-request` observer → `{origin, host, url,
  method}`. (Always-on; does **not** depend on juggler.)
- **Home:** a `browser-init`-style startup patch (chrome-privileged, runs
  during manual browsing). Chosen over autoconfig `settings/camoufox.cfg`
  because the AutoConfig sandbox can't cleanly register a JSWindowActor or open
  the panel tab. **Not** juggler (juggler runs only under Playwright
  automation, not manual browsing).

### Panel (`chrome://camoufox/content/tracking.html` + js)
- **What:** live table, one row per top-level origin. Columns: surface badges +
  counts, #network requests, top third-party hosts. Expand a row → chronological
  event timeline. fb/ig/threads pinned and highlighted.
- **Deps:** subscribes to Collector (chrome-privileged page messaging). Plain
  HTML/JS, no build step.

### Config / toggle
- Off by default. `CAMOU_OBSERVE=1` arms: C++ emit + parent hooks + auto-open
  panel tab. Env check precedes any work → zero overhead when off.

## Data model

```
access = { type:"access", ts, userContextId, origin, surface, key }
net     = { type:"net",    ts, userContextId, origin, host, url, method }
```

- `surface` derived from `key` prefix (`canvas`, `webGl`, `navigator`,
  `webrtc`, `font`, `audio`, `screen`, `media`, `geo`, `timezone`).
- **Correlation = group by `origin`** (top-level page origin) within a session.
- fb/ig/threads matched by host allowlist (`facebook.com`, `instagram.com`,
  `threads.net`, `*.fbcdn.net`, `graph.facebook.com`, …) → highlighted.

## Testing

- **Env-off ⇒ zero notifications** (assert no emit when `CAMOU_OBSERVE` unset).
- **Patch rehearsal:** every modified patch passes
  `rc=0 rejects=0 skipped=0 wrongpath=0 fuzz=0 max|offset|=0`
  (`scripts/rehearse-patch.sh`).
- **Compile:** CI `Build` green.
- **Runtime:** with `CAMOU_OBSERVE=1`, visit a canvas-fingerprinting tester +
  facebook.com → access rows and net rows appear in the panel; with env unset →
  panel stays empty.
- **ponytail self-check:** feed synthetic access+net events into the Collector,
  assert per-origin grouping + fb/ig/threads highlight.

## Risks

1. **Thread-safety** — config getters can run off-main-thread. Notify must
   main-thread-guard.
2. **Always-on home** — lives in a `browser-init`-style startup patch active
   during manual browsing, not juggler.
3. **Emit volume** — hot getters (e.g. webgl `getParameter`) can fire often;
   Collector dedups/counts, and env-gating keeps the default path cost-free.

## Scope defaults (confirmed)

Env-gated off; all surfaces observed (Phase 1 chokepoint); all sites observed,
panel highlights fb/ig/threads; Phase 2 adds per-surface real-vs-spoofed
precision + network response bodies.
