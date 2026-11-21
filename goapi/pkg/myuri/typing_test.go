package myuri

import (
	"context"
	"testing"
)

// Type's wpm argument is the typist's speed, as Options.WPM is.
func TestTypeWPMArgument(t *testing.T) {
	run := func(opts Options, wpm float64) [][]any {
		r := &recorder{g: &golden{Viewport: [2]float64{1280, 720}}, seen: map[string]int{}}
		if err := New(r, opts).Type(context.Background(), "speed check", wpm); err != nil {
			t.Fatal(err)
		}
		return r.calls
	}
	viaOption, viaArg := run(Options{OS: "linux", Seed: 3, WPM: 40}, 0), run(Options{OS: "linux", Seed: 3}, 40)
	if len(viaOption) == 0 || len(viaOption) != len(viaArg) {
		t.Fatalf("%d calls via Options.WPM, %d via the argument", len(viaOption), len(viaArg))
	}
	for i := range viaOption {
		if !sameCall(viaOption[i], viaArg[i]) {
			t.Fatalf("call %d: %v vs %v", i, viaOption[i], viaArg[i])
		}
	}
	// The control: the default speed must plan something different.
	def := run(Options{OS: "linux", Seed: 3}, 0)
	differs := len(def) != len(viaArg)
	for i := 0; !differs && i < len(def); i++ {
		differs = !sameCall(def[i], viaArg[i])
	}
	if !differs {
		t.Fatal("wpm 40 and the default 80 planned the same keys")
	}
}

func TestTypeEmptyText(t *testing.T) {
	if err := New(&recorder{}, Options{OS: "linux"}).Type(context.Background(), "", 0); err == nil {
		t.Fatal("empty text typed without error")
	}
}
