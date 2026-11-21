package camoufox

import (
	"context"
	"encoding/json"
	"fmt"
	"math/rand/v2"
	"sync"
	"time"

	"github.com/lang315/camoufox/goapi/pkg/juggler"
	"github.com/lang315/camoufox/goapi/pkg/myuri"
)

// The browser does not humanize input: each input call is one native event.
// Humanizing is the driver's job, as in the Python and TypeScript launchers
// (docs/humanize.md). A channel set to "myuri" is planned by pkg/myuri, the Go
// port of myuri's smart actions, and its events are sent through this file's
// host; a "raw" channel, and every channel without a Humanize, is goapi's own
// dispatch, unchanged.

// Engine names who plans a channel's input.
type Engine struct {
	// Name is "myuri" (paths, clicks, typing and wheel turns as people make
	// them on the identity's OS, and the decisions around a click: scroll into
	// view, the point, whether it lands) or "raw" (goapi's own calls).
	Name string
}

const (
	engineMyuri = "myuri"
	engineRaw   = "raw"
)

// Humanize chooses the engine of each input channel. A nil channel is myuri, so
// the zero Humanize is myuri on every channel; a nil *Humanize (WithHumanize
// not used) is raw on every channel.
//
//	Mouse     Mouse.Move, Mouse.Click, Mouse.DblClick; Page.Click; ElementHandle.Click and Hover
//	Keyboard  Keyboard.Type and Press; Page.Type; ElementHandle.Type
//	Scroll    Mouse.Wheel; ElementHandle.ScrollIntoViewIfNeeded, and the scroll
//	          into view before a pointer action or typing
//
// Page.ScrollTo, ScrollBy and ScrollToBottom, Mouse.Down and Up, Keyboard.Down
// and Up, tap, and drag are always goapi's own.
type Humanize struct {
	Mouse, Keyboard, Scroll *Engine
	// Seed seeds the stream every draw of a page comes from, in [0, 2^32): two
	// pages given one seed make the same calls. Nil draws a fresh seed per page.
	Seed *uint64
}

// WithHumanize sets which input channels the driver humanizes. See Humanize.
func WithHumanize(h *Humanize) Option { return func(c *launchConfig) { c.humanize = h } }

// humanizeSetup is a validated Humanize: which channels myuri drives, and the
// OS of the identity whose people it models.
type humanizeSetup struct {
	mouse, keyboard, scroll bool
	seed                    *uint64
	os                      string
}

// newHumanizeSetup validates h. It returns nil when no channel is myuri: such a
// browser sends exactly what an unhumanized one does.
func newHumanizeSetup(h *Humanize) (*humanizeSetup, error) {
	if h == nil {
		return nil, nil
	}
	s := &humanizeSetup{seed: h.Seed}
	for _, ch := range []struct {
		name   string
		engine *Engine
		drives *bool
	}{{"Mouse", h.Mouse, &s.mouse}, {"Keyboard", h.Keyboard, &s.keyboard}, {"Scroll", h.Scroll, &s.scroll}} {
		switch {
		case ch.engine == nil || ch.engine.Name == engineMyuri:
			*ch.drives = true
		case ch.engine.Name == engineRaw:
		default:
			return nil, fmt.Errorf("camoufox: Humanize.%s: unknown engine %q; use %q or %q", ch.name, ch.engine.Name, engineMyuri, engineRaw)
		}
	}
	if h.Seed != nil && *h.Seed >= 1<<32 {
		return nil, fmt.Errorf("camoufox: Humanize.Seed %d is not in [0, 2^32)", *h.Seed)
	}
	if !s.mouse && !s.keyboard && !s.scroll {
		return nil, nil
	}
	return s, nil
}

// useOS sets the identity's OS, which picks myuri's model of how its people type
// and turn a wheel.
func (s *humanizeSetup) useOS(os string) error {
	switch os {
	case "macos", "windows", "linux":
		s.os = os
		return nil
	}
	return fmt.Errorf("camoufox: Humanize: myuri has no model for the OS %q; use WithOS with macos, windows or linux", os)
}

// humanizeActionTimeoutMS is how long a click keeps trying after a miss, as
// Playwright's default action timeout does.
const humanizeActionTimeoutMS = 30000

// humanizer is myuri's actions on one page.
type humanizer struct {
	*humanizeSetup
	host *pageHost

	mu      sync.Mutex // myuri.Actions is not safe for concurrent use
	actions *myuri.Actions
}

// humanizer is the page's myuri actions, or nil when no channel is myuri.
func (p *Page) humanizer() *humanizer {
	if p.bc == nil || p.bc.b == nil || p.bc.b.humanize == nil {
		return nil
	}
	p.humOnce.Do(func() {
		s := p.bc.b.humanize
		// Each page's stream starts at the seed; without one, at its own random seed.
		seed := uint64(rand.Uint32())
		if s.seed != nil {
			seed = *s.seed
		}
		h := &humanizer{humanizeSetup: s}
		h.host = &pageHost{p: p, own: &Keyboard{page: p, modifiers: map[string]bool{}, pressed: map[string]bool{}}, start: time.Now()}
		h.host.kb = h.host.own
		opts := myuri.Options{OS: s.os, Seed: seed, RawMove: !s.mouse}
		if !s.scroll {
			// A raw scroll channel scrolls as goapi does; the wheel is for myuri's.
			opts.IntoView = func(ctx context.Context, t myuri.Target) error {
				return t.(elementTarget).e.ScrollIntoViewIfNeeded(ctx)
			}
		}
		h.actions = myuri.New(h.host, opts)
		p.hum = h
	})
	return p.hum
}

// do runs f on the page's actions, one operation at a time. The events carry the
// modifiers of kb (the Keyboard the caller used) when it is not nil.
func (h *humanizer) do(kb *Keyboard, f func(*myuri.Actions) error) error {
	h.mu.Lock()
	defer h.mu.Unlock()
	if kb != nil {
		h.host.kb = kb
		defer func() { h.host.kb = h.host.own }()
	}
	return f(h.actions)
}

// noteMouse tells the actions where a raw call left the mouse, so its next path
// starts there.
func (p *Page) noteMouse(x, y float64) {
	if h := p.humanizer(); h != nil {
		h.mu.Lock()
		defer h.mu.Unlock()
		h.host.x, h.host.y = x, y
		h.actions.Moved(x, y)
	}
}

func (h *humanizer) move(ctx context.Context, x, y float64) error {
	return wrapHumanize("mouse Move", h.do(nil, func(a *myuri.Actions) error { return a.Move(ctx, x, y) }))
}

// clickAt moves to (x, y) and presses there, holding the modifiers (names of keys) for the press.
func (h *humanizer) clickAt(ctx context.Context, x, y float64, button string, count int, modifiers []string) error {
	return wrapHumanize("mouse Click", h.do(nil, func(a *myuri.Actions) error {
		err := a.Move(ctx, x, y)
		if err == nil {
			err = a.Press(ctx, button, count, modifiers)
		}
		if err != nil {
			// A press that fails or is cancelled midway leaves its modifiers down;
			// the next action would then run with Shift or Control held.
			h.releaseModifiers(ctx, modifiers)
		}
		return err
	}))
}

func (h *humanizer) releaseModifiers(ctx context.Context, modifiers []string) {
	ctx, cancel := context.WithTimeout(context.WithoutCancel(ctx), 5*time.Second)
	defer cancel()
	for i := len(modifiers) - 1; i >= 0; i-- {
		if h.host.kb.modifiers[modifiers[i]] {
			_ = h.host.kb.Up(ctx, modifiers[i])
		}
	}
}

// wheel turns the wheel at (x, y), where the caller names it.
func (h *humanizer) wheel(ctx context.Context, x, y, dx, dy float64) error {
	return wrapHumanize("mouse Wheel", h.do(nil, func(a *myuri.Actions) error {
		h.host.wheelAt = &myuri.Point{X: x, Y: y}
		defer func() { h.host.wheelAt = nil }()
		return a.Wheel(ctx, dx, dy)
	}))
}

func (h *humanizer) typeText(ctx context.Context, kb *Keyboard, text string) error {
	return wrapHumanize("Type", h.do(kb, func(a *myuri.Actions) error { return a.Type(ctx, text, 0) }))
}

func (h *humanizer) pressKey(ctx context.Context, kb *Keyboard, key string) error {
	return wrapHumanize("Press", h.do(kb, func(a *myuri.Actions) error { return a.Key(ctx, key) }))
}

// pointAt scrolls e into view, moves onto it and presses, or only moves when hover is set.
func (h *humanizer) pointAt(ctx context.Context, e *ElementHandle, hover bool) error {
	op := "Click"
	if hover {
		op = "Hover"
	}
	return wrapHumanize(op, h.do(nil, func(a *myuri.Actions) error {
		return a.Click(ctx, elementTarget{e}, myuri.ClickOptions{Hover: hover, Timeout: humanizeActionTimeoutMS})
	}))
}

func (h *humanizer) intoView(ctx context.Context, e *ElementHandle) error {
	return wrapHumanize("ScrollIntoViewIfNeeded", h.do(nil, func(a *myuri.Actions) error { return a.IntoView(ctx, elementTarget{e}) }))
}

// withElement runs f on the first element matching selector, then releases the handle.
func (p *Page) withElement(ctx context.Context, op, selector string, f func(*ElementHandle, context.Context) error) error {
	e, err := p.QuerySelector(ctx, selector)
	if err != nil {
		return fmt.Errorf("camoufox: %s resolve %q: %w", op, selector, err)
	}
	if e == nil {
		return fmt.Errorf("camoufox: %s: selector %q not found", op, selector)
	}
	defer func() {
		dctx, cancel := context.WithTimeout(context.WithoutCancel(ctx), 5*time.Second)
		defer cancel()
		_ = e.Dispose(dctx)
	}()
	return f(e, ctx)
}

func wrapHumanize(op string, err error) error {
	if err == nil {
		return nil
	}
	return fmt.Errorf("camoufox: %s: %w", op, err)
}

// humanClick is Mouse.Click and DblClick when myuri drives the mouse.
func (m *Mouse) humanClick(ctx context.Context, h *humanizer, x, y float64, count int, opts []MouseClickOption) error {
	o := mouseClickOpts{}
	for _, fn := range opts {
		fn(&o)
	}
	button := [...]string{"left", "middle", "right"}
	if o.button < 0 || o.button >= len(button) {
		return fmt.Errorf("camoufox: mouse Click: unknown button %d", o.button)
	}
	var modifiers []string
	for _, mod := range [...]struct {
		bit  int
		name string
	}{{1, "Alt"}, {2, "Control"}, {4, "Shift"}, {8, "Meta"}} {
		if o.modifiers&mod.bit != 0 {
			modifiers = append(modifiers, mod.name)
		}
	}
	return h.clickAt(ctx, x, y, button[o.button], count, modifiers)
}

// pageHost is myuri's host on one page: every event is one Juggler input call,
// the one goapi's own Mouse and Keyboard send.
type pageHost struct {
	p   *Page
	own *Keyboard // the humanizer's own keyboard
	kb  *Keyboard // the keyboard whose modifiers the events carry: own, or the caller's during its call

	x, y    float64      // where the mouse is
	buttons int          // the buttons held, as Juggler's mask
	wheelAt *myuri.Point // where the wheel turns during a Mouse.Wheel; nil: at the mouse
	start   time.Time
	nowFn   func() float64 // the clock and its sleep, replaced in tests
	sleepFn func(ctx context.Context, ms float64) error
}

var mouseButtons = map[string]struct{ number, mask int }{"left": {0, 1}, "middle": {1, 4}, "right": {2, 2}}

func (h *pageHost) dispatch(ctx context.Context, typ string, button, buttons, clicks int) error {
	ev := juggler.PageDispatchMouseEventParams{Type: typ, Button: button, X: h.x, Y: h.y, Modifiers: h.kb.modifierMask(), Buttons: buttons}
	if clicks > 0 {
		ev.ClickCount = &clicks
	}
	if err := h.p.session.Call(ctx, "Page.dispatchMouseEvent", ev, nil); err != nil {
		return fmt.Errorf("camoufox: mouse %s: %w", typ, err)
	}
	return nil
}

func (h *pageHost) Move(ctx context.Context, x, y float64) error {
	h.x, h.y = x, y
	return h.dispatch(ctx, "mousemove", 0, h.buttons, 0)
}

func (h *pageHost) Click(ctx context.Context, button string, clickCount int, holdMS float64) error {
	if err := h.press(ctx, button, clickCount); err != nil {
		return err
	}
	if err := h.Sleep(ctx, holdMS); err != nil {
		return err
	}
	return h.release(ctx, button, clickCount)
}

func (h *pageHost) Down(ctx context.Context, button string) error { return h.press(ctx, button, 1) }
func (h *pageHost) Up(ctx context.Context, button string) error   { return h.release(ctx, button, 1) }

func (h *pageHost) press(ctx context.Context, button string, clicks int) error {
	b, ok := mouseButtons[button]
	if !ok {
		return fmt.Errorf("camoufox: unknown mouse button %q", button)
	}
	if err := h.dispatch(ctx, "mousedown", b.number, h.buttons|b.mask, clicks); err != nil {
		return err
	}
	h.buttons |= b.mask
	return nil
}

func (h *pageHost) release(ctx context.Context, button string, clicks int) error {
	b, ok := mouseButtons[button]
	if !ok {
		return fmt.Errorf("camoufox: unknown mouse button %q", button)
	}
	if err := h.dispatch(ctx, "mouseup", b.number, h.buttons&^b.mask, clicks); err != nil {
		return err
	}
	h.buttons &^= b.mask
	return nil
}

// Wheel sends the turn and waits for the browser's answer; myuri's JS host does
// not wait for the page. The turns still reach the page in order, only the next
// notch is planned a round trip later.
func (h *pageHost) Wheel(ctx context.Context, dx, dy float64) error {
	x, y := h.x, h.y
	if h.wheelAt != nil {
		x, y = h.wheelAt.X, h.wheelAt.Y
	}
	params := juggler.PageDispatchWheelEventParams{X: x, Y: y, DeltaX: dx, DeltaY: dy, Modifiers: h.kb.modifierMask()}
	if err := h.p.session.Call(ctx, "Page.dispatchWheelEvent", params, nil); err != nil {
		return fmt.Errorf("camoufox: mouse Wheel: %w", err)
	}
	return nil
}

func (h *pageHost) KeyDown(ctx context.Context, key string) error { return h.kb.Down(ctx, key) }
func (h *pageHost) KeyUp(ctx context.Context, key string) error   { return h.kb.Up(ctx, key) }
func (h *pageHost) InsertText(ctx context.Context, text string) error {
	return h.kb.insertText(ctx, text)
}

func (h *pageHost) Viewport(ctx context.Context) (float64, float64, error) {
	v, err := h.p.Evaluate(ctx, `[innerWidth, innerHeight]`)
	if err != nil {
		return 0, 0, err
	}
	size, _ := v.([]any)
	if len(size) != 2 {
		return 0, 0, fmt.Errorf("camoufox: viewport size is %v", v)
	}
	w, _ := size[0].(float64)
	ht, _ := size[1].(float64)
	return w, ht, nil
}

func (h *pageHost) Now() float64 {
	if h.nowFn != nil {
		return h.nowFn()
	}
	return float64(time.Since(h.start)) / float64(time.Millisecond)
}

func (h *pageHost) Sleep(ctx context.Context, ms float64) error {
	if h.sleepFn != nil {
		return h.sleepFn(ctx, ms)
	}
	t := time.NewTimer(time.Duration(ms * float64(time.Millisecond)))
	defer t.Stop()
	select {
	case <-t.C:
		return nil
	case <-ctx.Done():
		return ctx.Err()
	}
}

// modifierMask is the held modifier keys as Juggler's modifiers field.
func (k *Keyboard) modifierMask() int {
	mask := 0
	for key, bit := range map[string]int{"Alt": 1, "Control": 2, "Shift": 4, "Meta": 8} {
		if k.modifiers[key] {
			mask |= bit
		}
	}
	return mask
}

// elementTarget is an element of the page's main frame as myuri's Target: the
// page functions run on it, in the isolated world its handle lives in.
type elementTarget struct{ e *ElementHandle }

// Offset is (0, 0): a handle is an element of the main document (EvaluateElement
// refuses other documents), whose viewport is the page's.
func (elementTarget) Offset(context.Context) (float64, float64, bool, error) { return 0, 0, true, nil }

func (t elementTarget) Plan(ctx context.Context, args myuri.PlanArgs) (*myuri.ScrollPlan, error) {
	raw, err := t.e.run(ctx, myuri.ScrollPlanJS, args)
	if err != nil || len(raw) == 0 {
		return nil, err
	}
	var plan *myuri.ScrollPlan
	if err := json.Unmarshal(raw, &plan); err != nil {
		return nil, fmt.Errorf("camoufox: decode scroll plan: %w", err)
	}
	return plan, nil
}

func (t elementTarget) HitTest(ctx context.Context, x, y float64, pressing bool) (string, error) {
	raw, err := t.e.run(ctx, myuri.HitTestJS, struct {
		X        float64 `json:"x"`
		Y        float64 `json:"y"`
		Pressing bool    `json:"pressing"`
	}{x, y, pressing})
	if err != nil || len(raw) == 0 {
		return "", err
	}
	var reason *string
	if err := json.Unmarshal(raw, &reason); err != nil {
		return "", fmt.Errorf("camoufox: decode hit test: %w", err)
	}
	if reason == nil {
		return "", nil
	}
	return *reason, nil
}

// run calls the page function fn, an arrow function (el, arg) => ..., on the element.
func (e *ElementHandle) run(ctx context.Context, fn string, arg any) (json.RawMessage, error) {
	argJSON, err := json.Marshal(arg)
	if err != nil {
		return nil, err
	}
	res, err := e.page.callFunction(ctx, e.ctxID, "function(el, arg) { return ("+fn+")(el, arg); }",
		[]juggler.CallFunctionArgument{{ObjectID: e.objectID}, {Value: argJSON}}, true)
	if err != nil || res.Result == nil {
		return nil, err
	}
	return res.Result.Value, nil
}
