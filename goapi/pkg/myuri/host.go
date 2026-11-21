// Package myuri is a Go port of the myuri 4.0.0 human-input library
// (@jwriter20/myuri) on cursory-js 2.1.0: the timing and motion of the mouse
// and the wheel, and the decisions around a click. For one seed and one
// sequence of calls it asks its Host for the same events, at the same times, as
// the TypeScript library does (see testdata/gen). The licence is in LICENSE and
// the notice in NOTICE.
package myuri

import (
	"context"
	"fmt"
	"math"
)

// Host sends each event the way its browser takes it, and reads the page. It is
// myuri's host contract (the Python glue's _Host); Wheel does not wait for the
// page, so a host may send it without waiting.
type Host interface {
	Move(ctx context.Context, x, y float64) error
	// Click presses and releases once, holding holdMS between, as click number clickCount of a run.
	Click(ctx context.Context, button string, clickCount int, holdMS float64) error
	Down(ctx context.Context, button string) error
	Up(ctx context.Context, button string) error
	Wheel(ctx context.Context, dx, dy float64) error
	KeyDown(ctx context.Context, key string) error
	KeyUp(ctx context.Context, key string) error
	InsertText(ctx context.Context, text string) error
	// Viewport is the size of the top page's viewport.
	Viewport(ctx context.Context) (w, h float64, err error)
	// Now is a monotonic clock in milliseconds.
	Now() float64
	Sleep(ctx context.Context, ms float64) error
}

// Options configure Actions. OS is the OS the browser claims ("macos", "windows"
// or "linux"); Seed seeds the stream every draw comes from, taken mod 2^32; WPM
// is the typing speed (0: 80).
type Options struct {
	OS   string
	Seed uint64
	WPM  float64
	// RNG, when set, is the stream every draw comes from, instead of one made from Seed:
	// actions on several pages draw from one stream, which the caller must make safe for
	// concurrent use.
	RNG RNG
	// IntoView replaces the wheel scroll into view, as a part of the JS Actions does (a raw scroll channel).
	IntoView func(ctx context.Context, target Target) error
	// RawMove makes every move one event at its point, with no path and no clamping, as a raw mouse channel does.
	RawMove bool
}

// Missed is a click that could not reach its element; Reason says why.
type Missed struct{ Reason string }

func (m *Missed) Error() string { return m.Reason }

// Actions is the smart actions on one host, for a person with a mouse on the OS
// the browser claims. It is not safe for concurrent use.
type Actions struct {
	host Host
	rng  RNG
	os   string
	wpm  float64

	intoView func(ctx context.Context, target Target) error
	rawMove  bool

	// Where the cursor is, in page px; unset until known. Before the first move
	// it is only where the person's hand is taken to be.
	cursor    Point
	hasCursor bool
	// placed is whether a move has put the cursor there, as opposed to a guess.
	placed              bool
	movedAt, releasedAt float64
}

// New returns the actions on host. It panics on an OS it does not know, as
// myuri throws: that is a caller's bug, not a runtime condition.
func New(host Host, opts Options) *Actions {
	switch opts.OS {
	case "macos", "windows", "linux":
	default:
		panic(fmt.Sprintf("myuri: unknown os %q; use 'macos', 'windows' or 'linux'", opts.OS))
	}
	wpm := opts.WPM
	if wpm == 0 {
		wpm = defaultWPM
	}
	rng := opts.RNG
	if rng == nil {
		rng = MakeRNG(opts.Seed)
	}
	return &Actions{host: host, rng: rng, os: opts.OS, wpm: wpm, intoView: opts.IntoView, rawMove: opts.RawMove, movedAt: math.Inf(-1), releasedAt: math.Inf(-1)}
}
