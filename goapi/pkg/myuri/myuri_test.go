package myuri

import (
	"context"
	"encoding/json"
	"errors"
	"math"
	"os"
	"path/filepath"
	"testing"
)

// The goldens are the host calls @jwriter20/myuri 4.0.0 made for these scenarios
// (testdata/gen/gen.mjs). The port must issue the same calls, floats within 1e-9.
const tol = 1e-9

type golden struct {
	Versions   map[string]string `json:"versions"`
	Viewport   [2]float64        `json:"viewport"`
	ClockStart float64           `json:"clockStart"`
	Cases      []goldenCase      `json:"cases"`
}

type goldenCase struct {
	Name    string                  `json:"name"`
	Seed    uint64                  `json:"seed"`
	OS      string                  `json:"os"`
	WPM     float64                 `json:"wpm"`
	Targets map[string]goldenTarget `json:"targets"`
	Ops     []goldenOp              `json:"ops"`
	Calls   [][]any                 `json:"calls"`
}

type goldenTarget struct {
	Offset *[2]float64   `json:"offset"`
	Plans  []*ScrollPlan `json:"plans"`
	Hits   []*string     `json:"hits"`
}

type goldenOp struct {
	Op        string   `json:"op"`
	X         float64  `json:"x"`
	Y         float64  `json:"y"`
	Dx        float64  `json:"dx"`
	Dy        float64  `json:"dy"`
	Button    string   `json:"button"`
	Count     int      `json:"count"`
	Modifiers []string `json:"modifiers"`
	Target    string   `json:"target"`
	Text      string   `json:"text"`
	Key       string   `json:"key"`
	Opts      struct {
		Button     string   `json:"button"`
		ClickCount int      `json:"clickCount"`
		Modifiers  []string `json:"modifiers"`
		Position   *Point   `json:"position"`
		Force      bool     `json:"force"`
		Press      *bool    `json:"press"`
		Timeout    float64  `json:"timeout"`
		Attempts   int      `json:"attempts"`
	} `json:"opts"`
}

// recorder is a Host and a set of Targets on a virtual clock: a sleep or a
// click's hold advances it by exactly its duration.
type recorder struct {
	g     *golden
	c     *goldenCase
	now   float64
	calls [][]any
	seen  map[string]int
}

func (r *recorder) add(call ...any) { r.calls = append(r.calls, call) }

func (r *recorder) Move(_ context.Context, x, y float64) error { r.add("move", x, y); return nil }
func (r *recorder) Click(_ context.Context, button string, count int, hold float64) error {
	r.add("click", button, float64(count), hold)
	r.now += hold
	return nil
}
func (r *recorder) Down(_ context.Context, b string) error { r.add("down", b); return nil }
func (r *recorder) Up(_ context.Context, b string) error   { r.add("up", b); return nil }
func (r *recorder) Wheel(_ context.Context, dx, dy float64) error {
	r.add("wheel", dx, dy)
	return nil
}
func (r *recorder) KeyDown(_ context.Context, k string) error { r.add("keyDown", k); return nil }
func (r *recorder) KeyUp(_ context.Context, k string) error   { r.add("keyUp", k); return nil }
func (r *recorder) InsertText(_ context.Context, t string) error {
	r.add("insertText", t)
	return nil
}
func (r *recorder) Viewport(context.Context) (float64, float64, error) {
	r.add("viewport")
	return r.g.Viewport[0], r.g.Viewport[1], nil
}
func (r *recorder) Now() float64 { return r.now }
func (r *recorder) Sleep(_ context.Context, ms float64) error {
	r.add("sleep", ms)
	r.now += ms
	return nil
}

// next returns the scripted answer for a call: the n-th, then the last one forever.
func (r *recorder) next(key string, length int) int {
	i := r.seen[key]
	r.seen[key] = i + 1
	return min(i, length-1)
}

type scripted struct {
	r    *recorder
	name string
	spec goldenTarget
}

func (t scripted) Offset(context.Context) (float64, float64, bool, error) {
	t.r.add("offset", t.name)
	if t.spec.Offset == nil {
		return 0, 0, false, nil
	}
	return t.spec.Offset[0], t.spec.Offset[1], true, nil
}

func (t scripted) Plan(_ context.Context, a PlanArgs) (*ScrollPlan, error) {
	t.r.add("plan", t.name, a.FromX, a.FromY, a.FinishPosition, a.Pad, a.Edge)
	p := t.spec.Plans[t.r.next(t.name+":plan", len(t.spec.Plans))]
	if p == nil {
		return nil, nil
	}
	c := *p
	return &c, nil
}

func (t scripted) HitTest(_ context.Context, x, y float64, pressing bool) (string, error) {
	t.r.add("hit", t.name, x, y, pressing)
	if h := t.spec.Hits[t.r.next(t.name+":hit", len(t.spec.Hits))]; h != nil {
		return *h, nil
	}
	return "", nil
}

func replay(t *testing.T, g *golden, c *goldenCase) [][]any {
	t.Helper()
	r := &recorder{g: g, c: c, now: g.ClockStart, seen: map[string]int{}}
	a := New(r, Options{OS: c.OS, Seed: c.Seed, WPM: c.WPM})
	ctx := context.Background()
	target := func(name string) Target { return scripted{r: r, name: name, spec: c.Targets[name]} }
	for _, op := range c.Ops {
		var err error
		switch op.Op {
		case "move":
			err = a.Move(ctx, op.X, op.Y)
		case "clickAt":
			err = a.ClickAt(ctx, op.X, op.Y, op.Button, op.Count)
		case "press":
			err = a.Press(ctx, op.Button, op.Count, op.Modifiers)
		case "wheel":
			err = a.Wheel(ctx, op.Dx, op.Dy)
		case "type":
			err = a.Type(ctx, op.Text, 0)
		case "key":
			err = a.Key(ctx, op.Key)
		case "intoView":
			err = a.IntoView(ctx, target(op.Target))
		case "click":
			o := op.Opts
			err = a.Click(ctx, target(op.Target), ClickOptions{
				Button: o.Button, ClickCount: o.ClickCount, Modifiers: o.Modifiers, Position: o.Position,
				Force: o.Force, Hover: o.Press != nil && !*o.Press, Timeout: o.Timeout, Attempts: o.Attempts,
			})
		default:
			t.Fatalf("unknown op %q", op.Op)
		}
		var missed *Missed
		if errors.As(err, &missed) {
			r.add("error", "Missed: "+missed.Reason)
		} else if err != nil {
			t.Fatalf("%s: %s: %v", c.Name, op.Op, err)
		}
	}
	return r.calls
}

func sameCall(want, got []any) bool {
	if len(want) != len(got) {
		return false
	}
	for i := range want {
		w, wf := want[i].(float64)
		g, gf := got[i].(float64)
		switch {
		case wf && gf:
			if math.Abs(w-g) > tol {
				return false
			}
		case want[i] != got[i]:
			return false
		}
	}
	return true
}

func runGolden(t *testing.T, file string, cases int) {
	raw, err := os.ReadFile(filepath.Join("testdata", file))
	if err != nil {
		t.Fatal(err)
	}
	var g golden
	if err := json.Unmarshal(raw, &g); err != nil {
		t.Fatal(err)
	}
	if g.Versions["myuri"] != "4.0.0" || g.Versions["cursory-js"] != "2.1.0" {
		t.Fatalf("golden recorded from %v, the port tracks myuri 4.0.0 on cursory-js 2.1.0", g.Versions)
	}
	if len(g.Cases) != cases {
		t.Fatalf("%d cases, want %d seeds", len(g.Cases), cases)
	}
	for i := range g.Cases {
		c := &g.Cases[i]
		t.Run(c.Name, func(t *testing.T) {
			got := replay(t, &g, c)
			for i := 0; i < len(c.Calls) && i < len(got); i++ {
				if !sameCall(c.Calls[i], got[i]) {
					t.Fatalf("call %d: want %v, got %v", i, c.Calls[i], got[i])
				}
			}
			if len(got) != len(c.Calls) {
				t.Fatalf("%d calls, want %d", len(got), len(c.Calls))
			}
		})
	}
}

func TestGoldenMouse(t *testing.T)  { runGolden(t, "mouse.json", 5) }
func TestGoldenScroll(t *testing.T) { runGolden(t, "scroll.json", 5) }
func TestGoldenTyping(t *testing.T) { runGolden(t, "typing.json", 3) }
func TestGoldenKey(t *testing.T)    { runGolden(t, "key.json", 3) }
