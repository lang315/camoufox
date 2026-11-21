package camoufox

import (
	"context"
	"reflect"
	"strings"
	"testing"
)

// samePage is another page of p's browser, on the same fake session.
func samePage(p *Page) *Page {
	return &Page{
		bc:             p.bc,
		session:        p.session,
		mainFrameID:    p.mainFrameID,
		mainContextID:  p.mainContextID,
		contextReadyCh: make(chan struct{}),
		closed:         make(chan struct{}),
		frames:         make(map[string]*Frame),
	}
}

// One stream serves the browser: a second page of it draws on from where the
// first left off, so two pages never replay the same draws. (A second launch
// with the seed replays; TestHumanizeSeedReplays.)
func TestHumanizeTwoPagesOneBrowserDrawDifferently(t *testing.T) {
	ctx := ctxT(t)
	a, fb := newHumanizePage(t, &Humanize{Seed: u64(7)}, "windows")
	b := samePage(a)
	virtualClock(a)
	virtualClock(b)
	if err := scenario(ctx, a); err != nil {
		t.Fatal(err)
	}
	first := fb.recorded()
	if err := scenario(ctx, b); err != nil {
		t.Fatal(err)
	}
	second := fb.recorded()[len(first):]
	if len(first) < 100 || reflect.DeepEqual(first, second) {
		t.Fatalf("page 2 made the calls of page 1 (%d and %d calls)", len(first), len(second))
	}
}

// Without a seed each launch draws its own.
func TestHumanizeUnseededLaunchesDiffer(t *testing.T) {
	run := func() []fakeCall {
		p, fb := newHumanizePage(t, &Humanize{}, "linux")
		virtualClock(p)
		if err := p.Mouse().Move(ctxT(t), 600, 400); err != nil {
			t.Fatal(err)
		}
		return fb.recorded()
	}
	if reflect.DeepEqual(run(), run()) {
		t.Fatal("two unseeded launches made the same calls")
	}
}

// cancelWhen runs the page on a virtual clock whose sleep cancels the context,
// and fails, the first time cond holds.
func cancelWhen(p *Page, cancel context.CancelFunc, cond func(*pageHost) bool) {
	host := p.humanizer().host
	now := 0.0
	host.nowFn = func() float64 { return now }
	host.sleepFn = func(ctx context.Context, ms float64) error {
		now += ms
		if cond(host) {
			cancel()
			return ctx.Err()
		}
		return nil
	}
}

// A cancelled Press or click lets go of what it pressed.
func TestHumanizeReleasesOnCancellation(t *testing.T) {
	t.Run("modifier of a chord", func(t *testing.T) {
		p, fb := newHumanizePage(t, &Humanize{Seed: u64(2)}, "linux")
		ctx, cancel := context.WithCancel(ctxT(t))
		cancelWhen(p, cancel, func(h *pageHost) bool { return len(h.held) > 0 })
		if err := p.Keyboard().Press(ctx, "Control+a"); err == nil {
			t.Fatal("a cancelled Press succeeded")
		}
		var control []string
		for _, c := range fb.inputs() {
			if c.Method == "Page.dispatchKeyEvent" && c.Params["key"] == "Control" {
				control = append(control, c.Params["type"].(string))
			}
		}
		if !reflect.DeepEqual(control, []string{"keydown", "keyup"}) {
			t.Fatalf("Control events %v, want the keydown and the keyup that lets it go", control)
		}
	})
	t.Run("button held during the hold", func(t *testing.T) {
		p, fb := newHumanizePage(t, &Humanize{Seed: u64(2)}, "linux")
		ctx, cancel := context.WithCancel(ctxT(t))
		hum := p.humanizer()
		cancelWhen(p, cancel, func(h *pageHost) bool { return h.buttons != 0 })
		if err := p.Mouse().Click(ctx, 50, 50); err == nil {
			t.Fatal("a cancelled click succeeded")
		}
		var last fakeCall
		for _, c := range fb.inputs() {
			if c.Method == "Page.dispatchMouseEvent" {
				last = c
			}
		}
		if last.Params["type"] != "mouseup" || last.Params["buttons"] != 0.0 {
			t.Fatalf("the last mouse event was %v, want the mouseup that releases the button", last.Params)
		}
		if hum.host.buttons != 0 {
			t.Fatal("the host still thinks the button is down")
		}
	})
}

// A typing run cancelled with Shift held lets Shift go.
func TestHumanizeTypeReleasesShiftOnCancellation(t *testing.T) {
	p, fb := newHumanizePage(t, &Humanize{Seed: u64(3)}, "linux")
	ctx, cancel := context.WithCancel(ctxT(t))
	cancelWhen(p, cancel, func(h *pageHost) bool {
		for _, k := range h.held {
			if k == "Shift" {
				return true
			}
		}
		return false
	})
	if err := p.Keyboard().Type(ctx, "HELLO"); err == nil {
		t.Fatal("a cancelled Type succeeded")
	}
	var down, up int
	for _, c := range fb.inputs() {
		if c.Method == "Page.dispatchKeyEvent" && c.Params["key"] == "Shift" {
			if c.Params["type"] == "keydown" {
				down++
			} else {
				up++
			}
		}
	}
	if down == 0 || down != up {
		t.Fatalf("Shift went down %d times and up %d", down, up)
	}
}

// A page that answers a page function with no value, or a viewport that is not
// two numbers, is an error, not "the press lands" or a 0x0 viewport.
func TestHumanizeBadPageReadsFail(t *testing.T) {
	ctx := ctxT(t)
	t.Run("no hit test value", func(t *testing.T) {
		p, fb := newHumanizePage(t, &Humanize{Seed: u64(1)}, "linux")
		virtualClock(p)
		fb.override = func(method string, params map[string]any) (string, bool) {
			if args, _ := params["args"].([]any); len(args) == 2 {
				if arg, _ := args[1].(map[string]any)["value"].(map[string]any); arg["pressing"] != nil {
					return `{"result":{}}`, true
				}
			}
			return "", false
		}
		err := p.Click(ctx, "#a")
		if err == nil || !strings.Contains(err.Error(), "no value") {
			t.Fatalf("Click error = %v, want the page function's missing value", err)
		}
		for _, c := range fb.inputs() {
			if c.Params["type"] == "mousedown" {
				t.Fatal("the press went out without a hit test answer")
			}
		}
	})
	t.Run("bad viewport", func(t *testing.T) {
		for _, bad := range []string{`["a",2]`, `[1]`, `"x"`} {
			p, fb := newHumanizePage(t, &Humanize{Seed: u64(1)}, "linux")
			virtualClock(p)
			fb.override = func(method string, params map[string]any) (string, bool) {
				if expr, _ := params["expression"].(string); strings.Contains(expr, "innerWidth") {
					return `{"result":{"value":` + bad + `}}`, true
				}
				return "", false
			}
			if err := p.Mouse().Move(ctx, 10, 10); err == nil || !strings.Contains(err.Error(), "viewport") {
				t.Errorf("viewport %s: Move error = %v", bad, err)
			}
		}
	})
}

// Page.MouseClick is a person's click on a myuri mouse: a path, a hold.
func TestHumanizePageMouseClick(t *testing.T) {
	ctx := ctxT(t)
	p, fb := newHumanizePage(t, &Humanize{Seed: u64(4)}, "macos")
	virtualClock(p)
	if err := p.MouseClick(ctx, 200, 300); err != nil {
		t.Fatal(err)
	}
	var moves, downs int
	for _, c := range fb.inputs() {
		switch c.Params["type"] {
		case "mousemove":
			moves++
		case "mousedown":
			downs++
		}
	}
	if moves < 5 || downs != 1 {
		t.Fatalf("%d moves and %d presses; a humanized click is a path and one press", moves, downs)
	}
}

// A raw call that moves the pointer tells the actions, so the next path and
// the next wheel start where the pointer is.
func TestHumanizeRawMovesAreTracked(t *testing.T) {
	ctx := ctxT(t)
	p, _ := newHumanizePage(t, &Humanize{Mouse: &Engine{Name: "raw"}}, "linux")
	virtualClock(p)
	host := p.humanizer().host
	at := func() [2]float64 { return [2]float64{host.x, host.y} }
	if err := p.MouseClick(ctx, 200, 300); err != nil || at() != [2]float64{200, 300} {
		t.Fatalf("after a raw MouseClick the host is at %v (err %v)", at(), err)
	}
	if err := p.Mouse().Move(ctx, 11, 12); err != nil || at() != [2]float64{11, 12} {
		t.Fatalf("after a raw Move the host is at %v (err %v)", at(), err)
	}
	el := &ElementHandle{page: p, objectID: "o1", ctxID: "x1", frameID: "f1"}
	if err := el.Hover(ctx); err != nil || at() != [2]float64{125, 110} {
		t.Fatalf("after a raw Hover the host is at %v (err %v)", at(), err)
	}
	if err := p.Mouse().Down(ctx, 5, 6); err != nil || at() != [2]float64{5, 6} {
		t.Fatalf("after a raw Down the host is at %v (err %v)", at(), err)
	}
}

// With scroll myuri and mouse raw, the click does not scroll again with an
// instant programmatic scroll after the wheel's.
func TestHumanizeRawClickAfterMyuriScroll(t *testing.T) {
	ctx := ctxT(t)
	p, fb := newHumanizePage(t, &Humanize{Mouse: &Engine{Name: "raw"}, Keyboard: &Engine{Name: "raw"}, Seed: u64(9)}, "linux")
	virtualClock(p)
	el := &ElementHandle{page: p, objectID: "o1", ctxID: "x1", frameID: "f1"}
	if err := el.Click(ctx); err != nil {
		t.Fatal(err)
	}
	var plans, centre int
	for _, c := range fb.recorded() {
		decl, _ := c.Params["functionDeclaration"].(string)
		if strings.Contains(decl, "scrollIntoView(") {
			t.Fatalf("an instant scroll followed the humanized one: %s", decl)
		}
		if strings.Contains(decl, "finishPosition") {
			plans++
		}
		if strings.Contains(decl, "getBoundingClientRect") && !strings.Contains(decl, "finishPosition") {
			centre++
		}
	}
	if plans == 0 || centre != 1 {
		t.Fatalf("%d scroll plans and %d centre reads", plans, centre)
	}
	// The control: with the scroll raw too the instant scroll is goapi's own.
	q, fq := newHumanizePage(t, &Humanize{Mouse: &Engine{Name: "raw"}, Scroll: &Engine{Name: "raw"}}, "linux")
	if err := (&ElementHandle{page: q, objectID: "o1", ctxID: "x1", frameID: "f1"}).Click(ctx); err != nil {
		t.Fatal(err)
	}
	found := false
	for _, c := range fq.recorded() {
		decl, _ := c.Params["functionDeclaration"].(string)
		found = found || strings.Contains(decl, "scrollIntoView(")
	}
	if !found {
		t.Fatal("control: a raw click lost its scroll")
	}
}

// The keyboard's speed is the engine's WPM.
func TestHumanizeKeyboardWPM(t *testing.T) {
	elapsed := func(wpm float64) float64 {
		p, _ := newHumanizePage(t, &Humanize{Seed: u64(6), Keyboard: &Engine{Name: "myuri", WPM: wpm}}, "linux")
		hum := p.humanizer()
		now := 0.0
		hum.host.nowFn = func() float64 { return now }
		hum.host.sleepFn = func(_ context.Context, ms float64) error { now += ms; return nil }
		if err := p.Keyboard().Type(ctxT(t), "the quick brown fox"); err != nil {
			t.Fatal(err)
		}
		return now
	}
	if slow, fast := elapsed(25), elapsed(200); slow < 2*fast {
		t.Fatalf("25 wpm took %.0f ms and 200 wpm %.0f ms", slow, fast)
	}
}
