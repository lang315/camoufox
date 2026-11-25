package camoufox

import (
	"context"
	"encoding/json"
	"fmt"
	"math"
	"os"
	"strings"
	"testing"
)

// The default-parts scenario of python/tests/test_humanize_playwright.py, on the
// same page layout: myuri's own parts on every channel, seed 1234, its waits on a
// virtual clock. The Python and TypeScript launchers play it too, against
// browser/tests/humanize/sequence-default.json.
func TestHumanizeDefaultScenarioMatchesTheSharedSequence(t *testing.T) {
	const width, height = 1000.0, 700.0
	layout := map[string][4]float64{"#far": {100, 1600, 80, 30}, "#near": {500, 300, 50, 20}}
	seed := uint64(1234)
	p, fb := newHumanizePage(t, &Humanize{Seed: &seed}, "linux")
	scrollY := 0.0
	fb.override = func(method string, params map[string]any) (string, bool) {
		switch method {
		case "Page.dispatchWheelEvent":
			scrollY += params["deltaY"].(float64)
		case "Runtime.evaluate":
			if strings.Contains(params["expression"].(string), "innerWidth") {
				return fmt.Sprintf(`{"result":{"value":[%v,%v]}}`, width, height), true
			}
		case "Runtime.callFunction":
			args, _ := params["args"].([]any)
			if strings.Contains(params["functionDeclaration"].(string), "document.querySelector(sel)") {
				for _, a := range args {
					if sel, ok := a.(map[string]any)["value"].(string); ok && layout[sel] != [4]float64{} {
						return fmt.Sprintf(`{"result":{"type":"object","subtype":"node","objectId":%q}}`, sel), true
					}
				}
			}
			if len(args) != 2 {
				break
			}
			arg, _ := args[1].(map[string]any)["value"].(map[string]any)
			finish, ok := arg["finishPosition"].(float64)
			if !ok {
				break
			}
			// The scroll plan the Python fake answers: the box in the viewport after the wheel's scroll.
			b := layout[args[0].(map[string]any)["objectId"].(string)]
			x, y, w, h := b[0], b[1]-scrollY, b[2], b[3]
			region := "null"
			if top, bottom := math.Max(y, 0), math.Min(y+h, height); bottom > top {
				region = fmt.Sprintf(`{"x":%v,"y":%v,"width":%v,"height":%v}`, x, top, w, bottom-top)
			}
			return fmt.Sprintf(`{"result":{"value":{"inView":%v,"deltaY":%v,"hoverX":%v,"hoverY":%v,"isPage":true,`+
				`"region":%s,"box":{"x":%v,"y":%v,"width":%v,"height":%v},"borders":[2,3]}}}`,
				y >= 0 && y+h <= height, y+h/2-height*finish, width/2, height/2, region, x, y, w, h), true
		}
		return "", false
	}
	virtualClock(p)
	host := p.humanizer().host
	sleep := host.sleepFn
	host.sleepFn = func(ctx context.Context, ms float64) error {
		fb.mu.Lock()
		fb.calls = append(fb.calls, fakeCall{"sleep", map[string]any{"ms": ms}})
		fb.mu.Unlock()
		return sleep(ctx, ms)
	}

	ctx := ctxT(t)
	steps := []func() error{
		func() error { return p.Mouse().Move(ctx, 300, 200) },
		func() error { return p.Mouse().Wheel(ctx, 300, 200, 0, 480) },
		func() error { return p.Click(ctx, "#far") },
		// goapi has no Page.Hover.
		func() error { return p.withElement(ctx, "Hover", "#near", (*ElementHandle).Hover) },
		func() error { return p.Keyboard().Type(ctx, "Hi") },
		func() error { return p.Keyboard().Press(ctx, "Enter") },
		func() error { return p.Mouse().Click(ctx, 10, 20) },
		func() error { return p.Click(ctx, "#near") },
	}
	for i, step := range steps {
		if err := step(); err != nil {
			t.Fatalf("step %d: %v", i, err)
		}
	}

	// The input calls as the Python fake records Playwright's.
	button := map[float64]string{0: "left", 1: "middle", 2: "right"}
	var got [][]any
	for _, c := range fb.recorded() {
		typ, _ := c.Params["type"].(string)
		switch {
		case c.Method == "sleep":
			got = append(got, []any{"sleep", c.Params["ms"]})
		case c.Method == "Page.dispatchMouseEvent" && typ == "mousemove":
			got = append(got, []any{"mouse.move", c.Params["x"], c.Params["y"]})
		case c.Method == "Page.dispatchMouseEvent":
			got = append(got, []any{"mouse." + strings.TrimPrefix(typ, "mouse"), button[c.Params["button"].(float64)], c.Params["clickCount"]})
		case c.Method == "Page.dispatchWheelEvent":
			got = append(got, []any{"mouse.wheel", c.Params["deltaX"], c.Params["deltaY"]})
		case c.Method == "Page.dispatchKeyEvent":
			got = append(got, []any{"keyboard." + strings.TrimPrefix(typ, "key"), c.Params["key"]})
		case strings.HasPrefix(c.Method, "Page.dispatch") || c.Method == "Page.insertText" || c.Method == "Page.scrollIntoViewIfNeeded":
			t.Fatalf("unmapped input call %s", sig(c))
		}
	}

	raw, err := os.ReadFile("../browser/tests/humanize/sequence-default.json")
	if err != nil {
		t.Fatal(err)
	}
	var want struct{ Events [][]any }
	if err := json.Unmarshal(raw, &want); err != nil {
		t.Fatal(err)
	}
	for i := 0; i < len(got) && i < len(want.Events); i++ {
		if !sameEvent(got[i], want.Events[i]) {
			t.Fatalf("event %d: got %v, want %v", i, got[i], want.Events[i])
		}
	}
	if len(got) != len(want.Events) {
		t.Fatalf("%d events, want %d", len(got), len(want.Events))
	}
}

// sameEvent is equality with numbers to 1e-9 relative: Python, JavaScript and Go round some math in the last bit.
func sameEvent(got, want []any) bool {
	if len(got) != len(want) {
		return false
	}
	for i := range got {
		g, gok := got[i].(float64)
		w, wok := want[i].(float64)
		if gok && wok {
			if math.Abs(g-w) > 1e-9*math.Max(1, math.Abs(w)) {
				return false
			}
		} else if got[i] != want[i] {
			return false
		}
	}
	return true
}
