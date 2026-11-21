package myuri

import (
	"context"
	"errors"
	"testing"
)

func newRecorder() *recorder {
	return &recorder{g: &golden{Viewport: [2]float64{1280, 720}}, seen: map[string]int{}}
}

// Options.RawMove sends a move as the one event it asks for, with no path and no clamp.
func TestRawMoveIsOneEvent(t *testing.T) {
	r := newRecorder()
	if err := New(r, Options{OS: "linux", RawMove: true}).Move(context.Background(), 5000.5, -3); err != nil {
		t.Fatal(err)
	}
	if len(r.calls) != 1 || !sameCall(r.calls[0], []any{"move", 5000.5, -3.0}) {
		t.Fatalf("calls = %v, want one move to (5000.5, -3)", r.calls)
	}
	// The control: the default is a path, clamped to the viewport.
	d := newRecorder()
	if err := New(d, Options{OS: "linux"}).Move(context.Background(), 5000.5, -3); err != nil {
		t.Fatal(err)
	}
	if len(d.calls) < 3 {
		t.Fatalf("a default move made %d calls, want a path", len(d.calls))
	}
}

type unmeasurable struct{}

func (unmeasurable) Offset(context.Context) (float64, float64, bool, error) { return 0, 0, true, nil }
func (unmeasurable) Plan(context.Context, PlanArgs) (*ScrollPlan, error) {
	return nil, errors.New("the wheel scroll measured the page")
}
func (unmeasurable) HitTest(context.Context, float64, float64, bool) (string, error) { return "", nil }

// Options.IntoView replaces the wheel scroll, so the page is never measured for it.
func TestIntoViewOption(t *testing.T) {
	called := 0
	opts := Options{OS: "linux", IntoView: func(context.Context, Target) error { called++; return nil }}
	if err := New(newRecorder(), opts).IntoView(context.Background(), unmeasurable{}); err != nil || called != 1 {
		t.Fatalf("IntoView: err=%v, replaced %d times", err, called)
	}
	if err := New(newRecorder(), Options{OS: "linux"}).IntoView(context.Background(), unmeasurable{}); err == nil {
		t.Fatal("control: the default scroll did not measure the target")
	}
}
