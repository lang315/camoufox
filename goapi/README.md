# camoufox/goapi — Native Go client for Camoufox

Pure-Go launcher and Juggler-protocol driver for the [Camoufox](https://github.com/daijro/camoufox)
patched Firefox build. No Python, no Node, no `playwright-go` dependency.

## Status

**v0.1 — smoke-tested end-to-end** against Camoufox 150.0.2-beta.25 on
macOS arm64. v0.1 adds the WebRTC + canvas patch-companion options
(`WithCanvasNoise`, `WithWebRTCLocalIP`). The C++ patches that consume these
options live in `browser/patches/canvas-spoofing.patch` and `browser/patches/webrtc-ip-spoofing2.patch`
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
- `pkg/myuri` — Go port of myuri's mouse, wheel and typing planners, run by `WithHumanize`
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

## Element handles from an expression

`Page.QuerySelector` is not the only way to get an `ElementHandle`:

```go
// Any expression that yields a node, run in the same isolated world as Evaluate.
form, err := p.EvaluateElement(ctx, `document.querySelector("input").form`)
if err != nil || form == nil { /* nil, nil: the expression gave null or undefined */ }

// A JS function expression, called with the element as its first argument.
id, err := form.Evaluate(ctx, `el => el.id`)

// element.querySelector; nil, nil when nothing inside the element matches.
field, err := form.QuerySelector(ctx, "[name=email]")
```

`EvaluateElement` fails loudly instead of returning a handle that is not an element: a
number, string or plain object is an error, an `mw:` expression is an error (a main-world
value cannot become a handle), a node that is not an element (a text node, a comment, the
document) is an error, and so is an element of an iframe's document, because a handle
carries the main frame and `Click` would aim its frame-relative coordinates at the main
page. `ElementHandle.Evaluate` decodes the value as `Page.Evaluate` does.

## Humanized input

The browser does not humanize input: each input call is one native event, and no `humanize*`
config key reaches it. goapi humanizes in the driver, as the Python and TypeScript launchers do
([`docs/humanize.md`](../docs/humanize.md)), with `pkg/myuri`, a Go port of
[myuri](https://github.com/JWriter20/Myuri)'s smart actions: paths, clicks, typing and wheel turns as
the people it was fitted to make them on the identity's OS, and the decisions around a click (scroll
into view, the point, whether the press would land on the element, trying again when it does not).

```go
// myuri on every channel
b, err := camoufox.Launch(ctx, camoufox.WithExecutablePath(bin), camoufox.WithHumanize(&camoufox.Humanize{}))

// per channel, replayable: the same seed makes a launch send the same calls
seed := uint64(1234)
camoufox.WithHumanize(&camoufox.Humanize{
    Keyboard: &camoufox.Engine{Name: "myuri", WPM: 70},
    Scroll:   &camoufox.Engine{Name: "raw"}, // goapi's own calls; "myuri" is the default
    Seed:     &seed,
})
```

Without `WithHumanize` every channel is raw: goapi sends what it always has. An engine name other
than `"myuri"` (or its alias `"cursory"`) or `"raw"`, a `WPM` anywhere but on a myuri keyboard, or a
seed of 2^32 or more, makes `Launch` return an error. The OS myuri
models is the identity's (`WithOS`, or the config's user agent).

| Channel | Routed when it is myuri |
|---|---|
| `Mouse` | `Mouse.Move`, `Mouse.Click`, `Mouse.DblClick`, `Page.MouseClick`, `Page.Click`, `ElementHandle.Click` and `Hover` |
| `Keyboard` | `Keyboard.Type` and `Press`, `Page.Type`, `ElementHandle.Type` |
| `Scroll` | `Mouse.Wheel`, `ElementHandle.ScrollIntoViewIfNeeded`, and the scroll into view before a click, hover or `Type` |

`Keyboard.Type` ignores `WithDelay` and `Keyboard.Press` takes chords such as `Control+a` when
myuri types: the pace is myuri's. goapi has no Locator, so the `ElementHandle` methods are where the
Python and TypeScript launchers humanize Locator's. `Mouse.Wheel` turns at the `(x, y)` it is given:
a myuri mouse is moved there first, a raw one is not; it returns when its last notch has been sent. A click
that misses its element is tried again for 30 s, then returns an error wrapping the reason.
`ScrollTo`, `ScrollBy`, `ScrollToBottom`, `Mouse.Down` and `Up`, `Keyboard.Down` and `Up`, touch and
drag are always goapi's own. One stream, from the seed or a random one per launch, serves every page
of the browser, so two pages never replay the same draws; each page has its own cursor, and runs one
humanized call at a time. A humanized call that fails or is cancelled midway releases the keys and
buttons it pressed.

The port's planners are pinned to myuri 4.0.0 by golden traces recorded from the JS library;
the whole-scenario `browser/tests/humanize/sequence.json` that the Python and TypeScript launchers
share is not pinned for Go, which has no caller-replaced parts, `fill`, `position=` or `trial=`.

## Licence

Camoufox is MPL-2.0, but `pkg/myuri` is a port of [myuri](https://github.com/JWriter20/Myuri) and
[cursory-js](https://github.com/JWriter20/cursory-js) and stays LGPL-3.0-or-later. goapi links it into every
binary that imports goapi. Under LGPL section 4 you keep its notices, ship the licence texts
([`LICENSE`](pkg/myuri/LICENSE), [`COPYING`](pkg/myuri/COPYING), [`NOTICE`](pkg/myuri/NOTICE)) with your
binary, and let a user relink your program against a modified `pkg/myuri`, which this module's source gives
them. The rest of goapi is unaffected.

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

`BrowserContext.ExposeBinding(ctx, name, script, fn)` does the same for every page of a
context: the pages open now, pages `NewPage` opens later and popups, whose first document
runs `script` before `OnPage` reports the page. `fn` is `func(p *Page, payload string)`, so
it can tell a popup from its opener. A name is bound once per context, and a page of the
context cannot bind a name the context holds, nor the context a name an open page holds.

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
