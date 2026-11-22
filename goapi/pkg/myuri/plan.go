package myuri

import (
	"context"
	"fmt"
	"math"
)

// StepKind is the kind of one step of a timeline.
type StepKind string

const (
	StepMove  StepKind = "move"  // X, Y
	StepDown  StepKind = "down"  // Name: the button
	StepUp    StepKind = "up"    // Name: the button
	StepWheel StepKind = "wheel" // X, Y: the deltas
	StepKey   StepKind = "key"   // Name: the key, Down: pressed or released
	StepText  StepKind = "text"  // Name: the text
)

// Step is one event of a timeline, T ms from its start.
type Step struct {
	Kind StepKind
	X, Y float64
	Name string
	Down bool
	T    float64
}

// validate names the first bad step of a timeline: nothing is played unless every
// step is valid, so a half-played gesture never leaves a button held.
func validate(steps []Step) error {
	last := 0.0
	for i, s := range steps {
		bad := func(why string) error { return fmt.Errorf("myuri: play() step %d (%s): %s", i, s.Kind, why) }
		if math.IsNaN(s.T) || math.IsInf(s.T, 0) || s.T < 0 {
			return bad("t must be a finite number of milliseconds, at least 0")
		}
		if s.T < last {
			return bad(fmt.Sprintf("t goes back in time (%v after %v)", s.T, last))
		}
		last = s.T
		switch s.Kind {
		case StepMove, StepWheel:
			if math.IsNaN(s.X+s.Y) || math.IsInf(s.X+s.Y, 0) {
				return bad("takes finite numbers")
			}
		case StepDown, StepUp:
			if s.Name != "left" && s.Name != "right" && s.Name != "middle" {
				return bad("the button must be one of left, right, middle")
			}
		case StepKey:
			if s.Name == "" {
				return bad("a key needs a name")
			}
		case StepText:
		default:
			return bad("the kind must be move, down, up, wheel, key or text")
		}
	}
	return nil
}

// Play plays a timeline, each step at its time from the start; a late step delays only itself.
func (a *Actions) Play(ctx context.Context, steps []Step) error {
	if err := validate(steps); err != nil {
		return err
	}
	h := a.host
	start := h.Now()
	for _, s := range steps {
		// A timer may fire early, so wait until the step is due.
		for ms := start + s.T - h.Now(); ms > 0; ms = start + s.T - h.Now() {
			if err := h.Sleep(ctx, ms); err != nil {
				return err
			}
		}
		var err error
		switch s.Kind {
		case StepMove:
			if err = h.Move(ctx, s.X, s.Y); err == nil {
				a.Moved(s.X, s.Y)
			}
		case StepDown:
			err = h.Down(ctx, s.Name)
		case StepUp:
			if err = h.Up(ctx, s.Name); err == nil {
				a.releasedAt = h.Now()
			}
		case StepWheel:
			err = h.Wheel(ctx, s.X, s.Y)
		case StepKey:
			if s.Down {
				err = h.KeyDown(ctx, s.Name)
			} else {
				err = h.KeyUp(ctx, s.Name)
			}
		case StepText:
			err = h.InsertText(ctx, s.Name)
		}
		if err != nil {
			return err
		}
	}
	return nil
}

func (a *Actions) wait(ctx context.Context, ms float64) error {
	if ms > 0 {
		return a.host.Sleep(ctx, ms)
	}
	return nil
}
