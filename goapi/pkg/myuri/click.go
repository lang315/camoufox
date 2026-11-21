package myuri

import (
	"context"
	"errors"
	"math"
)

// Mouse-button timing (motion/click-model.ts): lognormals in ms fitted to
// recordings of people clicking in Firefox, mu at the log median.
type lognormalSpec struct{ mu, sd, lo, hi float64 }

var (
	holdFirst  = lognormalSpec{4.533, 0.21, 35, 400}  // pointerdown -> pointerup
	holdLater  = lognormalSpec{4.419, 0.227, 35, 400} // a later press of a run
	preClick   = lognormalSpec{3.717, 1.341, 4, 600}  // last pointermove -> pointerdown
	multiClick = lognormalSpec{4.353, 0.113, 30, 250} // pointerup -> next pointerdown
)

func (s lognormalSpec) draw(rng RNG) float64 {
	return jsRound(math.Max(s.lo, math.Min(s.hi, math.Exp(gaussian(rng, s.mu, s.sd)))))
}

// clickRunMS: the OS counts a press within this long of the last one, in place,
// into the same run (Windows' and macOS's double-click time).
const clickRunMS = 500

type press struct{ down, up float64 }

// clicksWith plans clicks first..last of a multi-click. lead is the wait before
// the first press: the dwell after the last move for click 1, the gap since the
// previous release otherwise.
func clicksWith(rng RNG, first, last int) (lead float64, presses []press) {
	if first == 1 {
		lead = preClick.draw(rng)
	}
	at := 0.0
	for count := first; count <= last; count++ {
		if count > 1 {
			gap := multiClick.draw(rng)
			if count == first {
				lead = gap
			} else {
				at += gap
			}
		}
		hold := holdFirst
		if count > 1 {
			hold = holdLater
		}
		up := at + hold.draw(rng)
		presses = append(presses, press{at, up})
		at = up
	}
	return lead, presses
}

// planClick plans a click, double click (clickCount 2) or triple click (3).
// sinceRelease is the ms since the last release, or negative for none.
func planClick(rng RNG, clickCount int, sinceRelease float64, hasSince bool) (dwell float64, presses []press) {
	if hasSince && sinceRelease < clickRunMS {
		lead, p := clicksWith(rng, 2, clickCount+1)
		return math.Max(0, lead-sinceRelease), p
	}
	lead, p := clicksWith(rng, 1, clickCount)
	if hasSince {
		return 0, p
	}
	return lead, p
}

// Press presses where the cursor is, clickCount times, holding modifiers.
func (a *Actions) Press(ctx context.Context, button string, clickCount int, modifiers []string) error {
	for _, key := range modifiers {
		if err := a.host.KeyDown(ctx, key); err != nil {
			return err
		}
	}
	if err := a.press(ctx, button, clickCount); err != nil {
		return err
	}
	a.releasedAt = a.host.Now()
	for i := len(modifiers) - 1; i >= 0; i-- {
		if err := a.host.KeyUp(ctx, modifiers[i]); err != nil {
			return err
		}
	}
	return nil
}

func (a *Actions) press(ctx context.Context, button string, clickCount int) error {
	now := a.host.Now()
	resting := a.movedAt < a.releasedAt
	since := now - a.releasedAt
	dwell, presses := planClick(a.rng, clickCount, since, resting)
	wait := a.movedAt + dwell - now
	if resting {
		wait = dwell
	}
	if err := a.wait(ctx, wait); err != nil {
		return err
	}
	// A press continuing a run is the run's next click.
	first := 1
	if resting && since < clickRunMS {
		first = 2
	}
	for i, p := range presses {
		if i > 0 {
			if err := a.wait(ctx, p.down-presses[i-1].up); err != nil {
				return err
			}
		}
		if err := a.host.Click(ctx, button, first+i, p.up-p.down); err != nil {
			return err
		}
	}
	return nil
}

// ClickAt moves to (x, y) and presses there.
func (a *Actions) ClickAt(ctx context.Context, x, y float64, button string, clickCount int) error {
	if err := a.Move(ctx, x, y); err != nil {
		return err
	}
	return a.Press(ctx, button, clickCount, nil)
}

// ClickOptions are the options of Click; the zero value is a plain left click.
type ClickOptions struct {
	Button     string   // "left" (default), "right" or "middle"
	ClickCount int      // 1 (default), 2 or 3
	Modifiers  []string // keys held for the press
	Position   *Point   // a point inside the element, from its padding-box corner; default: chosen in its visible part
	Force      bool     // press without checking that the press reaches the element
	Hover      bool     // move onto the element but do not press
	Timeout    float64  // ms to keep trying after a miss; 0 is no timeout
	Attempts   int      // tries; 0 is unlimited
}

// retryMS are the waits between attempts at a click, as Playwright waits
// between attempts at an action.
var retryMS = [...]float64{0, 20, 100, 100, 500}

// Click scrolls target into view, moves onto it and presses. Without a
// position, the point is chosen in the element's visible part. Unless Force,
// the press must reach the element. A miss is tried again until Attempts tries
// or Timeout ms, then returns a *Missed.
func (a *Actions) Click(ctx context.Context, target Target, o ClickOptions) error {
	if o.Button == "" {
		o.Button = "left"
	}
	if o.ClickCount == 0 {
		o.ClickCount = 1
	}
	deadline := math.Inf(1)
	if o.Timeout != 0 {
		deadline = a.host.Now() + o.Timeout
	}
	for attempt := 0; ; attempt++ {
		err := a.clickOnce(ctx, target, o, attempt)
		var missed *Missed
		if err == nil || !errors.As(err, &missed) || (o.Attempts > 0 && attempt+1 >= o.Attempts) || a.host.Now() >= deadline {
			return err
		}
		if err := a.wait(ctx, retryMS[min(attempt, len(retryMS)-1)]); err != nil {
			return err
		}
	}
}

func (a *Actions) clickOnce(ctx context.Context, target Target, o ClickOptions, attempt int) error {
	if err := a.IntoView(ctx, target); err != nil {
		return err
	}
	plan, err := a.measure(ctx, target)
	if err != nil {
		return err
	}
	if plan == nil {
		return &Missed{"element is not visible"}
	}
	var p Point
	switch {
	case o.Position != nil:
		p = Point{plan.Box.X + plan.Borders[0] + o.Position.X, plan.Box.Y + plan.Borders[1] + o.Position.Y}
	case plan.Region == nil:
		return &Missed{"element is outside of the viewport or covered"}
	default:
		if p, err = a.point(ctx, *plan.Region, attempt); err != nil {
			return err
		}
	}
	if err := a.Move(ctx, p.X, p.Y); err != nil {
		return err
	}
	if !o.Force {
		at := p
		if a.placed {
			at = a.cursor
		}
		reason, err := a.reaches(ctx, target, at, !o.Hover)
		if err != nil {
			return err
		}
		if reason != "" {
			return &Missed{reason}
		}
	}
	if o.Hover {
		return nil
	}
	return a.Press(ctx, o.Button, o.ClickCount, o.Modifiers)
}

// reaches is why a press at p would miss target, or "" when it lands on it.
func (a *Actions) reaches(ctx context.Context, target Target, p Point, pressing bool) (string, error) {
	dx, dy, ok, err := target.Offset(ctx)
	if err != nil {
		return "", err
	}
	if !ok {
		return "element is not visible", nil
	}
	return target.HitTest(ctx, p.X-dx, p.Y-dy, pressing)
}

// point chooses where in box to press. A later attempt aims somewhere new, not
// again where the last one missed.
func (a *Actions) point(ctx context.Context, box Box, attempt int) (Point, error) {
	here, err := a.here(ctx)
	if err != nil {
		return Point{}, err
	}
	// A pointer already on the box presses where it is.
	if attempt == 0 && pointInBox(here, box) {
		return here, nil
	}
	return randomBoxPoint(box, &here, a.rng), nil
}
