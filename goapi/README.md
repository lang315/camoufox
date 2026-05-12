# camoufox/goapi — Native Go client for Camoufox

Pure-Go launcher and Juggler-protocol driver for the [Camoufox](https://github.com/daijro/camoufox)
patched Firefox build. No Python, no Node, no `playwright-go` dependency.

## Status

**v0.1 — smoke-tested end-to-end** against Camoufox 150.0.2-beta.25 on
macOS arm64. v0.1 adds the WebRTC + canvas patch-companion options
(`WithCanvasNoise`, `WithWebRTCLocalIP`, default mDNS-obfuscation
disable). The C++ patches that consume these options live in
`patches/canvas-spoofing.patch` and `patches/webrtc-ip-spoofing2.patch`
and require a Firefox source rebuild via `make dir && make build`.

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
- `pkg/config` — full `CAMOU_CONFIG` schema (mirrors `settings/properties.json`) and env-var chunking
- `pkg/proxy` — proxy struct + IP/timezone resolution via `ip-api.com`
- `pkg/fingerprint` — minimal Firefox fingerprint sampler (presets + font/voice subset)
- `camoufox` — top-level public API: `Launch`, `Browser`, `BrowserContext`, `Page`

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
- `additions/juggler/pipe/nsRemoteDebuggingPipe.cpp` — pipe framing (`\0`-delimited)
- `additions/juggler/protocol/Dispatcher.js` — message envelope
- `additions/juggler/protocol/Protocol.js` — domain method/event schemas
- `additions/juggler/components/Juggler.js` — `--juggler-pipe` flag
- `settings/properties.json` — CAMOU_CONFIG schema
- `pythonlib/camoufox/utils.py:get_env_vars` — chunking limits
