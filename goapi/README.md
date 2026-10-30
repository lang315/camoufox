# camoufox/goapi — Native Go client for Camoufox

Pure-Go launcher and Juggler-protocol driver for the [Camoufox](https://github.com/daijro/camoufox)
patched Firefox build. No Python, no Node, no `playwright-go` dependency.

## Status

**v0.1 — smoke-tested end-to-end** against Camoufox 150.0.2-beta.25 on
macOS arm64. v0.1 adds the WebRTC + canvas patch-companion options
(`WithCanvasNoise`, `WithWebRTCLocalIP`, default mDNS-obfuscation
disable). The C++ patches that consume these options live in
`browser/patches/canvas-spoofing.patch` and `browser/patches/webrtc-ip-spoofing2.patch`
and require a Firefox source rebuild via `make -C browser dir && make -C browser build`.

The bare `WithExecutablePath(...)` flow still works against the stock
Camoufox release; the new keys are silently ignored by a binary that
doesn't have the matching patches applied.

Also: 150.0.2-beta.25 release tested. The `example/basic` flow (launch → newPage → goto
example.com → evaluate `navigator.userAgent` → screenshot a 1280×720
PNG) round-trips with `WithOS("windows")` returning a Windows UA, which
confirms FD 3/4 pipe wiring, `--juggler-pipe` framing, CAMOU_CONFIG
chunked env-var injection, and the Browser/Page/Runtime RPC paths.

Still v0: only a single platform proven. No Windows pipe transport.
Linux untested. WebGL/Network domains shipped but not exercised.

The package implements the launch path and Juggler RPC core:

- `pkg/juggler` — pipe transport (FDs 3/4, `\0`-delimited JSON), dispatcher, sessions
- `pkg/config` — full `CAMOU_CONFIG` schema (mirrors `browser/settings/properties.json`) and env-var chunking
- `pkg/proxy` — proxy struct + IP/timezone resolution via `ip-api.com`
- `pkg/fingerprint` — minimal Firefox fingerprint sampler (presets + font/voice subset)
- `camoufox` — top-level public API: `Launch`, `Browser`, `BrowserContext`, `Page`

On Linux, `Launch` points the browser at a runtime fontconfig (`FONTCONFIG_FILE`) built from
`fontconfig/<os>/fonts.conf` beside the binary, so it renders only the bundled fonts of the
identity's OS rather than the host's. The file is written to `$XDG_CACHE_HOME/camoufox/fontconfig/`
(`~/.cache` by default). A `FONTCONFIG_FILE` passed through `WithEnv` takes precedence. A bundle
without `fonts.conf` fails the launch. `pkg/fingerprint/data/fonts.json` must match
`python/src/camoufox/fonts.json`; a test enforces it.

A page reads the canvas and WebGL pixels the host renders, whatever the identity claims. Every
goapi identity names a preset's GPU, so by default `Launch` makes canvas readback return
`privacy.resistFingerprinting`'s random placeholder and sends no canvas noise seed, as the Python
and TypeScript launchers do for an identity that is not the host's own OS and GPU (#196).
`WithCanvasPlaceholder(false)` keeps stock canvas behaviour with the fork's seeded noise. WebGPU is
enabled where Firefox ships it for the claimed device, with no adapter.

## Features

- **Phase 1** — dialog, navigation (Goto/NavigateGuarded), console/pageerror/crash events, keyboard, mouse (move/click/wheel), permissions, hover, scroll-into-view, bounding-box, element screenshot, wait state machine
- **Phase 2** — file upload, download, file-chooser intercept, accessibility tree, touch events, frame URL/Name
- **Phase 3** — XPath query, shadow DOM pierce, mutation observer, resilient selector (CSS/XPath/Text/TestID), navigation guard with bot-wall detection, React fiber props
- **Phase 4** — scroll (ScrollTo/ScrollBy/ScrollToBottom with jitter), dismiss overlays, fill form (label/name/placeholder/aria-label matching), extract text, page summary (title/headings/main text), localStorage/sessionStorage, StorageState snapshot, page state snapshot

## Quickstart

```go
import (
    "context"
    "github.com/lang315/camoufox/goapi"
)

func main() {
    ctx := context.Background()
    b, err := camoufox.Launch(ctx,
        camoufox.WithExecutablePath("/path/to/camoufox/firefox"),
        camoufox.WithOS("windows"),
        camoufox.WithHeadless(true),
    )
    if err != nil { panic(err) }
    defer b.Close()

    bc, _ := b.NewContext(ctx)
    p, _ := bc.NewPage(ctx)
    _, _ = p.Goto(ctx, "https://example.com")
    ua, _ := p.Evaluate(ctx, "navigator.userAgent")
    println(ua.(string))
}
```

## Pages a context opens

A `window.open` popup or a `target=_blank` link opens a page the caller never asked for. `BrowserContext.Pages` lists every open page of the context, `NewPage`'s included, and `OnPage` runs a function for each new one:

```go
popups := make(chan *camoufox.Page, 1)
cancel := bc.OnPage(func(p *camoufox.Page) { popups <- p })
defer cancel()

_ = p.Click(ctx, "a[target=_blank]")
popup := <-popups // still on about:blank; it navigates to the link afterwards
```

A page leaves `Pages` when the browser closes it. `OnPage` fires once the page's main execution context exists, so the function may `Evaluate`.

## Main-world evaluation

`Page.Evaluate` runs in an isolated world: it sees the DOM but not the page's own
JavaScript globals or the properties page scripts set on DOM nodes. Script running in
the page's world is visible to the page, so isolation is the default and main-world
evaluation is an opt-in, per call. Launch with `WithMainWorldEval(true)` and prefix the
expression with `mw:`, as with pythonlib's `main_world_eval`:

```go
b, err := camoufox.Launch(ctx,
    camoufox.WithExecutablePath("/path/to/camoufox/firefox"),
    camoufox.WithMainWorldEval(true),
)
// ...
v, err := p.Evaluate(ctx, "mw:typeof window.myPageGlobal")
```

Without the option an `mw:` expression fails with `Main world evaluation is disabled`.
Only values come back: a DOM node is returned as the string `"ref: <Node>"`.
An object reached twice comes back as the same value in both places; one that contains
itself fails with `camoufox: main-world result contains a cycle`.

## Calling back into Go from the page

`Page.ExposeBinding` installs `window[name]` in the same isolated world as `Evaluate` and
`WatchMutations`, then runs a script there on every document. The script calls
`window[name](payload)` to hand a string to a Go function; JSON-encode anything structured.

```go
cancel, err := p.ExposeBinding(ctx, "report", `
    document.addEventListener("step", function (e) { window.report(String(e.detail)); }, true);
`, func(payload string) { fmt.Println("page said:", payload) })
if err != nil { panic(err) }
defer cancel()
```

`fn` runs on the connection's read loop: it must return promptly and must not call the browser, so hand work to a goroutine (calls arrive in page order).

The binding is not visible to the page: page script and a `mw:` init script read
`typeof window.report` as `"undefined"`. A main-world script reaches it by dispatching
a `CustomEvent` on `document`, as above; that event is visible to the page, so it is a
trace the caller accepts. On a new document the binding and its script run before any
init script, so a `mw:` init script may dispatch at once. On the document current when
`ExposeBinding` is called, earlier events are not delivered. A name is bound once per
page, and `cancel` stops delivery only: Juggler cannot remove `window.report`.

`BrowserContext.SetBypassCSP(ctx, true)` turns off Content-Security-Policy enforcement for
the context's next navigations, so a page served with `connect-src 'none'` can still
reach a local server such as a devtools backend.

## Architecture

```
camoufox.Launch
  └─ build Config from options (pkg/config)
  └─ generate fingerprint (pkg/fingerprint)
  └─ resolve proxy geo if requested (pkg/proxy)
  └─ serialize Config → CAMOU_CONFIG_N env vars
  └─ exec(camoufox_bin --juggler-pipe ...) with ExtraFiles for FDs 3,4
  └─ pkg/juggler.Connection(stdoutPipe, stdinPipe)
       └─ Browser.enable → ready
```

## References

Wire protocol traced from:
- `browser/additions/juggler/pipe/nsRemoteDebuggingPipe.cpp` — pipe framing (`\0`-delimited)
- `browser/additions/juggler/protocol/Dispatcher.js` — message envelope
- `browser/additions/juggler/protocol/Protocol.js` — domain method/event schemas
- `browser/additions/juggler/components/Juggler.js` — `--juggler-pipe` flag
- `browser/settings/properties.json` — CAMOU_CONFIG schema
- `python/src/camoufox/utils.py:get_env_vars` — chunking limits
