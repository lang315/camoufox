package camoufox

import (
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"reflect"
	"sort"
	"strings"
	"sync"
	"testing"
	"time"

	"github.com/lang315/camoufox/goapi/pkg/juggler"
)

// fakeBrowser answers a page session's requests itself and records them, so a
// test sees exactly which Juggler calls an API call makes and a seed's replay
// can be compared call for call.
type fakeBrowser struct {
	in chan []byte

	mu    sync.Mutex
	buf   []byte
	calls []fakeCall
	// override answers a call with this result instead of the default, when it returns ok.
	override func(method string, params map[string]any) (string, bool)
	// fail maps a method, or "method/type" for an input event, to the error it answers with.
	fail map[string]string
}

type fakeCall struct {
	Method string
	Params map[string]any
}

// Write reassembles the NUL-framed requests and answers each one.
func (f *fakeBrowser) Write(p []byte) (int, error) {
	f.mu.Lock()
	defer f.mu.Unlock()
	f.buf = append(f.buf, p...)
	for {
		i := bytes.IndexByte(f.buf, 0)
		if i < 0 {
			return len(p), nil
		}
		msg := f.buf[:i]
		f.buf = f.buf[i+1:]
		var req struct {
			ID     uint64         `json:"id"`
			Method string         `json:"method"`
			Params map[string]any `json:"params"`
		}
		if json.Unmarshal(msg, &req) != nil {
			continue
		}
		f.calls = append(f.calls, fakeCall{req.Method, req.Params})
		f.in <- []byte(f.answer(req.ID, req.Method, req.Params) + "\x00")
	}
}

const fakePlan = `{"inView":true,"deltaY":0,"hoverX":125,"hoverY":110,"isPage":true,` +
	`"region":{"x":100,"y":100,"width":50,"height":20},"box":{"x":100,"y":100,"width":50,"height":20},"borders":[0,0]}`

func (f *fakeBrowser) answer(id uint64, method string, params map[string]any) string {
	if msg, ok := f.fail[method]; ok {
		return fmt.Sprintf(`{"id":%d,"sessionId":"s1","error":{"message":%q}}`, id, msg)
	}
	if typ, _ := params["type"].(string); typ != "" {
		if msg, ok := f.fail[method+"/"+typ]; ok {
			return fmt.Sprintf(`{"id":%d,"sessionId":"s1","error":{"message":%q}}`, id, msg)
		}
	}
	result := `{}`
	if f.override != nil {
		if r, ok := f.override(method, params); ok {
			return fmt.Sprintf(`{"id":%d,"sessionId":"s1","result":%s}`, id, r)
		}
	}
	switch method {
	case "Runtime.evaluate":
		expr, _ := params["expression"].(string)
		switch {
		case strings.Contains(expr, "innerWidth"):
			result = `{"result":{"value":[1280,720]}}`
		case strings.Contains(expr, "getBoundingClientRect"):
			result = `{"result":{"value":{"x":200,"y":300,"found":true}}}`
		}
	case "Page.getContentQuads":
		result = `{"quads":[{"p1":{"x":100,"y":100},"p2":{"x":150,"y":100},"p3":{"x":150,"y":120},"p4":{"x":100,"y":120}}]}`
	case "Runtime.callFunction":
		decl, _ := params["functionDeclaration"].(string)
		args, _ := params["args"].([]any)
		var arg map[string]any
		if len(args) == 2 {
			arg, _ = args[1].(map[string]any)["value"].(map[string]any)
		}
		switch {
		case arg["finishPosition"] != nil:
			result = `{"result":{"value":` + fakePlan + `}}`
		case arg["pressing"] != nil:
			result = `{"result":{"value":null}}`
		case strings.Contains(decl, "getBoundingClientRect"):
			result = `{"result":{"value":{"x":125,"y":110}}}`
		case strings.Contains(decl, "document.querySelector(sel)"):
			result = `{"result":{"type":"object","subtype":"node","objectId":"o1"}}`
		}
	}
	return fmt.Sprintf(`{"id":%d,"sessionId":"s1","result":%s}`, id, result)
}

func (f *fakeBrowser) recorded() []fakeCall {
	f.mu.Lock()
	defer f.mu.Unlock()
	return append([]fakeCall(nil), f.calls...)
}

// events is the recorded input calls, as "method/type x,y" strings, without the page reads.
func (f *fakeBrowser) inputs() []fakeCall {
	var out []fakeCall
	for _, c := range f.recorded() {
		if strings.HasPrefix(c.Method, "Page.dispatch") || c.Method == "Page.insertText" || c.Method == "Page.scrollIntoViewIfNeeded" {
			out = append(out, c)
		}
	}
	return out
}

type reader struct {
	buf bytes.Buffer
	in  chan []byte
}

func (r *reader) Read(p []byte) (int, error) {
	for r.buf.Len() == 0 {
		b, ok := <-r.in
		if !ok {
			return 0, fmt.Errorf("closed")
		}
		r.buf.Write(b)
	}
	return r.buf.Read(p)
}

// newHumanizePage is a page on a fake browser launched with h, as an identity of os.
func newHumanizePage(t *testing.T, h *Humanize, os string) (*Page, *fakeBrowser) {
	t.Helper()
	setup, err := newHumanizeSetup(h)
	if err != nil {
		t.Fatal(err)
	}
	if setup != nil {
		if err := setup.useOS(os); err != nil {
			t.Fatal(err)
		}
	}
	in := make(chan []byte, 4096)
	fb := &fakeBrowser{in: in}
	conn := juggler.NewConnection(juggler.NewPipe(&reader{in: in}, fb, nil))
	b := &Browser{conn: conn, root: conn.RootSession(), pages: map[string]*Page{}, humanize: setup}
	p := &Page{
		bc:             &BrowserContext{b: b},
		session:        conn.Session("s1"),
		mainFrameID:    "f1",
		mainContextID:  "x1",
		contextReadyCh: make(chan struct{}),
		closed:         make(chan struct{}),
		frames:         make(map[string]*Frame),
	}
	t.Cleanup(func() {
		close(in)
		conn.Close()
	})
	return p, fb
}

// virtualClock makes the page's humanizer sleep by advancing a clock, so a
// test takes no real time and a replay sees the same times.
func virtualClock(p *Page) {
	hum := p.humanizer()
	var now float64
	hum.host.nowFn = func() float64 { return now }
	hum.host.sleepFn = func(_ context.Context, ms float64) error { now += ms; return nil }
}

func ctxT(t *testing.T) context.Context {
	t.Helper()
	ctx, cancel := context.WithTimeout(context.Background(), 20*time.Second)
	t.Cleanup(cancel)
	return ctx
}

// scenario is a fixed sequence of API calls over every routed entry point.
func scenario(ctx context.Context, p *Page) error {
	if err := p.Mouse().Move(ctx, 300, 200); err != nil {
		return err
	}
	if err := p.Mouse().Wheel(ctx, 300, 200, 0, 120); err != nil {
		return err
	}
	if err := p.Keyboard().Type(ctx, "hi"); err != nil {
		return err
	}
	if err := p.Click(ctx, "#a"); err != nil {
		return err
	}
	el, err := p.QuerySelector(ctx, "#a")
	if err != nil || el == nil {
		return fmt.Errorf("query: %v", err)
	}
	if err := el.Hover(ctx); err != nil {
		return err
	}
	if err := el.Type(ctx, "ok"); err != nil {
		return err
	}
	if err := el.Click(ctx); err != nil {
		return err
	}
	return el.ScrollIntoViewIfNeeded(ctx)
}

// sig is an input call as "method k=v ..." with the keys sorted, so a test pins every parameter.
func sig(c fakeCall) string {
	keys := make([]string, 0, len(c.Params))
	for k := range c.Params {
		keys = append(keys, k)
	}
	sort.Strings(keys)
	out := c.Method
	for _, k := range keys {
		out += fmt.Sprintf(" %s=%v", k, c.Params[k])
	}
	return out
}

func mouseSig(typ string, x, y float64, buttons int, clickCount int) string {
	cc := ""
	if clickCount > 0 {
		cc = fmt.Sprintf(" clickCount=%d", clickCount)
	}
	return fmt.Sprintf("Page.dispatchMouseEvent button=0 buttons=%d%s modifiers=0 type=%s x=%v y=%v", buttons, cc, typ, x, y)
}

// A nil Humanize sends what goapi sent before the option existed: one Juggler
// call per input call, with these parameters. A browser whose channels are all
// raw is the same browser.
func TestHumanizeRawIsPlaywrightDispatch(t *testing.T) {
	ctx := ctxT(t)
	run := func(h *Humanize) []string {
		p, fb := newHumanizePage(t, h, "linux")
		if err := scenario(ctx, p); err != nil {
			t.Fatal(err)
		}
		var out []string
		for _, c := range fb.recorded() {
			switch c.Method {
			case "Runtime.callFunction", "Runtime.evaluate":
				out = append(out, c.Method+" "+fmt.Sprint(c.Params["functionDeclaration"], c.Params["expression"]))
			default:
				out = append(out, sig(c))
			}
		}
		return out
	}
	got := run(nil)
	var inputs []string
	for _, c := range got {
		if strings.HasPrefix(c, "Page.") {
			inputs = append(inputs, c)
		}
	}
	want := []string{
		mouseSig("mousemove", 300, 200, 0, 0), // Mouse.Move
		"Page.dispatchWheelEvent deltaX=0 deltaY=120 deltaZ=0 modifiers=0 x=300 y=200",
		"Page.insertText text=hi",                                                                                         // Keyboard.Type
		mouseSig("mousemove", 200, 300, 0, 0), mouseSig("mousedown", 200, 300, 1, 1), mouseSig("mouseup", 200, 300, 0, 1), // Page.Click
		"Page.getContentQuads frameId=f1 objectId=o1", // Hover
		mouseSig("mousemove", 125, 110, 0, 0),
		"Page.insertText text=ok",                                                                                         // Type
		mouseSig("mousemove", 125, 110, 0, 0), mouseSig("mousedown", 125, 110, 1, 1), mouseSig("mouseup", 125, 110, 0, 1), // Click
		"Page.scrollIntoViewIfNeeded frameId=f1 objectId=o1",
	}
	if !reflect.DeepEqual(inputs, want) {
		t.Fatalf("raw input calls:\n got %q\nwant %q", inputs, want)
	}
	raw := &Engine{Name: "raw"}
	if allRaw := run(&Humanize{Mouse: raw, Keyboard: raw, Scroll: raw}); !reflect.DeepEqual(got, allRaw) {
		t.Fatalf("an all-raw Humanize sent other calls than none:\n nil: %q\n raw: %q", got, allRaw)
	}
}

func TestHumanizeUnknownEngineFails(t *testing.T) {
	for name, h := range map[string]*Humanize{
		"unknown mouse engine":    {Mouse: &Engine{Name: "bezier"}},
		"wpm on the mouse":        {Mouse: &Engine{WPM: 50}},
		"wpm on a raw keyboard":   {Keyboard: &Engine{Name: "raw", WPM: 50}},
		"negative wpm":            {Keyboard: &Engine{WPM: -1}},
		"unknown keyboard engine": {Keyboard: &Engine{Name: "bezier"}},
		"unknown scroll engine":   {Scroll: &Engine{Name: "Myuri"}},
		"unnamed engine":          {Mouse: &Engine{}},
		"seed past 2^32":          {Seed: u64(1 << 32)},
	} {
		if _, err := newHumanizeSetup(h); err == nil {
			t.Errorf("%s: newHumanizeSetup accepted it", name)
		}
		// Launch fails before it looks for the browser.
		if _, err := Launch(context.Background(), WithExecutablePath("/no/such/camoufox"), WithHumanize(h)); err == nil || strings.Contains(err.Error(), "resolve executable") {
			t.Errorf("%s: Launch error = %v, want the humanize error", name, err)
		}
	}
	if _, err := newHumanizeSetup(&Humanize{Mouse: &Engine{Name: "cursory"}, Keyboard: &Engine{Name: "myuri", WPM: 70}}); err != nil {
		t.Errorf("cursory is another name for myuri, and a myuri keyboard has a speed: %v", err)
	}
	if _, err := newHumanizeSetup(&Humanize{}); err != nil {
		t.Errorf("the zero Humanize is myuri everywhere: %v", err)
	}
	if _, err := newHumanizeSetup(&Humanize{Seed: u64(1<<32 - 1)}); err != nil {
		t.Errorf("seed 2^32-1: %v", err)
	}
	if s := (&humanizeSetup{}); s.useOS("beos") == nil {
		t.Error("an OS myuri has no model for was accepted")
	}
}

func u64(v uint64) *uint64 { return &v }

// Two pages with the same seed make the same Juggler calls; another seed does not.
func TestHumanizeSeedReplays(t *testing.T) {
	ctx := ctxT(t)
	run := func(seed uint64) []fakeCall {
		p, fb := newHumanizePage(t, &Humanize{Seed: u64(seed)}, "windows")
		virtualClock(p)
		if err := scenario(ctx, p); err != nil {
			t.Fatal(err)
		}
		return fb.recorded()
	}
	a, b, other := run(7), run(7), run(8)
	if len(a) < 100 {
		t.Fatalf("a humanized scenario made only %d calls", len(a))
	}
	if !reflect.DeepEqual(a, b) {
		for i := range a {
			if i >= len(b) || !reflect.DeepEqual(a[i], b[i]) {
				t.Fatalf("seed 7 replayed differently at call %d of %d/%d: %v vs %v", i, len(a), len(b), a[i], b[min(i, len(b)-1)])
			}
		}
		t.Fatalf("seed 7 replayed %d calls then %d", len(a), len(b))
	}
	if reflect.DeepEqual(a, other) {
		t.Fatal("control: seeds 7 and 8 made the same calls")
	}
}

// A humanized click moves along a path and presses inside the element.
func TestHumanizePageClickLandsOnTheElement(t *testing.T) {
	ctx := ctxT(t)
	p, fb := newHumanizePage(t, &Humanize{Seed: u64(1)}, "macos")
	virtualClock(p)
	if err := p.Click(ctx, "#a"); err != nil {
		t.Fatal(err)
	}
	var moves int
	var down, up fakeCall
	for _, c := range fb.inputs() {
		switch c.Params["type"] {
		case "mousemove":
			moves++
		case "mousedown":
			down = c
		case "mouseup":
			up = c
		}
	}
	if moves < 5 {
		t.Errorf("%d mousemove events; a path has many", moves)
	}
	x, y := down.Params["x"].(float64), down.Params["y"].(float64)
	if x < 100 || x > 150 || y < 100 || y > 120 {
		t.Errorf("pressed at (%v, %v), outside the element box (100,100,50,20)", x, y)
	}
	if down.Params["clickCount"] != 1.0 || up.Params["clickCount"] != 1.0 || down.Params["buttons"] != 1.0 || up.Params["buttons"] != 0.0 {
		t.Errorf("down %v, up %v", down.Params, up.Params)
	}
	// The page was measured with the scroll plan and the hit test of myuri.
	var plans, hits int
	for _, c := range fb.recorded() {
		if c.Method != "Runtime.callFunction" {
			continue
		}
		decl := c.Params["functionDeclaration"].(string)
		switch {
		case strings.Contains(decl, "finishPosition"):
			plans++
		case strings.Contains(decl, "intercepts pointer events"):
			hits++
		}
	}
	if plans == 0 || hits == 0 {
		t.Errorf("the page was asked for %d scroll plans and %d hit tests", plans, hits)
	}
}

// Keyboard.Type is keystrokes when myuri drives the keyboard, one insertText when raw.
func TestHumanizeKeyboardChannel(t *testing.T) {
	ctx := ctxT(t)
	for name, tc := range map[string]struct {
		h    *Humanize
		keys bool
	}{
		"myuri": {&Humanize{Seed: u64(3)}, true},
		"raw":   {&Humanize{Seed: u64(3), Keyboard: &Engine{Name: "raw"}}, false},
	} {
		p, fb := newHumanizePage(t, tc.h, "linux")
		virtualClock(p)
		if err := p.Keyboard().Type(ctx, "hello"); err != nil {
			t.Fatalf("%s: %v", name, err)
		}
		var keydowns, inserts int
		for _, c := range fb.inputs() {
			switch {
			case c.Params["type"] == "keydown":
				keydowns++
			case c.Method == "Page.insertText":
				inserts++
			}
		}
		if tc.keys && keydowns < 5 || !tc.keys && (keydowns != 0 || inserts != 1) {
			t.Errorf("%s: %d keydowns and %d insertText for \"hello\"", name, keydowns, inserts)
		}
	}
}

// Mouse.Wheel turns at the point the caller names: a myuri mouse is moved there
// first, a raw one is not moved.
func TestHumanizeWheelAtTheGivenPoint(t *testing.T) {
	for name, tc := range map[string]struct {
		h     *Humanize
		moves bool
	}{
		"myuri mouse": {&Humanize{Seed: u64(5)}, true},
		"raw mouse":   {&Humanize{Seed: u64(5), Mouse: &Engine{Name: "raw"}}, false},
	} {
		p, fb := newHumanizePage(t, tc.h, "linux")
		virtualClock(p)
		if err := p.Mouse().Wheel(ctxT(t), 640, 360, 0, 300); err != nil {
			t.Fatalf("%s: %v", name, err)
		}
		var total float64
		var moves int
		var last fakeCall
		for _, c := range fb.inputs() {
			switch c.Method {
			case "Page.dispatchMouseEvent":
				moves++
				last = c
			case "Page.dispatchWheelEvent":
				if c.Params["x"] != 640.0 || c.Params["y"] != 360.0 {
					t.Fatalf("%s: wheel at (%v, %v), want (640, 360)", name, c.Params["x"], c.Params["y"])
				}
				total += c.Params["deltaY"].(float64)
			}
		}
		if total != 300 {
			t.Errorf("%s: the notches add up to %v, want 300", name, total)
		}
		if tc.moves && (moves < 3 || last.Params["x"] != 640.0 || last.Params["y"] != 360.0) {
			t.Errorf("%s: %d moves ending at %v, want a path to (640, 360)", name, moves, last.Params)
		}
		if !tc.moves && moves != 0 {
			t.Errorf("%s: a raw mouse was moved %d times", name, moves)
		}
	}
}

// A click that fails with a modifier held lets the modifier go.
func TestHumanizeReleasesModifiersOnFailure(t *testing.T) {
	p, fb := newHumanizePage(t, &Humanize{Seed: u64(2)}, "linux")
	virtualClock(p)
	fb.fail = map[string]string{"Page.dispatchMouseEvent/mousedown": "boom"}
	err := p.Mouse().Click(ctxT(t), 50, 50, WithMouseModifiers(4))
	if err == nil || !strings.Contains(err.Error(), "boom") {
		t.Fatalf("Click error = %v, want the failed press", err)
	}
	var shift []string
	for _, c := range fb.inputs() {
		if c.Method == "Page.dispatchKeyEvent" && c.Params["key"] == "Shift" {
			shift = append(shift, c.Params["type"].(string))
		}
	}
	if !reflect.DeepEqual(shift, []string{"keydown", "keyup"}) {
		t.Fatalf("Shift events %v, want a keydown then the keyup that releases it", shift)
	}
}
